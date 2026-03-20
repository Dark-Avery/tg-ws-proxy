from __future__ import annotations

import ctypes
import json
import logging
import os
import winreg
import psutil
import sys
import threading
import time
import webbrowser
from urllib.parse import urlparse
import pystray
import pyperclip
import customtkinter as ctk
from pathlib import Path
import asyncio as _asyncio
from typing import Dict, Optional

from PIL import Image, ImageDraw, ImageFont

import proxy.tg_ws_proxy as tg_ws_proxy
from proxy.app_runtime import DEFAULT_CONFIG, ProxyAppRuntime


IS_FROZEN = bool(getattr(sys, "frozen", False))

APP_NAME = "TgWsProxy"
APP_DIR = Path(os.environ.get("APPDATA", Path.home())) / APP_NAME
FIRST_RUN_MARKER = APP_DIR / ".first_run_done"
IPV6_WARN_MARKER = APP_DIR / ".ipv6_warned"
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


def _same_process(lock_meta: dict, proc: psutil.Process) -> bool:
    try:
        lock_ct = float(lock_meta.get("create_time", 0.0))
        proc_ct = float(proc.create_time())
        if lock_ct > 0 and abs(lock_ct - proc_ct) > 1.0:
            return False
    except Exception:
        return False

    frozen = bool(getattr(sys, "frozen", False))
    if frozen:
        return os.path.basename(sys.executable) == proc.name()

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


def setup_logging(verbose: bool = False):
    _runtime.setup_logging(verbose)


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
    ctypes.windll.user32.MessageBoxW(0, text, title, 0x10)


def _show_info(text: str, title: str = "TG WS Proxy"):
    ctypes.windll.user32.MessageBoxW(0, text, title, 0x40)


