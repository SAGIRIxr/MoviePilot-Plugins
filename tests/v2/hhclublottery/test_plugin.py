# -*- coding: utf-8 -*-
"""HHCLUB幸运大转盘：插件外壳。

配置页和数据页是纯拼装，出错只会在 MoviePilot 界面上表现为一片空白 ——
借 conftest.py 里的 app.* 桩件把插件类加载起来，把这两块、Cookie 取用逻辑
以及「插件 + 假站点」的整条链路都真跑一遍。
"""
import json
import time
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
    assert set(paths) == {"/export", "/run", "/stop", "/status"}
    assert all(item["auth"] == "apikey" for item in paths.values())


def test_export_is_userscript_backup(plugin):
    plugin.save_data("total", {
        "draws": 20, "cost": 40000, "gains": {"beans": 13900},
        "prizes": {"beans": {"count": 15, "value": 13900, "tiers": {"100 憨豆": 9}}},
    })
    payload = plugin.build_backup()
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
        "draws": 100, "cost": 200000, "gains": {"beans": 1150000, "rainbow": 14},
        "prizes": {
            "beans": {"count": 60, "value": 150000, "tiers": {"1,000 憨豆": 40, "5,000 憨豆": 22}},
            "vip": {"count": 1, "value": 0, "swappedBeans": 1000000,
                    "tiers": {"已转换为憨豆 1,000,000": 1}},
            "rainbow": {"count": 2, "value": 14, "tiers": {"7 天": 2}},
        },
    })
    plugin.save_data("history", [
        {"date": "2026-08-20 09:05:00", "draws": 50, "cost": 100000, "beans": 70000,
         "profit": -30000, "rate": -30.0, "balance": 1200000, "duration": "6分 12秒",
         "status": "已达到设定抽奖次数（50 抽）"},
        {"date": "2026-08-21 09:05:00", "draws": 50, "cost": 100000, "beans": 1080000,
         "swapped": 1000000, "profit": 980000, "rate": 980.0, "balance": 2100000,
         "duration": "6分 3秒", "status": "正常结束"},
    ])
    text = str(plugin.get_page())

    assert "憨豆盈亏（历史总计）" in text and "奖项明细" in text and "运行记录" in text

    # 盈亏是这一页的主角
    assert "+950,000" in text, "净盈亏 = 1,150,000 - 200,000"
    assert "每抽 +9,500 憨豆" in text, "平均每抽赚多少才是真正有用的那个数"
    assert "每抽 2,000" in text, "平均每抽消耗"
    assert "575.0%" in text, "回本率 = 获得 / 消耗"

    # 折算来的憨豆要单独点出来，否则拿档位乘开对不上总数
    assert "档位 150,000 + 折算 1,000,000" in text

    # 档位是子行，不再是挤在一个格子里的顿号串
    assert "└ 1,000 憨豆" in text and "└ 5,000 憨豆" in text and "└ 7 天" in text
    assert "、" not in text, "档位不该再用顿号拼成一串"

    # 实测占比：类别和档位都要有
    assert "60.00%" in text and "40.00%" in text and "22.00%" in text

    # 每抽盈亏也进运行记录
    assert "+19,600" in text, "980,000 / 50"


def test_page_bean_column_adds_up(plugin):
    """「折合憨豆」这一列的合计必须等于累计获得 —— 对不上就说明哪一类算漏了。"""
    plugin.save_data("total", {
        "draws": 100, "cost": 200000, "gains": {"beans": 1150000, "rainbow": 14},
        "prizes": {
            "beans": {"count": 60, "value": 150000, "tiers": {"1,000 憨豆": 40, "5,000 憨豆": 22}},
            "vip": {"count": 1, "value": 0, "swappedBeans": 1000000,
                    "tiers": {"已转换为憨豆 1,000,000": 1}},
            "rainbow": {"count": 2, "value": 14, "tiers": {"7 天": 2}},
            "makeup": {"count": 37, "value": 37, "tiers": {"1 个": 37}},
        },
    })
    gain = plugin._HHClubLottery__bean_gain
    assert gain("beans", {"value": 150000}) == 150000
    assert gain("vip", {"value": 0, "swappedBeans": 1000000}) == 1000000
    # 天 / 个 / GB 换算不了，不硬凑
    assert gain("rainbow", {"value": 14}) == 0
    assert gain("makeup", {"value": 37}) == 0
    assert gain("upload", {"value": 5950}) == 0

    total = plugin.get_data("total")
    assert sum(gain(t, b) for t, b in total["prizes"].items()) == total["gains"]["beans"]

    text = str(plugin.get_page())
    assert "1,150,000" in text, "表尾合计"
    # 彩虹 / 补签卡那两行的折合憨豆是空的，不是 0 也不是瞎折算
    assert "5,950" not in text


def test_page_tier_bean_subtotal(plugin):
    """档位的憨豆小计 = 档位金额 × 次数，加起来要等于这一类的 value。"""
    plugin.save_data("total", {
        "draws": 62, "cost": 124000, "gains": {"beans": 150000},
        "prizes": {"beans": {"count": 62, "value": 150000,
                             "tiers": {"1,000 憨豆": 40, "5,000 憨豆": 22}}},
    })
    text = str(plugin.get_page())
    assert "40,000" in text, "1,000 × 40"
    assert "110,000" in text, "5,000 × 22"
    assert 40000 + 110000 == 150000


def test_page_jackpot_roster(plugin):
    """导进来的大奖名册要显示出来 —— 之前保留了却不展示，等于白留。"""
    plugin.save_data("total", {
        "draws": 10, "cost": 20000, "gains": {"beans": 5000},
        "prizes": {"beans": {"count": 10, "value": 5000, "tiers": {"500 憨豆": 10}},
                   "vip": {"count": 2, "value": 0, "swappedBeans": 2000000,
                           "tiers": {"已转换为憨豆 1,000,000": 2}}},
        "jackpots": [{"at": 1787370861410, "text": "VIP 7 Day(s)"},
                     {"at": 1787300000000, "text": "憨豆 780000"}],
    })
    text = str(plugin.get_page())
    assert "大奖名册（中过 2 次，2 条有时间记录）" in text
    assert "VIP 7 Day(s)" in text and "憨豆 780000" in text
    assert "2026-" in text, "时刻要渲染成人看得懂的时间"
    assert "没有时间记录" not in text, "名册齐了就别提这一句"


def test_page_jackpot_counts_without_roster(plugin):
    """名册只在油猴版面板上产生。MP 这边中过的那些没有时刻，
    但「中过几次」是准的 —— 只摆名册的话，中过 31 次却显示 1 条，看着像丢了数据。"""
    plugin.save_data("total", {
        "draws": 34228, "cost": 68456000, "gains": {"beans": 72451900},
        "prizes": {
            "beans": {"count": 28997, "value": 63451900,
                      "tiers": {"100 憨豆": 28975, "780,000 憨豆": 22}},
            "vip": {"count": 9, "value": 0, "swappedBeans": 9000000,
                    "tiers": {"已转换为憨豆 1,000,000": 9}},
        },
        "jackpots": [{"at": 1787370861410, "text": "VIP 7 Day(s)"}],
    })
    text = str(plugin.get_page())
    assert "大奖名册（中过 31 次，1 条有时间记录）" in text
    assert "⭐ VIP 9 次" in text
    assert "780,000 以上憨豆 22 次" in text
    assert "其中 30 次没有时间记录" in text


def test_page_jackpot_card_without_any_roster(plugin):
    """一条名册都没有、但统计里中过 —— 还是要把次数摆出来。"""
    plugin.save_data("total", {
        "draws": 5000, "cost": 10000000, "gains": {"beans": 5000000},
        "prizes": {"beans": {"count": 4999, "value": 5000000,
                             "tiers": {"780,000 憨豆": 3, "100 憨豆": 4996}}},
    })
    text = str(plugin.get_page())
    assert "大奖名册（中过 3 次）" in text
    assert "其中 3 次没有时间记录" in text


def test_page_without_jackpots_hides_the_card(plugin):
    """名册空、统计里也一次没中过 —— 这才该整卡不显示。"""
    plugin.save_data("total", {
        "draws": 10, "cost": 20000, "gains": {"beans": 5000},
        "prizes": {"beans": {"count": 10, "value": 5000, "tiers": {"500 憨豆": 10}}},
    })
    assert "大奖名册" not in str(plugin.get_page()), "一次没中过就别摆个空卡"


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

    payload = plugin.build_backup()
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
    first = plugin.build_backup()
    second = plugin.build_backup()

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
    assert plugin.build_backup()["originId"] == origin, "导出沿用已有编号，不另起一条"


# ============================================================
# 停止当前抽奖 / 保存配置不打断
# ============================================================

