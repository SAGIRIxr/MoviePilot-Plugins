# -*- coding: utf-8 -*-
"""HHCLUB幸运大转盘：本地假站点 + 真跑一遍 LotteryRunner。

抽奖接口花的是真憨豆，没法拿线上验证，所以这层是它唯一的安全网 —— 改完记得跑：

    pytest tests/v2/hhclublottery -m v2
"""
import json
import socket
import sys
import threading
from pathlib import Path

import pytest

pytestmark = pytest.mark.v2

# 插件目录不是可导入的包路径，按相对位置挂上去
PLUGIN_DIR = Path(__file__).resolve().parents[3] / "plugins.v2" / "hhclublottery"
sys.path.insert(0, str(PLUGIN_DIR))

import lottery as L  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fake_site import LUCKY_HTML, FakeSite, start_site, stop_site, win  # noqa: E402


class FastRunner(L.LotteryRunner):
    """把等待抹平，测行为不测墙上时钟。"""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.waits = []

    def sleep(self, ms):
        self.waits.append(ms)
        return self.stop_event.is_set()


def make_runner(host, site_total=None, runner_cls=FastRunner, **opts):
    notices = []
    logs = []
    options = L.LotteryOptions(host=host, follow_duration=True, **opts)
    runner = runner_cls(options=options, cookie="c_secure_uid=x; c_secure_pass=y",
                        total=site_total, log=logs.append,
                        notify=lambda t, b: notices.append((t, b)))
    return runner, logs, notices


def check(name, actual, expected):
    assert actual == expected, f"{name}：期望 {expected!r}，实际 {actual!r}"


def check_true(name, value):
    assert value, f"{name}：期望为真，实际 {value!r}"


# ============================================================
# 纯函数
# ============================================================

def test_pure():
    check("fmt 千分位", L.fmt(1574093), "1,574,093")
    check("fmt 两位小数", L.fmt(1256247.25), "1,256,247.25")
    check("fmt 一位小数", L.fmt(1000.5), "1,000.5")
    check("fmt 空", L.fmt(None), "0")

    check("first_number 千分位", L.first_number("消耗 2,000 憨豆"), 2000.0)
    check("decode_unicode", L.decode_unicode("\\u9b54\\u529b 2000"), "魔力 2000")

    check("憨豆", L.parse_prize_text("魔力 2000"), {"type": "beans", "value": 2000.0, "label": "2,000 憨豆"})
    check("憨豆·憨豆写法", L.parse_prize_text("憨豆 780000")["type"], "beans")
    check("彩虹", L.parse_prize_text("彩虹ID 7 Day(s)"), {"type": "rainbow", "value": 7.0, "label": "7 天"})
    check("VIP", L.parse_prize_text("VIP 7 Day(s)"), {"type": "vip", "value": 7.0, "label": "7 天"})
    check("补签卡", L.parse_prize_text("补签卡 1")["label"], "1 个")
    check("上传量 GB", L.parse_prize_text("上传量 2 GB")["value"], 2.0)
    check("上传量 TB→GB", L.parse_prize_text("上传量 1 TB")["value"], 1024.0)
    check("上传量 MB→GB", L.parse_prize_text("上传量 512 MB")["value"], 0.5)
    check("改名卡", L.parse_prize_text("改名卡 1")["type"], "rename")
    check("未知奖品", L.parse_prize_text("神秘礼包")["type"], "unknown")
    check("空文案", L.parse_prize_text("")["label"], "未知奖品")

    html = "<html>等级：<img src='pic/uploader.gif'><span class='Uploader_Name'>俺不中类</span></html>"
    check("等级 发布员", L.parse_class_rank(html), 12)
    check("等级 农民不是 None", L.parse_class_rank("等级：<img src='pic/peasant.gif'>"), 0)
    check("等级 读不到", L.parse_class_rank("<html>没有等级</html>"), None)
    check("等级 类名优先", L.parse_class_rank(
        "等级：<img src='pic/user.gif'><span class='VIP_Name'>x</span>"), 10)

    check("折算金额", L.parse_vip_swap_beans(LUCKY_HTML.format(balance="1", cost="2")), 1000000)
    check("折算金额读不到", L.parse_vip_swap_beans("<html>无</html>"), 0)

    check("余额解析", L.number_after_class(
        LUCKY_HTML.format(balance="1,574,093", cost="2,000"), "bean-number"), 1574093.0)
    check("消耗解析", L.number_after_class(
        LUCKY_HTML.format(balance="1,574,093", cost="2,000"), "use-bean"), 2000.0)

    # 退避阶梯：1 1 1 · 1.5 1.5 1.5 · 2.25 …
    check("退避 1", L.step_backoff_ms(1, 1000), 1000)
    check("退避 3", L.step_backoff_ms(3, 1000), 1000)
    check("退避 4", L.step_backoff_ms(4, 1000), 1500)
    check("退避 7", L.step_backoff_ms(7, 1000), 2250)
    check("退避封顶", L.step_backoff_ms(100, 10000), 300000)

    check("时长 秒", L.format_duration(45000), "45秒")
    check("时长 分", L.format_duration(125000), "2分 5秒")
    check("时长 时", L.format_duration(3725000), "1小时 2分")


