from __future__ import annotations

import ctypes
import ipaddress
import json
import logging
import logging.handlers
import os
import winreg
import psutil
import sys
import threading
import time
import tkinter as tk
import webbrowser
from urllib.parse import urlparse
from pathlib import Path
import asyncio as _asyncio
from typing import Dict, Optional

try:
    import pyperclip
except ImportError:
    pyperclip = None

try:
    import pystray
except ImportError:
    pystray = None

try:
    import customtkinter as ctk
except ImportError:
    ctk = None

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:
    Image = ImageDraw = ImageFont = None

import proxy.tg_ws_proxy as tg_ws_proxy
from proxy import __version__
from utils.default_config import default_tray_config
from ui.ctk_tray_ui import (
    install_tray_config_buttons,
    install_tray_config_form,
    populate_first_run_window,
    tray_settings_scroll_and_footer,
    validate_config_form,
)
from ui.ctk_theme import (
    CONFIG_DIALOG_FRAME_PAD,
    CONFIG_DIALOG_SIZE,
    FIRST_RUN_SIZE,
    create_ctk_root,
    ctk_theme_for_platform,
    main_content_frame,
)
from proxy.app_runtime import ProxyAppRuntime


IS_FROZEN = bool(getattr(sys, "frozen", False))

APP_NAME = "TgWsProxy"
APP_DIR = Path(os.environ.get("APPDATA", Path.home())) / APP_NAME
FIRST_RUN_MARKER = APP_DIR / ".first_run_done"
IPV6_WARN_MARKER = APP_DIR / ".ipv6_warned"

DEFAULT_CONFIG = default_tray_config()
_tray_icon: Optional[object] = None
_config: dict = {}
_exiting: bool = False
_lock_file_path: Optional[Path] = None

log = logging.getLogger("tg-ws-tray")
_runtime = ProxyAppRuntime(
    APP_DIR,
    default_config=DEFAULT_CONFIG,
    logger_name="tg-ws-tray",
    on_error=lambda text: _show_error(text),
)
CONFIG_FILE = _runtime.config_file
LOG_FILE = _runtime.log_file
UPSTREAM_MODE_DIRECT = "telegram_ws_direct"
UPSTREAM_MODE_AUTO = "auto"
UPSTREAM_MODE_RELAY = "relay_ws"


def _normalize_upstream_mode(value: Optional[str]) -> str:
    if value in (UPSTREAM_MODE_DIRECT, UPSTREAM_MODE_AUTO, UPSTREAM_MODE_RELAY):
        return value
    return UPSTREAM_MODE_DIRECT


def _relay_host(relay_url: Optional[str]) -> Optional[str]:
    if not relay_url:
        return None
    try:
        host = urlparse(relay_url.strip()).hostname
    except Exception:
        return None
    if host:
        return host
    return None


def _upstream_mode_label(value: Optional[str]) -> str:
    normalized = _normalize_upstream_mode(value)
    if normalized == UPSTREAM_MODE_AUTO:
        return "Auto: direct -> relay -> TCP"
    if normalized == UPSTREAM_MODE_RELAY:
        return "Relay only"
    return "Direct Telegram WS"


def _upstream_mode_summary(value: Optional[str],
                           relay_url: Optional[str] = None) -> str:
    normalized = _normalize_upstream_mode(value)
    relay_host = _relay_host(relay_url)
    if normalized == UPSTREAM_MODE_AUTO:
        if relay_host:
            return (
                "Сначала direct Telegram WS, затем relay "
                f"{relay_host}, затем direct TCP fallback."
            )
        return (
            "Сначала direct Telegram WS. Укажите relay URL, "
            "чтобы добавить relay fallback перед direct TCP."
        )
    if normalized == UPSTREAM_MODE_RELAY:
        if relay_host:
            return f"Сначала relay {relay_host}, затем direct TCP fallback."
        return "Сначала relay, затем direct TCP fallback."
    return "Используется direct Telegram WS, затем direct TCP fallback."


def _validate_relay_url(value: str) -> bool:
    try:
        parsed = urlparse(value.strip())
    except Exception:
        return False
    return parsed.scheme in ("ws", "wss") and bool(parsed.hostname)


