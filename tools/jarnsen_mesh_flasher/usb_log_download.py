from __future__ import annotations

import re
import threading
import time
from datetime import datetime
from pathlib import Path
from tkinter import messagebox
from typing import Any

import serial


COMMAND = b"JARNSEN_TOOL_FULL\n"
BEGIN = b"===JARNSEN_DIAG_LOG_BEGIN==="
END = b"===JARNSEN_DIAG_LOG_END==="


def _emit(message: str) -> None:
    try:
        import diagnostics
        diagnostics._emit(message)
    except Exception:
        pass


def _walk(widget: Any):
    yield widget
    try:
        children = widget.winfo_children()
    except Exception:
        children = []
    for child in children:
        yield from _walk(child)


def _button_text(widget: Any) -> str:
    try:
        return str(widget.cget("text") or "")
    except Exception:
        return ""


def _safe_filename(value: str) -> str:
    value = re.sub(r"[^A-Za-z0-9._-]+", "_", str(value or "").strip()).strip("._-")
    return value[:64] or "Node"


def _header_value(payload: bytes, name: bytes) -> str:
    match = re.search(rb"(?m)^# " + re.escape(name) + rb"=([^\r\n]+)", payload)
    return match.group(1).decode("utf-8", "replace").strip() if match else ""


def _expected_bytes(payload: bytes) -> int | None:
    match = re.search(rb"(?m)^# bytes=(\d+)\r?$", payload)
    if not match:
        return None
    try:
        return int(match.group(1))
    except Exception:
        return None


def _payload_offset(payload: bytes) -> int | None:
    match = re.search(rb"(?m)^# bytes=\d+\r?\n", payload)
    return match.end() if match else None


