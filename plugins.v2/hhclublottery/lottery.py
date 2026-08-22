# -*- coding: utf-8 -*-
"""HHCLUB 幸运大转盘的抽奖核心。

这里刻意不 import 任何 MoviePilot 的东西 —— 站点交互和统计口径跟宿主没关系，
拆开之后可以脱离 MP 直接跑起来验证。宿主要用的日志、通知、落盘都从外面传进来。

统计结构和油猴版 / 青龙版的 v4 备份完全一致，所以 MP 这边导出来的 JSON
能被 hhanclub.net/lucky.php 面板上的「📥 导入备份」直接吃下去。
"""
import json
import math
import random
import re
import threading
import time
from datetime import datetime, timezone
from typing import Callable, Dict, List, Optional, Tuple

import requests

# ============================================================
# 运行参数（对应青龙版的 RUNTIME）
# ============================================================

RUNTIME = {
    # 连续失败不收摊，每 3 次把等待抬一档（×1.5），封顶 5 分钟。
    # 挂机是无人值守的，站点重启 / CDN 抽风时收摊等于整晚白过。
    "retry_step_every": 3,
    "retry_step_factor": 1.5,
    "max_retry_ms": 300000,
    # 站点报错 / HTTP 异常的重试基数
    "error_retry_ms": 1000,
    # 网络层错误（DNS 挂了、连接被重置）单独一档，基数更大 —— 站点报错说明连得上，
    # 网络断了纯粹是外部原因，贴着重试没意义
    "network_retry_ms": 10000,
    # 连续失败到这个数提醒一声（只提醒，不收摊）
    "stuck_warn_every": 10,
    # 单个幂等请求（读页面、删站内信）内部的网络重试
    "request_retries": 3,
    "request_retry_step_ms": 1000,
    # 被限流后的退避（关掉自适应时才走这套）
    "backoff_after": 3,
    "backoff_factor": 1.5,
    "max_backoff_ms": 30000,
    # 自适应模式还没拿到首个 duration 时的兜底间隔
    "blind_gap_ms": 5000,
    # 已知上一抽冷却时，被限流后快速补枪
    "rate_limit_retry_ms": 300,
    # 冷却剩余未知时放慢补枪，避免过早攒满连续限流次数
    "blind_retry_ms": 1000,
    # 读不到站点公布的折算金额时的兜底
    "vip_swap_fallback_beans": 1000000,
    # 判折算的主证据是余额：至少要多出公布金额的这个比例
    "vip_swap_min_drift_ratio": 0.5,
    # 等级读不到时要求余额变动贴着公布金额，宁可漏记也不乱记
    "vip_swap_tolerance": 20000,
    # 站内信一次提交多少个 id
    "mail_chunk": 100,
    "mail_max_pages": 600,
    "mail_sweep_rounds": 20,
    # 抽奖途中每多少抽顺手清一次（和油猴版节奏一致）
    "mail_clean_every_draws": 25,
    "lottery_mail_keyword": "幸运大转盘",
    # 单个 HTTP 请求超时
    "connect_timeout": 10,
    "read_timeout": 30,
}

DEFAULT_USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")

# ============================================================
# 小工具
# ============================================================


def fmt(value) -> str:
    """千分位，最多两位小数。和 JS 的 toLocaleString('en-US') 对齐。"""
    try:
        number = float(value or 0)
    except (TypeError, ValueError):
        return "0"
    if not math.isfinite(number):
        return "0"
    text = f"{number:,.2f}"
    if text.endswith(".00"):
        return text[:-3]
    if text.endswith("0"):
        return text[:-1]
    return text


def _tidy(number: float):
    """整数就存成整数。统计要落盘并被油猴版面板导入，
    满屏 2000.0 / 15.0 既难看也和浏览器那边存的对不齐。"""
    return int(number) if isinstance(number, float) and number.is_integer() else number


def first_number(text) -> Optional[float]:
    """取第一个数字，兼容 "1,000" 这种千分位写法。"""
    matched = re.search(r"(\d[\d,]*(?:\.\d+)?)", str(text or ""))
    return _tidy(float(matched.group(1).replace(",", ""))) if matched else None


def decode_unicode(text):
    """接口返回的中奖文案是 \\uXXXX 转义过的（JSON 解出来还留着一层）。"""
    if not isinstance(text, str):
        return text
    return re.sub(r"\\u([0-9a-fA-F]{4})", lambda m: chr(int(m.group(1), 16)), text)


def text_after_class(html: str, class_name: str, span: int = 400) -> Optional[str]:
    """没有 DOM，只能在 HTML 里按 class 取值：先定位 class 属性，跳到所在标签的
    '>' 之后，再把后面一小段的标签剥掉。比整段正则匹配耐改版。"""
    matched = re.search(r'class="[^"]*\b%s\b[^"]*"' % re.escape(class_name), html or "", re.I)
    if not matched:
        return None
    start = (html or "").find(">", matched.start())
    if start < 0:
        return None
    return re.sub(r"<[^>]*>", " ", html[start + 1: start + 1 + span])


def number_after_class(html: str, class_name: str) -> Optional[float]:
    return first_number(text_after_class(html, class_name))


def format_duration(ms: float) -> str:
    total = max(0, round(ms / 1000))
    hours, rest = divmod(int(total), 3600)
    minutes, seconds = divmod(rest, 60)
    if hours:
        return f"{hours}小时 {minutes}分"
    if minutes:
        return f"{minutes}分 {seconds}秒"
    return f"{seconds}秒"


def step_backoff_ms(streak: int, base_ms: float) -> int:
    """连续失败第 streak 次该等多久。每 retry_step_every 次抬一档：
    基数 1 秒时是 1 1 1 · 1.5 1.5 1.5 · 2.25 …，封顶 max_retry_ms。"""
    step = max(0, streak - 1) // RUNTIME["retry_step_every"]
    return int(min(RUNTIME["max_retry_ms"], round(base_ms * (RUNTIME["retry_step_factor"] ** step))))


def interval_text(seconds: float) -> str:
    return f"{round(seconds, 2):g}"


# ============================================================
# 奖品解析（和油猴版 / 青龙版同一套规则）
# ============================================================

# 改这里之前想两件事：
#   ① unit 会进 parse_prize_text 拼出来的 label，而 label 就是统计里档位的 key ——
#      改了单位，老档案里的档位和新抽的对不上，会分成两行；
#   ② 油猴版有一份一模一样的，两边共用备份文件，只改一边就花了。
PRIZE_META: Dict[str, Dict[str, str]] = {
    "beans": {"name": "憨豆", "icon": "💰", "unit": ""},
    "magic": {"name": "憨豆（旧魔力）", "icon": "💰", "unit": ""},
    "invite": {"name": "邀请", "icon": "📧", "unit": ""},
    "rainbow": {"name": "彩虹ID", "icon": "🌈", "unit": "天"},
    "vip": {"name": "VIP", "icon": "⭐", "unit": "天"},
    "makeup": {"name": "补签卡", "icon": "🎫", "unit": "个"},
    "upload": {"name": "上传量", "icon": "⬆️", "unit": "GB"},
    "rename": {"name": "改名卡", "icon": "📛", "unit": "张"},
    "unknown": {"name": "其他奖品", "icon": "🎁", "unit": ""},
}

