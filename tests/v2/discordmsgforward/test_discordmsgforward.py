# -*- coding: utf-8 -*-
"""Discord消息转发 插件单测

覆盖 v4.2.0 的稳定性修复、v4.3.0 的频道互转与正则示例、
v4.4.0 的跳转链接开关与重复转发检测。
"""
from datetime import datetime, timedelta

import pytest
import pytz

pytestmark = pytest.mark.v2


def _rule(**kwargs):
    base = {
        "id": "r1", "name": "测试规则", "enabled": True,
        "channels": ["100"], "notify_enabled": True, "notify_channels": [],
        "forward_channels": [], "discord_template": "", "keywords": "",
        "blocked_keywords": "", "author_include": "", "author_exclude": "",
        "code_regex": "", "aggregate": True, "forward_image": True,
        "jump_link": True, "dedup": False,
        "quiet_hours": "", "title_template": "", "text_template": "",
    }
    base.update(kwargs)
    return base


def _item(text="内容", author="小明", codes=None, when="2026-01-01 10:00:00"):
    return {"text": text, "author": author, "time": when,
            "image": None, "link": None, "codes": codes or []}


def _msg(mid, content="hello", author="小明", uid="u1"):
    return {"id": str(mid), "content": content,
            "author": {"username": author, "id": uid},
            "timestamp": "2026-01-01T10:00:00+00:00"}


def _resp(status=200, data=None, text=""):
    """构造一个最小的 requests.Response 替身"""
    return type("R", (), {"status_code": status, "text": text,
                          "json": lambda self, d=data: d if d is not None else {}})()


# ---------------- 模板渲染 ----------------
class TemplateTest:
    def test_codes_line_removed_when_empty(self, dmf):
        render = dmf.DiscordMsgForward._DiscordMsgForward__render_template
        out = render("{content}\n\n🎁 码：{codes}\n\n👤 {author}",
                     {"content": "正文", "codes": "", "author": "小明"})
        assert "🎁" not in out
        assert "正文" in out and "小明" in out

    def test_content_braces_not_double_replaced(self, dmf):
        render = dmf.DiscordMsgForward._DiscordMsgForward__render_template
        out = render("{content}", {"content": "含有 {author} 字样的正文", "author": "小明"})
        assert out == "含有 {author} 字样的正文"


# ---------------- 免打扰时段 ----------------
class QuietHoursTest:
    @pytest.mark.parametrize("quiet,now_hm,expected", [
        ("23:00-08:00", (23, 30), True),    # 跨零点，起点后
        ("23:00-08:00", (3, 0), True),      # 跨零点，零点后
        ("23:00-08:00", (12, 0), False),
        ("09:00-18:00", (12, 0), True),
        ("09:00-18:00", (8, 0), False),
        ("09:00-18:00", (18, 0), False),    # 右开区间
        ("", (12, 0), False),
        ("乱写", (12, 0), False),
        ("25:00-08:00", (12, 0), False),    # 非法小时不再抛异常
        ("10:00-10:00", (10, 30), False),   # 起止相同视为不启用
    ])
    def test_quiet_hours(self, dmf, settings_stub, monkeypatch, quiet, now_hm, expected):
        tz = pytz.timezone(settings_stub.TZ)
        fixed = tz.localize(datetime(2026, 1, 1, now_hm[0], now_hm[1]))

        class _FakeDatetime(datetime):
            @classmethod
            def now(cls, tz=None):
                return fixed

        monkeypatch.setattr(dmf, "datetime", _FakeDatetime)
        assert dmf.DiscordMsgForward._DiscordMsgForward__in_quiet_hours(quiet) is expected


# ---------------- 过滤链 ----------------
class FilterTest:
    @pytest.mark.parametrize("rule_kwargs,text,author,expected", [
        ({}, "任意内容", "小明", True),
        ({"keywords": "礼包码"}, "今日礼包码放送", "小明", True),
        ({"keywords": "礼包码"}, "今日公告", "小明", False),
        ({"blocked_keywords": "广告"}, "这是广告", "小明", False),
        ({"author_include": "官方Bot"}, "内容", "小明", False),
        ({"author_include": "官方bot"}, "内容", "官方Bot", True),   # 不分大小写
        ({"author_exclude": "小明"}, "内容", "小明", False),
        # 屏蔽词优先于关键词白名单
        ({"keywords": "礼包码", "blocked_keywords": "测试"}, "礼包码测试", "小明", False),
    ])
    def test_filters(self, plugin, rule_kwargs, text, author, expected):
        assert plugin._DiscordMsgForward__pass_filters(_rule(**rule_kwargs), text, author) is expected