def test_stats_migration():
    # 早期版本把「魔力」拆成独立类别存过，读取时要合回憨豆
    legacy = {
        "draws": 10, "cost": 20000,
        "gains": {"beans": 300, "magic": 7000, "rainbow": 7},
        "prizes": {
            "magic": {"count": 3, "value": 7000, "tiers": {"2,000 憨豆": 3}},
            "beans": {"count": 1, "value": 300, "tiers": {"300 憨豆": 1}},
            "rainbow": {"count": 1, "value": 7, "tiers": {"7 天": 1}},
        },
        "raw": {"魔力 2000": 3},
    }
    stats = L.normalize_stats(legacy)
    check("v3 迁移 gains 合并", stats["gains"]["beans"], 7300)
    check("v3 迁移 magic 清零", stats["gains"]["magic"], 0)
    check("v3 迁移 prizes 合并次数", stats["prizes"]["beans"]["count"], 4)
    check("v3 迁移 档位合并", stats["prizes"]["beans"]["tiers"], {"2,000 憨豆": 3, "300 憨豆": 1})
    check("v3 迁移 没有 magic 桶", "magic" in stats["prizes"], False)
    check("normalize 垃圾输入", L.normalize_stats("坏数据")["draws"], 0)

    payload = L.backup_payload(L.empty_stats(), stats)
    check("备份 kind", payload["kind"], "hhclub-lottery-backup")
    check("备份 version", payload["version"], 4)
    check("备份 source", payload["source"], "moviepilot")
    check_true("备份可 JSON 序列化", json.dumps(payload))


# ============================================================
# 端到端
# ============================================================

def test_fixed_draws():
    site = FakeSite()
    site.draw_queue = [
        win("\\u9b54\\u529b 2000", credit=2000),
        win("补签卡 1"),
        win("彩虹ID 7 Day(s)"),
        win("上传量 2 GB"),
        win("憨豆 100 ", credit=100),
    ]
    server, host = start_site(site)
    try:
        runner, logs, notices = make_runner(host, draws=5)
        runner.run()
    finally:
        stop_site(server)

    check("按次数抽 抽数", runner.current["draws"], 5)
    check("按次数抽 消耗", runner.current["cost"], 10000)
    check("按次数抽 憨豆收入", runner.current["gains"]["beans"], 2100)
    check("按次数抽 类别数", len(runner.current["prizes"]), 4)
    check("按次数抽 憨豆次数", runner.current["prizes"]["beans"]["count"], 2)
    check("按次数抽 彩虹天数", runner.current["gains"]["rainbow"], 7)
    check("按次数抽 停止原因", runner.stop_reason, "已达到设定抽奖次数（5 抽）")
    check("按次数抽 余额本地结算", runner.balance, 1574093 - 10000 + 2100)
    check("按次数抽 raw 文案已解码", "魔力 2000" in runner.current["raw"], True)
    check("按次数抽 档位 trim", runner.current["prizes"]["beans"]["tiers"].get("100 憨豆"), 1)
    check("按次数抽 total 同步累计", runner.total["draws"], 5)
    check("按次数抽 不多抽", site.draw_calls, 5)


