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
from app.plugins import _PluginBase
from app.log import logger
from app.schemas import NotificationType

# Discord REST API
DISCORD_API = "https://discord.com/api/v10"


class DiscordMsgForward(_PluginBase):
    # 插件名称
    plugin_name = "Discord消息转发"
    # 插件描述
    plugin_desc = "轮询 Discord 频道新消息并通过 MoviePilot 通知渠道转发（微信/TG等），支持关键词过滤与兑换码提取，适合游戏礼包码频道。"
    # 插件图标
    plugin_icon = "https://raw.githubusercontent.com/SAGIRIxr/MoviePilot-Plugins/main/icons/DiscordForward_A.png"
    # 插件版本
    plugin_version = "1.0.0"
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
    # 频道列表：每行一个，格式 频道ID 或 频道ID#备注名
    _channels = ""
    # 轮询间隔（分钟）
    _interval = 5
    # 关键词过滤：多个用逗号分隔，留空转发全部
    _keywords = ""
    # 兑换码提取正则（可选）
    _code_regex = ""
    # 通知类型
    _msgtype = "Plugin"
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
            self._channels = config.get("channels") or ""
            self._interval = int(config.get("interval") or 5)
            self._keywords = (config.get("keywords") or "").strip()
            self._code_regex = (config.get("code_regex") or "").strip()
            self._msgtype = config.get("msgtype") or "Plugin"
            self._use_proxy = config.get("use_proxy") if config.get("use_proxy") is not None else True
            self._history_days = int(config.get("history_days") or 30)

        # 立即运行一次
        if self._onlyonce:
            self._scheduler = BackgroundScheduler(timezone=settings.TZ)
            logger.info("Discord消息转发服务启动，立即运行一次")
            self._scheduler.add_job(func=self.check_messages, trigger='date',
                                    run_date=datetime.now(tz=pytz.timezone(settings.TZ)) + timedelta(seconds=3),
                                    name="Discord消息转发")
            self._onlyonce = False
            self.__update_config()
            if self._scheduler.get_jobs():
                self._scheduler.print_jobs()
                self._scheduler.start()

    def __update_config(self):
        """将当前配置写回插件配置（用于重置 onlyonce）"""
        self.update_config({
            "enabled": self._enabled,
            "onlyonce": self._onlyonce,
            "token": self._token,
            "channels": self._channels,
            "interval": self._interval,
            "keywords": self._keywords,
            "code_regex": self._code_regex,
            "msgtype": self._msgtype,
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

    def __parse_channels(self) -> List[Tuple[str, str]]:
        """解析频道配置，返回 [(频道ID, 备注名)] 列表"""
        channels = []
        for line in (self._channels or "").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "#" in line:
                cid, _, name = line.partition("#")
                channels.append((cid.strip(), name.strip() or cid.strip()))
            else:
                channels.append((line, line))
        return channels

    def __api_get(self, path: str, params: dict = None):
        """调用 Discord REST API"""
        resp = requests.get(
            f"{DISCORD_API}{path}",
            headers={
                "Authorization": f"Bot {self._token}",
                "User-Agent": "DiscordBot (MoviePilot-Plugin-DiscordMsgForward, 1.0)",
            },
            params=params,
            proxies=self.__get_proxies(),
            timeout=30,
        )
        return resp

    @staticmethod
    def __extract_text(msg: dict) -> str:
        """从消息对象中提取文本内容（正文 + embed + 附件链接）"""
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
            if url:
                parts.append(f"[附件] {url}")
        return "\n".join(parts)

    def __match_keywords(self, text: str) -> bool:
        """关键词过滤：留空放行全部，否则命中任一关键词才转发"""
        if not self._keywords:
            return True
        for kw in self._keywords.replace("，", ",").split(","):
            kw = kw.strip()
            if kw and kw.lower() in text.lower():
                return True
        return False

    def __extract_codes(self, text: str) -> List[str]:
        """按配置的正则提取兑换码"""
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
            logger.error(f"兑换码正则无效: {e}")
            return []

    @staticmethod
    def __format_time(iso_time: str) -> str:
        """Discord ISO 时间转本地时间字符串"""
        try:
            dt = datetime.fromisoformat(iso_time)
            return dt.astimezone(pytz.timezone(settings.TZ)).strftime('%Y-%m-%d %H:%M:%S')
        except Exception:
            return iso_time or ""

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

        last_ids: Dict[str, str] = self.get_data("last_ids") or {}
        history_items: List[dict] = []

        for cid, cname in channels:
            try:
                last_id = last_ids.get(cid)
                if not last_id:
                    # 首次运行：只记录基线，不转发历史消息
                    resp = self.__api_get(f"/channels/{cid}/messages", params={"limit": 1})
                    if resp.status_code != 200:
                        self.__log_api_error(cid, cname, resp)
                        continue
                    msgs = resp.json()
                    last_ids[cid] = msgs[0]["id"] if msgs else "0"
                    logger.info(f"频道 [{cname}] 首次运行，已记录基线消息ID：{last_ids[cid]}，此后的新消息才会转发")
                    continue

                resp = self.__api_get(f"/channels/{cid}/messages",
                                      params={"after": last_id, "limit": 100})
                if resp.status_code != 200:
                    self.__log_api_error(cid, cname, resp)
                    continue

                msgs = sorted(resp.json(), key=lambda m: int(m["id"]))
                if not msgs:
                    logger.info(f"频道 [{cname}] 无新消息")
                    continue

                logger.info(f"频道 [{cname}] 获取到 {len(msgs)} 条新消息")
                for msg in msgs:
                    last_ids[cid] = msg["id"]
                    item = self.__forward_message(cname, msg)
                    if item:
                        history_items.append(item)
            except Exception as e:
                logger.error(f"频道 [{cname}] 轮询异常: {e}")

        self.save_data("last_ids", last_ids)
        if history_items:
            self.__save_history(history_items)

    @staticmethod
    def __log_api_error(cid: str, cname: str, resp):
        hints = {
            401: "Token 无效，请检查 Bot Token",
            403: "Bot 无权限访问该频道（需要「查看频道」和「阅读消息历史」权限）",
            404: "频道不存在，请检查频道 ID",
        }
        hint = hints.get(resp.status_code, resp.text[:200] if resp.text else "")
        logger.error(f"频道 [{cname}]({cid}) API 请求失败: HTTP {resp.status_code} {hint}")

    def __forward_message(self, cname: str, msg: dict) -> Optional[dict]:
        """处理单条消息：过滤、提取兑换码、发送通知。返回历史记录项（未转发返回 None）"""
        text = self.__extract_text(msg)
        if not text:
            return None
        if not self.__match_keywords(text):
            logger.info(f"频道 [{cname}] 消息未命中关键词，跳过")
            return None

        author = (msg.get("author") or {}).get("username") or "未知"
        msg_time = self.__format_time(msg.get("timestamp"))
        codes = self.__extract_codes(text)

        lines = [text]
        if codes:
            lines.append("")
            lines.append("🎁 兑换码：" + " / ".join(codes))
        lines.append("")
        lines.append(f"👤 {author}  🕐 {msg_time}")

        mtype = getattr(NotificationType, self._msgtype, None) or NotificationType.Plugin
        self.post_message(
            mtype=mtype,
            title=f"【Discord | {cname}】",
            text="\n".join(lines),
        )
        logger.info(f"频道 [{cname}] 消息已转发" + (f"，提取到兑换码: {codes}" if codes else ""))
        return {
            "date": datetime.now(tz=pytz.timezone(settings.TZ)).strftime('%Y-%m-%d %H:%M:%S'),
            "channel": cname,
            "author": author,
            "content": text if len(text) <= 200 else text[:200] + "…",
            "codes": " / ".join(codes),
        }

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

    # ---------------- MoviePilot 接口 ----------------
    def get_state(self) -> bool:
        return self._enabled

    @staticmethod
    def get_command() -> List[Dict[str, Any]]:
        pass

    def get_api(self) -> List[Dict[str, Any]]:
        pass

    def get_service(self) -> List[Dict[str, Any]]:
        """注册定时轮询服务"""
        if self._enabled and self._token and self._channels:
            return [{
                "id": "DiscordMsgForward",
                "name": "Discord消息转发服务",
                "trigger": IntervalTrigger(minutes=max(1, self._interval)),
                "func": self.check_messages,
                "kwargs": {},
            }]
        return []

    def get_form(self) -> Tuple[List[dict], Dict[str, Any]]:
        """拼装插件配置页面：返回 (页面配置, 默认数据结构)"""
        msgtype_options = [{'title': item.value, 'value': item.name} for item in NotificationType]
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
                                {'component': 'VRow', 'content': [
                                    {'component': 'VCol', 'props': {'cols': 12, 'md': 6}, 'content': [
                                        {'component': 'VSelect', 'props': {
                                            'model': 'msgtype', 'label': '通知类型',
                                            'prepend-inner-icon': 'mdi-bell-outline',
                                            'items': msgtype_options}}]},
                                    {'component': 'VCol', 'props': {'cols': 12, 'md': 6}, 'content': [
                                        {'component': 'VTextField', 'props': {
                                            'model': 'history_days', 'label': '历史记录保留天数', 'type': 'number',
                                            'placeholder': '30', 'prepend-inner-icon': 'mdi-history'}}]},
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
                                            'autocomplete': 'new-password', 'clearable': True}}]},
                                ]},
                                {'component': 'VRow', 'content': [
                                    {'component': 'VCol', 'props': {'cols': 12}, 'content': [
                                        {'component': 'VTextarea', 'props': {
                                            'model': 'channels', 'label': '监听频道',
                                            'placeholder': '每行一个频道，格式：频道ID 或 频道ID#备注名\n例如：1234567890123456789#WOS礼包码',
                                            'prepend-inner-icon': 'mdi-pound', 'rows': 3,
                                            'persistent-placeholder': True, 'clearable': True}}]},
                                ]},
                            ]}
                        ]
                    },
                    # 过滤与提取
                    {
                        'component': 'VCard',
                        'props': {'class': 'mt-3'},
                        'content': [
                            {'component': 'VCardTitle', 'props': {'class': 'd-flex align-center'}, 'content': [
                                {'component': 'VIcon', 'props': {'color': 'info', 'class': 'mr-2'}, 'text': 'mdi-filter'},
                                {'component': 'span', 'text': '过滤与提取（可选）'}
                            ]},
                            {'component': 'VDivider'},
                            {'component': 'VCardText', 'content': [
                                {'component': 'VRow', 'content': [
                                    {'component': 'VCol', 'props': {'cols': 12, 'md': 6}, 'content': [
                                        {'component': 'VTextField', 'props': {
                                            'model': 'keywords', 'label': '关键词过滤',
                                            'placeholder': '多个用逗号分隔，留空转发全部消息',
                                            'prepend-inner-icon': 'mdi-text-search',
                                            'hint': '消息包含任一关键词才转发，如：code,gift,兑换',
                                            'persistent-hint': True, 'clearable': True}}]},
                                    {'component': 'VCol', 'props': {'cols': 12, 'md': 6}, 'content': [
                                        {'component': 'VTextField', 'props': {
                                            'model': 'code_regex', 'label': '兑换码提取正则',
                                            'placeholder': '如：[A-Za-z0-9]{6,20}',
                                            'prepend-inner-icon': 'mdi-regex',
                                            'hint': '留空不提取；命中的兑换码会在通知中单独列出',
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
                                    'text': '【准备工作】① Discord 开发者平台创建应用和 Bot，拿到 Token，并在 Bot 页开启 MESSAGE CONTENT INTENT；'
                                            '② 用 OAuth2 URL 把 Bot 拉进自己的服务器（勾选 View Channels + Read Message History）；'
                                            '③ Discord 客户端开启开发者模式后，右键频道 → 复制频道 ID。别人的服务器无法拉 Bot，可用「关注公告频道」把消息转到自己服务器再监听。'}},
                                {'component': 'VAlert', 'props': {
                                    'type': 'info', 'variant': 'tonal',
                                    'text': '首次运行只记录基线、不转发历史消息，之后每次轮询转发新消息。转发走 MoviePilot 系统通知渠道，微信/TG 等在 设定→通知 里配置。'}},
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
            "msgtype": "Plugin",
            "history_days": 30,
            "token": "",
            "channels": "",
            "keywords": "",
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
                                    {'component': 'th', 'props': {'class': 'text-start'}, 'text': '兑换码'},
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
