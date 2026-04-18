from __future__ import annotations

import base64
import os
import socket as _socket
import ssl
from typing import Iterable


CFPROXY_TEST_DCS: tuple[int, ...] = (1, 2, 3, 4, 5, 203)


def _probe_host(ctx: ssl.SSLContext, host: str) -> tuple[bool, str, str]:
    try:
        with _socket.create_connection((host, 443), timeout=5) as raw:
            with ctx.wrap_socket(raw, server_hostname=host) as ssock:
                ws_key = base64.b64encode(os.urandom(16)).decode()
                request = (
                    "GET /apiws HTTP/1.1\r\n"
                    f"Host: {host}\r\n"
                    "Upgrade: websocket\r\n"
                    "Connection: Upgrade\r\n"
                    f"Sec-WebSocket-Key: {ws_key}\r\n"
                    "Sec-WebSocket-Version: 13\r\n"
                    "Sec-WebSocket-Protocol: binary\r\n"
                    "\r\n"
                ).encode()
                ssock.sendall(request)
                ssock.settimeout(5)
                buf = b""
                while b"\r\n\r\n" not in buf:
                    chunk = ssock.recv(512)
                    if not chunk:
                        break
                    buf += chunk
                first_line = buf.decode("utf-8", errors="replace").split("\r\n")[0]
                peer = ssock.getpeername()
                ip = str(peer[0]) if peer else ""
                if "101" in first_line:
                    return True, "", ip
                return False, first_line or "нет ответа", ip
    except _socket.timeout:
        return False, "таймаут", ""
    except OSError as exc:
        message = str(exc)
        return False, message[:60] if len(message) > 60 else message, ""


def run_connectivity_test(domain: str) -> dict:
    domain = str(domain or "").strip()
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE

    checks: dict[int, bool | str] = {}
    first_ip = ""
    success_count = 0
    for dc in CFPROXY_TEST_DCS:
        ok, detail, ip = _probe_host(ctx, f"kws{dc}.{domain}")
        if ok:
            checks[dc] = True
            success_count += 1
            if ip and not first_ip:
                first_ip = ip
        else:
            checks[dc] = detail

    total = len(CFPROXY_TEST_DCS)
    status = "ok" if success_count == total else "fail" if success_count == 0 else "partial"
    return {
        "ok": success_count == total,
        "domain": domain,
        "ip": first_ip,
        "status": status,
        "detail": f"{success_count}/{total} endpoints reachable",
        "checks": checks,
    }


def run_auto_test(domains: Iterable[str]) -> tuple[str | None, dict]:
    merged_checks: dict[int, bool | str] = {}
    selected_domain: str | None = None
    selected_ip = ""

    for domain in reversed(list(domains)):
        result = run_connectivity_test(domain)
        if result.get("ok"):
            result["mode"] = "auto"
            result["selected_domain"] = result.get("domain")
            return result.get("domain"), result

        for dc, value in result.get("checks", {}).items():
            if value is True:
                merged_checks[dc] = True
                selected_domain = result.get("domain")
                if result.get("ip"):
                    selected_ip = result["ip"]
            elif dc not in merged_checks:
                merged_checks[dc] = value

    if not merged_checks:
        best_result = {
            "ok": False,
            "domain": "",
            "ip": "",
            "status": "fail",
            "detail": "0/0 endpoints reachable",
            "checks": {},
        }
    else:
        success_count = sum(1 for value in merged_checks.values() if value is True)
        total = len(CFPROXY_TEST_DCS)
        best_result = {
            "ok": success_count == total,
            "domain": selected_domain or "",
            "ip": selected_ip,
            "status": "ok" if success_count == total else "partial" if success_count else "fail",
            "detail": f"{success_count}/{total} endpoints reachable",
            "checks": merged_checks,
        }

    best_result["mode"] = "auto"
    best_result["selected_domain"] = selected_domain
    return selected_domain, best_result
