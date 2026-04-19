import sys
import types
import unittest
from types import SimpleNamespace
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


class _FakeWidgets(SimpleNamespace):
    def __init__(self):
        super().__init__(
            host_var=_FakeVar("127.0.0.1"),
            port_var=_FakeVar("1443"),
            secret_var=_FakeVar("0123456789abcdef0123456789abcdef"),
            dc_textbox=_FakeText("2:149.154.167.220\n4:149.154.167.220"),
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


class TrayConfigTests(unittest.TestCase):
    def setUp(self):
        self._orig_proxy_thread = tray_common._proxy_thread
        self._orig_async_stop = tray_common._async_stop
        tray_common._proxy_thread = None
        tray_common._async_stop = None

    def tearDown(self):
        tray_common._proxy_thread = self._orig_proxy_thread
        tray_common._async_stop = self._orig_async_stop

    def test_default_tray_config_contains_common_defaults(self):
        cfg = default_tray_config()

        self.assertEqual(cfg["port"], 1443)
        self.assertEqual(cfg["host"], "127.0.0.1")
        self.assertTrue(cfg["cfproxy"])
        self.assertTrue(cfg["cfproxy_priority"])
        self.assertEqual(cfg["cfproxy_user_domain"], "")
        self.assertEqual(cfg["appearance"], "auto")

    def test_ensure_ctk_thread_accepts_legacy_appearance_argument(self):
        self.assertFalse(tray_common.ensure_ctk_thread(None, "auto"))

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

    def test_validate_config_form_keeps_desktop_fields_and_appearance(self):
        widgets = _FakeWidgets()
        default_config = default_tray_config()

        result = ctk_tray_ui.validate_config_form(
            widgets,
            default_config,
            include_autostart=False,
        )

        self.assertEqual(
            result,
            {
                "host": "127.0.0.1",
                "port": 1443,
                "secret": "0123456789abcdef0123456789abcdef",
                "dc_ip": ["2:149.154.167.220", "4:149.154.167.220"],
                "verbose": True,
                "cfproxy": True,
                "cfproxy_priority": False,
                "cfproxy_user_domain": "cdn.example.com",
                "appearance": "dark",
                "buf_kb": 256,
                "pool_size": 4,
                "log_max_mb": 5.0,
                "check_updates": True,
            },
        )


if __name__ == "__main__":
    unittest.main()
