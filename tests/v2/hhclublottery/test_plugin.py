# -*- coding: utf-8 -*-
"""HHCLUB幸运大转盘：插件外壳。

配置页和数据页是纯拼装，出错只会在 MoviePilot 界面上表现为一片空白 ——
借 conftest.py 里的 app.* 桩件把插件类加载起来，把这两块、Cookie 取用逻辑
以及「插件 + 假站点」的整条链路都真跑一遍。
"""
import json
import types

import pytest

from mp_stubs import HH, PLUGIN_DIR, REPO_ROOT
from fake_site import FakeSite, start_site, stop_site, win

pytestmark = pytest.mark.v2

HHClubLottery = HH.HHClubLottery


# ============================================================
# 元数据与目录约定
# ============================================================

def test_metadata_matches_index():
    index = json.loads((REPO_ROOT / "package.v2.json").read_text(encoding="utf-8"))
    entry = index["HHClubLottery"]
    assert entry["version"] == HHClubLottery.plugin_version, "package.v2.json 的 version 必须和 plugin_version 一致"
    assert entry["name"] == HHClubLottery.plugin_name
    assert entry["author"] == HHClubLottery.plugin_author
    # 目录名必须是插件类名的小写
    assert PLUGIN_DIR.name == "HHClubLottery".lower()


def test_icon_exists():
    icon = HHClubLottery.plugin_icon.rsplit("/", 1)[-1]
    assert (REPO_ROOT / "icons" / icon).exists(), f"图标 {icon} 不在 icons/ 下"


# ============================================================
# 配置页
# ============================================================

def _collect_models(node, found):
    if isinstance(node, dict):
        model = (node.get("props") or {}).get("model")
        if model:
            found.add(model)
        for value in node.values():
            _collect_models(value, found)
    elif isinstance(node, list):
        for item in node:
            _collect_models(item, found)


def test_form_models_match_defaults(plugin):
    page, defaults = plugin.get_form()
    models = set()
    _collect_models(page, models)

    # 每个控件都要在默认值里有对应项，反之亦然 —— 少一边就是保存后读不回来，
    # 或者配置项根本没有界面入口
    assert models - set(defaults) == set(), f"控件有 model 但默认值里没有：{models - set(defaults)}"
    assert set(defaults) - models == set(), f"默认值有项但界面上没入口：{set(defaults) - models}"


def test_form_and_page_are_json_serializable(plugin):
    """配置页 / 数据页会被序列化成 JSON 发给前端，塞进去个不可序列化的值
    只会表现为界面一片空白。"""
    page, defaults = plugin.get_form()
    json.dumps(page, ensure_ascii=False)
    json.dumps(defaults, ensure_ascii=False)

    plugin.save_data("total", {"draws": 3, "cost": 6000, "gains": {"beans": 100},
                               "prizes": {"beans": {"count": 1, "value": 100,
                                                    "tiers": {"100 憨豆": 1}}}})
    plugin.save_data("history", [{"date": "2026-08-21 09:05:00", "draws": 3, "cost": 6000,
                                  "beans": 100, "profit": -5900, "rate": -98.3,
                                  "balance": 1000, "duration": "20秒", "status": "正常结束"}])
    json.dumps(plugin.get_page(), ensure_ascii=False)


def test_form_defaults_are_sane(plugin):
    _, defaults = plugin.get_form()
    assert defaults["enabled"] is False, "默认不能自动开跑，抽奖花的是真憨豆"
    assert defaults["onlyonce"] is False
    assert defaults["cookie_source"] == "manual"
    assert defaults["host"] == "hhanclub.net"
    assert defaults["follow_duration"] is True
    assert defaults["draws"] == 10


def test_form_cookie_source_options(plugin):
    page, _ = plugin.get_form()
    values = set()

    def walk(node):
        if isinstance(node, dict):
            props = node.get("props") or {}
            if props.get("model") == "cookie_source":
                values.update(item["value"] for item in props["items"])
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(page)
    assert values == {"manual", "cookiecloud", "site"}


