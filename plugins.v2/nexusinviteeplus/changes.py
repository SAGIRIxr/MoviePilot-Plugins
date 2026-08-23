"""
变化追踪

原版每轮刷新直接覆盖旧数据，于是「谁昨天还在、今天被 ban 了」「谁的分享率一路在掉」
全都看不到——而这恰恰是后宫管理最该盯的事：下家出问题会连累邀请人。

不额外存快照：site_data.json 里存的本来就是上一轮的结果，写新数据之前先和它比一次，
把差异记成事件追加到 changes.json。
"""
import json
import os
import time
from typing import Any, Dict, List, Optional

from app.log import logger

# 变化记录保留多久 / 最多留多少条
KEEP_DAYS = 30
KEEP_MAX = 1000

# 事件类型
JOINED = "joined"
LEFT = "left"
BANNED = "banned"
UNBANNED = "unbanned"
RATIO_DROP = "ratio_drop"
QUOTA = "quota"
INVITE_OPEN = "invite_open"
INVITE_CLOSE = "invite_close"

# 展示用的中文名和图标
LABELS = {
    JOINED: ("新增成员", "🆕"),
    LEFT: ("成员消失", "👻"),
    BANNED: ("被禁用", "🚫"),
    UNBANNED: ("解除禁用", "✅"),
    RATIO_DROP: ("分享率告警", "⚠️"),
    QUOTA: ("邀请名额变动", "🎟️"),
    INVITE_OPEN: ("开放邀请", "🔓"),
    INVITE_CLOSE: ("关闭邀请", "🔒"),
}

# 健康度从好到坏，用来判断是不是「跌档」
_HEALTH_RANK = {"excellent": 4, "good": 3, "neutral": 2, "warning": 1, "danger": 0}


def _rank(health: Optional[str]) -> int:
    return _HEALTH_RANK.get(health or "", 2)


def _index_by_name(invitees: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """按用户名建索引。同名的以后出现的为准，实际站点里用户名是唯一的。"""
    result = {}
    for invitee in invitees or []:
        name = str(invitee.get("username") or "").strip()
        if name:
            result[name] = invitee
    return result


def diff_site(site_name: str, old_data: Optional[Dict[str, Any]],
              new_data: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    比对一个站点前后两轮的数据，返回变化事件列表。

    old_data 为 None 表示这个站点是头一回抓到——那就只建基线，不产生任何事件，
    否则第一次运行会一口气报出几百条「新增成员」。
    """
    if old_data is None:
        return []

    events: List[Dict[str, Any]] = []
    now = int(time.time())

    def add(kind: str, detail: str, username: str = ""):
        events.append({
            "ts": now,
            "site": site_name,
            "kind": kind,
            "username": username,
            "detail": detail,
        })

    old_members = _index_by_name(old_data.get("invitees"))
    new_members = _index_by_name(new_data.get("invitees"))

    for name, member in new_members.items():
        previous = old_members.get(name)
        if previous is None:
            add(JOINED, f"{name} 加入", name)
            continue

        was_banned = str(previous.get("enabled", "")).lower() == "no"
        is_banned = str(member.get("enabled", "")).lower() == "no"
        if is_banned and not was_banned:
            add(BANNED, f"{name} 被禁用", name)
        elif was_banned and not is_banned:
            add(UNBANNED, f"{name} 解除禁用", name)

        # 只报跌档，涨回去不吵人
        old_rank, new_rank = _rank(previous.get("ratio_health")), _rank(member.get("ratio_health"))
        if new_rank < old_rank and new_rank <= _HEALTH_RANK["warning"]:
            add(RATIO_DROP,
                f"{name} 分享率 {previous.get('ratio', '?')} → {member.get('ratio', '?')}",
                name)

    for name in old_members:
        if name not in new_members:
            add(LEFT, f"{name} 已不在列表中", name)

    old_status = old_data.get("invite_status") or {}
    new_status = new_data.get("invite_status") or {}

    old_quota = (old_status.get("permanent_count", 0), old_status.get("temporary_count", 0))
    new_quota = (new_status.get("permanent_count", 0), new_status.get("temporary_count", 0))
    if old_quota != new_quota:
        add(QUOTA, f"邀请名额 永久 {old_quota[0]}→{new_quota[0]}，临时 {old_quota[1]}→{new_quota[1]}")

    if bool(old_status.get("can_invite")) != bool(new_status.get("can_invite")):
        if new_status.get("can_invite"):
            add(INVITE_OPEN, f"变为可邀请（{new_status.get('reason', '')}）")
        else:
            add(INVITE_CLOSE, f"变为不可邀请（{new_status.get('reason', '')}）")

    return events


class ChangeStore:
    """变化事件的读写。就是一个按时间排的 JSON 列表，够用了。"""

    def __init__(self, data_path: str):
        self.file = os.path.join(data_path, "changes.json")

    def load(self) -> List[Dict[str, Any]]:
        if not os.path.exists(self.file):
            return []
        try:
            with open(self.file, "r", encoding="utf-8") as handle:
                data = json.load(handle)
            return data if isinstance(data, list) else []
        except Exception as e:
            logger.error(f"读取变化记录失败: {str(e)}")
            return []

    def append(self, events: List[Dict[str, Any]]) -> None:
        if not events:
            return
        records = self.load() + list(events)

        cutoff = int(time.time()) - KEEP_DAYS * 86400
        records = [r for r in records if r.get("ts", 0) >= cutoff]
        records.sort(key=lambda r: r.get("ts", 0))
        if len(records) > KEEP_MAX:
            records = records[-KEEP_MAX:]

        try:
            os.makedirs(os.path.dirname(self.file), exist_ok=True)
            with open(self.file, "w", encoding="utf-8") as handle:
                json.dump(records, handle, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"保存变化记录失败: {str(e)}")

    def recent(self, limit: int = 200) -> List[Dict[str, Any]]:
        """最近的变化，新的排前面。"""
        return list(reversed(self.load()))[:limit]


def summarize(events: List[Dict[str, Any]]) -> str:
    """把一轮的变化拼成通知正文；没有变化返回空串。"""
    if not events:
        return ""

    grouped: Dict[str, List[Dict[str, Any]]] = {}
    for event in events:
        grouped.setdefault(event.get("kind", ""), []).append(event)

    # 重要的排前面
    order = [BANNED, RATIO_DROP, LEFT, INVITE_OPEN, QUOTA, JOINED, UNBANNED, INVITE_CLOSE]
    lines = []
    for kind in order:
        items = grouped.get(kind)
        if not items:
            continue
        label, icon = LABELS.get(kind, (kind, "•"))
        lines.append(f"{icon} {label}（{len(items)}）")
        # 每类最多列 8 条，再多就只给个数字，免得通知长得没法看
        for item in items[:8]:
            lines.append(f"  [{item.get('site', '')}] {item.get('detail', '')}")
        if len(items) > 8:
            lines.append(f"  …另有 {len(items) - 8} 条")
        lines.append("")

    return "\n".join(lines).strip()