def _config_for(host, **overrides):
    """一份完整的配置字典，模拟界面上按「保存」提交的内容。"""
    config = {
        "enabled": True, "notify": False, "onlyonce": False, "stop_current": False,
        "cron": "5 9 * * *", "cookie_source": "manual",
        "cookie": "c_secure_uid=1; c_secure_pass=2", "host": host,
        "draws": 10, "reserve": 0, "interval": 6.8, "follow_duration": True,
        "duration_buffer": 0, "max_minutes": 60, "clean_mail": False,
        "stop_on_vip": False, "stop_on_780k": False,
        "notify_big_prize": True, "big_prize_min_beans": 780000,
        "notify_periodic": False, "periodic_minutes": 30,
        "use_proxy": False, "user_agent": "", "history_days": 90,
    }
    config.update(overrides)
    return config


def test_plain_config_save_does_not_interrupt(plugin, monkeypatch):
    """改个 cron、调个通知开关，不该把挂了一半的抽奖腰斩。

    MoviePilot 保存配置走的是同一个实例的 init_plugin，不经过 stop_service ——
    以前 init_plugin 第一行就调 stop_service，等于每次保存都腰斩一次。"""
    site = FakeSite()
    site.draw_queue = [win("补签卡 1") for _ in range(6)]
    server, host = start_site(site)
    saved = {"n": 0}

    def sleep_hook(self, ms):
        if self.current["draws"] == 2 and not saved["n"]:
            saved["n"] += 1
            # 用户在界面上改了抽奖周期就按了保存
            plugin.init_plugin(_config_for(host, cron="0 3 * * *"))
        return self.stop_event.is_set()

    monkeypatch.setattr(HH.LotteryRunner, "sleep", sleep_hook)
    try:
        plugin.init_plugin(_config_for(host, draws=5))
        plugin.run_lottery()
    finally:
        stop_site(server)

    assert saved["n"] == 1, "保存钩子没被触发，这个用例就没测到东西"
    assert plugin.get_data("history")[0]["draws"] == 5, "保存配置不该打断这一轮"
    assert plugin._cron == "0 3 * * *", "新配置照样生效"


def test_stop_current_interrupts_running_round(plugin, monkeypatch):
    site = FakeSite()
    site.draw_queue = [win("补签卡 1") for _ in range(10)]
    server, host = start_site(site)
    saved = {"n": 0}

    def sleep_hook(self, ms):
        if self.current["draws"] == 2 and not saved["n"]:
            saved["n"] += 1
            plugin.init_plugin(_config_for(host, stop_current=True))
        return self.stop_event.is_set()

    monkeypatch.setattr(HH.LotteryRunner, "sleep", sleep_hook)
    try:
        plugin.init_plugin(_config_for(host, draws=10))
        plugin.run_lottery()
    finally:
        stop_site(server)

    record = plugin.get_data("history")[0]
    assert record["draws"] == 2, "勾了就该当场收工"
    assert site.draw_calls == 2
    assert plugin.get_data("total")["draws"] == 2, "已抽的成绩照常落盘"


def test_stop_current_resets_itself(plugin):
    plugin.init_plugin(_config_for("hhanclub.net", stop_current=True))
    assert plugin._stop_current is False, "一次性开关，保存后立刻复位"
    assert plugin._config["stop_current"] is False, "复位要写回配置，不然下次保存又停一遍"


def test_stop_current_beats_onlyonce(plugin, monkeypatch):
    started = []
    monkeypatch.setattr(plugin, "run_lottery", lambda: started.append(1))
    plugin.init_plugin(_config_for("hhanclub.net", stop_current=True, onlyonce=True))
    assert started == [], "既要停又要开只能是勾错了，宁可什么都不启"
    assert plugin._onlyonce is False
    assert plugin._stop_current is False


def test_stop_event_is_never_swapped(plugin):
    """init_plugin 里换个新 Event 的话，正在跑的那一轮还攥着旧的，谁也叫不停它。"""
    before = plugin._stop_event
    plugin.init_plugin(_config_for("hhanclub.net"))
    assert plugin._stop_event is before, "同一个实例上 Event 不能换"

    plugin.stop_service()
    assert before.is_set(), "禁用插件仍然要能叫停"


def _buttons(page_json):
    """把状态卡上的按钮抠出来：{按钮文案: 是否禁用}。"""
    found = {}

    def walk(node):
        if isinstance(node, dict):
            if node.get("component") == "VBtn":
                found[node["text"]] = node["props"].get("disabled")
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(page_json)
    return found


def test_status_card_states(plugin):
    """抽奖周期可以留空，所以数据页上这两个按钮就是唯一入口，状态必须准。"""
    # 没启用：开始按钮点不动
    page = plugin.get_page()
    assert "插件未启用" in str(page)
    assert _buttons(page) == {"开始抽奖": True, "停止": True, "刷新": False, "导出备份": None}

    # 启用了、没设周期：只能手动开
    plugin._enabled = True
    plugin._cron = ""
    page = plugin.get_page()
    assert "空闲中" in str(page)
    assert "只在点「开始抽奖」时跑" in str(page)
    assert _buttons(page) == {"开始抽奖": False, "停止": True, "刷新": False, "导出备份": None}

    # 设了周期：两条路都说清楚
    plugin._cron = "5 9 * * *"
    assert "按抽奖周期 5 9 * * * 自动触发" in str(plugin.get_page())


def test_status_card_while_running(plugin, monkeypatch):
    site = FakeSite()
    site.draw_queue = [win("补签卡 1") for _ in range(6)]
    server, host = start_site(site)
    seen = {}

    def sleep_hook(self, ms):
        if self.current["draws"] == 2 and "page" not in seen:
            seen["page"] = plugin.get_page()
        return self.stop_event.is_set()

    monkeypatch.setattr(HH.LotteryRunner, "sleep", sleep_hook)
    try:
        _configure(plugin, host, draws=3)
        plugin.run_lottery()
    finally:
        stop_site(server)

    assert "正在抽 · 第 2 / 3 抽" in str(seen["page"])
    # 跑着的时候只能停，不能再开一轮
    assert _buttons(seen["page"]) == {"开始抽奖": True, "停止": False, "刷新": False, "导出备份": None}
    assert "空闲中" in str(plugin.get_page()), "跑完要回到空闲"


def test_action_buttons_call_plugin_api(plugin):
    """按钮走的是 MoviePilot PageRender 的 events.click，路径和参数得对上 get_api()。"""
    plugin._enabled = True
    events = []

    def walk(node):
        if isinstance(node, dict):
            if node.get("events"):
                events.append((node["text"], node["events"]["click"]))
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(plugin.get_page())
    assert len(events) == 3, "开始 / 停止 / 刷新；导出走 href 直链，不该也挂 events"
    registered = {item["path"] for item in plugin.get_api()}
    for text, click in events:
        assert click["method"] == "get"
        assert click["params"]["apikey"], "不带 apikey 会被挡在门外"
        prefix, plugin_id, path = click["api"].split("/")
        assert prefix == "plugin"
        # 分身之后类名会变，所以不能把插件 ID 写死
        assert plugin_id == plugin.__class__.__name__
        assert f"/{path}" in registered, f"{text} 指向了没注册的接口 /{path}"


def test_api_stop(plugin):
    assert plugin.api_stop()["code"] == 1, "没在跑就没什么好停的"
    plugin._running = True
    plugin._stop_event.clear()
    result = plugin.api_stop()
    assert result["code"] == 0
    assert plugin._stop_event.is_set()
    plugin._running = False


def test_cron_is_optional(plugin):
    _, defaults = plugin.get_form()
    assert defaults["cron"] == "", "抽奖花的是真憨豆，默认不该自己跑起来"

    plugin.init_plugin(_config_for("hhanclub.net", cron=""))
    assert plugin.get_service() == [], "没设周期就不注册定时服务"

    plugin.init_plugin(_config_for("hhanclub.net", cron="5 9 * * *"))
    assert len(plugin.get_service()) == 1


# ============================================================
# 配置页交上来的数字（实机上踩到的）
# ============================================================

def test_empty_draws_is_not_draw_to_bottom(plugin):
    """空输入框不等于 0。

    实机上把插件更新到新版后打开配置页点保存，存进去的 draws 是 0 ——
    而 0 在这儿是「一抽到底」，等于一个空输入框就能让它把余额抽干。
    根因是 `int(config.get("draws") or 0)`：前端交上来的 "" 被折成了 0。"""
    for blank in ("", "   ", None, "abc"):
        plugin.init_plugin(_config_for("hhanclub.net", draws=blank))
        assert plugin._draws == 10, f"draws={blank!r} 应当退回默认 10，而不是一抽到底"

    # 明明白白填的 0 才算一抽到底
    plugin.init_plugin(_config_for("hhanclub.net", draws=0))
    assert plugin._draws == 0
    plugin.init_plugin(_config_for("hhanclub.net", draws="0"))
    assert plugin._draws == 0
    plugin.init_plugin(_config_for("hhanclub.net", draws="100"))
    assert plugin._draws == 100


