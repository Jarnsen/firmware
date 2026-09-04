"""USB-first live display bridge for Framework7.

The firmware exposes the same Jarnsen framebuffer used by BLE through a private
USB CDC command stream.  Framework7 therefore prefers an exact serial mapping and
falls back to the mature BLE live worker only when USB is not available.
"""
from __future__ import annotations

import contextlib
import queue
import threading
import time
from typing import Any


_ALLOWED_CONTROLS = {"WAKE", "NEXT", "PREV", "UP", "DOWN", "SELECT", "BACK"}


def _write_line(port: Any, text: str) -> None:
    port.write((text.rstrip("\r\n") + "\r\n").encode("ascii"))
    port.flush()


def _read_exact(port: Any, count: int, timeout: float) -> bytes:
    deadline = time.monotonic() + timeout
    data = bytearray()
    while len(data) < count and time.monotonic() < deadline:
        chunk = port.read(count - len(data))
        if chunk:
            data.extend(chunk)
            continue
        time.sleep(0.002)
    if len(data) != count:
        raise TimeoutError(f"USB-Liveframe unvollständig: {len(data)}/{count} Bytes")
    return bytes(data)


def _read_frame(port: Any, timeout: float = 2.0) -> dict[str, Any]:
    # START/control acknowledgements and any final console tail may precede the
    # binary frame. Scan for the same JF/v1 marker used by the BLE characteristic.
    deadline = time.monotonic() + timeout
    marker = bytearray()
    while time.monotonic() < deadline:
        value = port.read(1)
        if not value:
            time.sleep(0.002)
            continue
        marker.extend(value)
        if len(marker) > 3:
            del marker[:-3]
        if bytes(marker) == b"JF\x01":
            rest = _read_exact(port, 9, max(0.1, deadline - time.monotonic()))
            header = b"JF\x01" + rest
            screen_on = bool(header[3] & 1)
            width = int(header[4])
            height = int(header[5])
            sequence = int.from_bytes(header[6:8], "little")
            offset = int.from_bytes(header[8:10], "little")
            total = int.from_bytes(header[10:12], "little")
            if offset != 0 or total <= 0 or total > 2048:
                raise RuntimeError("USB-Liveframe-Header ist ungültig")
            frame = _read_exact(port, total, max(0.2, deadline - time.monotonic()))
            return {
                "frame": frame,
                "width": width,
                "height": height,
                "sequence": sequence,
                "screen_on": screen_on,
            }
    raise TimeoutError("Kein USB-Liveframe empfangen")


