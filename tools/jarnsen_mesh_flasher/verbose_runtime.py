from __future__ import annotations

import subprocess
import time
import types
from typing import Any


def _emit(message: str) -> None:
    try:
        import diagnostics
        diagnostics._emit(message)
    except Exception:
        pass


def _redact(value: Any) -> str:
    text = "" if value is None else str(value)
    try:
        import diagnostics
        return diagnostics._redact(text)
    except Exception:
        lowered = text.lower()
        if any(token in lowered for token in ("psk", "privatekey", "private_key", "admin_key", "token", "password")):
            return "<redacted sensitive line>"
        return text


def _ui(services: Any, text: str) -> None:
    callback = getattr(services, "_jarnsen_ui_log_callback", None)
    if callable(callback):
        try:
            callback(_redact(text))
        except Exception:
            pass


def _log_block(services: Any, title: str, value: Any, *, max_lines: int = 600) -> None:
    text = _redact(value)
    if not text.strip():
        return
    lines = text.splitlines()
    for index, line in enumerate(lines[:max_lines], start=1):
        _ui(services, f"{title} [{index:03d}] {line}")
    if len(lines) > max_lines:
        _ui(services, f"{title} · … {len(lines) - max_lines} weitere Zeilen nur im Diagnose-Log")


def install(services: Any) -> None:
    services._jarnsen_flash_baud = str(getattr(services, "_jarnsen_flash_baud", "921600"))
    base_run_helper = services.run_helper

    def verbose_run_helper(tool: str, args: Any, *, timeout: int = 60, check: bool = True):
        argv = [str(item) for item in args]
        safe_args: list[str] = []
        hide_next = False
        for item in argv:
            if hide_next:
                safe_args.append("<redacted>")
                hide_next = False
                continue
            safe_args.append(item)
            if item.lower() in {"--psk", "--private-key", "--admin-key", "--token", "--password"}:
                hide_next = True
        _ui(services, f"TOOL START · {tool} · timeout={timeout}s · {' '.join(safe_args)}")
        started = time.monotonic()
        try:
            result = base_run_helper(tool, argv, timeout=timeout, check=check)
        except subprocess.TimeoutExpired as exc:
            elapsed = time.monotonic() - started
            _ui(services, f"TOOL TIMEOUT · {tool} · {elapsed:.1f}s/{timeout}s")
            _log_block(services, f"{tool} TIMEOUT STDOUT", getattr(exc, "stdout", ""))
            _log_block(services, f"{tool} TIMEOUT STDERR", getattr(exc, "stderr", ""))
            raise
        except Exception as exc:
            elapsed = time.monotonic() - started
            _ui(services, f"TOOL FEHLER · {tool} · nach {elapsed:.1f}s · {type(exc).__name__}: {exc}")
            raise
        elapsed = time.monotonic() - started
        _ui(services, f"TOOL ENDE · {tool} · Exit={result.returncode} · Dauer={elapsed:.2f}s")
        _log_block(services, f"{tool} STDOUT", result.stdout)
        _log_block(services, f"{tool} STDERR", result.stderr)
        return result

    services.run_helper = verbose_run_helper

    try:
        import customtkinter as ctk

        original_root_init = ctk.CTk.__init__

        def root_init(self: Any, *args: Any, **kwargs: Any) -> None:
            original_root_init(self, *args, **kwargs)

            def patch_app() -> None:
                if not hasattr(self, "_append_log") or not hasattr(self, "_set_progress"):
                    try: self.after(100, patch_app)
                    except Exception: pass
                    return
                if getattr(self, "_jarnsen_verbose_ui", False):
                    return
                self._jarnsen_verbose_ui = True
                services._jarnsen_ui_log_callback = self._append_log

                original_set_progress = self._set_progress
                def set_progress(app_self: Any, value: float, text: str) -> None:
                    value = max(0.0, min(1.0, float(value)))
                    pct = value * 100.0
                    original_set_progress(value, f"{pct:5.1f}% · {text}")
                self._set_progress = types.MethodType(set_progress, self)

                def walk(widget: Any):
                    yield widget
                    for child in widget.winfo_children():
                        yield from walk(child)

                local_button = None
                firmware_button = None
                for widget in walk(self):
                    if not isinstance(widget, ctk.CTkButton):
                        continue
                    try: label = str(widget.cget("text"))
                    except Exception: label = ""
                    if label == "Datei vom PC auswählen": local_button = widget
                    elif label == "Neueste Firmware prüfen": firmware_button = widget

                if local_button is not None:
                    row = local_button.master
                elif firmware_button is not None:
                    row = ctk.CTkFrame(firmware_button.master, fg_color="transparent")
                    row.pack(fill="x", padx=18, pady=(0, 14))
                else:
                    row = None

                if row is not None:
                    ctk.CTkLabel(row, text="Flash-Baud:").pack(side="left", padx=(18, 6))
                    baud_var = ctk.StringVar(value=services._jarnsen_flash_baud)
                    self.flash_baud_var = baud_var

                    def baud_changed(value: str) -> None:
                        services._jarnsen_flash_baud = str(value)
                        self._append_log(f"FLASH BAUD · {value} Baud ausgewählt")
                        self._set_status(f"Flash-Geschwindigkeit · {value} Baud")

                    ctk.CTkOptionMenu(
                        row,
                        variable=baud_var,
                        values=["115200", "230400", "460800", "921600"],
                        width=130,
                        command=baud_changed,
                    ).pack(side="left")

                self._append_log("PROTOKOLL · ausführlicher Modus aktiv")
                self._append_log(
                    f"FLASH · Standardgeschwindigkeit {services._jarnsen_flash_baud} Baud · "
                    "Wio/UF2 verwendet keine serielle esptool-Baudrate"
                )
                _emit("VERBOSE UI installed baud-selector=1 progress-percent=1")

            try: self.after(260, patch_app)
            except Exception: pass

        ctk.CTk.__init__ = root_init
    except Exception as exc:
        _emit(f"VERBOSE UI failed type={type(exc).__name__} message={exc}")

    _emit("VERBOSE RUNTIME installed ui-protocol=1 helper-detail=1 baud-selector=1")