def test_draw_to_bottom():
    site = FakeSite()
    site.balance = 10000
    site.draw_queue = [win("补签卡 1") for _ in range(10)]
    server, host = start_site(site)
    try:
        runner, logs, _ = make_runner(host, draws=0, reserve=4000)
        runner.run()
    finally:
        stop_site(server)

    # 10000 → 8000 → 6000 → 停（6000-2000=4000 不小于保留线，还能抽）→ 4000 → 停
    check("一抽到底 抽数", runner.current["draws"], 3)
    check("一抽到底 余额", runner.balance, 4000)
    check_true("一抽到底 停止原因", "保留线" in runner.stop_reason)


def test_rate_limit_and_errors():
    site = FakeSite()
    site.draw_queue = [
        {"ret": 1, "msg": "\\u4e0d\\u8981\\u91cd\\u590d\\u70b9\\u51fb"},   # 不要重复点击
        win("补签卡 1", duration=6000),
        {"ret": 1, "msg": "服务器开小差了"},
        win("补签卡 1", duration=6000),
    ]
    server, host = start_site(site)
    try:
        runner, logs, _ = make_runner(host, draws=2)
        runner.run()
    finally:
        stop_site(server)

    check("限流 不计入抽数", runner.current["draws"], 2)
    check("限流 请求发了 4 次", site.draw_calls, 4)
    check_true("限流 日志有补枪", any("不要重复点击" in line for line in logs))
    check_true("接口报错 日志", any("服务器开小差了" in line for line in logs))
    # 第一次限流时还没有 duration，走 blind_retry_ms(1000)；第二次有 duration 走 300
    check("限流 首次盲等 1 秒", runner.waits[0], 1000)
    check("接口报错 退避 1 秒", runner.waits[2], 1000)
    check("限流后计数器归零", runner.rate_limit_streak, 0)


def test_stop_signals():
    for msg, label in [("憨豆不足", "憨豆不足"), ("今日抽奖次数已用完", "次数用完")]:
        site = FakeSite()
        site.draw_queue = [win("补签卡 1"), {"ret": 1, "msg": msg}]
        server, host = start_site(site)
        try:
            runner, logs, _ = make_runner(host, draws=10)
            runner.run()
        finally:
            stop_site(server)
        check(f"{label} 立刻停", runner.current["draws"], 1)
        check(f"{label} 不重试", site.draw_calls, 2)
        check_true(f"{label} 停止原因", msg in runner.stop_reason)


def test_cookie_invalid():
    site = FakeSite()
    site.cookie_valid = False
    server, host = start_site(site)
    try:
        runner, logs, _ = make_runner(host, draws=5)
        raised = None
        try:
            runner.run()
        except L.CookieInvalid as err:
            raised = str(err)
    finally:
        stop_site(server)
    check_true("Cookie 失效抛 CookieInvalid", raised and "失效" in raised)
    check("Cookie 失效没抽", site.draw_calls, 0)


def test_vip_swap_eligible():
    """已是 VIP：站点改发 1,000,000 憨豆，档位改标，仍计一次 VIP 中奖。"""
    site = FakeSite()
    site.user_class = "VIP"
    # 中 VIP 时不扣豆之外还入账 100 万（站点折算），另加 60 做种收益
    site.draw_queue = [win("VIP 7 Day(s)", credit=1000060)]
    server, host = start_site(site)
    try:
        runner, logs, notices = make_runner(host, draws=1, notify_big_prize=True)
        runner.run()
    finally:
        stop_site(server)

    vip = runner.current["prizes"]["vip"]
    check("VIP折算 仍记一次 VIP", vip["count"], 1)
    check("VIP折算 天数扣回", runner.current["gains"]["vip"], 0)
    check("VIP折算 憨豆入账", runner.current["gains"]["beans"], 1000000)
    check("VIP折算 swappedBeans", vip["swappedBeans"], 1000000)
    check("VIP折算 档位改标", list(vip["tiers"]), ["已转换为憨豆 1,000,000"])
    check("VIP折算 汇总不含 1,000,060 档位", "1,000,060 憨豆" in json.dumps(runner.current), False)
    check_true("VIP折算 说明做种收益", any("做种收益" in m for m in runner.messages))
    check_true("VIP折算 推了大奖通知", notices and "大奖" in notices[0][0])
    check_true("VIP折算 通知里写明折算", "已折算 1,000,000 憨豆" in notices[0][1])


