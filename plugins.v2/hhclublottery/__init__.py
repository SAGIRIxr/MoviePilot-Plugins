# -*- coding: utf-8 -*-
import threading
import time
from datetime import datetime, timedelta

from fastapi.responses import JSONResponse
from typing import Any, Dict, List, Optional, Tuple

import pytz
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from app.core.config import settings
from app.core.event import eventmanager, Event
from app.log import logger
from app.plugins import _PluginBase
from app.schemas import NotificationType
from app.schemas.types import EventType

from .lottery import (
    CookieInvalid,
    _num,
    first_number,
    JACKPOT_BEANS,
    jackpot_counts,
    detect_overlap,
    merge_stats,
    parse_backup,
    record_import,
    LotteryOptions,
    LotteryRunner,
    PRIZE_META,
    backup_payload,
    empty_stats,
    fmt,
    format_duration,
    normalize_stats,
    profit_of,
    stamp_origin,
    swapped_beans_total,
    tidy_stats,
)

# HH 登录态的关键 Cookie，少了就是没登录
REQUIRED_COOKIE_KEYS = ("c_secure_uid", "c_secure_pass")


def _number(value, default, cast=float):
    """把配置页交上来的值收成数字。

    **空不等于 0。** 界面上的输入框被清空时前端交的是 ""，`int(x or 0)` 会把它
    变成 0 —— 对「每次抽多少次」来说 0 是「一抽到底」，一个空输入框就能让它
    把余额抽干。所以空、None、认不出来的一律退回默认值，只有明明白白填了
    数字才算数。
    """
    if value is None:
        return default
    if isinstance(value, str):
        value = value.strip()
        if not value:
            return default
    try:
        return cast(value)
    except (TypeError, ValueError):
        return default


def _load_cookiecloud_helper():
    """CookieCloud 的模块路径在 MoviePilot 各版本间搬过家，挨个试。

    v2 在 app.helper.cookiecloud，更早在 app.modules.cookiecloud.cookiecloud，
    新版重构后到了 app.adapters.external.cookiecloud。取不到就返回 None，
    由调用方给出「当前版本没有 CookieCloud」的明确提示，而不是抛一个 ImportError。
    """
    for module_path in ("app.helper.cookiecloud",
                        "app.modules.cookiecloud.cookiecloud",
                        "app.adapters.external.cookiecloud"):
        try:
            module = __import__(module_path, fromlist=["CookieCloudHelper"])
            helper = getattr(module, "CookieCloudHelper", None)
            if helper:
                return helper
        except Exception:
            continue
    return None


def _load_site_oper():
    """MoviePilot 站点管理里的 Cookie（它自己也会定时用 CookieCloud 刷新）。"""
    for module_path in ("app.db.site_oper", "app.db.siteoper"):
        try:
            module = __import__(module_path, fromlist=["SiteOper"])
            oper = getattr(module, "SiteOper", None)
            if oper:
                return oper
        except Exception:
            continue
    return None


def _short_domain(host: str) -> str:
    """把用户填的 host 收成 CookieCloud / 站点库里用的域名 key（末两级）。"""
    text = (host or "").strip().lower()
    text = text.split("://")[-1].split("/")[0].split("?")[0].split("@")[-1].split(":")[0]
    parts = [p for p in text.split(".") if p]
    if len(parts) <= 2:
        return ".".join(parts)
    # 二级后缀（com.cn / co.uk 之类）要多留一级
    if parts[-2] in ("com", "net", "org", "gov", "edu", "co") and len(parts[-1]) == 2:
        return ".".join(parts[-3:])
    return ".".join(parts[-2:])