# ---------------- 内容提取正则 ----------------
class ExtractCodesTest:
    def test_dedup_and_group(self, dmf):
        extract = dmf.DiscordMsgForward._DiscordMsgForward__extract_codes
        assert extract(r"码[:：]\s*(\w+)", "码：ABC123 码：ABC123 码：XYZ") == ["ABC123", "XYZ"]

    def test_invalid_regex_returns_empty(self, dmf):
        extract = dmf.DiscordMsgForward._DiscordMsgForward__extract_codes
        assert extract(r"([", "任意") == []


# ---------------- 分页拉取 ----------------
class FetchPagingTest:
    def test_follows_pages_until_short_batch(self, plugin, monkeypatch):
        pages = [
            [_msg(i) for i in range(1, 101)],   # 满页，应继续翻
            [_msg(i) for i in range(101, 131)], # 不满页，停止
        ]
        calls = []

        def fake_get(path, params=None, _retry=0):
            calls.append(params)
            data = pages[len(calls) - 1] if len(calls) <= len(pages) else []
            return type("R", (), {"status_code": 200, "json": lambda self, d=data: d})()

        monkeypatch.setattr(plugin, "_DiscordMsgForward__api_get", fake_get)
        msgs, err = plugin._DiscordMsgForward__fetch_new_messages("100", "0")
        assert err is None
        assert len(msgs) == 130
        assert calls[1]["after"] == "100"          # 游标推进到第一页最后一条
        assert msgs[-1]["id"] == "130"

    def test_stops_at_page_cap(self, dmf, plugin, monkeypatch):
        def fake_get(path, params=None, _retry=0):
            after = int(params["after"])
            data = [_msg(after + i) for i in range(1, 101)]
            return type("R", (), {"status_code": 200, "json": lambda self, d=data: d})()

        monkeypatch.setattr(plugin, "_DiscordMsgForward__api_get", fake_get)
        msgs, err = plugin._DiscordMsgForward__fetch_new_messages("100", "0")
        assert err is None
        assert len(msgs) == 100 * dmf.MAX_PAGES_PER_POLL

    def test_error_returns_partial(self, plugin, monkeypatch):
        state = {"n": 0}

        def fake_get(path, params=None, _retry=0):
            state["n"] += 1
            if state["n"] == 1:
                data = [_msg(i) for i in range(1, 101)]
                return type("R", (), {"status_code": 200, "json": lambda self, d=data: d})()
            return type("R", (), {"status_code": 403, "text": "", "json": lambda self: {}})()

        monkeypatch.setattr(plugin, "_DiscordMsgForward__api_get", fake_get)
        msgs, err = plugin._DiscordMsgForward__fetch_new_messages("100", "0")
        assert len(msgs) == 100
        assert err is not None and err.status_code == 403


# ---------------- 聚合切批与截断 ----------------
class BatchTest:
    def test_aggregate_splits_by_cap(self, dmf, plugin):
        items = [_item(text=f"m{i}") for i in range(45)]
        batches = plugin._DiscordMsgForward__build_batches(_rule(aggregate=True), items)
        assert [len(b) for b in batches] == [dmf.MAX_AGGREGATE_ITEMS, dmf.MAX_AGGREGATE_ITEMS, 5]

    def test_no_aggregate_one_per_batch(self, plugin):
        items = [_item(text=f"m{i}") for i in range(3)]
        batches = plugin._DiscordMsgForward__build_batches(_rule(aggregate=False), items)
        assert [len(b) for b in batches] == [1, 1, 1]

    def test_long_content_truncated(self, dmf, plugin):
        long_items = [_item(text="x" * 5000)]
        plugin._DiscordMsgForward__send_batch(_rule(), "频道", long_items)
        text = plugin.sent[0]["text"]
        assert len(text) < 5000
        assert "已截断" in text


# ---------------- 发送失败重试队列 ----------------
class RetryQueueTest:
    def test_failed_send_enters_retry_queue(self, plugin):
        plugin.post_error = RuntimeError("渠道挂了")
        record = plugin._DiscordMsgForward__send_batch(_rule(), "频道", [_item()])
        assert record is None
        queue = plugin.get_data("retry_queue")
        assert len(queue) == 1 and queue[0]["attempts"] == 1

    def test_retry_succeeds_next_round(self, plugin):
        plugin._rules = [_rule()]
        plugin.post_error = RuntimeError("渠道挂了")
        plugin._DiscordMsgForward__send_batch(_rule(), "频道", [_item(text="重要消息")])
        plugin.post_error = None
        records = plugin._DiscordMsgForward__flush_retry()
        assert len(records) == 1
        assert plugin.get_data("retry_queue") == []
        assert "重要消息" in plugin.sent[0]["text"]

    def test_dropped_after_max_attempts(self, dmf, plugin):
        plugin._rules = [_rule()]
        plugin.post_error = RuntimeError("渠道一直挂")
        plugin._DiscordMsgForward__send_batch(_rule(), "频道", [_item()])
        for _ in range(dmf.MAX_SEND_ATTEMPTS):
            plugin._DiscordMsgForward__flush_retry()
        assert plugin.get_data("retry_queue") == []

    def test_partial_channel_failure_still_delivers(self, plugin, monkeypatch):
        calls = []

        def flaky(**kwargs):
            calls.append(kwargs.get("source"))
            if kwargs.get("source") == "坏渠道":
                raise RuntimeError("boom")
            plugin.sent.append(kwargs)

        monkeypatch.setattr(plugin, "post_message", flaky)
        record = plugin._DiscordMsgForward__send_batch(
            _rule(notify_channels=["坏渠道", "好渠道"]), "频道", [_item()])
        assert record is not None                     # 有渠道成功就算成功
        assert calls == ["坏渠道", "好渠道"]           # 坏渠道不影响后续渠道
        assert plugin.get_data("retry_queue") in (None, [])