def _format_timeout_seconds(value: object) -> str:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        numeric = float(DEFAULT_CONFIG["direct_ws_timeout_seconds"])
    if numeric.is_integer():
        return str(int(numeric))
    return str(numeric)


def _bind_text_context_menu(widget):
    target = getattr(widget, "_entry", None) or getattr(widget, "_textbox", None) or widget
    menu = tk.Menu(target, tearoff=0)

    def _select_all():
        try:
            target.selection_range(0, "end")
            target.icursor("end")
        except Exception:
            try:
                target.tag_add("sel", "1.0", "end-1c")
                target.mark_set("insert", "end-1c")
                target.see("insert")
            except Exception:
                pass

    menu.add_command(label="Вырезать", command=lambda: target.event_generate("<<Cut>>"))
    menu.add_command(label="Копировать", command=lambda: target.event_generate("<<Copy>>"))
    menu.add_command(label="Вставить", command=lambda: target.event_generate("<<Paste>>"))
    menu.add_separator()
    menu.add_command(label="Выделить всё", command=_select_all)

    def _popup(event):
        try:
            target.focus_force()
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()
        return "break"

    target.bind("<Button-3>", _popup, add="+")

_user32 = ctypes.windll.user32
_user32.MessageBoxW.argtypes = [
    ctypes.c_void_p,
    ctypes.c_wchar_p,
    ctypes.c_wchar_p,
    ctypes.c_uint,
]
_user32.MessageBoxW.restype = ctypes.c_int


def _same_process(lock_meta: dict, proc: psutil.Process) -> bool:
    try:
        lock_ct = float(lock_meta.get("create_time", 0.0))
        proc_ct = float(proc.create_time())
        if lock_ct > 0 and abs(lock_ct - proc_ct) > 1.0:
            return False
    except Exception:
        return False

    try:
        for arg in proc.cmdline():
            if "windows.py" in arg:
                return True
    except Exception:
        pass

    frozen = bool(getattr(sys, "frozen", False))
    if frozen:
        return (
            os.path.basename(sys.executable).lower() == proc.name().lower()
        )

    return False


def _release_lock():
    global _lock_file_path
    if not _lock_file_path:
        return
    try:
        _lock_file_path.unlink(missing_ok=True)
    except Exception:
        pass
    _lock_file_path = None


def _acquire_lock() -> bool:
    global _lock_file_path
    _ensure_dirs()
    lock_files = list(APP_DIR.glob("*.lock"))

    for f in lock_files:
        pid = None
        meta: dict = {}

        try:
            pid = int(f.stem)
        except Exception:
            f.unlink(missing_ok=True)
            continue

        try:
            raw = f.read_text(encoding="utf-8").strip()
            if raw:
                meta = json.loads(raw)
        except Exception:
            meta = {}

        try:
            proc = psutil.Process(pid)
            if _same_process(meta, proc):
                return False
        except Exception:
            pass

        f.unlink(missing_ok=True)

    lock_file = APP_DIR / f"{os.getpid()}.lock"
    try:
        proc = psutil.Process(os.getpid())
        payload = {
            "create_time": proc.create_time(),
        }
        lock_file.write_text(json.dumps(payload, ensure_ascii=False),
                             encoding="utf-8")
    except Exception:
        lock_file.touch()

    _lock_file_path = lock_file
    return True


def _ensure_dirs():
    _runtime.ensure_dirs()


def load_config() -> dict:
    return _runtime.load_config()


def save_config(cfg: dict):
    _runtime.save_config(cfg)


def setup_logging(verbose: bool = False, log_max_mb: float = 5):
    _runtime.setup_logging(verbose, log_max_mb=log_max_mb)


def _autostart_reg_name() -> str:
    return APP_NAME


def _supports_autostart() -> bool:
    return IS_FROZEN


def _autostart_command() -> str:
    return f'"{sys.executable}"'