# 站点奖池里 type 1001 的 typeText 写作「魔力」，但图标是 bean_icon、消耗侧也叫憨豆
# —— 同一种货币，NexusPHP 的默认叫法没改干净，归到同一类盈亏才算得对。
_PRIZE_RULES: List[Tuple[str, Callable[[str], bool]]] = [
    ("beans", lambda t: "魔力" in t or "憨豆" in t),
    ("invite", lambda t: "邀请" in t),
    ("rainbow", lambda t: "彩虹" in t),
    ("vip", lambda t: bool(re.search(r"VIP", t, re.I))),
    ("makeup", lambda t: "补签" in t),
    ("upload", lambda t: "上传" in t),
    ("rename", lambda t: "改名" in t),
]


def parse_prize_text(text) -> Dict:
    compact = re.sub(r"\s+", " ", str(text or "").strip())
    fallback = {"type": "unknown", "value": 0, "label": compact or "未知奖品"}
    if not compact:
        return fallback

    for prize_type, test in _PRIZE_RULES:
        if not test(compact):
            continue
        meta = PRIZE_META[prize_type]

        if prize_type == "upload":
            matched = re.search(r"(\d[\d,]*(?:\.\d+)?)\s*(TB|GB|MB)", compact, re.I)
            if not matched:
                break
            value = float(matched.group(1).replace(",", ""))
            unit = matched.group(2).upper()
            if unit == "TB":
                value *= 1024
            if unit == "MB":
                value /= 1024
            value = _tidy(round(value * 100) / 100)
        else:
            value = first_number(compact)
            if value is None:
                break

        label = f"{fmt(value)}{' ' + meta['unit'] if meta['unit'] else ' ' + meta['name']}"
        return {"type": prize_type, "value": value, "label": label}

    return fallback


# 「VIP 或以上等级」说的是 NexusPHP 的 class 序号。站点能把等级名字改得面目全非
# （本站发布员叫「俺不中类」），但内核生成的 {ClassName}_Name 和图标文件名没改。
# peasant 是 0 —— H&R 不达标被降级的农民，挂机刷抽奖的号最容易掉进去，
# 表里没有它的话等级判定会退化成靠余额猜，给非 VIP 的号凭空记一百万。
CLASS_RANK = {
    "peasant": 0,
    "user": 1,
    "power": 2, "poweruser": 2,
    "elite": 3, "eliteuser": 3,
    "crazy": 4, "crazyuser": 4,
    "insane": 5, "insaneuser": 5,
    "veteran": 6, "veteranuser": 6,
    "extreme": 7, "extremeuser": 7,
    "ultimate": 8, "ultimateuser": 8,
    "nexusmaster": 9,
    "vip": 10,
    "retiree": 11,
    "uploader": 12,
    "moderator": 13,
    "coadministrator": 14, "administrator": 14,
    "sysop": 15,
    "staffleader": 16,
}


def parse_class_rank(html: str) -> Optional[int]:
    """读用户详情页里的等级序号。读不到返回 None —— 「没读到」和「不是 VIP」
    得分开，前者要退回余额差兜底，后者直接就能定。"""
    html = html or ""
    at = re.search(r"等级\s*[：:]", html)
    scope = html[at.start(): at.start() + 400] if at else html

    candidates = []
    by_class = re.search(r"class=['\"][^'\"]*?\b([A-Za-z]+)_Name\b", scope)
    if by_class:
        candidates.append(by_class.group(1))
    by_icon = re.search(r"pic/(\w+)\.(?:gif|png|svg|webp)", scope, re.I)
    if by_icon:
        candidates.append(by_icon.group(1))

    for name in candidates:
        rank = CLASS_RANK.get(name.lower())
        # 农民是 0，不能用真假判断，否则等于没读到
        if rank is not None:
            return rank
    return None


def parse_vip_swap_beans(html: str) -> int:
    """折算金额是站点明文印在抽奖页上的：
      「当中奖 [VIP] 时，如果用户已经是 VIP 或以上等级，奖励憨豆： 1000000」
    必须读它，不能拿余额差当金额 —— 憨豆会因为做种持续增长，两次读数之间涨的
    那几十点会被当成中奖收入（线上真出现过「1,000,060 憨豆」这种不存在的档位）。"""
    text = re.sub(r"\s+", " ", re.sub(r"<[^>]*>", " ", html or ""))
    matched = re.search(r"当中奖\s*\[?\s*VIP\s*\]?[^当]{0,80}?奖励憨豆[：:]\s*([\d,]+)", text, re.I)
    if not matched:
        return 0
    try:
        value = int(matched.group(1).replace(",", ""))
    except ValueError:
        return 0
    return value if value > 0 else 0


# ============================================================
# 统计（v4 结构，和油猴版备份格式一致）
# ============================================================

STATS_VERSION = 4
_GAIN_KEYS = ["beans", "magic", "invite", "rainbow", "vip", "makeup", "upload", "rename"]


def empty_stats() -> Dict:
    return {
        "version": STATS_VERSION,
        "draws": 0,
        "cost": 0,
        "gains": {key: 0 for key in _GAIN_KEYS},
        "prizes": {},
        "raw": {},
        # 记录线编号。这份统计本身就是油猴版能直接导入的备份，带上它，
        # 油猴版才认得出「同一份文件导了两遍」。
        "originId": None,
        "firstAt": None,
        "lastAt": None,
    }


def ensure_bucket(stats: Dict, prize_type: str) -> Dict:
    if prize_type not in stats["prizes"]:
        stats["prizes"][prize_type] = {"count": 0, "value": 0, "tiers": {}}
    return stats["prizes"][prize_type]


def _num(value) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0
    return _tidy(number) if math.isfinite(number) else 0


def normalize_stats(data) -> Dict:
    """读进来的可能是手改过的、或者早期版本存的，收一遍。
    早期版本把「魔力」当独立类别存过，这里合回 beans。"""
    stats = empty_stats()
    if not isinstance(data, dict):
        return stats

    stats["draws"] = _num(data.get("draws"))
    stats["cost"] = _num(data.get("cost"))
    stats["firstAt"] = data.get("firstAt")
    stats["lastAt"] = data.get("lastAt")

    gains = data.get("gains") or {}
    for key in _GAIN_KEYS:
        stats["gains"][key] = _num(gains.get(key))
    stats["gains"]["beans"] += _num(gains.get("magic"))
    stats["gains"]["magic"] = 0

    for prize_type, bucket in (data.get("prizes") or {}).items():
        bucket = bucket or {}
        merged = ensure_bucket(stats, "beans" if prize_type == "magic" else prize_type)
        merged["count"] += _num(bucket.get("count"))
        merged["value"] += _num(bucket.get("value"))
        swapped = _num(bucket.get("swappedBeans"))
        if swapped:
            merged["swappedBeans"] = _num(merged.get("swappedBeans")) + swapped
        for label, count in (bucket.get("tiers") or {}).items():
            merged["tiers"][label] = _num(merged["tiers"].get(label)) + _num(count)

    stats["raw"] = dict(data.get("raw") or {})
    stats["originId"] = data["originId"] if isinstance(data.get("originId"), str) else None

    # 大奖名册和导入台账是油猴版那边的东西，这边既不产生也不读 —— 但这份统计
    # 是双向的：真有人会把油猴版的备份导进 MP 让它接着记。原样带过去，
    # 别下次覆写就把人家攒了几个月的名册抹了。
    if isinstance(data.get("jackpots"), list):
        stats["jackpots"] = data["jackpots"]
    if isinstance(data.get("imports"), list):
        stats["imports"] = data["imports"]

    return stats