# ---------------- 历史记录 ----------------
class HistoryTest:
    def test_expiry_uses_settings_tz(self, plugin, settings_stub):
        tz = pytz.timezone(settings_stub.TZ)
        now = datetime.now(tz)
        fresh = (now - timedelta(days=1)).strftime('%Y-%m-%d %H:%M:%S')
        stale = (now - timedelta(days=40)).strftime('%Y-%m-%d %H:%M:%S')
        plugin._DiscordMsgForward__save_history([
            {"date": stale, "content": "旧"}, {"date": fresh, "content": "新"},
        ])
        kept = [h["content"] for h in plugin.get_data("history")]
        assert kept == ["新"]

    def test_boundary_record_kept(self, plugin, settings_stub):
        """保留 30 天：29 天 23 小时前的记录必须保留（旧实现在容器时区≠TZ 时会误删）"""
        tz = pytz.timezone(settings_stub.TZ)
        edge = (datetime.now(tz) - timedelta(days=29, hours=23)).strftime('%Y-%m-%d %H:%M:%S')
        plugin._DiscordMsgForward__save_history([{"date": edge, "content": "边界"}])
        assert len(plugin.get_data("history")) == 1

    def test_size_cap(self, dmf, plugin, settings_stub):
        tz = pytz.timezone(settings_stub.TZ)
        now = datetime.now(tz).strftime('%Y-%m-%d %H:%M:%S')
        plugin._DiscordMsgForward__save_history(
            [{"date": now, "content": str(i)} for i in range(dmf.MAX_HISTORY_SIZE + 50)])
        history = plugin.get_data("history")
        assert len(history) == dmf.MAX_HISTORY_SIZE
        assert history[-1]["content"] == str(dmf.MAX_HISTORY_SIZE + 49)   # 保留最新

    def test_malformed_record_ignored(self, plugin):
        plugin._DiscordMsgForward__save_history([{"date": "不是时间", "content": "坏"}])
        assert plugin.get_data("history") == []


# ---------------- 队列上限 ----------------
class QueueCapTest:
    def test_cap_keeps_newest(self, dmf, plugin):
        queue = [{"i": i} for i in range(dmf.MAX_QUEUE_SIZE + 10)]
        capped = plugin._DiscordMsgForward__cap_queue(queue, "测试")
        assert len(capped) == dmf.MAX_QUEUE_SIZE
        assert capped[-1]["i"] == dmf.MAX_QUEUE_SIZE + 9


# ---------------- 并发保护 ----------------
class ConcurrencyTest:
    def test_reentrant_check_skipped(self, plugin, monkeypatch):
        calls = []
        monkeypatch.setattr(plugin, "_DiscordMsgForward__check_messages",
                            lambda: calls.append(1))
        plugin._check_lock.acquire()
        try:
            plugin.check_messages()
            assert calls == []          # 已有检查在跑，本次跳过
        finally:
            plugin._check_lock.release()
        plugin.check_messages()
        assert calls == [1]

    def test_lock_released_on_exception(self, plugin, monkeypatch):
        def boom():
            raise RuntimeError("炸了")

        monkeypatch.setattr(plugin, "_DiscordMsgForward__check_messages", boom)
        with pytest.raises(RuntimeError):
            plugin.check_messages()
        assert not plugin._check_lock.locked()

    def test_check_now_rejects_while_running(self, plugin):
        plugin._check_lock.acquire()
        try:
            assert "仍在进行中" in plugin.api_check_now()["message"]
        finally:
            plugin._check_lock.release()


# ---------------- 调度器复用 ----------------
class SchedulerTest:
    def test_reuses_single_scheduler(self, plugin):
        plugin._DiscordMsgForward__run_once(lambda: None, "任务1", delay=60)
        first = plugin._scheduler
        plugin._DiscordMsgForward__run_once(lambda: None, "任务2", delay=60)
        assert plugin._scheduler is first
        assert len(first.get_jobs()) == 2
        plugin.stop_service()
        assert plugin._scheduler is None


