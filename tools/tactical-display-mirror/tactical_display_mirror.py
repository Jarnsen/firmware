#!/usr/bin/env python3
"""Live RGB/monochrome viewer and keyboard remote for Jarnsen USB display-mirror frames."""

from __future__ import annotations

import argparse
import queue
import threading
import time
import tkinter as tk
from dataclasses import dataclass
from typing import Optional

try:
    import serial
    from serial.tools import list_ports
except ImportError as exc:  # pragma: no cover - user-facing startup error
    raise SystemExit(
        "PySerial fehlt. Installieren mit: py -m pip install --user pyserial"
    ) from exc

MONO_FRAME_PREFIX = b"@TMF "
COLOR_FRAME_PREFIX = b"@TMF2 "
EXPECTED_WIDTH = 160
EXPECTED_HEIGHT = 80
KEY_COMMANDS = {
    "Left": "LEFT",
    "Right": "RIGHT",
    "Up": "UP",
    "Down": "DOWN",
    "space": "SPACE",
}


@dataclass(frozen=True)
class Frame:
    width: int
    height: int
    data: bytes
    received_at: float
    rgb565: bool = False
    sequence: int = 0


def _decode_rgb565_rle(payload: bytes, pixel_count: int) -> Optional[bytes]:
    if len(payload) % 3:
        return None

    output = bytearray(pixel_count * 2)
    pixel_offset = 0
    for offset in range(0, len(payload), 3):
        count = payload[offset]
        if count == 0 or pixel_offset + count > pixel_count:
            return None
        high = payload[offset + 1]
        low = payload[offset + 2]
        byte_offset = pixel_offset * 2
        for _ in range(count):
            output[byte_offset] = high
            output[byte_offset + 1] = low
            byte_offset += 2
        pixel_offset += count

    if pixel_offset != pixel_count:
        return None
    return bytes(output)


def parse_frame(raw: bytes) -> Optional[Frame]:
    """Extract one @TMF monochrome or @TMF2 RGB565 frame from a serial line."""
    color_marker = raw.find(COLOR_FRAME_PREFIX)
    mono_marker = raw.find(MONO_FRAME_PREFIX)

    if color_marker >= 0 and (mono_marker < 0 or color_marker <= mono_marker):
        try:
            text = raw[color_marker:].decode("ascii", errors="strict").strip()
            prefix, width_text, height_text, sequence_text, payload_text = text.split(maxsplit=4)
            if prefix != "@TMF2":
                return None
            width = int(width_text)
            height = int(height_text)
            sequence = int(sequence_text)
            packed = bytes.fromhex(payload_text)
        except (UnicodeDecodeError, ValueError):
            return None

        if width <= 0 or height <= 0:
            return None
        pixels = _decode_rgb565_rle(packed, width * height)
        if pixels is None:
            return None
        return Frame(
            width=width,
            height=height,
            data=pixels,
            received_at=time.monotonic(),
            rgb565=True,
            sequence=sequence,
        )

    if mono_marker < 0:
        return None

    try:
        text = raw[mono_marker:].decode("ascii", errors="strict").strip()
        prefix, width_text, height_text, payload = text.split(maxsplit=3)
        if prefix != "@TMF":
            return None
        width = int(width_text)
        height = int(height_text)
        data = bytes.fromhex(payload)
    except (UnicodeDecodeError, ValueError):
        return None

    expected = width * height // 8
    if width <= 0 or height <= 0 or height % 8 or len(data) != expected:
        return None
    return Frame(width=width, height=height, data=data, received_at=time.monotonic())


def rgb565_to_hex(high: int, low: int) -> str:
    value = (high << 8) | low
    red5 = (value >> 11) & 0x1F
    green6 = (value >> 5) & 0x3F
    blue5 = value & 0x1F
    red = (red5 << 3) | (red5 >> 2)
    green = (green6 << 2) | (green6 >> 4)
    blue = (blue5 << 3) | (blue5 >> 2)
    return f"#{red:02x}{green:02x}{blue:02x}"


def find_port(requested: Optional[str]) -> str:
    if requested:
        return requested

    ports = list(list_ports.comports())
    if len(ports) == 1:
        return ports[0].device
    if ports:
        choices = "\n".join(f"  {port.device}: {port.description}" for port in ports)
        raise SystemExit(
            "Mehrere COM-Ports gefunden. Bitte einen angeben, zum Beispiel:\n"
            "  py tactical_display_mirror.py COM5\n\nGefunden:\n" + choices
        )
    raise SystemExit("Kein serieller Anschluss gefunden. Tracker per USB verbinden.")


