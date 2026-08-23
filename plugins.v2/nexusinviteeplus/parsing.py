"""
后宫成员数据清洗

各站点的表格列顺序五花八门，handler 按列猜字段难免猜偏：日志里那些
「分享率转换失败: 分享率」是整行表头被当成了成员，「分享率转换失败:
7.529 TB (2.791 TB)」是上传量落进了分享率列。与其去改每个 handler 的列映射，
不如在数据出 handler 之后统一过一遍。
"""
import re
from typing import Any, Dict, List, Optional, Tuple

from app.log import logger

# 表头行被当成成员时，用户名会是这些词
HEADER_WORDS = {
    "用户名", "用户", "邮箱", "邮件", "分享率", "上传", "下载", "上传量", "下载量",
    "状态", "加入时间", "最近登录", "最后活动", "做种数", "上传数", "操作", "备注",
    "username", "user", "email", "ratio", "uploaded", "downloaded", "upload",
    "download", "status", "joined", "last seen", "action",
}

_SIZE_RE = re.compile(r"([\d.,]+)\s*([KMGTPE]?i?B)\b", re.I)
_INF_WORDS = {"∞", "inf", "inf.", "infinite", "无限", "无限大"}

_UNITS = {"B": 1, "KB": 1024, "MB": 1024 ** 2, "GB": 1024 ** 3, "TB": 1024 ** 4,
          "PB": 1024 ** 5, "EB": 1024 ** 6}


def to_bytes(text: str) -> Optional[float]:
    """把 "1.5 TB" 这种转成字节数；转不了返回 None。"""
    if not text:
        return None
    m = _SIZE_RE.search(str(text))
    if not m:
        return None
    num, unit = m.group(1).replace(",", ""), m.group(2).upper().replace("I", "")
    try:
        return float(num) * _UNITS.get(unit, 1)
    except ValueError:
        return None


def looks_like_size(text: str) -> bool:
    """带存储单位的文本不可能是分享率。"""
    return bool(_SIZE_RE.search(str(text or "")))


def parse_ratio(text: str) -> Optional[float]:
    """
    把分享率文本转成数字。返回 None 表示这压根不是分享率
    （表头文字、带单位的流量、空值都归到这里）。
    """
    if text is None:
        return None
    raw = str(text).strip()
    if not raw or raw in HEADER_WORDS:
        return None
    if raw.lower() in _INF_WORDS:
        return float("inf")
    if looks_like_size(raw):
        return None
    # 千分位逗号去掉，欧洲写法的小数逗号换成点
    normalized = re.sub(r"(?<=\d),(?=\d{3}\b)", "", raw)
    normalized = normalized.replace(",", ".")
    m = re.search(r"-?\d+(?:\.\d+)?", normalized)
    if not m:
        return None
    try:
        return float(m.group(0))
    except ValueError:
        return None


def is_header_row(invitee: Dict[str, Any]) -> bool:
    """判断这条「成员」其实是被误抓的表头行。"""
    name = str(invitee.get("username") or "").strip()
    if not name:
        return True
    if name.lower() in HEADER_WORDS or name in HEADER_WORDS:
        return True
    # 用户名和分享率两列都是表头词，基本可以确诊
    ratio = str(invitee.get("ratio") or "").strip()
    return ratio in HEADER_WORDS and name in HEADER_WORDS


def health_from_ratio(ratio: Optional[float]) -> Tuple[str, List[str]]:
    """分享率数值 -> (健康度, [标签, 颜色class])，和上游 UI 的取值保持一致。"""
    if ratio is None:
        return "neutral", ["无数据", "text-grey"]
    if ratio == float("inf"):
        return "excellent", ["分享率无限", "text-success"]
    if ratio >= 4.0:
        return "excellent", ["极好", "text-success"]
    if ratio >= 2.0:
        return "good", ["良好", "text-success"]
    if ratio >= 1.0:
        return "good", ["正常", "text-success"]
    if ratio > 0:
        return ("warning", ["较低", "text-warning"]) if ratio >= 0.4 else ("danger", ["危险", "text-error"])
    return "neutral", ["无数据", "text-grey"]


def sanitize_invitees(site_name: str, invitees: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    统一清洗一个站点的成员列表：
      - 丢掉被误抓成成员的表头行
      - 分享率列拿到的不是分享率时，回头用上传/下载自己算
      - 补齐 ratio_health / ratio_label，让统计和总览不再各算各的
    """
    cleaned: List[Dict[str, Any]] = []
    dropped = 0

    for invitee in invitees or []:
        if not isinstance(invitee, dict):
            continue
        if is_header_row(invitee):
            dropped += 1
            continue

        ratio_text = invitee.get("ratio")
        ratio_value = parse_ratio(ratio_text)

        if ratio_value is None:
            # 分享率列是脏的，用上传下载兜底
            up = to_bytes(invitee.get("uploaded"))
            down = to_bytes(invitee.get("downloaded"))
            if up is not None and down is not None:
                if down > 0:
                    ratio_value = up / down
                    invitee["ratio"] = f"{ratio_value:.3f}"
                elif up > 0:
                    ratio_value = float("inf")
                    invitee["ratio"] = "∞"
                else:
                    invitee["ratio"] = ""
            elif ratio_text and looks_like_size(ratio_text):
                # 列串位了又算不出来，至少别把流量当分享率留在页面上
                logger.debug(f"站点 {site_name} 成员 {invitee.get('username')} 的分享率列是流量值，已清空")
                invitee["ratio"] = ""

        health, label = health_from_ratio(ratio_value)
        invitee["ratio_health"] = health
        invitee["ratio_label"] = label
        invitee["ratio_value"] = None if ratio_value in (None, float("inf")) else round(ratio_value, 3)
        cleaned.append(invitee)

    if dropped:
        logger.debug(f"站点 {site_name} 清洗掉 {dropped} 行表头误抓的「成员」")
    return cleaned


# 站点提示里常跟着的「点击这里返回」之类的尾巴，对用户没有任何信息量
_TAIL_RE = re.compile(
    r"\s*[（(]?\s*(?:点击|點擊)?\s*(?:这里|這裏|這裡|here)\s*(?:返回|back)\s*[。.！!]?\s*[）)]?\s*$",
    re.IGNORECASE)


def tidy_reason(reason: Optional[str]) -> str:
    """
    收拾邀请状态的原因文案。

    handler 是直接从页面文本里抠这句话的，末尾常粘着「這裏返回。」这种
    跳转提示（蝶粉就是这样）。这里统一擦掉，顺便压平空白。
    """
    text = re.sub(r"\s+", " ", (reason or "")).strip()
    if not text:
        return text
    # 「這裏返回」可能重复出现，多擦几遍
    for _ in range(3):
        cleaned = _TAIL_RE.sub("", text)
        if cleaned == text:
            break
        text = cleaned
    # 顺手扫掉被截断的颜文字残渣（「:( 点击这里返回」擦完会剩个孤零零的冒号）
    return text.strip(" ；;，,:：(（")