# ---------------- 通知渠道选项 ----------------
class NotifierOptionTest:
    def test_only_enabled_channels(self, plugin, notification_helper, notifier_config):
        notification_helper.configs = {
            "a": notifier_config("微信", enabled=True),
            "b": notifier_config("已停用的TG", enabled=False),
        }
        try:
            titles = [o["title"] for o in plugin.api_get_notifiers()["options"]]
            assert titles == ["微信"]
        finally:
            notification_helper.configs = {}


# ---------------- 配置容错 ----------------
class ConfigTest:
    def test_blank_numbers_fall_back(self, dmf):
        p = dmf.DiscordMsgForward()
        p.init_plugin({"token": "t", "interval": "", "history_days": None})
        p.stop_service()
        assert p._interval == 5 and p._history_days == 30

    def test_interval_floor(self, dmf):
        p = dmf.DiscordMsgForward()
        p.init_plugin({"token": "t", "interval": 0})
        p.stop_service()
        assert p._interval == 1

    def test_rules_get_ids(self, dmf):
        p = dmf.DiscordMsgForward()
        p.init_plugin({"token": "t", "rules": [{"name": "无ID规则"}]})
        p.stop_service()
        assert p._rules[0]["id"]
        assert p._rules[0]["enabled"] is True     # 默认字段被补齐

    def test_empty_config_resets_rules(self, dmf):
        p = dmf.DiscordMsgForward()
        p.init_plugin({"token": "t", "rules": [{"name": "A"}]})
        p.init_plugin(None)
        p.stop_service()
        assert p._rules == []


# ---------------- 消息内容提取 ----------------
class ExtractContentTest:
    def test_forwarded_message_snapshot(self, dmf):
        extract = dmf.DiscordMsgForward._DiscordMsgForward__extract_text
        msg = {"content": "", "message_snapshots": [
            {"message": {"content": "被转发的正文"}}]}
        assert "被转发的正文" in extract(msg)

    def test_poll_and_sticker(self, dmf):
        extract = dmf.DiscordMsgForward._DiscordMsgForward__extract_text
        msg = {
            "sticker_items": [{"name": "点赞"}],
            "poll": {"question": {"text": "选哪个"},
                     "answers": [{"poll_media": {"text": "A"}}, {"poll_media": {"text": "B"}}]},
        }
        out = extract(msg)
        assert "[贴纸] 点赞" in out and "[投票] 选哪个" in out and "A / B" in out

    def test_image_from_snapshot(self, dmf):
        extract = dmf.DiscordMsgForward._DiscordMsgForward__extract_image
        msg = {"message_snapshots": [{"message": {"attachments": [
            {"filename": "a.PNG", "url": "http://x/a.png"}]}}]}
        assert extract(msg) == "http://x/a.png"

    def test_non_image_attachment_goes_to_text(self, dmf):
        extract = dmf.DiscordMsgForward._DiscordMsgForward__extract_text
        msg = {"attachments": [{"filename": "a.zip", "url": "http://x/a.zip"}]}
        assert "[附件] http://x/a.zip" in extract(msg)


# ---------------- 429 限流 ----------------
class RateLimitTest:
    def test_retries_after_wait(self, dmf, plugin, monkeypatch):
        slept = []
        monkeypatch.setattr(dmf.time, "sleep", lambda s: slept.append(s))
        responses = [
            type("R", (), {"status_code": 429, "headers": {"Retry-After": "2"},
                           "json": lambda self: {}})(),
            type("R", (), {"status_code": 200, "headers": {},
                           "json": lambda self: []})(),
        ]

        class _FakeSession:
            def get(self, *a, **k):
                return responses.pop(0)

        monkeypatch.setattr(plugin, "_DiscordMsgForward__get_session", lambda: _FakeSession())
        resp = plugin._DiscordMsgForward__api_get("/x")
        assert resp.status_code == 200
        assert slept == [2.0]

    def test_retry_after_clamped(self, dmf):
        parse = dmf.DiscordMsgForward._DiscordMsgForward__parse_retry_after
        assert parse(type("R", (), {"headers": {"Retry-After": "999"},
                                    "json": lambda self: {}})()) == 30.0
        assert parse(type("R", (), {"headers": {}, "json": lambda self: {}})()) == 3.0


