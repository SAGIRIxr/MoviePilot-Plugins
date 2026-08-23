"""
站点访问层

上游插件里每个 handler 各自 new 一个 Session、各自处理异常，结果是同一类故障
（Cookie 过期、CF 盾、证书链不全、域名没了）在日志里长得完全一样，全都报
"无法获取用户ID"。这里把请求这一层收拢：统一挂代理、证书失败自动降级、编码
猜错时纠正，并把响应分类成人话原因。
"""
import re
from typing import Any, Dict, Optional

import requests
import urllib3
from urllib.parse import urljoin, urlparse

from app.core.config import settings
from app.log import logger

from . import cfbypass

DEFAULT_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36")

# 站点不可用的分类原因，refresh 时直接拿去展示
REASON_COOKIE_EXPIRED = "Cookie 已失效，请重新登录站点更新 Cookie"
REASON_CF_CHALLENGE = "被 Cloudflare 盾拦截，请在站点配置里开启浏览器仿真或稍后再试"
REASON_DNS_FAIL = "域名无法解析，站点可能已更换域名或关闭"
REASON_SITE_GONE = "站点无响应或已关闭"


class SiteAccessError(Exception):
    """带分类原因的站点访问失败。"""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


def _proxies_for(site_info: Dict[str, Any]) -> Optional[dict]:
    """站点在 MP 里勾了代理才走代理，没勾就直连。"""
    if not site_info.get("proxy"):
        return None
    proxies = getattr(settings, "PROXY", None)
    if not proxies:
        logger.warning("站点要求走代理，但 MP 没有配置 PROXY，只能直连")
    return proxies


def build_session(site_info: Dict[str, Any]) -> requests.Session:
    """按站点配置造一个 Session：UA、Cookie、代理都在这里挂好。"""
    url = (site_info.get("url") or "").strip()
    ua = (site_info.get("ua") or "").strip() or DEFAULT_UA
    cookie = (site_info.get("cookie") or "").strip()

    session = requests.Session()
    session.headers.update({
        "User-Agent": ua,
        "Referer": url,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
        "Upgrade-Insecure-Requests": "1",
    })
    if cookie:
        session.headers["Cookie"] = cookie

    proxies = _proxies_for(site_info)
    if proxies:
        session.proxies.update(proxies)

    # 证书降级过一次之后，同一个 Session 后续请求都别再验了，省得每个页面都重试一遍
    session.verify = True
    # 过 CF 时要知道是哪个站点、要不要走代理，挂在 Session 上带着走
    session._nexusinvitee_site = site_info
    return session


def _fix_encoding(response: requests.Response) -> None:
    """
    requests 在没有 charset 头时会拍脑袋定成 ISO-8859-1，TTG 这类站点就会整页乱码，
    连带把「邀请：0」解析成乱码匹配不上。这里按内容重猜一次。
    """
    declared = (response.encoding or "").lower()
    if declared and declared not in ("iso-8859-1", "ascii"):
        return
    body = response.content[:4096]
    m = re.search(rb'charset=["\']?\s*([\w-]+)', body, re.I)
    if m:
        try:
            response.encoding = m.group(1).decode("ascii")
            return
        except Exception:
            pass
    response.encoding = response.apparent_encoding or "utf-8"


def _site_info_of(session: requests.Session) -> Optional[dict]:
    """build_session 时把站点配置挂在了 Session 上，过 CF 的时候要用。"""
    return getattr(session, "_nexusinvitee_site", None)


