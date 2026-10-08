"""Modified from OpenAI's MIT-licensed examples/chat-basic/app.py.

Exercise: Responses API + browser GUI + local SQLite history + ChatGPT OAuth.
"""
import json
from contextlib import contextmanager
import os
from pathlib import Path
import secrets
import sqlite3
import threading
import time
from uuid import uuid4

from flask import Flask, Response, jsonify, render_template, request, session, stream_with_context
from openai import APIConnectionError, APIStatusError, OpenAI
import jwt

from auth import ChatGPTLogin, private_write

DEFAULT_INSTRUCTIONS = "請以繁體中文回答。協助我理解概念；涉及程式時，提供清楚易明的解釋。"


def create_app(data_dir=None):
    directory = Path(data_dir or os.environ.get("DATA_DIR", Path(__file__).parent / "data"))
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    mode = os.environ.get("AUTH_MODE", "api_key")
    if mode not in {"chatgpt", "api_key"}:
        raise ValueError("AUTH_MODE 必須是 chatgpt 或 api_key。")
    secret_path = directory / "session-secret.json"
    if not secret_path.exists():
        private_write(secret_path, secrets.token_hex(32))
    app = Flask(__name__)
    app.config.update(SECRET_KEY=json.loads(secret_path.read_text()), MAX_CONTENT_LENGTH=65536,
                      SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax",
                      SESSION_COOKIE_NAME="local_chat_session",
                      TRUSTED_HOSTS=os.environ.get("CHAT_HOSTS", "127.0.0.1,localhost").split(","))
    login = ChatGPTLogin(directory, "http://127.0.0.1:1455")
    app.extensions["chat_login"] = login
    db_path = directory / "chat.sqlite3"
    # ponytail: one process/one shared credential; queue requests if simultaneous use becomes necessary.
    inference_lock = threading.Lock()
    setup_lock = threading.Lock()

    @contextmanager
    def database():
        connection = sqlite3.connect(db_path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    with database() as db:
        db.executescript("""
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS chats (
                id TEXT PRIMARY KEY, owner TEXT NOT NULL, title TEXT NOT NULL,
                instructions TEXT NOT NULL, created_at INTEGER NOT NULL, updated_at INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY, chat_id TEXT NOT NULL REFERENCES chats(id) ON DELETE CASCADE,
                role TEXT NOT NULL, content TEXT NOT NULL, status TEXT NOT NULL,
                model TEXT, created_at INTEGER NOT NULL
            );
            UPDATE messages SET status='interrupted' WHERE status='pending';
        """)
    os.chmod(db_path, 0o600)

    def active_account():
        key = login.status()["active"]
        if not key:
            raise ValueError("伺服器尚未設定 ChatGPT 憑證，請由擁有人完成一次授權。")
        return key

    def api_key():
        path = Path(os.environ.get("OPENAI_API_KEY_FILE", directory / "api-key.json"))
        key = os.environ.get("OPENAI_API_KEY", "") or (json.loads(path.read_text()) if path.exists() else "")
        if not key:
            raise ValueError("伺服器尚未設定 OpenAI API Key，請由擁有人完成設定。")
        return key

    def credentials():
        return login.access(active_account()) if mode == "chatgpt" else api_key()

    def available_models():
        if mode == "chatgpt":
            return login.models(active_account())
        with OpenAI(api_key=api_key(), base_url="https://api.openai.com/v1", timeout=30, max_retries=0) as client:
            catalog = client.models.list()
        models = [{"id": item.id, "name": item.id} for item in catalog.data
                  if item.id.startswith(("gpt-", "o1", "o3", "o4"))
                  and not any(word in item.id for word in ["audio", "realtime", "transcribe", "tts", "image"])]
        if not models:
            raise ValueError("此 API Key 沒有可用的文字模型。")
        return sorted(models, key=lambda item: item["id"])

    def find_chat(db, chat_id, owner):
        row = db.execute("SELECT * FROM chats WHERE id=? AND owner=?", (chat_id, owner)).fetchone()
        if not row:
            raise ValueError("找不到這段對話。")
        return dict(row)

    @app.before_request
    def protect_local_requests():
        if request.method in {"POST", "PATCH", "DELETE"}:
            token = request.headers.get("X-CSRF-Token", "")
            expected = session.get("csrf", "")
            if not expected or not secrets.compare_digest(token, expected):
                return jsonify(error="頁面已過期，請重新整理後再試。"), 403
            if not isinstance(request.get_json(silent=True), dict):
                return jsonify(error="請傳送 JSON 格式的請求。"), 400

    @app.after_request
    def response_headers(response):
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
        return response

    @app.errorhandler(ValueError)
    @app.errorhandler(RuntimeError)
    def readable_error(error):
        return jsonify(error=str(error)), 400

    @app.errorhandler(413)
    def too_large(error):
        return jsonify(error="內容太長；每次問題上限為 16,000 個字。"), 413

    @app.errorhandler(jwt.PyJWTError)
    def identity_error(error):
        return jsonify(error="伺服器憑證驗證失敗，請由擁有人重新授權。"), 401

    @app.errorhandler(APIStatusError)
    def provider_error(error):
        return jsonify(error=f"OpenAI 未能完成請求（HTTP {error.status_code}）；請由擁有人檢查授權及額度。"), 502

    @app.errorhandler(APIConnectionError)
    def connection_error(error):
        return jsonify(error="伺服器未能連接 OpenAI，請稍後再試。"), 502

    @app.get("/")
    def index():
        session.setdefault("browser_id", secrets.token_urlsafe(32))
        session.setdefault("csrf", secrets.token_urlsafe(32))
        return render_template("index.html", csrf=session["csrf"])

    @app.get("/health")
    def health():
        return jsonify(ok=True)

    @app.get("/api/status")
    def status():
        try:
            if mode == "api_key":
                api_key()
                configured = True
            else:
                configured = login.status()["connected"]
        except ValueError:
            configured = False
        return jsonify(connected=configured, mode=mode, preferred_model=os.environ.get("OPENAI_MODEL", ""))

    @app.post("/api/setup")
    def setup():
        if mode != "api_key":
            raise ValueError("伺服器目前使用 ChatGPT 方案授權，由擁有人執行一次 setup_account.py。")
        with setup_lock:
            try:
                api_key()
            except ValueError:
                pass
            else:
                return jsonify(error="伺服器已設定憑證，不能從客戶端覆寫。"), 409
            key = request.get_json().get("api_key", "")
            if not isinstance(key, str) or not key.strip() or len(key) > 8192 or any(c.isspace() for c in key.strip()):
                raise ValueError("請輸入有效的 OpenAI API Key。")
            key = key.strip()
            # Check the key before saving it; a rejected key must not lock first-run setup.
            with OpenAI(api_key=key, base_url="https://api.openai.com/v1", timeout=30, max_retries=0) as client:
                client.models.list()
            path = Path(os.environ.get("OPENAI_API_KEY_FILE", directory / "api-key.json"))
            private_write(path, key)
        return jsonify(ok=True), 201

    @app.get("/api/models")
    def models():
        return jsonify(models=available_models())

    @app.route("/api/chats", methods=["GET", "POST"])
    def chats():
        owner = "shared-workspace"
        with database() as db:
            if request.method == "POST":
                key, now = uuid4().hex, int(time.time())
                db.execute("INSERT INTO chats VALUES (?,?,?,?,?,?)", (key, owner, "新對話", DEFAULT_INSTRUCTIONS, now, now))
                return jsonify(id=key), 201
            rows = db.execute("SELECT id,title,updated_at FROM chats WHERE owner=? ORDER BY updated_at DESC,rowid DESC", (owner,))
            return jsonify(chats=[dict(row) for row in rows])

    @app.route("/api/chats/<chat_id>", methods=["GET", "PATCH", "DELETE"])
    def chat_detail(chat_id):
        with database() as db:
            chat = find_chat(db, chat_id, "shared-workspace")
            if request.method == "DELETE":
                if inference_lock.locked():
                    return jsonify(error="請等回答完成後再刪除。"), 409
                db.execute("DELETE FROM chats WHERE id=?", (chat_id,))
                return jsonify(ok=True)
            if request.method == "PATCH":
                instructions = request.get_json().get("instructions", "")
                if not isinstance(instructions, str) or len(instructions) > 4000:
                    raise ValueError("回答指示上限為 4,000 個字。")
                db.execute("UPDATE chats SET instructions=? WHERE id=?", (instructions, chat_id))
                return jsonify(ok=True)
            chat["messages"] = [dict(row) for row in db.execute("SELECT * FROM messages WHERE chat_id=? ORDER BY id", (chat_id,))]
            chat.pop("owner")
            return jsonify(chat)

    @app.get("/api/chats/<chat_id>/export")
    def export_chat(chat_id):
        with database() as db:
            chat = find_chat(db, chat_id, "shared-workspace")
            chat.pop("owner")
            chat["messages"] = [dict(row) for row in db.execute("SELECT role,content,status,model,created_at FROM messages WHERE chat_id=? ORDER BY id", (chat_id,))]
        return Response(json.dumps(chat, ensure_ascii=False, indent=2), mimetype="application/json",
                        headers={"Content-Disposition": f'attachment; filename="chat-{chat_id}.json"'})

    @app.post("/api/chats/<chat_id>/messages")
    def send_message(chat_id):
        body = request.get_json()
        prompt, model = body.get("message"), body.get("model")
        if not isinstance(prompt, str) or not prompt.strip() or len(prompt) > 16000:
            raise ValueError("請輸入問題；每次上限為 16,000 個字。")
        owner = "shared-workspace"
        if model not in {item["id"] for item in available_models()}:
            raise ValueError("請選擇此帳號可用的模型。")
        token = credentials()
        if not inference_lock.acquire(blocking=False):
            return jsonify(error="上一個回答仍在進行，請稍後再試。"), 409
        try:
            with database() as db:
                chat = find_chat(db, chat_id, owner)
                history = [{"role": row["role"], "content": row["content"]} for row in
                           db.execute("SELECT role,content FROM messages WHERE chat_id=? AND status='complete' ORDER BY id", (chat_id,))]
                prompt = prompt.strip()
                history.append({"role": "user", "content": prompt})
                now = int(time.time())
                db.execute("INSERT INTO messages(chat_id,role,content,status,created_at) VALUES (?,?,?,?,?)", (chat_id, "user", prompt, "complete", now))
                cursor = db.execute("INSERT INTO messages(chat_id,role,content,status,model,created_at) VALUES (?,?,?,?,?,?)", (chat_id, "assistant", "", "pending", model, now))
                message_id = cursor.lastrowid
                title = prompt[:32] if chat["title"] == "新對話" else chat["title"]
                db.execute("UPDATE chats SET title=?,updated_at=? WHERE id=?", (title, now, chat_id))
        except BaseException:
            inference_lock.release()
            raise

        def event(name, **payload):
            return "data: " + json.dumps({"type": name, **payload}, ensure_ascii=False) + "\n\n"

        def generate():
            text, state = "", "interrupted"
            try:
                yield event("start", id=message_id)
                # Exercise core: official SDK + Responses API. OAuth preview requires
                # full local history, store=False and stream=True; no temperature/max_output_tokens.
                with OpenAI(api_key=token, base_url="https://api.openai.com/v1", timeout=90, max_retries=0) as client:
                    with client.responses.create(model=model, instructions=chat["instructions"],
                                                 input=history, store=False, stream=True) as stream:
                        for item in stream:
                            if item.type == "response.output_text.delta":
                                text += item.delta
                                yield event("delta", text=item.delta)
                            elif item.type == "response.completed":
                                state = "complete"
                            elif item.type in {"response.failed", "response.incomplete", "error"}:
                                state = "failed"
                                code = getattr(getattr(item, "error", None), "code", None)
                                if not code:
                                    code = getattr(getattr(getattr(item, "response", None), "error", None), "code", "unknown")
                                note = "方案額度不足或此應用程式未獲授權；請到 ChatGPT 設定查看。" if str(code).startswith("subscription_sharing_") else "OpenAI 未完成回答；可稍後重試。"
                                yield event("error", message=note)
                                break
                if state != "complete":
                    if state != "failed":
                        yield event("error", message="連線中斷，回答未完成；已保留問題及收到的文字。")
                else:
                    if not text:
                        state = "failed"
                        yield event("error", message="模型未傳回文字，請換另一個模型再試。")
            except APIStatusError as error:
                state = "failed"
                yield event("error", message=f"OpenAI API 未能完成請求（HTTP {error.status_code}）；請由擁有人檢查憑證、額度及模型權限。")
            except APIConnectionError:
                state = "failed"
                yield event("error", message="未能連接 OpenAI；已保留問題，請稍後重試。")
            except Exception:
                state = "failed"
                yield event("error", message="回答未完成；已保留問題及收到的文字。")
            finally:
                try:
                    with database() as db:
                        db.execute("UPDATE messages SET content=?,status=? WHERE id=?", (text, state, message_id))
                finally:
                    inference_lock.release()
            yield event("done", status=state)

        return Response(stream_with_context(generate()), mimetype="text/event-stream",
                        headers={"X-Accel-Buffering": "no"})

    return app


if __name__ == "__main__":
    create_app().run(host="127.0.0.1", port=8080, debug=False)
