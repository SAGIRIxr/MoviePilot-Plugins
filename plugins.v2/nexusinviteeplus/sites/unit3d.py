"""
UNIT3D 体系站点（Aither、HUNO、Blutopia 这一挂）

上游插件只认 NexusPHP，碰到 UNIT3D 会去请求 usercp.php，站点直接回 404，
于是全部报「无法获取用户ID」。UNIT3D 根本没有 .php 入口，用户主页是
/users/{用户名}，邀请页是 /users/{用户名}/invites。
"""
import re
from typing import Any, Dict, List, Optional

import requests
from bs4 import BeautifulSoup

from app.log import logger

from . import _ISiteHandler
from ..sitehttp import SiteAccessError, classify, get

# 已知的 UNIT3D 站点域名。识别主要靠首页指纹（见 sitehttp.detect_schema），
# 这里只是让 match() 这条老路子也能命中。
KNOWN_DOMAINS = (
    "aither.cc", "hawke.uno", "blutopia.cc", "blutopia.xyz", "fearnopeer.com",
    "reelflix.xyz", "onlyencodes.cc", "upload.cx", "lst.gg", "seedpool.org",
    "itatorrents.xyz", "yu-scene.net", "cinematik.net", "shareisland.org",
)


class Unit3dHandler(_ISiteHandler):
    """UNIT3D 站点邀请系统处理器。"""

    site_schema = "unit3d"

    @classmethod
    def match(cls, site_url: str) -> bool:
        low = (site_url or "").lower()
        return any(domain in low for domain in KNOWN_DOMAINS)

    # --- 内部工具 ---

    @staticmethod
    def _find_username(html: str) -> Optional[str]:
        """
        找出当前登录的用户名。

        导航栏那个 top-nav__username 是最准的；主题改过的站点没这个 class，
        就退而求其次数 /users/xxx 出现的次数——自己的用户名会在导航、消息、
        设置一堆链接里反复出现，一定是最高频的那个。
        """
        soup = BeautifulSoup(html, "html.parser")
        for selector in ("a.top-nav__username",
                         "a[href*='/general-settings']",
                         "a[href*='/hub/settings']",
                         "a[href*='/settings/security']"):
            node = soup.select_one(selector)
            if node and node.get("href"):
                m = re.search(r"/users/([^/?#]+)", node["href"])
                if m:
                    return m.group(1)

        counts = {}
        for name in re.findall(r"/users/([^/\"'?#]+)", html):
            counts[name] = counts.get(name, 0) + 1
        if not counts:
            return None
        return max(counts.items(), key=lambda kv: kv[1])[0]

    @staticmethod
    def _invite_count(soup: BeautifulSoup) -> int:
        """从用户主页/邀请页上抠出剩余邀请数。"""
        for node in soup.select("[class*='invite']"):
            text = node.get_text(strip=True)
            if text.isdigit():
                return int(text)
        text = re.sub(r"\s+", " ", soup.get_text(" "))
        for pattern in (r"(?:邀请|Invites?)\s*[:：]?\s*(\d+)",
                        r"(\d+)\s*(?:invites?\s*(?:left|remaining)|个邀请)"):
            m = re.search(pattern, text, re.I)
            if m:
                return int(m.group(1))
        return 0

    @staticmethod
    def _parse_invite_table(soup: BeautifulSoup) -> List[Dict[str, Any]]:
        """
        解析「已寄出的邀请」表。

        UNIT3D 这张表记的是邀请码本身，列是 寄件者/邮箱/创建于/过期于/接受者/…，
        不像 NexusPHP 那样带被邀请人的上传下载，所以只能给出接受状态。
        """
        invitees = []
        for table in soup.select("table"):
            headers = [th.get_text(strip=True) for th in table.select("th")]
            if not headers:
                continue
            joined = " ".join(headers)
            if not re.search(r"接受者|Accepted\s*By|邮箱|Email", joined, re.I):
                continue

            def col(*names):
                for idx, header in enumerate(headers):
                    if any(n.lower() in header.lower() for n in names):
                        return idx
                return None

            i_email = col("邮箱", "email")
            i_accepted = col("接受者", "accepted by")
            i_created = col("创建于", "created")
            i_expires = col("过期于", "expires")
            i_accepted_at = col("接受于", "accepted on", "accepted at")

            body_rows = table.select("tbody tr") or table.select("tr")[1:]
            for row in body_rows:
                cells = [td.get_text(strip=True) for td in row.select("td")]
                if len(cells) < 2:
                    continue

                def cell(idx):
                    return cells[idx] if idx is not None and idx < len(cells) else ""

                accepted = cell(i_accepted)
                email = cell(i_email)
                if not accepted and not email:
                    continue
                if accepted:
                    status, enabled = "已接受", "Yes"
                elif cell(i_expires) and re.search(r"过期|expired", cell(i_expires), re.I):
                    status, enabled = "已过期", "No"
                else:
                    status, enabled = "待接受", "Yes"

                invitees.append({
                    "username": accepted or email or "（未使用的邀请）",
                    "email": email,
                    "uploaded": "",
                    "downloaded": "",
                    "ratio": "",
                    "enabled": enabled,
                    "status": status,
                    "joined": cell(i_accepted_at) or cell(i_created),
                })
            if invitees:
                break
        return invitees

    # --- 主流程 ---

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

        username = self._find_username(home.text)
        if not username:
            result["invite_status"]["reason"] = "页面里找不到当前登录用户，Cookie 可能已失效"
            return result
        logger.info(f"站点 {site_name} 识别为 UNIT3D，当前用户: {username}")

        # 各家 fork 把邀请页挂在不同路径下，挨个试
        candidates = (f"/users/{username}/invites",
                      f"/users/{username}/hub/invites",
                      "/invites")
        invite_page = None
        for path in candidates:
            try:
                response = get(session, site_url, path)
            except SiteAccessError as e:
                result["invite_status"]["reason"] = e.reason
                return result
            if response.status_code == 200 and classify(response) is None:
                invite_page = response
                logger.debug(f"站点 {site_name} 邀请页命中 {path}")
                break

        if invite_page is None:
            # HUNO 这类 fork 直接把邀请页关掉了，说清楚比报「无法获取用户ID」强
            result["invite_status"]["reason"] = "该站点未开放邀请页面（UNIT3D 定制版本已移除 /invites）"
            return result

        soup = BeautifulSoup(invite_page.text, "html.parser")
        permanent = self._invite_count(soup)
        if not permanent:
            try:
                profile = get(session, site_url, f"/users/{username}")
                if profile.status_code == 200:
                    permanent = self._invite_count(BeautifulSoup(profile.text, "html.parser"))
            except SiteAccessError:
                pass

        invitees = self._parse_invite_table(soup)
        page_text = re.sub(r"\s+", " ", soup.get_text(" "))
        send_selector = "a[href*='invites/create'], form[action*='invite']"
        has_send_form = bool(soup.select_one(send_selector)) or \
            bool(re.search(r"寄出邀请|Send\s*Invite", page_text, re.I))

        result["invite_status"]["permanent_count"] = permanent
        result["invitees"] = invitees

        if permanent > 0 and has_send_form:
            result["invite_status"]["can_invite"] = True
            result["invite_status"]["reason"] = f"可用邀请数: 永久={permanent}"
        elif permanent > 0:
            result["invite_status"]["can_invite"] = True
            result["invite_status"]["reason"] = f"有 {permanent} 个邀请，但页面上没找到发送入口"
        else:
            result["invite_status"]["reason"] = "当前没有可用邀请名额"

        logger.info(f"站点 {site_name} UNIT3D 解析完成: 邀请 {permanent} 个, 已发出 {len(invitees)} 条")
        return result