def request(session: requests.Session, url: str, method: str = "get",
            timeout=(10, 30), _cf_retried: bool = False, **kwargs) -> requests.Response:
    """
    发一个请求，并且：
      - 证书验证不过时降级重试（PT 站自签 / 证书链不全太常见了），降级后记一条 warning
      - 撞上 Cloudflare 挑战页时，用 CloakBrowser 取一次通行证再重试
      - DNS 解析不了、连不上时抛出分类清楚的 SiteAccessError
      - 修正被猜错的编码
    """
    kwargs.setdefault("allow_redirects", True)
    try:
        response = session.request(method, url, timeout=timeout, **kwargs)
    except requests.exceptions.SSLError as e:
        if session.verify:
            logger.warning(f"{urlparse(url).netloc} 证书验证失败，降级为不校验证书重试: {str(e)[:120]}")
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
            session.verify = False
            response = session.request(method, url, timeout=timeout, **kwargs)
        else:
            raise SiteAccessError(f"SSL 握手失败: {str(e)[:120]}")
    except requests.exceptions.ConnectionError as e:
        text = str(e)
        if "NameResolutionError" in text or "Name or service not known" in text \
                or "Temporary failure in name resolution" in text:
            raise SiteAccessError(REASON_DNS_FAIL)
        raise SiteAccessError(f"{REASON_SITE_GONE}: {text[:120]}")
    except requests.exceptions.Timeout:
        raise SiteAccessError("请求超时，站点响应过慢或被墙")

    _fix_encoding(response)

    # 撞上 CF 挑战页：拿一次通行证重试。只重试一次，拿不到就把 403 原样交回去，
    # 让上层报「被 Cloudflare 盾拦截」而不是在这里空转
    if not _cf_retried and is_cf_challenge(response):
        site_info = _site_info_of(session)
        if site_info and site_info.get("browser_emulation", True) and cfbypass.available():
            if cfbypass.arm_session(session, site_info):
                logger.info(f"{urlparse(url).netloc} 已带上 CF 通行证重试")
                return request(session, url, method, timeout, _cf_retried=True, **kwargs)

    return response


def get(session: requests.Session, base_url: str, path: str, **kwargs) -> requests.Response:
    """相对路径版的 request，省得每个 handler 自己拼 urljoin。"""
    return request(session, urljoin(base_url, path.lstrip("/")), **kwargs)


# --- 响应分类 ---------------------------------------------------------------

_CF_MARKS = ("just a moment", "checking your browser", "cf-browser-verification",
             "challenge-platform", "cf_chl_opt", "attention required! | cloudflare")
_LOGIN_PATHS = ("login.php", "takelogin.php", "/p_login/", "/login", "signin")


def is_cf_challenge(response: requests.Response) -> bool:
    """CF 的五秒盾 / 人机验证页。"""
    if response.status_code not in (403, 503, 429):
        return False
    low = (response.text or "")[:6000].lower()
    return any(mark in low for mark in _CF_MARKS)


def is_login_page(response: requests.Response) -> bool:
    """
    Cookie 过期时站点几乎都是 200 + 跳登录页，靠状态码根本看不出来，
    只能看最终落点和页面里有没有登录表单。
    """
    final = (response.url or "").lower()
    if any(p in final for p in _LOGIN_PATHS):
        return True
    body = response.text or ""
    low = body.lower()
    if 'action="takelogin.php"' in low or "action='takelogin.php'" in low:
        return True
    m = re.search(r"<title[^>]*>(.*?)</title>", body, re.S | re.I)
    if m:
        title = re.sub(r"\s+", " ", m.group(1)).strip().lower()
        # 「XXX :: 登录」「Login」这种整页标题就是登录页，正文里出现「登录」不算
        if re.search(r"(^|[:\s|-])(登录|登入|login|sign in)\s*($|[:\s|-])", title):
            return True
    return False


def classify(response: requests.Response) -> Optional[str]:
    """把一个响应翻译成失败原因；能正常用就返回 None。"""
    if is_cf_challenge(response):
        return REASON_CF_CHALLENGE
    # 中间页 / 站点已下线要排在登录页判定之前：这类页面既不是登录页，
    # 也不该被当成 Cookie 问题
    problem = page_problem(response)
    if problem:
        return problem
    if is_login_page(response):
        return REASON_COOKIE_EXPIRED
    if response.status_code >= 500:
        return f"{REASON_SITE_GONE}（HTTP {response.status_code}）"
    if response.status_code == 403:
        return "站点返回 403，可能是 Cookie 失效或触发了风控"
    return None


