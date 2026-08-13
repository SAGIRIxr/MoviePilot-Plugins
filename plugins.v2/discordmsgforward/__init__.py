# -*- coding: utf-8 -*-
import hashlib
import re
import threading
import time
import uuid
from datetime import datetime, timedelta
from typing import Any, List, Dict, Tuple, Optional

import pytz
import requests
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from app.core.config import settings
from app.core.event import eventmanager, Event
from app.helper.notification import NotificationHelper
from app.plugins import _PluginBase
from app.log import logger
from app.schemas import NotificationType
from app.schemas.types import EventType

# Discord REST API
DISCORD_API = "https://discord.com/api/v10"

# 使用说明（详情页「使用说明」按钮跳转到这里）
DOCS_URL = ("https://github.com/SAGIRIxr/MoviePilot-Plugins/blob/main/"
            "plugins.v2/discordmsgforward/README.md")

# 默认消息模板
DEFAULT_TITLE_TEMPLATE = "【Discord | {channel}】"
DEFAULT_TEXT_TEMPLATE = "{content}\n\n🎁 提取内容：{codes}\n\n👤 {author}  🕐 {time}"
# 转发到 Discord 频道时的默认模板（Discord 支持 Markdown，无标题概念）
DEFAULT_DISCORD_TEMPLATE = "**{channel}** · {author} · {time}\n{content}\n🎁 {codes}\n🔗 {link}"

# 模板里「值为空就整行删掉」的可选变量
OPTIONAL_TEMPLATE_VARS = ("codes", "link")

# 内置提取正则示例
# 礼包码：反引号包裹的码，或 "Code:" / "Gift Code" 标签后（冒号或换行分隔）跟的码。
# 码必须含数字或大小写混排，用来排除 "NEW GIFT CODE AVAILABLE" 这类全大写英文单词；
# 结尾用 (?![A-Za-z0-9]) 而不是 \b，避免 Python 的 Unicode \b 在「码+中文」时不匹配。
GIFTCODE_REGEX = (
    r"`([A-Za-z0-9]{4,20})`"
    r"|[Cc]ode[^\S\n]*(?:[:：=＝][^\S\n]*|\n[^\S\n]*)"
    r"((?:(?=[A-Za-z0-9]*\d)|(?=[A-Za-z0-9]*[a-z])(?=[A-Za-z0-9]*[A-Z]))"
    r"[A-Za-z0-9]{4,20})(?![A-Za-z0-9])"
)

REGEX_PRESETS = [
    {
        "title": "礼包码 / Gift Code",
        "value": GIFTCODE_REGEX,
        "desc": "识别 `code` 反引号写法、「Code: xxx」「Gift Code」换行写法；"
                "自动跳过 NEW GIFT CODE AVAILABLE 这类全大写英文。适配 WOS 等发码频道。",
    },
    {
        "title": "反引号包裹的内容",
        "value": r"`([^`\n]{2,60})`",
        "desc": "只取被 ` 包起来的片段，发码机器人常用这种格式。",
    },
    {
        "title": "http/https 链接",
        "value": r"https?://\S+",
        "desc": "提取消息里的所有链接。",
    },
]

# 图片附件扩展名
IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp")

# 连续失败多少次后告警
FAIL_ALERT_THRESHOLD = 3

# 单次轮询每个频道最多翻几页（每页 100 条），防止积压时无限拉取
MAX_PAGES_PER_POLL = 5
# 单条聚合通知最多包含多少条消息，超出拆成多条通知
MAX_AGGREGATE_ITEMS = 20
# 单条通知正文最大长度，超出截断（企微/TG 等渠道均有长度上限）
MAX_CONTENT_LENGTH = 3000
# 免打扰暂存 / 失败重试队列最大条数，超出丢弃最旧的
MAX_QUEUE_SIZE = 500
# 转发历史最大条数
MAX_HISTORY_SIZE = 1000
# 发送失败最多重投几次
MAX_SEND_ATTEMPTS = 3
# 单次 API 请求超时（秒）
API_TIMEOUT = 30
# 429 限流最多自动等待重试几次
MAX_RATE_LIMIT_RETRY = 2
# Discord 单条消息正文上限（官方限制 2000 字符）
MAX_DISCORD_LENGTH = 2000
# 重复检测：每条规则最多记住多少条指纹
DEDUP_MAX_PER_RULE = 200
# 重复检测：指纹保留天数，超过就当作新消息
DEDUP_TTL_DAYS = 7

# 规则默认值
RULE_DEFAULTS = {
    "id": "",
    "name": "",
    "enabled": True,
    "channels": [],           # 监听频道 ID 列表
    "notify_enabled": True,   # 是否推送到 MoviePilot 通知渠道
    "notify_channels": [],    # 通知渠道，空=全部
    "forward_channels": [],   # 转发目标 Discord 频道 ID 列表
    "discord_template": "",   # 转发到 Discord 频道时的正文模板
    "keywords": "",
    "blocked_keywords": "",
    "author_include": "",
    "author_exclude": "",
    "code_regex": "",
    "aggregate": True,
    "forward_image": True,
    "jump_link": True,        # 通知是否附带「点击查看」原消息跳转链接
    "dedup": False,           # 重复转发检测
    "quiet_hours": "",
    "title_template": "",
    "text_template": "",
}