@pytest.mark.parametrize("field,default", [
    ("reserve", 0), ("interval", 6.8), ("duration_buffer", 0), ("max_minutes", 60),
    ("big_prize_min_beans", 780000), ("periodic_minutes", 30), ("history_days", 90),
])
def test_blank_numbers_fall_back_to_defaults(plugin, field, default):
    plugin.init_plugin(_config_for("hhanclub.net", **{field: ""}))
    assert getattr(plugin, f"_{field}") == default


def test_number_helper():
    n = HH._number
    assert n("", 10, int) == 10
    assert n(None, 10, int) == 10
    assert n("  ", 10, int) == 10
    assert n("坏值", 10, int) == 10
    assert n(0, 10, int) == 0
    assert n("0", 10, int) == 0
    assert n("7", 10, int) == 7
    assert n(6.8, 1.0) == 6.8
    assert n("-500", 0, int) == -500


def test_draw_to_bottom_is_announced(plugin, instant, monkeypatch):
    """真进了一抽到底，日志里得说一声 —— 这是个会把余额抽干的决定。"""
    warnings = []
    monkeypatch.setattr(HH.logger, "warning", lambda msg, *a, **k: warnings.append(str(msg)))

    site = FakeSite()
    site.balance = 6000
    site.draw_queue = [win("补签卡 1") for _ in range(5)]
    server, host = start_site(site)
    try:
        _configure(plugin, host, draws=0, reserve=2000)
        plugin.run_lottery()
    finally:
        stop_site(server)

    assert any("一抽到底" in w for w in warnings)
    assert plugin.get_data("total")["draws"] == 2, "6000 → 4000 → 2000 触及保留线"


# ============================================================
# 备份导入导出
# ============================================================

def _backup(draws=10, cost=20000, beans=5000, origin="browserline",
            export_id="file0001", jackpots=None, first=1000, last=2000):
    """一份油猴版格式的备份。"""
    return {
        "kind": "hhclub-lottery-backup", "version": 4,
        "exportedAt": "2026-08-20T00:00:00.000Z", "source": "tampermonkey",
        "originId": origin, "exportId": export_id,
        "current": {"draws": 0},
        "total": {
            "version": 4, "draws": draws, "cost": cost,
            "gains": {"beans": beans, "rainbow": 7},
            "prizes": {
                "beans": {"count": draws - 1, "value": beans,
                          "tiers": {"1,000 憨豆": draws - 1}},
                "rainbow": {"count": 1, "value": 7, "tiers": {"7 天": 1}},
            },
            "raw": {"魔力 1000": draws - 1},
            "originId": origin, "firstAt": first, "lastAt": last,
            "jackpots": jackpots if jackpots is not None else [],
        },
    }


def _import_config(payload, mode="merge", **overrides):
    # notify 开着，导入结果的通知才发得出来 —— 那是用户唯一看得见结果的地方
    overrides.setdefault("notify", True)
    return _config_for("hhanclub.net", import_data=json.dumps(payload, ensure_ascii=False),
                       import_mode=mode, do_import=True, **overrides)


def _seed_total(plugin, draws=100, beans=125900, origin="mpline", **extra):
    total = {
        "version": 4, "draws": draws, "cost": draws * 2000,
        "gains": {"beans": beans},
        "prizes": {"beans": {"count": draws, "value": beans,
                             "tiers": {"1,000 憨豆": draws}}},
        "raw": {"魔力 1000": draws},
        "originId": origin, "firstAt": 5000, "lastAt": 9000,
    }
    total.update(extra)
    plugin.save_data("total", total)


def test_import_merge(plugin):
    _seed_total(plugin, draws=100, beans=125900)
    plugin.init_plugin(_import_config(_backup(draws=10, cost=20000, beans=5000)))

    total = plugin.get_data("total")
    assert total["draws"] == 110
    assert total["cost"] == 220000
    assert total["gains"]["beans"] == 130900
    assert total["gains"]["rainbow"] == 7
    assert total["prizes"]["beans"]["tiers"]["1,000 憨豆"] == 109
    assert total["prizes"]["rainbow"]["count"] == 1
    # 自己的记录线保住，对方的记进台账
    assert total["originId"] == "mpline"
    assert total["imports"][-1]["exportId"] == "file0001"
    assert total["imports"][-1]["originId"] == "browserline"
    assert total["imports"][-1]["draws"] == 10


def test_import_replace_takes_over_lineage(plugin):
    _seed_total(plugin, draws=100)
    plugin.init_plugin(_import_config(_backup(draws=10), mode="replace"))

    total = plugin.get_data("total")
    assert total["draws"] == 10, "覆盖就是取代，不是相加"
    assert total["originId"] == "browserline", "覆盖之后这台机器是那条记录线的延续"


def test_import_resets_switch_and_clears_box(plugin):
    _seed_total(plugin)
    plugin.init_plugin(_import_config(_backup()))
    assert plugin._do_import is False, "一次性开关"
    assert plugin._import_data == "", "导完要清空，免得下次保存又导一遍"
    assert plugin._config["do_import"] is False
    assert plugin._config["import_data"] == ""


def test_import_does_not_start_a_round(plugin, monkeypatch):
    started = []
    monkeypatch.setattr(plugin, "run_lottery", lambda: started.append(1))
    _seed_total(plugin)
    plugin.init_plugin(_import_config(_backup(), onlyonce=True))
    assert started == [], "导入就只做导入，不顺带开抽"
    assert plugin._onlyonce is False


def test_import_blocks_same_file_twice(plugin):
    _seed_total(plugin, draws=100)
    payload = _backup(draws=10, export_id="file0001")
    plugin.init_plugin(_import_config(payload))
    assert plugin.get_data("total")["draws"] == 110

    # 同一个文件再来一次 —— 台账里有它，拦下
    plugin.init_plugin(_import_config(payload))
    assert plugin.get_data("total")["draws"] == 110, "重复导入必须被拦住"
    assert plugin._import_data != "", "被拦下时别把人家贴的内容清掉"
    assert any("已经导入过" in (m.get("text") or "") for m in plugin.messages)


def test_force_merge_overrides_the_block(plugin):
    _seed_total(plugin, draws=100)
    payload = _backup(draws=10, export_id="file0001")
    plugin.init_plugin(_import_config(payload))
    plugin.init_plugin(_import_config(payload, mode="force"))
    assert plugin.get_data("total")["draws"] == 120, "明确选了强制合并就照做"


def test_import_blocks_same_lineage(plugin):
    """备份和当前历史出自同一条记录线 —— 比如从这台 MP 导出去又导回来。"""
    _seed_total(plugin, draws=100, origin="mpline")
    plugin.init_plugin(_import_config(_backup(draws=10, origin="mpline", export_id="other")))
    assert plugin.get_data("total")["draws"] == 100, "同源要拦"
    assert any("同源" in (m.get("text") or "") for m in plugin.messages)


def test_import_blocks_overlapping_jackpots(plugin):
    """老备份没有编号，只能拿大奖时刻对表 —— 同一毫秒同一个奖不会是巧合。"""
    shared = [{"at": 1755000000123, "text": "VIP 7 Day(s)"}]
    _seed_total(plugin, draws=100, origin="mpline", jackpots=shared)
    payload = _backup(draws=10, origin=None, export_id=None, jackpots=shared)
    payload.pop("originId")
    payload.pop("exportId")
    payload["total"]["originId"] = None
    plugin.init_plugin(_import_config(payload))
    assert plugin.get_data("total")["draws"] == 100
    assert any("大奖记录" in (m.get("text") or "") for m in plugin.messages)


def test_soft_overlap_still_imports(plugin):
    """「时间区间被罩住」只是看着像，不是证据 —— 提醒一句，照常导。

    两个人在同一段时间里各刷各的，抽得少的那份区间本来就会被罩住。"""
    _seed_total(plugin, draws=100, origin="mpline")   # firstAt 5000 lastAt 9000
    plugin.init_plugin(_import_config(
        _backup(draws=10, origin="otherline", export_id="f2", first=6000, last=8000)))
    assert plugin.get_data("total")["draws"] == 110, "软提示不该拦"


def test_import_rejects_garbage(plugin):
    _seed_total(plugin, draws=100)
    for bad in ("这不是 JSON", "{}", '{"foo": 1}', "[]"):
        plugin.init_plugin(_config_for("hhanclub.net", import_data=bad, notify=True,
                                       import_mode="merge", do_import=True))
        assert plugin.get_data("total")["draws"] == 100, f"{bad!r} 不该动到数据"
    assert any("读不出" in (m.get("text") or "") for m in plugin.messages)


