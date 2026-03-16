import os
import threading
import time
from pathlib import Path
from typing import Iterable, Optional

from proxy.app_runtime import ProxyAppRuntime


_RUNTIME_LOCK = threading.RLock()
_RUNTIME: Optional[ProxyAppRuntime] = None
_LAST_ERROR: Optional[str] = None


def _remember_error(message: str) -> None:
    global _LAST_ERROR
    _LAST_ERROR = message


def _normalize_dc_ip_list(dc_ip_list: Iterable[object]) -> list[str]:
    return [str(item).strip() for item in dc_ip_list if str(item).strip()]


def start_proxy(app_dir: str, host: str, port: int,
                dc_ip_list: Iterable[object], verbose: bool = False) -> str:
    global _RUNTIME, _LAST_ERROR

    with _RUNTIME_LOCK:
        if _RUNTIME is not None:
            _RUNTIME.stop_proxy()
            _RUNTIME = None

        _LAST_ERROR = None
        os.environ["TG_WS_PROXY_CRYPTO_BACKEND"] = "python"

        runtime = ProxyAppRuntime(
            Path(app_dir),
            logger_name="tg-ws-android",
            on_error=_remember_error,
        )
        runtime.reset_log_file()
        runtime.setup_logging(verbose=verbose)

        config = {
            "host": host,
            "port": int(port),
            "dc_ip": _normalize_dc_ip_list(dc_ip_list),
            "verbose": bool(verbose),
        }
        runtime.save_config(config)

        if not runtime.start_proxy(config):
            _RUNTIME = None
            raise RuntimeError(_LAST_ERROR or "Failed to start proxy runtime.")

        _RUNTIME = runtime

    # Give the proxy thread a short warm-up window so immediate bind failures
    # surface before Kotlin reports the service as running.
    for _ in range(10):
        time.sleep(0.1)
        with _RUNTIME_LOCK:
            if _LAST_ERROR:
                runtime.stop_proxy()
                _RUNTIME = None
                raise RuntimeError(_LAST_ERROR)
            if runtime.is_proxy_running():
                return str(runtime.log_file)

    with _RUNTIME_LOCK:
        runtime.stop_proxy()
        _RUNTIME = None
    raise RuntimeError("Proxy runtime did not become ready in time.")


def stop_proxy() -> None:
    global _RUNTIME, _LAST_ERROR

    with _RUNTIME_LOCK:
        _LAST_ERROR = None
        if _RUNTIME is not None:
            _RUNTIME.stop_proxy()
            _RUNTIME = None


def is_running() -> bool:
    with _RUNTIME_LOCK:
        return bool(_RUNTIME and _RUNTIME.is_proxy_running())


def get_last_error() -> Optional[str]:
    return _LAST_ERROR
