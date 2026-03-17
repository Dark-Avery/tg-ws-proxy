import unittest
import asyncio
import json

from proxy.tg_ws_proxy import (
    _format_exception_for_log,
    _build_relay_handshake,
    _RelayWsRoute,
    _ordered_upstream_routes,
    _parse_relay_url,
    _route_cooldown_remaining,
    _set_route_cooldown,
    reset_route_fail_states,
)
from unittest.mock import patch


class UpstreamRouteTests(unittest.TestCase):
    def setUp(self):
        reset_route_fail_states()

    def test_orders_direct_telegram_ws_route_first_for_regular_dc(self):
        routes = _ordered_upstream_routes(2, False, "149.154.167.220")

        self.assertEqual([route.route_name for route in routes],
                         ["telegram_ws_direct"])
        self.assertEqual(routes[0].state_key,
                         ("telegram_ws_direct", 2, False))
        self.assertEqual(routes[0].domains,
                         ["kws2.web.telegram.org",
                          "kws2-1.web.telegram.org"])

    def test_orders_media_domains_for_media_dc(self):
        routes = _ordered_upstream_routes(4, True, "149.154.167.91")

        self.assertEqual(routes[0].domains,
                         ["kws4-1.web.telegram.org",
                          "kws4.web.telegram.org"])

    def test_returns_no_routes_without_target_ip(self):
        self.assertEqual(_ordered_upstream_routes(2, False, None), [])

    def test_parse_relay_url_accepts_secure_websocket_url(self):
        parsed = _parse_relay_url("wss://relay.example.com/connect")

        self.assertEqual(parsed["host"], "relay.example.com")
        self.assertEqual(parsed["port"], 443)
        self.assertEqual(parsed["path"], "/connect")
        self.assertTrue(parsed["use_tls"])

    def test_parse_relay_url_rejects_non_websocket_scheme(self):
        with self.assertRaises(ValueError):
            _parse_relay_url("https://relay.example.com/connect")

    def test_build_relay_handshake_contains_route_metadata(self):
        payload = json.loads(_build_relay_handshake(
            2, False, "149.154.167.220", "secret",
            ["kws2.web.telegram.org", "kws2-1.web.telegram.org"]))

        self.assertEqual(payload["version"], 1)
        self.assertEqual(payload["auth_token"], "secret")
        self.assertEqual(payload["mode"], "telegram_ws")
        self.assertEqual(payload["dc"], 2)
        self.assertFalse(payload["media"])
        self.assertEqual(payload["target_ip"], "149.154.167.220")

    def test_format_exception_for_log_includes_type_and_message(self):
        self.assertEqual(_format_exception_for_log(OSError("boom")),
                         "OSError: boom")

    def test_format_exception_for_log_fills_empty_message(self):
        self.assertEqual(_format_exception_for_log(TimeoutError()),
                         "TimeoutError: (no message)")

    def test_cooldown_is_kept_separately_per_route_name(self):
        now = 100.0
        direct_key = ("telegram_ws_direct", 2, False)
        relay_key = ("relay_ws", 2, False)

        _set_route_cooldown(direct_key, now, cooldown=30.0)

        self.assertEqual(_route_cooldown_remaining(direct_key, now + 5.0),
                         25.0)
        self.assertEqual(_route_cooldown_remaining(relay_key, now + 5.0),
                         0.0)

    def test_orders_relay_route_when_relay_mode_is_selected(self):
        routes = _ordered_upstream_routes(
            2, False, "149.154.167.220",
            upstream_mode="relay_ws",
            relay_url="wss://relay.example.com/connect",
            relay_token="secret")

        self.assertEqual([route.route_name for route in routes],
                         ["relay_ws"])
        self.assertEqual(routes[0].state_key, ("relay_ws", 2, False))


class RelayRouteAsyncTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        reset_route_fail_states()

    async def test_relay_route_sends_handshake_and_accepts_ok_response(self):
        class _FakeRelaySocket:
            def __init__(self):
                self.sent_text = []
                self._closed = False

            async def send_text(self, text):
                self.sent_text.append(text)

            async def recv(self):
                return json.dumps({
                    "ok": True,
                    "version": 1,
                    "mode": "telegram_ws",
                    "upstream_domain": "kws2.web.telegram.org",
                }).encode("utf-8")

            async def close(self):
                self._closed = True

        fake_ws = _FakeRelaySocket()
        route = _RelayWsRoute(
            2, False, "149.154.167.220",
            "wss://relay.example.com/connect", "secret")

        with patch("proxy.tg_ws_proxy.RawWebSocket.connect",
                   return_value=fake_ws):
            ws = await route.try_connect("test", "149.154.167.41", 443)

        self.assertIs(ws, fake_ws)
        self.assertEqual(len(fake_ws.sent_text), 1)
        payload = json.loads(fake_ws.sent_text[0])
        self.assertEqual(payload["auth_token"], "secret")
        self.assertEqual(payload["target_ip"], "149.154.167.220")


if __name__ == "__main__":
    unittest.main()