class DiscordMsgForward(_PluginBase):
    # 插件名称
    plugin_name = "Discord消息转发"
    # 插件描述
    plugin_desc = "将 Discord 频道新消息按规则转发到通知渠道或其它 Discord 频道：规则卡片式管理，每条规则独立配置频道、去向、过滤、正则提取、模板与免打扰时段。"
    # 插件图标
    plugin_icon = "https://raw.githubusercontent.com/SAGIRIxr/MoviePilot-Plugins/main/icons/DiscordForward_A.png"
    # 插件版本
    plugin_version = "4.4.0"
    # 插件作者
    plugin_author = "SAGIRIxr"
    # 作者主页
    author_url = "https://github.com/SAGIRIxr"
    # 插件配置项ID前缀
    plugin_config_prefix = "discordmsgforward_"
    # 加载顺序
    plugin_order = 30
    # 可使用的用户级别
    auth_level = 1

    # ---------------- 私有属性 ----------------
    _enabled = False
    # Bot Token
    _token = ""
    # 轮询间隔（分钟）
    _interval = 5
    # 通知类型
    _msgtype = "Plugin"
    # 失败告警
    _fail_alert = True
    # 是否使用系统代理
    _use_proxy = True
    # 历史记录保留天数
    _history_days = 30
    # 转发规则列表
    _rules: List[dict] = []

    # 定时器（复用同一个实例，避免每次触发都新建后台线程池）
    _scheduler: Optional[BackgroundScheduler] = None
    # HTTP 会话（复用连接）
    _session: Optional[requests.Session] = None
    # 防止定时轮询与「立即检查」并发跑同一份 last_ids
    _check_lock = threading.Lock()
    # 保护 _scheduler 的创建/销毁
    _scheduler_lock = threading.Lock()

    def init_plugin(self, config: dict = None):
        # 停止现有任务
        self.stop_service()

        config = config or {}
        self._enabled = config.get("enabled") or False
        self._token = (config.get("token") or "").strip()
        self._interval = self.__safe_int(config.get("interval"), default=5, minimum=1)
        self._msgtype = config.get("msgtype") or "Plugin"
        self._fail_alert = config.get("fail_alert") if config.get("fail_alert") is not None else True
        self._use_proxy = config.get("use_proxy") if config.get("use_proxy") is not None else True
        self._history_days = self.__safe_int(config.get("history_days"), default=30, minimum=1)
        self._rules = [self.__norm_rule(r) for r in (config.get("rules") or [])]
        self.__prune_dedup()

        # 保存配置后：后台刷新频道列表缓存
        if self._token:
            self.__run_once(self.refresh_channel_options, "刷新Discord频道列表", delay=3)

    @staticmethod
    def __safe_int(value: Any, default: int, minimum: int = 0) -> int:
        """容错的整数转换：前端传空串/非法值时回落到默认值"""
        try:
            return max(minimum, int(value))
        except (TypeError, ValueError):
            return default

    @staticmethod
    def __norm_rule(rule: dict) -> dict:
        """补齐规则默认字段"""
        merged = {**RULE_DEFAULTS, **(rule or {})}
        if not merged.get("id"):
            merged["id"] = uuid.uuid4().hex[:8]
        return merged

    # ---------------- 调度 ----------------
    def __run_once(self, func, name: str, delay: int = 1):
        """复用同一个后台调度器投递一次性任务，避免调度器/线程泄漏"""
        try:
            with self._scheduler_lock:
                if self._scheduler is None or not self._scheduler.running:
                    self._scheduler = BackgroundScheduler(timezone=settings.TZ)
                    self._scheduler.start()
                self._scheduler.add_job(
                    func=func,
                    trigger="date",
                    run_date=datetime.now(tz=pytz.timezone(settings.TZ)) + timedelta(seconds=delay),
                    name=name,
                )
        except Exception as e:
            logger.error(f"投递后台任务 [{name}] 失败: {e}")

    # ---------------- 工具方法 ----------------
    def __get_proxies(self):
        """获取系统代理"""
        if not self._use_proxy:
            return None
        try:
            if hasattr(settings, "PROXY") and settings.PROXY:
                return settings.PROXY
        except Exception as e:
            logger.error(f"获取代理设置出错: {e}")
        return None

    @staticmethod
    def __split_multi(value: str) -> List[str]:
        """分隔多值字段：支持 | 、中英文逗号"""
        if not value:
            return []
        return [x.strip() for x in re.split(r"[|,，]", value) if x.strip()]

    def __get_session(self) -> requests.Session:
        """复用 HTTP 会话：连接池 + 5xx 自动重试"""
        if self._session is None:
            session = requests.Session()
            adapter = HTTPAdapter(
                pool_connections=4,
                pool_maxsize=8,
                max_retries=Retry(
                    total=2,
                    connect=2,
                    read=2,
                    status=0,
                    backoff_factor=1,
                    status_forcelist=(500, 502, 503, 504),
                    allowed_methods=frozenset(["GET"]),
                ),
            )
            session.mount("https://", adapter)
            session.headers.update({
                "User-Agent": "DiscordBot (MoviePilot-Plugin-DiscordMsgForward, 4.3)",
            })
            self._session = session
        return self._session

    @staticmethod
    def __parse_retry_after(resp) -> float:
        """解析 429 响应的等待秒数"""
        value = resp.headers.get("Retry-After")
        if value is None:
            try:
                value = (resp.json() or {}).get("retry_after")
            except Exception:
                value = None
        try:
            wait = float(value)
        except (TypeError, ValueError):
            wait = 3.0
        # 限制在 1~30 秒，避免长时间阻塞轮询线程
        return min(max(wait, 1.0), 30.0)

    def __api_get(self, path: str, params: dict = None, _retry: int = 0):
        """调用 Discord REST API，自动处理 429 限流"""
        resp = self.__get_session().get(
            f"{DISCORD_API}{path}",
            headers={"Authorization": f"Bot {self._token}"},
            params=params,
            proxies=self.__get_proxies(),
            timeout=API_TIMEOUT,
        )
        if resp.status_code == 429 and _retry < MAX_RATE_LIMIT_RETRY:
            wait = self.__parse_retry_after(resp)
            logger.warning(f"Discord 限流（{path}），等待 {wait:.1f} 秒后重试")
            time.sleep(wait)
            return self.__api_get(path, params, _retry + 1)
        return resp

    def __api_post(self, path: str, payload: dict, _retry: int = 0):
        """
        调用 Discord REST API 写接口。
        只在 429（明确未送达）时自动重试；5xx 不重试，避免重复发帖。
        """
        resp = self.__get_session().post(
            f"{DISCORD_API}{path}",
            headers={"Authorization": f"Bot {self._token}"},
            json=payload,
            proxies=self.__get_proxies(),
            timeout=API_TIMEOUT,
        )
        if resp.status_code == 429 and _retry < MAX_RATE_LIMIT_RETRY:
            wait = self.__parse_retry_after(resp)
            logger.warning(f"Discord 限流（POST {path}），等待 {wait:.1f} 秒后重试")
            time.sleep(wait)
            return self.__api_post(path, payload, _retry + 1)
        return resp

    def __get_bot_user_id(self) -> Optional[str]:
        """
        获取并缓存 Bot 自身的用户 ID。
        频道互转时用它跳过 Bot 自己发的消息，否则 A→B 的转发结果会被再次拉取，形成死循环。
        """
        cached = self.get_data("bot_user_id")
        if cached:
            return cached
        if not self._token:
            return None
        try:
            resp = self.__api_get("/users/@me")
            if resp.status_code == 200:
                uid = (resp.json() or {}).get("id")
                if uid:
                    self.save_data("bot_user_id", uid)
                    logger.info(f"已识别 Bot 自身 ID：{uid}，其发出的消息不会被再次转发")
                    return uid
            logger.warning(f"获取 Bot 自身信息失败: HTTP {resp.status_code}，"
                           f"频道互转的自消息过滤本轮不可用")
        except Exception as e:
            logger.warning(f"获取 Bot 自身信息异常: {e}")
        return None

    def refresh_channel_options(self) -> List[dict]:
        """拉取 Bot 可见的服务器与频道，缓存供前端下拉选择"""
        if not self._token:
            return []
        # Token 可能已更换，顺带重新识别 Bot 自身 ID
        self.save_data("bot_user_id", None)
        self.__get_bot_user_id()
        try:
            resp = self.__api_get("/users/@me/guilds")
            if resp.status_code != 200:
                logger.error(f"获取 Discord 服务器列表失败: HTTP {resp.status_code}")
                return self.get_data("channel_options") or []
            options = []
            meta: Dict[str, dict] = self.get_data("channel_meta") or {}
            for guild in resp.json():
                gid, gname = guild.get("id"), guild.get("name")
                cresp = self.__api_get(f"/guilds/{gid}/channels")
                if cresp.status_code != 200:
                    logger.warning(f"获取服务器 [{gname}] 频道列表失败: HTTP {cresp.status_code}")
                    continue
                # 0=文字频道 5=公告频道
                for ch in cresp.json():
                    if ch.get("type") in (0, 5):
                        name = f"{gname} / #{ch.get('name')}"
                        options.append({"title": name, "value": ch.get("id")})
                        meta[ch.get("id")] = {"guild_id": gid, "name": name}
            self.save_data("channel_options", options)
            self.save_data("channel_meta", meta)
            logger.info(f"已刷新 Discord 频道列表，共 {len(options)} 个文字/公告频道")
            return options
        except Exception as e:
            logger.error(f"刷新 Discord 频道列表异常: {e}")
            return self.get_data("channel_options") or []

    @staticmethod
    def __extract_text(msg: dict) -> str:
        """从消息对象中提取文本内容（正文 + embed + 非图片附件链接）"""
        parts = []
        content = (msg.get("content") or "").strip()
        if content:
            parts.append(content)
        for embed in msg.get("embeds") or []:
            for key in ("title", "description"):
                val = (embed.get(key) or "").strip()
                if val:
                    parts.append(val)
            for field in embed.get("fields") or []:
                name = (field.get("name") or "").strip()
                value = (field.get("value") or "").strip()
                if name or value:
                    parts.append(f"{name}: {value}".strip(": "))
        for att in msg.get("attachments") or []:
            url = att.get("url")
            if url and not DiscordMsgForward.__is_image_attachment(att):
                parts.append(f"[附件] {url}")
        # 贴纸消息
        for sticker in msg.get("sticker_items") or []:
            name = (sticker.get("name") or "").strip()
            if name:
                parts.append(f"[贴纸] {name}")
        # 投票消息
        poll = msg.get("poll") or {}
        question = ((poll.get("question") or {}).get("text") or "").strip()
        if question:
            answers = [((a.get("poll_media") or {}).get("text") or "").strip()
                       for a in poll.get("answers") or []]
            answers = [a for a in answers if a]
            parts.append(f"[投票] {question}" + (f"\n选项：{' / '.join(answers)}" if answers else ""))
        # Discord「转发」消息：正文/Embed/附件在 message_snapshots 里
        for snap in msg.get("message_snapshots") or []:
            sub = DiscordMsgForward.__extract_text(snap.get("message") or {})
            if sub:
                parts.append(sub)
        return "\n".join(parts)

    @staticmethod
    def __is_image_attachment(att: dict) -> bool:
        if (att.get("content_type") or "").startswith("image/"):
            return True
        filename = (att.get("filename") or "").lower()
        return filename.endswith(IMAGE_EXTS)

    @staticmethod
    def __extract_image(msg: dict) -> Optional[str]:
        """提取消息中第一张图片的 URL（附件优先，其次 embed 配图）"""
        for att in msg.get("attachments") or []:
            if DiscordMsgForward.__is_image_attachment(att) and att.get("url"):
                return att["url"]
        for embed in msg.get("embeds") or []:
            for key in ("image", "thumbnail"):
                url = (embed.get(key) or {}).get("url")
                if url:
                    return url
        # Discord「转发」消息：图片在 message_snapshots 里
        for snap in msg.get("message_snapshots") or []:
            url = DiscordMsgForward.__extract_image(snap.get("message") or {})
            if url:
                return url
        return None

    def __pass_filters(self, rule: dict, text: str, author: str) -> bool:
        """按顺序检查：作者白名单 → 作者黑名单 → 屏蔽词 → 关键词白名单"""
        include_authors = [a.lower() for a in self.__split_multi(rule.get("author_include"))]
        if include_authors and author.lower() not in include_authors:
            return False
        exclude_authors = [a.lower() for a in self.__split_multi(rule.get("author_exclude"))]
        if exclude_authors and author.lower() in exclude_authors:
            return False
        text_lower = text.lower()
        for blocked in self.__split_multi(rule.get("blocked_keywords")):
            if blocked.lower() in text_lower:
                return False
        keywords = self.__split_multi(rule.get("keywords"))
        if keywords and not any(kw.lower() in text_lower for kw in keywords):
            return False
        return True

    @staticmethod
    def __extract_codes(regex: str, text: str) -> List[str]:
        """按规则正则提取内容（如礼包码）"""
        if not regex or not text:
            return []
        try:
            codes = re.findall(regex, text)
            # 正则含分组时 findall 返回元组
            result = []
            for c in codes:
                c = c if isinstance(c, str) else next((x for x in c if x), "")
                if c and c not in result:
                    result.append(c)
            return result
        except re.error as e:
            logger.error(f"提取正则无效: {e}")
            return []

    @staticmethod
    def __format_time(iso_time: str) -> str:
        """Discord ISO 时间转本地时间字符串"""
        try:
            dt = datetime.fromisoformat(iso_time)
            return dt.astimezone(pytz.timezone(settings.TZ)).strftime('%Y-%m-%d %H:%M:%S')
        except Exception:
            return iso_time or ""

    @staticmethod
    def __render_template(template: str, variables: Dict[str, Any]) -> str:
        """
        渲染消息模板。支持变量：{channel} {author} {content} {codes} {time} {count} {link}
        {codes}/{link} 为空时自动去掉所在整行；{content} 最后替换，避免正文里的花括号被二次替换。
        """
        for optional in OPTIONAL_TEMPLATE_VARS:
            if not variables.get(optional):
                placeholder = "{%s}" % optional
                template = "\n".join(
                    line for line in template.splitlines() if placeholder not in line)
        for key in ("channel", "author", "codes", "time", "count", "link"):
            template = template.replace("{%s}" % key, str(variables.get(key) or ""))
        template = template.replace("{content}", variables.get("content") or "")
        # 清理多余空行
        return re.sub(r"\n{3,}", "\n\n", template).strip()

    @staticmethod
    def __in_quiet_hours(quiet_hours: str) -> bool:
        """判断当前是否处于免打扰时段（支持跨零点，如 23:00-08:00）"""
        if not quiet_hours:
            return False
        m = re.match(r"^(\d{1,2}):(\d{2})\s*-\s*(\d{1,2}):(\d{2})$", quiet_hours.strip())
        if not m:
            logger.warning(f"免打扰时段格式无效（应为 23:00-08:00）：{quiet_hours}")
            return False
        try:
            now = datetime.now(tz=pytz.timezone(settings.TZ)).time()
            start = now.replace(hour=int(m.group(1)), minute=int(m.group(2)), second=0, microsecond=0)
            end = now.replace(hour=int(m.group(3)), minute=int(m.group(4)), second=0, microsecond=0)
        except ValueError:
            logger.warning(f"免打扰时段时间非法（小时应 0-23，分钟应 0-59）：{quiet_hours}")
            return False
        if start == end:
            return False
        if start < end:
            return start <= now < end
        return now >= start or now < end

    def __get_guild_id(self, cid: str, meta: Dict[str, dict]) -> Optional[str]:
        """获取频道所属服务器 ID（用于拼消息跳转链接），未知时查询并缓存"""
        info = meta.get(cid) or {}
        if info.get("guild_id"):
            return info["guild_id"]
        try:
            resp = self.__api_get(f"/channels/{cid}")
            if resp.status_code == 200:
                gid = resp.json().get("guild_id")
                if gid:
                    meta[cid] = {**info, "guild_id": gid}
                    return gid
        except Exception as e:
            logger.debug(f"查询频道 {cid} 所属服务器失败: {e}")
        return None

    def __fetch_new_messages(self, cid: str, last_id: str) -> Tuple[List[dict], Optional[Any]]:
        """
        分页拉取 last_id 之后的新消息，返回 (按时间升序的消息列表, 失败响应)。
        Discord 单次最多返回 100 条，积压较多时需要连续翻页，否则要等好几轮轮询才能追平。
        """
        collected: List[dict] = []
        cursor = last_id
        for _ in range(MAX_PAGES_PER_POLL):
            resp = self.__api_get(f"/channels/{cid}/messages",
                                  params={"after": cursor, "limit": 100})
            if resp.status_code != 200:
                return collected, resp
            batch = sorted(resp.json() or [], key=lambda m: int(m["id"]))
            if not batch:
                break
            collected.extend(batch)
            cursor = batch[-1]["id"]
            if len(batch) < 100:
                break
        else:
            logger.warning(f"频道 {cid} 积压消息较多，本轮已拉取 {len(collected)} 条，剩余下轮继续")
        return collected, None

    @staticmethod
    def __chunk(items: List[dict], size: int) -> List[List[dict]]:
        """把消息列表切成不超过 size 条的批次"""
        return [items[i:i + size] for i in range(0, len(items), size)] or []

    def __build_batches(self, rule: dict, items: List[dict]) -> List[List[dict]]:
        """按规则的聚合开关切分发送批次，聚合时限制单批条数"""
        if not rule.get("aggregate"):
            return [[item] for item in items]
        return self.__chunk(items, MAX_AGGREGATE_ITEMS)

    @staticmethod
    def __dedup_key(item: dict) -> str:
        """
        去重指纹。
        有提取内容时只按提取内容算：同一个礼包码换个说法重发也应视为重复；
        没有提取内容时退回按正文算。
        """
        codes = item.get("codes") or []
        basis = " / ".join(codes) if codes else (item.get("text") or "")
        return hashlib.sha1(basis.encode("utf-8")).hexdigest()[:16]

    def __filter_duplicates(self, rule: dict, items: List[dict]) -> List[dict]:
        """按规则的重复检测开关过滤掉近期已转发过的相同消息"""
        if not rule.get("dedup") or not items:
            return items
        store: Dict[str, list] = self.get_data("dedup_seen") or {}
        seen: List[dict] = store.get(rule["id"]) or []

        now = datetime.now(tz=pytz.timezone(settings.TZ))
        cutoff = (now - timedelta(days=DEDUP_TTL_DAYS)).timestamp()
        # 过期指纹先清掉，避免长期堆积
        seen = [e for e in seen if float(e.get("t") or 0) >= cutoff]
        known = {e.get("h") for e in seen}

        kept = []
        skipped = 0
        for item in items:
            key = self.__dedup_key(item)
            if key in known:
                skipped += 1
                continue
            known.add(key)
            seen.append({"h": key, "t": now.timestamp()})
            kept.append(item)

        if skipped:
            logger.info(f"规则 [{rule.get('name')}] 重复检测跳过 {skipped} 条"
                        f"（与近 {DEDUP_TTL_DAYS} 天内已转发的内容相同）")
        store[rule["id"]] = seen[-DEDUP_MAX_PER_RULE:]
        self.save_data("dedup_seen", store)
        return kept

    def __prune_dedup(self):
        """清掉已删除规则的去重指纹"""
        store: Dict[str, list] = self.get_data("dedup_seen") or {}
        if not store or not self._rules:
            return
        ids = {r.get("id") for r in self._rules}
        pruned = {k: v for k, v in store.items() if k in ids}
        if len(pruned) != len(store):
            self.save_data("dedup_seen", pruned)

    @staticmethod
    def __rule_legs(rule: dict) -> List[str]:
        """规则的投递去向：notify=MoviePilot 通知渠道，discord=其它 Discord 频道"""
        legs = []
        if rule.get("notify_enabled", True):
            legs.append("notify")
        if rule.get("forward_channels"):
            legs.append("discord")
        return legs

    def __forward_targets(self, rule: dict, watched: set, bot_id: Optional[str]) -> List[str]:
        """
        解析规则的 Discord 转发目标。
        目标同时也被监听时，靠「跳过 Bot 自己发的消息」防死循环；
        Bot 自身 ID 拿不到时这层保护失效，此时直接放弃该目标，宁可不转发也不能刷屏。
        """
        targets = []
        for cid in rule.get("forward_channels") or []:
            if cid in (rule.get("channels") or []) and not bot_id:
                logger.error(f"规则 [{rule.get('name')}] 的转发目标 {cid} 同时也是监听频道，"
                             f"且当前拿不到 Bot 自身 ID，无法防止死循环，已跳过该目标")
                continue
            if cid in watched and not bot_id:
                logger.error(f"规则 [{rule.get('name')}] 的转发目标 {cid} 正被其它规则监听，"
                             f"且当前拿不到 Bot 自身 ID，无法防止死循环，已跳过该目标")
                continue
            targets.append(cid)
        return targets

    # ---------------- 核心逻辑 ----------------
    def check_messages(self):
        """轮询所有规则涉及的频道，按规则分发转发（同一时刻只允许一个实例运行）"""
        if not self._check_lock.acquire(blocking=False):
            logger.info("上一次 Discord 检查尚未结束，本次跳过")
            return
        try:
            self.__check_messages()
        finally:
            self._check_lock.release()

    def __check_messages(self):
        if not self._token:
            logger.error("未配置 Discord Bot Token")
            return
        rules = [r for r in self._rules if r.get("enabled")]
        if not rules:
            logger.info("没有启用中的转发规则")
            return

        # 收集所有频道及监听它们的规则（同频道只拉取一次）
        channel_rules: Dict[str, List[dict]] = {}
        for rule in rules:
            for cid in rule.get("channels") or []:
                channel_rules.setdefault(cid, []).append(rule)
        if not channel_rules:
            logger.info("启用中的规则均未配置频道")
            return

        # Bot 自身 ID：频道互转时用来跳过自己发的消息，避免 A→B→A 死循环
        bot_id = self.__get_bot_user_id() if any(r.get("forward_channels") for r in rules) else None
        watched = set(channel_rules.keys())

        history_items: List[dict] = []
        # 先重投上轮发送失败的批次，再冲刷已结束免打扰时段的暂存消息
        history_items.extend(self.__flush_retry(watched, bot_id))
        history_items.extend(self.__flush_pending(watched, bot_id))

        last_ids: Dict[str, str] = self.get_data("last_ids") or {}
        meta: Dict[str, dict] = self.get_data("channel_meta") or {}
        pending: List[dict] = self.get_data("pending") or []
        success_count = 0
        fail_count = 0
        last_error = ""

        for cid, watchers in channel_rules.items():
            cname = (meta.get(cid) or {}).get("name") or cid
            try:
                last_id = last_ids.get(cid)
                if not last_id:
                    # 首次监听该频道：只记录基线，不转发历史消息
                    resp = self.__api_get(f"/channels/{cid}/messages", params={"limit": 1})
                    if resp.status_code != 200:
                        fail_count += 1
                        last_error = self.__log_api_error(cid, cname, resp)
                        continue
                    msgs = resp.json()
                    last_ids[cid] = msgs[0]["id"] if msgs else "0"
                    success_count += 1
                    logger.info(f"频道 [{cname}] 首次监听，已记录基线消息ID：{last_ids[cid]}，此后的新消息才会转发")
                    continue

                msgs, error_resp = self.__fetch_new_messages(cid, last_id)
                if error_resp is not None:
                    fail_count += 1
                    last_error = self.__log_api_error(cid, cname, error_resp)
                    # 已成功拉到的部分照常处理，游标只推进到已拉取的最后一条
                    if not msgs:
                        continue
                else:
                    success_count += 1
                if not msgs:
                    continue

                logger.info(f"频道 [{cname}] 获取到 {len(msgs)} 条新消息")
                last_ids[cid] = msgs[-1]["id"]
                guild_id = self.__get_guild_id(cid, meta)

                # 预提取消息内容，再按各规则分发
                raw_items = []
                for msg in msgs:
                    # 跳过 Bot 自己发的消息：频道互转时它就是上一轮的转发结果
                    if bot_id and (msg.get("author") or {}).get("id") == bot_id:
                        logger.debug(f"频道 [{cname}] 消息 {msg.get('id')} 由本 Bot 发出，跳过")
                        continue
                    text = self.__extract_text(msg)
                    image = self.__extract_image(msg)
                    if not text and not image:
                        logger.info(f"频道 [{cname}] 消息 {msg.get('id')} 无可提取内容（type={msg.get('type')}），跳过")
                        continue
                    raw_items.append({
                        "text": text or "[图片]",
                        "author": (msg.get("author") or {}).get("username") or "未知",
                        "time": self.__format_time(msg.get("timestamp")),
                        "image": image,
                        "link": (f"https://discord.com/channels/{guild_id}/{cid}/{msg['id']}"
                                 if guild_id else None),
                    })
                if not raw_items:
                    continue

                for rule in watchers:
                    items = []
                    for raw in raw_items:
                        if not self.__pass_filters(rule, raw["text"], raw["author"]):
                            logger.info(f"规则 [{rule.get('name')}] 频道 [{cname}] 消息被过滤规则拦截，跳过")
                            continue
                        items.append({
                            **raw,
                            "image": raw["image"] if rule.get("forward_image") else None,
                            "codes": self.__extract_codes(rule.get("code_regex"), raw["text"]),
                        })
                    if not items:
                        continue
                    # 去重放在免打扰之前，重复内容连暂存都不进
                    items = self.__filter_duplicates(rule, items)
                    if not items:
                        continue
                    if self.__in_quiet_hours(rule.get("quiet_hours")):
                        for item in items:
                            pending.append({**item, "cname": cname, "rule_id": rule["id"]})
                        logger.info(f"规则 [{rule.get('name')}] 处于免打扰时段，{len(items)} 条消息已暂存")
                        continue
                    for batch in self.__build_batches(rule, items):
                        record = self.__send_batch(rule, cname, batch,
                                                   watched=watched, bot_id=bot_id)
                        if record:
                            history_items.append(record)
            except Exception as e:
                fail_count += 1
                last_error = str(e)
                logger.error(f"频道 [{cname}] 轮询异常: {e}")

        self.save_data("last_ids", last_ids)
        self.save_data("channel_meta", meta)
        self.save_data("pending", self.__cap_queue(pending, "免打扰暂存"))
        if history_items:
            self.__save_history(history_items)
        self.__update_fail_state(success_count, fail_count, last_error)

    @staticmethod
    def __cap_queue(queue: List[dict], name: str) -> List[dict]:
        """限制队列长度，超出丢弃最旧的，防止长期堆积拖慢每轮读写"""
        if len(queue) <= MAX_QUEUE_SIZE:
            return queue
        dropped = len(queue) - MAX_QUEUE_SIZE
        logger.warning(f"{name}队列超过 {MAX_QUEUE_SIZE} 条，已丢弃最旧的 {dropped} 条")
        return queue[-MAX_QUEUE_SIZE:]

    def __flush_pending(self, watched: set = None, bot_id: Optional[str] = None) -> List[dict]:
        """冲刷免打扰时段暂存的消息（仅时段已结束的规则），按规则+频道汇总推送"""
        pending: List[dict] = self.get_data("pending") or []
        if not pending:
            return []
        rule_map = {r["id"]: r for r in self._rules}
        records = []
        keep = []
        groups: Dict[tuple, List[dict]] = {}
        for item in pending:
            rule = rule_map.get(item.get("rule_id"))
            if not rule or not rule.get("enabled"):
                # 规则已删除/停用，丢弃暂存
                continue
            if self.__in_quiet_hours(rule.get("quiet_hours")):
                keep.append(item)
                continue
            groups.setdefault((item["rule_id"], item.get("cname") or "未知频道"), []).append(item)
        for (rule_id, cname), items in groups.items():
            # 暂存量可能很大，按上限拆成多条通知
            for batch in self.__chunk(items, MAX_AGGREGATE_ITEMS):
                record = self.__send_batch(rule_map[rule_id], cname, batch,
                                           watched=watched, bot_id=bot_id)
                if record:
                    records.append(record)
        if groups:
            flushed = sum(len(v) for v in groups.values())
            logger.info(f"免打扰时段结束，已汇总推送暂存的 {flushed} 条消息")
        self.save_data("pending", keep)
        return records

    def __flush_retry(self, watched: set = None, bot_id: Optional[str] = None) -> List[dict]:
        """重投上轮发送失败的批次（只重投当时失败的去向，已成功的不会重复发送）"""
        queue: List[dict] = self.get_data("retry_queue") or []
        if not queue:
            return []
        # 先清空，失败的批次会在 __send_batch 里重新入队
        self.save_data("retry_queue", [])
        rule_map = {r["id"]: r for r in self._rules}
        records = []
        for entry in queue:
            rule = rule_map.get(entry.get("rule_id"))
            if not rule or not rule.get("enabled"):
                logger.info(f"重试队列中规则 {entry.get('rule_id')} 已删除或停用，丢弃 {len(entry.get('items') or [])} 条消息")
                continue
            record = self.__send_batch(rule, entry.get("cname") or "未知频道",
                                       entry.get("items") or [],
                                       attempts=int(entry.get("attempts") or 1),
                                       legs=entry.get("legs"),
                                       watched=watched, bot_id=bot_id)
            if record:
                records.append(record)
        logger.info(f"已重投 {len(queue)} 个上轮发送失败的批次")
        return records

    def __queue_retry(self, rule: dict, cname: str, items: List[dict],
                      attempts: int, legs: List[str]):
        """把发送失败的去向放回重试队列，超过次数上限则丢弃并告警"""
        if attempts >= MAX_SEND_ATTEMPTS:
            logger.error(f"规则 [{rule.get('name')}] 频道 [{cname}] 的 {len(items)} 条消息"
                         f"连续 {attempts} 次发送失败（去向 {legs}），已放弃")
            return
        queue: List[dict] = self.get_data("retry_queue") or []
        queue.append({
            "rule_id": rule.get("id"),
            "cname": cname,
            "items": items,
            "attempts": attempts,
            "legs": legs,
        })
        self.save_data("retry_queue", self.__cap_queue(queue, "发送重试"))
        logger.warning(f"规则 [{rule.get('name')}] 频道 [{cname}] 的 {len(items)} 条消息发送失败，"
                       f"已入重试队列（去向 {legs}，第 {attempts} 次）")

    @staticmethod
    def __log_api_error(cid: str, cname: str, resp) -> str:
        hints = {
            401: "Token 无效，请检查 Bot Token",
            403: "Bot 无权限访问该频道（需要「查看频道」和「阅读消息历史」权限）",
            404: "频道不存在，请检查频道 ID",
            429: "请求过于频繁被 Discord 限流，可适当调大轮询间隔，下次轮询会自动重试",
        }
        hint = hints.get(resp.status_code, resp.text[:200] if resp.text else "")
        error = f"频道 [{cname}]({cid}) API 请求失败: HTTP {resp.status_code} {hint}"
        logger.error(error)
        return error

    @staticmethod
    def __truncate(content: str, count: int, limit: int = MAX_CONTENT_LENGTH) -> str:
        """限制正文长度，避免超出下游渠道上限导致整条发送失败"""
        if len(content) <= limit:
            return content
        suffix = f"\n\n…（共 {count} 条消息，内容过长已截断）"
        return content[:max(0, limit - len(suffix))] + suffix

    def __dispatch_discord(self, rule: dict, content: str, image: Optional[str],
                           targets: List[str], count: int = 1) -> Tuple[int, List[str]]:
        """
        把渲染好的正文发到目标 Discord 频道，单个频道失败不影响其它频道。
        allowed_mentions 置空，防止转发内容里的 @everyone / 身份组被真的 @ 出去。
        """
        sent = 0
        failed = []
        if image:
            # Discord 会自动为独立成行的图片链接生成预览
            content = f"{content}\n{image}"
        content = self.__truncate(content, count, MAX_DISCORD_LENGTH)
        for cid in targets:
            try:
                resp = self.__api_post(f"/channels/{cid}/messages", {
                    "content": content,
                    "allowed_mentions": {"parse": []},
                })
                if resp.status_code in (200, 201):
                    sent += 1
                    continue
                failed.append(cid)
                hints = {
                    401: "Token 无效",
                    403: "Bot 无权在该频道发言（需要「发送消息」权限；线程还需「在帖子中发送消息」）",
                    404: "目标频道不存在，请检查频道 ID",
                    429: "被 Discord 限流，下轮轮询会自动重投",
                }
                hint = hints.get(resp.status_code, (resp.text or "")[:200])
                logger.error(f"规则 [{rule.get('name')}] 转发到频道 {cid} 失败: "
                             f"HTTP {resp.status_code} {hint}")
            except Exception as e:
                failed.append(cid)
                logger.error(f"规则 [{rule.get('name')}] 转发到频道 {cid} 异常: {e}")
        return sent, failed

    def __dispatch(self, mtype, title: str, text: str, image: Optional[str],
                   link: Optional[str], targets: List[str]) -> Tuple[int, List[str]]:
        """按渠道逐个发送，单个渠道异常不影响其它渠道。返回 (成功数, 失败渠道列表)"""
        sent = 0
        failed = []
        for target in (targets or [None]):
            try:
                kwargs = {"mtype": mtype, "title": title, "text": text, "image": image, "link": link}
                if target:
                    kwargs["source"] = target
                self.post_message(**kwargs)
                sent += 1
            except Exception as e:
                failed.append(target or "全部渠道")
                logger.error(f"发送到渠道 [{target or '全部渠道'}] 失败: {e}")
        return sent, failed

    def __send_batch(self, rule: dict, cname: str, items: List[dict],
                     attempts: int = 0, legs: List[str] = None,
                     watched: set = None, bot_id: Optional[str] = None) -> Optional[dict]:
        """
        将一批消息渲染后投递到规则配置的去向（通知渠道 / Discord 频道），返回历史记录项。
        legs 指定本次要投递的去向，重投时只带上次失败的那部分，避免重复发送。
        """
        if not items:
            return None
        legs = legs or self.__rule_legs(rule)
        if not legs:
            logger.warning(f"规则 [{rule.get('name')}] 既未启用通知渠道也未配置转发频道，"
                           f"{len(items)} 条消息无处可发，已丢弃")
            return None

        # 聚合变量
        authors = []
        codes = []
        for item in items:
            if item["author"] not in authors:
                authors.append(item["author"])
            for c in item.get("codes") or []:
                if c not in codes:
                    codes.append(c)
        if len(items) > 1:
            content = "\n━━━━━━━━━━\n".join(i["text"] for i in items)
        else:
            content = items[0]["text"]
        content = self.__truncate(content, len(items))
        image = next((i["image"] for i in items if i.get("image")), None)
        link = next((i["link"] for i in reversed(items) if i.get("link")), None)

        variables = {
            "channel": cname,
            "author": "、".join(authors),
            "content": content,
            "codes": " / ".join(codes),
            "time": items[-1]["time"],
            "count": len(items),
            "link": link or "",
        }

        delivered: List[str] = []
        retry_legs: List[str] = []

        if "notify" in legs:
            title = self.__render_template(
                rule.get("title_template") or DEFAULT_TITLE_TEMPLATE, variables)
            text = self.__render_template(
                rule.get("text_template") or DEFAULT_TEXT_TEMPLATE, variables)
            notify_targets = rule.get("notify_channels") or []
            mtype = getattr(NotificationType, self._msgtype, None) or NotificationType.Plugin
            # 关掉跳转链接就不传 link，通知渠道那句「点击查看：…」由 link 触发
            sent, failed = self.__dispatch(
                mtype, title, text, image,
                link if rule.get("jump_link", True) else None,
                notify_targets)
            if sent:
                delivered.append("、".join(notify_targets) if notify_targets else "全部通知渠道")
                if failed:
                    logger.warning(f"规则 [{rule.get('name')}] 频道 [{cname}] "
                                   f"部分通知渠道发送失败: {failed}")
            else:
                retry_legs.append("notify")

        if "discord" in legs:
            targets = self.__forward_targets(rule, watched or set(), bot_id)
            if not targets:
                logger.warning(f"规则 [{rule.get('name')}] 的 Discord 转发目标均不可用，本次跳过")
            else:
                dc_text = self.__render_template(
                    rule.get("discord_template") or DEFAULT_DISCORD_TEMPLATE, variables)
                sent, failed = self.__dispatch_discord(
                    rule, dc_text, image if rule.get("forward_image") else None,
                    targets, len(items))
                if sent:
                    names = [(self.get_data("channel_meta") or {}).get(c, {}).get("name") or c
                             for c in targets if c not in failed]
                    delivered.append("Discord: " + "、".join(names))
                    if failed:
                        logger.warning(f"规则 [{rule.get('name')}] 频道 [{cname}] "
                                       f"部分 Discord 目标发送失败: {failed}")
                else:
                    retry_legs.append("discord")

        if retry_legs:
            # 只把失败的去向放回重试队列，已成功的那部分不会重复发送
            self.__queue_retry(rule, cname, items, attempts + 1, retry_legs)
        if not delivered:
            return None

        logger.info(f"规则 [{rule.get('name')}] 频道 [{cname}] {len(items)} 条消息已转发到 "
                    f"{' + '.join(delivered)}" + (f"，提取内容: {codes}" if codes else ""))
        return {
            "date": datetime.now(tz=pytz.timezone(settings.TZ)).strftime('%Y-%m-%d %H:%M:%S'),
            "rule": rule.get("name") or rule.get("id"),
            "channel": cname,
            "author": variables["author"],
            "content": content if len(content) <= 200 else content[:200] + "…",
            "codes": variables["codes"],
            "count": len(items),
            "targets": " + ".join(delivered),
        }

    def __update_fail_state(self, success_count: int, fail_count: int, last_error: str):
        """维护连续失败计数，达到阈值时发送一次告警，恢复后自动重置"""
        state = self.get_data("fail_state") or {"streak": 0, "alerted": False}
        if fail_count > 0 and success_count == 0:
            state["streak"] = int(state.get("streak") or 0) + 1
            state["last_error"] = (last_error or "")[:200]
            if self._fail_alert and state["streak"] >= FAIL_ALERT_THRESHOLD and not state.get("alerted"):
                mtype = getattr(NotificationType, self._msgtype, None) or NotificationType.Plugin
                try:
                    self.post_message(
                        mtype=mtype,
                        title="【Discord消息转发告警】",
                        text=(f"已连续 {state['streak']} 次轮询全部失败，插件可能无法正常工作。\n"
                              f"请检查 Bot Token、系统代理和频道配置。\n"
                              f"最近错误：{(last_error or '未知')[:200]}"),
                    )
                    state["alerted"] = True
                    logger.warning("已发送连续失败告警通知")
                except Exception as e:
                    logger.error(f"发送失败告警通知出错: {e}")
        else:
            state = {"streak": 0, "alerted": False, "last_error": ""}
        self.save_data("fail_state", state)

    def __save_history(self, items: List[dict]):
        """保存转发历史并清理过期记录"""
        history = self.get_data("history") or []
        if not isinstance(history, list):
            history = [history]
        history.extend(items)

        tz = pytz.timezone(settings.TZ)
        # 写入时按 settings.TZ 格式化，过期判断也必须按同一时区解析，否则容器时区不同会算错
        expired_before = datetime.now(tz=tz) - timedelta(days=self._history_days)
        cleaned = []
        for record in history:
            try:
                dt = tz.localize(datetime.strptime(record["date"], '%Y-%m-%d %H:%M:%S'))
                if dt >= expired_before:
                    cleaned.append(record)
            except Exception:
                logger.debug(f"忽略格式异常的转发历史记录: {record}")
        if len(cleaned) > MAX_HISTORY_SIZE:
            cleaned = cleaned[-MAX_HISTORY_SIZE:]
        self.save_data(key="history", value=cleaned)

    # ---------------- 远程命令 ----------------
    @eventmanager.register(EventType.PluginAction)
    def remote_check(self, event: Event):
        """远程命令 /discord_check 手动触发检查"""
        event_data = event.event_data or {}
        if event_data.get("action") != "discord_check":
            return
        logger.info("收到远程命令，立即检查 Discord 新消息")
        self.check_messages()

    # ---------------- 插件 API ----------------
    def api_get_channels(self, refresh: bool = False) -> dict:
        """获取频道选项（refresh=true 时强制从 Discord 拉取）"""
        if refresh:
            options = self.refresh_channel_options()
        else:
            options = self.get_data("channel_options") or []
            if not options and self._token:
                options = self.refresh_channel_options()
        return {"options": options}

    @staticmethod
    def api_get_notifiers() -> dict:
        """获取已启用的通知渠道选项"""
        try:
            options = [{"title": conf.name, "value": conf.name}
                       for conf in NotificationHelper().get_configs().values()
                       if getattr(conf, "enabled", True)]
        except Exception as e:
            logger.error(f"获取通知渠道列表出错: {e}")
            options = []
        return {"options": options}

    @staticmethod
    def api_get_msgtypes() -> dict:
        """获取通知类型选项"""
        return {"options": [{"title": item.value, "value": item.name} for item in NotificationType]}

    @staticmethod
    def api_get_regex_presets() -> dict:
        """获取内置提取正则示例"""
        return {"options": REGEX_PRESETS}

    def api_get_history(self) -> dict:
        """获取转发历史"""
        history = self.get_data("history") or []
        if not isinstance(history, list):
            history = [history]
        history = sorted(history, key=lambda x: x.get("date") or "", reverse=True)
        return {"history": history}

    def api_clear_history(self) -> dict:
        """清空转发历史"""
        self.save_data("history", [])
        return {"message": "已清空"}

    def api_get_status(self) -> dict:
        """获取运行状态"""
        fail_state = self.get_data("fail_state") or {}
        pending = self.get_data("pending") or []
        retry_queue = self.get_data("retry_queue") or []
        return {
            "enabled": self._enabled,
            "token_set": bool(self._token),
            "docs_url": DOCS_URL,
            "rules_total": len(self._rules),
            "rules_enabled": len([r for r in self._rules if r.get("enabled")]),
            "forward_rules": len([r for r in self._rules
                                  if r.get("enabled") and r.get("forward_channels")]),
            "fail_streak": int(fail_state.get("streak") or 0),
            "last_error": fail_state.get("last_error") or "",
            "pending_count": len(pending),
            "retry_count": len(retry_queue),
            "checking": self._check_lock.locked(),
        }

    def api_check_now(self) -> dict:
        """立即执行一次检查（后台运行）"""
        if not self._token:
            return {"message": "未配置 Bot Token"}
        if self._check_lock.locked():
            return {"message": "上一次检查仍在进行中，请稍候"}
        self.__run_once(self.check_messages, "Discord消息转发-手动检查", delay=1)
        return {"message": "已触发检查，稍后查看历史记录"}

    # ---------------- MoviePilot 接口 ----------------
    def get_state(self) -> bool:
        return self._enabled

    @staticmethod
    def get_command() -> List[Dict[str, Any]]:
        return [{
            "cmd": "/discord_check",
            "event": EventType.PluginAction,
            "desc": "检查Discord新消息",
            "category": "插件命令",
            "data": {"action": "discord_check"},
        }]

    def get_api(self) -> List[Dict[str, Any]]:
        return [
            {"path": "/channels", "endpoint": self.api_get_channels, "methods": ["GET"],
             "auth": "bear", "summary": "获取Discord频道选项"},
            {"path": "/notifiers", "endpoint": self.api_get_notifiers, "methods": ["GET"],
             "auth": "bear", "summary": "获取通知渠道选项"},
            {"path": "/msgtypes", "endpoint": self.api_get_msgtypes, "methods": ["GET"],
             "auth": "bear", "summary": "获取通知类型选项"},
            {"path": "/regex_presets", "endpoint": self.api_get_regex_presets, "methods": ["GET"],
             "auth": "bear", "summary": "获取内置提取正则示例"},
            {"path": "/history", "endpoint": self.api_get_history, "methods": ["GET"],
             "auth": "bear", "summary": "获取转发历史"},
            {"path": "/history", "endpoint": self.api_clear_history, "methods": ["DELETE"],
             "auth": "bear", "summary": "清空转发历史"},
            {"path": "/status", "endpoint": self.api_get_status, "methods": ["GET"],
             "auth": "bear", "summary": "获取运行状态"},
            {"path": "/check", "endpoint": self.api_check_now, "methods": ["POST"],
             "auth": "bear", "summary": "立即检查一次"},
        ]

    def get_service(self) -> List[Dict[str, Any]]:
        """注册定时轮询服务"""
        if self._enabled and self._token and any(
                r.get("enabled") and r.get("channels")
                and (r.get("notify_enabled", True) or r.get("forward_channels"))
                for r in self._rules):
            return [{
                "id": "DiscordMsgForward",
                "name": "Discord消息转发服务",
                "trigger": IntervalTrigger(minutes=max(1, self._interval)),
                "func": self.check_messages,
                "kwargs": {},
            }]
        return []

    @staticmethod
    def get_render_mode() -> Tuple[str, str]:
        """Vue 联邦组件渲染模式"""
        return "vue", "dist/assets"

    def get_form(self) -> Tuple[Optional[List[dict]], Dict[str, Any]]:
        """Vue 模式下返回默认配置模型"""
        return None, {
            "enabled": False,
            "token": "",
            "use_proxy": True,
            "interval": 5,
            "msgtype": "Plugin",
            "fail_alert": True,
            "history_days": 30,
            "rules": [],
        }

    def get_page(self) -> Optional[List[dict]]:
        """Vue 模式下详情页由前端组件渲染"""
        return None

    def stop_service(self):
        """退出插件"""
        try:
            with self._scheduler_lock:
                if self._scheduler:
                    self._scheduler.remove_all_jobs()
                    if self._scheduler.running:
                        self._scheduler.shutdown(wait=False)
                    self._scheduler = None
        except Exception as e:
            logger.error(f"停止Discord消息转发服务出错: {e}")
        try:
            if self._session:
                self._session.close()
                self._session = None
        except Exception as e:
            logger.debug(f"关闭 HTTP 会话出错: {e}")