class MirrorWindow:
    def __init__(self, root: tk.Tk, port: str, baudrate: int, scale: int) -> None:
        self.root = root
        self.port = port
        self.baudrate = baudrate
        self.scale = scale
        self.frames: queue.Queue[Frame] = queue.Queue(maxsize=2)
        self.messages: queue.Queue[str] = queue.Queue(maxsize=8)
        self.stop_event = threading.Event()
        self.serial_port: Optional[serial.Serial] = None
        self.serial_lock = threading.Lock()
        self.last_frame_time = 0.0

        root.title(f"Jarnsen Tactical Display Mirror – {port}")
        root.resizable(False, False)
        root.protocol("WM_DELETE_WINDOW", self.close)
        root.bind_all("<KeyPress>", self._on_key_press)
        root.focus_force()

        self.image_label = tk.Label(root, bg="black", bd=0, takefocus=True)
        self.image_label.pack(padx=12, pady=(12, 6))
        self.image_label.focus_set()

        self.controls = tk.StringVar(
            value="Steuerung: Pfeiltasten = Navigation  |  Leertaste = Auswählen/Drücken"
        )
        tk.Label(root, textvariable=self.controls, anchor="center").pack(fill="x", padx=12)

        self.status = tk.StringVar(value=f"Verbinde mit {port} …")
        tk.Label(root, textvariable=self.status, anchor="w").pack(fill="x", padx=12, pady=(4, 10))

        self._render_blank()
        self.reader = threading.Thread(target=self._reader_loop, daemon=True)
        self.reader.start()
        root.after(40, self._poll)

    def _render_blank(self) -> None:
        base = tk.PhotoImage(width=EXPECTED_WIDTH, height=EXPECTED_HEIGHT)
        base.put("black", to=(0, 0, EXPECTED_WIDTH, EXPECTED_HEIGHT))
        scaled = base.zoom(self.scale, self.scale)
        self.image_label.configure(image=scaled)
        self.image_label.image = scaled
        self._base_image = base

    def _reader_loop(self) -> None:
        try:
            self.serial_port = serial.Serial(self.port, self.baudrate, timeout=1.0)
            self._put_message(
                f"Verbunden: {self.port} @ {self.baudrate} Baud – RGB565, Pfeiltasten und Leertaste aktiv"
            )
            while not self.stop_event.is_set():
                raw = self.serial_port.readline()
                if not raw:
                    continue
                frame = parse_frame(raw)
                if frame is None:
                    continue
                while self.frames.full():
                    try:
                        self.frames.get_nowait()
                    except queue.Empty:
                        break
                self.frames.put_nowait(frame)
        except serial.SerialException as exc:
            self._put_message(f"Serieller Fehler: {exc}")
        finally:
            if self.serial_port and self.serial_port.is_open:
                self.serial_port.close()

    def _on_key_press(self, event: tk.Event) -> str | None:
        command = KEY_COMMANDS.get(event.keysym)
        if command is None:
            return None
        self._send_command(command)
        return "break"

    def _send_command(self, command: str) -> None:
        port = self.serial_port
        if port is None or not port.is_open:
            self._put_message("Noch nicht verbunden – Eingabe wurde nicht gesendet")
            return

        payload = f"@TMC {command}\n".encode("ascii")
        try:
            with self.serial_lock:
                port.write(payload)
                port.flush()
            self._put_message(f"Taste gesendet: {command}")
        except serial.SerialException as exc:
            self._put_message(f"Senden fehlgeschlagen: {exc}")

    def _put_message(self, message: str) -> None:
        while self.messages.full():
            try:
                self.messages.get_nowait()
            except queue.Empty:
                break
        self.messages.put_nowait(message)

    def _poll(self) -> None:
        try:
            while True:
                self.status.set(self.messages.get_nowait())
        except queue.Empty:
            pass

        newest: Optional[Frame] = None
        try:
            while True:
                newest = self.frames.get_nowait()
        except queue.Empty:
            pass

        if newest is not None:
            self._render(newest)
            age_ms = (time.monotonic() - newest.received_at) * 1000.0
            mode = "RGB565" if newest.rgb565 else "Mono"
            sequence = f" | Frame {newest.sequence}" if newest.rgb565 else ""
            self.status.set(
                f"Live: {newest.width}×{newest.height} | {mode}{sequence} | vor {age_ms:.0f} ms"
            )

        if not self.stop_event.is_set():
            self.root.after(40, self._poll)

    def _render(self, frame: Frame) -> None:
        base = tk.PhotoImage(width=frame.width, height=frame.height)
        if frame.rgb565:
            for y in range(frame.height):
                row = []
                row_offset = y * frame.width * 2
                for x in range(frame.width):
                    offset = row_offset + x * 2
                    row.append(rgb565_to_hex(frame.data[offset], frame.data[offset + 1]))
                base.put("{" + " ".join(row) + "}", to=(0, y))
        else:
            for y in range(frame.height):
                page = y // 8
                bit = 1 << (y & 7)
                row = []
                row_offset = page * frame.width
                for x in range(frame.width):
                    row.append("#ffffff" if frame.data[row_offset + x] & bit else "#000000")
                base.put("{" + " ".join(row) + "}", to=(0, y))

        scaled = base.zoom(self.scale, self.scale)
        self.image_label.configure(image=scaled)
        self.image_label.image = scaled
        self._base_image = base
        self.last_frame_time = frame.received_at

    def close(self) -> None:
        self.stop_event.set()
        if self.serial_port and self.serial_port.is_open:
            self.serial_port.close()
        self.root.destroy()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Spiegelt und steuert die aktuell sichtbare Displayseite eines Heltec Trackers unter Windows."
    )
    parser.add_argument("port", nargs="?", help="COM-Port, zum Beispiel COM5")
    parser.add_argument("--baud", type=int, default=115200, help="Baudrate (Standard: 115200)")
    parser.add_argument("--scale", type=int, default=6, choices=range(2, 11), metavar="2..10")
    args = parser.parse_args()

    port = find_port(args.port)
    root = tk.Tk()
    MirrorWindow(root, port=port, baudrate=args.baud, scale=args.scale)
    root.mainloop()


if __name__ == "__main__":
    main()