def download_tracker_usb_log(
    port: str,
    destination: Path,
    *,
    progress=None,
    log=None,
    timeout: float = 150.0,
) -> Path:
    """Request and receive the Tracker diagnostic log over raw USB CDC."""
    destination.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    last_data = started
    buffer = bytearray()
    capture = bytearray()
    found_begin = False
    expected: int | None = None
    payload_start: int | None = None
    last_report = 0.0

    def report(fraction: float, text: str) -> None:
        if progress is not None:
            try:
                progress(max(0.0, min(1.0, float(fraction))), text)
            except Exception:
                pass
        if log is not None:
            try:
                log(text)
            except Exception:
                pass

    report(0.02, f"USB-Log · COM-Port öffnen · {port}")
    _emit(f"USB LOG SERIAL OPEN port={port} baud=115200 command=JARNSEN_TOOL_FULL")

    with serial.Serial(port=port, baudrate=115200, timeout=0.12, write_timeout=2.0) as ser:
        # Clear boot/debug residue before the request. The firmware deliberately
        # waits for USB settle after accepting the command, so the begin marker
        # cannot be cleared by this pre-request reset.
        try:
            ser.reset_input_buffer()
        except Exception:
            pass
        time.sleep(0.25)
        report(0.06, "USB-Log · Export ohne Gerätebestätigung anfordern")
        ser.write(COMMAND)
        ser.flush()
        _emit(f"USB LOG COMMAND SENT port={port} bytes={len(COMMAND)}")

        while True:
            now = time.monotonic()
            elapsed = now - started
            if elapsed >= timeout:
                raise TimeoutError(f"USB-Logdownload auf {port} hat nach {int(timeout)} Sekunden das Zeitlimit erreicht.")

            chunk = ser.read(4096)
            if chunk:
                last_data = now
                if not found_begin:
                    buffer.extend(chunk)
                    idx = buffer.find(BEGIN)
                    if idx >= 0:
                        found_begin = True
                        capture.extend(buffer[idx:])
                        buffer.clear()
                        report(0.10, "USB-Log · Startmarker empfangen")
                        _emit(f"USB LOG BEGIN port={port} elapsed={elapsed:.2f}s")
                    elif len(buffer) > 65536:
                        del buffer[:-8192]
                else:
                    capture.extend(chunk)

                if found_begin:
                    if expected is None:
                        expected = _expected_bytes(bytes(capture))
                        payload_start = _payload_offset(bytes(capture))
                        if expected is not None:
                            report(0.12, f"USB-Log · {expected / 1024.0:.1f} KiB Nutzdaten angekündigt")
                            _emit(f"USB LOG SIZE port={port} payload_bytes={expected}")

                    end_idx = capture.find(END)
                    if end_idx >= 0:
                        end_pos = end_idx + len(END)
                        while end_pos < len(capture) and capture[end_pos] in (10, 13):
                            end_pos += 1
                        completed = bytes(capture[:end_pos])
                        node_id = _header_value(completed, b"node_id")
                        long_name = _header_value(completed, b"long_name")
                        device = _header_value(completed, b"device") or "HELTEC_TRACKER_V1.1"
                        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
                        stem = _safe_filename(long_name or node_id or port)
                        target = destination / f"{stem}-{_safe_filename(port)}-{stamp}.log"
                        target.write_bytes(completed)
                        payload_sent = 0
                        if payload_start is not None:
                            payload_sent = max(0, end_idx - payload_start)
                        report(1.0, f"USB-Log · Fertig · {target.name}")
                        _emit(
                            f"USB LOG COMPLETE port={port} device={device!r} node={node_id!r} "
                            f"payload_expected={expected!r} payload_observed={payload_sent} "
                            f"file_bytes={len(completed)} path={str(target)!r} duration={elapsed:.2f}s"
                        )
                        return target

                    if expected and payload_start is not None:
                        payload_received = max(0, len(capture) - payload_start)
                        fraction = min(0.97, 0.12 + 0.83 * min(1.0, payload_received / max(1, expected)))
                        if now - last_report >= 0.35:
                            pct = min(100.0, payload_received * 100.0 / max(1, expected))
                            report(
                                fraction,
                                f"USB-Log · {pct:.1f}% · {payload_received / 1024.0:.1f}/{expected / 1024.0:.1f} KiB",
                            )
                            last_report = now
            else:
                idle = now - last_data
                if not found_begin and idle >= 15.0:
                    raise TimeoutError(
                        "Der Node hat keinen JARNSEN-Diagnose-Startmarker gesendet. "
                        "Die installierte Firmware unterstützt den direkten USB-Service möglicherweise noch nicht."
                    )
                if found_begin and idle >= 20.0:
                    raise TimeoutError(
                        f"USB-Logübertragung auf {port} ist seit {idle:.0f} Sekunden ohne Daten."
                    )
                if now - last_report >= 2.0:
                    if found_begin:
                        report(0.12, f"USB-Log · Warte auf weitere Daten · {elapsed:.0f}s")
                    else:
                        report(0.08, f"USB-Log · Warte auf Startmarker · {elapsed:.0f}s")
                    last_report = now