def test_config_roundtrip():
    instance = HHClubLottery()
    instance.init_plugin({
        "enabled": True, "notify": False, "cron": "0 3 * * *",
        "cookie_source": "cookiecloud", "host": "hhanclub.net",
        "draws": 0, "reserve": 500000, "interval": 5.5, "follow_duration": False,
        "duration_buffer": 200, "max_minutes": 120, "clean_mail": True,
        "notify_big_prize": False, "big_prize_min_beans": 0,
        "notify_periodic": True, "periodic_minutes": 15,
        "use_proxy": True, "user_agent": "UA", "history_days": 30,
        "onlyonce": False,
    })
    assert instance.get_state() is True
    assert instance._draws == 0
    assert instance._reserve == 500000
    assert instance._follow_duration is False
    assert instance._notify is False
    assert instance._clean_mail is True
    assert instance._periodic_minutes == 15


# ============================================================
# Cookie 来源
# ============================================================

@pytest.mark.parametrize("host,expected", [
    ("hhanclub.net", "hhanclub.net"),
    ("https://hhanclub.net/lucky.php", "hhanclub.net"),
    ("www.hhanclub.net", "hhanclub.net"),
    ("HHANCLUB.NET:443", "hhanclub.net"),
    ("pt.example.com.cn", "example.com.cn"),
])
def test_short_domain(host, expected):
    assert HH._short_domain(host) == expected


def test_pick_domain_cookie():
    pick = HHClubLottery._HHClubLottery__pick_domain_cookie
    contents = {"hhanclub.net": "c_secure_uid=1", "m-team.cc": "x=1"}
    assert pick(contents, "hhanclub.net") == ("c_secure_uid=1", "hhanclub.net")
    # 用户填了子域名也要能命中
    assert pick({"hhanclub.net": "a=1"}, "pt.hhanclub.net")[0] == "a=1"
    assert pick(contents, "nowhere.net") == ("", "")
    assert pick({}, "hhanclub.net") == ("", "")


def test_resolve_cookie_manual(plugin):
    plugin._cookie_source = "manual"
    plugin._cookie = ""
    cookie, note = plugin._HHClubLottery__resolve_cookie()
    assert cookie == ""
    assert "没有填写" in note

    plugin._cookie = "c_secure_uid=NzMyMQ%3D%3D; c_secure_pass=abc"
    cookie, note = plugin._HHClubLottery__resolve_cookie()
    assert cookie.startswith("c_secure_uid=")
    assert note == "手动填写"


def test_resolve_cookie_from_cookiecloud(plugin, monkeypatch):
    class FakeHelper:
        payload = ({"hhanclub.net": "c_secure_uid=1; c_secure_pass=2",
                    "m-team.cc": "x=1"}, "")

        def download(self):
            return self.payload

    monkeypatch.setattr(HH, "_load_cookiecloud_helper", lambda: FakeHelper)
    plugin._cookie_source = "cookiecloud"
    plugin._host = "hhanclub.net"

    cookie, note = plugin._HHClubLottery__resolve_cookie()
    assert cookie == "c_secure_uid=1; c_secure_pass=2"
    assert "CookieCloud" in note

    # 同步范围里没有本站：要说清楚，并把实际有哪些域名列出来
    FakeHelper.payload = ({"m-team.cc": "x=1"}, "")
    cookie, note = plugin._HHClubLottery__resolve_cookie()
    assert cookie == ""
    assert "没有 hhanclub.net" in note and "m-team.cc" in note

    # CookieCloud 压根没配
    FakeHelper.payload = (None, "CookieCloud参数不正确")
    cookie, note = plugin._HHClubLottery__resolve_cookie()
    assert cookie == ""
    assert "CookieCloud参数不正确" in note


def test_resolve_cookie_cookiecloud_missing_module(plugin, monkeypatch):
    monkeypatch.setattr(HH, "_load_cookiecloud_helper", lambda: None)
    plugin._cookie_source = "cookiecloud"
    cookie, note = plugin._HHClubLottery__resolve_cookie()
    assert cookie == ""
    assert "没找到 CookieCloud 模块" in note