def test_import_empty_box(plugin):
    _seed_total(plugin, draws=100)
    plugin.init_plugin(_config_for("hhanclub.net", import_data="  ", notify=True,
                                   import_mode="merge", do_import=True))
    assert plugin.get_data("total")["draws"] == 100
    assert any("是空的" in (m.get("text") or "") for m in plugin.messages)


def test_import_keeps_foreign_jackpots(plugin):
    """油猴版的大奖名册要带过来 —— 那是这边产生不了、也补不回来的东西。"""
    _seed_total(plugin, draws=100, origin="mpline")
    payload = _backup(draws=10, origin="browserline", export_id="f9",
                      jackpots=[{"at": 1755000000001, "text": "VIP 7 Day(s)"},
                                {"at": 1755000000002, "text": "憨豆 780000"}])
    plugin.init_plugin(_import_config(payload))
    total = plugin.get_data("total")
    assert len(total["jackpots"]) == 2
    assert total["jackpots"][0]["at"] == 1755000000002, "名册按时间倒序"


def test_export_button_is_a_direct_link(plugin):
    """导出必须走 href —— events.click 是 axios 调用，拿不到响应体、存不成文件。"""
    def find(node):
        if isinstance(node, dict):
            if node.get("component") == "VBtn" and node.get("text") == "导出备份":
                return node
            for value in node.values():
                hit = find(value)
                if hit:
                    return hit
        elif isinstance(node, list):
            for item in node:
                hit = find(item)
                if hit:
                    return hit
        return None

    button = find(plugin.get_page())
    assert button is not None
    assert "events" not in button
    href = button["props"]["href"]
    assert href.startswith(f"/api/v1/plugin/{plugin.__class__.__name__}/export?apikey=")
    assert button["props"]["target"] == "_blank"


def test_export_is_downloadable(plugin):
    _seed_total(plugin, draws=42)
    response = plugin.api_export()
    disposition = response.headers.get("content-disposition")
    assert disposition and disposition.startswith("attachment;")
    assert "42draws.json" in disposition
    assert disposition.isascii(), "文件名带中文要走 RFC 5987，这里避开了"
    assert json.loads(response.body)["total"]["draws"] == 42


def test_round_trip(plugin):
    """导出再导回去，应当被当场认出是同一份，而不是把自己算两遍。"""
    _seed_total(plugin, draws=100)
    payload = plugin.build_backup()
    plugin.init_plugin(_import_config(payload))
    assert plugin.get_data("total")["draws"] == 100, "自己导出的自己导回来必须被拦"


def test_stop_reason_names_who_stopped(plugin, monkeypatch):
    """点按钮停和插件被停用都会 set 同一个 Event，运行记录上得分得开。"""
    site = FakeSite()
    site.draw_queue = [win("补签卡 1") for _ in range(10)]
    server, host = start_site(site)

    def sleep_hook(self, ms):
        if self.current["draws"] == 2:
            plugin.api_stop()
        return self.stop_event.is_set()

    monkeypatch.setattr(HH.LotteryRunner, "sleep", sleep_hook)
    try:
        _configure(plugin, host, draws=10)
        plugin.run_lottery()
    finally:
        stop_site(server)

    record = plugin.get_data("history")[0]
    assert record["draws"] == 2
    assert record["status"] == "手动停止（数据页按钮）"


def test_page_gain_card(plugin):
    """憨豆之外的东西：彩虹ID、补签卡、上传量这些换算不成憨豆，
    但它们才是抽奖真正想要的。没中过也要摆出来 —— 「邀请 0」本身就是信息。"""
    plugin.save_data("total", {
        "draws": 34228, "cost": 68456000,
        "gains": {"beans": 72451900, "rainbow": 6251, "makeup": 1959,
                  "upload": 5950, "invite": 58, "vip": 0, "rename": 0},
        "prizes": {
            "beans": {"count": 28997, "value": 63451900, "tiers": {"100 憨豆": 28997}},
            "rainbow": {"count": 893, "value": 6251, "tiers": {"7 天": 893}},
            "makeup": {"count": 1959, "value": 1959, "tiers": {"1 个": 1959}},
            "upload": {"count": 2312, "value": 5950, "tiers": {"2 GB": 2312}},
            "invite": {"count": 58, "value": 58, "tiers": {"1 邀请": 58}},
            "vip": {"count": 9, "value": 0, "swappedBeans": 9000000,
                    "tiers": {"已转换为憨豆 1,000,000": 9}},
        },
    })
    text = str(plugin.get_page())

    assert "奖品累计（憨豆以外）" in text
    assert "6,251 天" in text and "893 次" in text          # 彩虹ID
    assert "1,959 个" in text                                # 补签卡
    assert "5,950 GB" in text and "2,312 次" in text        # 上传量
    assert "📧 邀请" in text and "58" in text
    # VIP 折算之后天数被扣回 0，主值得是次数，否则看着像一次没中过
    assert "9 次" in text and "折算 9,000,000 憨豆" in text
    # 一次没中过的类别照样占位
    assert "📛 改名卡" in text and "没中过" in text


def test_gain_card_shows_vip_days_when_not_swapped(plugin):
    """没被折算时，VIP 的天数要照实显示。"""
    plugin.save_data("total", {
        "draws": 100, "cost": 200000, "gains": {"beans": 0, "vip": 14},
        "prizes": {"vip": {"count": 2, "value": 14, "tiers": {"7 天": 2}}},
    })
    text = str(plugin.get_page())
    assert "2 次" in text and "14 天" in text
    assert "折算" not in text.split("奖品累计")[1].split("奖项明细")[0]


def test_gain_card_keeps_unknown_prizes(plugin):
    """站点哪天加了认不出的新奖品，别让它凭空消失。"""
    plugin.save_data("total", {
        "draws": 10, "cost": 20000, "gains": {"beans": 0},
        "prizes": {"unknown": {"count": 3, "value": 0, "tiers": {"神秘礼包": 3}}},
    })
    text = str(plugin.get_page())
    assert "其他奖品" in text and "站点新加的奖品？" in text


# ============================================================
# 清空 / 撤销 / 导出→清空→导入
# ============================================================

def _clear_config(scope="all", **overrides):
    overrides.setdefault("notify", True)
    return _config_for("hhanclub.net", clear_scope=scope, do_clear=True, **overrides)


def test_clear_history_only(plugin):
    _seed_total(plugin, draws=100)
    plugin.save_data("history", [{"date": "2026-08-20 09:00:00", "draws": 100}])
    plugin.init_plugin(_clear_config("history"))

    assert plugin.get_data("history") is None
    assert plugin.get_data("total")["draws"] == 100, "只清运行记录就别动统计"


def test_clear_stats_only(plugin):
    _seed_total(plugin, draws=100)
    plugin.save_data("history", [{"date": "2026-08-20 09:00:00", "draws": 100}])
    plugin.init_plugin(_clear_config("stats"))

    assert plugin.get_data("total") is None
    assert len(plugin.get_data("history")) == 1, "只清统计就别动运行记录"


def test_clear_all(plugin):
    _seed_total(plugin, draws=100)
    plugin.save_data("history", [{"date": "2026-08-20 09:00:00", "draws": 100}])
    plugin.init_plugin(_clear_config("all"))

    assert plugin.get_data("total") is None
    assert plugin.get_data("history") is None
    assert "暂无抽奖记录" in str(plugin.get_page())


def test_clear_resets_switch(plugin):
    _seed_total(plugin, draws=100)
    plugin.init_plugin(_clear_config("all"))
    assert plugin._do_clear is False
    assert plugin._config["do_clear"] is False


def test_clear_empty_is_a_no_op(plugin):
    plugin.init_plugin(_clear_config("all"))
    assert any("本来就是空的" in (m.get("text") or "") for m in plugin.messages)
    assert plugin.get_data("before_clear") is None, "什么都没清就别留快照"


def test_restore_after_clear(plugin):
    """清空是不可逆的操作，配置页上一个开关离手滑只有一下的距离 —— 得能撤。"""
    _seed_total(plugin, draws=34228, beans=72451900)
    plugin.save_data("history", [{"date": "2026-08-20 09:00:00", "draws": 100}])

    plugin.init_plugin(_clear_config("all"))
    assert plugin.get_data("total") is None

    plugin.init_plugin(_config_for("hhanclub.net", do_restore=True, notify=True))
    total = plugin.get_data("total")
    assert total["draws"] == 34228
    assert total["gains"]["beans"] == 72451900
    assert len(plugin.get_data("history")) == 1
    assert plugin.get_data("before_clear") is None, "撤过一次就该把快照消掉"
    assert plugin._do_restore is False