def install(services: Any) -> None:
    """Add a one-click raw USB diagnostic-log button to the Flasher."""
    import customtkinter as ctk

    original_root_init = ctk.CTk.__init__

    def root_init(self: Any, *args: Any, **kwargs: Any) -> None:
        original_root_init(self, *args, **kwargs)

        def patch_app() -> None:
            if getattr(self, "_jarnsen_usb_log_installed", False):
                return
            required = ("_selected_device", "_selected_board_key", "_set_busy", "_set_progress", "_append_log")
            if not all(hasattr(self, name) for name in required):
                try:
                    self.after(160, patch_app)
                except Exception:
                    pass
                return

            search_button = None
            for widget in _walk(self):
                if _button_text(widget) == "Neu suchen":
                    search_button = widget
                    break
            if search_button is None:
                try:
                    self.after(180, patch_app)
                except Exception:
                    pass
                return

            parent = getattr(search_button, "master", None)
            if parent is None:
                return
            self._jarnsen_usb_log_installed = True

            def start_usb_log() -> None:
                if getattr(self, "busy", False):
                    return
                device = self._selected_device()
                if device is None:
                    messagebox.showwarning("Kein Gerät", "Bitte zuerst ein USB-Gerät auswählen.", parent=self)
                    return
                board_key = self._selected_board_key()
                if board_key != "tracker":
                    label = services.BOARD_PROFILES.get(board_key or "", {}).get("label", "Unbekannt")
                    messagebox.showinfo(
                        "USB-Log noch nicht aktiv",
                        f"Der direkte JARNSEN USB-Logservice ist derzeit für den Tracker V1.1 aktiviert.\n\n"
                        f"Ausgewählt: {label}\n\n"
                        "V3/Wio werden erst freigeschaltet, sobald deren Firmware denselben Servicepfad bereitstellt.",
                        parent=self,
                    )
                    return

                self._set_busy(True)
                threading.Thread(
                    target=usb_log_worker,
                    args=(device.port,),
                    name="jarnsen-usb-log",
                    daemon=True,
                ).start()

            usb_button = ctk.CTkButton(
                parent,
                text="NODE-LOG USB",
                width=125,
                command=start_usb_log,
            )
            usb_button.pack(side="left", padx=(10, 0))
            self.usb_log_button = usb_button

            original_set_busy = self._set_busy

            def wrapped_set_busy(busy: bool) -> None:
                original_set_busy(busy)
                try:
                    self.after(0, usb_button.configure, {"state": "disabled" if busy else "normal"})
                except Exception:
                    pass

            self._set_busy = wrapped_set_busy

            def usb_log_worker(port: str) -> None:
                try:
                    self._append_log(
                        f"USB-LOG START · Port={port} · Protokoll=JARNSEN_TOOL_FULL · "
                        "Bestätigung am Node=nicht erforderlich"
                    )
                    self._set_progress(0.02, "USB-Log · Raw-Modus vorbereiten")

                    # Device discovery uses Meshtastic protobuf and therefore puts
                    # SerialConsole into framed mode. Reboot once, then do NOT run
                    # meshtastic again before sending the raw service command.
                    self._append_log("USB-LOG · Node neu starten, damit USB wieder im Raw-Service-Modus ist")
                    try:
                        services.reboot_node(port)
                    except Exception as exc:
                        self._append_log(f"USB-LOG · Reboot-Befehl meldet {type(exc).__name__}: {exc} · Reconnect wird trotzdem versucht")

                    self._set_progress(0.08, "USB-Log · Auf USB-Neuanmeldung warten")
                    services.wait_for_serial(port, timeout=90)
                    time.sleep(1.0)

                    output_dir = Path(services.PATHS.logs) / "NODE-LOGS"

                    def progress(value: float, detail: str) -> None:
                        overall = 0.10 + 0.88 * max(0.0, min(1.0, value))
                        self._set_progress(overall, detail)

                    target = download_tracker_usb_log(
                        port,
                        output_dir,
                        progress=progress,
                        log=self._append_log,
                    )
                    self._set_progress(1.0, f"USB-Log gespeichert · {target.name}")
                    self._append_log(f"USB-LOG ENDE · ERFOLG · {target}")
                    self.after(
                        0,
                        messagebox.showinfo,
                        "Node-Log gespeichert",
                        f"Der Diagnose-Log wurde ohne Bestätigung am Node übertragen.\n\n{target}",
                    )
                except Exception as exc:
                    self._append_log(f"USB-LOG FEHLER · {type(exc).__name__}: {exc}")
                    try:
                        self._show_error(exc)
                    except Exception:
                        self.after(0, messagebox.showerror, "USB-Logdownload fehlgeschlagen", str(exc))
                finally:
                    self._set_busy(False)

            _emit("USB LOG UI installed command=JARNSEN_TOOL_FULL raw-after-reboot=1 node-confirmation=0")

        try:
            self.after(700, patch_app)
        except Exception:
            pass

    ctk.CTk.__init__ = root_init
    _emit("USB LOG DOWNLOAD layer installed tracker=1 v3=0 wio=0")