def apply_prize(stats: Dict, prize_text: str, cost: float, prize: Dict):
    stats["draws"] += 1
    stats["cost"] += cost

    if prize["type"] != "unknown":
        stats["gains"][prize["type"]] = _num(stats["gains"].get(prize["type"])) + prize["value"]

    bucket = ensure_bucket(stats, prize["type"])
    bucket["count"] += 1
    bucket["value"] += prize["value"]
    bucket["tiers"][prize["label"]] = _num(bucket["tiers"].get(prize["label"])) + 1

    # 接口返回的文案常带尾随空格，不 strip 的话同一个奖会留下两条 key
    raw_key = str(prize_text).strip()
    stats["raw"][raw_key] = _num(stats["raw"].get(raw_key)) + 1

    stats["lastAt"] = int(time.time() * 1000)
    if not stats["firstAt"]:
        stats["firstAt"] = stats["lastAt"]


def mark_vip_swapped(stats: Dict, prize: Dict, beans: float):
    """把刚记下的那一注 VIP 改标成「已转换为憨豆」。

    这一注仍然算在 VIP 类别里 —— 转盘确实停在 VIP 那一格，中奖次数和爆率统计
    不该少这一笔。变的只有档位和收益归属：VIP 天数扣回去（没真拿到），憨豆收入
    加上但单独记在 swappedBeans（天数和憨豆不是一个单位，不能混进 value）。"""
    stats["gains"]["vip"] = _num(stats["gains"].get("vip")) - prize["value"]
    stats["gains"]["beans"] = _num(stats["gains"].get("beans")) + beans

    bucket = ensure_bucket(stats, "vip")
    bucket["value"] -= prize["value"]
    bucket["swappedBeans"] = _num(bucket.get("swappedBeans")) + beans
    bucket["tiers"][prize["label"]] = _num(bucket["tiers"].get(prize["label"])) - 1
    if bucket["tiers"][prize["label"]] <= 0:
        bucket["tiers"].pop(prize["label"], None)

    swapped_label = f"已转换为憨豆 {fmt(beans)}"
    bucket["tiers"][swapped_label] = _num(bucket["tiers"].get(swapped_label)) + 1


def swapped_beans_total(stats: Dict) -> float:
    """所有类别里被折算成憨豆的总额。目前只有 VIP 会产生，写成通用的。"""
    return sum(_num(bucket.get("swappedBeans")) for bucket in (stats.get("prizes") or {}).values())


def tidy_stats(stats: Dict) -> Dict:
    """把统计里所有整数值收回 int。加减法一路下来会把 int 带成 float，
    落盘和导出前收一遍，导出的备份才和油猴版存的长得一样。"""
    if isinstance(stats, dict):
        return {key: tidy_stats(value) for key, value in stats.items()}
    if isinstance(stats, list):
        return [tidy_stats(item) for item in stats]
    return _tidy(stats) if isinstance(stats, float) else stats


_BASE36 = "0123456789abcdefghijklmnopqrstuvwxyz"


def _base36(number: int) -> str:
    text = ""
    while number:
        number, rest = divmod(number, 36)
        text = _BASE36[rest] + text
    return text or "0"


def random_id() -> str:
    """和油猴版同款：8 位随机 + 4 位时间尾巴，都是 base36。"""
    return ("".join(random.choice(_BASE36) for _ in range(8))
            + _base36(int(time.time() * 1000))[-4:])


def stamp_origin(total: Dict) -> Dict:
    """头一次就把记录线编号定下来，之后每次导出都沿用同一个。
    一抽没抽过就导出时也得补上，不然这份备份带不走记录线。"""
    if not total.get("originId"):
        total["originId"] = random_id()
    return total


def backup_payload(current: Dict, total: Dict) -> Dict:
    """油猴版「📥 导入备份」认的格式。

    两个编号是给那边的「重复导入」把关用的：originId 认记录线（同一台 MP
    导出多少次都是同一个），exportId 认这一个文件（每导一次换一个）。
    老备份没有也照样能导，只是认不出重复。"""
    total = stamp_origin(total)
    return {
        "kind": "hhclub-lottery-backup",
        "version": STATS_VERSION,
        "exportedAt": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z"),
        "source": "moviepilot",
        "originId": total["originId"],
        "exportId": random_id(),
        "current": tidy_stats(current),
        "total": tidy_stats(total),
    }


# ============================================================
# 通知正文
# ============================================================


def format_prize_details(prizes: Dict) -> str:
    entries = sorted(
        [(t, b) for t, b in (prizes or {}).items() if b and _num(b.get("count")) > 0],
        key=lambda item: _num(item[1].get("count")), reverse=True
    )
    if not entries:
        return "  （暂无奖品）"

    lines = []
    for prize_type, bucket in entries:
        meta = PRIZE_META.get(prize_type, PRIZE_META["unknown"])
        unit_name = meta["unit"] or ("憨豆" if prize_type in ("beans", "magic") else meta["name"])
        sums = []
        if _num(bucket.get("value")) > 0:
            sums.append(f"{fmt(bucket['value'])} {unit_name}".strip())
        if _num(bucket.get("swappedBeans")) > 0:
            sums.append(f"另折算 {fmt(bucket['swappedBeans'])} 憨豆")

        head = f"  {meta['icon']} {meta['name']}｜{fmt(bucket.get('count'))} 次"
        if sums:
            head += " · " + " · ".join(sums)
        lines.append(head)

        for label, count in sorted((bucket.get("tiers") or {}).items(),
                                   key=lambda item: _num(item[1]), reverse=True):
            lines.append(f"     └ {label} × {fmt(count)}")
    return "\n".join(lines)


def gain_line(stats: Dict, sign: str = "") -> str:
    """折算来的憨豆不在憨豆档位里，不点这一句的话，拿各档位乘开去对
    「获得憨豆」会差出一大截，看着像 bug。"""
    swapped = swapped_beans_total(stats)
    line = f"  🎁 获得：{sign}{fmt(stats['gains'].get('beans'))} 憨豆"
    if swapped > 0:
        line += f"（其中 {fmt(swapped)} 来自 VIP 折算）"
    return line


def profit_of(stats: Dict) -> Tuple[float, float]:
    beans = _num(stats["gains"].get("beans"))
    profit = beans - _num(stats.get("cost"))
    rate = (profit / stats["cost"] * 100) if _num(stats.get("cost")) > 0 else 0
    return profit, rate


def _signed(value: float) -> str:
    return f"{'+' if value >= 0 else ''}{fmt(value)}"


# ============================================================
# 抽奖
# ============================================================


