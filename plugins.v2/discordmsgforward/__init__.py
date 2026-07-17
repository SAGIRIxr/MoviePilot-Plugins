# -*- coding: utf-8 -*-
import re
import time
import uuid
from datetime import datetime, timedelta
from typing import Any, List, Dict, Tuple, Optional

import pytz
import requests
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

from app.core.config import settings
from app.core.event import eventmanager, Event
from app.helper.notification import NotificationHelper
from app.plugins import _PluginBase
from app.log import logger
from app.schemas import NotificationType
from app.schemas.types import EventType

# Discord REST API
DISCORD_API = "https://discord.com/api/v10"

# 默认消息模板
DEFAULT_TITLE_TEMPLATE = "【Discord | {channel}】"
DEFAULT_TEXT_TEMPLATE = "{content}\n\n🎁 提取内容：{codes}\n\n👤 {author}  🕐 {time}"

# 图片附件扩展名
IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp")

# 连续失败多少次后告警
FAIL_ALERT_THRESHOLD = 3

# 规则默认值
RULE_DEFAULTS = {
    "id": "",
    "name": "",
    "enabled": True,
    "channels": [],           # 监听频道 ID 列表
    "notify_channels": [],    # 转发渠道，空=全部
    "keywords": "",
    "blocked_keywords": "",
    "author_include": "",
    "author_exclude": "",
    "code_regex": "",
    "aggregate": True,
    "forward_image": True,
    "quiet_hours": "",
    "title_template": "",
    "text_template": "",
}


