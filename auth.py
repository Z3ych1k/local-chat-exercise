"""Official Sign in with ChatGPT: public-client PKCE, verified identity, refresh.

Credentials stay on the server. This app never reads Codex's credential files.
"""
import base64
import hashlib
import json
import os
from pathlib import Path
import secrets
import ssl
import threading
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from uuid import uuid4

import jwt
import truststore

ISSUER = "https://auth.openai.com"
RESOURCE = "https://api.openai.com/v1"
AUTHORIZE = ISSUER + "/api/accounts/authorize"
TOKEN = ISSUER + "/api/accounts/oauth/token"
SCOPES = "openid profile email offline_access resource.invoke chatgpt.tokens.use.direct"


def private_write(path, value):
    """Replace a secret atomically; temporary and final files are owner-only."""
    path = Path(path)
    temp = path.with_name(path.name + "." + secrets.token_hex(8) + ".tmp")
    try:
        with os.fdopen(os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w") as file:
            json.dump(value, file)
            file.flush()
            os.fsync(file.fileno())
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def request_json(url, form=None, token=None):
    headers = {"Accept": "application/json"}
    if token:
        headers["Authorization"] = "Bearer " + token
    body = None
    if form is not None:
        body = urlencode(form).encode()
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    try:
        with urlopen(Request(url, body, headers), timeout=30,
                     context=truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)) as response:
            raw = response.read()
            return json.loads(raw) if raw else {}
    except HTTPError as error:
        # Never include OAuth response bodies, URLs or credentials in errors.
        raise RuntimeError(f"OpenAI 連線失敗（HTTP {error.code}），請重新登入或稍後再試。") from None
    except (URLError, TimeoutError):
        raise RuntimeError("未能連接 OpenAI，請檢查網絡後再試。") from None


