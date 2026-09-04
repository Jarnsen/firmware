"""Headless adapter for the proven Jarnsen Service Tool device logic.

Framework7 is the only presentation layer.  This module deliberately creates a
ServiceTool-derived object without calling tkinter.Tk.__init__ and without
constructing any legacy widgets.  Small thread-safe value/widget proxies provide
only the state surfaces that the mature v2.1.x service methods still reference
while those methods are progressively extracted into standalone components.
"""
from __future__ import annotations

import contextlib
import queue
import threading
from pathlib import Path
from typing import Any, Callable


class HeadlessValue:
    """Thread-safe replacement for the tiny get/set part of Tk variables."""

    def __init__(self, value: Any = "") -> None:
        self._value = value
        self._lock = threading.RLock()

    def get(self) -> Any:
        with self._lock:
            return self._value

    def set(self, value: Any) -> None:
        with self._lock:
            self._value = value

    def trace_add(self, *_args: Any, **_kwargs: Any) -> str:
        return "headless-trace"

    def trace_remove(self, *_args: Any, **_kwargs: Any) -> None:
        return None


class HeadlessChoice(HeadlessValue):
    def __init__(self, value: Any = "", values: tuple[Any, ...] | list[Any] = ()) -> None:
        super().__init__(value)
        self.values = list(values)
        self._state = "normal"

    def current(self, index: int | None = None) -> int:
        if index is None:
            try:
                return self.values.index(self.get())
            except ValueError:
                return -1
        if 0 <= int(index) < len(self.values):
            self.set(self.values[int(index)])
        return int(index)

    def configure(self, **kwargs: Any) -> None:
        if "values" in kwargs:
            self.values = list(kwargs["values"])
        if "state" in kwargs:
            self._state = str(kwargs["state"])

    config = configure

    def cget(self, key: str) -> Any:
        if key == "values":
            return tuple(self.values)
        if key == "state":
            return self._state
        return ""


class HeadlessEntry(HeadlessValue):
    def delete(self, *_args: Any) -> None:
        self.set("")

    def insert(self, _index: Any, value: Any) -> None:
        self.set(str(value))


class HeadlessText:
    def __init__(self) -> None:
        self._text = ""
        self._state = "normal"
        self._lock = threading.RLock()

    def get(self, *_args: Any) -> str:
        with self._lock:
            return self._text

    def delete(self, *_args: Any) -> None:
        with self._lock:
            self._text = ""

    def insert(self, _index: Any, value: Any, *_tags: Any) -> None:
        with self._lock:
            self._text += str(value)

    def configure(self, **kwargs: Any) -> None:
        if "state" in kwargs:
            self._state = str(kwargs["state"])

    config = configure

    def cget(self, key: str) -> Any:
        return self._state if key == "state" else ""

    def see(self, *_args: Any) -> None:
        return None


class HeadlessLabel:
    def __init__(self, text: str = "") -> None:
        self._text = str(text)
        self._state = "normal"

    def configure(self, **kwargs: Any) -> None:
        if "text" in kwargs:
            self._text = str(kwargs["text"])
        if "state" in kwargs:
            self._state = str(kwargs["state"])

    config = configure

    def cget(self, key: str) -> Any:
        if key == "text":
            return self._text
        if key == "state":
            return self._state
        return ""


