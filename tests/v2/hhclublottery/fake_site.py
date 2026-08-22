# -*- coding: utf-8 -*-
"""本地假站点：把 hhanclub 的 lucky.php / lucky-draw / usercp / userdetails /
messages 这几个接口原样立起来，抽奖逻辑和插件外壳都拿它真跑一遍。"""
import json
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


# ============================================================
# 假站点
# ============================================================

LUCKY_HTML = """<html><body>
<div class="lottery-info">当中奖 [VIP] 时，如果用户已经是 VIP 或以上等级，奖励憨豆： 1000000</div>
<span class="bean-number font-bold">{balance}</span>
<div>单次消耗 <span class="use-bean">{cost}</span> 憨豆</div>
</body></html>"""

LOGIN_HTML = '<html><body><form action="takelogin.php"><input name="password"></form></body></html>'


class FakeSite:
    def __init__(self):
        self.balance = 1574093
        self.cost = 2000
        self.draw_queue = []
        self.cookie_valid = True
        self.mail_pages = []          # [[{id, subject}, ...], ...]
        self.deleted = []
        self.user_class = "VIP"       # {Class}_Name
        self.usercp_ok = True
        self.draw_calls = 0
        self.lucky_calls = 0
        self.lock = threading.Lock()

    def next_draw(self):
        with self.lock:
            self.draw_calls += 1
            if not self.draw_queue:
                return {"ret": 1, "msg": "抽奖次数已用完"}
            return self.draw_queue.pop(0)


class Handler(BaseHTTPRequestHandler):
    site: FakeSite = None

    def log_message(self, *args):
        pass

    def _send(self, body, status=200, ctype="text/html; charset=utf-8"):
        payload = body.encode("utf-8") if isinstance(body, str) else body
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self):
        site = Handler.site
        path = urllib.parse.urlparse(self.path)
        if not site.cookie_valid:
            return self._send(LOGIN_HTML)

        if path.path == "/lucky.php":
            with site.lock:
                site.lucky_calls += 1
                balance, cost = site.balance, site.cost
            return self._send(LUCKY_HTML.format(balance=f"{balance:,}", cost=f"{cost:,}"))

        if path.path == "/usercp.php":
            if not site.usercp_ok:
                return self._send("<html><body>控制面板</body></html>")
            return self._send('<html><body>'
                              '<a href="messages.php">站内信</a>'
                              '<a href="userdetails.php?id=9527" class="User_Name"><b>我自己</b></a>'
                              '<a href="userdetails.php?id=111">别人</a>'
                              '</body></html>')

        if path.path == "/userdetails.php":
            cls = site.user_class
            if cls is None:
                return self._send("<html><body>等级：神秘</body></html>")
            return self._send(f"<html><body>等级：<img src='pic/{cls.lower()}.gif'>"
                              f"<span class='{cls}_Name font-bold'>俺不中类</span></body></html>")

        if path.path == "/messages.php":
            query = urllib.parse.parse_qs(path.query)
            page = int((query.get("page") or ["0"])[0])
            pages = site.mail_pages
            items = pages[page] if page < len(pages) else []
            rows = "".join(
                f'<tr><td><a href="messages.php?action=viewmessage&amp;id={m["id"]}">'
                f'<b>{m["subject"]}</b></a></td></tr>' for m in items)
            options = "".join(f"<option value='{i}'>{i + 1}</option>" for i in range(len(pages)))
            select = f"<select onchange='switchPage(this)'>{options}</select>" if pages else ""
            return self._send(f"<html><body>{select}<table>{rows}</table></body></html>")

        return self._send("not found", 404)

    def do_POST(self):
        site = Handler.site
        path = urllib.parse.urlparse(self.path)
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length).decode("utf-8") if length else ""

        if not site.cookie_valid:
            return self._send(LOGIN_HTML)

        if path.path == "/plugin/lucky-draw":
            result = site.next_draw()
            if result.get("ret") == 0:
                with site.lock:
                    site.balance -= site.cost
                    site.balance += result.pop("_credit", 0)
            return self._send(json.dumps(result, ensure_ascii=False),
                              ctype="application/json; charset=utf-8")

        if path.path == "/messages.php":
            ids = urllib.parse.parse_qs(body).get("messages[]") or []
            with site.lock:
                site.deleted.extend(ids)
                site.mail_pages = [[m for m in page if m["id"] not in ids]
                                   for page in site.mail_pages]
                site.mail_pages = [p for p in site.mail_pages if p] or []
            return self._send("<html><body>删除成功</body></html>")

        return self._send("not found", 404)


def stop_site(server):
    server.shutdown()
    server.server_close()


def start_site(site: FakeSite):
    Handler.site = site
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, f"http://127.0.0.1:{server.server_address[1]}"


def win(prize_text, duration=4000, credit=0):
    """一次中奖响应。credit 是这一抽站点实际入账的憨豆（模拟 VIP 折算等）。"""
    return {"ret": 0, "msg": "ok", "data": {"prize_text": prize_text, "duration": duration},
            "_credit": credit}