def test_vip_not_eligible():
    """等级不到 VIP：账面多出来的钱另有来源，按 VIP 记，不凭空造一百万。"""
    site = FakeSite()
    site.user_class = "User"
    site.draw_queue = [win("VIP 7 Day(s)", credit=1000000)]
    server, host = start_site(site)
    try:
        runner, logs, _ = make_runner(host, draws=1)
        runner.run()
    finally:
        stop_site(server)

    vip = runner.current["prizes"]["vip"]
    check("非VIP 按天数记", runner.current["gains"]["vip"], 7)
    check("非VIP 不加憨豆", runner.current["gains"]["beans"], 0)
    check("非VIP 档位不变", list(vip["tiers"]), ["7 天"])
    check_true("非VIP 有告警", any("等级不到 VIP" in m for m in runner.messages))


def test_vip_class_unreadable_narrow_band():
    """等级读不到时，余额必须贴着公布金额才敢认折算。"""
    site = FakeSite()
    site.user_class = None
    site.usercp_ok = False
    site.draw_queue = [win("VIP 7 Day(s)", credit=1000000)]
    server, host = start_site(site)
    try:
        runner, _, _ = make_runner(host, draws=1)
        runner.run()
    finally:
        stop_site(server)
    check("等级读不到但金额吻合 → 认折算",
          runner.current["prizes"]["vip"].get("swappedBeans"), 1000000)

    # 同期中了 780,000，顶过 50% 门槛但对不上公布金额 → 不认
    site2 = FakeSite()
    site2.user_class = None
    site2.usercp_ok = False
    site2.draw_queue = [win("VIP 7 Day(s)", credit=780000)]
    server2, host2 = start_site(site2)
    try:
        runner2, _, _ = make_runner(host2, draws=1)
        runner2.run()
    finally:
        stop_site(server2)
    check("等级读不到且金额对不上 → 按 VIP 记",
          runner2.current["prizes"]["vip"].get("swappedBeans"), None)
    check_true("窄带告警", any("对不上公布的" in m for m in runner2.messages))


def test_vip_real_days():
    """账面没多出钱 = 真拿到了天数。"""
    site = FakeSite()
    site.user_class = "VIP"
    site.draw_queue = [win("VIP 7 Day(s)", credit=0)]
    server, host = start_site(site)
    try:
        runner, _, _ = make_runner(host, draws=1)
        runner.run()
    finally:
        stop_site(server)
    check("真发天数 不折算", runner.current["prizes"]["vip"].get("swappedBeans"), None)
    check("真发天数 记 7 天", runner.current["gains"]["vip"], 7)


def test_mail_cleanup():
    """收尾翻全本：第一页被别的通知占满，抽奖通知埋在第二页也要清掉。"""
    site = FakeSite()
    site.mail_pages = [
        [{"id": "1", "subject": "种子被删除"}, {"id": "2", "subject": "幸运大转盘 中奖通知"}],
        [{"id": "3", "subject": "幸运大转盘 中奖通知"}, {"id": "4", "subject": "憨豆 改变"}],
        [{"id": "5", "subject": "幸运大转盘 中奖通知"}],
    ]
    server, host = start_site(site)
    try:
        runner, logs, _ = make_runner(host, draws=1, clean_mail=True)
        runner.clean_mailbox()
    finally:
        stop_site(server)

    check("清信 只删抽奖通知", sorted(set(site.deleted)), ["2", "3", "5"])
    check("清信 计数", runner.mail_cleaned, 3)
    check_true("清信 报了一句", any("清掉 3 封" in m for m in runner.messages))


def test_mail_during_run():
    """途中每 25 抽扫一次第一页。"""
    site = FakeSite()
    site.mail_pages = [[{"id": str(i), "subject": "幸运大转盘 中奖通知"} for i in range(30)]]
    site.draw_queue = [win("补签卡 1") for _ in range(25)]
    server, host = start_site(site)
    try:
        runner, logs, _ = make_runner(host, draws=25, clean_mail=True)
        runner.run()
    finally:
        stop_site(server)
    check("途中清信 抽满 25", runner.current["draws"], 25)
    check("途中清信 删了 30 封", len(site.deleted), 30)
    check_true("途中清信 记了日志", any("清掉" in line for line in logs))


