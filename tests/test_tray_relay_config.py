import unittest
import types
import sys
from unittest.mock import patch

sys.modules.setdefault("psutil", types.SimpleNamespace(Process=object))

import ui.ctk_tray_ui as ctk_tray_ui
import utils.tray_common as tray_common
from utils.default_config import default_tray_config


class _FakeVar:
    def __init__(self, value):
        self._value = value

    def get(self):
        return self._value


class _FakeText:
    def __init__(self, value):
        self._value = value

    def get(self, start, end):
        return self._value


class _FakeEntry:
    def __init__(self, value):
        self._value = value

    def get(self):
        return self._value


class _FakeFrame:
    def __init__(self, entry):
        self._entry = entry

    def winfo_children(self):
        return [object(), self._entry]


class _FakeWidgets(types.SimpleNamespace):
    def __init__(self):
        super().__init__(
            host_var=_FakeVar("127.0.0.1"),
            port_var=_FakeVar("1443"),
            secret_var=_FakeVar("0123456789abcdef0123456789abcdef"),
            dc_textbox=_FakeText("2:149.154.167.220\n4:149.154.167.220"),
            upstream_mode_var=_FakeVar("auto"),
            relay_url_var=_FakeVar("wss://relay.example.com/connect"),
            relay_token_var=_FakeVar("relay-token"),
            direct_ws_timeout_var=_FakeVar("3.5"),
            verbose_var=_FakeVar(True),
            adv_entries=[
                _FakeFrame(_FakeEntry("256")),
                _FakeFrame(_FakeEntry("4")),
                _FakeFrame(_FakeEntry("5")),
            ],
            adv_keys=("buf_kb", "pool_size", "log_max_mb"),
            autostart_var=None,
            check_updates_var=_FakeVar(True),
            cfproxy_var=_FakeVar(True),
            cfproxy_priority_var=_FakeVar(False),
            cfproxy_user_domain_var=_FakeVar("cdn.example.com"),
            appearance_var=_FakeVar("Тёмная"),
        )