class HHClubLottery(_PluginBase):
    # 插件名称
    plugin_name = "HHCLUB幸运大转盘"
    # 插件描述
    plugin_desc = "hhanclub 幸运大转盘自动抽奖：Cookie 可手填或从 CookieCloud / 站点管理取，自适应延迟、VIP 折算、站内信清理与战绩统计。"
    # 插件图标
    plugin_icon = "https://raw.githubusercontent.com/SAGIRIxr/MoviePilot-Plugins/main/icons/HHLottery_A.png"
    # 插件版本
    plugin_version = "1.7.1"
    # 插件作者
    plugin_author = "SAGIRIxr"
    # 作者主页
    author_url = "https://github.com/SAGIRIxr"
    # 插件配置项ID前缀
    plugin_config_prefix = "hhclublottery_"
    # 加载顺序
    plugin_order = 25
    # 可使用的用户级别
    auth_level = 2

    # ---------------- 私有属性 ----------------
    _enabled = False
    _onlyonce = False
    _notify = True
    # 留空 = 不定时，只手动开始。抽奖花的是真憨豆，默认不该自己跑起来
    _cron = ""

    # Cookie 来源：manual / cookiecloud / site
    _cookie_source = "manual"
    _cookie = ""
    _host = "hhanclub.net"

    # 抽奖参数
    _draws = 10
    _reserve = 0
    _interval = 6.8
    _follow_duration = True
    _duration_buffer = 0
    _max_minutes = 60
    _clean_mail = False
    # 中大奖就收工，两个条件独立开关，都默认关
    _stop_on_vip = False
    _stop_on_780k = False

    # 通知
    _notify_big_prize = True
    _big_prize_min_beans = 780000
    _notify_periodic = False
    _periodic_minutes = 30

    # 其他
    _use_proxy = False
    _user_agent = ""
    _history_days = 90

    # 「停止当前抽奖」：一次性开关，保存后立刻复位（和 onlyonce 一个路子）
    _stop_current = False

    # 备份导入：粘贴 JSON + 方式 + 一次性执行开关
    _import_data = ""
    _import_mode = "merge"
    _do_import = False

    # 清空 / 撤销：同样是一次性开关
    _clear_scope = "history"
    _do_clear = False
    _do_restore = False

    # 运行时
    # 「在不在跑」的检查和置位必须是原子的：定时任务、/run 接口、立即运行一次
    # 是三个不同的线程，光靠 if self._running 挡不住同时进来 —— 漏过去就是
    # 两轮一起抽，花的是真憨豆
    _run_lock = threading.Lock()
    _scheduler: Optional[BackgroundScheduler] = None
    # 全程只有这一个 Event，绝不在 init_plugin 里换新的 —— 换了的话，
    # 正在跑的那一轮还攥着旧的，之后谁也叫不停它
    _stop_event: Optional[threading.Event] = None
    _running = False
    # 正在跑的那一轮，数据页拿它显示实时进度
    _runner: Optional[LotteryRunner] = None
    # 是谁叫停的。「点了停止」和「插件被停用/重载」都会 set 同一个 Event，
    # 但运行记录上写清楚是哪一种，回头看才有用
    _stop_source: Optional[str] = None

    def init_plugin(self, config: dict = None):
        """MoviePilot 保存插件配置走的就是这里（同一个实例，不经过 stop_service）。

        所以这里**不能**顺手把正在跑的那一轮打断 —— 改个 cron、调个通知开关
        都会把挂了一半的抽奖腰斩，还看不出是谁干的。要停就走「停止当前抽奖」
        那个开关，明明白白地停。"""
        self.__shutdown_scheduler()
        if self._stop_event is None:
            self._stop_event = threading.Event()

        if config:
            self._enabled = config.get("enabled") or False
            self._onlyonce = config.get("onlyonce") or False
            self._stop_current = config.get("stop_current") or False
            self._import_data = config.get("import_data") or ""
            self._import_mode = (config.get("import_mode") or "merge").strip()
            self._do_import = config.get("do_import") or False
            self._clear_scope = (config.get("clear_scope") or "history").strip()
            self._do_clear = config.get("do_clear") or False
            self._do_restore = config.get("do_restore") or False
            self._notify = config.get("notify") if config.get("notify") is not None else True
            self._cron = (config.get("cron") or "").strip()

            self._cookie_source = (config.get("cookie_source") or "manual").strip()
            self._cookie = (config.get("cookie") or "").strip()
            self._host = (config.get("host") or "hhanclub.net").strip()

            # 这几个都不能写成 `x or 默认值` —— 见 _number 的说明
            self._draws = _number(config.get("draws"), 10, int)
            self._reserve = _number(config.get("reserve"), 0)
            self._interval = _number(config.get("interval"), 6.8)
            self._follow_duration = (config.get("follow_duration")
                                     if config.get("follow_duration") is not None else True)
            self._duration_buffer = _number(config.get("duration_buffer"), 0, int)
            self._max_minutes = _number(config.get("max_minutes"), 60)
            self._clean_mail = config.get("clean_mail") or False
            self._stop_on_vip = config.get("stop_on_vip") or False
            self._stop_on_780k = config.get("stop_on_780k") or False

            self._notify_big_prize = (config.get("notify_big_prize")
                                      if config.get("notify_big_prize") is not None else True)
            self._big_prize_min_beans = _number(config.get("big_prize_min_beans"), 780000)
            self._notify_periodic = config.get("notify_periodic") or False
            self._periodic_minutes = _number(config.get("periodic_minutes"), 30)

            self._use_proxy = config.get("use_proxy") or False
            self._user_agent = (config.get("user_agent") or "").strip()
            # 至少留 1 天。填 0 的话 `x or 90` 会把它悄悄变成 90，说不清楚
            self._history_days = max(1, _number(config.get("history_days"), 90, int))

        # 一次性动作：导入 / 清空 / 撤销。一次保存只做一件，同时勾多个只能是
        # 勾错了 —— 与其猜哪个优先，不如全都不做、把话说清楚
        actions = [("do_import", "📥 备份导入", self.__run_import),
                   ("do_clear", "🧹 清空记录", self.__run_clear),
                   ("do_restore", "↩️ 撤销上次清空", self.__run_restore)]
        picked = [item for item in actions if getattr(self, f"_{item[0]}")]
        if picked:
            for key, _, _ in actions:
                setattr(self, f"_{key}", False)
            self._onlyonce = False

            if len(picked) > 1:
                names = "、".join(name for _, name, _ in picked)
                ok, title, message = False, "操作未执行", f"{names} 同时勾上了，一次只能做一件，都没执行"
            else:
                key, title, runner = picked[0]
                ok, message = runner()
                if ok and key == "do_import":
                    self._import_data = ""   # 导完清空，免得下次保存又导一遍

            (logger.info if ok else logger.error)(f"{title}：{message}")
            if self._notify:
                self.post_message(mtype=NotificationType.SiteMessage,
                                  title=f"【HHCLUB 幸运大转盘】{title.split(' ')[-1]}",
                                  text=("✅ " if ok else "⛔ ") + message)
            self.__update_config()
            return

        # 停止当前抽奖：只停不启。和「立即运行一次」同时勾上时，停优先 ——
        # 一次保存里既要停又要开，只能是勾错了，宁可什么都不启
        if self._stop_current:
            self._stop_current = False
            if self._running:
                logger.info("收到「停止当前抽奖」，本轮收工 —— 已抽的成绩会照常落盘")
                self._stop_source = "手动停止（配置页开关）"
                self._stop_event.set()
            else:
                logger.info("「停止当前抽奖」已复位 —— 当前没有正在跑的抽奖")
            if self._onlyonce:
                logger.warning("「停止当前抽奖」和「立即运行一次」同时勾上了，本次只停不启")
                self._onlyonce = False
            self.__update_config()
            return

        # 立即运行一次
        if self._onlyonce:
            self._scheduler = BackgroundScheduler(timezone=settings.TZ)
            logger.info("HHCLUB幸运大转盘：立即运行一次")
            self._scheduler.add_job(func=self.run_lottery, trigger="date",
                                    run_date=datetime.now(tz=pytz.timezone(settings.TZ))
                                    + timedelta(seconds=3),
                                    name="HHCLUB幸运大转盘")
            self._onlyonce = False
            self.__update_config()
            if self._scheduler.get_jobs():
                self._scheduler.print_jobs()
                self._scheduler.start()

    def __update_config(self):
        """把当前配置写回（主要用于复位 onlyonce）。"""
        self.update_config({
            "enabled": self._enabled,
            "onlyonce": self._onlyonce,
            "stop_current": self._stop_current,
            "import_data": self._import_data,
            "import_mode": self._import_mode,
            "do_import": self._do_import,
            "clear_scope": self._clear_scope,
            "do_clear": self._do_clear,
            "do_restore": self._do_restore,
            "notify": self._notify,
            "cron": self._cron,
            "cookie_source": self._cookie_source,
            "cookie": self._cookie,
            "host": self._host,
            "draws": self._draws,
            "reserve": self._reserve,
            "interval": self._interval,
            "follow_duration": self._follow_duration,
            "duration_buffer": self._duration_buffer,
            "max_minutes": self._max_minutes,
            "clean_mail": self._clean_mail,
            "stop_on_vip": self._stop_on_vip,
            "stop_on_780k": self._stop_on_780k,
            "notify_big_prize": self._notify_big_prize,
            "big_prize_min_beans": self._big_prize_min_beans,
            "notify_periodic": self._notify_periodic,
            "periodic_minutes": self._periodic_minutes,
            "use_proxy": self._use_proxy,
            "user_agent": self._user_agent,
            "history_days": self._history_days,
        })

    # ---------------- Cookie 来源 ----------------

    def __get_proxies(self) -> Optional[dict]:
        if not self._use_proxy:
            return None
        try:
            if getattr(settings, "PROXY", None):
                return settings.PROXY
        except Exception as err:
            logger.error(f"获取代理设置出错：{err}")
        return None

    @staticmethod
    def __pick_domain_cookie(contents: dict, domain: str) -> Tuple[str, str]:
        """在 {域名: cookie} 里找我们要的那个站。返回 (cookie, 命中的 key)。

        CookieCloud 那边用域名末两级做分组 key，正常就是 hhanclub.net；
        万一用户填的是完整 URL 或带子域名，再做一轮宽松匹配。"""
        if not contents:
            return "", ""
        if domain in contents:
            return contents[domain], domain
        for key, value in contents.items():
            key_lower = str(key).lower().lstrip(".")
            if key_lower == domain or key_lower.endswith("." + domain) or domain.endswith("." + key_lower):
                return value, key
        return "", ""

    def __cookie_from_cookiecloud(self, domain: str) -> Tuple[str, str]:
        helper_cls = _load_cookiecloud_helper()
        if not helper_cls:
            return "", "当前 MoviePilot 版本里没找到 CookieCloud 模块，请改用手动填写"
        try:
            contents, msg = helper_cls().download()
        except Exception as err:
            return "", f"CookieCloud 同步出错：{err}"
        if not contents:
            return "", f"CookieCloud 没返回数据：{msg or '请检查 MoviePilot 设定里的 CookieCloud 配置'}"

        cookie, hit = self.__pick_domain_cookie(contents, domain)
        if not cookie:
            # 把拿到的域名列一部分出来，用户一眼就能看出是不是同步了别的域名
            sample = "、".join(list(contents.keys())[:12])
            return "", (f"CookieCloud 里没有 {domain} 的 Cookie（共 {len(contents)} 个站点："
                        f"{sample}{'…' if len(contents) > 12 else ''}）。"
                        "请确认浏览器插件同步范围包含该站，且最近登录过")
        return cookie, f"CookieCloud（{hit}）"

    def __cookie_from_site(self, domain: str) -> Tuple[str, str]:
        oper_cls = _load_site_oper()
        if not oper_cls:
            return "", "当前 MoviePilot 版本里没找到站点管理模块，请改用手动填写"
        try:
            site = oper_cls().get_by_domain(domain)
        except Exception as err:
            return "", f"读取站点 Cookie 出错：{err}"
        if not site or not getattr(site, "cookie", None):
            return "", f"MoviePilot 站点管理里没有 {domain}，或该站点没有 Cookie"
        return site.cookie, f"MoviePilot 站点（{getattr(site, 'name', domain)}）"

    def __resolve_cookie(self) -> Tuple[str, str]:
        """返回 (cookie, 来源说明或失败原因)。cookie 为空时第二项就是错误信息。"""
        domain = _short_domain(self._host)

        if self._cookie_source == "cookiecloud":
            cookie, note = self.__cookie_from_cookiecloud(domain)
        elif self._cookie_source == "site":
            cookie, note = self.__cookie_from_site(domain)
        else:
            cookie, note = self._cookie, "手动填写"
            if not cookie:
                note = "没有填写 Cookie"

        cookie = (cookie or "").strip()
        if not cookie:
            return "", note

        # 少了这两个就是没登录态，早点说清楚比跑到一半被踢回登录页强
        missing = [key for key in REQUIRED_COOKIE_KEYS if key not in cookie]
        if missing:
            logger.warning(f"取到的 Cookie 里缺少 {'、'.join(missing)}，"
                           "多半不是已登录状态，抽奖大概率会失败")
        return cookie, note

    # ---------------- 清空 / 撤销 ----------------

    CLEAR_SCOPES = {
        "history": "运行记录",
        "stats": "统计（含大奖名册与记录线）",
        "all": "统计和运行记录（回到刚装好的样子）",
    }

    def __run_clear(self) -> Tuple[bool, str]:
        """清空记录。

        清之前先把当前的整份快照存进 before_clear，用「撤销上次清空」能原样放回去。
        这一步不是客气 —— 三万多抽的战绩清掉就再也回不来了，而配置页上一个开关
        离手滑只有一下的距离。"""
        scope = self._clear_scope if self._clear_scope in self.CLEAR_SCOPES else "history"
        total = normalize_stats(self.get_data("total"))
        history = self.get_data("history") or []
        if not isinstance(history, list):
            history = [history]

        if not total["draws"] and not history:
            return False, "本来就是空的，没什么可清"

        self.save_data("before_clear", {
            "at": datetime.now(pytz.timezone(settings.TZ)).strftime("%Y-%m-%d %H:%M:%S"),
            "scope": scope,
            "total": tidy_stats(total),
            "history": history,
        })

        cleared = []
        if scope in ("stats", "all"):
            self.del_data("total")
            cleared.append(f"统计 {fmt(total['draws'])} 抽")
        if scope in ("history", "all"):
            self.del_data("history")
            cleared.append(f"运行记录 {fmt(len(history))} 条")

        return True, (f"已清空{self.CLEAR_SCOPES[scope]}（{' · '.join(cleared)}）。"
                      "清之前的快照已留存，勾「撤销上次清空」保存即可原样放回去。")

    def __run_restore(self) -> Tuple[bool, str]:
        snapshot = self.get_data("before_clear")
        if not isinstance(snapshot, dict) or not snapshot.get("at"):
            return False, "没有可撤销的快照 —— 从没清空过，或者已经撤销过了"

        total = snapshot.get("total")
        history = snapshot.get("history")
        if total is not None:
            self.save_data("total", total)
        if history is not None:
            self.save_data("history", history)
        self.del_data("before_clear")

        draws = normalize_stats(total)["draws"]
        return True, (f"已恢复 {snapshot['at']} 清空前的记录"
                      f"（统计 {fmt(draws)} 抽 · 运行记录 {fmt(len(history or []))} 条）")

    # ---------------- 备份导入导出 ----------------

    def __run_import(self) -> Tuple[bool, str]:
        """把粘进来的备份并进历史。

        统计存的是累加值、没有逐抽流水，所以合并没法真去重 —— 重叠的部分一定会被
        算两遍。改不了这一点，那就在动手之前认出来：铁证（同一个文件导过、两份
        记录同源、大奖时刻完全重合）直接拦下，只是「看着像」的提醒一句照做。"""
        raw = (self._import_data or "").strip()
        if not raw:
            return False, "「导入备份」框是空的"

        try:
            parsed, export_id = parse_backup(raw)
        except Exception as err:
            return False, f"读不出这份备份：{err}"

        existing = normalize_stats(self.get_data("total"))
        overlap = detect_overlap(existing, parsed, export_id)

        # 白名单而不是 == "merge"：配置里万一是个认不出的值，也得按最保守的
        # 来 —— 拦下来，而不是绕过查重闷头合并
        if overlap and overlap["sure"] and self._import_mode not in ("force", "replace"):
            return False, (f"{overlap['title']} —— {overlap['detail']}"
                           "确认要合就把「导入方式」改成「强制合并」再存一次；"
                           "想让这份备份取代当前历史就选「覆盖」。")
        if overlap and not overlap["sure"]:
            logger.warning(f"📥 {overlap['title']}：{overlap['detail']}照常导入")

        if self._import_mode == "replace":
            # 覆盖之后这台机器就是那条记录线的延续，血脉跟着备份走
            merged = parsed
        else:
            merged = merge_stats(existing, parsed)

        record_import(merged, parsed, export_id)
        self.save_data("total", tidy_stats(merged))

        action = "覆盖" if self._import_mode == "replace" else "合并"
        return True, (f"已{action}导入 {fmt(parsed['draws'])} 抽 · "
                      f"历史共 {fmt(merged['draws'])} 抽")

    def build_backup(self) -> dict:
        """油猴版「📥 导入备份」认这个格式。"""
        total = normalize_stats(self.get_data("total"))
        payload = backup_payload(empty_stats(), total)
        # 记录线编号可能是这次现生成的（一轮没跑过就先导出）。存回去，
        # 之后每次导出都沿用同一个，油猴版才认得出这些文件同出一源。
        self.save_data("total", tidy_stats(total))
        return payload

    # ---------------- 主流程 ----------------

    def run_lottery(self):
        """跑一轮抽奖。定时服务、立即运行、远程命令和插件 API 都走这里。"""
        with self._run_lock:
            if self._running:
                logger.warning("上一轮抽奖还在跑，本次跳过")
                return
            if self._stop_event is None:
                self._stop_event = threading.Event()
            self._stop_event.clear()
            self._stop_source = None
            self._running = True

        try:
            cookie, note = self.__resolve_cookie()
            if not cookie:
                logger.error(f"取不到 Cookie：{note}")
                if self._notify:
                    self.post_message(mtype=NotificationType.SiteMessage,
                                      title="【HHCLUB 幸运大转盘】",
                                      text=f"❌ 取不到 Cookie，本次未执行\n{note}")
                return
            logger.info(f"Cookie 来源：{note}")

            options = LotteryOptions(
                host=self._host,
                user_agent=self._user_agent or None,
                draws=self._draws,
                reserve=self._reserve,
                interval=self._interval,
                follow_duration=self._follow_duration,
                duration_buffer_ms=self._duration_buffer,
                max_minutes=self._max_minutes,
                clean_mail=self._clean_mail,
                stop_on_vip=self._stop_on_vip,
                stop_on_780k=self._stop_on_780k,
                notify_big_prize=self._notify_big_prize and self._notify,
                big_prize_min_beans=self._big_prize_min_beans,
                notify_periodic=self._notify_periodic and self._notify,
                periodic_minutes=self._periodic_minutes,
                proxies=self.__get_proxies(),
                tz=pytz.timezone(settings.TZ),
            )

            runner = LotteryRunner(
                options=options,
                cookie=cookie,
                total=self.get_data("total"),
                log=logger.info,
                notify=self.__push,
                stop_event=self._stop_event,
            )
            self._runner = runner

            # 数值被收敛时说一声。实机上有人把「单次运行上限」填成了 600000 分钟，
            # 静悄悄按 1440 跑了，配置页上还显示 600000 —— 那就等于没人知道
            for name, filled, used in (("单次运行上限(分钟)", self._max_minutes, options.max_minutes),
                                       ("固定间隔(秒)", self._interval, options.interval),
                                       ("自适应缓冲(ms)", self._duration_buffer, options.duration_buffer_ms)):
                if filled != used:
                    logger.warning(f"「{name}」填的是 {fmt(filled)}，超出允许范围，"
                                   f"本轮按 {fmt(used)} 跑")

            if options.draws == 0:
                mode = f"一抽到底（保留 {fmt(options.reserve)} 憨豆）"
                logger.warning("「每次抽多少次」是 0 —— 本轮一抽到底，"
                               f"会一直抽到余额跌破保留线 {fmt(options.reserve)}")
            else:
                mode = f"抽 {fmt(options.draws)} 次"
            pace = ("自适应延迟 · 缓冲 %dms" % options.duration_buffer_ms
                    if options.follow_duration else f"固定间隔 {options.interval} 秒")
            logger.info(f"🎡 HHCLUB 幸运大转盘 · {mode} · {pace}")

            status_text = "正常结束"
            try:
                runner.run()
                if runner.stop_reason:
                    status_text = runner.stop_reason
                # 被叫停的话，记清楚是谁叫的
                if self._stop_event.is_set() and self._stop_source:
                    status_text = self._stop_source
            except CookieInvalid as err:
                status_text = f"Cookie 失效（{err}）"
                logger.error(status_text)
            except Exception as err:
                status_text = f"运行异常（{err}）"
                logger.error(f"抽奖过程出错：{err}", exc_info=True)

            # 先落盘再清信 —— 清信可能上百个请求，卡在那儿被打断的话成绩不能跟着丢
            self.save_data("total", tidy_stats(stamp_origin(runner.total)))
            self.__save_history(runner, status_text)

            if self._clean_mail and not self._stop_event.is_set():
                runner.clean_mailbox()

            logger.info("\n" + runner.summary_notice(status_text))
            if self._notify:
                self.post_message(mtype=NotificationType.SiteMessage,
                                  title="🎡 HHCLUB 幸运大转盘｜任务结算",
                                  text=runner.summary_notice(status_text))
        finally:
            self._runner = None
            self._running = False

    def __push(self, title: str, text: str):
        self.post_message(mtype=NotificationType.SiteMessage, title=title, text=text)

    def __save_history(self, runner: LotteryRunner, status_text: str):
        """一次运行记一条。抽了 0 次也记 —— Cookie 失效这种情况正需要在页面上看见。"""
        profit, rate = profit_of(runner.current)
        history = self.get_data("history") or []
        if not isinstance(history, list):
            history = [history]

        history.append(tidy_stats({
            "date": datetime.now(pytz.timezone(settings.TZ)).strftime("%Y-%m-%d %H:%M:%S"),
            "draws": runner.current["draws"],
            "cost": runner.current["cost"],
            "beans": runner.current["gains"]["beans"],
            "swapped": swapped_beans_total(runner.current),
            "profit": profit,
            "rate": round(rate, 1),
            "balance": runner.balance,
            "mail_cleaned": runner.mail_cleaned,
            "duration": format_duration((time.time() - runner.started_at) * 1000),
            "status": status_text,
        }))

        expired = time.time() - self._history_days * 86400
        cleaned = []
        for record in history:
            try:
                if datetime.strptime(record["date"], "%Y-%m-%d %H:%M:%S").timestamp() >= expired:
                    cleaned.append(record)
            except Exception:
                logger.debug(f"忽略格式异常的运行记录：{record}")
        self.save_data("history", cleaned)

    # ---------------- MoviePilot 接口 ----------------

    def get_state(self) -> bool:
        return self._enabled

    @staticmethod
    def get_command() -> List[Dict[str, Any]]:
        return [{
            "cmd": "/hh_lottery",
            "event": EventType.PluginAction,
            "desc": "HHCLUB 幸运大转盘抽奖",
            "category": "站点",
            "data": {"action": "hh_lottery"},
        }]

    @eventmanager.register(EventType.PluginAction)
    def remote_run(self, event: Event):
        if not event:
            return
        event_data = event.event_data or {}
        if event_data.get("action") != "hh_lottery":
            return
        logger.info("收到远程命令，开始抽奖")
        self.run_lottery()

    def get_api(self) -> List[Dict[str, Any]]:
        return [
            {
                "path": "/export",
                "endpoint": self.api_export,
                "methods": ["GET"],
                "auth": "apikey",
                "summary": "导出统计备份",
                "description": "导出油猴版面板可直接导入的 v4 备份 JSON",
            },
            {
                "path": "/run",
                "endpoint": self.api_run,
                "methods": ["GET"],
                "auth": "apikey",
                "summary": "开始抽奖",
                "description": "后台触发一轮抽奖，立即返回",
            },
            {
                "path": "/stop",
                "endpoint": self.api_stop,
                "methods": ["GET"],
                "auth": "apikey",
                "summary": "停止当前抽奖",
                "description": "让正在跑的那一轮收工，已抽的成绩照常落盘",
            },
        ]

    def api_export(self):
        """导出备份。带 Content-Disposition，点一下浏览器直接存成文件，
        不用在页面上盯着一堆 JSON 自己另存为。"""
        payload = self.build_backup()
        stamp = datetime.now(pytz.timezone(settings.TZ)).strftime("%Y%m%d-%H%M%S")
        draws = int(payload["total"].get("draws") or 0)
        # 文件名只用 ASCII —— 中文要走 RFC 5987 那套编码，不值当
        name = f"hhclub-lottery-backup-{stamp}-{draws}draws.json"
        return JSONResponse(content=payload,
                            headers={"Content-Disposition": f'attachment; filename="{name}"'})

    def api_run(self) -> dict:
        if self._running:
            return {"code": 1, "message": "上一轮还在跑"}
        threading.Thread(target=self.run_lottery, daemon=True).start()
        return {"code": 0, "message": "已在后台开始抽奖"}

    def api_stop(self) -> dict:
        if not self._running:
            return {"code": 1, "message": "当前没有正在跑的抽奖"}
        self._stop_source = "手动停止（数据页按钮）"
        if self._stop_event:
            self._stop_event.set()
        return {"code": 0, "message": "已通知收工，已抽的成绩会照常落盘"}

    def get_service(self) -> List[Dict[str, Any]]:
        if self._enabled and self._cron:
            return [{
                "id": "HHClubLottery",
                "name": "HHCLUB幸运大转盘",
                "trigger": CronTrigger.from_crontab(self._cron),
                "func": self.run_lottery,
                "kwargs": {},
            }]
        return []

    def get_form(self) -> Tuple[List[dict], Dict[str, Any]]:
        version = getattr(settings, "VERSION_FLAG", "v1")
        cron_field = "VCronField" if version == "v2" else "VTextField"

        def card(icon: str, color: str, title: str, rows: List[dict]) -> dict:
            return {
                "component": "VCard",
                "props": {"class": "mt-3"},
                "content": [
                    {"component": "VCardTitle", "props": {"class": "d-flex align-center"}, "content": [
                        {"component": "VIcon", "props": {"color": color, "class": "mr-2"}, "text": icon},
                        {"component": "span", "text": title},
                    ]},
                    {"component": "VDivider"},
                    {"component": "VCardText", "content": rows},
                ],
            }

        def col(md: int, component: dict) -> dict:
            return {"component": "VCol", "props": {"cols": 12, "md": md}, "content": [component]}

        return [
            {
                "component": "VForm",
                "content": [
                    card("mdi-cog", "info", "基础设置", [
                        {"component": "VRow", "content": [
                            col(3, {"component": "VSwitch", "props": {
                                "model": "enabled", "label": "启用插件", "color": "primary"}}),
                            col(3, {"component": "VSwitch", "props": {
                                "model": "notify", "label": "开启通知", "color": "info"}}),
                            col(3, {"component": "VSwitch", "props": {
                                "model": "onlyonce", "label": "立即运行一次", "color": "success"}}),
                            col(3, {"component": "VSwitch", "props": {
                                "model": "stop_current", "label": "停止当前抽奖", "color": "error",
                                "hint": "保存后立刻收工，已抽的成绩照常落盘",
                                "persistent-hint": True}}),
                        ]},
                        {"component": "VRow", "content": [
                            col(3, {"component": cron_field, "props": {
                                "model": "cron", "label": "抽奖周期（可留空）",
                                "placeholder": "留空 = 只手动开始",
                                "hint": "留空就不定时，靠数据页上的「开始抽奖」按钮手动跑",
                                "persistent-hint": True,
                                "prepend-inner-icon": "mdi-clock-outline"}}),
                        ]},
                    ]),

                    card("mdi-cookie", "warning", "Cookie 来源", [
                        {"component": "VRow", "content": [
                            col(4, {"component": "VSelect", "props": {
                                "model": "cookie_source", "label": "Cookie 来源",
                                "items": [
                                    {"title": "手动填写", "value": "manual"},
                                    {"title": "CookieCloud（用 MoviePilot 设定里的配置）", "value": "cookiecloud"},
                                    {"title": "MoviePilot 站点管理", "value": "site"},
                                ]}}),
                            col(4, {"component": "VTextField", "props": {
                                "model": "host", "label": "站点域名", "placeholder": "hhanclub.net",
                                "hint": "同时作为 CookieCloud / 站点管理里的匹配域名",
                                "persistent-hint": True}}),
                        ]},
                        {"component": "VRow", "content": [
                            {"component": "VCol", "props": {"cols": 12}, "content": [
                                {"component": "VTextarea", "props": {
                                    "model": "cookie", "label": "Cookie（来源选「手动填写」时必填）",
                                    "rows": 3, "auto-grow": True,
                                    "placeholder": "c_secure_uid=...; c_secure_pass=...; c_secure_ssl=...; "
                                                   "c_secure_tracker_ssl=...; c_secure_login=...",
                                    "hint": "浏览器登录站点 → F12 → Network → 任一请求的请求头里 Cookie 整行复制",
                                    "persistent-hint": True}},
                            ]},
                        ]},
                    ]),

                    card("mdi-slot-machine", "primary", "抽奖设置", [
                        {"component": "VRow", "content": [
                            col(3, {"component": "VTextField", "props": {
                                "model": "draws", "label": "每次抽多少次", "type": "number",
                                "placeholder": "10",
                                "hint": "填 0 = 一抽到底", "persistent-hint": True}}),
                            col(3, {"component": "VTextField", "props": {
                                "model": "reserve", "label": "保留憨豆", "type": "number",
                                "hint": "一抽到底时留多少不动", "persistent-hint": True}}),
                            col(3, {"component": "VTextField", "props": {
                                "model": "max_minutes", "label": "单次运行上限(分钟)", "type": "number",
                                "hint": "防止一抽到底把任务挂死", "persistent-hint": True}}),
                            col(3, {"component": "VSwitch", "props": {
                                "model": "clean_mail", "label": "清理抽奖站内信", "color": "warning",
                                "hint": "只删主题带「幸运大转盘」的", "persistent-hint": True}}),
                        ]},
                        {"component": "VRow", "content": [
                            col(4, {"component": "VSwitch", "props": {
                                "model": "follow_duration", "label": "自适应延迟（推荐）", "color": "success",
                                "hint": "按上一抽返回的转盘时长排队，开启后固定间隔不参与",
                                "persistent-hint": True}}),
                            col(4, {"component": "VTextField", "props": {
                                "model": "duration_buffer", "label": "自适应缓冲(ms)", "type": "number",
                                "hint": "-500 ~ 5000，负值更贴边", "persistent-hint": True}}),
                            col(4, {"component": "VTextField", "props": {
                                "model": "interval", "label": "固定间隔(秒)", "type": "number",
                                "hint": "仅在关闭自适应时生效，最小 3 秒", "persistent-hint": True}}),
                        ]},
                        {"component": "VRow", "content": [
                            col(6, {"component": "VSwitch", "props": {
                                "model": "stop_on_vip", "label": "中 VIP 就收工", "color": "error",
                                "hint": "已折算成憨豆的那一注也算", "persistent-hint": True}}),
                            col(6, {"component": "VSwitch", "props": {
                                "model": "stop_on_780k", "label": "中 780,000 憨豆就收工", "color": "error",
                                "hint": "只认这一个精确档位，不含 1,000,000 等其他档",
                                "persistent-hint": True}}),
                        ]},
                    ]),

                    card("mdi-bell-ring", "success", "通知设置", [
                        {"component": "VRow", "content": [
                            col(3, {"component": "VSwitch", "props": {
                                "model": "notify_big_prize", "label": "中大奖即时推送", "color": "success"}}),
                            col(3, {"component": "VTextField", "props": {
                                "model": "big_prize_min_beans", "label": "大奖门槛(憨豆)", "type": "number",
                                "hint": "填 0 则只有 VIP 才推", "persistent-hint": True}}),
                            col(3, {"component": "VSwitch", "props": {
                                "model": "notify_periodic", "label": "定时战报", "color": "info",
                                "hint": "长跑时中途也播报一次", "persistent-hint": True}}),
                            col(3, {"component": "VTextField", "props": {
                                "model": "periodic_minutes", "label": "战报间隔(分钟)", "type": "number",
                                "hint": "别填得比运行上限还大", "persistent-hint": True}}),
                        ]},
                    ]),

                    card("mdi-backup-restore", "purple", "备份导入", [
                        {"component": "VRow", "content": [
                            {"component": "VCol", "props": {"cols": 12}, "content": [
                                {"component": "VTextarea", "props": {
                                    "model": "import_data", "label": "把备份 JSON 粘在这里",
                                    "rows": 4, "auto-grow": False, "clearable": True,
                                    "placeholder": '{"kind": "hhclub-lottery-backup", ...}',
                                    "hint": "油猴版面板「💾 备份 JSON」导出的文件，或本插件导出的备份，内容整段贴进来",
                                    "persistent-hint": True}},
                            ]},
                        ]},
                        {"component": "VRow", "content": [
                            col(6, {"component": "VSelect", "props": {
                                "model": "import_mode", "label": "导入方式",
                                "items": [
                                    {"title": "合并（两边记录相加，换设备用这个）", "value": "merge"},
                                    {"title": "覆盖（用这份备份取代当前历史）", "value": "replace"},
                                    {"title": "强制合并（我知道会算两遍）", "value": "force"},
                                ]}}),
                            col(6, {"component": "VSwitch", "props": {
                                "model": "do_import", "label": "执行导入", "color": "purple",
                                "hint": "勾上保存即导入一次，随后自动复位并清空上面的框",
                                "persistent-hint": True}}),
                        ]},
                        {"component": "VAlert", "props": {
                            "type": "warning", "variant": "tonal", "class": "mt-2",
                            "text": "统计存的是累加值、没有逐抽流水，所以合并没法真去重 —— 重叠的部分一定会被算两遍。"
                                    "所以同一个文件导过第二次、两份记录同源、大奖时刻完全重合这三种铁证会直接拦下来，"
                                    "确认无误再改成「强制合并」。导出在「数据页」上，点「导出备份」直接下文件。"}},
                        {"component": "VAlert", "props": {
                            "type": "info", "variant": "tonal", "class": "mt-2",
                            "text": "从自己导出的备份恢复（导出 → 清空 → 导回来）用「覆盖」更彻底：连记录线一起回来，"
                                    "以后再导同一个文件还认得出。用「合并」也能恢复，只是会新起一条记录线。"
                                    "注意：只清了运行记录、统计还留着的话，导回自己的备份会被「两份记录同源」拦住 —— "
                                    "那是对的，不然就是把自己算两遍。"}},
                    ]),

                    card("mdi-broom", "error", "清空记录", [
                        {"component": "VRow", "content": [
                            col(4, {"component": "VSelect", "props": {
                                "model": "clear_scope", "label": "清空范围",
                                "items": [
                                    {"title": "只清运行记录（统计不动）", "value": "history"},
                                    {"title": "只清统计（含大奖名册与记录线）", "value": "stats"},
                                    {"title": "统计和运行记录都清（回到刚装好的样子）", "value": "all"},
                                ]}}),
                            col(4, {"component": "VSwitch", "props": {
                                "model": "do_clear", "label": "执行清空", "color": "error",
                                "hint": "勾上保存即清一次，随后自动复位",
                                "persistent-hint": True}}),
                            col(4, {"component": "VSwitch", "props": {
                                "model": "do_restore", "label": "撤销上次清空", "color": "success",
                                "hint": "把上次清空前的快照原样放回去",
                                "persistent-hint": True}}),
                        ]},
                        {"component": "VAlert", "props": {
                            "type": "info", "variant": "tonal", "class": "mt-2",
                            "text": "清之前会自动留一份快照，勾「撤销上次清空」就能原样放回来（只留最近一次）。"
                                    "真要搬走或长期留档，还是先到数据页点「导出备份」下一份文件更稳。"
                                    "「执行清空」「撤销上次清空」「执行导入」一次保存只能勾一个，同时勾会全都不执行。"}},
                    ]),

                    card("mdi-tune", "grey", "其他", [
                        {"component": "VRow", "content": [
                            col(3, {"component": "VSwitch", "props": {
                                "model": "use_proxy", "label": "使用系统代理", "color": "warning"}}),
                            col(3, {"component": "VTextField", "props": {
                                "model": "history_days", "label": "运行记录保留(天)", "type": "number"}}),
                            col(6, {"component": "VTextField", "props": {
                                "model": "user_agent", "label": "User-Agent（留空用默认 Chrome）"}}),
                        ]},
                    ]),

                    card("mdi-information", "info", "说明", [
                        {"component": "VAlert", "props": {
                            "type": "warning", "variant": "tonal", "class": "mb-2",
                            "text": "【CookieCloud】选它就用 MoviePilot「设定 → 站点 → CookieCloud」里已配好的服务器/KEY/密码，"
                                    "插件不再单独填一遍。前提是浏览器端的 CookieCloud 插件同步范围包含本站，"
                                    "且最近在浏览器里登录过 —— 站点 Cookie 缺 c_secure_uid / c_secure_pass 就是没登录态。"}},
                        {"component": "VAlert", "props": {
                            "type": "info", "variant": "tonal", "class": "mb-2",
                            "text": "【自适应延迟】站点的冷却窗口就等于上一抽返回的转盘时长（实测 3976~7666ms 随机），"
                                    "任何固定间隔都躲不掉「不要重复点击」。开着自适应时手填的固定间隔完全不参与；"
                                    "被挡回不扣憨豆，脚本会在 300ms 后补一枪。"}},
                        {"component": "VAlert", "props": {
                            "type": "success", "variant": "tonal", "class": "mb-2",
                            "text": "【VIP 折算】站点写明「已是 VIP 或以上等级时中 VIP 改发憨豆」。中到 VIP 会回服务端核余额 + 查等级，"
                                    "确认折算后这一注仍计为一次 VIP 中奖，只把收益记成憨豆，爆率统计和盈亏两头都不错。"}},
                        {"component": "VAlert", "props": {
                            "type": "info", "variant": "tonal", "class": "mb-2",
                            "text": "【统计互通】数据页的战绩可通过插件 API /api/v1/plugin/HHClubLottery/export?apikey=xxx 导出，"
                                    "格式与油猴版备份一致，在 lucky.php 面板上点「📥 导入备份」选「合并」即可带回浏览器。"}},
                        {"component": "VAlert", "props": {
                            "type": "error", "variant": "tonal",
                            "text": "抽奖花的是真憨豆。插件只调用站点自身接口、不做任何数据篡改，"
                                    "请自行控制抽奖频率，后果自负。"}},
                    ]),
                ],
            }
        ], {
            "enabled": False,
            "onlyonce": False,
            "stop_current": False,
            "import_data": "",
            "import_mode": "merge",
            "do_import": False,
            "clear_scope": "history",
            "do_clear": False,
            "do_restore": False,
            "notify": True,
            "cron": "",
            "cookie_source": "manual",
            "cookie": "",
            "host": "hhanclub.net",
            "draws": 10,
            "reserve": 0,
            "interval": 6.8,
            "follow_duration": True,
            "duration_buffer": 0,
            "max_minutes": 60,
            "clean_mail": False,
            "stop_on_vip": False,
            "stop_on_780k": False,
            "notify_big_prize": True,
            "big_prize_min_beans": 780000,
            "notify_periodic": False,
            "periodic_minutes": 30,
            "use_proxy": False,
            "user_agent": "",
            "history_days": 90,
        }

    # ---------------- 数据页 ----------------

    def __action_button(self, path: str, text: str, icon: str, color: str,
                        disabled: bool) -> dict:
        """数据页上的真按钮。MoviePilot 的 PageRender 认 events.click，
        点下去它会带着前端的会话去调插件 API，不用自己拼 URL。"""
        return {
            "component": "VBtn",
            "props": {"color": color, "variant": "flat", "class": "mr-2",
                      "prepend-icon": icon, "disabled": disabled},
            "events": {"click": {
                "api": f"plugin/{self.__class__.__name__}/{path}",
                "method": "get",
                "params": {"apikey": settings.API_TOKEN},
            }},
            "text": text,
        }

    def __status_card(self) -> dict:
        """在不在跑 + 开始 / 停止两个按钮。

        抽奖花的是真憨豆，定时不该是唯一入口 —— 抽奖周期留空就纯靠这里手动开。"""
        runner = self._runner
        running = self._running and runner is not None

        if running:
            color = "success"
            text = (f"正在抽 · 本轮已抽 {fmt(runner.current['draws'])} 次"
                    f" · 消耗 {fmt(runner.current['cost'])}"
                    f" · 余额 {fmt(runner.balance)} 憨豆")
            hint = "点「停止」当场收工，已抽的成绩会照常落盘"
        elif not self._enabled:
            color = "warning"
            text = "插件未启用"
            hint = "先到配置页勾上「启用插件」并保存"
        else:
            color = "secondary"
            text = "空闲中"
            hint = (f"按抽奖周期 {self._cron} 自动触发；也可以直接点「开始抽奖」"
                    if self._cron else "没设抽奖周期 —— 只在点「开始抽奖」时跑")

        return {
            "component": "VCard",
            "props": {"variant": "tonal", "color": color, "class": "mb-4"},
            "content": [{"component": "VCardText", "content": [
                {"component": "div", "props": {"class": "text-subtitle-1 font-weight-bold"},
                 "text": text},
                {"component": "div", "props": {"class": "text-caption mb-3"}, "text": hint},
                {"component": "div", "props": {"class": "d-flex flex-wrap"}, "content": [
                    self.__action_button("run", "开始抽奖", "mdi-play", "primary",
                                         disabled=running or not self._enabled),
                    self.__action_button("stop", "停止", "mdi-stop", "error",
                                         disabled=not running),
                    # 导出必须走 href：events.click 是 axios 调用，拿不到响应体，
                    # 也就存不成文件
                    {"component": "VBtn", "props": {
                        "color": "purple", "variant": "tonal", "class": "mr-2",
                        "prepend-icon": "mdi-download",
                        "href": (f"/api/v1/plugin/{self.__class__.__name__}"
                                 f"/export?apikey={settings.API_TOKEN}"),
                        "target": "_blank"},
                     "text": "导出备份"},
                ]},
            ]}],
        }

    @staticmethod
    def __bean_gain(prize_type: str, bucket: dict) -> float:
        """这一类到底进账了多少憨豆。

        只有憨豆类别本身的 value 是憨豆，别的类别单位是天 / 个 / GB，
        换算不了也不该硬凑；唯一的例外是被折算成憨豆的那部分（目前只有 VIP）。
        各类别的憨豆收益加起来必须等于 gains.beans。"""
        value = _num(bucket.get("value")) if prize_type in ("beans", "magic") else 0
        return value + _num(bucket.get("swappedBeans"))

    @staticmethod
    def __stat(label: str, value: str, color: str = "", hint: str = "",
               cols: int = 6, md: int = 3) -> dict:
        content = [
            {"component": "div", "props": {"class": "text-caption text-medium-emphasis"},
             "text": label},
            {"component": "div", "props": {"class": f"text-h6 {color}".strip()}, "text": value},
        ]
        if hint:
            content.append({"component": "div",
                            "props": {"class": "text-caption text-disabled"}, "text": hint})
        return {"component": "VCol", "props": {"cols": cols, "md": md}, "content": content}

    def __overview_card(self, total: dict, latest: dict) -> dict:
        """憨豆盈亏摆在最显眼的地方 —— 抽奖说到底就是拿憨豆换憨豆，
        「一共抽了多少次」远不如「平均每抽亏多少」有用。"""
        draws = _num(total["draws"]) or 0
        cost = _num(total["cost"])
        beans = _num(total["gains"]["beans"])
        swapped = swapped_beans_total(total)
        profit, rate = profit_of(total)
        per = (lambda value: fmt(round(value / draws, 1)) if draws else "—")

        profit_color = "text-success" if profit >= 0 else "text-error"
        # 回本率：每花 100 憨豆收回多少。和净盈亏率是同一件事的两种说法，
        # 但「回本 105.8%」比「+5.8%」更直观
        payback = f"{beans / cost * 100:.1f}%" if cost else "—"

        rows = [
            {"component": "VRow", "content": [
                self.__stat("💸 累计消耗", f"{fmt(cost)}", "text-warning",
                            f"每抽 {per(cost)}"),
                self.__stat("🎁 累计获得", f"{fmt(beans)}", "text-info",
                            (f"档位 {fmt(beans - swapped)} + 折算 {fmt(swapped)}"
                             if swapped else f"每抽 {per(beans)}")),
                self.__stat("🚀 净盈亏", f"{'+' if profit >= 0 else ''}{fmt(profit)}",
                            profit_color,
                            f"每抽 {'+' if profit >= 0 else ''}{per(profit)} 憨豆"),
                self.__stat("📈 回本率", payback, profit_color,
                            f"净盈亏率 {'+' if rate >= 0 else ''}{rate:.1f}%"),
            ]},
            {"component": "VDivider", "props": {"class": "my-3"}},
            {"component": "VRow", "content": [
                self.__stat("🎲 累计抽奖", f"{fmt(draws)} 抽"),
                self.__stat("🕐 最近运行", str(latest.get("date") or "—"),
                            hint=str(latest.get("status") or "")),
                self.__stat("💰 最近余额", f"{fmt(latest.get('balance') or 0)}"),
                self.__stat("⏱ 最近一轮", f"{fmt(latest.get('draws') or 0)} 抽",
                            hint=str(latest.get("duration") or "")),
            ]},
        ]

        return {
            "component": "VCard", "props": {"variant": "flat", "class": "mb-4"},
            "content": [
                {"component": "VCardItem", "props": {"class": "pa-4 pb-0"}, "content": [
                    {"component": "VCardTitle", "props": {"class": "d-flex align-center text-h6"},
                     "content": [
                         {"component": "VIcon", "props": {"color": "primary", "class": "mr-3"},
                          "text": "mdi-chart-box"},
                         {"component": "span", "text": "憨豆盈亏（历史总计）"},
                     ]},
                ]},
                {"component": "VCardText", "content": rows},
            ],
        }

    def __gain_card(self, total: dict) -> dict:
        """憨豆之外的东西。这些换算不成憨豆，但彩虹ID、补签卡、上传量本来就是
        抽奖真正想要的东西 —— 没中过也要摆出来，「邀请 0」本身就是信息。"""
        tiles = []
        for key in ("invite", "rainbow", "vip", "makeup", "upload", "rename"):
            meta = PRIZE_META[key]
            bucket = total["prizes"].get(key) or {}
            count = _num(bucket.get("count"))

            if key == "vip":
                # 折算之后天数被扣回 0，拿次数当主值才看得出到底中过几次
                value = f"{fmt(count)} 次"
                parts = []
                days = _num(total["gains"].get("vip"))
                swapped = _num(bucket.get("swappedBeans"))
                if days:
                    parts.append(f"{fmt(days)} 天")
                if swapped:
                    parts.append(f"折算 {fmt(swapped)} 憨豆")
                hint = " · ".join(parts) or ("没中过" if not count else "—")
            else:
                amount = _num(total["gains"].get(key))
                value = f"{fmt(amount)}{' ' + meta['unit'] if meta['unit'] else ''}"
                hint = f"{fmt(count)} 次" if count else "没中过"

            tiles.append(self.__stat(f"{meta['icon']} {meta['name']}", value,
                                     hint=hint, cols=6, md=2))

        # 站点哪天加了新奖品，认不出来的会落在这一类，别让它凭空消失
        other = total["prizes"].get("unknown") or {}
        if _num(other.get("count")):
            tiles.append(self.__stat(f"{PRIZE_META['unknown']['icon']} 其他奖品",
                                     f"{fmt(other['count'])} 次",
                                     hint="站点新加的奖品？", cols=6, md=2))

        return {
            "component": "VCard", "props": {"variant": "flat", "class": "mb-4"},
            "content": [
                {"component": "VCardItem", "props": {"class": "pa-4 pb-0"}, "content": [
                    {"component": "VCardTitle", "props": {"class": "d-flex align-center text-h6"},
                     "content": [
                         {"component": "VIcon", "props": {"color": "teal", "class": "mr-3"},
                          "text": "mdi-package-variant-closed"},
                         {"component": "span", "text": "奖品累计（憨豆以外）"},
                     ]},
                ]},
                {"component": "VCardText", "content": [
                    {"component": "VRow", "content": tiles}]},
            ],
        }

    def __prize_card(self, total: dict) -> dict:
        """奖项明细。档位从「挤在一个格子里用顿号拼」改成每档一行，
        并给每一行算出它到底折合多少憨豆 —— 之前那一列混着天 / 个 / GB，
        看不出哪一档才是真正在回血。"""
        draws = _num(total["draws"]) or 0
        rows = []

        for prize_type, bucket in sorted(total["prizes"].items(),
                                         key=lambda item: _num(item[1].get("count")),
                                         reverse=True):
            count = _num(bucket.get("count"))
            if not count:
                continue
            meta = PRIZE_META.get(prize_type, PRIZE_META["unknown"])
            unit = meta["unit"] or ("憨豆" if prize_type in ("beans", "magic") else "")
            bean_gain = self.__bean_gain(prize_type, bucket)

            amount = f"{fmt(bucket.get('value'))} {unit}".strip()
            if _num(bucket.get("swappedBeans")):
                amount = f"另折算 {fmt(bucket['swappedBeans'])} 憨豆" if not _num(
                    bucket.get("value")) else f"{amount} + 折算 {fmt(bucket['swappedBeans'])}"

            rows.append({"component": "tr", "props": {"class": "font-weight-medium"}, "content": [
                {"component": "td", "text": f"{meta['icon']} {meta['name']}"},
                {"component": "td", "text": f"{fmt(count)} 次"},
                {"component": "td", "text": f"{count / draws * 100:.2f}%" if draws else "—"},
                {"component": "td", "text": amount},
                {"component": "td", "text": f"{fmt(bean_gain)}" if bean_gain else "—"},
            ]})

            # 档位子行。憨豆小计只对能折成憨豆的档位算 —— 档位标签本身就是
            # 「金额 + 单位」，数字直接从里面取；天 / 个 / GB 这些留空不硬凑
            for label, tier_count in sorted((bucket.get("tiers") or {}).items(),
                                            key=lambda item: _num(item[1]), reverse=True):
                tier_count = _num(tier_count)
                tier_beans = ""
                if bean_gain:
                    each = first_number(label)
                    if each is not None:
                        tier_beans = fmt(each * tier_count)
                rows.append({"component": "tr", "content": [
                    {"component": "td", "props": {"class": "ps-8 text-medium-emphasis"},
                     "text": f"└ {label}"},
                    {"component": "td", "props": {"class": "text-medium-emphasis"},
                     "text": f"{fmt(tier_count)} 次"},
                    {"component": "td", "props": {"class": "text-medium-emphasis"},
                     "text": f"{tier_count / draws * 100:.2f}%" if draws else "—"},
                    {"component": "td", "text": ""},
                    {"component": "td", "props": {"class": "text-medium-emphasis"},
                     "text": tier_beans},
                ]})

        total_beans = sum(self.__bean_gain(t, b) for t, b in total["prizes"].items())
        rows.append({"component": "tr", "props": {"class": "font-weight-bold"}, "content": [
            {"component": "td", "text": "合计"},
            {"component": "td", "text": f"{fmt(draws)} 抽"},
            {"component": "td", "text": "100%"},
            {"component": "td", "text": ""},
            {"component": "td", "text": fmt(total_beans)},
        ]})

        return {
            "component": "VCard", "props": {"variant": "flat", "class": "mb-4"},
            "content": [
                {"component": "VCardItem", "props": {"class": "pa-4 pb-0"}, "content": [
                    {"component": "VCardTitle", "props": {"class": "d-flex align-center text-h6"},
                     "content": [
                         {"component": "VIcon", "props": {"color": "warning", "class": "mr-3"},
                          "text": "mdi-gift"},
                         {"component": "span", "text": "奖项明细"},
                     ]},
                ]},
                {"component": "VCardText", "content": [
                    {"component": "VTable", "props": {"hover": True, "density": "compact"},
                     "content": [
                         {"component": "thead", "content": [{"component": "tr", "content": [
                             {"component": "th", "props": {"class": "text-start"}, "text": "奖项 / 档位"},
                             {"component": "th", "props": {"class": "text-start"}, "text": "次数"},
                             {"component": "th", "props": {"class": "text-start"}, "text": "实测占比"},
                             {"component": "th", "props": {"class": "text-start"}, "text": "累计"},
                             {"component": "th", "props": {"class": "text-start"}, "text": "折合憨豆"},
                         ]}]},
                         {"component": "tbody", "content": rows},
                     ]},
                    {"component": "div", "props": {"class": "text-caption text-disabled mt-2"},
                     "text": "「折合憨豆」只算真进账的憨豆：彩虹ID / 补签卡 / 上传量的单位是天 / 个 / GB，"
                             "换算不了也不硬凑；VIP 那一行是被站点折算成的憨豆。这一列合计等于「累计获得」。"},
                ]},
            ],
        }

    def __jackpot_card(self, total: dict) -> Optional[dict]:
        """大奖名册。780,000 憨豆和 VIP 这两档几千抽才碰一次，日志滚掉就再也
        找不回来了。

        名册里带时刻的那些是从油猴版备份合并进来的，MP 这边不产生；但「一共
        中过几次」在 prizes 里一直是准的。两个数摆在一起，才看得出名册缺了
        多少条 —— 只摆名册的话，中过 31 次却只显示 1 条，看着像丢了数据。"""
        jackpots = [item for item in (total.get("jackpots") or []) if isinstance(item, dict)]
        total_hits, vip_hits, bean_hits = jackpot_counts(total)
        if not jackpots and not total_hits:
            return None

        missing = max(0, total_hits - len(jackpots))
        title = f"大奖名册（中过 {fmt(total_hits)} 次"
        title += f"，{fmt(len(jackpots))} 条有时间记录）" if jackpots else "）"

        breakdown = (f"⭐ VIP {fmt(vip_hits)} 次 · "
                     f"💰 {fmt(JACKPOT_BEANS)} 以上憨豆 {fmt(bean_hits)} 次")
        if missing:
            breakdown += (f" —— 其中 {fmt(missing)} 次没有时间记录："
                          "名册只在油猴版面板上产生，MP 这边只能靠导入备份带过来，"
                          "在此之前中的那些只剩次数。")

        rows = []
        for item in jackpots[:100]:
            at = item.get("at")
            try:
                when = datetime.fromtimestamp(at / 1000,
                                              pytz.timezone(settings.TZ)).strftime("%Y-%m-%d %H:%M:%S")
            except Exception:
                when = "—"
            rows.append({"component": "tr", "content": [
                {"component": "td", "text": when},
                {"component": "td", "text": str(item.get("text") or "")},
            ]})

        return {
            "component": "VCard", "props": {"variant": "flat", "class": "mb-4"},
            "content": [
                {"component": "VCardItem", "props": {"class": "pa-4 pb-0"}, "content": [
                    {"component": "VCardTitle", "props": {"class": "d-flex align-center text-h6"},
                     "content": [
                         {"component": "VIcon", "props": {"color": "amber", "class": "mr-3"},
                          "text": "mdi-trophy"},
                         {"component": "span", "text": title},
                     ]},
                ]},
                {"component": "VCardText", "content": [
                    {"component": "div", "props": {"class": "text-caption text-medium-emphasis mb-3"},
                     "text": breakdown},
                ] + ([
                    {"component": "VTable", "props": {"hover": True, "density": "compact"},
                     "content": [
                         {"component": "thead", "content": [{"component": "tr", "content": [
                             {"component": "th", "props": {"class": "text-start"}, "text": "时间"},
                             {"component": "th", "props": {"class": "text-start"}, "text": "中的什么"},
                         ]}]},
                         {"component": "tbody", "content": rows},
                     ]},
                ] if rows else [])},
            ],
        }

    def __run_card(self, history: List[dict]) -> dict:
        rows = []
        for record in history:
            record_profit = _num(record.get("profit"))
            record_draws = _num(record.get("draws"))
            per = fmt(round(record_profit / record_draws, 1)) if record_draws else "—"
            rows.append({"component": "tr", "content": [
                {"component": "td", "text": str(record.get("date") or "")},
                {"component": "td", "text": fmt(record_draws)},
                {"component": "td", "text": fmt(record.get("cost") or 0)},
                {"component": "td", "text": (
                    f"{fmt(record.get('beans') or 0)}"
                    + (f"（含折算 {fmt(record['swapped'])}）" if _num(record.get("swapped")) else ""))},
                {"component": "td", "content": [{"component": "VChip", "props": {
                    "color": "success" if record_profit >= 0 else "error",
                    "size": "small", "variant": "tonal"},
                    "text": f"{'+' if record_profit >= 0 else ''}{fmt(record_profit)}"
                            f"（{record.get('rate', 0)}%）"}]},
                {"component": "td", "text": f"{'+' if record_profit >= 0 else ''}{per}"},
                {"component": "td", "text": fmt(record.get("balance") or 0)},
                {"component": "td", "text": str(record.get("duration") or "")},
                {"component": "td", "text": str(record.get("status") or "")},
            ]})

        return {
            "component": "VCard", "props": {"variant": "flat"},
            "content": [
                {"component": "VCardItem", "props": {"class": "pa-4 pb-0"}, "content": [
                    {"component": "VCardTitle", "props": {"class": "d-flex align-center text-h6"},
                     "content": [
                         {"component": "VIcon", "props": {"color": "primary", "class": "mr-3"},
                          "text": "mdi-history"},
                         {"component": "span", "text": "运行记录"},
                     ]},
                ]},
                {"component": "VCardText", "content": [
                    {"component": "VTable", "props": {"hover": True, "density": "compact"},
                     "content": [
                         {"component": "thead", "content": [{"component": "tr", "content": [
                             {"component": "th", "props": {"class": "text-start"}, "text": "时间"},
                             {"component": "th", "props": {"class": "text-start"}, "text": "抽数"},
                             {"component": "th", "props": {"class": "text-start"}, "text": "消耗"},
                             {"component": "th", "props": {"class": "text-start"}, "text": "获得憨豆"},
                             {"component": "th", "props": {"class": "text-start"}, "text": "盈亏"},
                             {"component": "th", "props": {"class": "text-start"}, "text": "每抽盈亏"},
                             {"component": "th", "props": {"class": "text-start"}, "text": "结束余额"},
                             {"component": "th", "props": {"class": "text-start"}, "text": "时长"},
                             {"component": "th", "props": {"class": "text-start"}, "text": "状态"},
                         ]}]},
                         {"component": "tbody", "content": rows},
                     ]},
                ]},
            ],
        }

    def get_page(self) -> List[dict]:
        total = normalize_stats(self.get_data("total"))
        history = self.get_data("history") or []
        if not isinstance(history, list):
            history = [history]

        if not total["draws"] and not history:
            return [self.__status_card(), {
                "component": "VCard", "props": {"variant": "flat", "class": "mb-4"},
                "content": [{"component": "VCardItem", "props": {"class": "pa-6"}, "content": [
                    {"component": "VCardTitle", "props": {"class": "d-flex align-center text-h6"},
                     "content": [
                         {"component": "VIcon", "props": {"color": "primary", "class": "mr-3"},
                          "text": "mdi-database-remove"},
                         {"component": "span", "text": "暂无抽奖记录"},
                     ]},
                ]}],
            }]

        history = sorted(history, key=lambda item: item.get("date") or "", reverse=True)
        cards = [
            self.__status_card(),
            self.__overview_card(total, history[0] if history else {}),
            self.__gain_card(total),
            self.__prize_card(total),
        ]
        jackpot = self.__jackpot_card(total)
        if jackpot:
            cards.append(jackpot)
        cards.append(self.__run_card(history))
        return cards

    def __shutdown_scheduler(self):
        """收掉「立即运行一次」那个一次性调度器。不碰抽奖循环。"""
        try:
            if self._scheduler:
                self._scheduler.remove_all_jobs()
                if self._scheduler.running:
                    self._scheduler.shutdown()
                self._scheduler = None
        except Exception as err:
            logger.error(f"关闭调度器失败：{err}")

    def stop_service(self):
        """停用 / 重载插件：让抽奖循环自己收工（成绩已在每轮结束时落盘），再收调度器。

        MoviePilot 只在禁用插件、重载插件、退出时走这里；保存配置不走。"""
        self._stop_source = "插件停用 / 重载"
        if self._stop_event:
            self._stop_event.set()
        self.__shutdown_scheduler()
