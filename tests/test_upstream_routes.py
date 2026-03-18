import unittest
import asyncio
import json
import os
from unittest.mock import patch

from proxy.tg_ws_proxy import (
    _DirectTelegramWsRoute,
    _get_last_good_route,
    _LAST_GOOD_ROUTE_TTL,
    _try_upstream_routes,
    _format_exception_for_log,
    _build_relay_handshake,
    _RelayWsRoute,
    _ordered_upstream_routes,
    _parse_relay_url,
    _reorder_routes_by_last_good,
    _route_cooldown_remaining,
    _set_route_cooldown,
    _set_last_good_route,
    _ws_pool_enabled,
    reset_route_fail_states,
)


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

    def test_ws_pool_enabled_by_default(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("TG_WS_PROXY_DISABLE_WS_POOL", None)
            self.assertTrue(_ws_pool_enabled())

    def test_ws_pool_can_be_disabled_via_env(self):
        with patch.dict(os.environ, {"TG_WS_PROXY_DISABLE_WS_POOL": "1"}, clear=False):
            self.assertFalse(_ws_pool_enabled())

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

    def test_orders_direct_then_relay_in_auto_mode(self):
        routes = _ordered_upstream_routes(
            2, False, "149.154.167.220",
            upstream_mode="auto",
            relay_url="wss://relay.example.com/connect",
            relay_token="secret")

        self.assertEqual([route.route_name for route in routes],
                         ["telegram_ws_direct", "relay_ws"])

    def test_orders_only_direct_in_auto_mode_without_relay(self):
        routes = _ordered_upstream_routes(
            2, False, "149.154.167.220",
            upstream_mode="auto")

        self.assertEqual([route.route_name for route in routes],
                         ["telegram_ws_direct"])

    def test_auto_mode_prefers_last_good_route_when_present(self):
        _set_last_good_route(2, False, "relay_ws")

        routes = _ordered_upstream_routes(
            2, False, "149.154.167.220",
            upstream_mode="auto",
            relay_url="wss://relay.example.com/connect",
            relay_token="secret")

        self.assertEqual([route.route_name for route in routes],
                         ["relay_ws", "telegram_ws_direct"])

    def test_reorder_routes_by_last_good_keeps_order_when_preference_missing(self):
        direct = _DirectTelegramWsRoute(2, False, "149.154.167.220")
        relay = _RelayWsRoute(
            2, False, "149.154.167.220",
            "wss://relay.example.com/connect", "secret")

        routes = _reorder_routes_by_last_good([direct, relay], 2, False)

        self.assertEqual([route.route_name for route in routes],
                         ["telegram_ws_direct", "relay_ws"])

    def test_last_good_route_expires_after_ttl(self):
        with patch("proxy.tg_ws_proxy.time.monotonic",
                   side_effect=[100.0, 100.0 + _LAST_GOOD_ROUTE_TTL + 1.0]):
            _set_last_good_route(2, False, "relay_ws")
            preferred = _get_last_good_route(2, False)

        self.assertIsNone(preferred)

    def test_auto_mode_returns_to_direct_after_last_good_ttl(self):
        direct = _DirectTelegramWsRoute(2, False, "149.154.167.220")
        relay = _RelayWsRoute(
            2, False, "149.154.167.220",
            "wss://relay.example.com/connect", "secret")

        with patch("proxy.tg_ws_proxy.time.monotonic",
                   side_effect=[100.0, 100.0 + _LAST_GOOD_ROUTE_TTL + 1.0]):
            _set_last_good_route(2, False, "relay_ws")
            routes = _reorder_routes_by_last_good([direct, relay], 2, False)

        self.assertEqual([route.route_name for route in routes],
                         ["telegram_ws_direct", "relay_ws"])


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

    async def test_try_upstream_routes_uses_second_route_after_first_failure(self):
        class _FakeRoute:
            def __init__(self, route_name, result, dc=2, is_media=False):
                self.route_name = route_name
                self.result = result
                self.calls = 0
                self.dc = dc
                self.is_media = is_media

            async def try_connect(self, label, dst, port):
                self.calls += 1
                return self.result

        direct = _FakeRoute("telegram_ws_direct", None)
        relay_socket = object()
        relay = _FakeRoute("relay_ws", relay_socket)

        ws = await _try_upstream_routes(
            [direct, relay], "test", "149.154.167.41", 443)

        self.assertIs(ws, relay_socket)
        self.assertEqual(direct.calls, 1)
        self.assertEqual(relay.calls, 1)
        self.assertEqual(_get_last_good_route(2, False), "relay_ws")

    async def test_try_upstream_routes_returns_none_when_all_routes_fail(self):
        class _FakeRoute:
            def __init__(self, route_name):
                self.calls = 0
                self.route_name = route_name
                self.dc = 2
                self.is_media = False

            async def try_connect(self, label, dst, port):
                self.calls += 1
                return None

        first = _FakeRoute("telegram_ws_direct")
        second = _FakeRoute("relay_ws")

        ws = await _try_upstream_routes(
            [first, second], "test", "149.154.167.41", 443)

        self.assertIsNone(ws)
        self.assertEqual(first.calls, 1)
        self.assertEqual(second.calls, 1)
        self.assertIsNone(_get_last_good_route(2, False))


if __name__ == "__main__":
    unittest.main()