def test_resolve_cookie_from_site(plugin, monkeypatch):
    class FakeOper:
        site = types.SimpleNamespace(cookie="c_secure_uid=9; c_secure_pass=8", name="憨憨")

        def get_by_domain(self, domain):
            assert domain == "hhanclub.net"
            return self.site

    monkeypatch.setattr(HH, "_load_site_oper", lambda: FakeOper)
    plugin._cookie_source = "site"
    cookie, note = plugin._HHClubLottery__resolve_cookie()
    assert cookie == "c_secure_uid=9; c_secure_pass=8"
    assert "憨憨" in note

    FakeOper.site = None
    cookie, note = plugin._HHClubLottery__resolve_cookie()
    assert cookie == ""
    assert "没有 hhanclub.net" in note


def test_proxy_only_when_enabled(plugin):
    plugin._use_proxy = False
    assert plugin._HHClubLottery__get_proxies() is None
    plugin._use_proxy = True
    assert plugin._HHClubLottery__get_proxies() == {"http": "http://127.0.0.1:7890"}


# ============================================================
# 服务、命令、API
# ============================================================

def test_service_registered_only_when_enabled(plugin):
    plugin._enabled = False
    assert plugin.get_service() == []

    plugin._enabled = True
    plugin._cron = "5 9 * * *"
    services = plugin.get_service()
    assert len(services) == 1
    assert services[0]["id"] == "HHClubLottery"
    assert services[0]["func"] == plugin.run_lottery


def test_command_and_api(plugin):
    command = HHClubLottery.get_command()[0]
    assert command["cmd"] == "/hh_lottery"
    assert command["data"]["action"] == "hh_lottery"

    paths = {item["path"]: item for item in plugin.get_api()}
    assert set(paths) == {"/export", "/run"}
    assert all(item["auth"] == "apikey" for item in paths.values())


def test_export_is_userscript_backup(plugin):
    plugin.save_data("total", {
        "draws": 20, "cost": 40000, "gains": {"beans": 13900},
        "prizes": {"beans": {"count": 15, "value": 13900, "tiers": {"100 憨豆": 9}}},
    })
    payload = plugin.api_export()
    assert payload["kind"] == "hhclub-lottery-backup"
    assert payload["version"] == 4
    assert payload["total"]["draws"] == 20
    assert payload["total"]["gains"]["beans"] == 13900
    # 导出的是累计，current 留空，导入时选「合并」不会重复计
    assert payload["current"]["draws"] == 0


# ============================================================
# 数据页
# ============================================================

def test_page_empty(plugin):
    page = plugin.get_page()
    assert "暂无抽奖记录" in str(page)


def test_page_with_data(plugin):
    plugin.save_data("total", {
        "draws": 100, "cost": 200000, "gains": {"beans": 150000, "rainbow": 14},
        "prizes": {
            "beans": {"count": 60, "value": 150000, "tiers": {"1,000 憨豆": 40, "5,000 憨豆": 20}},
            "vip": {"count": 1, "value": 0, "swappedBeans": 1000000,
                    "tiers": {"已转换为憨豆 1,000,000": 1}},
            "rainbow": {"count": 2, "value": 14, "tiers": {"7 天": 2}},
        },
    })
    plugin.save_data("history", [
        {"date": "2026-08-20 09:05:00", "draws": 50, "cost": 100000, "beans": 70000,
         "profit": -30000, "rate": -30.0, "balance": 1200000, "duration": "6分 12秒",
         "status": "已达到设定抽奖次数（50 抽）"},
        {"date": "2026-08-21 09:05:00", "draws": 50, "cost": 100000, "beans": 80000,
         "profit": -20000, "rate": -20.0, "balance": 1100000, "duration": "6分 3秒",
         "status": "正常结束"},
    ])
    text = str(plugin.get_page())

    assert "历史总计" in text and "奖项明细" in text and "运行记录" in text
    assert "100 抽" in text
    # 折算来的憨豆要单独点出来，否则拿档位乘开对不上总数
    assert "含折算 1,000,000" in text
    assert "已转换为憨豆 1,000,000 × 1" in text
    assert "60.00%" in text, "实测占比按 60/100 计"
    # 最近一次应当是排序后的第一条
    assert "2026-08-21 09:05:00" in text
    assert text.index("2026-08-21") < text.index("2026-08-20")


