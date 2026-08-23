"""
Gazelle 体系站点（海豹 GreatPosterWall、Orpheus 这一挂）

Gazelle 虽然也是 .php，但没有 usercp.php，邀请页在 user.php?action=invite。
上游插件拿 NexusPHP 处理器去啃，usercp.php 返回的是「页面不存在」而不是 404，
所以连报错都报不准，只会说无法获取用户ID。
"""
import re
from typing import Any, Dict, List, Optional

import requests
from bs4 import BeautifulSoup

from app.log import logger

from . import _ISiteHandler
from ..sitehttp import SiteAccessError, classify, get

KNOWN_DOMAINS = (
    "greatposterwall.com", "dicmusic.com", "orpheus.network",
    "redacted.ch", "redacted.sh", "notwhat.cd",
)


class GazelleHandler(_ISiteHandler):
    """Gazelle 站点邀请系统处理器。"""

    site_schema = "gazelle"

    @classmethod
    def match(cls, site_url: str) -> bool:
        low = (site_url or "").lower()
        return any(domain in low for domain in KNOWN_DOMAINS)

    @staticmethod
    def _find_user_id(html: str) -> Optional[str]:
        """Gazelle 的自己人链接是 user.php?id=xxx，导航栏里就有。"""
        m = re.search(r"user\.php\?id=(\d+)", html)
        return m.group(1) if m else None

    @staticmethod
    def _invite_count(text: str) -> int:
        """个人页上写成「邀请: N [ 详情 ]」。"""
        for pattern in (r"邀请\s*[:：]\s*([\d,]+)",
                        r"Invites?\s*[:：]\s*([\d,]+)",
                        r"你有\s*([\d,]+)\s*个邀请"):
            m = re.search(pattern, text, re.I)
            if m:
                try:
                    return int(m.group(1).replace(",", ""))
                except ValueError:
                    continue
        return 0

    @staticmethod
    def _parse_invitee_table(soup: BeautifulSoup) -> List[Dict[str, Any]]:
        """
        邀请页那张「我邀请的人」表，列是
        用户名 / 邮箱 / 加入时间 / 最近登录 / 上传数 / 上传 / 下载 / 分享率。
        """
        invitees = []
        for table in soup.select("table"):
            rows = table.select("tr")
            if not rows:
                continue
            headers = [c.get_text(strip=True) for c in rows[0].select("td, th")]
            joined = " ".join(headers)
            if not re.search(r"用户名|Username", joined, re.I) or \
               not re.search(r"分享率|Ratio", joined, re.I):
                continue

            def col(*names):
                for idx, header in enumerate(headers):
                    if any(n.lower() in header.lower() for n in names):
                        return idx
                return None

            i_user = col("用户名", "username")
            i_email = col("邮箱", "email")
            i_joined = col("加入时间", "joined")
            i_seen = col("最近登录", "last seen")
            i_up = col("上传", "uploaded")
            i_down = col("下载", "downloaded")
            i_ratio = col("分享率", "ratio")
            # 「上传数」（种子数）和「上传」（流量）都含「上传」，取靠后的那个才是流量
            i_count = col("上传数")
            if i_count is not None and i_up == i_count:
                for idx in range(len(headers) - 1, -1, -1):
                    if "上传" in headers[idx] and idx != i_count:
                        i_up = idx
                        break

            for row in rows[1:]:
                cells = row.select("td")
                if len(cells) < 3:
                    continue
                texts = [c.get_text(strip=True) for c in cells]

                def cell(idx):
                    return texts[idx] if idx is not None and idx < len(texts) else ""

                raw_name = cell(i_user)
                if not raw_name:
                    continue
                # 「hyiming(Power User)」里括号内是用户组，拆出来单独放
                m = re.match(r"^(.*?)\s*[（(]([^）)]*)[）)]\s*$", raw_name)
                username, user_class = (m.group(1), m.group(2)) if m else (raw_name, "")

                row_html = str(row).lower()
                banned = bool(re.search(r"class=\"[^\"]*(disabled|banned)", row_html)) or \
                    bool(row.select_one("s, strike, del"))

                invitees.append({
                    "username": username,
                    "email": cell(i_email),
                    "uploaded": cell(i_up),
                    "downloaded": cell(i_down),
                    "ratio": cell(i_ratio),
                    "enabled": "No" if banned else "Yes",
                    "status": "已禁用" if banned else "已确认",
                    "joined": cell(i_joined),
                    "last_seen": cell(i_seen),
                    "user_class": user_class,
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
            home = get(session, site_url, "/")
        except SiteAccessError as e:
            result["invite_status"]["reason"] = e.reason
            return result

        reason = classify(home)
        if reason:
            result["invite_status"]["reason"] = reason
            return result

        user_id = self._find_user_id(home.text)
        if not user_id:
            result["invite_status"]["reason"] = "页面里找不到当前登录用户，Cookie 可能已失效"
            return result
        logger.info(f"站点 {site_name} 识别为 Gazelle，用户ID: {user_id}")

        try:
            invite_page = get(session, site_url, "user.php?action=invite")
        except SiteAccessError as e:
            result["invite_status"]["reason"] = e.reason
            return result

        reason = classify(invite_page)
        if reason:
            result["invite_status"]["reason"] = reason
            return result

        soup = BeautifulSoup(invite_page.text, "html.parser")
        page_text = re.sub(r"\s+", " ", soup.get_text(" "))
        invitees = self._parse_invitee_table(soup)

        # 个人页上的「邀请: N」比邀请页准，邀请页那串数字是上传下载积分
        permanent = 0
        try:
            profile = get(session, site_url, f"user.php?id={user_id}")
            if profile.status_code == 200:
                profile_text = re.sub(r"\s+", " ", BeautifulSoup(profile.text, "html.parser").get_text(" "))
                permanent = self._invite_count(profile_text)
        except SiteAccessError:
            pass

        # 邀请页上有填邮箱的表单才是真能发
        has_form = False
        for form in soup.select("form"):
            names = [i.get("name") for i in form.select("input")]
            if "email" in names:
                has_form = True
                break

        result["invite_status"]["permanent_count"] = permanent
        result["invitees"] = invitees

        if re.search(r"你没有邀请|无法邀请|invites?\s*are\s*(?:currently\s*)?closed|邀请已关闭", page_text, re.I):
            result["invite_status"]["reason"] = "站点当前关闭了邀请"
        elif permanent > 0 and has_form:
            result["invite_status"]["can_invite"] = True
            result["invite_status"]["reason"] = f"可用邀请数: 永久={permanent}"
        elif has_form:
            result["invite_status"]["reason"] = "有发送入口，但当前没有可用邀请名额"
        else:
            result["invite_status"]["reason"] = "当前没有可用邀请名额"

        logger.info(f"站点 {site_name} Gazelle 解析完成: 邀请 {permanent} 个, 后宫 {len(invitees)} 人")
        return result