class DiscordMsgForward(_PluginBase):
    # 插件名称
    plugin_name = "Discord消息转发"
    # 插件描述
    plugin_desc = "将 Discord 频道新消息按规则转发到指定通知渠道：规则卡片式管理，每条规则独立配置频道、渠道、过滤、模板与免打扰时段。"
    # 插件图标
    plugin_icon = "https://raw.githubusercontent.com/SAGIRIxr/MoviePilot-Plugins/main/icons/DiscordForward_A.png"
    # 插件版本
    plugin_version = "4.0.0"
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

    # 定时器
    _scheduler: Optional[BackgroundScheduler] = None

    def init_plugin(self, config: dict = None):
        # 停止现有任务
        self.stop_service()

        if config:
            self._enabled = config.get("enabled") or False
            self._token = (config.get("token") or "").strip()
            self._interval = int(config.get("interval") or 5)
            self._msgtype = config.get("msgtype") or "Plugin"
            self._fail_alert = config.get("fail_alert") if config.get("fail_alert") is not None else True
            self._use_proxy = config.get("use_proxy") if config.get("use_proxy") is not None else True
            self._history_days = int(config.get("history_days") or 30)
            self._rules = [self.__norm_rule(r) for r in (config.get("rules") or [])]

        # 保存配置后：后台刷新频道列表缓存
        if self._token:
            self._scheduler = BackgroundScheduler(timezone=settings.TZ)
            self._scheduler.add_job(func=self.refresh_channel_options, trigger='date',
                                    run_date=datetime.now(tz=pytz.timezone(settings.TZ)) + timedelta(seconds=3),
                                    name="刷新Discord频道列表")
            self._scheduler.start()

    @staticmethod
    def __norm_rule(rule: dict) -> dict:
        """补齐规则默认字段"""
        merged = {**RULE_DEFAULTS, **(rule or {})}
        if not merged.get("id"):
            merged["id"] = uuid.uuid4().hex[:8]
        return merged

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

    def __api_get(self, path: str, params: dict = None):
        """调用 Discord REST API"""
        resp = requests.get(
            f"{DISCORD_API}{path}",
            headers={
                "Authorization": f"Bot {self._token}",
                "User-Agent": "DiscordBot (MoviePilot-Plugin-DiscordMsgForward, 4.0)",
            },
            params=params,
            proxies=self.__get_proxies(),
            timeout=30,
        )
        return resp

    def refresh_channel_options(self) -> List[dict]:
        """拉取 Bot 可见的服务器与频道，缓存供前端下拉选择"""
        if not self._token:
            return []
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
        渲染消息模板。支持变量：{channel} {author} {content} {codes} {time} {count}
        提取内容为空时自动去掉包含 {codes} 的整行；{content} 最后替换，避免正文里的花括号被二次替换。
        """
        if not variables.get("codes"):
            template = "\n".join(
                line for line in template.splitlines() if "{codes}" not in line)
        for key in ("channel", "author", "codes", "time", "count"):
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
        now = datetime.now(tz=pytz.timezone(settings.TZ)).time()
        start = now.replace(hour=int(m.group(1)), minute=int(m.group(2)), second=0, microsecond=0)
        end = now.replace(hour=int(m.group(3)), minute=int(m.group(4)), second=0, microsecond=0)
        if start <= end:
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

    # ---------------- 核心逻辑 ----------------
    def check_messages(self):
        """轮询所有规则涉及的频道，按规则分发转发"""
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

        history_items: List[dict] = []
        # 先冲刷已结束免打扰时段的暂存消息
        history_items.extend(self.__flush_pending())

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

                resp = self.__api_get(f"/channels/{cid}/messages",
                                      params={"after": last_id, "limit": 100})
                if resp.status_code != 200:
                    fail_count += 1
                    last_error = self.__log_api_error(cid, cname, resp)
                    continue
                success_count += 1

                msgs = sorted(resp.json(), key=lambda m: int(m["id"]))
                if not msgs:
                    continue
                logger.info(f"频道 [{cname}] 获取到 {len(msgs)} 条新消息")
                last_ids[cid] = msgs[-1]["id"]
                guild_id = self.__get_guild_id(cid, meta)

                # 预提取消息内容，再按各规则分发
                raw_items = []
                for msg in msgs:
                    text = self.__extract_text(msg)
                    image = self.__extract_image(msg)
                    if not text and not image:
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
                            continue
                        items.append({
                            **raw,
                            "image": raw["image"] if rule.get("forward_image") else None,
                            "codes": self.__extract_codes(rule.get("code_regex"), raw["text"]),
                        })
                    if not items:
                        continue
                    if self.__in_quiet_hours(rule.get("quiet_hours")):
                        for item in items:
                            pending.append({**item, "cname": cname, "rule_id": rule["id"]})
                        logger.info(f"规则 [{rule.get('name')}] 处于免打扰时段，{len(items)} 条消息已暂存")
                        continue
                    batches = [items] if rule.get("aggregate") else [[item] for item in items]
                    for batch in batches:
                        record = self.__send_batch(rule, cname, batch)
                        if record:
                            history_items.append(record)
            except Exception as e:
                fail_count += 1
                last_error = str(e)
                logger.error(f"频道 [{cname}] 轮询异常: {e}")

        self.save_data("last_ids", last_ids)
        self.save_data("channel_meta", meta)
        self.save_data("pending", pending)
        if history_items:
            self.__save_history(history_items)
        self.__update_fail_state(success_count, fail_count, last_error)

    def __flush_pending(self) -> List[dict]:
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
            record = self.__send_batch(rule_map[rule_id], cname, items)
            if record:
                records.append(record)
        if groups:
            flushed = sum(len(v) for v in groups.values())
            logger.info(f"免打扰时段结束，已汇总推送暂存的 {flushed} 条消息")
        self.save_data("pending", keep)
        return records

    @staticmethod
    def __log_api_error(cid: str, cname: str, resp) -> str:
        hints = {
            401: "Token 无效，请检查 Bot Token",
            403: "Bot 无权限访问该频道（需要「查看频道」和「阅读消息历史」权限）",
            404: "频道不存在，请检查频道 ID",
        }
        hint = hints.get(resp.status_code, resp.text[:200] if resp.text else "")
        error = f"频道 [{cname}]({cid}) API 请求失败: HTTP {resp.status_code} {hint}"
        logger.error(error)
        return error

    def __send_batch(self, rule: dict, cname: str, items: List[dict]) -> Optional[dict]:
        """将一批消息渲染为一条通知并发送到规则指定的渠道，返回历史记录项"""
        if not items:
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
        image = next((i["image"] for i in items if i.get("image")), None)
        link = next((i["link"] for i in reversed(items) if i.get("link")), None)

        variables = {
            "channel": cname,
            "author": "、".join(authors),
            "content": content,
            "codes": " / ".join(codes),
            "time": items[-1]["time"],
            "count": len(items),
        }
        title = self.__render_template(rule.get("title_template") or DEFAULT_TITLE_TEMPLATE, variables)
        text = self.__render_template(rule.get("text_template") or DEFAULT_TEXT_TEMPLATE, variables)

        targets = rule.get("notify_channels") or []
        mtype = getattr(NotificationType, self._msgtype, None) or NotificationType.Plugin
        if targets:
            for target in targets:
                self.post_message(mtype=mtype, title=title, text=text, image=image,
                                  link=link, source=target)
        else:
            self.post_message(mtype=mtype, title=title, text=text, image=image, link=link)
        logger.info(f"规则 [{rule.get('name')}] 频道 [{cname}] {len(items)} 条消息已转发到 "
                    f"{targets or '全部渠道'}" + (f"，提取内容: {codes}" if codes else ""))
        return {
            "date": datetime.now(tz=pytz.timezone(settings.TZ)).strftime('%Y-%m-%d %H:%M:%S'),
            "rule": rule.get("name") or rule.get("id"),
            "channel": cname,
            "author": variables["author"],
            "content": content if len(content) <= 200 else content[:200] + "…",
            "codes": variables["codes"],
            "count": len(items),
        }

    def __update_fail_state(self, success_count: int, fail_count: int, last_error: str):
        """维护连续失败计数，达到阈值时发送一次告警，恢复后自动重置"""
        state = self.get_data("fail_state") or {"streak": 0, "alerted": False}
        if fail_count > 0 and success_count == 0:
            state["streak"] = int(state.get("streak") or 0) + 1
            state["last_error"] = (last_error or "")[:200]
            if self._fail_alert and state["streak"] >= FAIL_ALERT_THRESHOLD and not state.get("alerted"):
                mtype = getattr(NotificationType, self._msgtype, None) or NotificationType.Plugin
                self.post_message(
                    mtype=mtype,
                    title="【Discord消息转发告警】",
                    text=(f"已连续 {state['streak']} 次轮询全部失败，插件可能无法正常工作。\n"
                          f"请检查 Bot Token、系统代理和频道配置。\n"
                          f"最近错误：{(last_error or '未知')[:200]}"),
                )
                state["alerted"] = True
                logger.warning("已发送连续失败告警通知")
        else:
            state = {"streak": 0, "alerted": False, "last_error": ""}
        self.save_data("fail_state", state)

    def __save_history(self, items: List[dict]):
        """保存转发历史并清理过期记录"""
        history = self.get_data("history") or []
        if not isinstance(history, list):
            history = [history]
        history.extend(items)

        retain_seconds = int(self._history_days or 30) * 24 * 60 * 60
        expired_timestamp = time.time() - retain_seconds
        cleaned = []
        for record in history:
            try:
                if datetime.strptime(record["date"], '%Y-%m-%d %H:%M:%S').timestamp() >= expired_timestamp:
                    cleaned.append(record)
            except Exception:
                logger.debug(f"忽略格式异常的转发历史记录: {record}")
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
                       for conf in NotificationHelper().get_configs().values()]
        except Exception as e:
            logger.error(f"获取通知渠道列表出错: {e}")
            options = []
        return {"options": options}

    @staticmethod
    def api_get_msgtypes() -> dict:
        """获取通知类型选项"""
        return {"options": [{"title": item.value, "value": item.name} for item in NotificationType]}

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
        return {
            "enabled": self._enabled,
            "token_set": bool(self._token),
            "rules_total": len(self._rules),
            "rules_enabled": len([r for r in self._rules if r.get("enabled")]),
            "fail_streak": int(fail_state.get("streak") or 0),
            "last_error": fail_state.get("last_error") or "",
            "pending_count": len(pending),
        }

    def api_check_now(self) -> dict:
        """立即执行一次检查（后台运行）"""
        if not self._token:
            return {"message": "未配置 Bot Token"}
        scheduler = BackgroundScheduler(timezone=settings.TZ)
        scheduler.add_job(func=self.check_messages, trigger='date',
                          run_date=datetime.now(tz=pytz.timezone(settings.TZ)) + timedelta(seconds=1),
                          name="Discord消息转发-手动检查")
        scheduler.start()
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
                r.get("enabled") and r.get("channels") for r in self._rules):
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
            if self._scheduler:
                self._scheduler.remove_all_jobs()
                if self._scheduler.running:
                    self._scheduler.shutdown()
                self._scheduler = None
        except Exception as e:
            logger.error(f"停止Discord消息转发服务出错: {e}")