class HeadlessListbox:
    def __init__(self) -> None:
        self.items: list[str] = []
        self.selected: set[int] = set()

    def delete(self, first: Any, last: Any = None) -> None:
        if str(first) in {"0", "0.0"} and (last is None or str(last) == "end"):
            self.items.clear()
            self.selected.clear()
            return
        with contextlib.suppress(Exception):
            index = int(first)
            if 0 <= index < len(self.items):
                self.items.pop(index)
                self.selected = {i for i in self.selected if i != index}

    def insert(self, index: Any, value: Any) -> None:
        if str(index) == "end":
            self.items.append(str(value))
        else:
            try:
                self.items.insert(int(index), str(value))
            except Exception:
                self.items.append(str(value))

    def curselection(self) -> tuple[int, ...]:
        return tuple(sorted(self.selected))

    def selection_clear(self, first: Any, last: Any = None) -> None:
        if str(first) == "0" and (last is None or str(last) == "end"):
            self.selected.clear()
            return
        with contextlib.suppress(Exception):
            self.selected.discard(int(first))

    def selection_set(self, first: Any, last: Any = None) -> None:
        with contextlib.suppress(Exception):
            start = int(first)
            end = start if last is None or str(last) == "end" else int(last)
            for index in range(start, end + 1):
                if 0 <= index < len(self.items):
                    self.selected.add(index)

    def get(self, index: Any) -> str:
        return self.items[int(index)]

    def size(self) -> int:
        return len(self.items)