class LotteryOptions:
    """一次运行用到的全部参数。宿主把配置页的值塞进来即可。"""

    def __init__(self, **kwargs):
        self.host: str = kwargs.get("host") or "hhanclub.net"
        self.user_agent: str = kwargs.get("user_agent") or DEFAULT_USER_AGENT
        self.draws: int = int(kwargs.get("draws") or 0)
        self.reserve: float = float(kwargs.get("reserve") or 0)
        self.interval: float = float(kwargs.get("interval") or 6.8)
        self.follow_duration: bool = bool(kwargs.get("follow_duration", True))
        self.duration_buffer_ms: int = int(kwargs.get("duration_buffer_ms") or 0)
        self.max_minutes: float = float(kwargs.get("max_minutes") or 60)
        self.clean_mail: bool = bool(kwargs.get("clean_mail"))
        self.notify_big_prize: bool = bool(kwargs.get("notify_big_prize", True))
        self.big_prize_min_beans: float = float(kwargs.get("big_prize_min_beans") or 0)
        # 两个停止条件独立开关，都默认关。和上面的通知门槛互不影响 ——
        # 通知想宽松点、停机想严格点，本来就是两回事。
        self.stop_on_vip: bool = bool(kwargs.get("stop_on_vip"))
        self.stop_on_780k: bool = bool(kwargs.get("stop_on_780k"))
        self.notify_periodic: bool = bool(kwargs.get("notify_periodic"))
        self.periodic_minutes: float = float(kwargs.get("periodic_minutes") or 0)
        self.proxies: Optional[dict] = kwargs.get("proxies")
        self.tz = kwargs.get("tz")

        # 数值收敛，填错类型不至于炸
        self.interval = min(max(self.interval, 3.0), 3600.0)
        self.duration_buffer_ms = int(min(max(self.duration_buffer_ms, -500), 5000))
        self.max_minutes = min(max(self.max_minutes, 1.0), 1440.0)
        self.draws = max(self.draws, 0)
        self.reserve = max(self.reserve, 0)


class CookieInvalid(Exception):
    """Cookie 失效，站点把我们踢回登录页了。"""


