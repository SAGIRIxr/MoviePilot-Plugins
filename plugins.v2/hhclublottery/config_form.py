# -*- coding: utf-8 -*-
"""配置页。

单独拎出来是因为它长 —— 260 多行全是 Vuetify 组件的 JSON 拼装，和插件的
其余逻辑一点关系都没有（整个函数不碰 self）。混在 __init__.py 里，翻抽奖
逻辑时要一路滚过去。
"""
from typing import Any, Dict, List, Tuple

from app.core.config import settings

from .lottery import BIG_PRIZE_KINDS


def build_form() -> Tuple[List[dict], Dict[str, Any]]:
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
                            "model": "max_minutes", "label": "定时结束(分钟)", "type": "number",
                            "placeholder": "留空 = 不限时",
                            "hint": "到点收工，最多 1440（24 小时）", "persistent-hint": True}}),
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
                        col(6, {"component": "VSelect", "props": {
                            "model": "big_prize_kinds", "label": "中大奖即时推送",
                            "multiple": True, "chips": True, "clearable": True,
                            "items": [{"title": title, "value": value}
                                      for value, title in BIG_PRIZE_KINDS.items()],
                            "hint": "勾中的当场推一条，一样都不勾 = 不推",
                            "persistent-hint": True}}),
                        col(3, {"component": "VSwitch", "props": {
                            "model": "notify_periodic", "label": "定时战报", "color": "info",
                            "hint": "长跑时中途也播报一次", "persistent-hint": True}}),
                        col(3, {"component": "VTextField", "props": {
                            "model": "periodic_minutes", "label": "战报间隔(分钟)", "type": "number",
                            "hint": "别填得比这一轮跑的时间还长", "persistent-hint": True}}),
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
        "max_minutes": "",
        "clean_mail": False,
        "stop_on_vip": False,
        "stop_on_780k": False,
        "big_prize_kinds": list(BIG_PRIZE_KINDS),
        "notify_periodic": False,
        "periodic_minutes": 30,
        "use_proxy": False,
        "user_agent": "",
        "history_days": 90,
    }

# ---------------- 数据页 ----------------