def is_autostart_enabled() -> bool:
    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Run",
            0,
            winreg.KEY_READ,
        ) as k:
            val, _ = winreg.QueryValueEx(k, _autostart_reg_name())
        stored = str(val).strip()
        expected = _autostart_command().strip()
        return stored == expected
    except FileNotFoundError:
        return False
    except OSError:
        return False


def set_autostart_enabled(enabled: bool) -> None:
    try:
        with winreg.CreateKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Run",
        ) as k:
            if enabled:
                winreg.SetValueEx(
                    k,
                    _autostart_reg_name(),
                    0,
                    winreg.REG_SZ,
                    _autostart_command(),
                )
            else:
                try:
                    winreg.DeleteValue(k, _autostart_reg_name())
                except FileNotFoundError:
                    pass
    except OSError as exc:
        log.error("Failed to update autostart: %s", exc)
        _show_error(
            "Не удалось изменить автозапуск.\n\n"
            "Попробуйте запустить приложение от имени пользователя с правами на реестр.\n\n"
            f"Ошибка: {exc}"
        )


def _make_icon_image(size: int = 64):
    if Image is None:
        raise RuntimeError("Pillow is required for tray icon")
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    
    margin = 2
    draw.ellipse([margin, margin, size - margin, size - margin],
                 fill=(0, 136, 204, 255))
                 
    try:
        font = ImageFont.truetype("arial.ttf", size=int(size * 0.55))
    except Exception:
        font = ImageFont.load_default()
    bbox = draw.textbbox((0, 0), "T", font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    tx = (size - tw) // 2 - bbox[0]
    ty = (size - th) // 2 - bbox[1]
    draw.text((tx, ty), "T", fill=(255, 255, 255, 255), font=font)

    return img


def _load_icon():
    icon_path = Path(__file__).parent / "icon.ico"
    if icon_path.exists() and Image:
        try:
            return Image.open(str(icon_path))
        except Exception:
            pass
    return _make_icon_image()

def start_proxy():
    _runtime.start_proxy(_config)


def stop_proxy():
    _runtime.stop_proxy()


def restart_proxy():
    _runtime.restart_proxy()


def _show_error(text: str, title: str = "TG WS Proxy — Ошибка"):
    _user32.MessageBoxW(None, text, title, 0x10)


def _show_info(text: str, title: str = "TG WS Proxy"):
    _user32.MessageBoxW(None, text, title, 0x40)


def _ask_open_release_page(latest_version: str, url: str) -> bool:
    """Win32 Yes/No: открыть страницу релиза."""
    MB_YESNO = 0x4
    MB_ICONQUESTION = 0x20
    IDYES = 6
    text = (
        f"Доступна новая версия: {latest_version}\n\n"
        f"Открыть страницу релиза в браузере?"
    )
    r = _user32.MessageBoxW(
        None,
        text,
        "TG WS Proxy — обновление",
        MB_YESNO | MB_ICONQUESTION,
    )
    return r == IDYES


def _maybe_notify_update_async():
    """
    Фоновая проверка GitHub Releases и уведомление (не блокирует трей).
    """
    def _work():
        time.sleep(1.5)
        if _exiting:
            return
        if not _config.get("check_updates", True):
            return
        try:
            from utils.update_check import RELEASES_PAGE_URL, get_status, run_check
            run_check(__version__)
            st = get_status()
            if not st.get("has_update"):
                return
            url = (st.get("html_url") or "").strip() or RELEASES_PAGE_URL
            ver = st.get("latest") or "?"
            if _ask_open_release_page(str(ver), url):
                webbrowser.open(url)
        except Exception as exc:
            log.debug("Update check failed: %s", exc)

    threading.Thread(target=_work, daemon=True, name="update-check").start()


def _on_open_in_telegram(icon=None, item=None):
    host = _config.get("host", DEFAULT_CONFIG["host"])
    port = _config.get("port", DEFAULT_CONFIG["port"])
    url = f"tg://socks?server={host}&port={port}"
    log.info("Opening %s", url)
    try:
        result = webbrowser.open(url)
        if not result:
            raise RuntimeError("webbrowser.open returned False")
    except Exception:
        log.info("Browser open failed, copying to clipboard")
        if pyperclip is None:
            _show_error(
                "Не удалось открыть Telegram автоматически.\n\n"
                f"Установите пакет pyperclip для копирования в буфер или откройте вручную:\n{url}")
            return
        try:
            pyperclip.copy(url)
            _show_info(
                f"Не удалось открыть Telegram автоматически.\n\n"
                f"Ссылка скопирована в буфер обмена, отправьте её в Telegram и нажмите по ней ЛКМ:\n{url}",
                "TG WS Proxy")
        except Exception as exc:
            log.error("Clipboard copy failed: %s", exc)
            _show_error(f"Не удалось скопировать ссылку:\n{exc}")


def _on_restart(icon=None, item=None):
    threading.Thread(target=restart_proxy, daemon=True).start()


def _on_edit_config(icon=None, item=None):
    threading.Thread(target=_edit_config_dialog, daemon=True).start()


def _edit_config_dialog():
    if ctk is None:
        _show_error("customtkinter не установлен.")
        return

    cfg = dict(_config)
    cfg["autostart"] = is_autostart_enabled()

    # Make sure that the autostart key is removed if autostart
    # is disabled, even if the executable file is moved.
    if _supports_autostart() and not cfg["autostart"]:
        set_autostart_enabled(False)
    theme = ctk_theme_for_platform()
    w, h = CONFIG_DIALOG_SIZE
    if _supports_autostart():
        h += 100

    icon_path = str(Path(__file__).parent / "icon.ico")

    root = create_ctk_root(
        ctk,
        title="TG WS Proxy — Настройки",
        width=w,
        height=h,
        theme=theme,
        after_create=lambda r: r.iconbitmap(icon_path),
    )

    fpx, fpy = CONFIG_DIALOG_FRAME_PAD
    frame = main_content_frame(ctk, root, theme, padx=fpx, pady=fpy)

    scroll, footer = tray_settings_scroll_and_footer(ctk, frame, theme)

    widgets = install_tray_config_form(
        ctk,
        scroll,
        theme,
        cfg,
        DEFAULT_CONFIG,
        show_autostart=_supports_autostart(),
        autostart_value=cfg.get("autostart", False),
    )

    route_wrap = ctk.CTkFrame(scroll, fg_color="transparent")
    route_wrap.pack(fill="x", pady=(0, 6))
    ctk.CTkLabel(
        route_wrap,
        text="Маршрут upstream",
        font=(theme.ui_font_family, 12, "bold"),
        text_color=theme.text_primary,
        anchor="w",
    ).pack(anchor="w", pady=(0, 2))
    route_card = ctk.CTkFrame(
        route_wrap,
        fg_color=theme.field_bg,
        corner_radius=10,
        border_width=1,
        border_color=theme.field_border,
    )
    route_card.pack(fill="x")
    route_inner = ctk.CTkFrame(route_card, fg_color="transparent")
    route_inner.pack(fill="x", padx=10, pady=8)

    upstream_mode = _normalize_upstream_mode(
        cfg.get("upstream_mode", DEFAULT_CONFIG["upstream_mode"]))
    upstream_options = {
        "Direct Telegram WS": UPSTREAM_MODE_DIRECT,
        "Auto: direct -> relay -> TCP": UPSTREAM_MODE_AUTO,
        "Relay only": UPSTREAM_MODE_RELAY,
    }
    upstream_label_by_value = {
        value: label for label, value in upstream_options.items()
    }
    upstream_var = ctk.StringVar(
        value=upstream_label_by_value.get(upstream_mode, "Direct Telegram WS")
    )
    ctk.CTkLabel(
        route_inner,
        text="Режим маршрута",
        font=(theme.ui_font_family, 12),
        text_color=theme.text_secondary,
        anchor="w",
    ).pack(anchor="w", pady=(0, 2))
    upstream_menu = ctk.CTkOptionMenu(
        route_inner,
        variable=upstream_var,
        values=list(upstream_options.keys()),
        height=36,
        font=(theme.ui_font_family, 13),
        corner_radius=10,
        fg_color=theme.bg,
        button_color=theme.tg_blue,
        button_hover_color=theme.tg_blue_hover,
        text_color=theme.text_primary,
        dropdown_font=(theme.ui_font_family, 13),
    )
    upstream_menu.pack(fill="x", pady=(0, 8))

    relay_frame = ctk.CTkFrame(route_inner, fg_color="transparent")
    relay_url_var = ctk.StringVar(value=cfg.get("relay_url", ""))
    ctk.CTkLabel(
        relay_frame,
        text="Relay URL",
        font=(theme.ui_font_family, 12),
        text_color=theme.text_secondary,
        anchor="w",
    ).pack(anchor="w", pady=(0, 2))
    relay_url_entry = ctk.CTkEntry(
        relay_frame,
        textvariable=relay_url_var,
        height=36,
        font=(theme.ui_font_family, 13),
        corner_radius=10,
        fg_color=theme.bg,
        border_color=theme.field_border,
        border_width=1,
        text_color=theme.text_primary,
    )
    relay_url_entry.pack(fill="x", pady=(0, 8))
    _bind_text_context_menu(relay_url_entry)

    relay_token_var = ctk.StringVar(value=cfg.get("relay_token", ""))
    ctk.CTkLabel(
        relay_frame,
        text="Relay token",
        font=(theme.ui_font_family, 12),
        text_color=theme.text_secondary,
        anchor="w",
    ).pack(anchor="w", pady=(0, 2))
    relay_token_entry = ctk.CTkEntry(
        relay_frame,
        textvariable=relay_token_var,
        height=36,
        font=(theme.ui_font_family, 13),
        corner_radius=10,
        fg_color=theme.bg,
        border_color=theme.field_border,
        border_width=1,
        text_color=theme.text_primary,
    )
    relay_token_entry.pack(fill="x")
    _bind_text_context_menu(relay_token_entry)

    direct_ws_timeout_frame = ctk.CTkFrame(route_inner, fg_color="transparent")
    ctk.CTkLabel(
        direct_ws_timeout_frame,
        text="Таймаут direct WS перед relay (сек)",
        font=(theme.ui_font_family, 12),
        text_color=theme.text_secondary,
        anchor="w",
    ).pack(anchor="w", pady=(0, 2))
    direct_ws_timeout_var = ctk.StringVar(
        value=_format_timeout_seconds(
            cfg.get(
                "direct_ws_timeout_seconds",
                DEFAULT_CONFIG["direct_ws_timeout_seconds"],
            )
        )
    )
    direct_ws_timeout_entry = ctk.CTkEntry(
        direct_ws_timeout_frame,
        textvariable=direct_ws_timeout_var,
        width=140,
        height=36,
        font=(theme.ui_font_family, 13),
        corner_radius=10,
        fg_color=theme.bg,
        border_color=theme.field_border,
        border_width=1,
        text_color=theme.text_primary,
    )
    direct_ws_timeout_entry.pack(anchor="w")
    _bind_text_context_menu(direct_ws_timeout_entry)

    upstream_summary_var = ctk.StringVar(
        value=_upstream_mode_summary(upstream_mode, relay_url_var.get())
    )
    upstream_summary_label = ctk.CTkLabel(
        route_inner,
        textvariable=upstream_summary_var,
        font=(theme.ui_font_family, 11),
        text_color=theme.text_secondary,
        anchor="w",
        justify="left",
        wraplength=396,
    )
    upstream_summary_label.pack(anchor="w", pady=(8, 0))

    def update_upstream_controls(*_args):
        selected_mode = upstream_options.get(
            upstream_var.get(), UPSTREAM_MODE_DIRECT)
        relay_needed = selected_mode in (UPSTREAM_MODE_AUTO, UPSTREAM_MODE_RELAY)
        timeout_needed = selected_mode == UPSTREAM_MODE_AUTO
        if relay_needed:
            relay_frame.pack(fill="x", pady=(0, 8), before=upstream_summary_label)
        else:
            relay_frame.pack_forget()
        if timeout_needed:
            direct_ws_timeout_frame.pack(anchor="w", pady=(0, 0), before=upstream_summary_label)
        else:
            direct_ws_timeout_frame.pack_forget()
        upstream_summary_var.set(
            _upstream_mode_summary(selected_mode, relay_url_var.get()))

    upstream_var.trace_add("write", update_upstream_controls)
    relay_url_var.trace_add("write", update_upstream_controls)
    update_upstream_controls()

    def on_save():
        merged = validate_config_form(
            widgets,
            DEFAULT_CONFIG,
            include_autostart=_supports_autostart(),
        )
        if isinstance(merged, str):
            _show_error(merged)
            return
        upstream_mode_val = upstream_options.get(
            upstream_var.get(), UPSTREAM_MODE_DIRECT)
        relay_url_val = relay_url_var.get().strip()
        relay_token_val = relay_token_var.get().strip()
        try:
            direct_ws_timeout_val = float(direct_ws_timeout_var.get().strip())
            if direct_ws_timeout_val <= 0:
                raise ValueError
        except ValueError:
            _show_error("Таймаут direct WS должен быть положительным числом.")
            return
        if upstream_mode_val == UPSTREAM_MODE_RELAY and not relay_url_val:
            _show_error("Укажите relay URL для режима Relay only.")
            return
        if relay_url_val and not _validate_relay_url(relay_url_val):
            _show_error(
                "Relay URL должен быть в формате ws://host/path "
                "или wss://host/path.")
            return

        new_cfg = dict(merged)
        new_cfg.update({
            "upstream_mode": upstream_mode_val,
            "relay_url": relay_url_val,
            "relay_token": relay_token_val,
            "direct_ws_timeout_seconds": direct_ws_timeout_val,
        })
        save_config(new_cfg)
        _config.update(new_cfg)
        log.info("Config saved: %s", new_cfg)

        if _supports_autostart():
            set_autostart_enabled(bool(new_cfg.get("autostart", False)))

        _tray_icon.menu = _build_menu()

        # Win32 MessageBox из того же потока, что и mainloop CTk, блокирует обработку Tcl/Tk
        # и даёт зависание; tkinter.messagebox согласован с циклом окна.
        from tkinter import messagebox
        if messagebox.askyesno("Перезапустить?",
                               "Настройки сохранены.\n\n"
                               "Перезапустить прокси сейчас?",
                               parent=root):
            root.destroy()
            restart_proxy()
        else:
            root.destroy()

    def on_cancel():
        root.destroy()

    install_tray_config_buttons(
        ctk, footer, theme, on_save=on_save, on_cancel=on_cancel)

    try:
        root.mainloop()
    finally:
        import tkinter as tk
        try:
            if root.winfo_exists():
                root.destroy()
        except tk.TclError:
            pass


def _on_open_logs(icon=None, item=None):
    log.info("Opening log file: %s", LOG_FILE)
    if LOG_FILE.exists():
        os.startfile(str(LOG_FILE))
    else:
        _show_info("Файл логов ещё не создан.", "TG WS Proxy")


def _on_exit(icon=None, item=None):
    global _exiting
    if _exiting:
        os._exit(0)
        return
    _exiting = True
    log.info("User requested exit")

    def _force_exit():
        time.sleep(3)
        os._exit(0)
    threading.Thread(target=_force_exit, daemon=True, name="force-exit").start()

    if icon:
        icon.stop()



def _show_first_run():
    _ensure_dirs()
    if FIRST_RUN_MARKER.exists():
        return

    host = _config.get("host", DEFAULT_CONFIG["host"])
    port = _config.get("port", DEFAULT_CONFIG["port"])

    if ctk is None:
        FIRST_RUN_MARKER.touch()
        return

    theme = ctk_theme_for_platform()
    icon_path = str(Path(__file__).parent / "icon.ico")
    w, h = FIRST_RUN_SIZE
    root = create_ctk_root(
        ctk,
        title="TG WS Proxy",
        width=w,
        height=h,
        theme=theme,
        after_create=lambda r: r.iconbitmap(icon_path),
    )

    def on_done(open_tg: bool):
        FIRST_RUN_MARKER.touch()
        root.destroy()
        if open_tg:
            _on_open_in_telegram()

    populate_first_run_window(
        ctk, root, theme, host=host, port=port, on_done=on_done)

    try:
        root.mainloop()
    finally:
        import tkinter as tk
        try:
            if root.winfo_exists():
                root.destroy()
        except tk.TclError:
            pass


def _has_ipv6_enabled() -> bool:
    import socket as _sock
    try:
        addrs = _sock.getaddrinfo(_sock.gethostname(), None, _sock.AF_INET6)
        for addr in addrs:
            ip = addr[4][0]
            if not ip or ip.startswith("::1"):
                continue
            try:
                if ipaddress.IPv6Address(ip).is_link_local:
                    continue
            except ValueError:
                if ip.startswith("fe80:"):
                    continue
            return True
    except Exception:
        pass
    try:
        s = _sock.socket(_sock.AF_INET6, _sock.SOCK_STREAM)
        s.bind(('::1', 0))
        s.close()
        return True
    except Exception:
        return False


def _check_ipv6_warning():
    _ensure_dirs()
    if IPV6_WARN_MARKER.exists():
        return
    if not _has_ipv6_enabled():
        return

    IPV6_WARN_MARKER.touch()

    threading.Thread(target=_show_ipv6_dialog, daemon=True).start()


def _show_ipv6_dialog():
    _show_info(
        "На вашем компьютере включена поддержка подключения по IPv6.\n\n"
        "Telegram может пытаться подключаться через IPv6, "
        "что не поддерживается и может привести к ошибкам.\n\n"
        "Если прокси не работает или в логах присутствуют ошибки, "
        "связанные с попытками подключения по IPv6 - "
        "попробуйте отключить в настройках прокси Telegram попытку соединения "
        "по IPv6. Если данная мера не помогает, попробуйте отключить IPv6 "
        "в системе.\n\n"
        "Это предупреждение будет показано только один раз.",
        "TG WS Proxy")


def _build_menu():
    if pystray is None:
        return None
    host = _config.get("host", DEFAULT_CONFIG["host"])
    port = _config.get("port", DEFAULT_CONFIG["port"])
    upstream_mode = _config.get("upstream_mode", DEFAULT_CONFIG["upstream_mode"])
    relay_url = _config.get("relay_url", DEFAULT_CONFIG["relay_url"])
    return pystray.Menu(
        pystray.MenuItem(
            f"Открыть в Telegram ({host}:{port})",
            _on_open_in_telegram,
            default=True),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem(
            f"Маршрут: {_upstream_mode_label(upstream_mode)}",
            lambda icon, item: None,
            enabled=False),
        pystray.MenuItem(
            _upstream_mode_summary(upstream_mode, relay_url),
            lambda icon, item: None,
            enabled=False),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Перезапустить прокси", _on_restart),
        pystray.MenuItem("Настройки...", _on_edit_config),
        pystray.MenuItem("Открыть логи", _on_open_logs),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Выход", _on_exit),
    )


def run_tray():
    global _tray_icon, _config

    _config = _runtime.prepare()
    _runtime.reset_log_file()

    setup_logging(_config.get("verbose", False),
                  log_max_mb=_config.get("log_max_mb", DEFAULT_CONFIG["log_max_mb"]))
    log.info("TG WS Proxy версия %s, tray app starting", __version__)
    log.info("Config: %s", _config)
    log.info("Log file: %s", LOG_FILE)

    if pystray is None or Image is None or ctk is None:
        log.error(
            "pystray, Pillow or customtkinter not installed; "
            "running in console mode")
        start_proxy()
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            stop_proxy()
        return

    start_proxy()

    _maybe_notify_update_async()

    _show_first_run()
    _check_ipv6_warning()

    icon_image = _load_icon()
    _tray_icon = pystray.Icon(
        APP_NAME,
        icon_image,
        "TG WS Proxy",
        menu=_build_menu())

    log.info("Tray icon running")
    _tray_icon.run()

    stop_proxy()
    log.info("Tray app exited")


def main():
    if not _acquire_lock():
        _show_info("Приложение уже запущено.", os.path.basename(sys.argv[0]))
        return

    try:
        run_tray()
    finally:
        _release_lock()


if __name__ == "__main__":
    main()
