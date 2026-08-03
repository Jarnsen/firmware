#!/usr/bin/env python3
"""Resizable RGB565/mono viewer and low-latency keyboard remote for Jarnsen Tactical."""

from __future__ import annotations

import argparse
import queue
import threading
import time
import tkinter as tk
from collections import deque
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from tkinter import ttk
from typing import Deque, Dict, Optional, Tuple

try:
    import serial
    from serial.tools import list_ports
except ImportError as exc:  # pragma: no cover - user-facing startup error
    raise SystemExit(
        "PySerial fehlt. Installieren mit: py -m pip install --user pyserial"
    ) from exc

try:
    from PIL import Image, ImageTk
except ImportError as exc:  # pragma: no cover - user-facing startup error
    raise SystemExit(
        "Pillow fehlt. Installieren mit: py -m pip install --user pillow"
    ) from exc

MONO_FRAME_PREFIX = b"@TMF "
COLOR_FRAME_PREFIX = b"@TMF2 "
CHUNK_FRAME_PREFIX = b"@TMF3 "
ACK_PREFIX = b"@TMA "
EXPECTED_WIDTH = 160
EXPECTED_HEIGHT = 80
CHUNK_ASSEMBLY_TIMEOUT_SECONDS = 4.0
DEFAULT_BAUD_RATE = 460800
STATUS_REFRESH_MS = 50
RENDER_DEBOUNCE_MS = 12
KEY_REPEAT_DELAY_MS = 180
KEY_REPEAT_INTERVAL_MS = 45
MAX_NAVIGATION_IN_FLIGHT = 2

REPEATABLE_COMMANDS = frozenset({"LEFT", "RIGHT", "UP", "DOWN"})

KEY_COMMANDS = {
    "Left": "LEFT",
    "Right": "RIGHT",
    "Up": "UP",
    "Down": "DOWN",
    "a": "LEFT",
    "A": "LEFT",
    "d": "RIGHT",
    "D": "RIGHT",
    "w": "UP",
    "W": "UP",
    "s": "DOWN",
    "S": "DOWN",
    "space": "SPACE",
    "Return": "ENTER",
    "KP_Enter": "ENTER",
    "Escape": "BACK",
    "BackSpace": "BACK",
}

RESAMPLING = getattr(Image, "Resampling", Image)


def _build_rgb565_lookup() -> bytes:
    """Build one compact 65536-entry RGB888 lookup table."""
    output = bytearray(65536 * 3)
    for value in range(65536):
        red5 = (value >> 11) & 0x1F
        green6 = (value >> 5) & 0x3F
        blue5 = value & 0x1F
        offset = value * 3
        output[offset] = (red5 << 3) | (red5 >> 2)
        output[offset + 1] = (green6 << 2) | (green6 >> 4)
        output[offset + 2] = (blue5 << 3) | (blue5 >> 2)
    return bytes(output)


RGB565_TO_RGB888 = _build_rgb565_lookup()


@dataclass(frozen=True)
class Frame:
    width: int
    height: int
    rgb: bytes
    received_at: float
    source_format: str
    sequence: int = 0


@dataclass
class _ChunkAssembly:
    mode: str
    width: int
    height: int
    sequence: int
    chunk_count: int
    chunks: Dict[int, bytes]
    updated_at: float


def _rgb565_pair_to_rgb(high: int, low: int) -> bytes:
    offset = ((high << 8) | low) * 3
    return RGB565_TO_RGB888[offset : offset + 3]


def _decode_rgb565_rle(payload: bytes, pixel_count: int) -> Optional[bytes]:
    """Decode count/high/low runs directly into RGB888 without an intermediate frame."""
    if pixel_count <= 0 or len(payload) % 3:
        return None

    output = bytearray(pixel_count * 3)
    pixel_offset = 0
    for offset in range(0, len(payload), 3):
        count = payload[offset]
        if count == 0 or pixel_offset + count > pixel_count:
            return None
        rgb = _rgb565_pair_to_rgb(payload[offset + 1], payload[offset + 2])
        byte_offset = pixel_offset * 3
        output[byte_offset : byte_offset + count * 3] = rgb * count
        pixel_offset += count

    if pixel_offset != pixel_count:
        return None
    return bytes(output)