class LotteryRunner:
    """跑一轮抽奖。和青龙版共用一套节奏与口径。"""

    def __init__(self, options: LotteryOptions, cookie: str, total: Optional[Dict] = None,
                 log: Optional[Callable[[str], None]] = None,
                 notify: Optional[Callable[[str, str], None]] = None,
                 stop_event: Optional[threading.Event] = None):
        self.options = options
        self.cookie = cookie
        self.origin = options.host if re.match(r"^https?://", options.host) else f"https://{options.host}"
        self.origin = self.origin.rstrip("/")

        self._log = log or (lambda line: None)
        self._notify = notify
        self.stop_event = stop_event or threading.Event()

        self.session = requests.Session()
        if options.proxies:
            self.session.proxies.update(options.proxies)
        self.session.trust_env = False

        self.balance = 0.0
        self.cost = 2000.0

        self.current = empty_stats()
        self.total = normalize_stats(total)
        self.interval_stats = empty_stats()

        # 站点公布的折算金额，开跑时从抽奖页读
        self.vip_swap_beans = 0
        # True = 是 VIP 或以上，False = 不是，None = 没查出来
        self.vip_or_above: Optional[bool] = None
        self.vip_class_checked = False
        self.last_vip_swapped_beans = 0
        # 这一抽有没有回服务端校准过余额。中大奖停机前要补一次，
        # VIP 折算核对时已经校准过的就别再要一遍
        self.calibrated_this_draw = False

        self.mail_cleaned = 0
        self.started_at = time.time()
        self.last_periodic_report_at = self.started_at
        self.stop_reason = ""
        # report() 收下的提示，最后拼进通知正文 —— 挂机的人不看日志，通知是唯一出口
        self.messages: List[str] = []

        self.error_streak = 0
        self.rate_limit_streak = 0
        self.network_error_streak = 0
        self.interval_ms = options.interval * 1000
        # 上一抽的 duration 就是下一抽的冷却窗口；请求发出时服务端已开始计时
        self.last_duration_ms = 0
        self.last_draw_sent_at = 0.0
        # 被限流后的单次等待覆盖值，用过即清
        self.quick_retry_ms = 0
        self.deadline = self.started_at + options.max_minutes * 60

    # ---------------- 基础设施 ----------------

    def log(self, line: str):
        self._log(line)

    def report(self, line: str):
        """既要进日志，也要进最后的通知正文。"""
        self.messages.append(line)
        self._log(line)

    def notify(self, title: str, text: str):
        if not self._notify:
            return
        try:
            self._notify(title, text)
        except Exception as err:  # 推送失败不能影响抽奖
            self.log(f"⚠️ 通知发送失败：{err}")

    def now_text(self) -> str:
        return datetime.now(self.options.tz).strftime("%Y-%m-%d %H:%M:%S")

    def sleep(self, ms: float) -> bool:
        """可被停用打断的等待。返回 True 表示被要求停下。"""
        return self.stop_event.wait(max(0.0, ms) / 1000)

    def stopping(self) -> bool:
        return self.stop_event.is_set()

    def headers(self, extra: Optional[dict] = None) -> dict:
        head = {
            "cookie": self.cookie,
            "user-agent": self.options.user_agent,
            "accept-language": "zh-CN,zh;q=0.9,en;q=0.8",
            "referer": f"{self.origin}/lucky.php",
        }
        if extra:
            head.update(extra)
        return head

    @property
    def timeout(self):
        return RUNTIME["connect_timeout"], RUNTIME["read_timeout"]

    def request_idempotent(self, method: str, url: str, label: str, **kwargs):
        """幂等请求专用：网络抖了就重试。

        只给读页面和删站内信用。抽奖那个 POST 绝不能走这里 —— 请求可能已经在
        服务端生效了，重发就是又扣一次憨豆。"""
        attempt = 0
        while True:
            try:
                return self.session.request(method, url, timeout=self.timeout, **kwargs)
            except requests.RequestException as err:
                if attempt >= RUNTIME["request_retries"]:
                    raise
                wait = RUNTIME["request_retry_step_ms"] * (attempt + 1)
                self.log(f"📡 {label}网络不通（{err}），{round(wait / 1000)} 秒后重试"
                         f"（{attempt + 1}/{RUNTIME['request_retries']}）")
                if self.sleep(wait):
                    raise
                attempt += 1

    def get(self, url_path: str) -> str:
        response = self.request_idempotent("GET", f"{self.origin}{url_path}", f"读 {url_path} 时",
                                           headers=self.headers())
        if not response.ok:
            raise RuntimeError(f"{url_path} 请求失败（HTTP {response.status_code}）")
        return response.text

    # ---------------- 站点交互 ----------------

    def snapshot(self) -> Dict:
        """一次请求同时拿余额、单抽消耗。站点抽完不刷新页面，这两个数只能主动来取。"""
        html = self.get("/lucky.php")

        if re.search(r"takelogin\.php|name=\"password\"", html, re.I):
            raise CookieInvalid("Cookie 已失效，站点把我踢回登录页了")

        # 折算金额和单抽消耗一样是站点随时能改的，顺手刷新
        swap_beans = parse_vip_swap_beans(html)
        if swap_beans > 0:
            self.vip_swap_beans = swap_beans

        balance = number_after_class(html, "bean-number")
        cost = number_after_class(html, "use-bean")
        if balance is None:
            raise RuntimeError("读不到憨豆余额，站点可能改版了")

        return {"balance": balance, "cost": round(cost) if cost and cost > 0 else None}

    def draw_once(self) -> Dict:
        """抽一次。任何失败都变成返回值，绝不往外抛 —— 网络一断异常冒出去，
        整轮当场收摊，重试机制压根没机会跑。"""
        self.last_draw_sent_at = time.time()

        try:
            response = self.session.post(
                f"{self.origin}/plugin/lucky-draw",
                headers=self.headers({
                    "x-requested-with": "XMLHttpRequest",
                    # 站点自己用的是 jQuery.post，对齐 Content-Type
                    "content-type": "application/x-www-form-urlencoded; charset=UTF-8",
                }),
                data="",
                timeout=self.timeout,
            )
        except requests.RequestException as err:
            # 请求根本没出去或没回来 —— 网络层的事，和站点无关
            return {"ok": False, "status": 0, "data": None, "network": True, "error": str(err)}

        try:
            text = response.text
        except Exception as err:
            return {"ok": False, "status": response.status_code, "data": None,
                    "network": True, "error": str(err)}

        try:
            return {"ok": response.ok, "status": response.status_code, "data": json.loads(text)}
        except (ValueError, TypeError):
            # ok 报的是 HTTP 层的真实结果，别因为 JSON 没解出来就写成 False ——
            # 站点掉登录时正是拿 200 回一张登录页，describe_draw_failure 要靠
            # 「HTTP 通了但不是 JSON」这个组合才认得出来
            return {"ok": response.ok, "status": response.status_code,
                    "data": None, "raw": text}

    @staticmethod
    def describe_draw_failure(result: Dict) -> str:
        """这一枪到底是怎么失败的。

        以前一律报 status，站点掉登录时拿 HTTP 200 回一张登录页，日志上就只有
        一句「请求失败（HTTP 200）」。既然现在不因失败次数收摊、会一直重试下去，
        人回来满屏都是这个，根本不知道该去重新登录。"""
        if result.get("error"):
            return f"请求失败：{result['error']}"
        status = result.get("status")
        if status in (401, 403):
            return "请求被拒（登录多半已经失效）"
        if not result.get("ok"):
            return f"请求失败：HTTP {status}"

        # HTTP 200 但不是 JSON —— 登录页、维护页、人机验证都长这样
        body = str(result.get("raw") or "")
        if re.search(r"<html", body, re.I):
            if re.search(r"takelogin|login\.php|请登录|登录后", body, re.I):
                return "站点回的是登录页 —— 登录已失效，去页面上重新登一下再抽"
            return "站点没返回 JSON（维护页或人机验证？）"
        return f"站点返回了认不出的内容（HTTP {status}）"

    def record(self, prize_text: str, prize: Dict):
        for stats in (self.current, self.total, self.interval_stats):
            apply_prize(stats, prize_text, self.cost, prize)

    # ---------------- VIP 折算 ----------------

    def read_vip_swap_beans(self) -> float:
        return self.vip_swap_beans or RUNTIME["vip_swap_fallback_beans"]

    def fetch_self_user_id(self) -> Optional[str]:
        """取自己的 user id。不能抓页面上第一个 userdetails 链接就走 —— 站内信发件人、
        邀请列表里全是别人的链接。优先认链接里紧跟着 <b> 或 {Class}_Name 的那个
        （NexusPHP 就是这么渲染本人用户名的）。"""
        html = self.get("/usercp.php")

        owner = re.search(r"userdetails\.php\?id=(\d+)[^>]*>\s*(?:<b>|<span[^>]*_Name)", html, re.I)
        if owner:
            return owner.group(1)

        ids = list(dict.fromkeys(re.findall(r"userdetails\.php\?id=(\d+)", html)))
        return ids[0] if len(ids) == 1 else None

    def check_vip_or_above(self) -> Optional[bool]:
        """查一次就记住。读不到返回 None。"""
        if self.vip_class_checked:
            return self.vip_or_above
        try:
            user_id = self.fetch_self_user_id()
            if not user_id:
                return None
            rank = parse_class_rank(self.get(f"/userdetails.php?id={user_id}"))
            if rank is None:
                return None
            self.vip_or_above = rank >= CLASS_RANK["vip"]
            # 只在真查出来时才记住。查失败（网络抖一下、502）就别记 ——
            # 记了的话整轮都不会再试，后面再中 VIP 只能退回余额差去猜。
            self.vip_class_checked = True
            return self.vip_or_above
        except Exception:
            return None

    def reconcile_vip(self, prize: Dict):
        """抽奖页写着「当中奖 [VIP] 时，如果用户已经是 VIP 或以上等级，奖励憨豆
        1000000」，但接口返回的文案还是 VIP。所以中到 VIP 就回服务端核一次余额。"""
        estimated = self.balance
        try:
            actual = self.snapshot()["balance"]
        except Exception:
            # 这里悄悄放过去最要命：VIP 几千抽才碰一次，漏一次就是一百万
            self.report("⚠️ 中了 VIP 但余额没核成 —— 你若本来就是 VIP，这一注的憨豆没记上")
            return

        drift = actual - estimated
        self.balance = actual
        self.calibrated_this_draw = True

        beans = self.read_vip_swap_beans()
        eligible = self.check_vip_or_above()

        # 账面没多出那笔钱，就是真拿到了天数 —— 不管等级看着像什么
        if drift < beans * RUNTIME["vip_swap_min_drift_ratio"]:
            if eligible is True:
                self.report(f"ℹ️ 中了 VIP，你的等级也够折算，但账面只变动 {_signed(round(drift))}"
                            " —— 站点发的是天数，按 VIP 记")
            return

        # 钱到账了，但等级明确不够 —— 这笔多出来的多半来自别处（赠送、别的实例在抽）
        if eligible is False:
            self.report(f"⚠️ 中了 VIP 后余额多出 {fmt(round(drift))}，但你的等级不到 VIP，"
                        "不符合折算条件 —— 这一注按 VIP 记，多出的钱另有来源")
            return

        # 等级读不到：光有「多了一大笔」不作数。同期中一发 780,000 就能顶过门槛
        if eligible is None and abs(drift - beans) > RUNTIME["vip_swap_tolerance"]:
            self.report(f"⚠️ 中了 VIP 且余额多出 {fmt(round(drift))}，但读不到你的等级、"
                        f"数额也对不上公布的 {fmt(beans)} —— 这一注按 VIP 记")
            return

        # 金额一律按站点公布的来。drift 里混着做种收益、赠送，当金额用会记出
        # 「1,000,060 憨豆」这种奖池里根本没有的档位。
        for stats in (self.current, self.total, self.interval_stats):
            mark_vip_swapped(stats, prize, beans)
        self.last_vip_swapped_beans = beans

        self.report(f"👑 你已经是 VIP，站点改发了 {fmt(beans)} 憨豆 · 仍计为一次 VIP 中奖")

        extra = round(drift - beans)
        if abs(extra) >= 1:
            self.report(f"ℹ️ 同期余额另有 {_signed(extra)}（做种收益 / 赠送等），未计入中奖")

    # ---------------- 通知 ----------------

    def is_big_prize(self, prize: Dict) -> bool:
        """够不够格推一条大奖通知。门槛可配，和「中奖就停」那两个开关互不影响。"""
        return prize["type"] == "vip" or (
            self.options.big_prize_min_beans > 0
            and prize["type"] == "beans"
            and prize["value"] >= self.options.big_prize_min_beans
        )

    def should_stop_for_prize(self, prize: Dict) -> bool:
        """中了就收工。VIP 已折算成憨豆的那一注 type 仍是 vip，照样按 VIP 判；
        780,000 只认普通憨豆的精确档位，不含 1,000,000 等其他档。"""
        return ((self.options.stop_on_vip and prize["type"] == "vip")
                or (self.options.stop_on_780k
                    and prize["type"] == "beans" and prize["value"] == 780000))

    def push_big_prize(self, prize: Dict, prize_text: str, will_stop: bool = False):
        """挂机跑一晚上，中了大奖当场推一条 —— 不然要等跑完才知道。"""
        if not self.options.notify_big_prize or not self.is_big_prize(prize):
            return

        # label 只是档位（VIP 那档就是「7 天」），单独拿出来看不出中的是什么奖，
        # 所以带单位的档位都补上类别名；不带单位的（憨豆、邀请）label 自带名字
        meta = PRIZE_META.get(prize["type"], PRIZE_META["unknown"])
        label = prize.get("label") or str(prize_text).strip()
        prize_display = f"{meta['icon']} {meta['name'] + ' ' if meta['unit'] else ''}{label}"

        # 已经是 VIP 的话站点改发憨豆，通知得说清实际到手的是什么
        if prize["type"] == "vip" and self.last_vip_swapped_beans:
            prize_display += f" → 已折算 {fmt(self.last_vip_swapped_beans)} 憨豆"
            self.last_vip_swapped_beans = 0

        profit, rate = profit_of(self.current)
        body = "\n".join([
            "╭─ 🎊 欧皇降临",
            f"│ 命中大奖：{prize_display}",
            f"│ 中奖时间：{self.now_text()}",
            f"│ 当前抽数：本次第 {fmt(self.current['draws'])} 抽",
            f"╰─ 历史累计：{fmt(self.total['draws'])} 抽",
            "━━━━━━━━━━━━━━━━━━━",
            "📊 本次运行数据",
            f"  🎲 已抽：{fmt(self.current['draws'])} 抽",
            f"  🔥 消耗：{fmt(self.current['cost'])} 憨豆",
            f"  🎁 获得：{fmt(self.current['gains']['beans'])} 憨豆",
            f"  🚀 净盈亏：{_signed(profit)}（{'+' if rate >= 0 else ''}{rate:.1f}%）",
            f"  💰 当前余额：{fmt(self.balance)} 憨豆",
            "━━━━━━━━━━━━━━━━━━━",
            "🛑 已按设置停止本轮抽奖" if will_stop else "🌟 后台持续挂机抽奖中",
        ])
        self.notify("🎉 HHCLUB 幸运大转盘｜命中大奖", body)

    def push_periodic_report(self):
        """定时战报：挂机长跑时按设定周期推送此次增量与累计总览。"""
        if not self.options.notify_periodic or not self.interval_stats["draws"]:
            return

        delta_profit, delta_rate = profit_of(self.interval_stats)
        total_profit, total_rate = profit_of(self.total)

        # 报实际隔了多久，别报配置值 —— 被限流拖慢时两者能差出一大截
        elapsed_minutes = max(1, round((time.time() - self.last_periodic_report_at) / 60))
        next_minutes = max(1, round(self.options.periodic_minutes))

        body = "\n".join([
            "╭─ ⏰ 播报概览",
            f"│ 统计区间：近 {elapsed_minutes} 分钟",
            f"│ 持续运行：{format_duration((time.time() - self.started_at) * 1000)}",
            f"╰─ 播报时间：{self.now_text()}",
            "━━━━━━━━━━━━━━━━━━━",
            "⚡ 此次播报增量",
            f"  🎲 抽奖：+{fmt(self.interval_stats['draws'])} 抽",
            f"  🔥 消耗：-{fmt(self.interval_stats['cost'])} 憨豆",
            gain_line(self.interval_stats, "+"),
            f"  🚀 净盈亏：{_signed(delta_profit)}（{'+' if delta_rate >= 0 else ''}{delta_rate:.1f}%）",
            f"  💰 当前余额：{fmt(self.balance)} 憨豆",
            "━━━━━━━━━━━━━━━━━━━",
            "🎁 此次奖品明细",
            format_prize_details(self.interval_stats["prizes"]),
            "━━━━━━━━━━━━━━━━━━━",
            "🏆 历史累计总量（含此次增量）",
            f"  🎲 抽奖：{fmt(self.total['draws'])} 抽",
            f"  🔥 消耗：{fmt(self.total['cost'])} 憨豆",
            gain_line(self.total),
            f"  ✨ 净盈亏：{_signed(total_profit)}（{'+' if total_rate >= 0 else ''}{total_rate:.1f}%）",
            "━━━━━━━━━━━━━━━━━━━",
            f"🌟 后台持续监控与抽奖中 · 下次播报约 {next_minutes} 分钟后",
        ])
        self.notify("📊 HHCLUB 幸运大转盘｜定时战报", body)

    # ---------------- 节奏 ----------------

    def planned_gap(self) -> float:
        if self.options.follow_duration:
            base = self.last_duration_ms or RUNTIME["blind_gap_ms"]
            return max(500, base + self.options.duration_buffer_ms)
        return max(1000, round(self.interval_ms))

    def next_delay(self) -> float:
        # 被拒不会重置服务端冷却，补一枪即可，不必再等完整 duration
        if self.quick_retry_ms > 0:
            wait = self.quick_retry_ms
            self.quick_retry_ms = 0
            return wait

        gap = self.planned_gap()
        if self.options.follow_duration and self.last_draw_sent_at:
            # 响应传输、记账和通知耗掉的时间也算在冷却里
            return max(250, gap - (time.time() - self.last_draw_sent_at) * 1000)
        return gap

    def should_continue(self) -> bool:
        if self.stopping():
            self.stop_reason = self.stop_reason or "插件停用 / 手动停止"
            return False
        if time.time() > self.deadline:
            self.stop_reason = f"到达单次运行时间上限（{interval_text(self.options.max_minutes)} 分钟）"
            self.report(f"⏰ {self.stop_reason}，收工")
            return False
        if self.options.draws > 0:
            if self.current["draws"] >= self.options.draws:
                self.stop_reason = f"已达到设定抽奖次数（{fmt(self.options.draws)} 抽）"
            return self.current["draws"] < self.options.draws

        # 一抽到底：留够保留线
        if self.balance - self.cost < self.options.reserve:
            self.stop_reason = (f"一抽到底完成（余额 {fmt(self.balance)} 触及保留线 "
                                f"{fmt(self.options.reserve)}）")
            self.report(f"🏁 一抽到底完成，余额 {fmt(self.balance)}"
                        f"（保留线 {fmt(self.options.reserve)}）")
            return False
        return True

    def stop_for_prize(self, prize: Dict, prize_text: str):
        """按设置停在中奖那一刻。收工前拿一次权威余额 —— 开这个功能本来就是
        为了停在中奖那一刻对账，记录里摆个本地估算说不过去。
        VIP 那一注刚才折算核对时已经校准过，这里就跳过了。"""
        if not self.calibrated_this_draw:
            try:
                self.balance = self.snapshot()["balance"]
            except Exception as err:
                self.log(f"⚠️ 停机前校准余额失败（{err}），余额按本地估算记")

        stop_prize = "VIP（含折算）" if prize["type"] == "vip" else "780,000 憨豆"
        self.stop_reason = f"命中停止条件（{stop_prize}），按设置停止"
        self.report(f"🏆 命中 {str(prize_text).strip()}（停止项：{stop_prize}） · 按设置停止本轮")

    def note_stuck(self, streak: int, what: str, wait_ms: float):
        """一直卡着不动时隔一阵子推一条，让人知道它还在转、卡在哪 —— 但不收摊，
        无人值守的时候停了就再也起不来了。"""
        if streak > 0 and streak % RUNTIME["stuck_warn_every"] == 0:
            self.report(f"⚠️ {what}已经连续 {streak} 次 · 仍在重试，"
                        f"当前每 {interval_text(wait_ms / 1000)} 秒探一次")

    # ---------------- 主循环 ----------------

    def run(self):
        start = self.snapshot()
        self.balance = start["balance"]
        if start["cost"]:
            self.cost = start["cost"]

        self.report(f"▶ 开始 · 余额 {fmt(self.balance)} 憨豆 · 单抽 {fmt(self.cost)}")

        if self.balance < self.cost:
            self.stop_reason = "憨豆不足，跳过"
            self.report("💸 憨豆不足，跳过")
            return
        if self.options.draws == 0 and self.balance - self.cost < self.options.reserve:
            self.stop_reason = "余额已在保留线之下，跳过"
            self.report("💸 余额已在保留线之下，跳过")
            return

        first_round = True
        while self.should_continue():
            # 间隔放在开头：最后一抽完就收工，不用白等；出错和限流重试也自然
            # 变成「先等再试」
            if not first_round and self.sleep(self.next_delay()):
                self.stop_reason = self.stop_reason or "插件停用 / 手动停止"
                break
            first_round = False

            result = self.draw_once()

            # 网络层失败：外部原因，一直熬，等待按阶梯往上抬
            if result.get("network"):
                self.network_error_streak += 1
                wait = step_backoff_ms(self.network_error_streak, RUNTIME["network_retry_ms"])
                self.log(f"📡 网络不通（{result.get('error')}）· 第 {self.network_error_streak} 次，"
                         f"{interval_text(wait / 1000)} 秒后重试")
                self.note_stuck(self.network_error_streak, "网络不通", wait)
                self.quick_retry_ms = wait
                continue

            if not result.get("data"):
                self.error_streak += 1
                self.quick_retry_ms = step_backoff_ms(self.error_streak, RUNTIME["error_retry_ms"])
                self.log(f"❌ {self.describe_draw_failure(result)} · "
                         f"{interval_text(self.quick_retry_ms / 1000)} 秒后再试")
                self.note_stuck(self.error_streak, "请求失败", self.quick_retry_ms)
                continue

            data = result["data"]
            if data.get("ret") == 0:
                if self.network_error_streak:
                    self.log("📡 网络恢复了，接着抽")
                    self.network_error_streak = 0
                self.error_streak = 0
                self.rate_limit_streak = 0
                self.interval_ms = self.options.interval * 1000

                payload = data.get("data") or {}
                duration = payload.get("duration")
                try:
                    duration = float(duration)
                except (TypeError, ValueError):
                    duration = 0
                self.last_duration_ms = duration if 0 < duration <= 300000 else 0

                prize_text = decode_unicode(payload.get("prize_text") or "未知奖品")
                prize = parse_prize_text(prize_text)

                self.record(prize_text, prize)
                # 中的憨豆是真回血，本地结算一次，省得每抽都去要余额
                gained = prize["value"] if prize["type"] == "beans" else 0
                self.balance = max(0, self.balance - self.cost + gained)

                self.log(f"🎲 第 {fmt(self.current['draws'])} 抽：{str(prize_text).strip()}"
                         f" · 余额 {fmt(self.balance)}")

                self.calibrated_this_draw = False
                if prize["type"] == "vip":
                    self.reconcile_vip(prize)

                will_stop = self.should_stop_for_prize(prize)
                self.push_big_prize(prize, prize_text, will_stop)

                # 中了大奖就收工。放在 VIP 折算和通知之后 —— 那两件事得先办完，
                # 不然这一注的账记不齐、通知也发不出去。
                if will_stop:
                    self.stop_for_prize(prize, prize_text)
                    break

                if (self.options.notify_periodic and self.options.periodic_minutes > 0
                        and time.time() - self.last_periodic_report_at
                        >= self.options.periodic_minutes * 60):
                    if self.interval_stats["draws"] > 0:
                        self.push_periodic_report()
                        self.last_periodic_report_at = time.time()
                        self.interval_stats = empty_stats()

                # 和油猴版一个节奏：每 25 抽顺手清一次。挂机跑几百抽的话，
                # 收件箱整场都在涨，等到最后才清没道理
                if (self.options.clean_mail
                        and self.current["draws"] % RUNTIME["mail_clean_every_draws"] == 0):
                    self.sweep_during_run()
                continue

            msg = decode_unicode(data.get("msg") or "未知错误")

            if "重复点击" in msg or "请稍后" in msg or "频繁" in msg:
                self.rate_limit_streak += 1
                if self.options.follow_duration:
                    # 一直被拒就按阶梯往上抬，不设次数上限 —— 站点在限流，等下去
                    # 总能过，收摊反而白白空过一整夜
                    base = (RUNTIME["rate_limit_retry_ms"] if self.last_duration_ms
                            else RUNTIME["blind_retry_ms"])
                    self.quick_retry_ms = step_backoff_ms(self.rate_limit_streak, base)
                    if self.last_duration_ms:
                        self.log(f"⏳ {msg}（上一抽转盘 "
                                 f"{interval_text(self.last_duration_ms / 1000)} 秒，没等够 · "
                                 f"{self.quick_retry_ms}ms 后补一枪）")
                    else:
                        self.log(f"⏳ {msg}（冷却剩多久未知，{self.quick_retry_ms}ms 后再试）")
                else:
                    self.quick_retry_ms = step_backoff_ms(self.rate_limit_streak,
                                                          RUNTIME["rate_limit_retry_ms"])
                    self.log(f"⏳ {msg} · {interval_text(self.quick_retry_ms / 1000)} 秒后再试")
                    if self.rate_limit_streak >= RUNTIME["backoff_after"]:
                        self.interval_ms = min(self.interval_ms * RUNTIME["backoff_factor"],
                                               RUNTIME["max_backoff_ms"])
                self.note_stuck(self.rate_limit_streak, "被限流", self.quick_retry_ms)
                continue

            # 憨豆不足 / 次数用完这类是明确的终止信号，不重试
            if "次数" in msg or "用完" in msg or "不足" in msg:
                self.stop_reason = f"{msg}，停止"
                self.report(f"🛑 {msg}，停止")
                return

            self.error_streak += 1
            self.quick_retry_ms = step_backoff_ms(self.error_streak, RUNTIME["error_retry_ms"])
            self.log(f"❌ {msg} · {interval_text(self.quick_retry_ms / 1000)} 秒后再试")
            self.note_stuck(self.error_streak, "接口报错", self.quick_retry_ms)

    # ---------------- 站内信清理 ----------------

    def parse_mailbox(self, html: str) -> Dict:
        """站点每抽一次就发一封「幸运大转盘 中奖通知」，挂机一晚收件箱就被埋了。
        只删这一种，「种子被删除」之类的一封不碰。"""
        items = [{"id": mid, "subject": re.sub(r"<[^>]*>", "", subject).strip()}
                 for mid, subject in re.findall(
                     r"viewmessage&(?:amp;)?id=(\d+)\"[^>]*>(.*?)</a>", html or "",
                     re.I | re.S)]

        # 翻页下拉框每页一个 option，直接就是总页数。不能靠「这页不满 100 封」判断
        # —— 每页显示多少封是用户自己在站点设置里定的
        select = re.search(r"<select[^>]*switchPage[^>]*>(.*?)</select>", html or "", re.I | re.S)
        page_count = len(re.findall(r"<option", select.group(1), re.I)) if select else 0

        return {"items": items, "pageCount": page_count}

    def is_lottery_mail(self, item: Dict) -> bool:
        return RUNTIME["lottery_mail_keyword"] in item["subject"]

    def mail_page(self, page: int) -> Dict:
        return self.parse_mailbox(
            self.get(f"/messages.php?action=viewmailbox&box=1&page={page}"))

    def delete_mail(self, ids: List[str]) -> int:
        done = 0
        chunk_size = RUNTIME["mail_chunk"]
        for at in range(0, len(ids), chunk_size):
            chunk = ids[at: at + chunk_size]
            body = [("action", "moveordel")]
            body += [("messages[]", mid) for mid in chunk]
            body.append(("delete", "删除"))

            # 删除是幂等的 —— 同一批 id 删两次，第二次什么也不会发生，可以放心重试
            response = self.request_idempotent(
                "POST", f"{self.origin}/messages.php", "删站内信时",
                headers=self.headers({"content-type": "application/x-www-form-urlencoded"}),
                data=body)
            if not response.ok:
                raise RuntimeError(f"删除站内信失败（HTTP {response.status_code}）")
            done += len(chunk)
        return done

    def sweep_first_page(self) -> int:
        """反复清第一页，直到第一页不再有抽奖通知。新信都排在最前面，所以抽奖途中
        用这个就够；一页可能只有 10 封，清一次远不够，所以要循环。"""
        removed = 0
        for _ in range(RUNTIME["mail_sweep_rounds"]):
            if self.stopping():
                break
            ids = [item["id"] for item in self.mail_page(0)["items"] if self.is_lottery_mail(item)]
            if not ids:
                break
            removed += self.delete_mail(ids)
        return removed

    def sweep_during_run(self):
        """抽奖途中顺手清。清信失败不该把抽奖带停，记一行就算了。"""
        try:
            removed = self.sweep_first_page()
            if not removed:
                return
            self.mail_cleaned += removed
            self.log(f"📪 清掉 {fmt(removed)} 封抽奖通知 · 本次累计 {fmt(self.mail_cleaned)} 封")
        except Exception as err:
            self.log(f"⚠️ 站内信清理失败：{err}")

    def clean_mailbox(self):
        """收尾时翻一遍整个收件箱。

        途中那种只扫第一页的清法会漏：第一页被「种子被删除」这类通知占满时，
        埋在下面的抽奖通知就够不着。翻全本才收得干净。"""
        removed = 0
        try:
            doomed: List[str] = []
            seen = set()
            first = self.mail_page(0)
            total_pages = first["pageCount"] if first["pageCount"] > 0 else RUNTIME["mail_max_pages"]

            for page in range(min(total_pages, RUNTIME["mail_max_pages"])):
                if self.stopping():
                    break
                current = first if page == 0 else self.mail_page(page)
                items = current["items"]
                if not items:
                    break
                if all(item["id"] in seen for item in items):
                    break

                for item in items:
                    if item["id"] in seen:
                        continue
                    seen.add(item["id"])
                    if self.is_lottery_mail(item):
                        doomed.append(item["id"])

                # 下拉框读不到页数时退回长度判断，以第一页的条数为准
                if first["pageCount"] <= 0 and len(items) < len(first["items"]):
                    break

            if doomed:
                removed += self.delete_mail(doomed)
            # 扫描到删完这几秒里可能又进了新通知，补扫第一页收尾
            removed += self.sweep_first_page()
        except Exception as err:
            self.report(f"⚠️ 站内信清理失败：{err}")
            return

        self.mail_cleaned += removed
        if self.mail_cleaned:
            self.report(f"📪 本次共清掉 {fmt(self.mail_cleaned)} 封抽奖通知")

    # ---------------- 结算 ----------------

    def summary_notice(self, status_text: str = "正常结束") -> str:
        current_profit, current_rate = profit_of(self.current)
        total_profit, total_rate = profit_of(self.total)

        sections = [
            "╭─ 🎯 任务结算",
            f"│ 运行状态：{status_text}",
            f"│ 运行时长：{format_duration((time.time() - self.started_at) * 1000)}",
            f"│ 最终余额：{fmt(self.balance)} 憨豆",
            f"╰─ 结束时间：{self.now_text()}",
            "━━━━━━━━━━━━━━━━━━━",
            "⚡ 本次运行增量",
            f"  🎲 抽奖：+{fmt(self.current['draws'])} 抽",
            f"  🔥 消耗：-{fmt(self.current['cost'])} 憨豆",
            gain_line(self.current, "+"),
            f"  🚀 净盈亏：{_signed(current_profit)}（{'+' if current_rate >= 0 else ''}{current_rate:.1f}%）",
            "━━━━━━━━━━━━━━━━━━━",
            "🎁 本次奖品明细",
            format_prize_details(self.current["prizes"]),
        ]

        if self.total["draws"] > 0:
            sections += [
                "━━━━━━━━━━━━━━━━━━━",
                "🏆 历史累计总览（含本次）",
                f"  🎲 抽奖：{fmt(self.total['draws'])} 抽",
                f"  🔥 消耗：{fmt(self.total['cost'])} 憨豆",
                gain_line(self.total),
                f"  ✨ 净盈亏：{_signed(total_profit)}（{'+' if total_rate >= 0 else ''}{total_rate:.1f}%）",
                "━━━━━━━━━━━━━━━━━━━",
                "📜 历史奖品明细",
                format_prize_details(self.total["prizes"]),
            ]

        # 卡片是好看，但警告和错误不能只留在日志里 —— 挂机的人本来就不看日志。
        # 开头那行「▶ 开始」和收工原因已经在卡片里了，不必再重复一遍。
        notices = [line for line in self.messages
                   if not re.match(r"^(▶|⏰|🏁|💸|🛑)", line)]
        if notices:
            sections += ["━━━━━━━━━━━━━━━━━━━", "📌 运行提示"]
            sections += [f"  {line}" for line in notices[-20:]]

        return "\n".join(sections)