# ---------------- 内置礼包码正则示例 ----------------
class GiftCodePresetTest:
    """三段样本取自真实的 WOS 发码频道，__extract_text 会把 Embed 拼成这种形态"""

    WSCO_EMBED = (
        "🎁 NEW GIFT CODE AVAILABLE 🎁\n"
        "A new official Whiteout Survival gift code has been released!\n"
        "Redeem it now on the official redemption page.\n"
        "✨ Gift Code: summer26jp\n"
        "🔗 Redeem: Open redemption page\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "🤖 Aria 1.2 for your alliance Discord — auto-redeem all gift codes for your "
        "entire alliance, plus war boards, Foundry planner, events, tickets & roles in one bot.\n"
        "See plans & features → whiteoutsurvival-community.com/aria\n"
        "🎁 NEW GIFT CODE AVAILABLE 🎁"
    )
    WSCO_NEWLINE = ("🎁 NEW GIFT CODE AVAILABLE 🎁\n✨ Gift Code\nsummer26jp\n"
                    "🔗 Redeem\nOpen redemption page")
    PLAIN_CODE = ("📌 Code: 47ar5vzKz\n"
                  "⏰Valid Until: August 3, 23:59 (UTC+0)\n"
                  "🥳 Redemption page: https://wos-giftcode.centurygame.com/")
    BACKTICK_LIST = (
        "Gift Codes\n"
        "Active now · 7 Register ID · My Giftcodes — buttons below ━━━━━━━━━━━━━━━━ "
        "`summer26jp`  `WOS0812`  `100gomYTKOR`  `GuDokYTKOR`  `2ndYoutubeKR`  "
        "`1stYoutubeKR`  `gogoWOS` ━━━━━━━━━━━━━━━━  Updated 13 Aug 2026\n"
        "────────────────────────\n"
        "Made with ❤️ in Germany ＆ Poland\n"
        "© WSCO Community – discord.gg/wos-community · Developed by Bros24 · State 214"
    )

    @pytest.mark.parametrize("sample, expected", [
        ("WSCO_EMBED", ["summer26jp"]),
        ("WSCO_NEWLINE", ["summer26jp"]),
        ("PLAIN_CODE", ["47ar5vzKz"]),
        ("BACKTICK_LIST", ["summer26jp", "WOS0812", "100gomYTKOR", "GuDokYTKOR",
                           "2ndYoutubeKR", "1stYoutubeKR", "gogoWOS"]),
    ])
    def test_real_samples(self, dmf, sample, expected):
        extract = dmf.DiscordMsgForward._DiscordMsgForward__extract_codes
        assert extract(dmf.GIFTCODE_REGEX, getattr(self, sample)) == expected

    @pytest.mark.parametrize("text", [
        "🎁 NEW GIFT CODE AVAILABLE 🎁",           # 全大写英文，不是码
        "Code Redeem Now on the site",             # 标签后没有冒号/换行
        "Gift Code Expired yesterday",
        "Please read the Code of Conduct",
        "https://wos-giftcode.centurygame.com/",   # URL 里的 code
        "auto-redeem all gift codes for your entire alliance",
        "Gift Codes\nActive now · 7 Register ID",  # 复数标题后跟正文
        "Code: ab1",                               # 太短
        "Code: abcdefghij0123456789extra",         # 太长
    ])
    def test_no_false_positive(self, dmf, text):
        extract = dmf.DiscordMsgForward._DiscordMsgForward__extract_codes
        assert extract(dmf.GIFTCODE_REGEX, text) == []

    def test_code_followed_by_cjk(self, dmf):
        # 结尾用 (?![A-Za-z0-9]) 而不是 \b，中文紧跟在码后面也要能提取
        extract = dmf.DiscordMsgForward._DiscordMsgForward__extract_codes
        assert extract(dmf.GIFTCODE_REGEX, "Code: abc123兑换码") == ["abc123"]

    def test_all_presets_compile(self, dmf):
        import re
        assert dmf.REGEX_PRESETS
        for preset in dmf.REGEX_PRESETS:
            re.compile(preset["value"])
            assert preset["title"] and preset["desc"]

    def test_preset_api_returns_options(self, dmf):
        options = dmf.DiscordMsgForward.api_get_regex_presets()["options"]
        assert any(o["value"] == dmf.GIFTCODE_REGEX for o in options)


# ---------------- 投递去向 ----------------
class RuleLegsTest:
    def test_legs_resolution(self, dmf):
        legs = dmf.DiscordMsgForward._DiscordMsgForward__rule_legs
        assert legs(_rule()) == ["notify"]
        assert legs(_rule(forward_channels=["900"])) == ["notify", "discord"]
        assert legs(_rule(notify_enabled=False, forward_channels=["900"])) == ["discord"]
        assert legs(_rule(notify_enabled=False)) == []

    def test_legacy_rule_defaults_to_notify(self, dmf):
        # 4.2.0 及以前保存的规则没有 notify_enabled 字段，必须仍然走通知渠道
        legs = dmf.DiscordMsgForward._DiscordMsgForward__rule_legs
        assert legs({"channels": ["100"]}) == ["notify"]

    def test_rule_without_destination_drops_batch(self, plugin):
        record = plugin._DiscordMsgForward__send_batch(
            _rule(notify_enabled=False), "频道", [_item()])
        assert record is None
        assert plugin.sent == []
        assert plugin.get_data("retry_queue") in (None, [])