def check_alive(session: requests.Session, site_info: Dict[str, Any]) -> Optional[str]:
    """
    连通性预检。

    上游是拿站点首页试的，可 UBits 这类站点恰恰是首页挂着 CF 盾、内页反而正常，
    于是每次都被判成整站失败。这里按「首页 -> 控制面板 -> 索引页」依次试，
    只要有一个页面能正常打开就算活着。
    """
    url = (site_info.get("url") or "").strip()
    last_reason = None
    for path in ("", "usercp.php", "index.php"):
        try:
            response = get(session, url, path or "/", timeout=(10, 30))
        except SiteAccessError as e:
            last_reason = e.reason
            continue
        reason = classify(response)
        if reason is None and response.status_code < 400:
            return None
        last_reason = reason or f"HTTP {response.status_code}"
    return last_reason or REASON_SITE_GONE


# --- 体系指纹 ---------------------------------------------------------------

def detect_schema(html: str, site_url: str = "") -> Optional[str]:
    """
    从首页 HTML 认出站点用的是哪套程序。

    上游是按域名硬编码匹配 handler 的，站点一换域名就退回 NexusPHP 处理器，
    然后去请求根本不存在的 usercp.php。看页面指纹比看域名靠谱得多。

    注意判定顺序和严格程度：PT 站首页普遍挂着一排友情链接，
    「页面里出现 totheglory」这种宽松匹配会把葡萄、北洋园这些正经 NexusPHP 站
    误判成 TTG，所以站点专属体系一律按域名认，只有通用体系才看页面内容。
    """
    if not html:
        return None
    host = urlparse(site_url or "").netloc.lower()
    low = html[:200000].lower()

    # TTG 是独一家，按域名认，绝不能靠页面里出现的字符串
    if host.endswith("totheglory.im"):
        return "ttg"
    # UNIT3D：Laravel + livewire，模板里全是 /users/xxx 和 unit3d 字样
    if "unit3d" in low or ("livewire" in low and "/users/" in low):
        return "unit3d"
    # NexusPHP 的这几个入口很有辨识度，放在 Gazelle 之前判
    if "nexusphp" in low or "usercp.php" in low or "takelogin.php" in low:
        return "nexusphp"
    # Gazelle：user.php?action= 系列配合 torrents.php
    if "gazelle" in low or ("user.php?action=" in low and "torrents.php" in low):
        return "gazelle"
    return None


_INTERSTITIAL_TITLES = ("redirecting", "just a moment", "please wait",
                        "checking your browser", "one moment")
_GONE_TITLES = ("没有找到站点", "站点不存在", "site not found", "no such site",
                "welcome to nginx", "apache2 ubuntu default page", "404 not found")


def _title_of(response: requests.Response) -> str:
    m = re.search(r"<title[^>]*>(.*?)</title>", response.text or "", re.S | re.I)
    return re.sub(r"\s+", " ", m.group(1)).strip().lower() if m else ""


def page_problem(response: requests.Response) -> Optional[str]:
    """
    页面能打开、状态码也正常，但内容根本不是站点本体的情况。

    没有这一层的话，Rousi 的 JS 反爬中间页和铂金学院那个「没有找到站点」
    都会一路走到 NexusPHP 处理器里，最后统一报成「Cookie 已失效」，
    照着这个提示去换 Cookie 是白费功夫。
    """
    title = _title_of(response)
    if not title:
        return None
    if any(t in title for t in _GONE_TITLES):
        return REASON_SITE_GONE
    if any(t in title for t in _INTERSTITIAL_TITLES):
        return ("站点返回了跳转/校验中间页（反爬或 CDN 拦截），"
                "拿不到真实页面内容")
    return None
