import unittest

from proxy.tg_ws_proxy import (
    _format_exception_for_log,
    _ordered_upstream_routes,
    _route_cooldown_remaining,
    _set_route_cooldown,
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


if __name__ == "__main__":
    unittest.main()