class ForwardTargetTest:
    def test_watched_target_dropped_without_bot_id(self, plugin):
        resolve = plugin._DiscordMsgForward__forward_targets
        rule = _rule(channels=["100"], forward_channels=["100", "900"])
        # 拿不到 Bot 自身 ID 时，指向被监听频道的目标必须放弃，否则会死循环刷屏
        assert resolve(rule, {"100"}, None) == ["900"]

    def test_watched_target_kept_with_bot_id(self, plugin):
        resolve = plugin._DiscordMsgForward__forward_targets
        rule = _rule(channels=["100"], forward_channels=["100", "900"])
        assert resolve(rule, {"100"}, "bot1") == ["100", "900"]


# ---------------- 频道 → 频道转发 ----------------
class DiscordForwardTest:
    def test_posts_to_target_channel(self, plugin, monkeypatch):
        posts = []

        def fake_post(path, payload, _retry=0):
            posts.append((path, payload))
            return _resp(200)

        monkeypatch.setattr(plugin, "_DiscordMsgForward__api_post", fake_post)
        record = plugin._DiscordMsgForward__send_batch(
            _rule(notify_enabled=False, forward_channels=["900"]),
            "频道", [_item(text="正文内容")], bot_id="bot1")
        assert record is not None
        assert posts[0][0] == "/channels/900/messages"
        assert "正文内容" in posts[0][1]["content"]
        assert plugin.sent == []                       # 没有走通知渠道

    def test_mentions_are_suppressed(self, plugin, monkeypatch):
        posts = []

        def fake_post(path, payload, _retry=0):
            posts.append(payload)
            return _resp(200)

        monkeypatch.setattr(plugin, "_DiscordMsgForward__api_post", fake_post)
        plugin._DiscordMsgForward__send_batch(
            _rule(notify_enabled=False, forward_channels=["900"]),
            "频道", [_item(text="@everyone 快来")], bot_id="bot1")
        assert posts[0]["allowed_mentions"] == {"parse": []}

    def test_content_truncated_to_discord_limit(self, dmf, plugin, monkeypatch):
        posts = []

        def fake_post(path, payload, _retry=0):
            posts.append(payload)
            return _resp(200)

        monkeypatch.setattr(plugin, "_DiscordMsgForward__api_post", fake_post)
        plugin._DiscordMsgForward__send_batch(
            _rule(notify_enabled=False, forward_channels=["900"], discord_template="{content}"),
            "频道", [_item(text="x" * 5000)], bot_id="bot1")
        assert len(posts[0]["content"]) <= dmf.MAX_DISCORD_LENGTH
        assert "已截断" in posts[0]["content"]

    def test_one_target_fails_others_still_delivered(self, plugin, monkeypatch):
        def fake_post(path, payload, _retry=0):
            return _resp(403) if "/901/" in path else _resp(200)

        monkeypatch.setattr(plugin, "_DiscordMsgForward__api_post", fake_post)
        record = plugin._DiscordMsgForward__send_batch(
            _rule(notify_enabled=False, forward_channels=["901", "900"]),
            "频道", [_item()], bot_id="bot1")
        assert record is not None                       # 有一个成功就算送达
        assert plugin.get_data("retry_queue") in (None, [])

    def test_all_targets_fail_enters_retry(self, plugin, monkeypatch):
        monkeypatch.setattr(plugin, "_DiscordMsgForward__api_post",
                            lambda path, payload, _retry=0: _resp(403))
        record = plugin._DiscordMsgForward__send_batch(
            _rule(notify_enabled=False, forward_channels=["900"]),
            "频道", [_item()], bot_id="bot1")
        assert record is None
        assert plugin.get_data("retry_queue")[0]["legs"] == ["discord"]

    def test_only_failed_leg_is_retried(self, plugin, monkeypatch):
        """通知成功、Discord 失败时，重投只补发 Discord，通知不能重复推送"""
        plugin._rules = [_rule(forward_channels=["900"])]
        monkeypatch.setattr(plugin, "_DiscordMsgForward__api_post",
                            lambda path, payload, _retry=0: _resp(403))
        record = plugin._DiscordMsgForward__send_batch(
            _rule(forward_channels=["900"]), "频道", [_item()], bot_id="bot1")
        assert record is not None and len(plugin.sent) == 1
        assert plugin.get_data("retry_queue")[0]["legs"] == ["discord"]

        posts = []

        def ok_post(path, payload, _retry=0):
            posts.append(path)
            return _resp(200)

        monkeypatch.setattr(plugin, "_DiscordMsgForward__api_post", ok_post)
        plugin._DiscordMsgForward__flush_retry(set(), "bot1")
        assert len(plugin.sent) == 1                     # 通知没有被重复发送
        assert posts == ["/channels/900/messages"]
        assert plugin.get_data("retry_queue") == []

    def test_post_5xx_not_auto_retried(self, plugin, monkeypatch):
        """写接口 5xx 不能自动重试，否则可能重复发帖；只有 429 才重试"""
        calls = []

        class _FakeSession:
            def post(self, *a, **k):
                calls.append(1)
                return type("R", (), {"status_code": 500, "text": "",
                                      "headers": {}, "json": lambda self: {}})()

        monkeypatch.setattr(plugin, "_DiscordMsgForward__get_session", lambda: _FakeSession())
        resp = plugin._DiscordMsgForward__api_post("/channels/900/messages", {"content": "x"})
        assert resp.status_code == 500
        assert len(calls) == 1


