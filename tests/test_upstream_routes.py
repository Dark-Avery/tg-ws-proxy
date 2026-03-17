import unittest

from proxy.tg_ws_proxy import _ordered_upstream_routes


class UpstreamRouteTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
