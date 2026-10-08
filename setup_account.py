"""Owner-only setup in the container. Chat clients never need to sign in.

NAS: forward 127.0.0.1:1455 over SSH, run this script, open the printed URL
on the owner's computer. OAuth credentials are stored on the NAS itself.
"""
import os
from pathlib import Path
import secrets
import time
from urllib.parse import parse_qs
from wsgiref.simple_server import make_server, WSGIRequestHandler

import jwt
from auth import ChatGPTLogin


class QuietHandler(WSGIRequestHandler):
    def log_message(self, *args):
        pass  # Callback URLs contain authorization codes; do not log them.


def main():
    directory = Path(os.environ.get("DATA_DIR", Path(__file__).parent / "data"))
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    login = ChatGPTLogin(directory, "http://127.0.0.1:1455")
    browser_id = secrets.token_urlsafe(32)
    account = login.status()["active"]
    outcome = {"finished": False, "ok": False}

    def callback(environ, start_response):
        if environ["PATH_INFO"] != "/auth/callback":
            start_response("404 Not Found", [("Content-Type", "text/plain")])
            return [b"Not found"]
        query = {key: values[0] for key, values in parse_qs(environ["QUERY_STRING"]).items()}
        try:
            login.finish(browser_id, query)
            message = "伺服器授權已完成。所有客戶端現在可直接使用聊天介面；你可以關閉本頁。"
            outcome.update(finished=True, ok=True)
        except (ValueError, RuntimeError, jwt.PyJWTError, KeyError):
            message = "授權未完成。請回到伺服器終端重新執行設定，並確認帳號及應用程式有使用方案的權限。"
            outcome["finished"] = True
        start_response("200 OK", [("Content-Type", "text/html; charset=utf-8"),
                                  ("Cache-Control", "no-store"), ("Referrer-Policy", "no-referrer")])
        return [("<!doctype html><html lang='zh-Hant'><meta charset='utf-8'><title>Server setup</title><p>" + message + "</p></html>").encode()]

    bind = os.environ.get("SETUP_BIND", "127.0.0.1")
    with make_server(bind, 1455, callback, handler_class=QuietHandler) as server:
        server.timeout = 2
        # Omit token hints so no saved ID token is ever printed in the terminal.
        url = login.start(browser_id, account, include_hints=False)
        print("在擁有人電腦的瀏覽器開啟下列 OpenAI URL，完成一次伺服器授權：", flush=True)
        print(url, flush=True)
        print("等待回呼，10 分鐘後逾時。NAS 需要先建立 1455 的 SSH 轉發。", flush=True)
        deadline = time.time() + 600
        while not outcome["finished"] and time.time() < deadline:
            server.handle_request()
    if outcome["ok"]:
        print("已保存伺服器憑證；客戶端不需要登入。", flush=True)
    else:
        raise SystemExit("未完成授權；沒有啟用 API。")


if __name__ == "__main__":
    main()