def test_page_survives_legacy_magic_split(plugin):
    """早期版本把「魔力」拆成独立类别，数据页读的时候要合回憨豆。"""
    plugin.save_data("total", {
        "draws": 4, "cost": 8000, "gains": {"beans": 300, "magic": 7000},
        "prizes": {"magic": {"count": 3, "value": 7000, "tiers": {"2,000 憨豆": 3}},
                   "beans": {"count": 1, "value": 300, "tiers": {"300 憨豆": 1}}},
    })
    text = str(plugin.get_page())
    assert "憨豆（旧魔力）" not in text, "magic 桶应当已经并进憨豆"
    assert "7,300" in text


# ============================================================
# 插件 + 假站点：整条链路
# ============================================================

def _configure(plugin, host, **overrides):
    plugin._enabled = True
    plugin._notify = True
    plugin._cookie_source = "manual"
    plugin._cookie = "c_secure_uid=1; c_secure_pass=2"
    plugin._host = host
    plugin._draws = 3
    plugin._follow_duration = True
    for key, value in overrides.items():
        setattr(plugin, f"_{key}", value)


def test_run_lottery_end_to_end(plugin, instant):
    site = FakeSite()
    site.draw_queue = [win("\u9b54\u529b 2000", credit=2000),
                       win("彩虹ID 7 Day(s)"),
                       win("补签卡 1")]
    server, host = start_site(site)
    try:
        _configure(plugin, host)
        plugin.run_lottery()
    finally:
        stop_site(server)

    total = plugin.get_data("total")
    assert total["draws"] == 3
    assert total["cost"] == 6000
    assert total["gains"]["beans"] == 2000
    assert total["prizes"]["rainbow"]["tiers"] == {"7 天": 1}

    history = plugin.get_data("history")
    assert len(history) == 1
    record = history[0]
    assert record["draws"] == 3
    assert record["profit"] == -4000
    assert "已达到设定抽奖次数" in record["status"]

    titles = [m.get("title") or "" for m in plugin.messages]
    assert any("任务结算" in title for title in titles), "跑完应当推一条结算通知"


def test_run_lottery_accumulates_across_runs(plugin, instant):
    for _ in range(2):
        site = FakeSite()
        site.draw_queue = [win("补签卡 1"), win("补签卡 1")]
        server, host = start_site(site)
        try:
            _configure(plugin, host, draws=2)
            plugin.run_lottery()
        finally:
            stop_site(server)

    assert plugin.get_data("total")["draws"] == 4, "第二轮要在第一轮的基础上累加"
    assert len(plugin.get_data("history")) == 2


def test_run_lottery_without_cookie_does_not_touch_site(plugin, instant):
    site = FakeSite()
    site.draw_queue = [win("补签卡 1")]
    server, host = start_site(site)
    try:
        _configure(plugin, host)
        plugin._cookie = ""
        plugin.run_lottery()
    finally:
        stop_site(server)

    assert site.draw_calls == 0, "取不到 Cookie 就不该发请求"
    assert plugin.get_data("total") is None
    assert any("取不到 Cookie" in (m.get("text") or "") for m in plugin.messages)


def test_run_lottery_cookie_expired(plugin, instant):
    site = FakeSite()
    site.cookie_valid = False
    server, host = start_site(site)
    try:
        _configure(plugin, host)
        plugin.run_lottery()
    finally:
        stop_site(server)

    record = plugin.get_data("history")[0]
    assert record["draws"] == 0
    assert "Cookie 失效" in record["status"], "失效要记进运行记录，页面上看得见"
    assert any("Cookie 失效" in (m.get("text") or "") for m in plugin.messages)


def test_run_lottery_big_prize_pushes_immediately(plugin, instant):
    site = FakeSite()
    site.user_class = "User"
    site.draw_queue = [win("憨豆 780000", credit=780000), win("补签卡 1")]
    server, host = start_site(site)
    try:
        _configure(plugin, host, draws=2, big_prize_min_beans=780000)
        plugin.run_lottery()
    finally:
        stop_site(server)

    titles = [m.get("title") or "" for m in plugin.messages]
    assert any("命中大奖" in title for title in titles)
    # 大奖通知在结算之前就发出去了，不用等跑完
    assert titles.index(next(t for t in titles if "命中大奖" in t)) <            titles.index(next(t for t in titles if "任务结算" in t))