# ---------------- 自消息过滤（防死循环） ----------------
class SelfMessageTest:
    def test_own_message_not_forwarded(self, plugin, monkeypatch):
        plugin._rules = [_rule(notify_enabled=False, forward_channels=["900"])]
        plugin.save_data("last_ids", {"100": "0"})
        plugin.save_data("bot_user_id", "bot1")
        msgs = [_msg(1, "别人发的", uid="u1"), _msg(2, "上一轮转发的", uid="bot1")]

        def fake_get(path, params=None, _retry=0):
            if path.endswith("/messages"):
                return _resp(200, msgs if (params or {}).get("after") == "0" else [])
            return _resp(200, {})

        posts = []

        def fake_post(path, payload, _retry=0):
            posts.append(payload)
            return _resp(200)

        monkeypatch.setattr(plugin, "_DiscordMsgForward__api_get", fake_get)
        monkeypatch.setattr(plugin, "_DiscordMsgForward__api_post", fake_post)
        plugin.check_messages()

        assert len(posts) == 1
        assert "别人发的" in posts[0]["content"]
        assert "上一轮转发的" not in posts[0]["content"]

    def test_bot_id_cached_from_api(self, plugin, monkeypatch):
        calls = []

        def fake_get(path, params=None, _retry=0):
            calls.append(path)
            return _resp(200, {"id": "bot-123"})

        monkeypatch.setattr(plugin, "_DiscordMsgForward__api_get", fake_get)
        assert plugin._DiscordMsgForward__get_bot_user_id() == "bot-123"
        assert plugin._DiscordMsgForward__get_bot_user_id() == "bot-123"
        assert calls == ["/users/@me"]                   # 第二次走缓存

    def test_bot_id_failure_returns_none(self, plugin, monkeypatch):
        monkeypatch.setattr(plugin, "_DiscordMsgForward__api_get",
                            lambda path, params=None, _retry=0: _resp(401))
        assert plugin._DiscordMsgForward__get_bot_user_id() is None


# ---------------- 模板 {link} 与详情页入口 ----------------
class LinkTemplateTest:
    def test_link_line_removed_when_empty(self, dmf):
        render = dmf.DiscordMsgForward._DiscordMsgForward__render_template
        out = render("{content}\n🔗 {link}", {"content": "正文", "link": ""})
        assert "🔗" not in out and "正文" in out

    def test_link_rendered_when_present(self, dmf):
        render = dmf.DiscordMsgForward._DiscordMsgForward__render_template
        out = render("{content}\n🔗 {link}",
                     {"content": "正文", "link": "https://discord.com/channels/1/2/3"})
        assert "https://discord.com/channels/1/2/3" in out

    def test_status_exposes_docs_url(self, dmf, plugin):
        status = plugin.api_get_status()
        assert status["docs_url"] == dmf.DOCS_URL
        assert "forward_rules" in status


# ---------------- 跳转链接开关 ----------------
class JumpLinkTest:
    def test_link_passed_by_default(self, plugin):
        item = {**_item(), "link": "https://discord.com/channels/1/2/3"}
        plugin._DiscordMsgForward__send_batch(_rule(), "频道", [item])
        assert plugin.sent[0]["link"] == "https://discord.com/channels/1/2/3"

    def test_link_suppressed_when_off(self, plugin):
        """关掉后不给 post_message 传 link，通知渠道就不会追加「点击查看：…」"""
        item = {**_item(), "link": "https://discord.com/channels/1/2/3"}
        plugin._DiscordMsgForward__send_batch(_rule(jump_link=False), "频道", [item])
        assert plugin.sent[0]["link"] is None

    def test_legacy_rule_keeps_link(self, plugin):
        # 4.3.0 及以前保存的规则没有 jump_link 字段，行为必须不变
        rule = _rule()
        rule.pop("jump_link", None)
        item = {**_item(), "link": "https://discord.com/channels/1/2/3"}
        plugin._DiscordMsgForward__send_batch(rule, "频道", [item])
        assert plugin.sent[0]["link"] == "https://discord.com/channels/1/2/3"

    def test_template_link_var_independent(self, plugin):
        """开关只管「点击查看」，模板里显式写的 {link} 不受影响"""
        item = {**_item(), "link": "https://discord.com/channels/1/2/3"}
        plugin._DiscordMsgForward__send_batch(
            _rule(jump_link=False, text_template="{content}\n{link}"), "频道", [item])
        assert plugin.sent[0]["link"] is None
        assert "https://discord.com/channels/1/2/3" in plugin.sent[0]["text"]