def test_pacing():
    """自适应延迟：按上一抽的 duration 排队，请求发出即开始计时。"""
    options = L.LotteryOptions(host="x.test", follow_duration=True, duration_buffer_ms=0)
    runner = L.LotteryRunner(options, "ck")
    check("无 duration 时盲等 5 秒", runner.planned_gap(), 5000)
    runner.last_duration_ms = 7666
    check("按 duration 排队", runner.planned_gap(), 7666)
    runner.options.duration_buffer_ms = -500
    check("负缓冲更贴边", runner.planned_gap(), 7166)
    runner.options.duration_buffer_ms = 1000
    check("正缓冲更保守", runner.planned_gap(), 8666)

    runner.quick_retry_ms = 300
    check("补枪覆盖本次等待", runner.next_delay(), 300)
    check("补枪用过即清", runner.quick_retry_ms, 0)

    fixed = L.LotteryRunner(L.LotteryOptions(host="x.test", follow_duration=False, interval=6.8), "ck")
    check("固定间隔", fixed.planned_gap(), 6800)
    check("间隔下限 3 秒", L.LotteryOptions(host="x", interval=0.5).interval, 3.0)
    check("缓冲收敛下限", L.LotteryOptions(host="x", duration_buffer_ms=-9999).duration_buffer_ms, -500)
    check("缓冲收敛上限", L.LotteryOptions(host="x", duration_buffer_ms=99999).duration_buffer_ms, 5000)


def test_stop_event():
    """停用插件：循环当场收工，已抽的成绩留在 runner 上等着落盘。"""
    site = FakeSite()
    site.draw_queue = [win("补签卡 1") for _ in range(50)]
    stop = threading.Event()
    server, host = start_site(site)

    class StopAfterThree(FastRunner):
        def sleep(self, ms):
            if self.current["draws"] >= 3:
                stop.set()
            return self.stop_event.is_set()

    try:
        options = L.LotteryOptions(host=host, draws=50, follow_duration=True)
        runner = StopAfterThree(options, "ck", stop_event=stop)
        runner.run()
    finally:
        stop_site(server)

    check("停用后不再抽", runner.current["draws"], 3)
    check_true("停止原因写明", "停止" in runner.stop_reason or "停用" in runner.stop_reason)


def test_cross_run_accumulation():
    """跨次累计：上一轮的 total 传进来，这一轮接着加。"""
    site = FakeSite()
    site.draw_queue = [win("憨豆 100", credit=100), win("补签卡 1")]
    server, host = start_site(site)
    try:
        previous = L.empty_stats()
        previous["draws"] = 20
        previous["cost"] = 40000
        previous["gains"]["beans"] = 13900
        previous["prizes"] = {"beans": {"count": 15, "value": 13900, "tiers": {"100 憨豆": 9}}}
        runner, _, _ = make_runner(host, site_total=previous, draws=2)
        runner.run()
    finally:
        stop_site(server)

    check("累计 抽数", runner.total["draws"], 22)
    check("累计 消耗", runner.total["cost"], 44000)
    check("累计 憨豆", runner.total["gains"]["beans"], 14000)
    check("累计 档位叠加", runner.total["prizes"]["beans"]["tiers"]["100 憨豆"], 10)
    check("本次独立计数", runner.current["draws"], 2)


def test_summary_notice():
    site = FakeSite()
    site.draw_queue = [win("憨豆 100", credit=100), win("彩虹ID 7 Day(s)")]
    server, host = start_site(site)
    try:
        runner, _, _ = make_runner(host, draws=2)
        runner.run()
        text = runner.summary_notice("正常结束")
    finally:
        stop_site(server)

    check_true("结算 有任务结算头", "🎯 任务结算" in text)
    check_true("结算 有抽数", "+2 抽" in text)
    check_true("结算 有消耗", "-4,000 憨豆" in text)
    check_true("结算 有奖品明细", "🌈 彩虹ID｜1 次" in text)
    check_true("结算 有档位", "└ 7 天 × 1" in text)
    check_true("结算 有净盈亏", "净盈亏：-3,900" in text)
    check("结算 不重复回显开始行", text.count("▶ 开始"), 0)


