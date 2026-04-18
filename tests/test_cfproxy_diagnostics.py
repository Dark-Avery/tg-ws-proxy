import unittest
from unittest import mock

from utils import cfproxy_diagnostics


class _FakeSslSocket:
    def __init__(self, response: bytes, ip: str):
        self._response = response
        self._ip = ip
        self.sent = b""

    def sendall(self, data: bytes) -> None:
        self.sent += data

    def settimeout(self, value: float) -> None:
        self.timeout = value

    def recv(self, size: int) -> bytes:
        response, self._response = self._response, b""
        return response

    def getpeername(self):
        return (self._ip, 443)

    def close(self) -> None:
        pass

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class _FakeRawSocket:
    def close(self) -> None:
        pass

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class _FakeSslContext:
    def __init__(self, responses):
        self._responses = list(responses)
        self.check_hostname = True
        self.verify_mode = object()

    def wrap_socket(self, raw, server_hostname=None):
        response, ip = self._responses.pop(0)
        return _FakeSslSocket(response, ip)


class CfProxyDiagnosticsTests(unittest.TestCase):
    def test_run_connectivity_test_returns_compact_payload_and_preserves_checks(self):
        responses = [
            (b"HTTP/1.1 101 Switching Protocols\r\n\r\n", "203.0.113.10"),
            (b"HTTP/1.1 101 Switching Protocols\r\n\r\n", "203.0.113.11"),
            (b"HTTP/1.1 101 Switching Protocols\r\n\r\n", "203.0.113.12"),
            (b"HTTP/1.1 101 Switching Protocols\r\n\r\n", "203.0.113.13"),
            (b"HTTP/1.1 101 Switching Protocols\r\n\r\n", "203.0.113.14"),
            (b"HTTP/1.1 101 Switching Protocols\r\n\r\n", "203.0.113.15"),
        ]
        context = _FakeSslContext(responses)

        with mock.patch.object(
            cfproxy_diagnostics.ssl,
            "create_default_context",
            return_value=context,
        ), mock.patch.object(
            cfproxy_diagnostics._socket,
            "create_connection",
            side_effect=lambda *args, **kwargs: _FakeRawSocket(),
        ):
            result = cfproxy_diagnostics.run_connectivity_test("cdn.example.com")

        self.assertTrue(result["ok"])
        self.assertEqual(result["domain"], "cdn.example.com")
        self.assertEqual(result["ip"], "203.0.113.10")
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["detail"], "6/6 endpoints reachable")
        self.assertEqual(len(result["checks"]), 6)
        self.assertTrue(all(value is True for value in result["checks"].values()))

    def test_run_auto_test_prefers_last_fully_working_domain_like_legacy_tray(self):
        with mock.patch.object(
            cfproxy_diagnostics,
            "run_connectivity_test",
            side_effect=lambda domain: {
                "first.example.com": {
                    "ok": False,
                    "domain": "first.example.com",
                    "ip": "",
                    "status": "fail",
                    "detail": "0/6 endpoints reachable",
                    "checks": {1: "timeout"},
                },
                "second.example.com": {
                    "ok": False,
                    "domain": "second.example.com",
                    "ip": "203.0.113.25",
                    "status": "partial",
                    "detail": "4/6 endpoints reachable",
                    "checks": {1: True, 2: True, 3: True, 4: True, 5: "timeout", 203: "timeout"},
                },
                "third.example.com": {
                    "ok": True,
                    "domain": "third.example.com",
                    "ip": "203.0.113.30",
                    "status": "ok",
                    "detail": "6/6 endpoints reachable",
                    "checks": {1: True, 2: True, 3: True, 4: True, 5: True, 203: True},
                },
                "fourth.example.com": {
                    "ok": True,
                    "domain": "fourth.example.com",
                    "ip": "203.0.113.31",
                    "status": "ok",
                    "detail": "6/6 endpoints reachable",
                    "checks": {1: True, 2: True, 3: True, 4: True, 5: True, 203: True},
                },
            }[domain],
        ):
            selected_domain, result = cfproxy_diagnostics.run_auto_test(
                [
                    "first.example.com",
                    "second.example.com",
                    "third.example.com",
                    "fourth.example.com",
                ]
            )

        self.assertEqual(selected_domain, "fourth.example.com")
        self.assertTrue(result["ok"])
        self.assertEqual(result["domain"], "fourth.example.com")
        self.assertEqual(result["ip"], "203.0.113.31")
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["detail"], "6/6 endpoints reachable")
        self.assertEqual(result["mode"], "auto")
        self.assertEqual(result["selected_domain"], "fourth.example.com")

    def test_run_auto_test_merges_partial_results_across_domains(self):
        with mock.patch.object(
            cfproxy_diagnostics,
            "run_connectivity_test",
            side_effect=lambda domain: {
                "first.example.com": {
                    "ok": False,
                    "domain": "first.example.com",
                    "ip": "",
                    "status": "partial",
                    "detail": "1/6 endpoints reachable",
                    "checks": {
                        1: "timeout",
                        2: True,
                        3: "timeout",
                        4: "timeout",
                        5: "timeout",
                        203: "timeout",
                    },
                },
                "second.example.com": {
                    "ok": False,
                    "domain": "second.example.com",
                    "ip": "203.0.113.99",
                    "status": "partial",
                    "detail": "2/6 endpoints reachable",
                    "checks": {
                        1: True,
                        2: "timeout",
                        3: True,
                        4: "timeout",
                        5: "timeout",
                        203: "timeout",
                    },
                },
            }[domain],
        ):
            selected_domain, result = cfproxy_diagnostics.run_auto_test(
                ["first.example.com", "second.example.com"]
            )

        self.assertEqual(selected_domain, "first.example.com")
        self.assertFalse(result["ok"])
        self.assertEqual(result["domain"], "first.example.com")
        self.assertEqual(result["ip"], "203.0.113.99")
        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["detail"], "3/6 endpoints reachable")
        self.assertEqual(result["checks"][1], True)
        self.assertEqual(result["checks"][2], True)
        self.assertEqual(result["checks"][3], True)
        self.assertEqual(result["mode"], "auto")
        self.assertEqual(result["selected_domain"], "first.example.com")


if __name__ == "__main__":
    unittest.main()
