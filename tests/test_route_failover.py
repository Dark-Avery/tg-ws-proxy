import unittest
from unittest.mock import patch

from proxy import bridge as bridge_mod
from proxy import tg_ws_proxy


class RouteFailoverTests(unittest.IsolatedAsyncioTestCase):
    async def test_do_fallback_prefers_cfproxy_when_enabled_and_priority_set(self):
        with patch.object(bridge_mod.proxy_config, "fallback_cfproxy", True), \
                patch.object(bridge_mod.proxy_config,
                             "fallback_cfproxy_priority", True), \
                patch("proxy.bridge._cfproxy_fallback", return_value=True) as cf, \
                patch("proxy.bridge._tcp_fallback", return_value=True) as tcp:
            result = await bridge_mod.do_fallback(
                None, None, b"init", "test", 2, False, "", None
            )

        self.assertTrue(result)
        cf.assert_awaited_once()
        tcp.assert_not_awaited()

    async def test_do_fallback_uses_tcp_when_cfproxy_disabled(self):
        with patch.object(bridge_mod.proxy_config, "fallback_cfproxy", False), \
                patch.object(bridge_mod.proxy_config,
                             "fallback_cfproxy_priority", True), \
                patch("proxy.bridge._cfproxy_fallback", return_value=True) as cf, \
                patch("proxy.bridge._tcp_fallback", return_value=True) as tcp:
            result = await bridge_mod.do_fallback(
                None, None, b"init", "test", 2, False, "", None
            )

        self.assertTrue(result)
        cf.assert_not_awaited()
        tcp.assert_awaited_once()

    def test_reset_route_fail_states_clears_ws_blacklist(self):
        tg_ws_proxy.ws_blacklist.add((2, False))

        tg_ws_proxy.reset_route_fail_states()

        self.assertEqual(tg_ws_proxy.ws_blacklist, set())


if __name__ == "__main__":
    unittest.main()
