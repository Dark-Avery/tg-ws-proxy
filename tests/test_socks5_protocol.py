import json
import hashlib
import struct
import unittest
from unittest.mock import patch
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from proxy.tg_ws_proxy import (
    PROTO_TAG_ABRIDGED,
    PROTO_TAG_INTERMEDIATE,
    RawWebSocket,
    _build_relay_handshake,
    _generate_relay_init,
    _parse_relay_url,
    _try_relay_ws,
    _try_handshake,
)


KEY = bytes(range(32))
IV = bytes(range(16))
SECRET = bytes.fromhex("0123456789abcdef0123456789abcdef")


def _xor(left: bytes, right: bytes) -> bytes:
    return bytes(a ^ b for a, b in zip(left, right))


def _build_client_handshake(dc_raw: int, proto_tag: bytes) -> bytes:
    packet = bytearray(64)
    packet[8:40] = KEY
    packet[40:56] = IV

    dec_key = hashlib.sha256(KEY + SECRET).digest()
    decryptor = Cipher(algorithms.AES(dec_key), modes.CTR(IV)).encryptor()
    keystream = decryptor.update(b"\x00" * 64)

    plain_tail = proto_tag + struct.pack("<h", dc_raw) + b"\x00\x00"
    packet[56:64] = _xor(plain_tail, keystream[56:64])
    return bytes(packet)


class MtProtoProtocolTests(unittest.TestCase):
    def test_try_handshake_accepts_abridged_proto(self):
        handshake = _build_client_handshake(2, PROTO_TAG_ABRIDGED)

        result = _try_handshake(handshake, SECRET)

        self.assertIsNotNone(result)
        self.assertEqual(result[:3], (2, False, PROTO_TAG_ABRIDGED))

    def test_try_handshake_accepts_intermediate_proto(self):
        handshake = _build_client_handshake(-4, PROTO_TAG_INTERMEDIATE)

        result = _try_handshake(handshake, SECRET)

        self.assertIsNotNone(result)
        self.assertEqual(result[:3], (4, True, PROTO_TAG_INTERMEDIATE))

    def test_generate_relay_init_produces_handshake_sized_packet(self):
        relay_init = _generate_relay_init(PROTO_TAG_ABRIDGED, -2)

        self.assertEqual(len(relay_init), 64)
        self.assertEqual(relay_init[0], relay_init[0] & 0xFF)

    def test_parse_relay_url_supports_default_connect_path(self):
        parsed = _parse_relay_url("wss://relay.example.com")

        self.assertEqual(parsed["host"], "relay.example.com")
        self.assertEqual(parsed["port"], 443)
        self.assertTrue(parsed["use_tls"])
        self.assertEqual(parsed["path"], "/connect")

    def test_build_relay_handshake_matches_protocol_v1_shape(self):
        payload = json.loads(
            _build_relay_handshake(
                dc=2,
                is_media=True,
                target_ip="149.154.167.220",
                relay_token="secret-token",
                domains=["kws2.web.telegram.org", "kws2-1.web.telegram.org"],
            )
        )

        self.assertEqual(payload["version"], 1)
        self.assertEqual(payload["mode"], "telegram_ws")
        self.assertEqual(payload["dc"], 2)
        self.assertTrue(payload["media"])
        self.assertEqual(payload["target_ip"], "149.154.167.220")
        self.assertEqual(
            payload["domains"],
            ["kws2.web.telegram.org", "kws2-1.web.telegram.org"],
        )
        self.assertEqual(payload["auth_token"], "secret-token")

    def test_raw_websocket_send_text_writes_text_frame(self):
        class _Writer:
            def __init__(self):
                self.chunks = []

            def write(self, data):
                self.chunks.append(data)

            async def drain(self):
                return None

        async def _run():
            writer = _Writer()
            ws = RawWebSocket(reader=None, writer=writer)
            await ws.send_text('{"ok":true}')
            self.assertEqual(len(writer.chunks), 1)
            frame = writer.chunks[0]
            self.assertEqual(frame[0] & 0x0F, RawWebSocket.OP_TEXT)

        import asyncio
        asyncio.run(_run())


class RelayHandshakeTests(unittest.IsolatedAsyncioTestCase):
    async def test_try_relay_ws_sends_text_handshake_and_accepts_ok_response(self):
        class _FakeRelaySocket:
            def __init__(self):
                self.sent_text = []
                self.closed = False

            async def send_text(self, text):
                self.sent_text.append(text)

            async def recv(self):
                return json.dumps({"ok": True}).encode("utf-8")

            async def close(self):
                self.closed = True

        fake_ws = _FakeRelaySocket()
        with patch("proxy.tg_ws_proxy.RawWebSocket.connect",
                   return_value=fake_ws):
            ws = await _try_relay_ws(
                dc=2,
                is_media=True,
                target="149.154.167.220",
                domains=["kws2.web.telegram.org", "kws2-1.web.telegram.org"],
                label="test",
                media_tag=" media",
                relay_url="wss://relay.example.com/connect",
                relay_token="secret-token",
            )

        self.assertIs(ws, fake_ws)
        self.assertEqual(len(fake_ws.sent_text), 1)
        payload = json.loads(fake_ws.sent_text[0])
        self.assertEqual(payload["auth_token"], "secret-token")
        self.assertEqual(payload["dc"], 2)
        self.assertTrue(payload["media"])


if __name__ == "__main__":
    unittest.main()