def _on_open_in_telegram(icon=None, item=None):
    port = _config.get("port", DEFAULT_CONFIG["port"])
    url = f"tg://socks?server=127.0.0.1&port={port}"
    log.info("Opening %s", url)
    try:
        result = webbrowser.open(url)
        if not result:
            raise RuntimeError("webbrowser.open returned False")
    except Exception:
        log.info("Browser open failed, copying to clipboard")
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

    ctk.set_appearance_mode("light")
    ctk.set_default_color_theme("blue")

    root = ctk.CTk()
    root.title("TG WS Proxy — Настройки")
    root.resizable(True, True)
    root.attributes("-topmost", True)
    icon_path = str(Path(__file__).parent / "icon.ico")
    root.iconbitmap(icon_path)

    TG_BLUE = "#3390ec"
    TG_BLUE_HOVER = "#2b7cd4"
    BG = "#ffffff"
    FIELD_BG = "#f0f2f5"
    FIELD_BORDER = "#d6d9dc"
    TEXT_PRIMARY = "#000000"
    TEXT_SECONDARY = "#707579"
    FONT_FAMILY = "Segoe UI"

    sw = root.winfo_screenwidth()
    sh = root.winfo_screenheight()
    w = 460
    h = min(760, max(620, sh - 80))
    root.geometry(f"{w}x{h}+{(sw-w)//2}+{(sh-h)//2}")
    root.minsize(440, 620)
    root.configure(fg_color=BG)

    frame = ctk.CTkScrollableFrame(root, fg_color=BG, corner_radius=0)
    frame.pack(fill="both", expand=True, padx=24, pady=20)

    # Host
    ctk.CTkLabel(frame, text="IP-адрес прокси",
                 font=(FONT_FAMILY, 13), text_color=TEXT_PRIMARY,
                 anchor="w").pack(anchor="w", pady=(0, 4))
    host_var = ctk.StringVar(value=cfg.get("host", "127.0.0.1"))
    host_entry = ctk.CTkEntry(frame, textvariable=host_var, width=200, height=36,
                              font=(FONT_FAMILY, 13), corner_radius=10,
                              fg_color=FIELD_BG, border_color=FIELD_BORDER,
                              border_width=1, text_color=TEXT_PRIMARY)
    host_entry.pack(anchor="w", pady=(0, 12))

    # Port
    ctk.CTkLabel(frame, text="Порт прокси",
                 font=(FONT_FAMILY, 13), text_color=TEXT_PRIMARY,
                 anchor="w").pack(anchor="w", pady=(0, 4))
    port_var = ctk.StringVar(value=str(cfg.get("port", 1080)))
    port_entry = ctk.CTkEntry(frame, textvariable=port_var, width=120, height=36,
                              font=(FONT_FAMILY, 13), corner_radius=10,
                              fg_color=FIELD_BG, border_color=FIELD_BORDER,
                              border_width=1, text_color=TEXT_PRIMARY)
    port_entry.pack(anchor="w", pady=(0, 12))

    # DC-IP mappings
    ctk.CTkLabel(frame, text="DC → IP маппинги (по одному на строку, формат DC:IP)",
                 font=(FONT_FAMILY, 13), text_color=TEXT_PRIMARY,
                 anchor="w").pack(anchor="w", pady=(0, 4))
    dc_textbox = ctk.CTkTextbox(frame, width=370, height=120,
                                font=("Consolas", 12), corner_radius=10,
                                fg_color=FIELD_BG, border_color=FIELD_BORDER,
                                border_width=1, text_color=TEXT_PRIMARY)
    dc_textbox.pack(anchor="w", pady=(0, 12))
    dc_textbox.insert("1.0", "\n".join(cfg.get("dc_ip", DEFAULT_CONFIG["dc_ip"])))

    upstream_mode = _normalize_upstream_mode(
        cfg.get("upstream_mode", DEFAULT_CONFIG["upstream_mode"]))
    upstream_options = {
        "Direct Telegram WS": UPSTREAM_MODE_DIRECT,
        "Auto: direct -> relay -> TCP": UPSTREAM_MODE_AUTO,
        "Relay only": UPSTREAM_MODE_RELAY,
    }
    upstream_option_labels = list(upstream_options.keys())
    upstream_label_by_value = {
        value: label for label, value in upstream_options.items()
    }
    upstream_var = ctk.StringVar(
        value=upstream_label_by_value.get(
            upstream_mode,
            upstream_option_labels[0],
        )
    )

    ctk.CTkLabel(frame, text="Маршрут upstream",
                 font=(FONT_FAMILY, 13), text_color=TEXT_PRIMARY,
                 anchor="w").pack(anchor="w", pady=(0, 4))
    upstream_menu = ctk.CTkOptionMenu(
        frame,
        variable=upstream_var,
        values=upstream_option_labels,
        width=370,
        height=36,
        font=(FONT_FAMILY, 13),
        corner_radius=10,
        fg_color=FIELD_BG,
        button_color=TG_BLUE,
        button_hover_color=TG_BLUE_HOVER,
        text_color=TEXT_PRIMARY,
        dropdown_font=(FONT_FAMILY, 13),
    )
    upstream_menu.pack(anchor="w", pady=(0, 8))

    relay_frame = ctk.CTkFrame(frame, fg_color="transparent")
    relay_frame.pack(fill="x", pady=(0, 8))

    ctk.CTkLabel(relay_frame, text="Relay URL",
                 font=(FONT_FAMILY, 13), text_color=TEXT_PRIMARY,
                 anchor="w").pack(anchor="w", pady=(0, 4))
    relay_url_var = ctk.StringVar(value=cfg.get("relay_url", ""))
    relay_url_entry = ctk.CTkEntry(
        relay_frame, textvariable=relay_url_var, width=370, height=36,
        font=(FONT_FAMILY, 13), corner_radius=10,
        fg_color=FIELD_BG, border_color=FIELD_BORDER,
        border_width=1, text_color=TEXT_PRIMARY)
    relay_url_entry.pack(anchor="w", pady=(0, 10))

    ctk.CTkLabel(relay_frame, text="Relay token",
                 font=(FONT_FAMILY, 13), text_color=TEXT_PRIMARY,
                 anchor="w").pack(anchor="w", pady=(0, 4))
    relay_token_var = ctk.StringVar(value=cfg.get("relay_token", ""))
    relay_token_entry = ctk.CTkEntry(
        relay_frame, textvariable=relay_token_var, width=370, height=36,
        font=(FONT_FAMILY, 13), corner_radius=10,
        fg_color=FIELD_BG, border_color=FIELD_BORDER,
        border_width=1, text_color=TEXT_PRIMARY)
    relay_token_entry.pack(anchor="w", pady=(0, 8))

    ctk.CTkLabel(frame, text="Таймаут direct WS перед relay (сек)",
                 font=(FONT_FAMILY, 13), text_color=TEXT_PRIMARY,
                 anchor="w").pack(anchor="w", pady=(0, 4))
    direct_ws_timeout_var = ctk.StringVar(
        value=_format_timeout_seconds(
            cfg.get("direct_ws_timeout_seconds",
                    DEFAULT_CONFIG["direct_ws_timeout_seconds"])
        )
    )
    direct_ws_timeout_entry = ctk.CTkEntry(
        frame, textvariable=direct_ws_timeout_var, width=120, height=36,
        font=(FONT_FAMILY, 13), corner_radius=10,
        fg_color=FIELD_BG, border_color=FIELD_BORDER,
        border_width=1, text_color=TEXT_PRIMARY)
    direct_ws_timeout_entry.pack(anchor="w", pady=(0, 12))

    upstream_summary_var = ctk.StringVar(
        value=_upstream_mode_summary(upstream_mode, relay_url_var.get()))
    upstream_summary_label = ctk.CTkLabel(
        frame, textvariable=upstream_summary_var,
        font=(FONT_FAMILY, 11), text_color=TEXT_SECONDARY,
        anchor="w", justify="left", wraplength=370)
    upstream_summary_label.pack(anchor="w", pady=(0, 10))

    def update_upstream_controls(*_args):
        selected_mode = upstream_options.get(
            upstream_var.get(), UPSTREAM_MODE_DIRECT)
        relay_needed = selected_mode in (
            UPSTREAM_MODE_AUTO, UPSTREAM_MODE_RELAY)
        if relay_needed:
            relay_frame.pack(fill="x", pady=(0, 8), before=upstream_summary_label)
        else:
            relay_frame.pack_forget()
        upstream_summary_var.set(
            _upstream_mode_summary(selected_mode, relay_url_var.get()))

    upstream_var.trace_add("write", update_upstream_controls)
    relay_url_var.trace_add("write", update_upstream_controls)
    update_upstream_controls()

    # Verbose
    verbose_var = ctk.BooleanVar(value=cfg.get("verbose", False))
    ctk.CTkCheckBox(frame, text="Подробное логирование (verbose)",
                    variable=verbose_var, font=(FONT_FAMILY, 13),
                    text_color=TEXT_PRIMARY,
                    fg_color=TG_BLUE, hover_color=TG_BLUE_HOVER,
                    corner_radius=6, border_width=2,
                    border_color=FIELD_BORDER).pack(anchor="w", pady=(0, 8))

    autostart_var = None
    if _supports_autostart():
        autostart_var = ctk.BooleanVar(value=cfg["autostart"])
        ctk.CTkCheckBox(frame, text="Автозапуск при включении Windows",
                        variable=autostart_var, font=(FONT_FAMILY, 13),
                        text_color=TEXT_PRIMARY,
                        fg_color=TG_BLUE, hover_color=TG_BLUE_HOVER,
                        corner_radius=6, border_width=2,
                        border_color=FIELD_BORDER).pack(anchor="w", pady=(0, 8))
        ctk.CTkLabel(frame, text="При перемещении файла или открытии из другой папки\nавтозапуск будет сброшен",
                 font=(FONT_FAMILY, 13), text_color=TEXT_SECONDARY,
                 anchor="w", justify="left").pack(anchor="w", pady=(0, 8))

    def on_save():
        import socket as _sock
        host_val = host_var.get().strip()
        try:
            _sock.inet_aton(host_val)
        except OSError:
            _show_error("Некорректный IP-адрес.")
            return

        try:
            port_val = int(port_var.get().strip())
            if not (1 <= port_val <= 65535):
                raise ValueError
        except ValueError:
            _show_error("Порт должен быть числом 1-65535")
            return

        lines = [l.strip() for l in dc_textbox.get("1.0", "end").strip().splitlines()
                 if l.strip()]
        try:
            tg_ws_proxy.parse_dc_ip_list(lines)
        except ValueError as e:
            _show_error(str(e))
            return

        upstream_mode_val = upstream_options.get(
            upstream_var.get(), UPSTREAM_MODE_DIRECT)
        relay_url_val = relay_url_var.get().strip()
        relay_token_val = relay_token_var.get().strip()
        try:
            direct_ws_timeout_val = float(
                direct_ws_timeout_var.get().strip())
            if direct_ws_timeout_val <= 0:
                raise ValueError
        except ValueError:
            _show_error("Таймаут direct WS должен быть положительным числом.")
            return
        if (upstream_mode_val == UPSTREAM_MODE_RELAY and
                not relay_url_val):
            _show_error("Укажите relay URL для режима Relay only.")
            return
        if relay_url_val and not _validate_relay_url(relay_url_val):
            _show_error(
                "Relay URL должен быть в формате ws://host/path "
                "или wss://host/path.")
            return

        new_cfg = {
            "host": host_val,
            "port": port_val,
            "dc_ip": lines,
            "upstream_mode": upstream_mode_val,
            "relay_url": relay_url_val,
            "relay_token": relay_token_val,
            "direct_ws_timeout_seconds": direct_ws_timeout_val,
            "verbose": verbose_var.get(),
            "autostart": (autostart_var.get() if autostart_var is not None else False),
        }
        save_config(new_cfg)
        _config.update(new_cfg)
        log.info("Config saved: %s", new_cfg)

        if _supports_autostart():
            set_autostart_enabled(bool(new_cfg.get("autostart", False)))

        _tray_icon.menu = _build_menu()

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

    btn_frame = ctk.CTkFrame(frame, fg_color="transparent")
    btn_frame.pack(fill="x", pady=(20, 0))
    ctk.CTkButton(btn_frame, text="Сохранить", height=38,
                  font=(FONT_FAMILY, 14, "bold"), corner_radius=10,
                  fg_color=TG_BLUE, hover_color=TG_BLUE_HOVER,
                  text_color="#ffffff",
                  command=on_save).pack(side="left", fill="x", expand=True, padx=(0, 8))
    ctk.CTkButton(btn_frame, text="Отмена", height=38,
                  font=(FONT_FAMILY, 14), corner_radius=10,
                  fg_color=FIELD_BG, hover_color=FIELD_BORDER,
                  text_color=TEXT_PRIMARY, border_width=1,
                  border_color=FIELD_BORDER,
                  command=on_cancel).pack(side="right", fill="x", expand=True)

    root.mainloop()


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
    tg_url = f"tg://socks?server={host}&port={port}"

    if ctk is None:
        FIRST_RUN_MARKER.touch()
        return

    ctk.set_appearance_mode("light")
    ctk.set_default_color_theme("blue")

    TG_BLUE = "#3390ec"
    TG_BLUE_HOVER = "#2b7cd4"
    BG = "#ffffff"
    FIELD_BG = "#f0f2f5"
    FIELD_BORDER = "#d6d9dc"
    TEXT_PRIMARY = "#000000"
    TEXT_SECONDARY = "#707579"
    FONT_FAMILY = "Segoe UI"

    root = ctk.CTk()
    root.title("TG WS Proxy")
    root.resizable(False, False)
    root.attributes("-topmost", True)
    icon_path = str(Path(__file__).parent / "icon.ico")
    root.iconbitmap(icon_path)

    w, h = 520, 440
    sw = root.winfo_screenwidth()
    sh = root.winfo_screenheight()
    root.geometry(f"{w}x{h}+{(sw-w)//2}+{(sh-h)//2}")
    root.configure(fg_color=BG)

    frame = ctk.CTkFrame(root, fg_color=BG, corner_radius=0)
    frame.pack(fill="both", expand=True, padx=28, pady=24)

    title_frame = ctk.CTkFrame(frame, fg_color="transparent")
    title_frame.pack(anchor="w", pady=(0, 16), fill="x")

    # Blue accent bar
    accent_bar = ctk.CTkFrame(title_frame, fg_color=TG_BLUE,
                              width=4, height=32, corner_radius=2)
    accent_bar.pack(side="left", padx=(0, 12))

    ctk.CTkLabel(title_frame, text="Прокси запущен и работает в системном трее",
                 font=(FONT_FAMILY, 17, "bold"),
                 text_color=TEXT_PRIMARY).pack(side="left")

    # Info sections
    sections = [
        ("Как подключить Telegram Desktop:", True),
        ("  Автоматически:", True),
        (f"  ПКМ по иконке в трее → «Открыть в Telegram»", False),
        (f"  Или ссылка: {tg_url}", False),
        ("\n  Вручную:", True),
        ("  Настройки → Продвинутые → Тип подключения → Прокси", False),
        (f"  SOCKS5 → {host} : {port} (без логина/пароля)", False),
    ]

    for text, bold in sections:
        weight = "bold" if bold else "normal"
        ctk.CTkLabel(frame, text=text,
                     font=(FONT_FAMILY, 13, weight),
                     text_color=TEXT_PRIMARY,
                     anchor="w", justify="left").pack(anchor="w", pady=1)

    # Spacer
    ctk.CTkFrame(frame, fg_color="transparent", height=16).pack()

    # Separator
    ctk.CTkFrame(frame, fg_color=FIELD_BORDER, height=1,
                 corner_radius=0).pack(fill="x", pady=(0, 12))

    # Checkbox
    auto_var = ctk.BooleanVar(value=True)
    ctk.CTkCheckBox(frame, text="Открыть прокси в Telegram сейчас",
                    variable=auto_var, font=(FONT_FAMILY, 13),
                    text_color=TEXT_PRIMARY,
                    fg_color=TG_BLUE, hover_color=TG_BLUE_HOVER,
                    corner_radius=6, border_width=2,
                    border_color=FIELD_BORDER).pack(anchor="w", pady=(0, 16))

    def on_ok():
        FIRST_RUN_MARKER.touch()
        open_tg = auto_var.get()
        root.destroy()
        if open_tg:
            _on_open_in_telegram()

    ctk.CTkButton(frame, text="Начать", width=180, height=42,
                  font=(FONT_FAMILY, 15, "bold"), corner_radius=10,
                  fg_color=TG_BLUE, hover_color=TG_BLUE_HOVER,
                  text_color="#ffffff",
                  command=on_ok).pack(pady=(0, 0))

    root.protocol("WM_DELETE_WINDOW", on_ok)
    root.mainloop()


def _has_ipv6_enabled() -> bool:
    import socket as _sock
    try:
        addrs = _sock.getaddrinfo(_sock.gethostname(), None, _sock.AF_INET6)
        for addr in addrs:
            ip = addr[4][0]
            if ip and not ip.startswith('::1') and not ip.startswith('fe80::1'):
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

    setup_logging(_config.get("verbose", False))
    log.info("TG WS Proxy tray app starting")
    log.info("Config: %s", _config)
    log.info("Log file: %s", LOG_FILE)

    if pystray is None or Image is None:
        log.error("pystray or Pillow not installed; "
                  "running in console mode")
        start_proxy()
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            stop_proxy()
        return

    start_proxy()

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