class HeadlessScheduler:
    """Small cross-thread scheduler used instead of Tcl/Tk's event loop."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._timers: dict[str, threading.Timer] = {}
        self._counter = 0
        self.closed = False

    def after(self, milliseconds: int, callback: Callable[..., Any] | None = None, *args: Any) -> str:
        with self._lock:
            self._counter += 1
            token = f"headless-after-{self._counter}"
            if self.closed or callback is None:
                return token

            def run() -> None:
                try:
                    if not self.closed:
                        callback(*args)
                finally:
                    with self._lock:
                        self._timers.pop(token, None)

            timer = threading.Timer(max(0.0, float(milliseconds) / 1000.0), run)
            timer.daemon = True
            self._timers[token] = timer
            timer.start()
            return token

    def after_idle(self, callback: Callable[..., Any], *args: Any) -> str:
        return self.after(0, callback, *args)

    def cancel(self, token: str) -> None:
        with self._lock:
            timer = self._timers.pop(str(token), None)
        if timer is not None:
            timer.cancel()

    def close(self) -> None:
        with self._lock:
            self.closed = True
            timers = list(self._timers.values())
            self._timers.clear()
        for timer in timers:
            timer.cancel()


class HeadlessStyle:
    def configure(self, *_args: Any, **_kwargs: Any) -> None:
        return None

    def map(self, *_args: Any, **_kwargs: Any) -> None:
        return None

    def theme_use(self, *_args: Any, **_kwargs: Any) -> str:
        return "headless"


class HeadlessNotebook:
    def __init__(self) -> None:
        self.selected: Any = None

    def select(self, value: Any = None) -> Any:
        if value is not None:
            self.selected = value
        return self.selected


class HeadlessProgress:
    def __init__(self) -> None:
        self.value = 0

    def configure(self, **kwargs: Any) -> None:
        if "value" in kwargs:
            self.value = kwargs["value"]

    config = configure

    def __setitem__(self, key: str, value: Any) -> None:
        if key == "value":
            self.value = value

    def __getitem__(self, key: str) -> Any:
        if key == "value":
            return self.value
        raise KeyError(key)


class _HeadlessBase:
    """Mixin overrides for methods that were presentation-only in v2.1.x."""

    def after(self, milliseconds: int, callback: Callable[..., Any] | None = None, *args: Any) -> str:
        return self._headless_scheduler.after(milliseconds, callback, *args)

    def after_idle(self, callback: Callable[..., Any], *args: Any) -> str:
        return self._headless_scheduler.after_idle(callback, *args)

    def after_cancel(self, token: str) -> None:
        self._headless_scheduler.cancel(token)

    def destroy(self) -> None:
        self._headless_destroyed = True
        self._headless_scheduler.close()

    def protocol(self, *_args: Any, **_kwargs: Any) -> None:
        return None

    def withdraw(self) -> None:
        return None

    def winfo_toplevel(self) -> Any:
        return self

    def winfo_exists(self) -> bool:
        return not self._headless_destroyed

    def update(self) -> None:
        return None

    def update_idletasks(self) -> None:
        return None

    def refresh_ports(self) -> None:
        return None

    def refresh_nodes(self) -> None:
        return None

    def refresh_all_nodes_overview(self) -> bool:
        with contextlib.suppress(Exception):
            self.repository.scan_logs()
        return True

    def render_dashboard(self) -> None:
        return None

    def render_track_map(self) -> None:
        return None

    def render_node_tiles_v2132(self) -> None:
        return None

    def apply_theme(self) -> None:
        return None

    def _maximize_window(self) -> None:
        return None

    def _refresh_config_profile_ui(self) -> None:
        return None

    def _set_config_profile_buttons_state(self, _state: str) -> None:
        return None

    def _select_serial_port_in_ui(self, port: str) -> None:
        self.port.set(str(port or ""))

    def _select_ble_entries_v2133(self, entries: list[tuple[str, object]]) -> None:
        labels = list(getattr(self, "ble_map", {}))
        wanted = {label for label, _device in entries}
        self.ble_device.selection_clear(0, "end")
        for index, label in enumerate(labels):
            if label in wanted:
                self.ble_device.selection_set(index)

    def set_transfer_progress(self, percent: Any = None, text: str = "", active: bool = False) -> None:
        if percent is not None:
            with contextlib.suppress(Exception):
                self.progress["value"] = float(percent)
            self.progress_percent.configure(text=f"{int(float(percent))} %")
        self.progress_text.configure(text=str(text or ""))
        self._headless_transfer_active = bool(active)

    def set_status(self, text: str, level: str = "normal") -> None:
        self.status_text_var.set(str(text or ""))
        self.status_level = str(level or "normal")

    def _build_ui(self) -> None:
        return None


def build_headless_tool(legacy: Any) -> Any:
    """Create a ServiceTool-compatible service object with no Tk interpreter."""

    class HeadlessServiceTool(_HeadlessBase, legacy.ServiceTool):
        def __init__(self) -> None:
            # Deliberately do not call legacy.ServiceTool.__init__ or tk.Tk.__init__.
            self._headless_scheduler = HeadlessScheduler()
            self._headless_destroyed = False
            self._headless_transfer_active = False
            self._headless_lock = threading.RLock()

            self.events: queue.Queue[tuple[str, object]] = queue.Queue()
            self.stop_event = threading.Event()
            self.worker: threading.Thread | None = None
            self.worker_running = False
            self.live_worker: threading.Thread | None = None
            self.last_output: Path | None = None
            self.last_payload: bytes | None = None
            self.last_comparison = ""
            self.expected_device = "Automatisch"
            self.status_level = "normal"
            self.port_map: dict[str, str] = {}
            self.ble_map: dict[str, object] = {}
            self.node_sync_state_v2132: dict[str, str] = {}
            self.node_selection_v2133: dict[str, HeadlessValue] = {}
            self.visible_node_ids_v2133: list[str] = []
            self._auto_ble_after_v2132 = None
            self._auto_ble_retry_after_v2133 = None

            self.repository = legacy.NodeRepository()
            self.firmware_cache_path = legacy.output_directory() / "Jarnsen_Firmware_Status.json"
            with contextlib.suppress(Exception):
                self.firmware_releases = self._load_firmware_cache()
            if not hasattr(self, "firmware_releases"):
                self.firmware_releases = {}
            self.firmware_check_running = False
            self.selected_node_id = ""
            self.node_logs: list[dict[str, object]] = []

            self.show_archived_var = HeadlessValue(False)
            self.live_stop = threading.Event()
            self.live_commands: queue.Queue[str] = queue.Queue()
            self.live_connected = False
            self.live_snapshot: dict[str, object] = {}
            self.live_image = None
            self.style = HeadlessStyle()
            self.track_points: list[dict[str, object]] = []
            self.track_view = None

            # Headless replacements for controls still referenced by service code.
            self.device = HeadlessChoice("Automatisch", ("Automatisch", "Tracker V1.1", "Heltec V3"))
            self.port = HeadlessChoice("")
            self.ble_device = HeadlessListbox()
            self.notebook = HeadlessNotebook()
            self.live_tab = object()
            self.progress = HeadlessProgress()
            self.progress_percent = HeadlessLabel("0 %")
            self.progress_text = HeadlessLabel("Bereit")
            self.status = HeadlessLabel("Bereit")
            self.status_badge = HeadlessLabel(" BEREIT ")
            self.status_text_var = HeadlessValue("Bereit")
            self.status_var = self.status_text_var

            # Profile/service state formerly created as a side effect of old tabs.
            self.config_profile_transport_var = HeadlessValue("Automatisch")
            self.config_target_long_var = HeadlessValue("")
            self.config_target_short_var = HeadlessValue("")
            self.config_bt_pin_var = HeadlessValue("240180")
            self.config_apply_bt_pin_var = HeadlessValue(True)
            self.config_apply_psk_var = HeadlessValue(False)
            self.config_profile_slot_var = HeadlessValue(0)
            self.config_profile_category_var = HeadlessValue("Gerät & Mesh")

            # Serial monitor/recovery controls used by Framework7 parity APIs.
            self.serial_baud = HeadlessChoice("115200")
            self.serial_send_newline_var = HeadlessValue(True)
            self.serial_command = HeadlessEntry("")
            self.serial_monitor_text = HeadlessText()
            self.serial_monitor_status = HeadlessLabel("Monitor gestoppt")
            self.serial_monitor_bytes = 0
            self.serial_monitor_log_path = ""
            self.serial_monitor_worker = None
            self.serial_monitor_stop = threading.Event()

            self.app_update_manifest: dict[str, object] = {}
            self.app_update_available = False
            self.app_update_url = ""
            self._provision_active = False
            self._provision_context = None

            # Load persistent profile state directly; no hidden profile page needed.
            if hasattr(self, "_load_config_profile_store"):
                with contextlib.suppress(Exception):
                    self.config_profile_store = self._load_config_profile_store()
            if not hasattr(self, "config_profile_store") or not isinstance(self.config_profile_store, dict):
                self.config_profile_store = {
                    "schema": 1,
                    "authorized_915": {"a_mhz": "", "b_mhz": ""},
                    "profiles": [None, None, None, None],
                }
            profiles = self.config_profile_store.get("profiles")
            if not isinstance(profiles, list):
                self.config_profile_store["profiles"] = [None, None, None, None]
            while len(self.config_profile_store["profiles"]) < 4:
                self.config_profile_store["profiles"].append(None)

            self.mac_activity_events_v220: list[str] = []

            # Background service event drain: keep status/activity useful without
            # recreating the old Tk event pump.
            self.after(100, self._headless_pump_events)

        def _headless_pump_events(self) -> None:
            if self._headless_destroyed:
                return
            for _ in range(250):
                try:
                    kind, payload = self.events.get_nowait()
                except queue.Empty:
                    break
                text = str(payload or "")
                if kind in {"status", "status_normal", "status_success", "status_warning", "status_error"}:
                    self.status_text_var.set(text)
                    if kind.startswith("status_"):
                        self.status_level = kind.removeprefix("status_")
                elif kind == "progress":
                    with contextlib.suppress(Exception):
                        self.set_transfer_progress(float(payload), self.progress_text.cget("text"), self._headless_transfer_active)
                elif kind == "progress_detail":
                    try:
                        percent, detail, active = payload
                    except Exception:
                        percent, detail, active = None, text, self._headless_transfer_active
                    self.set_transfer_progress(percent, str(detail or ""), bool(active))
                elif kind == "auto_ble_trace_v2133" and text:
                    self.mac_activity_events_v220.append(text)
                    del self.mac_activity_events_v220[:-200]
                elif kind in {"node_cards_refresh_v2132", "done"}:
                    pass
                elif text:
                    self.mac_activity_events_v220.append(f"{kind}: {text}")
                    del self.mac_activity_events_v220[:-200]
            self.after(100, self._headless_pump_events)

    return HeadlessServiceTool()
