import asyncio
import unittest
from unittest.mock import patch

from proxy import tg_ws_proxy


class RouteFailoverTests(unittest.TestCase):
    def setUp(self):
        tg_ws_proxy.reset_route_fail_states()
        tg_ws_proxy.configure_route_timing()

    def test_auto_mode_prefers_relay_when_direct_route_on_cooldown(self):
        with patch("proxy.tg_ws_proxy._upstream_mode", "auto"), \
                patch("proxy.tg_ws_proxy._relay_url",
                      "wss://relay.example.com/connect"), \
                patch("proxy.tg_ws_proxy.time.monotonic", return_value=100.0):
            tg_ws_proxy._set_route_cooldown((2, False), 100.0)
            routes = tg_ws_proxy._ordered_transport_routes(2, False)

        self.assertEqual(routes, ["relay_ws", "telegram_ws_direct"])

    def test_auto_mode_prefers_last_good_relay_route(self):
        with patch("proxy.tg_ws_proxy._upstream_mode", "auto"), \
                patch("proxy.tg_ws_proxy._relay_url",
                      "wss://relay.example.com/connect"), \
                patch("proxy.tg_ws_proxy.time.monotonic", return_value=100.0):
            tg_ws_proxy._set_last_good_route(2, False, "relay_ws")
            routes = tg_ws_proxy._ordered_transport_routes(2, False)

        self.assertEqual(routes, ["relay_ws", "telegram_ws_direct"])

    def test_last_good_route_expires_after_ttl(self):
        with patch("proxy.tg_ws_proxy.time.monotonic",
                   side_effect=[100.0, 100.0 + tg_ws_proxy.LAST_GOOD_ROUTE_TTL + 1.0]):
            tg_ws_proxy._set_last_good_route(2, False, "relay_ws")
            preferred = tg_ws_proxy._get_last_good_route(2, False)

        self.assertIsNone(preferred)

    def test_degraded_direct_media_sessions_trigger_cooldown(self):
        with patch("proxy.tg_ws_proxy._upstream_mode", "auto"), \
                patch("proxy.tg_ws_proxy.time.monotonic",
                      side_effect=[100.0, 101.0]):
            tg_ws_proxy._record_route_session_result(
                "test", "telegram_ws_direct", 2, True, 12.0, 32 * 1024)
            tg_ws_proxy._record_route_session_result(
                "test", "telegram_ws_direct", 2, True, 11.0, 16 * 1024)

        remaining = tg_ws_proxy._route_cooldown_remaining((2, True), 101.0)
        self.assertGreater(remaining, 0.0)
        self.assertLessEqual(remaining, tg_ws_proxy.DC_FAIL_COOLDOWN)

    def test_healthy_direct_media_session_clears_degraded_streak(self):
        with patch("proxy.tg_ws_proxy._upstream_mode", "auto"), \
                patch("proxy.tg_ws_proxy.time.monotonic",
                      side_effect=[100.0, 101.0, 102.0]):
            tg_ws_proxy._record_route_session_result(
                "test", "telegram_ws_direct", 2, True, 12.0, 32 * 1024)
            tg_ws_proxy._record_route_session_result(
                "test", "telegram_ws_direct", 2, True, 12.0, 128 * 1024)
            tg_ws_proxy._record_route_session_result(
                "test", "telegram_ws_direct", 2, True, 12.0, 32 * 1024)

        remaining = tg_ws_proxy._route_cooldown_remaining((2, True), 102.0)
        self.assertEqual(remaining, 0.0)


