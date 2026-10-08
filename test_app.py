"""Run: python -m unittest -v. All credentials and responses here are fake.

These checks do not establish live OpenAI access or account eligibility.
"""
import json
from contextlib import closing
import os
from pathlib import Path
import sqlite3
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

from cryptography.hazmat.primitives.asymmetric import rsa
import jwt

from app import create_app
from auth import ISSUER, SCOPES, private_write


class LocalChatChecks(unittest.TestCase):
    def setUp(self):
        self.mode_patch = patch.dict(os.environ, {"AUTH_MODE": "chatgpt"})
        self.mode_patch.start()
        self.addCleanup(self.mode_patch.stop)
        self.temp = tempfile.TemporaryDirectory()
        self.directory = Path(self.temp.name)
        self.app = create_app(self.directory)
        self.app.config.update(TESTING=True, SERVER_NAME="127.0.0.1:8080")
        self.browser = self.app.test_client()
        self.assertEqual(self.browser.get("/").status_code, 200)
        with self.browser.session_transaction() as session:
            self.headers = {"X-CSRF-Token": session["csrf"]}
        self.login = self.app.extensions["chat_login"]

    def tearDown(self):
        self.temp.cleanup()

    def seed_account(self):
        private_write(self.login.path, {"active": "account-a", "accounts": {
            "account-a": {"subject": "fake-subject-a", "client_id": "oaiapp_fake_a",
                          "email": "test-a@example.invalid", "access_token": "fake-test-token",
                          "refresh_token": "fake-refresh-token", "scopes": SCOPES.split(),
                          "expires_at": time.time() + 3600},
            "account-b": {"subject": "fake-subject-b", "client_id": "oaiapp_fake_b",
                          "email": "test-b@example.invalid", "access_token": "fake-test-token-b",
                          "scopes": SCOPES.split(), "expires_at": time.time() + 3600}
        }})

    def post(self, path, body):
        return self.browser.post(path, json=body, headers=self.headers)

    def new_chat(self):
        response = self.post("/api/chats", {})
        self.assertEqual(response.status_code, 201)
        return response.json["id"]

    def send_fake(self, chat_id, events):
        with patch.object(self.login, "models", return_value=[{"id": "fake-model", "name": "Test"}]), patch("app.OpenAI") as factory:
            client = factory.return_value.__enter__.return_value
            client.responses.create.return_value.__enter__.return_value = iter(events)
            response = self.post(f"/api/chats/{chat_id}/messages", {"message": "解釋 list", "model": "fake-model"})
            response.get_data()
            return response, client.responses.create.call_args.kwargs

    def test_local_boundary_and_validation(self):
        self.assertEqual(self.browser.get("/health").json, {"ok": True})
        self.assertFalse(self.browser.get("/api/status").json["connected"])
        self.assertEqual(self.browser.post("/api/chats", json={}).status_code, 403)
        self.assertEqual(self.browser.post("/api/chats", data="[]", content_type="application/json", headers=self.headers).status_code, 400)
        self.assertEqual(self.browser.get("/api/status", base_url="http://attacker.example").status_code, 400)
        self.assertIn("frame-ancestors 'none'", self.browser.get("/").headers["Content-Security-Policy"])

    def test_stream_persistence_context_and_export(self):
        self.seed_account()
        chat = self.new_chat()
        response, params = self.send_fake(chat, [SimpleNamespace(type="response.output_text.delta", delta="第一行\n第二行"), SimpleNamespace(type="response.completed")])
        self.assertEqual(response.status_code, 200)
        self.assertIn('"status": "complete"', response.get_data(as_text=True))
        self.assertIs(params["store"], False)
        self.assertIs(params["stream"], True)
        self.assertEqual(params["input"], [{"role": "user", "content": "解釋 list"}])
        self.assertNotIn("temperature", params)
        restored = create_app(self.directory)
        restored.config.update(TESTING=True, SERVER_NAME="127.0.0.1:8080")
        saved = restored.test_client().get(f"/api/chats/{chat}").json
        self.assertEqual(saved["messages"][-1]["content"], "第一行\n第二行")
        exported = self.browser.get(f"/api/chats/{chat}/export")
        self.assertIn("attachment", exported.headers["Content-Disposition"])
        self.assertEqual(json.loads(exported.data)["messages"][-1]["status"], "complete")
        _, next_params = self.send_fake(chat, [SimpleNamespace(type="response.output_text.delta", delta="下一個回答"), SimpleNamespace(type="response.completed")])
        self.assertEqual(len(next_params["input"]), 3)

    def test_failed_stream_does_not_lose_question_or_partial_text(self):
        self.seed_account()
        chat = self.new_chat()
        event = SimpleNamespace(type="response.failed", response=SimpleNamespace(error=SimpleNamespace(code="subscription_sharing_usage_limit_exceeded")))
        response, _ = self.send_fake(chat, [SimpleNamespace(type="response.output_text.delta", delta="部分文字"), event])
        self.assertIn("方案額度", response.get_data(as_text=True))
        messages = self.browser.get(f"/api/chats/{chat}").json["messages"]
        self.assertEqual(messages[0]["content"], "解釋 list")
        self.assertEqual((messages[1]["content"], messages[1]["status"]), ("部分文字", "failed"))

    def test_interrupted_stream_and_recovery(self):
        self.seed_account()
        chat = self.new_chat()
        self.send_fake(chat, [SimpleNamespace(type="response.output_text.delta", delta="中斷前")])
        self.assertEqual(self.browser.get(f"/api/chats/{chat}").json["messages"][-1]["status"], "interrupted")
        with closing(sqlite3.connect(self.directory / "chat.sqlite3")) as db:
            db.execute("UPDATE messages SET status='pending' WHERE role='assistant'")
            db.commit()
        create_app(self.directory)
        self.assertEqual(self.browser.get(f"/api/chats/{chat}").json["messages"][-1]["status"], "interrupted")

    def test_clients_share_server_credentials_and_history(self):
        self.seed_account()
        chat = self.new_chat()
        other = self.app.test_client()
        page = other.get("/")
        self.assertNotIn(b"Continue with ChatGPT", page.data)
        self.assertEqual(other.get("/api/chats").json["chats"][0]["id"], chat)
        self.assertEqual(other.get(f"/api/chats/{chat}").status_code, 200)
        self.assertTrue(other.get("/api/status").json["connected"])
        self.assertEqual(other.get("/auth/callback").status_code, 404)
        with other.session_transaction() as session:
            headers = {"X-CSRF-Token": session["csrf"]}
        self.assertEqual(other.delete(f"/api/chats/{chat}", json={}, headers=headers).status_code, 200)
        self.assertEqual(self.browser.get("/api/chats").json["chats"], [])

    def test_first_run_key_saved_once_and_shared_after_restart(self):
        with patch.dict(os.environ, {"AUTH_MODE": "api_key"}):
            app = create_app(self.directory)
            browser = app.test_client()
            browser.get("/")
            with browser.session_transaction() as session:
                headers = {"X-CSRF-Token": session["csrf"]}
            self.assertFalse(browser.get("/api/status").json["connected"])
            with patch("app.OpenAI") as factory:
                factory.return_value.__enter__.return_value.models.list.return_value.data = [SimpleNamespace(id="gpt-test")]
                response = browser.post("/api/setup", json={"api_key": "sk-fake-test-only"}, headers=headers)
                self.assertEqual(response.status_code, 201)
            path = self.directory / "api-key.json"
            self.assertEqual(json.loads(path.read_text()), "sk-fake-test-only")
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            restored = create_app(self.directory).test_client()
            status = restored.get("/api/status")
            self.assertTrue(status.json["connected"])
            self.assertNotIn(b"sk-fake", status.data)
            self.assertEqual(browser.post("/api/setup", json={"api_key": "replacement"}, headers=headers).status_code, 409)
            self.assertEqual(json.loads(path.read_text()), "sk-fake-test-only")

    def test_pkce_state_and_replay_rejected(self):
        browser_id = "owner-setup-only"
        query = parse_qs(urlparse(self.login.start(browser_id, include_hints=False)).query)
        self.assertEqual(query["client_id"], ["dynamic_agent_client"])
        self.assertEqual(query["redirect_uri"], ["http://127.0.0.1:1455/auth/callback"])
        self.assertEqual(query["code_challenge_method"], ["S256"])
        self.assertIn("chatgpt.tokens.use.direct", query["scope"][0])
        with patch("auth.request_json") as network:
            with self.assertRaises(ValueError): self.login.finish(browser_id, {"state": "wrong", "code": "fake"})
            with self.assertRaises(ValueError): self.login.finish(browser_id, {"state": query["state"][0], "code": "fake"})
            network.assert_not_called()

    def test_verified_oidc_identity_and_granted_scope(self):
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        nonce = "test-nonce"
        payload = {"iss": ISSUER, "aud": "oaiapp_test", "sub": "fake-subject", "iat": int(time.time()), "exp": int(time.time()) + 600, "nonce": nonce}
        tokens = {"id_token": jwt.encode(payload, key, algorithm="RS256")}
        with patch.object(self.login.jwks, "get_signing_key_from_jwt", return_value=SimpleNamespace(key=key.public_key())):
            self.assertEqual(self.login.validate_identity(tokens, "oaiapp_test", nonce)["sub"], "fake-subject")
            with self.assertRaises(ValueError): self.login.validate_identity(tokens, "oaiapp_test", "wrong-nonce")
            with self.assertRaises(jwt.InvalidAudienceError): self.login.validate_identity(tokens, "wrong-client", nonce)
            payload["sub"] = "another-subject"
            tokens["id_token"] = jwt.encode(payload, key, algorithm="RS256")
            with self.assertRaises(ValueError): self.login.validate_identity(tokens, "oaiapp_test", nonce, "fake-subject")
        with self.assertRaises(ValueError):
            self.login.update_tokens({}, {"scope": "openid email", "access_token": "fake", "token_type": "Bearer", "expires_in": 3600})

    def test_refresh_rotation_and_owner_only_credentials(self):
        self.seed_account()
        saved = self.login.load()
        saved["accounts"]["account-a"]["expires_at"] = 0
        private_write(self.login.path, saved)
        with patch("auth.request_json", return_value={"access_token": "fake-new-token", "refresh_token": "fake-new-refresh", "token_type": "Bearer", "expires_in": 3600, "scope": SCOPES}) as network:
            self.assertEqual(self.login.access("account-a"), "fake-new-token")
            self.assertEqual(network.call_args.args[1]["client_id"], "oaiapp_fake_a")
        refreshed = self.login.load()
        self.assertEqual(refreshed["accounts"]["account-a"]["refresh_token"], "fake-new-refresh")
        self.assertEqual(refreshed["accounts"]["account-b"]["access_token"], "fake-test-token-b")
        if os.name != "nt": self.assertEqual(self.login.path.stat().st_mode & 0o777, 0o600)
        self.assertNotIn("fake-new-token", json.dumps(self.browser.get("/api/status").json))


if __name__ == "__main__":
    unittest.main()