class TrayRelayConfigTests(unittest.TestCase):
    def setUp(self):
        self._orig_proxy_thread = tray_common._proxy_thread
        self._orig_async_stop = tray_common._async_stop
        self._orig_upstream_mode = tray_common.tg_ws_proxy._upstream_mode
        self._orig_relay_url = tray_common.tg_ws_proxy._relay_url
        self._orig_relay_token = tray_common.tg_ws_proxy._relay_token
        self._orig_direct_timeout = (
            tray_common.tg_ws_proxy.proxy_config.direct_ws_timeout_seconds
        )
        self._orig_proxy_config = {
            "upstream_mode": tray_common.tg_ws_proxy.proxy_config.upstream_mode,
            "relay_url": tray_common.tg_ws_proxy.proxy_config.relay_url,
            "relay_token": tray_common.tg_ws_proxy.proxy_config.relay_token,
            "fallback_cfproxy": tray_common.tg_ws_proxy.proxy_config.fallback_cfproxy,
            "fallback_cfproxy_priority": (
                tray_common.tg_ws_proxy.proxy_config.fallback_cfproxy_priority
            ),
            "cfproxy_user_domain": (
                tray_common.tg_ws_proxy.proxy_config.cfproxy_user_domain
            ),
        }
        tray_common._proxy_thread = None
        tray_common._async_stop = None

    def tearDown(self):
        tray_common._proxy_thread = self._orig_proxy_thread
        tray_common._async_stop = self._orig_async_stop
        tray_common.tg_ws_proxy._upstream_mode = self._orig_upstream_mode
        tray_common.tg_ws_proxy._relay_url = self._orig_relay_url
        tray_common.tg_ws_proxy._relay_token = self._orig_relay_token
        tray_common.tg_ws_proxy.proxy_config.upstream_mode = self._orig_proxy_config[
            "upstream_mode"
        ]
        tray_common.tg_ws_proxy.proxy_config.relay_url = self._orig_proxy_config[
            "relay_url"
        ]
        tray_common.tg_ws_proxy.proxy_config.relay_token = self._orig_proxy_config[
            "relay_token"
        ]
        tray_common.tg_ws_proxy.proxy_config.fallback_cfproxy = (
            self._orig_proxy_config["fallback_cfproxy"]
        )
        tray_common.tg_ws_proxy.proxy_config.fallback_cfproxy_priority = (
            self._orig_proxy_config["fallback_cfproxy_priority"]
        )
        tray_common.tg_ws_proxy.proxy_config.cfproxy_user_domain = (
            self._orig_proxy_config["cfproxy_user_domain"]
        )
        tray_common.tg_ws_proxy.proxy_config.direct_ws_timeout_seconds = (
            self._orig_direct_timeout
        )

    def test_default_tray_config_contains_relay_fields(self):
        cfg = default_tray_config()
        self.assertEqual(cfg["upstream_mode"], "telegram_ws_direct")
        self.assertEqual(cfg["relay_url"], "")
        self.assertEqual(cfg["relay_token"], "")
        self.assertEqual(cfg["direct_ws_timeout_seconds"], 10.0)
        self.assertTrue(cfg["cfproxy"])
        self.assertTrue(cfg["cfproxy_priority"])
        self.assertEqual(cfg["cfproxy_user_domain"], "")
        self.assertEqual(cfg["appearance"], "auto")

    def test_ensure_ctk_thread_accepts_legacy_appearance_argument(self):
        self.assertFalse(tray_common.ensure_ctk_thread(None, "auto"))

    def test_start_proxy_passes_current_relay_settings_to_runtime(self):
        cfg = default_tray_config()
        cfg.update(
            {
                "upstream_mode": "auto",
                "relay_url": "wss://relay.example.com/connect",
                "relay_token": "relay-token",
                "direct_ws_timeout_seconds": 3.5,
            }
        )

        tray_common.tg_ws_proxy._upstream_mode = "telegram_ws_direct"
        tray_common.tg_ws_proxy._relay_url = None
        tray_common.tg_ws_proxy._relay_token = ""

        captured = {}

        async def fake_run(**kwargs):
            captured.update(kwargs)

        class FakeThread:
            def __init__(self, *, target, args=(), kwargs=None, **_unused):
                self._target = target
                self._args = args
                self._kwargs = kwargs or {}
                self._alive = False

            def is_alive(self):
                return self._alive

            def start(self):
                self._alive = True
                try:
                    self._target(*self._args, **self._kwargs)
                finally:
                    self._alive = False

        with patch.object(tray_common.tg_ws_proxy, "_run", fake_run), patch.object(
            tray_common.threading, "Thread", FakeThread
        ):
            tray_common.start_proxy(
                cfg,
                lambda message: self.fail(f"unexpected tray error: {message}"),
            )

        self.assertEqual(captured["upstream_mode"], "auto")
        self.assertEqual(
            captured["relay_url"],
            "wss://relay.example.com/connect",
        )
        self.assertEqual(captured["relay_token"], "relay-token")
        self.assertEqual(
            tray_common.tg_ws_proxy.proxy_config.direct_ws_timeout_seconds,
            3.5,
        )

    def test_validate_config_form_preserves_relay_fields_and_appearance(self):
        widgets = _FakeWidgets()
        cfg = default_tray_config()

        result = ctk_tray_ui.validate_config_form(
            widgets,
            cfg,
            include_autostart=False,
        )

        self.assertEqual(result["upstream_mode"], "auto")
        self.assertEqual(result["relay_url"], "wss://relay.example.com/connect")
        self.assertEqual(result["relay_token"], "relay-token")
        self.assertEqual(result["direct_ws_timeout_seconds"], 3.5)
        self.assertTrue(result["cfproxy"])
        self.assertFalse(result["cfproxy_priority"])
        self.assertEqual(result["cfproxy_user_domain"], "cdn.example.com")
        self.assertEqual(result["appearance"], "dark")

    def test_start_proxy_applies_cfproxy_settings_to_runtime_config(self):
        cfg = default_tray_config()
        cfg.update(
            {
                "cfproxy": False,
                "cfproxy_priority": False,
                "cfproxy_user_domain": "cdn.example.com",
            }
        )

        async def fake_run(**_kwargs):
            return None

        class FakeThread:
            def __init__(self, *, target, args=(), kwargs=None, **_unused):
                self._target = target
                self._args = args
                self._kwargs = kwargs or {}
                self._alive = False

            def is_alive(self):
                return self._alive

            def start(self):
                self._alive = True
                try:
                    self._target(*self._args, **self._kwargs)
                finally:
                    self._alive = False

        with patch.object(tray_common.tg_ws_proxy, "_run", fake_run), patch.object(
            tray_common.threading, "Thread", FakeThread
        ):
            tray_common.start_proxy(
                cfg,
                lambda message: self.fail(f"unexpected tray error: {message}"),
            )

        self.assertFalse(tray_common.tg_ws_proxy.proxy_config.fallback_cfproxy)
        self.assertFalse(
            tray_common.tg_ws_proxy.proxy_config.fallback_cfproxy_priority
        )
        self.assertEqual(
            tray_common.tg_ws_proxy.proxy_config.cfproxy_user_domain,
            "cdn.example.com",
        )


if __name__ == "__main__":
    unittest.main()