class RunConfigContractTests(unittest.IsolatedAsyncioTestCase):
    async def test_run_preserves_preloaded_config_when_overrides_omitted(self):
        class _FakeServer:
            def __init__(self):
                self.sockets = []

            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return False

            async def serve_forever(self):
                await asyncio.Future()

            def close(self):
                return None

            async def wait_closed(self):
                return None

        original = {
            "host": tg_ws_proxy.proxy_config.host,
            "port": tg_ws_proxy.proxy_config.port,
            "secret": tg_ws_proxy.proxy_config.secret,
            "dc_redirects": dict(tg_ws_proxy.proxy_config.dc_redirects),
            "fallback_cfproxy": tg_ws_proxy.proxy_config.fallback_cfproxy,
            "upstream_mode": tg_ws_proxy.proxy_config.upstream_mode,
            "relay_url": tg_ws_proxy.proxy_config.relay_url,
            "relay_token": tg_ws_proxy.proxy_config.relay_token,
            "direct_ws_timeout_seconds": (
                tg_ws_proxy.proxy_config.direct_ws_timeout_seconds
            ),
            "_upstream_mode": tg_ws_proxy._upstream_mode,
            "_relay_url": tg_ws_proxy._relay_url,
            "_relay_token": tg_ws_proxy._relay_token,
        }
        stop_event = asyncio.Event()
        stop_event.set()

        tg_ws_proxy.proxy_config.host = "127.0.0.1"
        tg_ws_proxy.proxy_config.port = 1443
        tg_ws_proxy.proxy_config.secret = "0123456789abcdef0123456789abcdef"
        tg_ws_proxy.proxy_config.dc_redirects = {2: "149.154.167.220"}
        tg_ws_proxy.proxy_config.fallback_cfproxy = False
        tg_ws_proxy.proxy_config.upstream_mode = "auto"
        tg_ws_proxy.proxy_config.relay_url = "wss://relay.example.com/connect"
        tg_ws_proxy.proxy_config.relay_token = "saved-token"
        tg_ws_proxy.proxy_config.direct_ws_timeout_seconds = 3.5

        try:
            with patch("proxy.tg_ws_proxy.asyncio.start_server",
                       return_value=_FakeServer()), \
                    patch("proxy.tg_ws_proxy._ws_pool.warmup"), \
                    patch("proxy.tg_ws_proxy.get_link_host",
                          return_value="127.0.0.1"):
                await tg_ws_proxy._run(stop_event=stop_event)

            self.assertEqual(tg_ws_proxy.proxy_config.upstream_mode, "auto")
            self.assertEqual(
                tg_ws_proxy.proxy_config.relay_url,
                "wss://relay.example.com/connect",
            )
            self.assertEqual(tg_ws_proxy.proxy_config.relay_token, "saved-token")
            self.assertEqual(
                tg_ws_proxy.proxy_config.direct_ws_timeout_seconds,
                3.5,
            )
        finally:
            for key, value in original.items():
                if key.startswith("_"):
                    setattr(tg_ws_proxy, key, value)
                    continue
                setattr(tg_ws_proxy.proxy_config, key, value)


class RouteSessionAccountingTests(unittest.IsolatedAsyncioTestCase):
    async def test_handle_client_records_session_local_downstream_bytes(self):
        class _Transform:
            def update(self, data):
                return data

        class _Cipher:
            def __init__(self, *_args, **_kwargs):
                pass

            def encryptor(self):
                return _Transform()

        class _Reader:
            def __init__(self):
                self._parts = [b"\x01", b"\x00" * 63]

            async def readexactly(self, n):
                part = self._parts.pop(0)
                self.assert_equal_len = n
                return part

            async def read(self, _n):
                return b""

        class _Writer:
            def __init__(self):
                self.transport = self
                self.closed = False

            def get_extra_info(self, name):
                if name == "peername":
                    return ("127.0.0.1", 54321)
                if name == "socket":
                    return None
                return None

            def write(self, _data):
                return None

            async def drain(self):
                return None

            def close(self):
                self.closed = True

            async def wait_closed(self):
                return None

        class _WebSocket:
            async def send(self, _data):
                return None

        async def _fake_bridge(*_args, **_kwargs):
            tg_ws_proxy.stats.bytes_down += 1024 * 1024
            return 12.0, 32 * 1024

        original = {
            "fake_tls_domain": tg_ws_proxy.proxy_config.fake_tls_domain,
            "proxy_protocol": tg_ws_proxy.proxy_config.proxy_protocol,
            "dc_redirects": dict(tg_ws_proxy.proxy_config.dc_redirects),
            "bytes_down": tg_ws_proxy.stats.bytes_down,
        }
        tg_ws_proxy.proxy_config.fake_tls_domain = ""
        tg_ws_proxy.proxy_config.proxy_protocol = False
        tg_ws_proxy.proxy_config.dc_redirects = {2: "149.154.167.220"}
        tg_ws_proxy.stats.bytes_down = 5 * 1024 * 1024

        try:
            with patch("proxy.tg_ws_proxy._try_handshake",
                       return_value=(2, True,
                                     tg_ws_proxy.PROTO_TAG_ABRIDGED,
                                     b"\x01" * 48)), \
                    patch("proxy.tg_ws_proxy._generate_relay_init",
                          return_value=b"\x02" * 64), \
                    patch("proxy.tg_ws_proxy.Cipher", _Cipher), \
                    patch("proxy.tg_ws_proxy._try_direct_ws",
                          return_value=(_WebSocket(), False, False)), \
                    patch("proxy.tg_ws_proxy.bridge_ws_reencrypt",
                          side_effect=_fake_bridge), \
                    patch("proxy.tg_ws_proxy._record_route_session_result") as record:
                await tg_ws_proxy._handle_client(
                    _Reader(),
                    _Writer(),
                    bytes.fromhex("0123456789abcdef0123456789abcdef"),
                )

            record.assert_called_once()
            self.assertEqual(record.call_args.args[5], 32 * 1024)
        finally:
            for key, value in original.items():
                if key == "bytes_down":
                    tg_ws_proxy.stats.bytes_down = value
                    continue
                setattr(tg_ws_proxy.proxy_config, key, value)


if __name__ == "__main__":
    unittest.main()
