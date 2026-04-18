import json
import tempfile
import unittest
from pathlib import Path

from proxy.app_runtime import DEFAULT_CONFIG, ProxyAppRuntime


class _FakeThread:
    def __init__(self, target=None, args=(), daemon=None, name=None):
        self.target = target
        self.args = args
        self.daemon = daemon
        self.name = name
        self.started = False
        self.join_timeout = None
        self._alive = False

    def start(self):
        self.started = True
        self._alive = True

    def is_alive(self):
        return self._alive

    def join(self, timeout=None):
        self.join_timeout = timeout
        self._alive = False


class ProxyAppRuntimeTests(unittest.TestCase):
    def test_load_config_returns_defaults_when_missing(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            runtime = ProxyAppRuntime(Path(tmpdir))

            cfg = runtime.load_config()

            self.assertEqual(cfg, DEFAULT_CONFIG)

    def test_load_config_merges_defaults_into_saved_config(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            app_dir = Path(tmpdir)
            config_path = app_dir / "config.json"
            app_dir.mkdir(parents=True, exist_ok=True)
            config_path.write_text(
                json.dumps({"port": 9050, "host": "127.0.0.2"}),
                encoding="utf-8")
            runtime = ProxyAppRuntime(app_dir)

            cfg = runtime.load_config()

            self.assertEqual(cfg["port"], 9050)
            self.assertEqual(cfg["host"], "127.0.0.2")
            self.assertEqual(cfg["dc_ip"], DEFAULT_CONFIG["dc_ip"])
            self.assertEqual(
                cfg["direct_ws_timeout_seconds"],
                DEFAULT_CONFIG["direct_ws_timeout_seconds"],
            )
            self.assertEqual(cfg["verbose"], DEFAULT_CONFIG["verbose"])

    def test_invalid_config_file_falls_back_to_defaults(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            app_dir = Path(tmpdir)
            app_dir.mkdir(parents=True, exist_ok=True)
            (app_dir / "config.json").write_text("{broken", encoding="utf-8")
            runtime = ProxyAppRuntime(app_dir)

            cfg = runtime.load_config()

            self.assertEqual(cfg, DEFAULT_CONFIG)

    def test_start_proxy_starts_thread_with_parsed_dc_options(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            captured = {}
            thread_holder = {}

            def fake_parse(entries):
                captured["dc_ip"] = list(entries)
                return {2: "149.154.167.220"}

            def fake_thread_factory(**kwargs):
                thread = _FakeThread(**kwargs)
                thread_holder["thread"] = thread
                return thread

            runtime = ProxyAppRuntime(
                Path(tmpdir),
                parse_dc_ip_list=fake_parse,
                thread_factory=fake_thread_factory)

            started = runtime.start_proxy(dict(DEFAULT_CONFIG))

            self.assertTrue(started)
            self.assertEqual(captured["dc_ip"], DEFAULT_CONFIG["dc_ip"])
            self.assertTrue(thread_holder["thread"].started)
            self.assertEqual(
                thread_holder["thread"].args,
                (DEFAULT_CONFIG["port"], {2: "149.154.167.220"},
                 DEFAULT_CONFIG["host"],
                 DEFAULT_CONFIG["upstream_mode"],
                 DEFAULT_CONFIG["relay_url"],
                 DEFAULT_CONFIG["relay_token"],
                 DEFAULT_CONFIG["direct_ws_timeout_seconds"]))

    def test_start_proxy_applies_cfproxy_settings_to_core_proxy_config(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            thread_holder = {}
            import proxy.tg_ws_proxy as tg_ws_proxy
            import proxy.config as config_mod
            import proxy.bridge as bridge_mod

            def fake_thread_factory(**kwargs):
                thread = _FakeThread(**kwargs)
                thread_holder["thread"] = thread
                return thread

            runtime = ProxyAppRuntime(
                Path(tmpdir),
                thread_factory=fake_thread_factory,
            )

            original_core_proxy_config = tg_ws_proxy.proxy_config
            try:
                started = runtime.start_proxy({
                    "port": 1443,
                    "host": "127.0.0.1",
                    "secret": "0123456789abcdef0123456789abcdef",
                    "dc_ip": list(DEFAULT_CONFIG["dc_ip"]),
                    "upstream_mode": "telegram_ws_direct",
                    "relay_url": "",
                    "relay_token": "",
                    "direct_ws_timeout_seconds": 10.0,
                    "buf_kb": 256,
                    "pool_size": 4,
                    "verbose": False,
                    "cfproxy": False,
                    "cfproxy_priority": False,
                    "cfproxy_user_domain": "cdn.example.com",
                })
                applied_proxy_config = tg_ws_proxy.proxy_config
            finally:
                tg_ws_proxy.proxy_config = original_core_proxy_config

            self.assertTrue(started)
            self.assertTrue(thread_holder["thread"].started)
            self.assertIs(applied_proxy_config, config_mod.proxy_config)
            self.assertIs(applied_proxy_config, bridge_mod.proxy_config)
            self.assertFalse(applied_proxy_config.fallback_cfproxy)
            self.assertFalse(applied_proxy_config.fallback_cfproxy_priority)
            self.assertEqual(
                applied_proxy_config.cfproxy_user_domain,
                "cdn.example.com",
            )

    def test_run_proxy_thread_passes_only_stop_event_to_legacy_callable(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            captured = {}

            async def fake_run_proxy(stop_event=None):
                captured["kwargs"] = {"stop_event": stop_event}

            runtime = ProxyAppRuntime(
                Path(tmpdir),
                run_proxy=fake_run_proxy,
            )

            runtime._run_proxy_thread(1443, {2: "149.154.167.220"}, "127.0.0.1")

            self.assertEqual(set(captured["kwargs"].keys()), {"stop_event"})
            self.assertIsNotNone(captured["kwargs"]["stop_event"])

    def test_run_proxy_thread_passes_extended_kwargs_when_supported(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            captured = {}

            async def fake_run_proxy(
                stop_event=None,
                upstream_mode=None,
                relay_url=None,
                relay_token=None,
                direct_ws_timeout_seconds=None,
            ):
                captured["kwargs"] = {
                    "stop_event": stop_event,
                    "upstream_mode": upstream_mode,
                    "relay_url": relay_url,
                    "relay_token": relay_token,
                    "direct_ws_timeout_seconds": direct_ws_timeout_seconds,
                }

            runtime = ProxyAppRuntime(
                Path(tmpdir),
                run_proxy=fake_run_proxy,
            )

            runtime._run_proxy_thread(1443, {2: "149.154.167.220"}, "127.0.0.1")

            self.assertEqual(
                captured["kwargs"],
                {
                    "stop_event": captured["kwargs"]["stop_event"],
                    "upstream_mode": "telegram_ws_direct",
                    "relay_url": None,
                    "relay_token": "",
                    "direct_ws_timeout_seconds": 10.0,
                },
            )

    def test_start_proxy_reports_bad_config(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            errors = []

            def fake_parse(entries):
                raise ValueError("bad dc mapping")

            runtime = ProxyAppRuntime(
                Path(tmpdir),
                parse_dc_ip_list=fake_parse,
                on_error=errors.append)

            started = runtime.start_proxy({
                "host": "127.0.0.1",
                "port": 1080,
                "dc_ip": ["broken"],
                "verbose": False,
            })

            self.assertFalse(started)
            self.assertEqual(errors, ["Ошибка конфигурации:\nbad dc mapping"])

    def test_run_proxy_thread_reports_generic_runtime_error(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            errors = []

            async def fake_run_proxy(stop_event=None):
                raise RuntimeError("proxy boom")

            runtime = ProxyAppRuntime(
                Path(tmpdir),
                on_error=errors.append,
                run_proxy=fake_run_proxy,
            )

            runtime._run_proxy_thread(1443, {2: "149.154.167.220"}, "127.0.0.1")

            self.assertEqual(errors, ["proxy boom"])

    def test_run_proxy_thread_reports_port_in_use_case_insensitively(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            errors = []

            async def fake_run_proxy(stop_event=None):
                raise RuntimeError(
                    "[Errno 98] error while attempting to bind on address "
                    "('127.0.0.1', 1443): address already in use"
                )

            runtime = ProxyAppRuntime(
                Path(tmpdir),
                on_error=errors.append,
                run_proxy=fake_run_proxy,
            )

            runtime._run_proxy_thread(1443, {2: "149.154.167.220"}, "127.0.0.1")

            self.assertEqual(
                errors,
                [
                    "Не удалось запустить прокси:\n"
                    "Порт уже используется другим приложением.\n\n"
                    "Закройте приложение, использующее этот порт, "
                    "или измените порт в настройках прокси и перезапустите."
                ],
            )


if __name__ == "__main__":
    unittest.main()
