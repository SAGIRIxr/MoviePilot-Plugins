# -*- coding: utf-8 -*-
import re
import time
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


class DiscordMsgForward(_PluginBase):
    # 插件名称
    plugin_name = "Discord消息转发"
    # 插件描述
    plugin_desc = "将 Discord 频道新消息转发到指定通知渠道（可多选），支持频道下拉选择、关键词/作者/屏蔽词过滤、图片转发、消息聚合、免打扰时段、自定义模板与失败告警。"
    # 插件图标
    plugin_icon = "https://raw.githubusercontent.com/SAGIRIxr/MoviePilot-Plugins/main/icons/DiscordForward_A.png"
    # 插件版本
    plugin_version = "3.0.0"
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
    _onlyonce = False
    # Bot Token
    _token = ""
    # 下拉选择的频道 ID 列表
    _channel_ids: List[str] = []
    # 手动/高级频道规则：每行 频道ID#备注#关键词#转发渠道
    _channels = ""
    # 轮询间隔（分钟）
    _interval = 5
    # 全局转发渠道（多选，空=全部启用的渠道）
    _notify_channels: List[str] = []
    # 全局关键词过滤（白名单）：多个用逗号分隔，留空转发全部
    _keywords = ""
    # 屏蔽词（黑名单）：命中任一屏蔽词不转发
    _blocked_keywords = ""
    # 只转发这些作者（留空不限制）
    _author_include = ""
    # 屏蔽这些作者
    _author_exclude = ""
    # 内容提取正则（如礼包码，可选）
    _code_regex = ""
    # 通知类型
    _msgtype = "Plugin"
    # 消息聚合：一次轮询的多条消息合并为一条通知
    _aggregate = True
    # 图片转发
    _forward_image = True
    # 失败告警
    _fail_alert = True
    # 免打扰时段，如 23:00-08:00，留空不启用
    _quiet_hours = ""
    # 通知标题模板
    _title_template = DEFAULT_TITLE_TEMPLATE
    # 通知内容模板
    _text_template = DEFAULT_TEXT_TEMPLATE
    # 是否使用系统代理
    _use_proxy = True
    # 历史记录保留天数
    _history_days = 30

    # 定时器
    _scheduler: Optional[BackgroundScheduler] = None

    def init_plugin(self, config: dict = None):
        # 停止现有任务
        self.stop_service()

        if config:
            self._enabled = config.get("enabled") or False
            self._onlyonce = config.get("onlyonce") or False
            self._token = (config.get("token") or "").strip()
            self._channel_ids = config.get("channel_ids") or []
            self._channels = config.get("channels") or ""
            self._interval = int(config.get("interval") or 5)
            self._notify_channels = config.get("notify_channels") or []
            self._keywords = (config.get("keywords") or "").strip()
            self._blocked_keywords = (config.get("blocked_keywords") or "").strip()
            self._author_include = (config.get("author_include") or "").strip()
            self._author_exclude = (config.get("author_exclude") or "").strip()
            self._code_regex = (config.get("code_regex") or "").strip()
            self._msgtype = config.get("msgtype") or "Plugin"
            self._aggregate = config.get("aggregate") if config.get("aggregate") is not None else True
            self._forward_image = config.get("forward_image") if config.get("forward_image") is not None else True
            self._fail_alert = config.get("fail_alert") if config.get("fail_alert") is not None else True
            self._quiet_hours = (config.get("quiet_hours") or "").strip()
            self._title_template = config.get("title_template") or DEFAULT_TITLE_TEMPLATE
            self._text_template = config.get("text_template") or DEFAULT_TEXT_TEMPLATE
            self._use_proxy = config.get("use_proxy") if config.get("use_proxy") is not None else True
            self._history_days = int(config.get("history_days") or 30)

        # 保存配置后：后台刷新频道列表；如勾选则立即运行一次
        if self._token or self._onlyonce:
            self._scheduler = BackgroundScheduler(timezone=settings.TZ)
            now = datetime.now(tz=pytz.timezone(settings.TZ))
            if self._token:
                self._scheduler.add_job(func=self.refresh_channel_options, trigger='date',
                                        run_date=now + timedelta(seconds=3),
                                        name="刷新Discord频道列表")
            if self._onlyonce:
                logger.info("Discord消息转发服务启动，立即运行一次")
                self._scheduler.add_job(func=self.check_messages, trigger='date',
                                        run_date=now + timedelta(seconds=8),
                                        name="Discord消息转发")
                self._onlyonce = False
                self.__update_config()
            if self._scheduler.get_jobs():
                self._scheduler.start()

    def __update_config(self):
        """将当前配置写回插件配置（用于重置 onlyonce）"""
        self.update_config({
            "enabled": self._enabled,
            "onlyonce": self._onlyonce,
            "token": self._token,
            "channel_ids": self._channel_ids,
            "channels": self._channels,
            "interval": self._interval,
            "notify_channels": self._notify_channels,
            "keywords": self._keywords,
            "blocked_keywords": self._blocked_keywords,
            "author_include": self._author_include,
            "author_exclude": self._author_exclude,
            "code_regex": self._code_regex,
            "msgtype": self._msgtype,
            "aggregate": self._aggregate,
            "forward_image": self._forward_image,
            "fail_alert": self._fail_alert,
            "quiet_hours": self._quiet_hours,
            "title_template": self._title_template,
            "text_template": self._text_template,
            "use_proxy": self._use_proxy,
            "history_days": self._history_days,
        })

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
                "User-Agent": "DiscordBot (MoviePilot-Plugin-DiscordMsgForward, 3.0)",
            },
            params=params,
            proxies=self.__get_proxies(),
            timeout=30,
        )
        return resp

    def refresh_channel_options(self):
        """拉取 Bot 可见的服务器与频道，缓存供配置页下拉选择"""
        if not self._token:
            return
        try:
            resp = self.__api_get("/users/@me/guilds")
            if resp.status_code != 200:
                logger.error(f"获取 Discord 服务器列表失败: HTTP {resp.status_code}")
                return
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
            logger.info(f"已刷新 Discord 频道列表，共 {len(options)} 个文字/公告频道，重新打开配置页即可选择")
        except Exception as e:
            logger.error(f"刷新 Discord 频道列表异常: {e}")

    def __parse_channels(self) -> List[dict]:
        """
        合并「下拉选择的频道」与「手动/高级规则」。
        手动行格式：频道ID#备注#关键词#转发渠道（后三段可省略，多值用 | 分隔）；
        同一频道 ID 手动行的规则优先。
        """
        meta: Dict[str, dict] = self.get_data("channel_meta") or {}
        channels: Dict[str, dict] = {}
        for cid in self._channel_ids or []:
            channels[cid] = {
                "id": cid,
                "name": (meta.get(cid) or {}).get("name") or cid,
                "keywords": None,
                "notify_channels": None,
            }
        for line in (self._channels or "").splitlines():
            line = line.strip()
            if not line or line.startswith("//"):
                continue
            parts = [p.strip() for p in line.split("#")]
            cid = parts[0]
            if not cid:
                continue
            channels[cid] = {
                "id": cid,
                "name": (parts[1] if len(parts) > 1 else "") or (meta.get(cid) or {}).get("name") or cid,
                "keywords": self.__split_multi(parts[2]) if len(parts) > 2 else None,
                "notify_channels": self.__split_multi(parts[3]) if len(parts) > 3 else None,
            }
        return list(channels.values())

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

    def __pass_filters(self, text: str, author: str, keywords: Optional[List[str]]) -> bool:
        """按顺序检查：作者白名单 → 作者黑名单 → 屏蔽词 → 关键词白名单"""
        include_authors = [a.lower() for a in self.__split_multi(self._author_include)]
        if include_authors and author.lower() not in include_authors:
            return False
        exclude_authors = [a.lower() for a in self.__split_multi(self._author_exclude)]
        if exclude_authors and author.lower() in exclude_authors:
            return False
        text_lower = text.lower()
        for blocked in self.__split_multi(self._blocked_keywords):
            if blocked.lower() in text_lower:
                return False
        if keywords is None:
            keywords = self.__split_multi(self._keywords)
        if keywords and not any(kw.lower() in text_lower for kw in keywords):
            return False
        return True

    def __extract_codes(self, text: str) -> List[str]:
        """按配置的正则提取内容（如礼包码）"""
        if not self._code_regex or not text:
            return []
        try:
            codes = re.findall(self._code_regex, text)
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

    def __render_template(self, template: str, variables: Dict[str, Any]) -> str:
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

    def __in_quiet_hours(self) -> bool:
        """判断当前是否处于免打扰时段（支持跨零点，如 23:00-08:00）"""
        if not self._quiet_hours:
            return False
        m = re.match(r"^(\d{1,2}):(\d{2})\s*-\s*(\d{1,2}):(\d{2})$", self._quiet_hours)
        if not m:
            logger.warning(f"免打扰时段格式无效（应为 23:00-08:00）：{self._quiet_hours}")
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
        """轮询所有配置频道的新消息并转发"""
        if not self._token:
            logger.error("未配置 Discord Bot Token")
            return
        channels = self.__parse_channels()
        if not channels:
            logger.error("未配置 Discord 频道")
            return

        quiet = self.__in_quiet_hours()
        history_items: List[dict] = []
        # 免打扰时段结束后先冲刷暂存消息
        if not quiet:
            history_items.extend(self.__flush_pending())

        last_ids: Dict[str, str] = self.get_data("last_ids") or {}
        meta: Dict[str, dict] = self.get_data("channel_meta") or {}
        pending: List[dict] = self.get_data("pending") or []
        success_count = 0
        fail_count = 0
        last_error = ""

        for channel in channels:
            cid, cname = channel["id"], channel["name"]
            try:
                last_id = last_ids.get(cid)
                if not last_id:
                    # 首次运行：只记录基线，不转发历史消息
                    resp = self.__api_get(f"/channels/{cid}/messages", params={"limit": 1})
                    if resp.status_code != 200:
                        fail_count += 1
                        last_error = self.__log_api_error(cid, cname, resp)
                        continue
                    msgs = resp.json()
                    last_ids[cid] = msgs[0]["id"] if msgs else "0"
                    success_count += 1
                    logger.info(f"频道 [{cname}] 首次运行，已记录基线消息ID：{last_ids[cid]}，此后的新消息才会转发")
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

                # 提取并过滤
                items = []
                for msg in msgs:
                    text = self.__extract_text(msg)
                    image = self.__extract_image(msg) if self._forward_image else None
                    if not text and not image:
                        continue
                    author = (msg.get("author") or {}).get("username") or "未知"
                    if not self.__pass_filters(text, author, channel["keywords"]):
                        logger.info(f"频道 [{cname}] 消息被过滤规则拦截，跳过")
                        continue
                    link = (f"https://discord.com/channels/{guild_id}/{cid}/{msg['id']}"
                            if guild_id else None)
                    items.append({
                        "text": text or "[图片]",
                        "author": author,
                        "time": self.__format_time(msg.get("timestamp")),
                        "image": image,
                        "codes": self.__extract_codes(text),
                        "link": link,
                    })
                if not items:
                    continue

                targets = channel["notify_channels"] or self._notify_channels
                if quiet:
                    # 免打扰时段：暂存，时段结束后汇总推送
                    for item in items:
                        pending.append({**item, "cname": cname, "targets": targets})
                    logger.info(f"频道 [{cname}] 处于免打扰时段，{len(items)} 条消息已暂存")
                    continue

                batches = [items] if self._aggregate else [[item] for item in items]
                for batch in batches:
                    record = self.__send_batch(cname, batch, targets)
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
        """冲刷免打扰时段暂存的消息，按频道汇总推送，返回历史记录项"""
        pending: List[dict] = self.get_data("pending") or []
        if not pending:
            return []
        records = []
        groups: Dict[str, List[dict]] = {}
        for item in pending:
            groups.setdefault(item.get("cname") or "未知频道", []).append(item)
        for cname, items in groups.items():
            record = self.__send_batch(cname, items, items[-1].get("targets"))
            if record:
                records.append(record)
        self.save_data("pending", [])
        logger.info(f"免打扰时段结束，已汇总推送暂存的 {len(pending)} 条消息")
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

    def __send_batch(self, cname: str, items: List[dict], targets: Optional[List[str]]) -> Optional[dict]:
        """将一批消息渲染为一条通知并发送到目标渠道，返回历史记录项"""
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
        title = self.__render_template(self._title_template, variables)
        text = self.__render_template(self._text_template, variables)

        mtype = getattr(NotificationType, self._msgtype, None) or NotificationType.Plugin
        if targets:
            for target in targets:
                self.post_message(mtype=mtype, title=title, text=text, image=image,
                                  link=link, source=target)
        else:
            self.post_message(mtype=mtype, title=title, text=text, image=image, link=link)
        logger.info(f"频道 [{cname}] {len(items)} 条消息已转发到 "
                    f"{targets or '全部渠道'}" + (f"，提取内容: {codes}" if codes else ""))
        return {
            "date": datetime.now(tz=pytz.timezone(settings.TZ)).strftime('%Y-%m-%d %H:%M:%S'),
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
            if self._fail_alert and state["streak"] >= FAIL_ALERT_THRESHOLD and not state.get("alerted"):
                mtype = getattr(NotificationType, self._msgtype, None) or NotificationType.Plugin
                title = "【Discord消息转发告警】"
                text = (f"已连续 {state['streak']} 次轮询全部失败，插件可能无法正常工作。\n"
                        f"请检查 Bot Token、系统代理和频道配置。\n"
                        f"最近错误：{(last_error or '未知')[:200]}")
                if self._notify_channels:
                    for target in self._notify_channels:
                        self.post_message(mtype=mtype, title=title, text=text, source=target)
                else:
                    self.post_message(mtype=mtype, title=title, text=text)
                state["alerted"] = True
                logger.warning("已发送连续失败告警通知")
        else:
            state = {"streak": 0, "alerted": False}
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
        pass

    def get_service(self) -> List[Dict[str, Any]]:
        """注册定时轮询服务"""
        if self._enabled and self._token and (self._channel_ids or self._channels):
            return [{
                "id": "DiscordMsgForward",
                "name": "Discord消息转发服务",
                "trigger": IntervalTrigger(minutes=max(1, self._interval)),
                "func": self.check_messages,
                "kwargs": {},
            }]
        return []

    @staticmethod
    def __notify_channel_options() -> List[dict]:
        """获取已启用的通知渠道选项"""
        try:
            return [{'title': f"{conf.name}", 'value': conf.name}
                    for conf in NotificationHelper().get_configs().values()]
        except Exception as e:
            logger.error(f"获取通知渠道列表出错: {e}")
            return []

    def get_form(self) -> Tuple[List[dict], Dict[str, Any]]:
        """拼装插件配置页面：返回 (页面配置, 默认数据结构)"""
        msgtype_options = [{'title': item.value, 'value': item.name} for item in NotificationType]
        channel_options = self.get_data("channel_options") or []
        return [
            {
                'component': 'VForm',
                'content': [
                    # 基础设置
                    {
                        'component': 'VCard',
                        'props': {'class': 'mt-0'},
                        'content': [
                            {'component': 'VCardTitle', 'props': {'class': 'd-flex align-center'}, 'content': [
                                {'component': 'VIcon', 'props': {'color': 'info', 'class': 'mr-2'}, 'text': 'mdi-cog'},
                                {'component': 'span', 'text': '基础设置'}
                            ]},
                            {'component': 'VDivider'},
                            {'component': 'VCardText', 'content': [
                                {'component': 'VRow', 'content': [
                                    {'component': 'VCol', 'props': {'cols': 12, 'md': 3}, 'content': [
                                        {'component': 'VSwitch', 'props': {'model': 'enabled', 'label': '启用插件', 'color': 'primary'}}]},
                                    {'component': 'VCol', 'props': {'cols': 12, 'md': 3}, 'content': [
                                        {'component': 'VSwitch', 'props': {'model': 'onlyonce', 'label': '立即运行一次', 'color': 'success'}}]},
                                    {'component': 'VCol', 'props': {'cols': 12, 'md': 3}, 'content': [
                                        {'component': 'VSwitch', 'props': {
                                            'model': 'use_proxy', 'label': '使用系统代理', 'color': 'warning',
                                            'hint': '国内环境访问 Discord 必须开启', 'persistent-hint': True}}]},
                                    {'component': 'VCol', 'props': {'cols': 12, 'md': 3}, 'content': [
                                        {'component': 'VTextField', 'props': {
                                            'model': 'interval', 'label': '轮询间隔(分钟)', 'type': 'number',
                                            'placeholder': '5', 'prepend-inner-icon': 'mdi-timer-outline'}}]},
                                ]},
                            ]}
                        ]
                    },
                    # Discord 设置
                    {
                        'component': 'VCard',
                        'props': {'class': 'mt-3'},
                        'content': [
                            {'component': 'VCardTitle', 'props': {'class': 'd-flex align-center'}, 'content': [
                                {'component': 'VIcon', 'props': {'color': 'info', 'class': 'mr-2'}, 'text': 'mdi-robot'},
                                {'component': 'span', 'text': 'Discord 设置'}
                            ]},
                            {'component': 'VDivider'},
                            {'component': 'VCardText', 'content': [
                                {'component': 'VRow', 'content': [
                                    {'component': 'VCol', 'props': {'cols': 12}, 'content': [
                                        {'component': 'VTextField', 'props': {
                                            'model': 'token', 'label': 'Bot Token',
                                            'placeholder': 'Discord 开发者平台创建的 Bot Token',
                                            'prepend-inner-icon': 'mdi-key', 'type': 'password',
                                            'autocomplete': 'new-password', 'clearable': True,
                                            'hint': '保存后会自动拉取 Bot 可见的频道列表，重新打开本页即可在下方直接勾选',
                                            'persistent-hint': True}}]},
                                ]},
                                {'component': 'VRow', 'content': [
                                    {'component': 'VCol', 'props': {'cols': 12}, 'content': [
                                        {'component': 'VSelect', 'props': {
                                            'model': 'channel_ids', 'label': '监听频道（下拉选择）',
                                            'prepend-inner-icon': 'mdi-pound',
                                            'multiple': True, 'chips': True, 'clearable': True,
                                            'items': channel_options,
                                            'no-data-text': '暂无频道数据：请先填写 Token 并保存，稍等几秒后重新打开本页',
                                            'hint': '列表为 Bot 所在服务器的文字/公告频道；也可在下方手动填写',
                                            'persistent-hint': True}}]},
                                ]},
                                {'component': 'VRow', 'content': [
                                    {'component': 'VCol', 'props': {'cols': 12}, 'content': [
                                        {'component': 'VTextarea', 'props': {
                                            'model': 'channels', 'label': '手动频道 / 高级规则（可选）',
                                            'placeholder': '每行一个频道：频道ID#备注#关键词#转发渠道（后三段可省略）\n'
                                                           '例：1234567890123456789#礼包码#code|gift#微信\n'
                                                           '同一频道在这里配置的规则优先于全局配置',
                                            'prepend-inner-icon': 'mdi-format-list-text', 'rows': 3,
                                            'persistent-placeholder': True, 'clearable': True}}]},
                                ]},
                            ]}
                        ]
                    },
                    # 转发设置
                    {
                        'component': 'VCard',
                        'props': {'class': 'mt-3'},
                        'content': [
                            {'component': 'VCardTitle', 'props': {'class': 'd-flex align-center'}, 'content': [
                                {'component': 'VIcon', 'props': {'color': 'info', 'class': 'mr-2'}, 'text': 'mdi-send'},
                                {'component': 'span', 'text': '转发设置'}
                            ]},
                            {'component': 'VDivider'},
                            {'component': 'VCardText', 'content': [
                                {'component': 'VRow', 'content': [
                                    {'component': 'VCol', 'props': {'cols': 12, 'md': 6}, 'content': [
                                        {'component': 'VSelect', 'props': {
                                            'model': 'notify_channels', 'label': '转发渠道（可多选）',
                                            'prepend-inner-icon': 'mdi-send-circle',
                                            'multiple': True, 'chips': True, 'clearable': True,
                                            'items': self.__notify_channel_options(),
                                            'hint': '留空 = 发送到全部启用的通知渠道',
                                            'persistent-hint': True}}]},
                                    {'component': 'VCol', 'props': {'cols': 12, 'md': 6}, 'content': [
                                        {'component': 'VSelect', 'props': {
                                            'model': 'msgtype', 'label': '通知类型',
                                            'prepend-inner-icon': 'mdi-bell-outline',
                                            'items': msgtype_options,
                                            'hint': '需在 设定→通知 中开启所选渠道对应类型的开关',
                                            'persistent-hint': True}}]},
                                ]},
                                {'component': 'VRow', 'content': [
                                    {'component': 'VCol', 'props': {'cols': 12, 'md': 3}, 'content': [
                                        {'component': 'VSwitch', 'props': {
                                            'model': 'aggregate', 'label': '消息聚合', 'color': 'info',
                                            'hint': '多条新消息合并为一条通知', 'persistent-hint': True}}]},
                                    {'component': 'VCol', 'props': {'cols': 12, 'md': 3}, 'content': [
                                        {'component': 'VSwitch', 'props': {
                                            'model': 'forward_image', 'label': '图片转发', 'color': 'info',
                                            'hint': '消息中的图片作为通知图片推送', 'persistent-hint': True}}]},
                                    {'component': 'VCol', 'props': {'cols': 12, 'md': 3}, 'content': [
                                        {'component': 'VSwitch', 'props': {
                                            'model': 'fail_alert', 'label': '失败告警', 'color': 'error',
                                            'hint': f'连续{FAIL_ALERT_THRESHOLD}次轮询失败时推送提醒', 'persistent-hint': True}}]},
                                    {'component': 'VCol', 'props': {'cols': 12, 'md': 3}, 'content': [
                                        {'component': 'VTextField', 'props': {
                                            'model': 'quiet_hours', 'label': '免打扰时段',
                                            'placeholder': '23:00-08:00，留空不启用',
                                            'prepend-inner-icon': 'mdi-sleep',
                                            'hint': '时段内消息暂存，结束后汇总推送', 'persistent-hint': True,
                                            'clearable': True}}]},
                                ]},
                            ]}
                        ]
                    },
                    # 过滤规则
                    {
                        'component': 'VCard',
                        'props': {'class': 'mt-3'},
                        'content': [
                            {'component': 'VCardTitle', 'props': {'class': 'd-flex align-center'}, 'content': [
                                {'component': 'VIcon', 'props': {'color': 'info', 'class': 'mr-2'}, 'text': 'mdi-filter'},
                                {'component': 'span', 'text': '过滤规则（可选，留空全部转发）'}
                            ]},
                            {'component': 'VDivider'},
                            {'component': 'VCardText', 'content': [
                                {'component': 'VRow', 'content': [
                                    {'component': 'VCol', 'props': {'cols': 12, 'md': 6}, 'content': [
                                        {'component': 'VTextField', 'props': {
                                            'model': 'keywords', 'label': '关键词（白名单）',
                                            'placeholder': '含任一关键词才转发，逗号或 | 分隔',
                                            'prepend-inner-icon': 'mdi-text-search', 'clearable': True}}]},
                                    {'component': 'VCol', 'props': {'cols': 12, 'md': 6}, 'content': [
                                        {'component': 'VTextField', 'props': {
                                            'model': 'blocked_keywords', 'label': '屏蔽词（黑名单）',
                                            'placeholder': '含任一屏蔽词不转发，逗号或 | 分隔',
                                            'prepend-inner-icon': 'mdi-text-box-remove', 'clearable': True}}]},
                                ]},
                                {'component': 'VRow', 'content': [
                                    {'component': 'VCol', 'props': {'cols': 12, 'md': 6}, 'content': [
                                        {'component': 'VTextField', 'props': {
                                            'model': 'author_include', 'label': '只转发这些作者',
                                            'placeholder': '按用户名精确匹配（不分大小写），逗号或 | 分隔',
                                            'prepend-inner-icon': 'mdi-account-check', 'clearable': True}}]},
                                    {'component': 'VCol', 'props': {'cols': 12, 'md': 6}, 'content': [
                                        {'component': 'VTextField', 'props': {
                                            'model': 'author_exclude', 'label': '屏蔽这些作者',
                                            'placeholder': '按用户名精确匹配（不分大小写），逗号或 | 分隔',
                                            'prepend-inner-icon': 'mdi-account-cancel', 'clearable': True}}]},
                                ]},
                            ]}
                        ]
                    },
                    # 高级选项
                    {
                        'component': 'VCard',
                        'props': {'class': 'mt-3'},
                        'content': [
                            {'component': 'VCardTitle', 'props': {'class': 'd-flex align-center'}, 'content': [
                                {'component': 'VIcon', 'props': {'color': 'info', 'class': 'mr-2'}, 'text': 'mdi-tune'},
                                {'component': 'span', 'text': '高级选项（可选，默认即可）'}
                            ]},
                            {'component': 'VDivider'},
                            {'component': 'VCardText', 'content': [
                                {'component': 'VRow', 'content': [
                                    {'component': 'VCol', 'props': {'cols': 12, 'md': 6}, 'content': [
                                        {'component': 'VTextField', 'props': {
                                            'model': 'code_regex', 'label': '内容提取正则（如礼包码）',
                                            'placeholder': '如：[A-Za-z0-9]{6,20}，留空不提取',
                                            'prepend-inner-icon': 'mdi-regex',
                                            'hint': '命中内容会在通知中单独列出，对应模板变量 {codes}',
                                            'persistent-hint': True, 'clearable': True}}]},
                                    {'component': 'VCol', 'props': {'cols': 12, 'md': 6}, 'content': [
                                        {'component': 'VTextField', 'props': {
                                            'model': 'history_days', 'label': '历史记录保留天数', 'type': 'number',
                                            'placeholder': '30', 'prepend-inner-icon': 'mdi-history'}}]},
                                ]},
                                {'component': 'VRow', 'content': [
                                    {'component': 'VCol', 'props': {'cols': 12, 'md': 4}, 'content': [
                                        {'component': 'VTextField', 'props': {
                                            'model': 'title_template', 'label': '标题模板',
                                            'placeholder': DEFAULT_TITLE_TEMPLATE,
                                            'prepend-inner-icon': 'mdi-format-title', 'clearable': True}}]},
                                    {'component': 'VCol', 'props': {'cols': 12, 'md': 8}, 'content': [
                                        {'component': 'VTextarea', 'props': {
                                            'model': 'text_template', 'label': '内容模板',
                                            'placeholder': DEFAULT_TEXT_TEMPLATE.replace("\n", "\\n"),
                                            'prepend-inner-icon': 'mdi-text', 'rows': 3,
                                            'hint': '变量：{channel} 频道、{author} 作者、{content} 正文、{codes} 提取内容、{time} 时间、{count} 条数；提取内容为空时含 {codes} 的行自动隐藏',
                                            'persistent-hint': True, 'clearable': True}}]},
                                ]},
                            ]}
                        ]
                    },
                    # 使用说明
                    {
                        'component': 'VCard',
                        'props': {'class': 'mt-3'},
                        'content': [
                            {'component': 'VCardTitle', 'props': {'class': 'd-flex align-center'}, 'content': [
                                {'component': 'VIcon', 'props': {'color': 'info', 'class': 'mr-2'}, 'text': 'mdi-information'},
                                {'component': 'span', 'text': '使用说明'}
                            ]},
                            {'component': 'VDivider'},
                            {'component': 'VCardText', 'content': [
                                {'component': 'VAlert', 'props': {
                                    'type': 'success', 'variant': 'tonal', 'class': 'mb-2',
                                    'text': '【三步上手】① 填 Bot Token 保存 → ② 重新打开本页，下拉勾选要监听的频道 → ③ 选转发渠道（留空发全部），启用即可。'}},
                                {'component': 'VAlert', 'props': {
                                    'type': 'info', 'variant': 'tonal', 'class': 'mb-2',
                                    'text': '【Bot 准备】Discord 开发者平台创建 Bot 并开启 MESSAGE CONTENT INTENT，用 OAuth2 URL（勾 View Channels + Read Message History）拉进自己的服务器。'
                                            '别人服务器的公告频道可先「关注」到自己服务器再监听。'}},
                                {'component': 'VAlert', 'props': {
                                    'type': 'info', 'variant': 'tonal',
                                    'text': '首次运行只记录基线、不转发历史消息；通知自带跳转链接，点开直达 Discord 原消息；交互渠道发送 /discord_check 可手动触发检查。'}},
                            ]}
                        ]
                    }
                ]
            }
        ], {
            "enabled": False,
            "onlyonce": False,
            "use_proxy": True,
            "interval": 5,
            "channel_ids": [],
            "notify_channels": [],
            "msgtype": "Plugin",
            "aggregate": True,
            "forward_image": True,
            "fail_alert": True,
            "quiet_hours": "",
            "title_template": DEFAULT_TITLE_TEMPLATE,
            "text_template": DEFAULT_TEXT_TEMPLATE,
            "history_days": 30,
            "token": "",
            "channels": "",
            "keywords": "",
            "blocked_keywords": "",
            "author_include": "",
            "author_exclude": "",
            "code_regex": "",
        }

    def get_page(self) -> List[dict]:
        """转发历史记录页面"""
        historys = self.get_data('history')
        if not historys:
            return [
                {
                    'component': 'VCard',
                    'props': {'variant': 'flat', 'class': 'mb-4'},
                    'content': [
                        {'component': 'VCardItem', 'props': {'class': 'pa-6'}, 'content': [
                            {'component': 'VCardTitle', 'props': {'class': 'd-flex align-center text-h6'}, 'content': [
                                {'component': 'VIcon', 'props': {'color': 'primary', 'class': 'mr-3'}, 'text': 'mdi-database-remove'},
                                {'component': 'span', 'text': '暂无转发记录'}
                            ]}
                        ]}
                    ]
                }
            ]
        if not isinstance(historys, list):
            historys = [historys]
        historys = sorted(historys, key=lambda x: x.get("date") or "", reverse=True)

        rows = []
        for h in historys:
            if h.get("codes"):
                codes_td = {'component': 'td', 'content': [
                    {'component': 'VChip', 'props': {
                        'color': 'success', 'size': 'small', 'variant': 'tonal'},
                     'text': h.get("codes")}
                ]}
            else:
                codes_td = {'component': 'td', 'text': '-'}
            rows.append({
                'component': 'tr',
                'content': [
                    {'component': 'td', 'text': h.get("date", "")},
                    {'component': 'td', 'text': h.get("channel", "")},
                    {'component': 'td', 'text': h.get("author", "")},
                    {'component': 'td', 'text': h.get("content", "")},
                    {'component': 'td', 'text': str(h.get("count", 1))},
                    codes_td,
                ]
            })

        return [
            {
                'component': 'VCard',
                'props': {'variant': 'flat', 'class': 'mb-4'},
                'content': [
                    {'component': 'VCardItem', 'props': {'class': 'pa-4'}, 'content': [
                        {'component': 'VCardTitle', 'props': {'class': 'd-flex align-center text-h6'}, 'content': [
                            {'component': 'VIcon', 'props': {'color': 'primary', 'class': 'mr-3'}, 'text': 'mdi-history'},
                            {'component': 'span', 'text': '转发历史记录'}
                        ]}
                    ]},
                    {'component': 'VCardText', 'content': [
                        {'component': 'VTable', 'props': {'hover': True}, 'content': [
                            {'component': 'thead', 'content': [
                                {'component': 'tr', 'content': [
                                    {'component': 'th', 'props': {'class': 'text-start'}, 'text': '时间'},
                                    {'component': 'th', 'props': {'class': 'text-start'}, 'text': '频道'},
                                    {'component': 'th', 'props': {'class': 'text-start'}, 'text': '发送者'},
                                    {'component': 'th', 'props': {'class': 'text-start'}, 'text': '内容'},
                                    {'component': 'th', 'props': {'class': 'text-start'}, 'text': '条数'},
                                    {'component': 'th', 'props': {'class': 'text-start'}, 'text': '提取内容'},
                                ]}
                            ]},
                            {'component': 'tbody', 'content': rows}
                        ]}
                    ]}
                ]
            }
        ]

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