def test_restore_without_snapshot(plugin):
    _seed_total(plugin, draws=100)
    plugin.init_plugin(_config_for("hhanclub.net", do_restore=True, notify=True))
    assert plugin.get_data("total")["draws"] == 100, "没快照就别动现有数据"
    assert any("没有可撤销的快照" in (m.get("text") or "") for m in plugin.messages)


def test_two_one_shot_switches_do_nothing(plugin):
    """一次保存只做一件事。同时勾多个只能是勾错了，与其猜哪个优先，不如都不做。"""
    _seed_total(plugin, draws=100)
    plugin.init_plugin(_config_for(
        "hhanclub.net", notify=True, do_clear=True, clear_scope="all",
        do_import=True, import_data=json.dumps(_backup())))

    assert plugin.get_data("total")["draws"] == 100, "谁都不该执行"
    assert plugin._do_clear is False and plugin._do_import is False, "但开关都要复位"
    assert any("一次只能做一件" in (m.get("text") or "") for m in plugin.messages)


def test_export_clear_import_round_trip(plugin):
    """导出 → 清空 → 把刚导出的那份导回来。这是最常用的搬家 / 重置流程，
    必须能走通 —— 清空要把记录线一起清掉，否则导回来会被「两份记录同源」拦住。"""
    _seed_total(plugin, draws=34228, beans=72451900, origin="mpline")
    plugin.save_data("history", [{"date": "2026-08-20 09:00:00", "draws": 100,
                                  "cost": 200000, "beans": 1125900, "profit": 925900}])
    backup = plugin.build_backup()
    assert backup["total"]["draws"] == 34228

    # 清空（统计和运行记录都清）
    plugin.init_plugin(_clear_config("all"))
    assert plugin.get_data("total") is None

    # 原样导回来
    plugin.init_plugin(_import_config(backup))
    total = plugin.get_data("total")
    assert total["draws"] == 34228, "清空之后导回自己的备份必须成功"
    assert total["cost"] == 34228 * 2000
    assert total["gains"]["beans"] == 72451900
    assert not any("⛔" in (m.get("text") or "") for m in plugin.messages), "不该被查重拦下"


def test_export_clear_import_replace_keeps_lineage(plugin):
    """用「覆盖」导回来的话，记录线也跟着回来 —— 恢复得更彻底。"""
    _seed_total(plugin, draws=500, origin="mpline")
    backup = plugin.build_backup()
    origin = backup["originId"]

    plugin.init_plugin(_clear_config("all"))
    plugin.init_plugin(_import_config(backup, mode="replace"))

    total = plugin.get_data("total")
    assert total["draws"] == 500
    assert total["originId"] == origin, "覆盖恢复应当连记录线一起回来"


def test_clearing_only_history_still_blocks_reimport(plugin):
    """只清了运行记录、统计还在 —— 这时候再导回自己的备份，仍然要被拦住，
    不然就是把自己算两遍。"""
    _seed_total(plugin, draws=500, origin="mpline")
    backup = plugin.build_backup()
    plugin.init_plugin(_clear_config("history"))

    plugin.init_plugin(_import_config(backup))
    assert plugin.get_data("total")["draws"] == 500, "统计还在，不该重复合并"
    assert any("同源" in (m.get("text") or "") for m in plugin.messages)


# ============================================================
# review 带出来的几处
# ============================================================

def test_update_config_covers_every_form_field(plugin):
    """配置页控件、默认值、写回配置三张单子必须一致。

    少一项就是：界面上改了、保存后又被写回旧值，或者复位 onlyonce 时把某项
    抹掉。前两张有 test_form_models_match_defaults 盯着，这条盯第三张。"""
    _, defaults = plugin.get_form()
    plugin._config.clear()
    plugin._HHClubLottery__update_config()
    assert set(plugin._config) == set(defaults), (
        f"只在写回里有：{set(plugin._config) - set(defaults)}；"
        f"只在默认值里有：{set(defaults) - set(plugin._config)}")


