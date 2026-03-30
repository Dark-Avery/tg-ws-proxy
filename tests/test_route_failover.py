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


if __name__ == "__main__":
    unittest.main()