def test_notify_switch_silences_everything(plugin, instant):
    site = FakeSite()
    site.draw_queue = [win("憨豆 780000", credit=780000)]
    server, host = start_site(site)
    try:
        _configure(plugin, host, draws=1, notify=False, big_prize_min_beans=780000)
        plugin.run_lottery()
    finally:
        stop_site(server)

    assert plugin.messages == [], "总通知开关关掉时，大奖和结算都不该推"
    assert plugin.get_data("total")["draws"] == 1, "但成绩照记"


def test_history_retention(plugin, instant):
    plugin.save_data("history", [
        {"date": "2020-01-01 00:00:00", "draws": 1},      # 早就过期
        {"date": "坏掉的时间", "draws": 1},                 # 解析不了的脏数据
    ])
    site = FakeSite()
    site.draw_queue = [win("补签卡 1")]
    server, host = start_site(site)
    try:
        _configure(plugin, host, draws=1, history_days=30)
        plugin.run_lottery()
    finally:
        stop_site(server)

    history = plugin.get_data("history")
    assert len(history) == 1, "过期记录和脏数据都该被清掉，只剩这一次"


def test_saved_stats_have_no_float_tails(plugin, instant):
    """加减法一路会把 int 带成 float。落盘和导出前要收干净 ——
    不然备份里满屏 2000.0 / 15.0，和油猴版面板存的对不齐。"""
    site = FakeSite()
    site.draw_queue = [win("魔力 2000", credit=2000), win("上传量 512 MB")]
    server, host = start_site(site)
    try:
        _configure(plugin, host, draws=2)
        plugin.run_lottery()
    finally:
        stop_site(server)

    def floats(node, path="total"):
        if isinstance(node, dict):
            return [item for key, value in node.items() for item in floats(value, f"{path}.{key}")]
        if isinstance(node, float):
            return [] if not node.is_integer() else [path]
        return []

    total = plugin.get_data("total")
    assert floats(total) == [], "整数不该存成浮点"
    assert total["draws"] == 2 and isinstance(total["draws"], int)
    # 非整数的照旧保留：512MB 折算成 0.5GB
    assert total["gains"]["upload"] == 0.5

    payload = plugin.api_export()
    assert floats(payload["total"], "export.total") == []


def test_stop_on_big_prize_end_to_end(plugin, instant):
    site = FakeSite()
    site.balance = 1000000
    site.draw_queue = [win("补签卡 1"), win("憨豆 780000", credit=780000),
                       win("补签卡 1"), win("补签卡 1")]
    server, host = start_site(site)
    try:
        _configure(plugin, host, draws=10, stop_on_780k=True)
        plugin.run_lottery()
    finally:
        stop_site(server)

    record = plugin.get_data("history")[0]
    assert record["draws"] == 2
    assert "命中停止条件（780,000 憨豆）" in record["status"]
    assert site.draw_calls == 2, "停了就别再发请求"


def test_stop_switches_default_off(plugin):
    _, defaults = plugin.get_form()
    assert defaults["stop_on_vip"] is False
    assert defaults["stop_on_780k"] is False


def test_export_origin_id_is_stable(plugin):
    """记录线编号头一次导出时生成，之后每次导出都得是同一个 ——
    油猴版靠它认出这些文件同出一源。"""
    first = plugin.api_export()
    second = plugin.api_export()

    assert first["originId"], "一轮没跑过也要带上记录线编号"
    assert second["originId"] == first["originId"]
    assert second["exportId"] != first["exportId"], "每个文件一个 exportId"
    assert plugin.get_data("total")["originId"] == first["originId"], "编号要存回去"


def test_run_stamps_origin_id(plugin, instant):
    site = FakeSite()
    site.draw_queue = [win("补签卡 1")]
    server, host = start_site(site)
    try:
        _configure(plugin, host, draws=1)
        plugin.run_lottery()
    finally:
        stop_site(server)

    origin = plugin.get_data("total")["originId"]
    assert origin, "跑完落盘时就该盖上编号"
    assert plugin.api_export()["originId"] == origin, "导出沿用已有编号，不另起一条"