def install_serial_live(LegacyBridge: type) -> None:
    if getattr(LegacyBridge, "_jarnsen_serial_live", False):
        return
    LegacyBridge._jarnsen_serial_live = True

    original_live_action = LegacyBridge.live_action
    original_state = LegacyBridge.state

    def _serial_live_stop(self: Any) -> None:
        stop = self.__dict__.get("_framework7_serial_live_stop")
        if isinstance(stop, threading.Event):
            stop.set()

    def _serial_live_worker(self: Any, node_id: str, port_name: str, stop: threading.Event, commands: queue.Queue[str]) -> None:
        serial_port = None
        try:
            import serial

            serial_port = serial.Serial(
                port=port_name,
                baudrate=115200,
                timeout=0.08,
                write_timeout=0.5,
                rtscts=False,
                dsrdtr=False,
            )
            with contextlib.suppress(Exception):
                serial_port.dtr = False
                serial_port.rts = False
            with contextlib.suppress(Exception):
                serial_port.reset_input_buffer()

            _write_line(serial_port, "JARNSEN_TOOL_LIVE START")
            self.tool.live_connected = True
            self.tool._framework7_live_node = node_id
            self.tool.selected_node_id = node_id

            failures = 0
            while not stop.is_set():
                while True:
                    try:
                        control = commands.get_nowait()
                    except queue.Empty:
                        break
                    _write_line(serial_port, f"JARNSEN_TOOL_LIVE CMD {control}")

                _write_line(serial_port, "JARNSEN_TOOL_LIVE FRAME")
                try:
                    snapshot = _read_frame(serial_port, 2.0)
                    failures = 0
                    snapshot["node_id"] = node_id
                    snapshot["transport"] = "USB"
                    snapshot["port"] = port_name
                    snapshot["connected"] = True
                    self.tool.live_snapshot = snapshot
                except TimeoutError:
                    failures += 1
                    if failures >= 3:
                        raise
                stop.wait(0.12)
        except Exception as exc:  # noqa: BLE001
            self.tool.live_connected = False
            self.tool.live_snapshot = {
                "node_id": node_id,
                "transport": "USB",
                "port": port_name,
                "connected": False,
                "error": f"{type(exc).__name__}: {exc}",
            }
            events = getattr(self.tool, "mac_activity_events_v220", None)
            if isinstance(events, list):
                events.append(f"USB-Live {port_name}: {type(exc).__name__}: {exc}")
                del events[:-200]
        finally:
            if serial_port is not None:
                with contextlib.suppress(Exception):
                    _write_line(serial_port, "JARNSEN_TOOL_LIVE STOP")
                with contextlib.suppress(Exception):
                    serial_port.close()
            self.tool.live_connected = False
            if self.__dict__.get("_framework7_serial_live_node") == node_id:
                self.__dict__["_framework7_serial_live_node"] = ""
                self.__dict__["_framework7_serial_live_port"] = ""

    def live_action(self: Any, payload: dict[str, Any]) -> dict[str, Any]:
        command = str(payload.get("command") or "").strip().lower()
        node_id = str(payload.get("node_id") or "").strip()
        active_node = str(self.__dict__.get("_framework7_serial_live_node") or "").strip()
        active_thread = self.__dict__.get("_framework7_serial_live_thread")
        serial_active = isinstance(active_thread, threading.Thread) and active_thread.is_alive()

        if command == "stop" and serial_active:
            _serial_live_stop(self)
            return {"ok": True, "message": "USB-Live-Verbindung wird beendet", "transport": "USB"}

        if command == "command" and serial_active:
            if node_id and active_node and node_id.lower() != active_node.lower():
                raise RuntimeError("Der Live-Befehl gehört nicht zur aktuell über USB verbundenen Node")
            control = str(payload.get("control") or "").upper().strip()
            if control not in _ALLOWED_CONTROLS:
                raise RuntimeError("Ungültiger Live-Befehl")
            commands = self.__dict__.get("_framework7_serial_live_commands")
            if not isinstance(commands, queue.Queue):
                raise RuntimeError("USB-Live-Befehlskanal ist nicht verfügbar")
            commands.put(control)
            return {"ok": True, "message": f"{control} über USB gesendet", "transport": "USB"}

        if command != "start":
            return original_live_action(self, payload)

        if not node_id:
            node_id = str(getattr(self.tool, "selected_node_id", "") or "").strip()
        if not node_id:
            raise RuntimeError("Bitte zuerst eine Node auswählen")

        usb_port = ""
        current_usb = getattr(self, "_current_usb_port", None)
        if callable(current_usb):
            with contextlib.suppress(Exception):
                usb_port = str(current_usb(node_id) or "").strip()

        if not usb_port:
            return original_live_action(self, {**payload, "node_id": node_id})

        worker = getattr(self.tool, "worker", None)
        if worker is not None:
            with contextlib.suppress(Exception):
                if worker.is_alive():
                    raise RuntimeError("USB ist noch durch einen Log-/Servicevorgang belegt")

        if serial_active:
            if active_node.lower() == node_id.lower():
                return {
                    "ok": True,
                    "message": f"USB-Live zu {node_id} läuft bereits",
                    "transport": "USB",
                    "target": usb_port,
                }
            _serial_live_stop(self)
            raise RuntimeError("Eine andere USB-Live-Sitzung wird gerade beendet. Bitte erneut starten.")

        stop = threading.Event()
        commands: queue.Queue[str] = queue.Queue()
        thread = threading.Thread(
            target=_serial_live_worker,
            args=(self, node_id, usb_port, stop, commands),
            name=f"framework7-usb-live-{usb_port}",
            daemon=True,
        )
        self.__dict__["_framework7_serial_live_stop"] = stop
        self.__dict__["_framework7_serial_live_commands"] = commands
        self.__dict__["_framework7_serial_live_thread"] = thread
        self.__dict__["_framework7_serial_live_node"] = node_id
        self.__dict__["_framework7_serial_live_port"] = usb_port
        self.tool._framework7_live_node = node_id
        self.tool.selected_node_id = node_id
        self.tool.live_snapshot = {
            "node_id": node_id,
            "transport": "USB",
            "port": usb_port,
            "connected": False,
        }
        thread.start()
        return {
            "ok": True,
            "message": f"Live-Verbindung zu {node_id} wird über {usb_port} aufgebaut",
            "transport": "USB",
            "target": usb_port,
        }

    def state(self: Any) -> dict[str, Any]:
        data = original_state(self)
        thread = self.__dict__.get("_framework7_serial_live_thread")
        if isinstance(thread, threading.Thread) and thread.is_alive():
            data["live_transport"] = "USB"
            data["live_node_id"] = str(self.__dict__.get("_framework7_serial_live_node") or "")
            data["live_port"] = str(self.__dict__.get("_framework7_serial_live_port") or "")
        return data

    LegacyBridge.live_action = live_action
    LegacyBridge.state = state