class ChatGPTLogin:
    def __init__(self, directory, base_url):
        self.path = Path(directory) / "credentials.json"
        self.host_path = Path(directory) / "host.json"
        self.callback = base_url + "/auth/callback"
        self.lock = threading.RLock()
        self.pending = {}
        self.catalog = {}
        if not self.host_path.exists():
            private_write(self.host_path, {"host_id": "urn:uuid:" + str(uuid4())})
        self.host_id = json.loads(self.host_path.read_text())["host_id"]
        self.jwks = jwt.PyJWKClient(ISSUER + "/.well-known/jwks.json", timeout=30,
                                  ssl_context=truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT))

    def load(self):
        if not self.path.exists():
            return {"active": None, "accounts": {}}
        return json.loads(self.path.read_text())

    def status(self):
        with self.lock:
            saved = self.load()
            active = saved["accounts"].get(saved["active"], {})
            return {"active": saved["active"], "connected": bool(active.get("access_token")),
                    "accounts": [{"id": key, "label": account.get("email") or account["subject"],
                                  "client": account["client_id"][-8:],
                                  "connected": bool(account.get("access_token"))}
                                 for key, account in saved["accounts"].items()]}

    def start(self, browser_id, account_id=None, include_hints=True):
        with self.lock:
            saved = self.load()
            selected = saved["accounts"].get(account_id)
            if account_id and not selected:
                raise ValueError("找不到這個帳號。")
            now = time.time()
            self.pending = {key: value for key, value in self.pending.items() if value["expiry"] > now}
            verifier = secrets.token_urlsafe(64)
            attempt = {"state": secrets.token_urlsafe(32), "nonce": secrets.token_urlsafe(32),
                       "verifier": verifier, "expiry": now + 600,
                       "client_id": selected["client_id"] if selected else "dynamic_agent_client",
                       "subject": selected["subject"] if selected else None}
            self.pending[browser_id] = attempt
            params = {"client_id": attempt["client_id"], "ext_agent_host_id": self.host_id,
                      "response_type": "code", "redirect_uri": self.callback,
                      "scope": SCOPES, "resource": RESOURCE, "state": attempt["state"],
                      "nonce": attempt["nonce"], "code_challenge_method": "S256",
                      "code_challenge": base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")}
            if selected:
                if include_hints and selected.get("id_token"):
                    params["id_token_hint"] = selected["id_token"]
                if include_hints and selected.get("email"):
                    params["login_hint"] = selected["email"]
            else:
                params["agent_name_hint"] = "Local Chat Exercise"
            return AUTHORIZE + "?" + urlencode(params)

    def validate_identity(self, tokens, client_id, nonce=None, subject=None):
        raw = tokens.get("id_token")
        if not raw:
            raise ValueError("OpenAI 未傳回身份憑證，請重新登入。")
        key = self.jwks.get_signing_key_from_jwt(raw).key
        identity = jwt.decode(raw, key, algorithms=["RS256", "ES256"], audience=client_id,
                              issuer=ISSUER, leeway=5, options={"require": ["sub", "exp", "iat"]})
        if not isinstance(identity["sub"], str) or not identity["sub"]:
            raise ValueError("帳號身份驗證失敗。")
        if nonce is not None and identity.get("nonce") != nonce:
            raise ValueError("登入 nonce 驗證失敗，請重新登入。")
        if subject is not None and identity["sub"] != subject:
            raise ValueError("登入帳號不符合原本的帳號，原有設定已保留。")
        return identity

    def finish(self, browser_id, query):
        with self.lock:
            attempt = self.pending.pop(browser_id, None)
            state = query.get("state", "")
            if not attempt or attempt["expiry"] < time.time() or not secrets.compare_digest(state, attempt["state"]):
                raise ValueError("登入已過期或 state 不符，請重新登入。")
            if query.get("error"):
                raise ValueError("登入未完成或未獲授權；請重新登入並允許使用 ChatGPT 方案。")
            client_id = query.get("client_id") or attempt["client_id"]
            if client_id == "dynamic_agent_client" or not query.get("code"):
                raise ValueError("OpenAI 未完成程式註冊，請重新登入。")
            if attempt["subject"] and client_id != attempt["client_id"]:
                raise ValueError("OpenAI 傳回的 client ID 不符。")
            tokens = request_json(TOKEN, {"grant_type": "authorization_code", "client_id": client_id,
                                         "code": query["code"], "code_verifier": attempt["verifier"],
                                         "redirect_uri": self.callback, "resource": RESOURCE})
            identity = self.validate_identity(tokens, client_id, attempt["nonce"], attempt["subject"])
            record = {"client_id": client_id, "subject": identity["sub"], "email": identity.get("email", "")}
            self.update_tokens(record, tokens)
            key = hashlib.sha256((client_id + ":" + identity["sub"]).encode()).hexdigest()[:24]
            saved = self.load()
            saved["accounts"][key] = record
            saved["active"] = key
            private_write(self.path, saved)
            self.catalog.clear()

    @staticmethod
    def update_tokens(record, tokens):
        scopes = tokens.get("scope", " ".join(record.get("scopes", []))).split()
        if "chatgpt.tokens.use.direct" not in scopes or "resource.invoke" not in scopes:
            raise ValueError("未授權使用 ChatGPT 方案額度；請重新登入並允許使用方案。")
        if not tokens.get("access_token") or tokens.get("token_type", "").lower() != "bearer":
            raise ValueError("OpenAI 傳回的 API 憑證不完整。")
        for field in ["access_token", "refresh_token", "id_token"]:
            if tokens.get(field):
                record[field] = tokens[field]
        record.update(scopes=scopes, expires_at=time.time() + int(tokens["expires_in"]))

    def access(self, account_id):
        with self.lock:
            saved = self.load()
            record = saved["accounts"].get(account_id, {})
            if not record.get("access_token"):
                raise ValueError("請由擁有人完成伺服器授權。")
            if record["expires_at"] <= time.time() + 60:
                if not record.get("refresh_token"):
                    raise ValueError("伺服器授權已過期，請由擁有人重新授權。")
                tokens = request_json(TOKEN, {"grant_type": "refresh_token", "client_id": record["client_id"],
                                             "refresh_token": record["refresh_token"], "resource": RESOURCE})
                if tokens.get("id_token"):
                    self.validate_identity(tokens, record["client_id"], subject=record["subject"])
                self.update_tokens(record, tokens)
                private_write(self.path, saved)
            return record["access_token"]

    def models(self, account_id):
        token = self.access(account_id)
        with self.lock:
            cached = self.catalog.get(account_id)
            if cached and cached[0] > time.time():
                return cached[1]
            payload = request_json(RESOURCE + "/models", token=token)
            choices = [{"id": item["slug"], "name": item.get("display_name", item["slug"])}
                       for item in payload.get("models", []) if item.get("visibility") == "list"]
            if not choices:
                raise ValueError("這個帳號沒有可用模型，請檢查方案及應用程式授權。")
            self.catalog[account_id] = (time.time() + 300, choices)
            return choices

    def select(self, account_id):
        with self.lock:
            saved = self.load()
            if account_id not in saved["accounts"]:
                raise ValueError("找不到這個帳號。")
            saved["active"] = account_id
            private_write(self.path, saved)

    def logout(self, account_id):
        with self.lock:
            saved = self.load()
            record = saved["accounts"].get(account_id)
            if not record:
                raise ValueError("找不到這個帳號。")
            confirmed = not record.get("refresh_token")
            try:
                if record.get("refresh_token"):
                    discovery = request_json(ISSUER + "/.well-known/openid-configuration")
                    endpoint = discovery["revocation_endpoint"]
                    if not endpoint.startswith(ISSUER + "/"):
                        raise ValueError("Unexpected revocation endpoint")
                    request_json(endpoint, {"token": record["refresh_token"], "token_type_hint": "refresh_token",
                                            "client_id": record["client_id"]})
                    confirmed = True
            except (RuntimeError, KeyError, ValueError):
                confirmed = False
            for field in ["access_token", "refresh_token", "id_token", "expires_at"]:
                record.pop(field, None)
            private_write(self.path, saved)
            self.catalog.pop(account_id, None)
            return confirmed
