#!/usr/bin/env python3
"""
Tests for the control panel: config safety, auth, and the JSON API.

Run:  python3 -m unittest discover -s tests -v
"""

import importlib.util
import json
import os
import shutil
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Must be set before the module is imported — the panel reads them at import.
TEST_TOKEN = "test-token-abc123"
os.environ["PANEL_TOKEN"] = TEST_TOKEN
os.environ["PANEL_HOST"] = "127.0.0.1"

_spec = importlib.util.spec_from_file_location(
    "panel_server", ROOT / "control-panel" / "server.py")
panel = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(panel)


SECRETS = {
    "claude_key": "sk-ant-api03-REALKEY1234567890abcdefXYZ",
    "email_password": "hunter2-app-password",
    "hmac": "a-real-random-hmac-secret-value",
}


def make_config() -> dict:
    return {
        "default_model": "ollama",
        "fallback_chain": ["ollama", "claude"],
        "models": {
            "claude": {"provider": "anthropic", "model": "claude-opus-4-6",
                       "api_key": SECRETS["claude_key"]},
            "ollama": {"provider": "ollama", "model": "llama3",
                       "base_url": "http://localhost:11434"},
            "opencode": {"provider": "opencode", "model": "x",
                         "base_url": "http://localhost:54321"},
        },
        "security": {"hmac_secret": SECRETS["hmac"], "max_message_length": 4000,
                     "rate_limit_per_minute": 20, "block_prompt_injection": True,
                     "injection_patterns": ["ignore previous"]},
        "email": {"enabled": False, "address": "me@example.com",
                  "password": SECRETS["email_password"], "allowed_senders": []},
        "telegram": {"enabled": False, "allowed_user_ids": []},
        "whatsapp": {"enabled": True, "bridge_port": 8766, "allowed_numbers": []},
        "imessage": {"enabled": False, "allowed_handles": []},
    }