def test_network_retry():
    """站点连不上：幂等请求内部先重试几次，全失败才抛出去。"""
    probe = socket.socket()
    probe.bind(("127.0.0.1", 0))
    dead_port = probe.getsockname()[1]
    probe.close()

    runner, logs, _ = make_runner(f"http://127.0.0.1:{dead_port}", draws=1)
    raised = None
    try:
        runner.run()
    except Exception as err:
        raised = err

    check_true("连不上 抛出异常", raised is not None)
    check_true("连不上 日志提示重试", any("网络不通" in line for line in logs))
    check("连不上 重试满 3 次", sum(1 for line in logs if "网络不通" in line), 3)
    check("连不上 没抽", runner.current["draws"], 0)


# ============================================================
# 中大奖就停（上游 2b454b4 / 60bfba9 / d1011a0）
# ============================================================

def _run_with_stop(queue, **opts):
    site = FakeSite()
    site.balance = 1000000
    site.draw_queue = queue
    server, host = start_site(site)
    try:
        runner, logs, notices = make_runner(host, draws=10, **opts)
        runner.run()
    finally:
        stop_site(server)
    return site, runner, logs, notices


def test_stop_on_780k():
    site, runner, _, _ = _run_with_stop(
        [win("补签卡 1"), win("憨豆 780000", credit=780000), win("补签卡 1")],
        stop_on_780k=True)
    check("中 780k 就停 抽数", runner.current["draws"], 2)
    check("中 780k 就停 不再发请求", site.draw_calls, 2)
    check_true("中 780k 停止原因", "命中停止条件（780,000 憨豆）" in runner.stop_reason)


def test_stop_on_780k_is_exact_tier():
    """只认 780,000 这一个档位 —— 别的大额憨豆不停。"""
    site, runner, _, _ = _run_with_stop(
        [win("憨豆 1000000", credit=1000000), win("憨豆 779999", credit=779999),
         win("补签卡 1")],
        stop_on_780k=True)
    check("1,000,000 不触发", runner.current["draws"], 3)
    check("779,999 不触发", runner.stop_reason, "已达到设定抽奖次数（10 抽）"
          if runner.current["draws"] >= 10 else runner.stop_reason)
    check_true("跑完整个队列", site.draw_calls >= 3)


def test_stop_on_vip_covers_swapped():
    """VIP 折算成憨豆的那一注，type 仍是 vip，照样按 VIP 停。"""
    site, runner, _, notices = _run_with_stop(
        [win("VIP 7 Day(s)", credit=1000000), win("补签卡 1")],
        stop_on_vip=True)
    check("中 VIP 就停 抽数", runner.current["draws"], 1)
    check("折算记上了", runner.current["prizes"]["vip"].get("swappedBeans"), 1000000)
    check_true("停止原因写明含折算", "VIP（含折算）" in runner.stop_reason)
    check_true("大奖通知末行改口", notices and "已按设置停止本轮抽奖" in notices[0][1])


def test_no_stop_when_switches_off():
    site, runner, _, notices = _run_with_stop(
        [win("憨豆 780000", credit=780000), win("VIP 7 Day(s)", credit=0),
         win("补签卡 1")])
    check("开关都关 不停", runner.current["draws"], 3)
    check_true("通知末行还是挂机中",
               notices and all("后台持续挂机抽奖中" in body for _, body in notices))


def test_stop_calibrates_balance():
    """停在中奖那一刻要对账，不能摆本地估算。"""
    site, runner, logs, _ = _run_with_stop(
        # 站点实际入账比奖品档位多 137（做种收益），本地估算算不出来
        [win("憨豆 780000", credit=780137)],
        stop_on_780k=True)
    check("停机前回服务端校准", runner.balance, 1000000 - 2000 + 780137)
    check("多读了一次 lucky.php", site.lucky_calls, 2)


def test_stop_on_vip_skips_double_calibration():
    """VIP 那一注折算核对时已经校准过，停机前不用再要一遍。"""
    site, runner, _, _ = _run_with_stop(
        [win("VIP 7 Day(s)", credit=1000000)], stop_on_vip=True)
    # 开跑一次 + 折算核对一次 = 2；再多就是白要了
    check("不重复校准", site.lucky_calls, 2)


def test_notify_threshold_and_stop_are_independent():
    """通知门槛和停机条件是两回事：门槛调到只推 VIP，780k 照样能停。"""
    site, runner, _, notices = _run_with_stop(
        [win("憨豆 780000", credit=780000)],
        stop_on_780k=True, big_prize_min_beans=0, notify_big_prize=True)
    check("停了", runner.current["draws"], 1)
    check("没推大奖通知", notices, [])