def test_concurrent_starts_only_run_once(plugin, monkeypatch):
    """定时任务、/run 接口、立即运行一次是三个不同的线程。

    要命的窗口在「检查 self._running」和「置位 self._running」之间：光靠
    if 挡不住同时进来，漏过去就是两轮一起抽，花的是真憨豆。这里往那个窗口
    里塞一个会拖时间的 Event.clear()，把窗口撑到肉眼可见，再放六个线程进去。
    """
    import threading

    class SlowEvent(threading.Event):
        def clear(self):
            time.sleep(0.2)      # 检查过了、还没置位 —— 别的线程正好撞进来
            return super().clear()

    site = FakeSite()
    site.draw_queue = [win("补签卡 1") for _ in range(60)]
    server, host = start_site(site)
    started = []

    real_run = HH.LotteryRunner.run

    def counting_run(self):
        started.append(1)
        return real_run(self)

    monkeypatch.setattr(HH.LotteryRunner, "run", counting_run)
    monkeypatch.setattr(HH.LotteryRunner, "sleep",
                        lambda self, ms: self.stop_event.is_set())
    try:
        _configure(plugin, host, draws=5)
        plugin._stop_event = SlowEvent()
        threads = [threading.Thread(target=plugin.run_lottery) for _ in range(6)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(15)
    finally:
        stop_site(server)

    assert len(started) == 1, f"只该跑一轮，实际起了 {len(started)} 轮"
    assert len(plugin.get_data("history")) == 1
    assert site.draw_calls == 5, "抽的次数就是设定的那些，不能翻倍"


def test_unknown_import_mode_is_treated_as_the_safest(plugin):
    """配置里万一是个认不出的导入方式，也得按最保守的来 —— 拦，而不是
    绕过查重闷头合并。"""
    _seed_total(plugin, draws=500, origin="mpline")
    backup = plugin.build_backup()
    plugin.init_plugin(_import_config(backup, mode="乱填的"))
    assert plugin.get_data("total")["draws"] == 500, "认不出的方式不该绕过查重"
    assert any("同源" in (m.get("text") or "") for m in plugin.messages)


def test_history_days_is_at_least_one(plugin):
    """填 0 的话 `x or 90` 会把它悄悄变成 90，说不清楚；直接收敛到 1 天。"""
    plugin.init_plugin(_config_for("hhanclub.net", history_days=0))
    assert plugin._history_days == 1
    plugin.init_plugin(_config_for("hhanclub.net", history_days=-5))
    assert plugin._history_days == 1
    plugin.init_plugin(_config_for("hhanclub.net", history_days=30))
    assert plugin._history_days == 30


def test_out_of_range_values_are_announced(plugin, instant, monkeypatch):
    """实机上有人把「单次运行上限」填成了 600000 分钟，静悄悄按 1440 跑了，
    配置页上还显示 600000 —— 那就等于没人知道。"""
    warnings = []
    monkeypatch.setattr(HH.logger, "warning", lambda msg, *a, **k: warnings.append(str(msg)))

    site = FakeSite()
    site.draw_queue = [win("补签卡 1")]
    server, host = start_site(site)
    try:
        _configure(plugin, host, draws=1, max_minutes=600000)
        plugin.run_lottery()
    finally:
        stop_site(server)

    assert any("单次运行上限(分钟)" in w and "600,000" in w and "1,440" in w for w in warnings)


# ============================================================
# 油猴版导出的大奖时间线
# ============================================================

def _userscript_backup(jackpot_count=5, draws=8000):
    """一份油猴版 backupStats() 会吐出来的东西。

    名册是 total.jackpots，条目 {at, text}、新的在前，封顶 100 条 ——
    照着 hhclub-auto-lottery.user.js 的 emptyStats / recordDraw 写的。"""
    base = 1787000000000
    jackpots = [{"at": base - i * 3600_000,
                 "text": "VIP 7 Day(s)" if i % 3 == 0 else "憨豆 780000"}
                for i in range(jackpot_count)]
    vip = len([j for j in jackpots if "VIP" in j["text"]])
    big = jackpot_count - vip
    return {
        "kind": "hhclub-lottery-backup", "version": 4,
        "exportedAt": "2026-08-22T02:00:00.000Z", "source": "tampermonkey",
        "originId": "browserline01", "exportId": "browserfile01",
        "current": {"draws": 0},
        "total": {
            "version": 4, "draws": draws, "cost": draws * 2000,
            "gains": {"beans": big * 780000 + 500000, "rainbow": 70, "vip": vip * 7},
            "prizes": {
                "beans": {"count": draws - 20, "value": big * 780000 + 500000,
                          "tiers": {"780,000 憨豆": big, "100 憨豆": draws - 20 - big}},
                "vip": {"count": vip, "value": vip * 7, "tiers": {"7 天": vip}},
                "rainbow": {"count": 10, "value": 70, "tiers": {"7 天": 10}},
            },
            "raw": {"魔力 100": draws - 20},
            "originId": "browserline01",
            "firstAt": 1786000000000, "lastAt": base,
            "jackpots": jackpots,
            "imports": [],
        },
    }


def test_userscript_backup_carries_the_roster(plugin):
    """油猴版导出带不带大奖时间线 —— 带。导进 MP 能不能成 —— 能。"""
    payload = _userscript_backup(jackpot_count=5)
    plugin.init_plugin(_import_config(payload))

    total = plugin.get_data("total")
    assert total["draws"] == 8000, "统计进来了"
    assert len(total["jackpots"]) == 5, "名册一条不少"
    assert total["jackpots"][0]["text"] == "VIP 7 Day(s)"
    assert all(set(item) == {"at", "text"} for item in total["jackpots"])
    # 新的在前
    stamps = [item["at"] for item in total["jackpots"]]
    assert stamps == sorted(stamps, reverse=True)

    text = str(plugin.get_page())
    assert "大奖名册（中过 5 次，5 条有时间记录）" in text
    assert "没有时间记录" not in text, "名册齐了就别提这句"
    assert "2026-" in text


def test_merging_two_rosters_dedupes(plugin):
    """两边各有名册时合并：同一条（时刻 + 文案都一样）只留一份，
    否则同一份备份导两次就多出一堆重影。"""
    first = _userscript_backup(jackpot_count=5)
    plugin.init_plugin(_import_config(first))
    assert len(plugin.get_data("total")["jackpots"]) == 5

    # 另一台设备的备份，前三条大奖是同一批（两边互相导过），后两条是它自己的
    second = _userscript_backup(jackpot_count=3)
    second["originId"] = "browserline02"
    second["exportId"] = "browserfile02"
    second["total"]["originId"] = "browserline02"
    second["total"]["jackpots"] = second["total"]["jackpots"] + [
        {"at": 1786500000000, "text": "憨豆 780000"},
        {"at": 1786400000000, "text": "VIP 7 Day(s)"},
    ]
    plugin.init_plugin(_import_config(second, mode="force"))

    roster = plugin.get_data("total")["jackpots"]
    assert len(roster) == 7, "5 条原有 + 2 条新的，重合那 3 条不重复计"
    stamps = [item["at"] for item in roster]
    assert len(set(stamps)) == len(stamps)
    assert stamps == sorted(stamps, reverse=True)


def test_roster_survives_export_clear_import(plugin):
    """名册跟着备份走完整个来回。"""
    plugin.init_plugin(_import_config(_userscript_backup(jackpot_count=5)))
    before = plugin.get_data("total")["jackpots"]

    backup = plugin.build_backup()
    assert len(backup["total"]["jackpots"]) == 5, "MP 导出也要带名册"

    plugin.init_plugin(_clear_config("all"))
    plugin.init_plugin(_import_config(backup, mode="replace"))

    assert plugin.get_data("total")["jackpots"] == before


def test_roster_beyond_hundred_is_capped(plugin):
    """油猴版自己就封顶 100 条，这边也一样。"""
    payload = _userscript_backup(jackpot_count=100, draws=50000)
    payload["total"]["jackpots"] += [
        {"at": 1780000000000 - i, "text": "憨豆 780000"} for i in range(30)]
    plugin.init_plugin(_import_config(payload))
    assert len(plugin.get_data("total")["jackpots"]) == 100


# ============================================================
# 刷新
# ============================================================

def test_refresh_button_is_a_no_op_call(plugin):
    """MoviePilot 前端在 events.click 调完接口后会 emit(action)，容器收到就
    重新拉一遍整页 —— 所以「调一个什么都不做的接口」就是这里唯一能拿到的
    刷新手段。那这个接口就必须真的什么都不做。"""
    _seed_total(plugin, draws=100)
    before = json.dumps(plugin.get_data(), ensure_ascii=False, sort_keys=True)

    result = plugin.api_status()
    assert result["code"] == 0
    assert result["data"]["running"] is False
    assert result["data"]["total_draws"] == 100

    after = json.dumps(plugin.get_data(), ensure_ascii=False, sort_keys=True)
    assert after == before, "刷新不该改动任何数据"
    assert plugin.messages == [], "更不该推通知"


def test_status_api_while_running(plugin, monkeypatch):
    site = FakeSite()
    site.draw_queue = [win("憨豆 100", credit=100) for _ in range(6)]
    server, host = start_site(site)
    seen = {}

    def sleep_hook(self, ms):
        if self.current["draws"] == 2 and "status" not in seen:
            seen["status"] = plugin.api_status()
        return self.stop_event.is_set()

    monkeypatch.setattr(HH.LotteryRunner, "sleep", sleep_hook)
    try:
        _configure(plugin, host, draws=3)
        plugin.run_lottery()
    finally:
        stop_site(server)

    data = seen["status"]["data"]
    assert data["running"] is True
    assert data["draws"] == 2 and data["cost"] == 4000
    assert data["balance"] > 0 and data["elapsed"]


def test_status_card_does_not_show_all_zeros_while_warming_up(plugin, monkeypatch):
    """起跑的头一两秒还没回站点读余额，摆一排 0 出来会让人以为是坏了。"""
    site = FakeSite()
    site.draw_queue = [win("补签卡 1")]
    server, host = start_site(site)
    seen = {}

    real_snapshot = HH.LotteryRunner.snapshot

    def slow_snapshot(self):
        if "page" not in seen:
            seen["page"] = str(plugin.get_page())   # 此刻 balance 还是 0
        return real_snapshot(self)

    monkeypatch.setattr(HH.LotteryRunner, "snapshot", slow_snapshot)
    monkeypatch.setattr(HH.LotteryRunner, "sleep",
                        lambda self, ms: self.stop_event.is_set())
    try:
        _configure(plugin, host, draws=1)
        plugin.run_lottery()
    finally:
        stop_site(server)

    assert "正在启动" in seen["page"]
    assert "余额 0 憨豆" not in seen["page"]
    assert "已抽 0 次" not in seen["page"]


# ============================================================
# 跑着的时候页面上有什么
# ============================================================

def _page_while_running(plugin, monkeypatch, at_draw=3, **opts):
    site = FakeSite()
    site.balance = 1000000
    site.draw_queue = ([win("憨豆 5000", credit=5000), win("补签卡 1"),
                        win("憨豆 1000", credit=1000), win("彩虹ID 7 Day(s)")]
                       + [win("憨豆 100", credit=100) for _ in range(20)])
    server, host = start_site(site)
    seen = {}

    def sleep_hook(self, ms):
        if self.current["draws"] == at_draw and "page" not in seen:
            seen["page"] = str(plugin.get_page())
        time.sleep(0.01)          # 让「已跑」有个非零的秒数
        return self.stop_event.is_set()

    monkeypatch.setattr(HH.LotteryRunner, "sleep", sleep_hook)
    try:
        _configure(plugin, host, **opts)
        plugin.run_lottery()
    finally:
        stop_site(server)
    return seen["page"]


def test_running_card_shows_progress(plugin, monkeypatch):
    text = _page_while_running(plugin, monkeypatch, at_draw=3, draws=10)
    assert "正在抽 · 第 3 / 10 抽" in text
    assert "VProgressLinear" in text and "model-value': 30.0" in text


def test_running_card_shows_profit(plugin, monkeypatch):
    text = _page_while_running(plugin, monkeypatch, at_draw=3, draws=10)
    # 3 抽：5,000 + 补签卡 + 1,000 = 获得 6,000，消耗 6,000，盈亏 0
    assert "消耗 6,000 · 获得 6,000" in text
    assert "盈亏 +0（+0.0%）" in text
    assert "余额" in text


def test_running_card_shows_timing(plugin, monkeypatch):
    text = _page_while_running(plugin, monkeypatch, at_draw=3, draws=10)
    assert "已跑" in text
    assert "预计还要" in text, "有分母才估得出剩余"


def test_running_card_shows_prize_brief(plugin, monkeypatch):
    text = _page_while_running(plugin, monkeypatch, at_draw=4, draws=10)
    assert "本轮奖品：" in text
    assert "💰 憨豆 ×2" in text
    assert "🎫 补签卡 ×1" in text
    assert "🌈 彩虹ID ×1" in text


def test_draw_to_bottom_has_no_progress_bar(plugin, monkeypatch):
    """一抽到底没有终点，画个进度条就是撒谎。"""
    text = _page_while_running(plugin, monkeypatch, at_draw=3, draws=0, reserve=980000)
    assert "一抽到底" in text
    assert "VProgressLinear" not in text
    assert "预计还要" not in text
    assert "平均每抽" in text, "估不出剩余，至少给个速度"


def test_whole_page_follows_the_running_round(plugin, monkeypatch):
    """total 只在一轮跑完时才写库。挂机中途点刷新，历史总计不能停在开跑前 ——
    不然只有顶上的状态卡在动，下面几张卡纹丝不动，看着像没在记。"""
    _seed_total(plugin, draws=1000, beans=500000, origin="mpline")
    text = _page_while_running(plugin, monkeypatch, at_draw=3, draws=10)

    assert "1,003 抽" in text, "历史总计要含上跑到一半的这三抽"
    assert "1,000 抽" not in text, "不该还停在开跑前"
    # 落盘的那份这会儿确实还没动
    assert plugin.get_data("total")["draws"] in (1000, 1010)


def test_live_stats_failure_falls_back(plugin, monkeypatch):
    """抽奖不能被数据页拖累：快照读不到就退回落盘那份，页面照样出得来。"""
    _seed_total(plugin, draws=777)

    class Boom:
        current = {"draws": 0}
        balance = 0

        def stats_snapshot(self):
            raise RuntimeError("dictionary changed size during iteration")

    plugin._running = True
    plugin._runner = Boom()
    try:
        text = str(plugin.get_page())
    finally:
        plugin._running = False
        plugin._runner = None
    assert "777 抽" in text


# ============================================================
# 抽奖途中动统计（会重复落盘 / 丢数据的两条路）
# ============================================================

def _do_while_running(plugin, monkeypatch, at_draw, action, draws=6):
    site = FakeSite()
    site.draw_queue = [win("补签卡 1") for _ in range(20)]
    server, host = start_site(site)
    out = {}

    def sleep_hook(self, ms):
        if self.current["draws"] == at_draw and "done" not in out:
            out["done"] = True
            out["result"] = action(host)
        return self.stop_event.is_set()

    monkeypatch.setattr(HH.LotteryRunner, "sleep", sleep_hook)
    try:
        _configure(plugin, host, draws=draws)
        plugin.run_lottery()
    finally:
        stop_site(server)
    assert out.get("done"), "钩子没触发，这个用例没测到东西"
    return out.get("result")


def test_import_while_running_is_refused(plugin, monkeypatch):
    """跑着的那一轮手里攥着自己那份统计，收尾时整份写回库。这时候导入，
    几秒后就会被那一份盖掉 —— 悄无声息地白干。"""
    _seed_total(plugin, draws=100, origin="mpline")
    payload = _backup(draws=9999, origin="otherline", export_id="f1")

    _do_while_running(plugin, monkeypatch, 2, lambda host: plugin.init_plugin(
        _config_for(host, notify=True, do_import=True,
                    import_data=json.dumps(payload))))

    assert any("正在抽奖" in (m.get("text") or "") for m in plugin.messages), "要拦下来并说清楚"
    assert plugin.get_data("total")["draws"] == 106, "100 + 这轮 6 抽；导入的 9,999 一个都不该进来"


@pytest.mark.parametrize("switch,extra", [
    ("do_clear", {"clear_scope": "all"}),
    ("do_restore", {}),
])
def test_clear_and_restore_while_running_are_refused(plugin, monkeypatch, switch, extra):
    _seed_total(plugin, draws=100)
    _do_while_running(plugin, monkeypatch, 2, lambda host: plugin.init_plugin(
        _config_for(host, notify=True, **{switch: True}, **extra)))

    assert any("正在抽奖" in (m.get("text") or "") for m in plugin.messages)
    assert plugin.get_data("total")["draws"] == 106, "统计不该被动过"


def test_export_while_running_keeps_one_lineage(plugin, monkeypatch):
    """跑到一半点导出，编号是那会儿现生成的。不写回运行中那份的话，收尾落盘
    会另起一个，这份备份就成了孤儿 —— 以后导回来认不出同源，会被当成别人的
    记录合进去，等于把自己算两遍。"""
    _seed_total(plugin, draws=50)
    plugin.del_data("total")
    plugin.save_data("total", {"draws": 50, "cost": 100000, "gains": {"beans": 20000},
                               "prizes": {"beans": {"count": 50, "value": 20000,
                                                    "tiers": {"400 憨豆": 50}}}})

    backup = _do_while_running(plugin, monkeypatch, 2, lambda host: plugin.build_backup())

    after = plugin.get_data("total")
    assert backup["originId"], "导出必须带记录线编号"
    assert backup["originId"] == after["originId"], "收尾落盘要沿用同一个编号，不能另起"
    assert backup["total"]["draws"] == 52, "导的是含这一轮在内的实时统计，和页面上看到的一致"
    assert after["draws"] == 56

    # 把这份备份导回来，必须被同源拦住 —— 这就是「重复落盘」真正的入口
    plugin.init_plugin(_import_config(backup))
    assert plugin.get_data("total")["draws"] == 56, "自己导出的自己导回来不能被算两遍"
    assert any("同源" in (m.get("text") or "") for m in plugin.messages)


def test_one_round_writes_history_once(plugin, instant):
    """一轮只落一条运行记录。"""
    site = FakeSite()
    site.draw_queue = [win("补签卡 1") for _ in range(5)]
    server, host = start_site(site)
    try:
        _configure(plugin, host, draws=3)
        plugin.run_lottery()
    finally:
        stop_site(server)
    assert len(plugin.get_data("history")) == 1
    assert plugin.get_data("total")["draws"] == 3, "这一轮只该被计一次"


# ============================================================
# 本轮 review 带出来的
# ============================================================

def test_api_run_requires_enabled(plugin):
    """「禁用」就该是「不会花憨豆」。定时服务本来就要 enabled 才注册，
    数据页的开始按钮也按这个置灰 —— 接口再放行就前后不一致了。"""
    plugin._enabled = False
    result = plugin.api_run()
    assert result["code"] == 1 and "未启用" in result["message"]
    assert plugin._running is False

    plugin._enabled = True
    plugin._running = True          # 已经在跑，也该拦
    assert plugin.api_run()["code"] == 1
    plugin._running = False


def test_status_card_is_honest_when_snapshot_fails(plugin):
    """跑着但快照读不到时，别谎称「正在启动」—— 那会让人以为刚开始。"""
    class Boom:
        def stats_snapshot(self):
            raise RuntimeError("dictionary changed size during iteration")

    _seed_total(plugin, draws=777)
    plugin._running = True
    plugin._runner = Boom()
    try:
        text = str(plugin.get_page())
    finally:
        plugin._running = False
        plugin._runner = None

    assert "这一下没读到进度" in text
    assert "正在启动" not in text
    assert "777 抽" in text, "读不到实时的就退回落盘那份，页面照样出得来"


def test_action_notification_titles(plugin):
    """通知标题原来是从「📥 备份导入」里按空格抠字，多一个空格就散架。"""
    _seed_total(plugin, draws=100)
    plugin.init_plugin(_config_for("hhanclub.net", notify=True, do_restore=True))
    titles = [m.get("title") for m in plugin.messages]
    assert "【HHCLUB 幸运大转盘】撤销上次清空" in titles

    plugin.messages.clear()
    plugin.init_plugin(_clear_config("all"))
    assert "【HHCLUB 幸运大转盘】清空记录" in [m.get("title") for m in plugin.messages]


def test_get_form_delegates_to_the_form_module(plugin, monkeypatch):
    """配置页 260 多行纯 JSON 拼装、整个函数不碰 self，已经搬去 config_form.py。
    get_form 只该是个转发 —— 别哪天又往里塞逻辑。

    （不直接 import config_form 来比对：那样会拿 sys.modules 里当时的 settings
    重新绑一遍，插件自己那份用的是加载时的桩，两边的 VERSION_FLAG 不一样。）
    """
    sentinel = ([{"component": "VForm", "content": []}], {"enabled": False})
    monkeypatch.setattr(HH, "build_form", lambda: sentinel)
    assert plugin.get_form() is sentinel


# ============================================================
# 本轮大奖单拎一行
# ============================================================

def test_jackpot_line_surfaces_big_beans(plugin, monkeypatch):
    """中了 780,000 混在类别汇总里根本看不出来 —— 只不过让「憨豆 ×10」
    变成「×11」，而那一注顶得上三百多抽的消耗。"""
    site = FakeSite()
    site.balance = 2000000
    site.draw_queue = [win("憨豆 100", credit=100), win("憨豆 780000", credit=780000),
                       win("憨豆 100", credit=100), win("补签卡 1")] +                       [win("憨豆 100", credit=100) for _ in range(10)]
    server, host = start_site(site)
    seen = {}

    def sleep_hook(self, ms):
        if self.current["draws"] == 4 and "page" not in seen:
            seen["page"] = str(plugin.get_page())
        return self.stop_event.is_set()

    monkeypatch.setattr(HH.LotteryRunner, "sleep", sleep_hook)
    try:
        _configure(plugin, host, draws=6)
        plugin.run_lottery()
    finally:
        stop_site(server)

    assert "🏆 本轮大奖：💰 780,000 憨豆 ×1" in seen["page"]
    # 类别汇总照旧给总数，两行不冲突
    assert "本轮奖品：💰 憨豆 ×3" in seen["page"]


def test_jackpot_line_shows_vip_with_swap(plugin, monkeypatch):
    site = FakeSite()
    site.user_class = "VIP"
    site.draw_queue = [win("补签卡 1"), win("VIP 7 Day(s)", credit=1000000),
                       win("补签卡 1")] + [win("补签卡 1") for _ in range(5)]
    server, host = start_site(site)
    seen = {}

    def sleep_hook(self, ms):
        if self.current["draws"] == 3 and "page" not in seen:
            seen["page"] = str(plugin.get_page())
        return self.stop_event.is_set()

    monkeypatch.setattr(HH.LotteryRunner, "sleep", sleep_hook)
    try:
        _configure(plugin, host, draws=5)
        plugin.run_lottery()
    finally:
        stop_site(server)

    assert "🏆 本轮大奖：⭐ VIP ×1（折算 1,000,000 憨豆）" in seen["page"]
    # VIP 已经在大奖那行说全了，别在类别汇总里再重复一遍
    assert "⭐ VIP ×1 ·" not in seen["page"].split("本轮奖品：")[1][:80]


def test_no_jackpot_line_when_nothing_big(plugin, monkeypatch):
    text = _page_while_running(plugin, monkeypatch, at_draw=3, draws=10)
    assert "本轮大奖" not in text, "没中就别占地方"
    assert "本轮奖品：" in text


def test_jackpot_parts():
    parts = HH.jackpot_parts(HH.normalize_stats({
        "draws": 5000,
        "prizes": {
            "beans": {"count": 4000, "tiers": {
                "100 憨豆": 3000, "780,000 憨豆": 3, "1,000,000 憨豆": 1, "5,000 憨豆": 996}},
            "vip": {"count": 2, "swappedBeans": 2000000, "tiers": {"已转换为憨豆 1,000,000": 2}},
            "makeup": {"count": 998, "tiers": {"1 个": 998}},
        }}))
    assert parts == ["⭐ VIP ×2（折算 2,000,000 憨豆）",
                     "💰 1,000,000 憨豆 ×1",
                     "💰 780,000 憨豆 ×3"], "VIP 在前，憨豆按档位从大到小"

    # 门槛以下的一个都不该混进来
    assert HH.jackpot_parts(HH.normalize_stats({
        "draws": 10, "prizes": {"beans": {"count": 10, "tiers": {"779,999 憨豆": 10}}}})) == []


def test_jackpot_parts_without_swap():
    """没被折算时不该凭空写个「折算 0 憨豆」。"""
    parts = HH.jackpot_parts(HH.normalize_stats({
        "draws": 10, "prizes": {"vip": {"count": 1, "value": 7, "tiers": {"7 天": 1}}}}))
    assert parts == ["⭐ VIP ×1"]


def test_current_balance_is_live_while_running(plugin, monkeypatch):
    """叫「当前余额」就得真是当前的。跑着的时候拿运行中那份的实时读数，
    不能还摆着上一轮收尾时的数字。"""
    plugin.save_data("history", [{"date": "2026-08-20 09:00:00", "draws": 10,
                                  "cost": 20000, "beans": 0, "profit": -20000,
                                  "balance": 111111, "duration": "1分", "status": "正常结束"}])
    site = FakeSite()
    site.balance = 999999
    site.draw_queue = [win("补签卡 1") for _ in range(8)]
    server, host = start_site(site)
    seen = {}

    def sleep_hook(self, ms):
        if self.current["draws"] == 2 and "page" not in seen:
            # 只看概览卡 —— 运行记录那张表里本来就该有上一轮的结束余额
            seen["page"] = str(plugin.get_page()[1])
        return self.stop_event.is_set()

    monkeypatch.setattr(HH.LotteryRunner, "sleep", sleep_hook)
    try:
        _configure(plugin, host, draws=4)
        plugin.run_lottery()
    finally:
        stop_site(server)

    assert "💰 当前余额" in seen["page"]
    assert "995,999" in seen["page"], "999,999 - 2 抽 × 2,000"
    assert "111,111" not in seen["page"], "不该还摆着上一轮的余额"
    assert "抽奖中 · 实时结算" in seen["page"]


def test_current_balance_says_when_it_was_read(plugin):
    """空闲时只能是上一轮收尾的读数 —— 做种收益一直在涨，
    不说清楚截至什么时候就是在骗人。"""
    plugin.save_data("total", {"draws": 10, "cost": 20000, "gains": {"beans": 5000},
                               "prizes": {"beans": {"count": 10, "value": 5000,
                                                    "tiers": {"500 憨豆": 10}}}})
    plugin.save_data("history", [{"date": "2026-08-22 17:46:55", "draws": 10,
                                  "cost": 20000, "beans": 5000, "profit": -15000,
                                  "balance": 5530655, "duration": "1分", "status": "正常结束"}])
    text = str(plugin.get_page())
    assert "💰 当前余额" in text and "5,530,655" in text
    assert "截至 2026-08-22 17:46:55" in text
    assert "最近余额" not in text


# ============================================================
# MP 这边自己记大奖名册
# ============================================================

def _run_and_get_roster(plugin, queue, **opts):
    site = FakeSite()
    site.balance = 5000000
    site.user_class = "VIP"
    site.draw_queue = queue
    server, host = start_site(site)
    try:
        _configure(plugin, host, **opts)
        plugin.run_lottery()
    finally:
        stop_site(server)
    return (plugin.get_data("total") or {}).get("jackpots") or []


def test_big_beans_are_recorded(plugin, instant):
    """在 MP 里中了 780,000，名册就该有 —— 之前只有油猴版会记，
    在 MP 上中的大奖日志滚掉就再也找不回来了。"""
    roster = _run_and_get_roster(plugin, [
        win("憨豆 100", credit=100),
        win("憨豆 780000", credit=780000),
        win("补签卡 1"),
    ], draws=3)

    assert len(roster) == 1
    assert roster[0]["text"] == "憨豆 780000"
    assert roster[0]["at"] > 1700000000000, "时刻是毫秒"
    assert set(roster[0]) == {"at", "text"}, "形状要和油猴版一致"


def test_vip_is_recorded(plugin, instant):
    roster = _run_and_get_roster(plugin, [win("VIP 7 Day(s)", credit=1000000)], draws=1)
    assert len(roster) == 1
    assert roster[0]["text"] == "VIP 7 Day(s)", "记的是原始文案，折算前"


def test_small_prizes_are_not_recorded(plugin, instant):
    """名册只收 VIP 和 780,000 以上的憨豆。"""
    roster = _run_and_get_roster(plugin, [
        win("憨豆 5000", credit=5000), win("憨豆 779999", credit=779999),
        win("补签卡 1"), win("彩虹ID 7 Day(s)"),
    ], draws=4)
    assert roster == []


def test_roster_口径_ignores_the_notification_threshold(plugin, instant):
    """「大奖通知门槛」是可配的，有人调到 100 图个热闹。名册不能跟着走，
    不然就成流水账了。"""
    roster = _run_and_get_roster(plugin, [
        win("憨豆 5000", credit=5000), win("憨豆 100", credit=100),
    ], draws=2, big_prize_min_beans=100)
    assert roster == [], "门槛调到 100 也不该往名册里塞"


def test_roster_accumulates_across_rounds(plugin, instant):
    """名册跟着 total 走，跨轮累积；新的在前。"""
    _run_and_get_roster(plugin, [win("憨豆 780000", credit=780000)], draws=1)
    roster = _run_and_get_roster(plugin, [win("VIP 7 Day(s)", credit=1000000)], draws=1)

    assert len(roster) == 2
    assert roster[0]["text"] == "VIP 7 Day(s)", "新的在前"
    assert roster[1]["text"] == "憨豆 780000"
    assert roster[0]["at"] >= roster[1]["at"]


def test_roster_shows_up_on_the_page(plugin, instant):
    _run_and_get_roster(plugin, [win("憨豆 780000", credit=780000)], draws=1)
    text = str(plugin.get_page())
    assert "大奖名册（中过 1 次，1 条有时间记录）" in text
    assert "憨豆 780000" in text
    assert "没有时间记录" not in text, "这条是 MP 自己记的，时刻齐全"
