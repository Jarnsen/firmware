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

    base_sha256 = services._sha256
    def verbose_sha256(path):
        try:
            size = path.stat().st_size
        except Exception:
            size = 0
        _ui(services, f"SHA256 START · {path.name} · {size} Bytes")
        started = time.monotonic()
        digest = base_sha256(path)
        _ui(services, f"SHA256 OK · {path.name} · {digest} · {time.monotonic()-started:.2f}s")
        return digest
    services._sha256 = verbose_sha256

    base_resolve = services.GitHubFirmwareClient.resolve_latest
    def verbose_resolve(self, board_key: str):
        local = getattr(services, "_jarnsen_local_firmware_bundle", None)
        source = "PC-Datei" if local is not None and getattr(local, "board_key", None) == board_key else "GitHub"
        _ui(services, f"FIRMWARE SUCHE START · Quelle={source} · Board={services.BOARD_PROFILES[board_key]['label']}")
        started = time.monotonic()
        bundle = base_resolve(self, board_key)
        _ui(
            services,
            f"FIRMWARE SUCHE ENDE · {bundle.display_name} · Artifact={bundle.artifact_name} · "
            f"Dauer={time.monotonic()-started:.2f}s",
        )
        for label, path in (
            ("Factory", getattr(bundle, "factory", None)),
            ("Update", getattr(bundle, "update", None)),
            ("Web/UF2", getattr(bundle, "webflasher", None)),
            ("SHA256", getattr(bundle, "checksums", None)),
        ):
            if path is None:
                continue
            try:
                _ui(services, f"FIRMWARE DATEI · {label} · {path.name} · {path.stat().st_size} Bytes · {path}")
            except Exception:
                _ui(services, f"FIRMWARE DATEI · {label} · {path}")
        return bundle
    services.GitHubFirmwareClient.resolve_latest = verbose_resolve

    def verbose_wait_for_serial(port: str, timeout: int = 90) -> None:
        _ui(services, f"RECONNECT START · Port={port} · Timeout={timeout}s")
        deadline = time.monotonic() + timeout
        started = time.monotonic()
        last_second = -1
        while time.monotonic() < deadline:
            elapsed = time.monotonic() - started
            second = int(elapsed)
            if second != last_second and (second < 5 or second % 2 == 0):
                last_second = second
                visible = []
                try:
                    visible = [p.device for p in services.list_ports.comports()]
                except Exception:
                    pass
                _ui(services, f"RECONNECT · {elapsed:.1f}s · gesucht={port} · sichtbar={visible}")
            try:
                present = any(p.device.upper() == port.upper() for p in services.list_ports.comports())
            except Exception:
                present = False
            if present:
                _ui(services, f"RECONNECT PORT GEFUNDEN · {port} · nach {elapsed:.1f}s · Stabilisierung 3s")
                time.sleep(3)
                _ui(services, f"RECONNECT OK · {port} · Gesamtdauer={time.monotonic()-started:.1f}s")
                return
            time.sleep(0.5)
        _ui(services, f"RECONNECT FEHLER · {port} · nach {timeout}s nicht wieder erschienen")
        raise services.FlasherError(f"{port} ist nach dem Flash nicht wieder erschienen.")
    services.wait_for_serial = verbose_wait_for_serial

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
                self._append_log("PROTOKOLL · Tool-Ausgaben, SHA256, Firmwaredateien, Reconnect und Flashfortschritt werden mitgeschrieben")
                _emit("VERBOSE UI installed baud-selector=1 progress-percent=1")

            try: self.after(260, patch_app)
            except Exception: pass

        ctk.CTk.__init__ = root_init
    except Exception as exc:
        _emit(f"VERBOSE UI failed type={type(exc).__name__} message={exc}")

    _emit("VERBOSE RUNTIME installed ui-protocol=1 helper-detail=1 baud-selector=1 sha256=1 reconnect=1")
