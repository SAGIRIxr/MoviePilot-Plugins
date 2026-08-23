"""
Cloudflare 通行证

MoviePilot 从 2.14 起把站点访问换成了 CloakBrowser 内核（settings.BROWSER_EMULATION
默认就是 cloakbrowser），但这个插件一直是裸 requests，所以挂了 CF 盾的站点
（UBits 这种）永远拿 403 的「Just a moment...」。

这里补上：撞到挑战页时开一次无头浏览器把 cf_clearance 拿回来，塞进 Session 继续用。
cf_clearance 是和 UA + 出口 IP 绑定的，所以浏览器用的 UA 必须一起带回来覆盖掉
站点原本配置的 UA，否则通行证当场作废。
"""
import threading
import time
from typing import Dict, Optional, Tuple
from urllib.parse import urlparse

import requests

from app.core.config import settings
from app.log import logger

# cf_clearance 有效期通常挺长，保守按 6 小时复用；进程内缓存，按域名分开存
_TTL = 6 * 3600
# 过盾失败也要记下来。一次挑战最多要跑 100 秒，而一轮刷新里同一个站点会被访问好几次
# （预检三个入口 + 邀请页），不缓存失败的话光一个 UBits 就能把刷新拖上五分钟。
_FAIL_TTL = 30 * 60
_cache: Dict[str, Tuple[Optional[str], Optional[str], float]] = {}
_lock = threading.Lock()


def available() -> bool:
    """当前环境有没有 CloakBrowser。"""
    try:
        import cloakbrowser  # noqa: F401
        return True
    except Exception:
        return False


def _proxy_server(site_info: dict) -> Optional[str]:
    """站点勾了代理就把代理地址给浏览器，不然浏览器出口 IP 和 requests 对不上，
    拿回来的通行证照样不能用。"""
    if not site_info.get("proxy"):
        return None
    return getattr(settings, "PROXY_SERVER", None) or None


def _fetch(site_url: str, proxy: Optional[str]) -> Tuple[Optional[str], Optional[str]]:
    """开一个干净的浏览器上下文过挑战，返回 (cf_clearance, UA)。"""
    try:
        from cloakbrowser import launch_context
    except Exception as e:
        logger.warning(f"未安装 CloakBrowser 浏览器仿真环境，无法自动过 CF: {e}")
        return None, None

    context = page = None
    try:
        logger.info(f"[CF] 启动浏览器仿真获取 {urlparse(site_url).netloc} 的通行证...")
        context = launch_context(
            headless=True,
            proxy=proxy,
            humanize=bool(getattr(settings, "CLOAKBROWSER_HUMANIZE", True)),
            human_preset=getattr(settings, "CLOAKBROWSER_HUMAN_PRESET", "default"),
        )
        page = context.new_page()
        page.goto(site_url, timeout=60 * 1000)
        try:
            page.wait_for_load_state("networkidle", timeout=60 * 1000)
        except Exception:
            pass

        # 注意：这个上下文里不要注入站点已有的 Cookie。带着过期 session 去过挑战，
        # WAF 会一直下发新挑战，浏览器就卡在 Just a moment 页出不来。
        clearance = None
        deadline = time.time() + 40
        while time.time() < deadline:
            clearance = next((c.get("value") for c in (context.cookies() or [])
                              if c.get("name") == "cf_clearance"), None)
            if clearance:
                break
            time.sleep(3)

        ua = None
        try:
            ua = page.evaluate("()=>navigator.userAgent")
        except Exception:
            pass

        if clearance and ua:
            logger.info(f"[CF] 已取得 {urlparse(site_url).netloc} 的通行证")
            return clearance, ua
        logger.warning(f"[CF] {urlparse(site_url).netloc} 未能取得 cf_clearance，可能仍卡在挑战页")
        return None, None
    except Exception as e:
        logger.error(f"[CF] 获取通行证异常: {e}")
        return None, None
    finally:
        for obj in (page, context):
            try:
                if obj:
                    obj.close()
            except Exception:
                pass


def get_clearance(site_info: dict, force: bool = False) -> Tuple[Optional[str], Optional[str]]:
    """取一个可用的 (cf_clearance, UA)，命中缓存就不开浏览器。"""
    site_url = (site_info.get("url") or "").strip()
    host = urlparse(site_url).netloc.lower()
    if not host:
        return None, None

    with _lock:
        if not force:
            cached = _cache.get(host)
            if cached:
                clearance, ua, ts = cached
                age = time.time() - ts
                if clearance and ua and age < _TTL:
                    return clearance, ua
                if not clearance and age < _FAIL_TTL:
                    # 刚试过没成，这轮就别再开浏览器了
                    logger.debug(f"[CF] {host} 最近一次过盾失败，{int(_FAIL_TTL - age)} 秒内不再重试")
                    return None, None

        clearance, ua = _fetch(site_url, _proxy_server(site_info))
        # 成功失败都记，失败按更短的 TTL 冷却
        _cache[host] = (clearance, ua, time.time())
        return clearance, ua


def arm_session(session: requests.Session, site_info: dict, force: bool = False) -> bool:
    """
    把通行证挂到 Session 上。

    站点原本的登录 Cookie 要留着——cf_clearance 只负责过盾，身份还是靠它。
    """
    clearance, ua = get_clearance(site_info, force=force)
    if not clearance or not ua:
        return False

    existing = session.headers.get("Cookie") or ""
    parts = [p.strip() for p in existing.split(";") if p.strip()
             and not p.strip().lower().startswith("cf_clearance=")]
    parts.append(f"cf_clearance={clearance}")
    session.headers["Cookie"] = "; ".join(parts)
    # UA 必须换成浏览器那个，通行证和 UA 是绑定的
    session.headers["User-Agent"] = ua
    return True
