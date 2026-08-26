"""v1.7 additions for the shared Jarnsen Node Service Tool.

Adds a Bluetooth-backed serial monitor using Meshtastic LOGRADIO notifications
and turns the old font-oriented zoom into whole-window density scaling with an
automatic fit mode aimed at 1920x1080 notebooks running Windows at 125% DPI.
Runs after the v1.6 patcher.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

APP_VERSION = "1.7.0"


def method_span(text: str, name: str) -> tuple[int, int]:
    start = text.find(f"    def {name}(")
    if start < 0:
        raise SystemExit(f"method {name} not found")
    next_method = text.find("\n    def ", start + 1)
    return start, next_method if next_method >= 0 else len(text)


def insert_before_method(text: str, name: str, code: str) -> str:
    start, _ = method_span(text, name)
    return text[:start] + code.rstrip() + "\n\n" + text[start:]


def patch(source: str) -> str:
    source = re.sub(r'APP_VERSION = "[^"]+"', f'APP_VERSION = "{APP_VERSION}"', source, count=1)
    source = source.replace('APP_VERSION != "1.6.0"', 'APP_VERSION != "1.7.0"')
    source = source.replace('App-Version ist nicht v1.6.0', 'App-Version ist nicht v1.7.0')

    # Meshtastic's existing protobuf debug-log notification characteristic.
    if 'LOGRADIO_UUID = "5a3d6e49-06e6-4423-9944-e9de8cdf9547"' not in source:
        anchor = 'MESH_SERVICE_UUID = "6ba1b218-15a8-461f-9fa8-5dcae273eafd"\n'
        if source.count(anchor) != 1:
            raise SystemExit("MESH service UUID anchor not found")
        source = source.replace(
            anchor,
            anchor + 'LOGRADIO_UUID = "5a3d6e49-06e6-4423-9944-e9de8cdf9547"\n',
            1,
        )

    if "def decode_meshtastic_log_record(" not in source:
        anchor = "\ndef output_directory() -> pathlib.Path:\n"
        if source.count(anchor) != 1:
            raise SystemExit("output_directory anchor not found")
        helper = r'''


def decode_meshtastic_log_record(payload: bytes) -> str:
    """Decode the small Meshtastic LogRecord protobuf without a protobuf runtime."""

    def read_varint(data: bytes, offset: int) -> tuple[int, int]:
        value = 0
        shift = 0
        while offset < len(data) and shift <= 63:
            byte = data[offset]
            offset += 1
            value |= (byte & 0x7F) << shift
            if not byte & 0x80:
                return value, offset
            shift += 7
        raise ValueError("invalid protobuf varint")

    message = ""
    source_name = ""
    level = 0
    timestamp = 0
    offset = 0
    try:
        while offset < len(payload):
            key, offset = read_varint(payload, offset)
            field = key >> 3
            wire = key & 0x07
            if wire == 0:
                value, offset = read_varint(payload, offset)
                if field == 4:
                    level = int(value)
            elif wire == 2:
                length, offset = read_varint(payload, offset)
                end = offset + int(length)
                if end > len(payload):
                    raise ValueError("truncated protobuf string")
                value = payload[offset:end]
                offset = end
                if field == 1:
                    message = value.decode("utf-8", "replace")
                elif field == 3:
                    source_name = value.decode("utf-8", "replace")
            elif wire == 5:
                end = offset + 4
                if end > len(payload):
                    raise ValueError("truncated protobuf fixed32")
                value = int.from_bytes(payload[offset:end], "little", signed=False)
                offset = end
                if field == 2:
                    timestamp = value
            elif wire == 1:
                offset += 8
            else:
                raise ValueError(f"unsupported protobuf wire type {wire}")
    except (ValueError, IndexError):
        return "[BT-LOG] " + payload.hex(" ")

    level_name = {
        50: "CRITICAL",
        40: "ERROR",
        30: "WARN",
        20: "INFO",
        10: "DEBUG",
        5: "TRACE",
        0: "LOG",
    }.get(level, f"LOG{level}")
    if timestamp:
        try:
            stamp = dt.datetime.fromtimestamp(timestamp, dt.timezone.utc).astimezone().strftime("%H:%M:%S")
        except (OverflowError, OSError, ValueError):
            stamp = "??:??:??"
    else:
        stamp = "??:??:??"
    origin = f"[{source_name}] " if source_name else ""
    text = message.rstrip("\r\n")
    return f"{level_name} | {stamp} {origin}{text}".rstrip()
'''
        source = source.replace(anchor, helper + anchor, 1)

    # Runtime state for transport-aware serial monitor and full-window zoom.
    state_anchor = '''        self.serial_monitor_bytes = 0
        self.serial_display_paused = False
'''
    if "self.serial_monitor_transport" not in source:
        state_new = '''        self.serial_monitor_bytes = 0
        self.serial_monitor_transport = "USB / COM"
        self.ui_scale_factor = 1.0
        self.ui_effective_zoom_percent = 100
        self.serial_display_paused = False
'''
        if source.count(state_anchor) != 1:
            raise SystemExit("v1.7 runtime state anchor not found")
        source = source.replace(state_anchor, state_new, 1)

    # Expose the left control content so the scrollbar can disappear whenever
    # the entire column fits at the current zoom.
    controls_anchor = '''        controls = ttk.Frame(self.controls_canvas, padding=(0, 0, 8, 0))
        self.controls_window = self.controls_canvas.create_window(
            (0, 0), window=controls, anchor="nw"
        )
'''
    if "self.controls_content = ttk.Frame" not in source:
        controls_new = '''        self.controls_content = ttk.Frame(self.controls_canvas, padding=(0, 0, 8, 0))
        controls = self.controls_content
        self.controls_window = self.controls_canvas.create_window(
            (0, 0), window=controls, anchor="nw"
        )
'''
        if source.count(controls_anchor) != 1:
            raise SystemExit("controls content anchor not found")
        source = source.replace(controls_anchor, controls_new, 1)

    # Transport picker in the existing Serial Monitor tab.
    toolbar_anchor = '''        ttk.Label(serial_toolbar, text="Port: Auswahl links · Baud").pack(side="left")
        self.serial_baud = ttk.Combobox(
'''
    if "self.serial_source = ttk.Combobox" not in source:
        toolbar_new = '''        ttk.Label(serial_toolbar, text="Quelle").pack(side="left")
        self.serial_source = ttk.Combobox(
            serial_toolbar,
            state="readonly",
            values=("USB / COM", "Bluetooth"),
            width=12,
        )
        self.serial_source.set("USB / COM")
        self.serial_source.pack(side="left", padx=(6, 10))
        self.serial_source.bind(
            "<<ComboboxSelected>>", lambda _event: self.update_serial_monitor_source_ui()
        )
        ttk.Label(serial_toolbar, text="Baud").pack(side="left")
        self.serial_baud = ttk.Combobox(
'''
        if source.count(toolbar_anchor) != 1:
            raise SystemExit("serial source toolbar anchor not found")
        source = source.replace(toolbar_anchor, toolbar_new, 1)

    # Make zoom steps clearly different and add an automatic fit mode.
    zoom_values_old = '''            values=("80 %", "90 %", "100 %", "110 %", "125 %"),
            width=7,
        )
        self.ui_zoom.set("100 %")
'''
    if 'values=("Automatisch", "75 %", "85 %", "100 %", "115 %", "130 %")' not in source:
        zoom_values_new = '''            values=("Automatisch", "75 %", "85 %", "100 %", "115 %", "130 %"),
            width=12,
        )
        self.ui_zoom.set("Automatisch")
'''
        if source.count(zoom_values_old) != 1:
            raise SystemExit("zoom combobox anchor not found")
        source = source.replace(zoom_values_old, zoom_values_new, 1)

    zoom_label_anchor = '''        ttk.Label(title_row, text="Zoom").pack(side="right", padx=(8, 0))'''
    if "self.ui_zoom_status" not in source:
        zoom_label_new = '''        self.ui_zoom_status = ttk.Label(title_row, text="", style="Subtitle.TLabel")
        self.ui_zoom_status.pack(side="right", padx=(6, 0))
        ttk.Label(title_row, text="Zoom").pack(side="right", padx=(8, 0))'''
        if source.count(zoom_label_anchor) != 1:
            raise SystemExit("zoom label anchor not found")
        source = source.replace(zoom_label_anchor, zoom_label_new, 1)

    # Start in Fit mode after the window is maximized, so the effective DPI and
    # actual monitor dimensions are already known.
    maximize_anchor = '''        self.after_idle(self._maximize_window)
        self.after(100, self._pump_events)
'''
    if "self.after(120, self.apply_ui_zoom)" not in source:
        maximize_new = '''        self.after_idle(self._maximize_window)
        self.after(120, self.apply_ui_zoom)
        self.after(100, self._pump_events)
'''
        if source.count(maximize_anchor) != 1:
            raise SystemExit("startup zoom anchor not found")
        source = source.replace(maximize_anchor, maximize_new, 1)

    # Whole-window scaling helpers. 100% means the old OS-scaled UI; Auto/Fit
    # deliberately compensates for 125/150% Windows DPI so a 1080p notebook can
    # show the complete control column without needing the scrollbar.
    if "    def apply_scaled_dimensions(self)" not in source:
        helpers = r'''    def _ui_px(self, value: int, minimum: int = 1) -> int:
        return max(minimum, int(round(value * float(getattr(self, "ui_scale_factor", 1.0)))))

    def _update_controls_scroll_state(self) -> None:
        if not hasattr(self, "controls_canvas") or not hasattr(self, "controls_content"):
            return
        try:
            self.controls_canvas.configure(scrollregion=self.controls_canvas.bbox("all"))
            required = self.controls_content.winfo_reqheight()
            visible = self.controls_canvas.winfo_height()
            needs_scroll = required > visible + self._ui_px(4)
            if needs_scroll:
                if not self.controls_scrollbar.winfo_ismapped():
                    self.controls_scrollbar.pack(side="right", fill="y")
            else:
                self.controls_canvas.yview_moveto(0.0)
                if self.controls_scrollbar.winfo_ismapped():
                    self.controls_scrollbar.pack_forget()
        except tk.TclError:
            pass

    def apply_scaled_dimensions(self) -> None:
        px = self._ui_px
        ios = hasattr(self, "theme") and self.theme.get() == "iOS"
        if hasattr(self, "root"):
            self.root.configure(padding=px(10))
        if hasattr(self, "controls_canvas"):
            self.controls_canvas.configure(width=px(365, 300))
        if hasattr(self, "progress"):
            self.progress.configure(length=px(340, 180))
        if hasattr(self, "node_tree"):
            self.node_tree.configure(height=3 if self.ui_scale_factor <= 0.90 else 4)
        if hasattr(self, "ble_device"):
            self.ble_device.configure(height=2 if self.ui_scale_factor <= 0.90 else 3)
        if hasattr(self, "trend_canvas"):
            self.trend_canvas.configure(height=px(440, 260))
        if hasattr(self, "virtual_display"):
            self.virtual_display.configure(height=px(390, 230))
        if hasattr(self, "serial_power_canvas"):
            self.serial_power_canvas.configure(height=px(58, 38), width=px(360, 220))
        self.style.configure("Treeview", rowheight=px(28 if ios else 24, 18))
        self.style.configure(
            "TButton",
            padding=(px(10 if ios else 6, 3), px(7 if ios else 4, 2)),
        )
        self.style.configure("TNotebook.Tab", padding=(px(12, 6), px(6, 3)))
        if hasattr(self, "controls_content") and not getattr(self, "_v17_controls_bound", False):
            self.controls_content.bind(
                "<Configure>", lambda _event: self.after_idle(self._update_controls_scroll_state), add="+"
            )
            self.controls_canvas.bind(
                "<Configure>", lambda _event: self.after_idle(self._update_controls_scroll_state), add="+"
            )
            self._v17_controls_bound = True
        self.update_idletasks()
        self.after_idle(self._update_controls_scroll_state)
        self.after_idle(self.render_dashboard)
        self.after_idle(self.render_trend)
        self.after_idle(self.render_virtual_display)

    def update_serial_monitor_source_ui(self) -> None:
        source_name = self.serial_source.get() if hasattr(self, "serial_source") else "USB / COM"
        self.serial_monitor_transport = source_name
        if hasattr(self, "serial_baud"):
            self.serial_baud.configure(state="disabled" if source_name == "Bluetooth" else "readonly")
        if hasattr(self, "serial_monitor_status") and not self.serial_monitor_active():
            if source_name == "Bluetooth":
                self.serial_monitor_status.configure(
                    text="Bluetooth: links genau eine Node markieren · Service am Gerät öffnen · dann Monitor starten"
                )
            else:
                self.serial_monitor_status.configure(
                    text="USB/COM: Port links auswählen · Sitzungslog wird beim Start automatisch gespeichert"
                )
'''
        source = insert_before_method(source, "apply_ui_zoom", helpers)

    start, end = method_span(source, "apply_ui_zoom")
    old_zoom_method = source[start:end]
    new_zoom_method = r'''    def apply_ui_zoom(self) -> None:
        selected = self.ui_zoom.get().strip() if hasattr(self, "ui_zoom") else "Automatisch"
        screen_w = max(800, self.winfo_screenwidth())
        screen_h = max(600, self.winfo_screenheight())
        if selected == "Automatisch":
            # Tk's normal 96-DPI scaling is 96/72 = 1.3333. At Windows 125%
            # base_tk_scaling is roughly 1.6667, so Auto selects about 80% and
            # restores the physical density a 1080p screen needs to fit the UI.
            dpi_ratio = max(1.0, float(self.base_tk_scaling) / (96.0 / 72.0))
            factor = min(1.0 / dpi_ratio, screen_w / 1920.0, screen_h / 1080.0, 1.0)
            factor = max(0.70, min(1.0, round(factor * 20.0) / 20.0))
            percent = int(round(factor * 100.0))
        else:
            match = re.search(r"\d+", selected)
            percent = int(match.group(0)) if match else 100
            percent = max(70, min(140, percent))
            factor = percent / 100.0

        self.ui_scale_factor = factor
        self.ui_effective_zoom_percent = percent
        self.tk.call("tk", "scaling", self.base_tk_scaling * factor)
        self.apply_theme()
        self.apply_scaled_dimensions()
        if hasattr(self, "ui_zoom_status"):
            suffix = "Fit" if selected == "Automatisch" else ""
            self.ui_zoom_status.configure(
                text=f"{percent}% {suffix} · {screen_w}×{screen_h}".strip()
            )
        try:
            settings = {
                "ui_zoom": selected,
                "ui_zoom_percent": percent,
                "theme": self.theme.get(),
            }
            self.settings_path.write_text(json.dumps(settings, indent=2), encoding="utf-8")
        except OSError:
            pass
'''
    source = source[:start] + new_zoom_method.rstrip() + "\n\n" + source[end:]

    # Replace the USB-only start method by a transport dispatcher while keeping
    # the v1.6 long-name filename behavior for USB sessions.
    start, end = method_span(source, "start_serial_monitor")
    new_start_method = r'''    def start_serial_monitor(self) -> None:
        source_name = self.serial_source.get() if hasattr(self, "serial_source") else "USB / COM"
        self.serial_monitor_transport = source_name
        if self.worker and self.worker.is_alive():
            messagebox.showinfo(
                "Serieller Monitor",
                "Bitte den laufenden Download oder Firmwarevorgang zuerst beenden.",
            )
            return
        if self.live_worker and self.live_worker.is_alive():
            messagebox.showinfo(
                "Serieller Monitor",
                "Bitte die Live-Anzeige zuerst trennen; beide Funktionen teilen denselben Bluetooth-Service.",
            )
            return
        if source_name == "Bluetooth":
            self.start_bluetooth_serial_monitor()
            return

        port = self.selected_port()
        if not port:
            messagebox.showerror("Serieller Monitor", "Bitte links einen COM-Port auswählen.")
            return
        try:
            baud = int(self.serial_baud.get())
        except (TypeError, ValueError):
            baud = 115200
        self.serial_monitor_stop.clear()
        self.serial_monitor_bytes = 0
        safe_port = safe_filename(port.replace(":", "_"))
        node_long_name = self._serial_monitor_long_name()
        safe_node = safe_filename(node_long_name)
        self.serial_monitor_log_path = output_directory() / (
            f"Serial_Monitor_{safe_node}_{safe_port}_{now_local():%Y-%m-%d_%H%M%S}.log"
        )
        self.serial_monitor_button.configure(text="Monitor stoppen")
        self.serial_monitor_status.configure(text=f"Verbinde {port} @ {baud} Baud …")
        self.serial_monitor_thread = threading.Thread(
            target=self._serial_monitor_worker,
            args=(port, baud, self.serial_monitor_log_path),
            daemon=True,
        )
        self.serial_monitor_thread.start()
'''
    source = source[:start] + new_start_method.rstrip() + "\n\n" + source[end:]

    if "    def start_bluetooth_serial_monitor(self)" not in source:
        bt_methods = r'''    def start_bluetooth_serial_monitor(self) -> None:
        if not BLE_AVAILABLE:
            messagebox.showerror("BT-Serieller Monitor", "Bluetooth ist in dieser App-Ausgabe nicht verfügbar.")
            return
        selected = self.selected_ble_devices()
        if len(selected) != 1:
            messagebox.showinfo(
                "BT-Serieller Monitor",
                "Bitte links genau einen Bluetooth-Node markieren.",
            )
            return
        label, ble_device = selected[0]
        device_name = str(getattr(ble_device, "name", "") or "").strip()
        if not device_name:
            device_name = label.split(" - ", 1)[0].replace("[OTA]", "").strip()
        if not device_name:
            device_name = self._serial_monitor_long_name()
        safe_node = safe_filename(device_name)
        address = str(getattr(ble_device, "address", "") or "BLE")
        safe_address = safe_filename(address.replace(":", "_"))[-24:]
        self.serial_monitor_stop.clear()
        self.serial_monitor_bytes = 0
        self.serial_monitor_transport = "Bluetooth"
        self.serial_monitor_log_path = output_directory() / (
            f"BT_Serial_Monitor_{safe_node}_{safe_address}_{now_local():%Y-%m-%d_%H%M%S}.log"
        )
        self.serial_monitor_button.configure(text="Monitor stoppen")
        self.serial_monitor_status.configure(text=f"Bluetooth-Verbindung zu {device_name} wird aufgebaut …")
        self.serial_monitor_thread = threading.Thread(
            target=self._bluetooth_serial_monitor_worker,
            args=(label, ble_device, self.serial_monitor_log_path),
            daemon=True,
        )
        self.serial_monitor_thread.start()

    def _bluetooth_serial_monitor_worker(
        self, label: str, ble_device: object, log_path: pathlib.Path
    ) -> None:
        try:
            asyncio.run(self._bluetooth_serial_monitor_async(label, ble_device, log_path))
        except Exception as exc:
            if not self.serial_monitor_stop.is_set():
                self.events.put(("serial_monitor_error", f"BT-Seriellog: {exc}"))
        finally:
            self.serial_monitor_stop.set()
            self.events.put(("serial_monitor_stopped", str(log_path)))

    async def _bluetooth_serial_monitor_async(
        self, label: str, ble_device: object, log_path: pathlib.Path
    ) -> None:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        queue_in: asyncio.Queue[bytes] = asyncio.Queue()

        def notification_handler(_characteristic: object, data: bytearray) -> None:
            with contextlib.suppress(asyncio.QueueFull):
                queue_in.put_nowait(bytes(data))

        with log_path.open("wb") as handle:
            header = (
                f"# Jarnsen Node Service Tool v{APP_VERSION} build={APP_BUILD}\r\n"
                f"# Bluetooth serial monitor node={label} started={now_local().isoformat(timespec='seconds')}\r\n"
                "# Meshtastic LOGRADIO protobuf stream; enabled only for this service session\r\n"
                "# ------------------------------------------------------------\r\n"
            ).encode("utf-8")
            handle.write(header)
            handle.flush()
            async with BleakClient(
                ble_device,
                timeout=45.0,
                pair=False,
                winrt={"use_cached_services": False},
            ) as client:
                control = client.services.get_characteristic(JARNSEN_DIAG_CONTROL_UUID)
                log_characteristic = client.services.get_characteristic(LOGRADIO_UUID)
                if control is None:
                    raise RuntimeError("Jarnsen-Service-Steuerung fehlt; aktuelle Firmware installieren.")
                if log_characteristic is None:
                    raise RuntimeError("Meshtastic LOGRADIO-Characteristic fehlt.")
                await client.start_notify(LOGRADIO_UUID, notification_handler)
                try:
                    await client.write_gatt_char(
                        JARNSEN_DIAG_CONTROL_UUID, b"BTLOGON", response=True
                    )
                    response = bytes(
                        await client.read_gatt_char(JARNSEN_DIAG_CONTROL_UUID)
                    ).decode("ascii", "replace").strip()
                    if response == "LOCKED":
                        raise RuntimeError(
                            "Servicefenster der Node ist nicht geöffnet. GPIO0/Service am Gerät öffnen und erneut starten."
                        )
                    if response != "BTLOG_READY":
                        raise RuntimeError(
                            "Firmware unterstützt den BT-Seriellog noch nicht "
                            f"({response or '--'})."
                        )
                    self.events.put(("serial_monitor_bt_started", (label, str(log_path))))
                    while not self.serial_monitor_stop.is_set():
                        try:
                            packet = await asyncio.wait_for(queue_in.get(), timeout=0.5)
                        except asyncio.TimeoutError:
                            continue
                        line = decode_meshtastic_log_record(packet)
                        if not line:
                            continue
                        encoded = (line + "\r\n").encode("utf-8", "replace")
                        handle.write(encoded)
                        handle.flush()
                        self.serial_monitor_bytes += len(encoded)
                        self.events.put(
                            ("serial_monitor_data", (line + "\n", self.serial_monitor_bytes))
                        )
                finally:
                    with contextlib.suppress(Exception):
                        await client.write_gatt_char(
                            JARNSEN_DIAG_CONTROL_UUID, b"BTLOGOFF", response=True
                        )
                    with contextlib.suppress(Exception):
                        await client.stop_notify(LOGRADIO_UUID)
'''
        source = insert_before_method(source, "stop_serial_monitor", bt_methods)

    # Raw command TX is a true serial-port feature; do not pretend LOGRADIO is a
    # bidirectional shell.
    start, end = method_span(source, "send_serial_monitor_command")
    old_send = source[start:end]
    if 'self.serial_monitor_transport == "Bluetooth"' not in old_send:
        guard = r'''    def send_serial_monitor_command(self) -> None:
        if self.serial_monitor_transport == "Bluetooth":
            messagebox.showinfo(
                "BT-Serieller Monitor",
                "Der Bluetooth-Monitor ist ein sicherer Live-Logstream, keine serielle Konsole. Senden bleibt deshalb USB/COM vorbehalten.",
            )
            return
'''
        body = old_send.split("\n", 1)[1]
        # Strip the original method indentation header and append its body under
        # the new guard without changing the USB behavior.
        source = source[:start] + guard.rstrip() + "\n" + body + source[end:]

    # Event for the Bluetooth monitor uses the same downstream text/filter/power
    # path as USB so all v1.5/v1.6 monitor features continue to work.
    event_anchor = '                elif kind == "serial_monitor_started":\n'
    if 'elif kind == "serial_monitor_bt_started":' not in source:
        bt_event = '''                elif kind == "serial_monitor_bt_started":
                    label, path = value
                    self.serial_monitor_transport = "Bluetooth"
                    self.serial_monitor_button.configure(text="Monitor stoppen")
                    self.serial_monitor_status.configure(
                        text=f"BT-Seriellog aktiv · {label} · Auto-Log: {path}"
                    )
                    self.status_level = "success"
                    self.status.configure(text=f"BT-Serieller Monitor aktiv · {label}")
                    self._update_status_badge()
'''
        if source.count(event_anchor) != 1:
            raise SystemExit("serial monitor event anchor not found")
        source = source.replace(event_anchor, bt_event + event_anchor, 1)

    # When a monitor stops, refresh the source-specific hint instead of always
    # implying a COM port.
    stopped_old = '''                elif kind == "serial_monitor_stopped":
                    self.serial_monitor_button.configure(text="Monitor starten")
                    self.serial_monitor_status.configure(
                        text=f"Gestoppt · Sitzungslog: {value}"
                    )
'''
    if stopped_old in source:
        stopped_new = '''                elif kind == "serial_monitor_stopped":
                    self.serial_monitor_button.configure(text="Monitor starten")
                    self.serial_monitor_status.configure(
                        text=f"Gestoppt · Sitzungslog: {value}"
                    )
                    self.after(1500, self.update_serial_monitor_source_ui)
'''
        source = source.replace(stopped_old, stopped_new, 1)

    # Extend the packaged self-test without opening Tk/BLE.
    selftest_anchor = '''        if APP_VERSION != "1.7.0":
            raise RuntimeError("App-Version ist nicht v1.7.0")
'''
    if '"start_bluetooth_serial_monitor"' not in source[source.find("def packaged_self_test"):]:
        addition = selftest_anchor + '''        sample_log = bytes.fromhex("0a 05 68 65 6c 6c 6f 15 00 00 00 00 1a 04 74 65 73 74 20 14")
        decoded_log = decode_meshtastic_log_record(sample_log)
        if "INFO" not in decoded_log or "[test] hello" not in decoded_log:
            raise RuntimeError("BT LogRecord Decoder ist fehlerhaft")
        for method_name in (
            "apply_scaled_dimensions",
            "update_serial_monitor_source_ui",
            "start_bluetooth_serial_monitor",
            "_bluetooth_serial_monitor_worker",
            "_bluetooth_serial_monitor_async",
        ):
            if not hasattr(ServiceTool, method_name):
                raise RuntimeError(f"v1.7-Funktion fehlt: {method_name}")
'''
        if source.count(selftest_anchor) != 1:
            raise SystemExit("v1.7 self-test anchor not found")
        source = source.replace(selftest_anchor, addition, 1)

    required = (
        'APP_VERSION = "1.7.0"',
        'LOGRADIO_UUID = "5a3d6e49-06e6-4423-9944-e9de8cdf9547"',
        "def decode_meshtastic_log_record(",
        'values=("USB / COM", "Bluetooth")',
        'values=("Automatisch", "75 %", "85 %", "100 %", "115 %", "130 %")',
        "def apply_scaled_dimensions(self)",
        "def start_bluetooth_serial_monitor(self)",
        'b"BTLOGON"',
        'b"BTLOGOFF"',
        'elif kind == "serial_monitor_bt_started":',
    )
    for marker in required:
        if marker not in source:
            raise SystemExit(f"missing v1.7 marker: {marker}")
    return source


def main() -> None:
    target = Path(sys.argv[1] if len(sys.argv) > 1 else "tools/JARNSEN_NODE_SERVICE_TOOL.py")
    source = target.read_text(encoding="utf-8")
    target.write_text(patch(source), encoding="utf-8")
    print("Service tool patched to v1.7.0: Bluetooth serial monitor + whole-window auto-fit zoom")


if __name__ == "__main__":
    main()
