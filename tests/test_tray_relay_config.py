import unittest
import types
import sys
from unittest.mock import patch

sys.modules.setdefault("psutil", types.SimpleNamespace(Process=object))

import utils.tray_common as tray_common
from utils.default_config import default_tray_config


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
        tray_common.tg_ws_proxy.proxy_config.direct_ws_timeout_seconds = (
            self._orig_direct_timeout
        )

    def test_default_tray_config_contains_relay_fields(self):
        cfg = default_tray_config()
        self.assertEqual(cfg["upstream_mode"], "telegram_ws_direct")
        self.assertEqual(cfg["relay_url"], "")
        self.assertEqual(cfg["relay_token"], "")
        self.assertEqual(cfg["direct_ws_timeout_seconds"], 10.0)

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


if __name__ == "__main__":
    unittest.main()