class PanelConfigTest(unittest.TestCase):
    """The blocker: adding a contact used to overwrite every secret."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="pybridge-test-"))
        self.cfg_path = self.tmp / "config.json"
        self.cfg_path.write_text(json.dumps(make_config(), indent=2))
        self._orig = panel.PYBRIDGE_CONFIG
        panel.PYBRIDGE_CONFIG = self.cfg_path

    def tearDown(self):
        panel.PYBRIDGE_CONFIG = self._orig
        shutil.rmtree(self.tmp, ignore_errors=True)

    def on_disk(self) -> dict:
        return json.loads(self.cfg_path.read_text())

    def assert_secrets_intact(self):
        cfg = self.on_disk()
        self.assertEqual(cfg["models"]["claude"]["api_key"], SECRETS["claude_key"])
        self.assertEqual(cfg["email"]["password"], SECRETS["email_password"])
        self.assertEqual(cfg["security"]["hmac_secret"], SECRETS["hmac"])

    def test_read_config_redacts_for_display(self):
        safe = panel.read_config()
        self.assertNotEqual(safe["models"]["claude"]["api_key"], SECRETS["claude_key"])
        self.assertEqual(safe["email"]["password"], "••••••••")
        self.assert_secrets_intact()          # display must not touch the file

    def test_add_contact_preserves_secrets(self):
        ok, err = panel.update_contact("whatsapp", "+919876543210", "add")
        self.assertTrue(ok, err)
        self.assertEqual(self.on_disk()["whatsapp"]["allowed_numbers"],
                         ["+919876543210"])
        self.assert_secrets_intact()

    def test_remove_contact_preserves_secrets(self):
        panel.update_contact("email", "phone@example.com", "add")
        ok, _ = panel.update_contact("email", "phone@example.com", "remove")
        self.assertTrue(ok)
        self.assertEqual(self.on_disk()["email"]["allowed_senders"], [])
        self.assert_secrets_intact()

    def test_telegram_ids_are_integers(self):
        ok, err = panel.update_contact("telegram", "123456789", "add")
        self.assertTrue(ok, err)
        self.assertEqual(self.on_disk()["telegram"]["allowed_user_ids"], [123456789])
        ok, err = panel.update_contact("telegram", "not-a-number", "add")
        self.assertFalse(ok)
        self.assertIn("Invalid Telegram", err)

    def test_unknown_channel_rejected(self):
        ok, err = panel.update_contact("carrier-pigeon", "x", "add")
        self.assertFalse(ok)
        self.assertIn("Unknown channel", err)

    def test_contacts_list_reads_every_channel(self):
        panel.update_contact("whatsapp", "+1", "add")
        panel.update_contact("imessage", "+2", "add")
        self.assertEqual(panel.list_contacts(),
                         {"whatsapp": ["+1"], "telegram": [], "email": [],
                          "imessage": ["+2"]})

    def test_health_does_not_flag_keyless_local_providers(self):
        msgs = [w["msg"] for w in panel.check_health()]
        self.assertFalse([m for m in msgs if m.startswith("ollama:")], msgs)
        self.assertFalse([m for m in msgs if m.startswith("opencode:")], msgs)


class PanelHTTPTest(unittest.TestCase):
    """Auth gate and routing over a real socket."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="pybridge-http-"))
        cls.cfg_path = cls.tmp / "config.json"
        cls.cfg_path.write_text(json.dumps(make_config(), indent=2))
        cls._orig = panel.PYBRIDGE_CONFIG
        panel.PYBRIDGE_CONFIG = cls.cfg_path

        cls.server = panel.build_server(0)
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.thread.join(timeout=5)
        cls.server.server_close()
        panel.PYBRIDGE_CONFIG = cls._orig
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def url(self, path: str) -> str:
        return f"http://127.0.0.1:{self.port}{path}"

    def fetch(self, path, token=None, data=None):
        req = urllib.request.Request(self.url(path))
        if token:
            req.add_header("Authorization", f"Bearer {token}")
        if data is not None:
            req.data = json.dumps(data).encode()
            req.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                return resp.status, resp.read(), dict(resp.headers)
        except urllib.error.HTTPError as e:
            return e.code, e.read(), dict(e.headers)

    def test_api_requires_token(self):
        status, body, _ = self.fetch("/api/config")
        self.assertEqual(status, 401)
        self.assertEqual(json.loads(body)["error"], "unauthorized")

    def test_api_accepts_bearer_token(self):
        status, body, _ = self.fetch("/api/config", token=TEST_TOKEN)
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["default_model"], "ollama")

    def test_api_rejects_wrong_token(self):
        status, _, _ = self.fetch("/api/config", token="wrong")
        self.assertEqual(status, 401)

    def test_root_serves_login_page_without_token(self):
        status, body, _ = self.fetch("/")
        self.assertEqual(status, 401)
        self.assertIn(b"Access token", body)

    def test_token_in_query_sets_cookie(self):
        status, body, headers = self.fetch(f"/?token={TEST_TOKEN}")
        self.assertEqual(status, 200)
        self.assertIn("pybridge_panel=", headers.get("Set-Cookie", ""))
        self.assertIn(b"Control Panel", body)

    def test_contacts_list_answers_GET(self):
        """The frontend GETs this on every page load; it used to be POST-only."""
        status, body, _ = self.fetch("/api/contacts/list", token=TEST_TOKEN)
        self.assertEqual(status, 200)
        self.assertIn("whatsapp", json.loads(body))

    def test_post_contact_then_secrets_still_on_disk(self):
        status, body, _ = self.fetch(
            "/api/contacts", token=TEST_TOKEN,
            data={"channel": "whatsapp", "value": "+15550001111", "action": "add"})
        self.assertEqual(status, 200)
        self.assertTrue(json.loads(body)["ok"])
        cfg = json.loads(self.cfg_path.read_text())
        self.assertIn("+15550001111", cfg["whatsapp"]["allowed_numbers"])
        self.assertEqual(cfg["models"]["claude"]["api_key"], SECRETS["claude_key"])
        self.assertEqual(cfg["security"]["hmac_secret"], SECRETS["hmac"])

    def test_unknown_default_model_rejected(self):
        status, body, _ = self.fetch("/api/model/default", token=TEST_TOKEN,
                                     data={"model": "gpt-9000"})
        self.assertEqual(status, 400)
        self.assertIn("Unknown model", json.loads(body)["error"])

    def test_unknown_route_404s(self):
        status, _, _ = self.fetch("/api/nope", token=TEST_TOKEN)
        self.assertEqual(status, 404)

    def test_healthz_is_open_and_leaks_nothing(self):
        """Docker's HEALTHCHECK has no token — but must not see the config."""
        status, body, _ = self.fetch("/healthz")
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body), {"status": "ok"})


if __name__ == "__main__":
    unittest.main(verbosity=2)
