import unittest

from utils.default_config import default_tray_config


class TrayRelayConfigTests(unittest.TestCase):
    def test_default_tray_config_contains_relay_fields(self):
        cfg = default_tray_config()
        self.assertEqual(cfg["upstream_mode"], "telegram_ws_direct")
        self.assertEqual(cfg["relay_url"], "")
        self.assertEqual(cfg["relay_token"], "")
        self.assertEqual(cfg["direct_ws_timeout_seconds"], 10.0)


if __name__ == "__main__":
    unittest.main()