def _decode_mono(payload: bytes, width: int, height: int) -> Optional[bytes]:
    if width <= 0 or height <= 0 or height % 8:
        return None
    if len(payload) != width * height // 8:
        return None

    output = bytearray(width * height * 3)
    white = b"\xff\xff\xff"
    black = b"\x00\x00\x00"
    for y in range(height):
        source_offset = (y // 8) * width
        mask = 1 << (y & 7)
        row_offset = y * width * 3
        for x in range(width):
            destination = row_offset + x * 3
            output[destination : destination + 3] = (
                white if payload[source_offset + x] & mask else black
            )
    return bytes(output)


def parse_frame(raw: bytes) -> Optional[Frame]:
    """Extract one legacy @TMF or @TMF2 frame from a serial line."""
    color_marker = raw.find(COLOR_FRAME_PREFIX)
    mono_marker = raw.find(MONO_FRAME_PREFIX)

    if color_marker >= 0 and (mono_marker < 0 or color_marker <= mono_marker):
        try:
            text = raw[color_marker:].decode("ascii", errors="strict").strip()
            prefix, width_text, height_text, sequence_text, payload_text = text.split(
                maxsplit=4
            )
            if prefix != "@TMF2":
                return None
            width = int(width_text)
            height = int(height_text)
            sequence = int(sequence_text)
            packed = bytes.fromhex(payload_text)
        except (UnicodeDecodeError, ValueError):
            return None

        rgb = _decode_rgb565_rle(packed, width * height)
        if rgb is None:
            return None
        return Frame(
            width=width,
            height=height,
            rgb=rgb,
            received_at=time.monotonic(),
            source_format="RGB565/TMF2",
            sequence=sequence,
        )

    if mono_marker < 0:
        return None

    try:
        text = raw[mono_marker:].decode("ascii", errors="strict").strip()
        prefix, width_text, height_text, payload_text = text.split(maxsplit=3)
        if prefix != "@TMF":
            return None
        width = int(width_text)
        height = int(height_text)
        packed = bytes.fromhex(payload_text)
    except (UnicodeDecodeError, ValueError):
        return None

    rgb = _decode_mono(packed, width, height)
    if rgb is None:
        return None
    return Frame(
        width=width,
        height=height,
        rgb=rgb,
        received_at=time.monotonic(),
        source_format="Mono/TMF",
    )


def parse_ack(raw: bytes) -> Optional[Tuple[int, str, Optional[int]]]:
    marker = raw.find(ACK_PREFIX)
    if marker < 0:
        return None
    try:
        parts = raw[marker:].decode("ascii", errors="strict").strip().split()
    except UnicodeDecodeError:
        return None

    if len(parts) < 3 or parts[0] != "@TMA" or not parts[1].isdigit():
        return None
    request_id = int(parts[1])
    status = parts[2]
    firmware_millis = None
    if len(parts) >= 4:
        try:
            firmware_millis = int(parts[3])
        except ValueError:
            firmware_millis = None
    return request_id, status, firmware_millis


class FrameDecoder:
    """Reassemble short @TMF3 chunks while retaining legacy frame support."""

    def __init__(self) -> None:
        self._assemblies: Dict[Tuple[str, int], _ChunkAssembly] = {}

    def feed(self, raw: bytes) -> Optional[Frame]:
        marker = raw.find(CHUNK_FRAME_PREFIX)
        if marker < 0:
            return parse_frame(raw)

        try:
            text = raw[marker:].decode("ascii", errors="strict").strip()
            (
                prefix,
                mode,
                width_text,
                height_text,
                sequence_text,
                chunk_index_text,
                chunk_count_text,
                payload_text,
            ) = text.split(maxsplit=7)
            if prefix != "@TMF3" or mode not in {"M", "C"}:
                return None
            width = int(width_text)
            height = int(height_text)
            sequence = int(sequence_text)
            chunk_index = int(chunk_index_text)
            chunk_count = int(chunk_count_text)
            payload = bytes.fromhex(payload_text)
        except (UnicodeDecodeError, ValueError):
            return None

        if (
            width <= 0
            or height <= 0
            or chunk_count <= 0
            or chunk_count > 4096
            or chunk_index < 0
            or chunk_index >= chunk_count
            or not payload
        ):
            return None

        now = time.monotonic()
        self._discard_stale(now)
        key = (mode, sequence)
        assembly = self._assemblies.get(key)
        if assembly is None or (
            assembly.width != width
            or assembly.height != height
            or assembly.chunk_count != chunk_count
        ):
            # The newest sequence supersedes incomplete images of the same mode.
            self._assemblies = {
                old_key: old
                for old_key, old in self._assemblies.items()
                if old_key[0] != mode
            }
            assembly = _ChunkAssembly(
                mode=mode,
                width=width,
                height=height,
                sequence=sequence,
                chunk_count=chunk_count,
                chunks={},
                updated_at=now,
            )
            self._assemblies[key] = assembly

        assembly.chunks[chunk_index] = payload
        assembly.updated_at = now
        if len(assembly.chunks) != assembly.chunk_count:
            return None

        try:
            packed = b"".join(assembly.chunks[index] for index in range(chunk_count))
        except KeyError:
            return None
        del self._assemblies[key]

        if mode == "C":
            rgb = _decode_rgb565_rle(packed, width * height)
            source_format = "RGB565/TMF3"
        else:
            rgb = _decode_mono(packed, width, height)
            source_format = "Mono/TMF3"
        if rgb is None:
            return None

        return Frame(
            width=width,
            height=height,
            rgb=rgb,
            received_at=now,
            source_format=source_format,
            sequence=sequence,
        )

    def _discard_stale(self, now: float) -> None:
        self._assemblies = {
            key: assembly
            for key, assembly in self._assemblies.items()
            if now - assembly.updated_at <= CHUNK_ASSEMBLY_TIMEOUT_SECONDS
        }


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
    def __init__(self, root: tk.Tk, port: str, baudrate: int, render_mode: str) -> None:
        self.root = root
        self.port = port
        self.baudrate = baudrate
        self.frames: queue.Queue[Frame] = queue.Queue(maxsize=1)
        self.messages: queue.Queue[str] = queue.Queue(maxsize=8)
        self.outgoing: queue.PriorityQueue[
            Tuple[int, int, Optional[str], int, int, str, bytes]
        ] = queue.PriorityQueue()
        self.stop_event = threading.Event()
        self.serial_port: Optional[serial.Serial] = None
        self.serial_lock = threading.Lock()
        self.pending_commands: Dict[int, Tuple[float, str]] = {}
        self.pending_lock = threading.Lock()
        self.coalesce_generation: Dict[str, int] = {}
        self.coalesce_lock = threading.Lock()
        self.pressed_keys: Dict[int, str] = {}
        self.repeat_after_ids: Dict[int, str] = {}
        self.next_command_id = 1

        self.connection_state = "Verbinde"
        self.last_frame: Optional[Frame] = None
        self.last_native_image: Optional[Image.Image] = None
        self.last_frame_time = 0.0
        self.last_ack_latency_ms: Optional[float] = None
        self.frame_times: Deque[float] = deque(maxlen=240)
        self.fullscreen = False
        self.render_after_id: Optional[str] = None
        self.photo_buffers: list[Optional[ImageTk.PhotoImage]] = [None, None]
        self.photo_slot = 0

        root.title(f"Jarnsen Tactical Display Mirror - {port}")
        root.geometry("1050x720")
        root.minsize(640, 420)
        root.resizable(True, True)
        root.protocol("WM_DELETE_WINDOW", self.close)
        root.bind_all("<KeyPress>", self._on_key_press)
        root.bind_all("<KeyRelease>", self._on_key_release)
        root.bind_all("<FocusOut>", self._release_all_keys)
        root.bind_all("<MouseWheel>", self._on_mouse_wheel)
        root.bind_all("<F11>", self._toggle_fullscreen)
        root.bind_all("<F12>", self._save_screenshot)
        root.bind_all("<Control-s>", self._save_screenshot)
        root.bind_all("<Control-S>", self._save_screenshot)
        root.focus_force()

        toolbar = ttk.Frame(root, padding=(10, 8, 10, 4))
        toolbar.pack(fill="x")
        ttk.Label(toolbar, text="Darstellung:").pack(side="left")
        self.render_mode = tk.StringVar(
            value="HD geglättet" if render_mode == "hd" else "Pixel scharf"
        )
        mode_box = ttk.Combobox(
            toolbar,
            textvariable=self.render_mode,
            values=("Pixel scharf", "HD geglättet"),
            state="readonly",
            width=16,
        )
        mode_box.pack(side="left", padx=(6, 14))
        mode_box.bind("<<ComboboxSelected>>", lambda _event: self._schedule_render())
        ttk.Button(
            toolbar, text="Screenshot (F12)", command=self._save_screenshot
        ).pack(side="left")
        ttk.Button(
            toolbar, text="Vollbild (F11)", command=self._toggle_fullscreen
        ).pack(side="left", padx=(8, 0))
        self.notice = tk.StringVar(value="")
        ttk.Label(toolbar, textvariable=self.notice, anchor="e").pack(
            side="right", fill="x", expand=True
        )

        display_frame = ttk.Frame(root, padding=(10, 4, 10, 4))
        display_frame.pack(fill="both", expand=True)
        self.canvas = tk.Canvas(
            display_frame,
            bg="black",
            highlightthickness=0,
            takefocus=True,
        )
        self.canvas.pack(fill="both", expand=True)
        self.canvas_image = self.canvas.create_image(0, 0, anchor="center")
        self.canvas.bind("<Configure>", lambda _event: self._schedule_render())
        self.canvas.focus_set()

        controls_frame = ttk.LabelFrame(root, text="PC-Steuerung", padding=(10, 6))
        controls_frame.pack(fill="x", padx=10, pady=(2, 4))
        control_items = (
            ("← / → oder A / D", "Seite wechseln"),
            ("↑ / ↓ oder W / S", "Menü/Auswahl bewegen"),
            ("Leertaste / Enter", "Auswählen oder bestätigen"),
            ("Esc / Rücktaste", "Zurück"),
            ("Mausrad", "Menü hoch/runter"),
            ("F11 / F12", "Vollbild / Screenshot"),
        )
        for index, (keys, description) in enumerate(control_items):
            row = index // 3
            column = index % 3
            item = ttk.Frame(controls_frame)
            item.grid(row=row, column=column, sticky="w", padx=(0, 24), pady=2)
            ttk.Label(item, text=keys, width=20, anchor="w").pack(side="left")
            ttk.Label(item, text=description, anchor="w").pack(side="left")
        for column in range(3):
            controls_frame.grid_columnconfigure(column, weight=1)

        self.status = tk.StringVar(value=f"Verbinde mit {port} @ {baudrate} Baud ...")
        ttk.Label(
            root, textvariable=self.status, anchor="w", padding=(10, 4, 10, 8)
        ).pack(fill="x")

        self._render_blank()
        self.reader = threading.Thread(target=self._reader_loop, daemon=True)
        self.writer = threading.Thread(target=self._writer_loop, daemon=True)
        self.reader.start()
        self.writer.start()
        root.after(STATUS_REFRESH_MS, self._poll)

    def _render_blank(self) -> None:
        self.last_native_image = Image.new(
            "RGB", (EXPECTED_WIDTH, EXPECTED_HEIGHT), "black"
        )
        self._schedule_render()

    def _reader_loop(self) -> None:
        decoder = FrameDecoder()
        try:
            port = serial.Serial(
                self.port,
                self.baudrate,
                timeout=0.15,
                write_timeout=0.05,
            )
            with self.serial_lock:
                self.serial_port = port
            self.connection_state = "Verbunden"
            self._queue_wire_message(b"@TMC CAPS TMF3 ACK1\n", priority=-100)
            self._put_message(f"Verbunden: {self.port} @ {self.baudrate} Baud")

            while not self.stop_event.is_set():
                raw = port.readline()
                if not raw:
                    continue

                ack = parse_ack(raw)
                if ack is not None:
                    self._handle_ack(*ack)
                    continue

                frame = decoder.feed(raw)
                if frame is None:
                    continue
                self._publish_newest_frame(frame)
        except (serial.SerialException, OSError) as exc:
            self.connection_state = "Getrennt"
            self._put_message(f"Serieller Fehler: {exc}")
        finally:
            with self.serial_lock:
                port = self.serial_port
                self.serial_port = None
            if port is not None and port.is_open:
                port.close()

    def _writer_loop(self) -> None:
        while not self.stop_event.is_set():
            try:
                (
                    priority,
                    order,
                    coalesce_key,
                    generation,
                    request_id,
                    command,
                    payload,
                ) = self.outgoing.get(timeout=0.1)
            except queue.Empty:
                continue
            del priority, order

            if coalesce_key and not self._is_current_generation(
                coalesce_key, generation
            ):
                continue

            if coalesce_key == "navigation":
                stale = False
                while not self.stop_event.is_set():
                    with self.pending_lock:
                        in_flight = sum(
                            1
                            for _sent_at, pending_command in self.pending_commands.values()
                            if pending_command in REPEATABLE_COMMANDS
                        )
                    if in_flight < MAX_NAVIGATION_IN_FLIGHT:
                        break
                    if not self._is_current_generation(coalesce_key, generation):
                        stale = True
                        break
                    time.sleep(0.004)
                if stale or self.stop_event.is_set():
                    continue

            port: Optional[serial.Serial]
            with self.serial_lock:
                port = self.serial_port
            if port is None or not port.is_open:
                continue

            if request_id:
                with self.pending_lock:
                    self.pending_commands[request_id] = (time.monotonic(), command)
            try:
                with self.serial_lock:
                    port.write(payload)
            except (
                serial.SerialException,
                serial.SerialTimeoutException,
                OSError,
            ) as exc:
                if request_id:
                    with self.pending_lock:
                        self.pending_commands.pop(request_id, None)
                self._put_message(f"Senden fehlgeschlagen: {exc}")

    def _publish_newest_frame(self, frame: Frame) -> None:
        while self.frames.full():
            try:
                self.frames.get_nowait()
            except queue.Empty:
                break
        try:
            self.frames.put_nowait(frame)
        except queue.Full:
            pass

    def _queue_wire_message(
        self,
        payload: bytes,
        priority: int = 0,
        coalesce_key: Optional[str] = None,
        request_id: int = 0,
        command: str = "",
    ) -> None:
        generation = 0
        if coalesce_key:
            with self.coalesce_lock:
                generation = self.coalesce_generation.get(coalesce_key, 0) + 1
                self.coalesce_generation[coalesce_key] = generation
        order = time.monotonic_ns()
        self.outgoing.put(
            (
                priority,
                order,
                coalesce_key,
                generation,
                request_id,
                command,
                payload,
            )
        )

    def _is_current_generation(self, coalesce_key: str, generation: int) -> bool:
        with self.coalesce_lock:
            return self.coalesce_generation.get(coalesce_key) == generation

    def _on_key_press(self, event: tk.Event) -> Optional[str]:
        # Keep shortcuts such as Ctrl+S available instead of treating the S as DOWN.
        if int(event.state) & 0x000C:
            return None
        command = KEY_COMMANDS.get(event.keysym)
        if command is None:
            return None

        key_id = int(event.keycode)
        if key_id in self.pressed_keys:
            return "break"

        self.pressed_keys[key_id] = command
        self._send_command(command)
        if command in REPEATABLE_COMMANDS:
            self.repeat_after_ids[key_id] = self.root.after(
                KEY_REPEAT_DELAY_MS,
                lambda key_id=key_id, command=command: self._repeat_key(
                    key_id, command
                ),
            )
        return "break"

    def _on_key_release(self, event: tk.Event) -> Optional[str]:
        key_id = int(event.keycode)
        command = self.pressed_keys.pop(key_id, None)
        after_id = self.repeat_after_ids.pop(key_id, None)
        if after_id is not None:
            try:
                self.root.after_cancel(after_id)
            except tk.TclError:
                pass
        return "break" if command is not None else None

    def _repeat_key(self, key_id: int, command: str) -> None:
        if self.pressed_keys.get(key_id) != command:
            self.repeat_after_ids.pop(key_id, None)
            return
        self._send_command(command)
        self.repeat_after_ids[key_id] = self.root.after(
            KEY_REPEAT_INTERVAL_MS,
            lambda key_id=key_id, command=command: self._repeat_key(key_id, command),
        )

    def _release_all_keys(self, _event: Optional[tk.Event] = None) -> None:
        self.pressed_keys.clear()
        for after_id in self.repeat_after_ids.values():
            try:
                self.root.after_cancel(after_id)
            except tk.TclError:
                pass
        self.repeat_after_ids.clear()

    def _on_mouse_wheel(self, event: tk.Event) -> str:
        self._send_command("UP" if event.delta > 0 else "DOWN")
        return "break"

    def _send_command(self, command: str) -> None:
        with self.serial_lock:
            port = self.serial_port
        if port is None or not port.is_open:
            self._put_message("Nicht verbunden - Eingabe wurde nicht gesendet")
            return

        request_id = self.next_command_id
        self.next_command_id = (self.next_command_id + 1) & 0x7FFFFFFF
        if self.next_command_id == 0:
            self.next_command_id = 1
        payload = f"@TMC {request_id} {command}\n".encode("ascii")
        self._queue_wire_message(
            payload,
            priority=-1000,
            coalesce_key=("navigation" if command in REPEATABLE_COMMANDS else None),
            request_id=request_id,
            command=command,
        )
        self.notice.set(f"Taste: {command}")

    def _handle_ack(
        self, request_id: int, status: str, firmware_millis: Optional[int]
    ) -> None:
        del firmware_millis
        with self.pending_lock:
            pending = self.pending_commands.pop(request_id, None)
        if pending is None:
            return
        sent_at, _command = pending
        latency_ms = (time.monotonic() - sent_at) * 1000.0
        if self.last_ack_latency_ms is None:
            self.last_ack_latency_ms = latency_ms
        else:
            self.last_ack_latency_ms = self.last_ack_latency_ms * 0.7 + latency_ms * 0.3
        if status != "OK":
            self._put_message(f"Tracker-ACK {request_id}: {status}")

    def _put_message(self, message: str) -> None:
        while self.messages.full():
            try:
                self.messages.get_nowait()
            except queue.Empty:
                break
        try:
            self.messages.put_nowait(message)
        except queue.Full:
            pass

    def _poll(self) -> None:
        try:
            while True:
                self.notice.set(self.messages.get_nowait())
        except queue.Empty:
            pass

        newest: Optional[Frame] = None
        try:
            while True:
                newest = self.frames.get_nowait()
        except queue.Empty:
            pass

        if newest is not None:
            self.last_frame = newest
            self.last_frame_time = newest.received_at
            self.frame_times.append(newest.received_at)
            self.last_native_image = Image.frombytes(
                "RGB", (newest.width, newest.height), newest.rgb
            )
            self._schedule_render()

        self._expire_pending_commands()
        self._update_status()

        if not self.stop_event.is_set():
            self.root.after(STATUS_REFRESH_MS, self._poll)

    def _expire_pending_commands(self) -> None:
        cutoff = time.monotonic() - 3.0
        with self.pending_lock:
            expired = [
                request_id
                for request_id, (sent_at, _command) in self.pending_commands.items()
                if sent_at < cutoff
            ]
            for request_id in expired:
                del self.pending_commands[request_id]

    def _update_status(self) -> None:
        now = time.monotonic()
        while self.frame_times and now - self.frame_times[0] > 1.0:
            self.frame_times.popleft()
        fps = float(len(self.frame_times))
        if self.last_frame is None:
            frame_age = "-"
            resolution = f"{EXPECTED_WIDTH}x{EXPECTED_HEIGHT}"
            source_format = "warte auf Frame"
        else:
            frame_age = f"{(now - self.last_frame.received_at) * 1000.0:.0f} ms"
            resolution = f"{self.last_frame.width}x{self.last_frame.height}"
            source_format = self.last_frame.source_format
        latency = (
            f"{self.last_ack_latency_ms:.1f} ms"
            if self.last_ack_latency_ms is not None
            else "-"
        )
        self.status.set(
            f"{self.connection_state} | {self.port} @ {self.baudrate} | "
            f"{source_format} | {resolution} | FPS {fps:.0f} | "
            f"Frame-Alter {frame_age} | USB-RTT {latency}"
        )

    def _schedule_render(self) -> None:
        if self.render_after_id is not None:
            try:
                self.root.after_cancel(self.render_after_id)
            except tk.TclError:
                pass
        self.render_after_id = self.root.after(RENDER_DEBOUNCE_MS, self._render_current)

    def _render_current(self) -> None:
        self.render_after_id = None
        image = self.last_native_image
        if image is None:
            return

        canvas_width = max(1, self.canvas.winfo_width())
        canvas_height = max(1, self.canvas.winfo_height())
        scale = min(canvas_width / image.width, canvas_height / image.height)
        target_width = max(1, int(image.width * scale))
        target_height = max(1, int(image.height * scale))
        resample = (
            RESAMPLING.LANCZOS
            if self.render_mode.get() == "HD geglättet"
            else RESAMPLING.NEAREST
        )
        rendered = image.resize((target_width, target_height), resample=resample)

        self.photo_slot ^= 1
        photo = ImageTk.PhotoImage(rendered)
        self.photo_buffers[self.photo_slot] = photo
        self.canvas.coords(self.canvas_image, canvas_width // 2, canvas_height // 2)
        self.canvas.itemconfigure(self.canvas_image, image=photo)

    def _toggle_fullscreen(self, _event: Optional[tk.Event] = None) -> str:
        self.fullscreen = not self.fullscreen
        self.root.attributes("-fullscreen", self.fullscreen)
        self.notice.set("Vollbild an" if self.fullscreen else "Vollbild aus")
        self._schedule_render()
        return "break"

    def _save_screenshot(self, _event: Optional[tk.Event] = None) -> str:
        image = self.last_native_image
        if image is None:
            self.notice.set("Noch kein Bild für einen Screenshot vorhanden")
            return "break"

        screenshot_dir = Path(__file__).resolve().parent / "screenshots"
        screenshot_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")[:-3]
        sequence = (
            f"-frame-{self.last_frame.sequence}"
            if self.last_frame is not None and self.last_frame.sequence
            else ""
        )
        path = screenshot_dir / f"jarnsen-tactical-{timestamp}{sequence}.png"
        try:
            image.save(path, format="PNG")
            self.notice.set(f"Screenshot gespeichert: {path.name}")
        except OSError as exc:
            self.notice.set(f"Screenshot fehlgeschlagen: {exc}")
        return "break"

    def close(self) -> None:
        self._release_all_keys()
        self.stop_event.set()
        with self.serial_lock:
            port = self.serial_port
            self.serial_port = None
        if port is not None and port.is_open:
            port.close()
        self.root.destroy()


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Spiegelt und steuert die sichtbare Displayseite eines "
            "Jarnsen Tactical Trackers unter Windows."
        )
    )
    parser.add_argument("port", nargs="?", help="COM-Port, zum Beispiel COM5")
    parser.add_argument(
        "--baud",
        type=int,
        default=DEFAULT_BAUD_RATE,
        help=f"Baudrate (Standard: {DEFAULT_BAUD_RATE})",
    )
    parser.add_argument(
        "--mode",
        choices=("pixel", "hd"),
        default="pixel",
        help="Darstellung: pixel = scharf, hd = geglättet",
    )
    args = parser.parse_args()

    port = find_port(args.port)
    root = tk.Tk()
    MirrorWindow(root, port=port, baudrate=args.baud, render_mode=args.mode)
    root.mainloop()


if __name__ == "__main__":
    main()
