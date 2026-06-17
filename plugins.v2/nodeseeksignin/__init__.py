# -*- coding: utf-8 -*-
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from typing import Any, List, Dict, Tuple, Optional

import pytz
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from app.core.config import settings
from app.plugins import _PluginBase
from app.log import logger
from app.schemas import NotificationType

from .turnstile_solver import TurnstileSolver, TurnstileSolverError
from .yescaptcha import YesCaptchaSolver, YesCaptchaSolverError

# NodeSeek 站点常量
SIGNIN_PAGE = "https://www.nodeseek.com/signIn.html"
SIGNIN_API = "https://www.nodeseek.com/api/account/signIn"
ATTENDANCE_API = "https://www.nodeseek.com/api/attendance"
CREDIT_API = "https://www.nodeseek.com/api/account/credit/page-"
SITEKEY = "0x4AAAAAAAaNy7leGjewpVyR"


class NodeSeekSignin(_PluginBase):
    # 插件名称
    plugin_name = "NodeSeek签到"
    # 插件描述
    plugin_desc = "NodeSeek 论坛自动签到，支持多账号 Cookie / 账密登录、随机签到、收益统计与通知。"
    # 插件图标
    plugin_icon = "https://www.nodeseek.com/static/image/favicon/favicon-32x32.png"
    # 插件版本
    plugin_version = "1.0.6"
    # 插件作者
    plugin_author = "SAGIRIxr"
    # 作者主页
    author_url = "https://github.com/SAGIRIxr"
    # 插件配置项ID前缀
    plugin_config_prefix = "nodeseeksignin_"
    # 加载顺序
    plugin_order = 24
    # 可使用的用户级别
    auth_level = 2

    # ---------------- 私有属性 ----------------
    _enabled = False
    _onlyonce = False
    _notify = True
    _cron = None
    # NS_COOKIE：多账号用 & 或换行分隔
    _cookie = ""
    # 账密：每行一个，格式 用户名----密码
    _accounts = ""
    # NS_RANDOM
    _ns_random = True
    # SOLVER_TYPE：turnstile / yescaptcha
    _solver_type = "turnstile"
    # API_BASE_URL（CloudFreed 地址 / YesCaptcha 节点）
    _api_base_url = ""
    # CLIENTT_KEY
    _client_key = ""
    # NS_IMPERSONATE 首选指纹
    _impersonate = "chrome110"
    # 收益统计周期（天）
    _stats_days = 30
    # 历史记录保留天数
    _history_days = 30
    # 是否使用 MoviePilot 系统代理
    _use_proxy = False
    # 登录成功后是否把新 Cookie 写回插件配置
    _auto_save_cookie = True
    # 账密登录时是否优先使用 MoviePilot 内置 CloakBrowser 真实浏览器（curl_cffi 在 MP 环境取不到登录 Cookie）
    _use_browser_login = True

    # 定时器
    _scheduler: Optional[BackgroundScheduler] = None

    # 指纹候选列表（与原脚本一致）
    _impersonate_defaults = [
        # Chrome (Desktop)
        "chrome99", "chrome100", "chrome101", "chrome104", "chrome107",
        "chrome110", "chrome116", "chrome119", "chrome120", "chrome123",
        "chrome124", "chrome131", "chrome133a", "chrome136",
        # Chrome (Android)
        "chrome99_android", "chrome131_android",
        # Edge
        "edge99", "edge101",
        # Safari
        "safari153", "safari155", "safari170", "safari172_ios", "safari180",
        "safari180_ios", "safari184", "safari184_ios", "safari260", "safari260_ios",
        # Firefox / Tor
        "firefox133", "tor145",
    ]

    def init_plugin(self, config: dict = None):
        # 停止现有任务
        self.stop_service()

        if config:
            self._enabled = config.get("enabled") or False
            self._onlyonce = config.get("onlyonce") or False
            self._notify = config.get("notify") if config.get("notify") is not None else True
            self._cron = config.get("cron")
            self._cookie = config.get("cookie") or ""
            self._accounts = config.get("accounts") or ""
            self._ns_random = config.get("ns_random") if config.get("ns_random") is not None else True
            self._solver_type = (config.get("solver_type") or "turnstile").strip()
            self._api_base_url = (config.get("api_base_url") or "").strip()
            self._client_key = (config.get("client_key") or "").strip()
            self._impersonate = (config.get("impersonate") or "chrome110").strip()
            self._stats_days = int(config.get("stats_days") or 30)
            self._history_days = int(config.get("history_days") or 30)
            self._use_proxy = config.get("use_proxy") or False
            self._auto_save_cookie = config.get("auto_save_cookie") if config.get("auto_save_cookie") is not None else True
            self._use_browser_login = config.get("use_browser_login") if config.get("use_browser_login") is not None else True

        # 立即运行一次
        if self._onlyonce:
            self._scheduler = BackgroundScheduler(timezone=settings.TZ)
            logger.info("NodeSeek签到服务启动，立即运行一次")
            self._scheduler.add_job(func=self.signin, trigger='date',
                                    run_date=datetime.now(tz=pytz.timezone(settings.TZ)) + timedelta(seconds=3),
                                    name="NodeSeek签到")
            self._onlyonce = False
            self.__update_config()
            if self._scheduler.get_jobs():
                self._scheduler.print_jobs()
                self._scheduler.start()

    def __update_config(self):
        """将当前配置写回插件配置（用于重置 onlyonce / 回写刷新后的 Cookie）"""
        self.update_config({
            "enabled": self._enabled,
            "onlyonce": self._onlyonce,
            "notify": self._notify,
            "cron": self._cron,
            "cookie": self._cookie,
            "accounts": self._accounts,
            "ns_random": self._ns_random,
            "solver_type": self._solver_type,
            "api_base_url": self._api_base_url,
            "client_key": self._client_key,
            "impersonate": self._impersonate,
            "stats_days": self._stats_days,
            "history_days": self._history_days,
            "use_proxy": self._use_proxy,
            "auto_save_cookie": self._auto_save_cookie,
            "use_browser_login": self._use_browser_login,
        })

    # ---------------- 工具方法 ----------------
    def __get_proxies(self):
        """获取系统代理"""
        if not self._use_proxy:
            return None
        try:
            if hasattr(settings, "PROXY") and settings.PROXY:
                return settings.PROXY
        except Exception as e:
            logger.error(f"获取代理设置出错: {e}")
        return None

    def __impersonate_candidates(self) -> List[str]:
        """生成 curl_cffi impersonate 版本候选列表，首选项优先。"""
        candidates: List[str] = []
        for v in ([self._impersonate] if self._impersonate else []) + self._impersonate_defaults:
            if v and v not in candidates:
                candidates.append(v)
        return candidates

    @staticmethod
    def _is_cloudflare_challenge(text: str) -> bool:
        if not text:
            return False
        t = text.lower()
        return ("just a moment" in t) or ("cf-chl" in t) or ("challenge" in t and "cloudflare" in t)

    def _request_with_impersonate_fallback(self, method: str, url: str, *, headers: dict,
                                           json_data=None, timeout: int = 25):
        """带指纹回退的请求（应对 Cloudflare 403 挑战页）。"""
        from curl_cffi import requests as cffi_requests
        proxies = self.__get_proxies()
        last_resp = None
        last_err = None
        for ver in self.__impersonate_candidates():
            try:
                resp = cffi_requests.request(method, url, headers=headers, json=json_data,
                                             impersonate=ver, timeout=timeout, proxies=proxies)
                last_resp = resp
                if resp.status_code != 403:
                    return resp, ver, None
                if self._is_cloudflare_challenge(resp.text):
                    logger.warning(f"403 Cloudflare 挑战 (impersonate={ver})，尝试切换指纹...")
                    continue
                return resp, ver, None
            except Exception as e:
                last_err = e
                logger.warning(f"请求异常 (impersonate={ver}): {e}")
                continue
        candidates = self.__impersonate_candidates()
        return last_resp, (candidates[-1] if candidates else self._impersonate), last_err

    # ---------------- 登录逻辑 ----------------
    @staticmethod
    def __extract_cookies(session, response) -> dict:
        """尽可能从 curl_cffi 的会话/响应中提取 cookie（兼容不同取法）。"""
        cookies = {}
        for obj in (session, response):
            try:
                d = obj.cookies.get_dict()
                if d:
                    cookies.update(d)
            except Exception:
                pass
        # 遍历底层 cookiejar 兜底
        try:
            for c in session.cookies.jar:
                if getattr(c, "name", None):
                    cookies.setdefault(c.name, c.value)
        except Exception:
            pass
        try:
            jar_names = [getattr(c, "name", "?") for c in session.cookies.jar]
            logger.info(f"会话 cookie jar：{jar_names}")
        except Exception as e:
            logger.info(f"读取 cookie jar 失败：{e}；session.cookies={str(session.cookies)[:200]}")
        return cookies

    def __solve_captcha(self) -> Tuple[Optional[str], str]:
        """调用验证码服务解出 Turnstile 令牌，返回 (token, 失败原因)。成功时原因为空。"""
        if not self._client_key:
            return None, "未配置验证码密钥（CLIENTT_KEY）；账密登录必须配验证码服务"
        try:
            if self._solver_type.lower() == "yescaptcha":
                logger.info(f"正在使用 YesCaptcha 解决验证码（节点：{self._api_base_url or 'https://api.yescaptcha.com'}）...")
                solver = YesCaptchaSolver(
                    api_base_url=self._api_base_url or "https://api.yescaptcha.com",
                    client_key=self._client_key,
                )
            else:
                logger.info("正在使用 TurnstileSolver 解决验证码...")
                if not self._api_base_url:
                    return None, "验证码服务选择了 turnstile 但未填 API_BASE_URL（需自建 CloudFreed）；有 YesCaptcha 密钥请把服务改为 yescaptcha"
                solver = TurnstileSolver(
                    api_base_url=self._api_base_url,
                    client_key=self._client_key,
                )
            token = solver.solve(url=SIGNIN_PAGE, sitekey=SITEKEY, verbose=True)
            if not token:
                return None, "验证码解析失败（检查服务类型/密钥/余额/节点）"
            return token, ""
        except (TurnstileSolverError, YesCaptchaSolverError) as e:
            return None, f"验证码服务错误：{e}"
        except Exception as e:
            return None, f"验证码服务异常：{e}"

    def __browser_signin(self, user: str, password: str) -> Tuple[str, str, Optional[dict]]:
        """账密 → 浏览器仿真：登录 + 签到 + 收益统计，全程在 CloakBrowser 内完成。

        NodeSeek 新版鉴权为 HTTP 头（x-security-token 由登录响应头下发，x-integrity-token 由
        浏览器指纹算出），取不到、也用不上 Cookie，因此登录后直接在浏览器内带正确鉴权头调用
        签到 / 收益接口。返回 (结果状态, 消息, 收益统计dict 或 None)。
        """
        token, reason = self.__solve_captcha()
        if not token:
            return "loginfail", f"登录失败：{reason}", None
        return self.__run_browser_flow(user, password, token)

    def __run_browser_flow(self, user: str, password: str, token: str) -> Tuple[str, str, Optional[dict]]:
        """在 CloakBrowser 内执行：登录 → 写入 localStorage 令牌 → 构造鉴权头 → 签到 + 收益统计。"""
        try:
            from cloakbrowser import launch_context
        except Exception as e:
            return "loginfail", f"登录失败：未安装 CloakBrowser 浏览器仿真环境：{e}", None

        proxy = None
        try:
            if self._use_proxy and hasattr(settings, "PROXY_SERVER") and settings.PROXY_SERVER:
                proxy = settings.PROXY_SERVER
        except Exception:
            pass

        context = None
        page = None
        try:
            logger.info("[浏览器仿真] 启动 CloakBrowser 登录并签到...")
            context = launch_context(headless=True, proxy=proxy)
            page = context.new_page()
            page.goto(SIGNIN_PAGE)
            try:
                page.wait_for_load_state("networkidle", timeout=60 * 1000)
            except Exception:
                pass

            js = r"""
            async ({token, username, password, statsDays}) => {
                const out = {phase: 'start'};
                // 1) 登录
                const lr = await fetch('/api/account/signIn', {
                    method: 'POST', credentials: 'include',
                    headers: {'Content-Type': 'application/json', 'x-captcha-token': token, 'x-captcha-source': 'turnstile'},
                    body: JSON.stringify({username: username, password: password})
                });
                out.loginStatus = lr.status;
                const sec = lr.headers.get('x-security-token');
                const csrf = lr.headers.get('x-csrf-token');
                out.hasSec = !!sec;
                try { out.loginBody = await lr.json(); } catch (e) { out.loginBody = null; }
                if (!out.loginBody || !out.loginBody.success) { out.phase = 'login-fail'; return out; }
                // 2) 像前端 postLogin 一样把令牌写入 localStorage
                try { if (sec) localStorage.setItem('security_token', sec); } catch (e) {}
                try { if (csrf) localStorage.setItem('csrf_token', csrf); } catch (e) {}
                // 3) 用前端 preLogin 模块构造鉴权头（含指纹算出的 x-integrity-token）
                let vh = {};
                try {
                    const urls = performance.getEntriesByType('resource').map(e => e.name);
                    const preUrl = urls.find(u => /\/assets\/preLogin-[^/]*\.js/.test(u));
                    const pre = await import(preUrl);
                    vh = await pre.g();
                    out.vKeys = Object.keys(vh);
                } catch (e) {
                    out.vErr = String(e);
                    if (sec) vh = {'x-security-token': sec};
                }
                // 4) 签到
                const ar = await fetch('/api/attendance?random=true', {
                    method: 'POST', credentials: 'include',
                    headers: Object.assign({'Content-Type': 'application/json'}, vh), body: '{}'
                });
                out.attStatus = ar.status;
                try { out.attBody = await ar.json(); } catch (e) { out.attBody = null; }
                // 5) 收益统计（积分流水分页）
                try {
                    const minMs = Date.now() - statsDays * 86400 * 1000;
                    let total = 0, cnt = 0, page = 1, stop = false;
                    while (page <= 20 && !stop) {
                        const cr = await fetch('/api/account/credit/page-' + page, {credentials: 'include', headers: vh});
                        let cb = null; try { cb = await cr.json(); } catch (e) {}
                        if (!cb || !cb.success || !cb.data || !cb.data.length) break;
                        for (const rec of cb.data) {
                            const amt = rec[0], desc = rec[2], ts = rec[3];
                            const t = new Date(ts).getTime();
                            if (t < minMs) { stop = true; continue; }
                            if (typeof desc === 'string' && desc.indexOf('签到收益') >= 0 && desc.indexOf('鸡腿') >= 0) { total += amt; cnt++; }
                        }
                        page++;
                    }
                    out.stats = {total: total, cnt: cnt};
                } catch (e) { out.statsErr = String(e); }
                out.phase = 'done';
                return out;
            }
            """
            res = page.evaluate(js, {"token": token, "username": user, "password": password,
                                     "statsDays": int(self._stats_days or 30)}) or {}
            logger.info(f"[浏览器仿真] 登录HTTP={res.get('loginStatus')} hasSecToken={res.get('hasSec')} "
                        f"鉴权头={res.get('vKeys')} vErr={res.get('vErr')} 签到HTTP={res.get('attStatus')}")

            login_body = res.get("loginBody") or {}
            if res.get("phase") == "login-fail" or not login_body.get("success"):
                msg = login_body.get("message") or f"HTTP {res.get('loginStatus')}"
                return "loginfail", f"登录失败：{msg}", None

            att = res.get("attBody") or {}
            amsg = att.get("message") or ""
            logger.info(f"[浏览器仿真] 签到响应：HTTP {res.get('attStatus')}，message={amsg}")
            if "鸡腿" in amsg or att.get("success"):
                result = "success"
            elif "已完成" in amsg or "已经签到" in amsg or "已签到" in amsg:
                result = "already"
            else:
                result = "fail"

            stats = None
            s = res.get("stats")
            if isinstance(s, dict):
                cnt = int(s.get("cnt") or 0)
                total = s.get("total") or 0
                period = "今天" if int(self._stats_days or 30) == 1 else f"近{self._stats_days}天"
                stats = {
                    "total_amount": total,
                    "average": round(total / cnt, 2) if cnt else 0,
                    "days_count": cnt,
                    "records": [],
                    "period": period,
                }
            return result, (amsg or "签到完成"), stats
        except Exception as e:
            logger.error(f"[浏览器仿真] 流程异常：{e}")
            return "error", f"浏览器流程异常：{e}", None
        finally:
            try:
                if page:
                    page.close()
            except Exception:
                pass
            try:
                if context:
                    context.close()
            except Exception:
                pass

    def __session_login(self, user: str, password: str) -> Tuple[Optional[str], str]:
        """[兜底] curl_cffi 账密登录（仅在关闭「浏览器登录」时使用）。返回 (新 Cookie, 失败原因)。

        注意：NodeSeek 新版鉴权已改为 HTTP 头（x-security-token + x-integrity-token），
        curl_cffi 在 MoviePilot 环境登录虽成功但取不到鉴权信息，此路径多半无效，仅作保留。
        """
        from curl_cffi import requests as cffi_requests
        token, reason = self.__solve_captcha()
        if not token:
            return None, reason

        proxies = self.__get_proxies()
        initial_impersonate = self._impersonate or "chrome110"
        session = cffi_requests.Session(impersonate=initial_impersonate)
        logger.info(f"使用初始 impersonate: {initial_impersonate}")
        try:
            session.get(SIGNIN_PAGE, proxies=proxies)
        except Exception as e:
            logger.warning(f"预加载登录页异常: {e}")

        # NodeSeek 登录接口：验证码 token 改走请求头 x-captcha-token / x-captcha-source
        data = {"username": user, "password": password}
        headers = {
            'User-Agent': "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36 Edg/125.0.0.0",
            'sec-ch-ua': "\"Not A(Brand\";v=\"99\", \"Microsoft Edge\";v=\"121\", \"Chromium\";v=\"121\"",
            'sec-ch-ua-mobile': "?0",
            'sec-ch-ua-platform': "\"Windows\"",
            'origin': "https://www.nodeseek.com",
            'sec-fetch-site': "same-origin",
            'sec-fetch-mode': "cors",
            'sec-fetch-dest': "empty",
            'referer': SIGNIN_PAGE,
            'accept-language': "zh-CN,zh;q=0.9,en;q=0.8,en-GB;q=0.7,en-US;q=0.6",
            'Content-Type': "application/json",
            'x-captcha-token': token,
            'x-captcha-source': "turnstile",
        }
        try:
            response = session.post(SIGNIN_API, json=data, headers=headers, proxies=proxies)
            try:
                resp_json = response.json()
            except Exception:
                snippet = (response.text or "")[:120]
                return None, f"登录接口返回非 JSON（HTTP {response.status_code}），可能被 Cloudflare 拦截：{snippet}"
            logger.info(f"登录响应：HTTP {response.status_code}，success={resp_json.get('success')}，message={resp_json.get('message')}")
            if resp_json.get("success"):
                cookies = self.__extract_cookies(session, response)
                cookie_string = '; '.join([f"{k}={v}" for k, v in cookies.items()])
                if not cookie_string:
                    set_cookie = response.headers.get('Set-Cookie', '') or response.headers.get('set-cookie', '')
                    logger.warning(f"登录成功但仍未取到 Cookie；Set-Cookie={str(set_cookie)[:300]}")
                    return None, "登录返回成功但未取到 Cookie（curl_cffi 未捕获会话 Cookie，建议改用浏览器仿真）"
                logger.info(f"登录成功，获取到 Cookie 字段：{list(cookies.keys())}")
                return cookie_string, ""
            return None, f"登录接口拒绝：{resp_json.get('message')}"
        except Exception as e:
            logger.error(f"登录异常: {e}")
            return None, f"登录请求异常：{e}"

    # ---------------- 签到逻辑 ----------------
    def __sign(self, ns_cookie: str) -> Tuple[str, str]:
        """单个 Cookie 签到，返回 (结果状态, 消息)。"""
        if not ns_cookie:
            return "invalid", "无有效Cookie"
        ns_random = "true" if self._ns_random else "false"
        headers = {
            'User-Agent': "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36 Edg/125.0.0.0",
            'origin': "https://www.nodeseek.com",
            'referer': "https://www.nodeseek.com/board",
            'Content-Type': 'application/json',
            'Cookie': ns_cookie,
        }
        try:
            url = f"{ATTENDANCE_API}?random={ns_random}"
            response, used_impersonate, req_err = self._request_with_impersonate_fallback(
                "POST", url, headers=headers, json_data={}, timeout=25)
            if req_err is not None:
                return "error", f"请求异常: {req_err}"
            if response is None:
                return "error", "请求失败：无响应"
            if response.status_code == 403:
                if self._is_cloudflare_challenge(response.text):
                    return "forbidden", f"403 Cloudflare challenge (最后尝试 impersonate={used_impersonate})"
                return "forbidden", f"403 Forbidden (impersonate={used_impersonate})"
            data = response.json()
            msg = data.get("message", "")
            if "鸡腿" in msg or data.get("success"):
                return "success", msg
            elif "已完成签到" in msg:
                return "already", msg
            elif data.get("status") == 404:
                return "invalid", msg
            return "fail", msg
        except Exception as e:
            return "error", str(e)

    # ---------------- 收益统计 ----------------
    def __get_signin_stats(self, ns_cookie: str, days: int = 30) -> Tuple[Optional[dict], str]:
        """查询前 days 天内的签到收益统计。"""
        if not ns_cookie:
            return None, "无有效Cookie"
        if days <= 0:
            days = 1
        headers = {
            'User-Agent': "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36 Edg/125.0.0.0",
            'origin': "https://www.nodeseek.com",
            'referer': "https://www.nodeseek.com/board",
            'Cookie': ns_cookie,
        }
        try:
            shanghai_tz = ZoneInfo("Asia/Shanghai")
            now_shanghai = datetime.now(shanghai_tz)
            query_start_time = now_shanghai - timedelta(days=days)

            all_records = []
            page = 1
            while page <= 20:
                url = f"{CREDIT_API}{page}"
                response, used_impersonate, req_err = self._request_with_impersonate_fallback(
                    "GET", url, headers=headers, json_data=None, timeout=25)
                if req_err is not None:
                    return None, f"请求异常: {req_err}"
                if response is None:
                    return None, "请求失败：无响应"

                data = response.json()
                if not data.get("success") or not data.get("data"):
                    break
                records = data.get("data", [])
                if not records:
                    break

                last_record_time = datetime.fromisoformat(records[-1][3].replace('Z', '+00:00'))
                last_record_time_shanghai = last_record_time.astimezone(shanghai_tz)
                if last_record_time_shanghai < query_start_time:
                    for record in records:
                        record_time = datetime.fromisoformat(record[3].replace('Z', '+00:00'))
                        if record_time.astimezone(shanghai_tz) >= query_start_time:
                            all_records.append(record)
                    break
                else:
                    all_records.extend(records)
                page += 1
                time.sleep(0.5)

            signin_records = []
            for record in all_records:
                amount, balance, description, timestamp = record
                record_time = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
                record_time_shanghai = record_time.astimezone(shanghai_tz)
                if (record_time_shanghai >= query_start_time and
                        "签到收益" in description and "鸡腿" in description):
                    signin_records.append({
                        'amount': amount,
                        'date': record_time_shanghai.strftime('%Y-%m-%d'),
                        'description': description,
                    })

            period_desc = "今天" if days == 1 else f"近{days}天"
            if not signin_records:
                return {
                    'total_amount': 0, 'average': 0, 'days_count': 0,
                    'records': [], 'period': period_desc,
                }, f"查询成功，但没有找到{period_desc}的签到记录"

            total_amount = sum(r['amount'] for r in signin_records)
            days_count = len(signin_records)
            average = round(total_amount / days_count, 2) if days_count > 0 else 0
            return {
                'total_amount': total_amount, 'average': average, 'days_count': days_count,
                'records': signin_records, 'period': period_desc,
            }, "查询成功"
        except Exception as e:
            return None, f"查询异常: {e}"

    # ---------------- 账号解析 ----------------
    def __parse_cookies(self) -> List[str]:
        """解析 Cookie 字符串：支持 & 与换行分隔。"""
        raw = (self._cookie or "").replace("\r", "\n")
        parts = []
        for chunk in raw.split("\n"):
            for c in chunk.split("&"):
                c = c.strip()
                if c:
                    parts.append(c)
        return parts

    def __parse_accounts(self) -> List[Dict[str, str]]:
        """解析账密：每行一个，支持 用户名----密码 / 用户名,密码 / 用户名:密码。"""
        accounts = []
        for line in (self._accounts or "").splitlines():
            line = line.strip()
            if not line:
                continue
            user = password = None
            for sep in ["----", ",", "，", ":", "：", "|", "\t"]:
                if sep in line:
                    user, password = line.split(sep, 1)
                    break
            if user is not None and password is not None:
                user, password = user.strip(), password.strip()
                if user and password:
                    accounts.append({"user": user, "password": password})
        return accounts

    # ---------------- 主签到流程 ----------------
    def signin(self):
        """执行 NodeSeek 签到主流程。"""
        if not self._cookie and not self._accounts:
            logger.warning("未配置 Cookie 或账密，跳过签到")
            return

        accounts = self.__parse_accounts()
        cookie_list = self.__parse_cookies()
        logger.info(f"共发现 {len(accounts)} 个账密配置，{len(cookie_list)} 个现有Cookie")

        # 仅有 Cookie、无账密时，为每个 Cookie 补一个空账密占位
        if len(accounts) == 0 and len(cookie_list) > 0:
            accounts = [{"user": "", "password": ""} for _ in cookie_list]

        max_count = max(len(accounts), len(cookie_list))
        while len(accounts) < max_count:
            accounts.append({"user": "", "password": ""})
        while len(cookie_list) < max_count:
            cookie_list.append("")

        cookies_updated = False
        notify_lines = []
        history_items = []

        for i in range(max_count):
            account_index = i + 1
            user = accounts[i]["user"]
            password = accounts[i]["password"]
            cookie = cookie_list[i]
            display_user = user if user else f"账号{account_index}"
            logger.info(f"==== 账号 {display_user} 开始签到 ====")

            stats = None
            if cookie:
                result, msg = self.__sign(cookie)
            else:
                result, msg = "invalid", "无Cookie"

            used_cookie = cookie
            if result in ["success", "already"]:
                logger.info(f"账号 {display_user} 签到成功: {msg}")
            elif user and password:
                if self._use_browser_login:
                    logger.info(f"账号 {display_user} 使用浏览器仿真登录并签到...")
                    result, msg, stats = self.__browser_signin(user, password)
                    if result in ["success", "already"]:
                        logger.info(f"账号 {display_user} 签到成功: {msg}")
                    else:
                        logger.error(f"账号 {display_user} 浏览器签到失败: {msg}")
                else:
                    logger.info(f"账号 {display_user} Cookie 签到失败({msg})，尝试 curl 重新登录...")
                    new_cookie, login_reason = self.__session_login(user, password)
                    if new_cookie:
                        logger.info("登录成功，使用新Cookie重新签到...")
                        result, msg = self.__sign(new_cookie)
                        if result in ["success", "already"]:
                            cookie_list[i] = new_cookie
                            used_cookie = new_cookie
                            cookies_updated = True
                            logger.info(f"账号 {display_user} 签到成功: {msg}")
                        else:
                            logger.error(f"账号 {display_user} 重新签到仍然失败: {msg}")
                    else:
                        logger.error(f"账号 {display_user} 登录失败：{login_reason}")
                        result, msg = "loginfail", f"登录失败：{login_reason}"
            else:
                logger.error(f"账号 {display_user} 签到失败且未配置账密: {msg}")

            # 收益统计（浏览器路径已带回 stats；cookie 路径在此查询）
            if stats is None and result in ["success", "already"] and used_cookie:
                stats, stats_msg = self.__get_signin_stats(used_cookie, self._stats_days)
                if not stats:
                    logger.warning(f"统计查询失败: {stats_msg}")

            # 汇总通知文本
            status_emoji = "✅" if result in ["success", "already"] else "❌"
            line = f"{status_emoji} {display_user}：{msg}"
            if stats and stats.get("days_count"):
                line += (f"\n   └ {stats['period']}签到{stats['days_count']}天，"
                         f"共{stats['total_amount']}鸡腿，均{stats['average']}/天")
            notify_lines.append(line)

            history_items.append({
                "date": datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                "account": display_user,
                "result": result,
                "message": msg,
                "total_amount": (stats or {}).get("total_amount", 0),
                "days_count": (stats or {}).get("days_count", 0),
            })

        # 回写刷新后的 Cookie
        if cookies_updated and self._auto_save_cookie:
            new_cookie_str = "\n".join([c for c in cookie_list if c.strip()])
            if new_cookie_str != self._cookie:
                self._cookie = new_cookie_str
                self.__update_config()
                logger.info("已将刷新后的 Cookie 写回插件配置")

        # 保存历史
        self.__save_history(history_items)

        # 发送通知
        if self._notify and notify_lines:
            self.post_message(
                mtype=NotificationType.SiteMessage,
                title="【NodeSeek 签到】",
                text="━━━━━━━━━━━━━━\n" + "\n".join(notify_lines) +
                     "\n━━━━━━━━━━━━━━\n"
                     f"🕐 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            )

    def __save_history(self, items: List[dict]):
        """保存签到历史并清理过期记录。"""
        if not items:
            return
        history = self.get_data('history') or []
        if not isinstance(history, list):
            history = [history]
        history.extend(items)

        retain_seconds = int(self._history_days or 30) * 24 * 60 * 60
        expired_timestamp = time.time() - retain_seconds
        cleaned = []
        for record in history:
            try:
                if datetime.strptime(record["date"], '%Y-%m-%d %H:%M:%S').timestamp() >= expired_timestamp:
                    cleaned.append(record)
            except Exception:
                logger.debug(f"忽略格式异常的签到历史记录: {record}")
        self.save_data(key="history", value=cleaned)

    # ---------------- MoviePilot 接口 ----------------
    def get_state(self) -> bool:
        return self._enabled

    @staticmethod
    def get_command() -> List[Dict[str, Any]]:
        pass

    def get_api(self) -> List[Dict[str, Any]]:
        pass

    def get_service(self) -> List[Dict[str, Any]]:
        """注册定时签到服务。"""
        if self._enabled and self._cron:
            return [{
                "id": "NodeSeekSignin",
                "name": "NodeSeek签到服务",
                "trigger": CronTrigger.from_crontab(self._cron),
                "func": self.signin,
                "kwargs": {},
            }]
        return []

    def get_form(self) -> Tuple[List[dict], Dict[str, Any]]:
        """拼装插件配置页面：返回 (页面配置, 默认数据结构)。"""
        version = getattr(settings, "VERSION_FLAG", "v1")
        cron_field_component = "VCronField" if version == "v2" else "VTextField"
        return [
            {
                'component': 'VForm',
                'content': [
                    # 基础设置
                    {
                        'component': 'VCard',
                        'props': {'class': 'mt-0'},
                        'content': [
                            {'component': 'VCardTitle', 'props': {'class': 'd-flex align-center'}, 'content': [
                                {'component': 'VIcon', 'props': {'color': 'info', 'class': 'mr-2'}, 'text': 'mdi-cog'},
                                {'component': 'span', 'text': '基础设置'}
                            ]},
                            {'component': 'VDivider'},
                            {'component': 'VCardText', 'content': [
                                {'component': 'VRow', 'content': [
                                    {'component': 'VCol', 'props': {'cols': 12, 'md': 3}, 'content': [
                                        {'component': 'VSwitch', 'props': {'model': 'enabled', 'label': '启用插件', 'color': 'primary'}}]},
                                    {'component': 'VCol', 'props': {'cols': 12, 'md': 3}, 'content': [
                                        {'component': 'VSwitch', 'props': {'model': 'notify', 'label': '开启通知', 'color': 'info'}}]},
                                    {'component': 'VCol', 'props': {'cols': 12, 'md': 3}, 'content': [
                                        {'component': 'VSwitch', 'props': {'model': 'onlyonce', 'label': '立即运行一次', 'color': 'success'}}]},
                                    {'component': 'VCol', 'props': {'cols': 12, 'md': 3}, 'content': [
                                        {'component': 'VSwitch', 'props': {'model': 'ns_random', 'label': '随机签到', 'color': 'warning'}}]},
                                ]},
                                {'component': 'VRow', 'content': [
                                    {'component': 'VCol', 'props': {'cols': 12, 'md': 3}, 'content': [
                                        {'component': 'VSwitch', 'props': {'model': 'use_proxy', 'label': '使用系统代理', 'color': 'warning'}}]},
                                    {'component': 'VCol', 'props': {'cols': 12, 'md': 3}, 'content': [
                                        {'component': 'VSwitch', 'props': {'model': 'auto_save_cookie', 'label': '回写刷新Cookie', 'color': 'success'}}]},
                                    {'component': 'VCol', 'props': {'cols': 12, 'md': 3}, 'content': [
                                        {'component': 'VSwitch', 'props': {'model': 'use_browser_login', 'label': '浏览器登录(CloakBrowser)', 'color': 'primary'}}]},
                                    {'component': 'VCol', 'props': {'cols': 12, 'md': 3}, 'content': [
                                        {'component': cron_field_component, 'props': {
                                            'model': 'cron', 'label': '签到周期', 'placeholder': '0 8 * * *',
                                            'prepend-inner-icon': 'mdi-clock-outline'}}]},
                                    {'component': 'VCol', 'props': {'cols': 12, 'md': 3}, 'content': [
                                        {'component': 'VTextField', 'props': {
                                            'model': 'stats_days', 'label': '收益统计周期(天)', 'type': 'number',
                                            'placeholder': '30', 'prepend-inner-icon': 'mdi-chart-line'}}]},
                                ]},
                            ]}
                        ]
                    },
                    # 账号设置
                    {
                        'component': 'VCard',
                        'props': {'class': 'mt-3'},
                        'content': [
                            {'component': 'VCardTitle', 'props': {'class': 'd-flex align-center'}, 'content': [
                                {'component': 'VIcon', 'props': {'color': 'info', 'class': 'mr-2'}, 'text': 'mdi-account-key'},
                                {'component': 'span', 'text': '账号设置'}
                            ]},
                            {'component': 'VDivider'},
                            {'component': 'VCardText', 'content': [
                                {'component': 'VRow', 'content': [
                                    {'component': 'VCol', 'props': {'cols': 12}, 'content': [
                                        {'component': 'VTextarea', 'props': {
                                            'model': 'cookie', 'label': 'NS_COOKIE',
                                            'placeholder': '论坛 Cookie，多账号用 & 或换行分隔',
                                            'prepend-inner-icon': 'mdi-cookie', 'rows': 3,
                                            'persistent-placeholder': True, 'clearable': True}}]},
                                ]},
                                {'component': 'VRow', 'content': [
                                    {'component': 'VCol', 'props': {'cols': 12}, 'content': [
                                        {'component': 'VTextarea', 'props': {
                                            'model': 'accounts', 'label': '账号密码（可选，用于Cookie失效时重新登录）',
                                            'placeholder': '每行一个账号，格式：用户名----密码（顺序与 Cookie 一一对应）',
                                            'prepend-inner-icon': 'mdi-account', 'rows': 2,
                                            'persistent-placeholder': True, 'clearable': True}}]},
                                ]},
                            ]}
                        ]
                    },
                    # 验证码设置
                    {
                        'component': 'VCard',
                        'props': {'class': 'mt-3'},
                        'content': [
                            {'component': 'VCardTitle', 'props': {'class': 'd-flex align-center'}, 'content': [
                                {'component': 'VIcon', 'props': {'color': 'info', 'class': 'mr-2'}, 'text': 'mdi-shield-key'},
                                {'component': 'span', 'text': '验证码 / 指纹设置（账密登录时需要）'}
                            ]},
                            {'component': 'VDivider'},
                            {'component': 'VCardText', 'content': [
                                {'component': 'VRow', 'content': [
                                    {'component': 'VCol', 'props': {'cols': 12, 'md': 4}, 'content': [
                                        {'component': 'VSelect', 'props': {
                                            'model': 'solver_type', 'label': '验证码服务',
                                            'prepend-inner-icon': 'mdi-puzzle',
                                            'items': [
                                                {'title': 'TurnstileSolver（CloudFreed 自建/免费）', 'value': 'turnstile'},
                                                {'title': 'YesCaptcha（商业）', 'value': 'yescaptcha'},
                                            ]}}]},
                                    {'component': 'VCol', 'props': {'cols': 12, 'md': 4}, 'content': [
                                        {'component': 'VTextField', 'props': {
                                            'model': 'api_base_url', 'label': 'API_BASE_URL',
                                            'placeholder': 'CloudFreed 地址，YesCaptcha 可留空',
                                            'prepend-inner-icon': 'mdi-link', 'clearable': True}}]},
                                    {'component': 'VCol', 'props': {'cols': 12, 'md': 4}, 'content': [
                                        {'component': 'VTextField', 'props': {
                                            'model': 'client_key', 'label': 'CLIENTT_KEY（验证码密钥）',
                                            'placeholder': '验证码服务 client key',
                                            'prepend-inner-icon': 'mdi-key', 'type': 'password',
                                            'autocomplete': 'new-password', 'clearable': True}}]},
                                ]},
                                {'component': 'VRow', 'content': [
                                    {'component': 'VCol', 'props': {'cols': 12, 'md': 4}, 'content': [
                                        {'component': 'VTextField', 'props': {
                                            'model': 'impersonate', 'label': 'NS_IMPERSONATE（首选指纹）',
                                            'placeholder': 'chrome110',
                                            'prepend-inner-icon': 'mdi-fingerprint', 'clearable': True}}]},
                                    {'component': 'VCol', 'props': {'cols': 12, 'md': 4}, 'content': [
                                        {'component': 'VTextField', 'props': {
                                            'model': 'history_days', 'label': '历史记录保留天数', 'type': 'number',
                                            'placeholder': '30', 'prepend-inner-icon': 'mdi-calendar-range'}}]},
                                ]},
                            ]}
                        ]
                    },
                    # 使用说明
                    {
                        'component': 'VCard',
                        'props': {'class': 'mt-3'},
                        'content': [
                            {'component': 'VCardTitle', 'props': {'class': 'd-flex align-center'}, 'content': [
                                {'component': 'VIcon', 'props': {'color': 'info', 'class': 'mr-2'}, 'text': 'mdi-information'},
                                {'component': 'span', 'text': '使用说明'}
                            ]},
                            {'component': 'VDivider'},
                            {'component': 'VCardText', 'content': [
                                {'component': 'VAlert', 'props': {
                                    'type': 'info', 'variant': 'tonal', 'class': 'mb-2',
                                    'text': '推荐填写 Cookie 签到（在浏览器登录 nodeseek.com 后复制 Cookie）。多账号 Cookie 用 & 或换行分隔。'}},
                                {'component': 'VAlert', 'props': {
                                    'type': 'warning', 'variant': 'tonal', 'class': 'mb-2',
                                    'text': 'Cookie 失效时，若同时配置了对应的「账号密码」，会自动通过验证码服务登录获取新 Cookie 并回写。账密顺序需与 Cookie 一一对应。'}},
                                {'component': 'VAlert', 'props': {
                                    'type': 'success', 'variant': 'tonal', 'class': 'mb-2',
                                    'text': '账密登录需配置验证码服务：TurnstileSolver 需自建 CloudFreed 并填写 API_BASE_URL；YesCaptcha 为商业服务，填写 CLIENTT_KEY 即可。'}},
                                {'component': 'VAlert', 'props': {
                                    'type': 'error', 'variant': 'tonal',
                                    'text': '账密自动签到请开启「浏览器登录(CloakBrowser)」：NodeSeek 新版鉴权改为 HTTP 头(x-security-token + 浏览器指纹算出的 x-integrity-token)，只能用 MoviePilot 内置真实浏览器登录并签到（仍需配置验证码服务）。需 MP 已准备好浏览器仿真环境。'}},
                            ]}
                        ]
                    }
                ]
            }
        ], {
            "enabled": False,
            "onlyonce": False,
            "notify": True,
            "ns_random": True,
            "use_proxy": False,
            "auto_save_cookie": True,
            "use_browser_login": True,
            "cron": "0 8 * * *",
            "cookie": "",
            "accounts": "",
            "solver_type": "turnstile",
            "api_base_url": "",
            "client_key": "",
            "impersonate": "chrome110",
            "stats_days": 30,
            "history_days": 30,
        }

    def get_page(self) -> List[dict]:
        """签到历史记录页面。"""
        historys = self.get_data('history')
        if not historys:
            return [
                {
                    'component': 'VCard',
                    'props': {'variant': 'flat', 'class': 'mb-4'},
                    'content': [
                        {'component': 'VCardItem', 'props': {'class': 'pa-6'}, 'content': [
                            {'component': 'VCardTitle', 'props': {'class': 'd-flex align-center text-h6'}, 'content': [
                                {'component': 'VIcon', 'props': {'color': 'primary', 'class': 'mr-3'}, 'text': 'mdi-database-remove'},
                                {'component': 'span', 'text': '暂无签到记录'}
                            ]}
                        ]}
                    ]
                }
            ]
        if not isinstance(historys, list):
            historys = [historys]
        historys = sorted(historys, key=lambda x: x.get("date") or "", reverse=True)

        rows = []
        for h in historys:
            success = h.get("result") in ["success", "already"]
            rows.append({
                'component': 'tr',
                'content': [
                    {'component': 'td', 'text': h.get("date", "")},
                    {'component': 'td', 'text': h.get("account", "")},
                    {'component': 'td', 'content': [
                        {'component': 'VChip', 'props': {
                            'color': 'success' if success else 'error', 'size': 'small', 'variant': 'tonal'},
                         'text': '成功' if success else '失败'}
                    ]},
                    {'component': 'td', 'text': str(h.get("message", ""))},
                    {'component': 'td', 'text': str(h.get("total_amount", 0))},
                    {'component': 'td', 'text': str(h.get("days_count", 0))},
                ]
            })

        return [
            {
                'component': 'VCard',
                'props': {'variant': 'flat', 'class': 'mb-4'},
                'content': [
                    {'component': 'VCardItem', 'props': {'class': 'pa-4'}, 'content': [
                        {'component': 'VCardTitle', 'props': {'class': 'd-flex align-center text-h6'}, 'content': [
                            {'component': 'VIcon', 'props': {'color': 'primary', 'class': 'mr-3'}, 'text': 'mdi-history'},
                            {'component': 'span', 'text': '签到历史记录'}
                        ]}
                    ]},
                    {'component': 'VCardText', 'content': [
                        {'component': 'VTable', 'props': {'hover': True}, 'content': [
                            {'component': 'thead', 'content': [
                                {'component': 'tr', 'content': [
                                    {'component': 'th', 'props': {'class': 'text-start'}, 'text': '时间'},
                                    {'component': 'th', 'props': {'class': 'text-start'}, 'text': '账号'},
                                    {'component': 'th', 'props': {'class': 'text-start'}, 'text': '状态'},
                                    {'component': 'th', 'props': {'class': 'text-start'}, 'text': '消息'},
                                    {'component': 'th', 'props': {'class': 'text-start'}, 'text': f'近{self._stats_days}天鸡腿'},
                                    {'component': 'th', 'props': {'class': 'text-start'}, 'text': '签到天数'},
                                ]}
                            ]},
                            {'component': 'tbody', 'content': rows}
                        ]}
                    ]}
                ]
            }
        ]

    def stop_service(self):
        """退出插件。"""
        try:
            if self._scheduler:
                self._scheduler.remove_all_jobs()
                if self._scheduler.running:
                    self._scheduler.shutdown()
                self._scheduler = None
        except Exception as e:
            logger.error("退出插件失败：%s" % str(e))