# ---------------- 重复转发检测 ----------------
class DedupTest:
    def test_off_by_default(self, plugin):
        items = [_item(text="一样的内容"), _item(text="一样的内容")]
        assert plugin._DiscordMsgForward__filter_duplicates(_rule(), items) == items

    def test_same_text_skipped(self, plugin):
        f = plugin._DiscordMsgForward__filter_duplicates
        rule = _rule(dedup=True)
        assert len(f(rule, [_item(text="礼包码 ABC")])) == 1
        assert f(rule, [_item(text="礼包码 ABC")]) == []          # 第二轮重复
        assert len(f(rule, [_item(text="礼包码 XYZ")])) == 1      # 不同内容照发

    def test_same_batch_internal_dedup(self, plugin):
        f = plugin._DiscordMsgForward__filter_duplicates
        kept = f(_rule(dedup=True), [_item(text="A"), _item(text="A"), _item(text="B")])
        assert [i["text"] for i in kept] == ["A", "B"]

    def test_codes_take_priority_over_text(self, plugin):
        """同一个码换个说法重发，也应算重复"""
        f = plugin._DiscordMsgForward__filter_duplicates
        rule = _rule(dedup=True)
        assert len(f(rule, [_item(text="Gift Code: abc123", codes=["abc123"])])) == 1
        assert f(rule, [_item(text="今日新码 abc123 快领", codes=["abc123"])]) == []

    def test_different_codes_not_deduped(self, plugin):
        f = plugin._DiscordMsgForward__filter_duplicates
        rule = _rule(dedup=True)
        assert len(f(rule, [_item(text="x", codes=["aaa"])])) == 1
        assert len(f(rule, [_item(text="x", codes=["bbb"])])) == 1

    def test_rules_are_independent(self, plugin):
        f = plugin._DiscordMsgForward__filter_duplicates
        assert len(f(_rule(id="r1", dedup=True), [_item(text="同样内容")])) == 1
        assert len(f(_rule(id="r2", dedup=True), [_item(text="同样内容")])) == 1

    def test_expired_fingerprint_allows_resend(self, dmf, plugin):
        f = plugin._DiscordMsgForward__filter_duplicates
        rule = _rule(dedup=True)
        assert len(f(rule, [_item(text="老消息")])) == 1
        # 把指纹时间戳推到 TTL 之外
        store = plugin.get_data("dedup_seen")
        old = datetime.now(tz=pytz.timezone("Asia/Shanghai")) - timedelta(days=dmf.DEDUP_TTL_DAYS + 1)
        for e in store["r1"]:
            e["t"] = old.timestamp()
        plugin.save_data("dedup_seen", store)
        assert len(f(rule, [_item(text="老消息")])) == 1

    def test_fingerprint_store_capped(self, dmf, plugin):
        f = plugin._DiscordMsgForward__filter_duplicates
        rule = _rule(dedup=True)
        f(rule, [_item(text=f"msg{i}") for i in range(dmf.DEDUP_MAX_PER_RULE + 50)])
        assert len(plugin.get_data("dedup_seen")["r1"]) == dmf.DEDUP_MAX_PER_RULE

    def test_deleted_rule_pruned(self, dmf, plugin):
        plugin._DiscordMsgForward__filter_duplicates(_rule(id="gone", dedup=True), [_item()])
        assert "gone" in plugin.get_data("dedup_seen")
        plugin._rules = [_rule(id="r1")]
        plugin._DiscordMsgForward__prune_dedup()
        assert "gone" not in plugin.get_data("dedup_seen")

    def test_duplicate_not_stored_in_pending(self, plugin, monkeypatch):
        """重复检测在免打扰之前，重复内容连暂存都不该进"""
        plugin._rules = [_rule(dedup=True, quiet_hours="00:00-23:59")]
        plugin.save_data("last_ids", {"100": "0"})
        msgs = [_msg(1, "重复内容"), _msg(2, "重复内容")]

        def fake_get(path, params=None, _retry=0):
            if path.endswith("/messages"):
                return _resp(200, msgs if (params or {}).get("after") == "0" else [])
            return _resp(200, {})

        monkeypatch.setattr(plugin, "_DiscordMsgForward__api_get", fake_get)
        plugin.check_messages()
        pending = plugin.get_data("pending") or []
        assert len(pending) == 1