# ============================================================
# 请求失败要说清是怎么失败的（上游 57fb242）
# ============================================================

def test_describe_draw_failure():
    d = L.LotteryRunner.describe_draw_failure
    check("网络层错误", d({"error": "Connection reset"}), "请求失败：Connection reset")
    check("401", d({"status": 401, "ok": False}), "请求被拒（登录多半已经失效）")
    check("403", d({"status": 403, "ok": False}), "请求被拒（登录多半已经失效）")
    check("502", d({"status": 502, "ok": False}), "请求失败：HTTP 502")
    # 站点掉登录时拿 200 回一张登录页 —— 以前只报一句「请求失败：200」
    check_true("200 登录页", "登录已失效" in d(
        {"status": 200, "ok": True, "raw": "<html><form action='takelogin.php'>"}))
    check("200 其他 HTML", d({"status": 200, "ok": True, "raw": "<html>维护中</html>"}),
          "站点没返回 JSON（维护页或人机验证？）")
    check("200 非 HTML", d({"status": 200, "ok": True, "raw": "???"}),
          "站点返回了认不出的内容（HTTP 200）")


def test_login_page_failure_shows_up_in_log():
    """整条链路走一遍：抽奖接口回登录页时，日志得说人话。

    页面还能读、只有接口掉登录，所以走的是「请求失败」那条线而不是
    CookieInvalid —— 以前这里只会记一句「请求失败（HTTP 200）」。"""
    site = FakeSite()
    site.draw_returns_login = True
    server, host = start_site(site)

    class StopAfterOneFailure(FastRunner):
        def sleep(self, ms):
            self.stop_event.set()   # 记一条就够，不用真的一直重试下去
            return True

    try:
        options = L.LotteryOptions(host=host, draws=5, follow_duration=True)
        logs = []
        runner = StopAfterOneFailure(options, "ck", log=logs.append)
        runner.run()
    finally:
        stop_site(server)

    check("一抽没记上", runner.current["draws"], 0)
    check_true("日志指向重新登录", any("登录已失效" in line for line in logs))
    check_true("不再是干巴巴的 HTTP 200",
               not any("请求失败（HTTP 200）" in line for line in logs))


# ============================================================
# 备份编号与外来字段（上游 a2a0f2d / d1011a0）
# ============================================================

def test_backup_carries_origin_and_export_id():
    total = L.empty_stats()
    first = L.backup_payload(L.empty_stats(), total)
    second = L.backup_payload(L.empty_stats(), total)

    check_true("有 originId", first["originId"])
    check_true("有 exportId", first["exportId"])
    check("originId 认记录线，导多少次都一样", second["originId"], first["originId"])
    check_true("exportId 认这一个文件，每次都换", second["exportId"] != first["exportId"])
    check("originId 也进 total", first["total"]["originId"], first["originId"])
    check("编号长度和油猴版一致", len(first["originId"]), 12)


def test_stamp_origin_is_idempotent():
    total = L.normalize_stats({"originId": "keepthisid00"})
    L.stamp_origin(total)
    check("已有编号不覆盖", total["originId"], "keepthisid00")


def test_foreign_fields_survive():
    """油猴版的大奖名册和导入台账原样带过去 —— 别把人家攒了几个月的记录抹了。"""
    incoming = {
        "draws": 5, "cost": 10000, "originId": "browserline",
        "gains": {"beans": 100},
        "jackpots": [{"label": "VIP 7 天", "at": 1755000000000}],
        "imports": [{"exportId": "abc", "originId": "xyz", "draws": 3, "at": 1}],
    }
    stats = L.normalize_stats(incoming)
    check("名册保住了", stats["jackpots"], incoming["jackpots"])
    check("台账保住了", stats["imports"], incoming["imports"])
    check("记录线保住了", stats["originId"], "browserline")

    # 再导出去时也得原样带着
    payload = L.backup_payload(L.empty_stats(), stats)
    check("导出仍带名册", payload["total"]["jackpots"], incoming["jackpots"])
    check("导出沿用原记录线", payload["originId"], "browserline")

    # 没有这两个字段的普通统计不该凭空长出来
    plain = L.normalize_stats({"draws": 1})
    check_true("普通统计不长名册", "jackpots" not in plain and "imports" not in plain)
