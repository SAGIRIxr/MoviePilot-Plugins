"""
TTG（totheglory.im）

TTG 是自成一派的老站：没有 usercp.php，邀请名额写在每页顶栏的
「[ 邀请： N ]」里，邀请页是 invite.php。另外它不发 charset 头，
requests 会把整页当 ISO-8859-1 解出乱码——编码在 sitehttp 里统一纠正了。
"""
import re
from typing import Any, Dict, List

import requests
from bs4 import BeautifulSoup

from app.log import logger

from . import _ISiteHandler
from ..sitehttp import SiteAccessError, classify, get

KNOWN_DOMAINS = ("totheglory.im",)


class TtgHandler(_ISiteHandler):
    """TTG 邀请系统处理器。"""

    site_schema = "ttg"

    @classmethod
    def match(cls, site_url: str) -> bool:
        low = (site_url or "").lower()
        return any(domain in low for domain in KNOWN_DOMAINS)

    @staticmethod
    def _invite_count(text: str) -> int:
        """顶栏写成「[ 邀请： 0 ]」，冒号可能是全角也可能是半角。"""
        m = re.search(r"邀请\s*[:：]\s*(\d+)", text)
        if m:
            return int(m.group(1))
        m = re.search(r"invites?\s*[:：]\s*(\d+)", text, re.I)
        return int(m.group(1)) if m else 0

    @staticmethod
    def _parse_invitees(soup: BeautifulSoup) -> List[Dict[str, Any]]:
        """
        找带用户名和分享率的那张表。TTG 邀请页在没有名额时只有一句提示，
        有后宫时才会渲染表格，所以找不到表不算失败。
        """
        invitees = []
        for table in soup.select("table"):
            rows = table.select("tr")
            if len(rows) < 2:
                continue
            headers = [c.get_text(strip=True) for c in rows[0].select("td, th")]
            joined = " ".join(headers)
            if not re.search(r"用户名|Username", joined, re.I):
                continue

            def col(*names):
                for idx, header in enumerate(headers):
                    if any(n.lower() in header.lower() for n in names):
                        return idx
                return None

            i_user = col("用户名", "username")
            i_email = col("邮箱", "email")
            i_up = col("上传量", "上传", "uploaded")
            i_down = col("下载量", "下载", "downloaded")
            i_ratio = col("分享率", "ratio")
            i_status = col("状态", "status")

            for row in rows[1:]:
                texts = [c.get_text(strip=True) for c in row.select("td")]
                if len(texts) < 2:
                    continue

                def cell(idx):
                    return texts[idx] if idx is not None and idx < len(texts) else ""

                username = cell(i_user)
                if not username:
                    continue
                status_text = cell(i_status)
                banned = bool(re.search(r"禁用|banned|disabled", status_text, re.I)) or \
                    bool(row.select_one("s, strike, del"))

                invitees.append({
                    "username": username,
                    "email": cell(i_email),
                    "uploaded": cell(i_up),
                    "downloaded": cell(i_down),
                    "ratio": cell(i_ratio),
                    "enabled": "No" if banned else "Yes",
                    "status": "已禁用" if banned else (status_text or "已确认"),
                })
            if invitees:
                break
        return invitees

    def parse_invite_page(self, site_info: Dict[str, Any], session: requests.Session) -> Dict[str, Any]:
        site_name = site_info.get("name", "")
        site_url = site_info.get("url", "")

        result = {
            "invite_status": {
                "can_invite": False,
                "reason": "",
                "permanent_count": 0,
                "temporary_count": 0,
                "bonus": 0,
                "permanent_invite_price": 0,
                "temporary_invite_price": 0,
            },
            "invitees": [],
        }

        try:
            invite_page = get(session, site_url, "invite.php")
        except SiteAccessError as e:
            result["invite_status"]["reason"] = e.reason
            return result

        reason = classify(invite_page)
        if reason:
            result["invite_status"]["reason"] = reason
            return result

        soup = BeautifulSoup(invite_page.text, "html.parser")
        page_text = re.sub(r"\s+", " ", soup.get_text(" "))

        # TTG 每页顶栏都带「欢迎回来，用户名」，没有就是没登录
        if "欢迎回来" not in page_text and "Welcome back" not in page_text:
            result["invite_status"]["reason"] = "Cookie 已失效，请重新登录站点更新 Cookie"
            return result

        permanent = self._invite_count(page_text)
        invitees = self._parse_invitees(soup)

        result["invite_status"]["permanent_count"] = permanent
        result["invitees"] = invitees

        if re.search(r"没有邀请名额|对不起", page_text):
            result["invite_status"]["reason"] = "当前没有邀请名额"
        elif permanent > 0:
            result["invite_status"]["can_invite"] = True
            result["invite_status"]["reason"] = f"可用邀请数: 永久={permanent}"
        else:
            result["invite_status"]["reason"] = "当前没有可用邀请名额"

        logger.info(f"站点 {site_name} TTG 解析完成: 邀请 {permanent} 个, 后宫 {len(invitees)} 人")
        return result
