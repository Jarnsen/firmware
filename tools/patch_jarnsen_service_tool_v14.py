"""v1.4 additions for the shared Jarnsen Node Service Tool.

Runs after the v1.3 patcher and adds adaptive/DPI-safe UI handling plus a
full serial monitor with continuous file logging.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

APP_VERSION = "1.4.0"


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
    # Version stamped by the v1.3 patcher first, then promoted here.
    source = re.sub(
        r'APP_VERSION = "[^"]+"',
        f'APP_VERSION = "{APP_VERSION}"',
        source,
        count=1,
    )

    # Windows DPI awareness and Save-As dialog.
    if "import ctypes\n" not in source:
        anchor = "import contextlib\nimport csv\n"
        if source.count(anchor) != 1:
            raise SystemExit("ctypes import anchor not found")
        source = source.replace(anchor, "import contextlib\nimport ctypes\nimport csv\n", 1)
    if "from tkinter import filedialog, messagebox, ttk" not in source:
        anchor = "from tkinter import messagebox, ttk"
        if source.count(anchor) != 1:
            raise SystemExit("tkinter import anchor not found")
        source = source.replace(anchor, "from tkinter import filedialog, messagebox, ttk", 1)

    if "def enable_windows_dpi_awareness(" not in source:
        class_anchor = "\n\nclass ServiceTool(tk.Tk):\n"
        if source.count(class_anchor) != 1:
            raise SystemExit("ServiceTool class anchor not found")
        dpi_helper = r'''


def enable_windows_dpi_awareness() -> None:
    """Use real monitor pixels on Windows and let Tk scale consistently."""
    if sys.platform != "win32":
        return
    try:
        # PER_MONITOR_AWARE_V2. Available on modern Windows 10/11.
        ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
        return
    except Exception:
        pass
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        pass
'''
        source = source.replace(class_anchor, dpi_helper + class_anchor, 1)

    # Adaptive initial size. The controls column will scroll, so a smaller
    # minimum height is safe even with 125/150 % Windows scaling.
    geometry_old = '''        self.geometry("1240x860")
        self.minsize(1000, 720)
'''
    geometry_new = '''        screen_w = max(800, self.winfo_screenwidth())
        screen_h = max(600, self.winfo_screenheight())
        target_w = min(1500, max(900, int(screen_w * 0.94)))
        target_h = min(980, max(620, int(screen_h * 0.90)))
        self.geometry(f"{target_w}x{target_h}")
        self.minsize(880, 560)
'''
    if geometry_old in source:
        source = source.replace(geometry_old, geometry_new, 1)
    elif "target_w = min(1500" not in source:
        raise SystemExit("window geometry anchor not found")

    # Serial-monitor runtime state.
    init_anchor = '''        self.live_image: tk.PhotoImage | None = None
        self.style = ttk.Style(self)
'''
    if "self.serial_monitor_stop" not in source:
        init_new = '''        self.live_image: tk.PhotoImage | None = None
        self.serial_monitor_stop = threading.Event()
        self.serial_monitor_thread: threading.Thread | None = None
        self.serial_monitor_ser: serial.Serial | None = None
        self.serial_monitor_log_path: pathlib.Path | None = None
        self.serial_monitor_bytes = 0
        self.style = ttk.Style(self)
'''
        if source.count(init_anchor) != 1:
            raise SystemExit("serial monitor state anchor not found")
        source = source.replace(init_anchor, init_new, 1)

    # The left column is the part that grew beyond 720/768 px displays.
    # Make it independently scrollable while keeping the workspace full size.
    controls_old = '''        controls = ttk.Frame(body, padding=(0, 0, 12, 0), width=365)
        body.add(controls, weight=0)
        workspace = ttk.Frame(body)
'''
    if "self.controls_canvas" not in source:
        controls_new = '''        controls_host = ttk.Frame(body, width=380)
        body.add(controls_host, weight=0)
        self.controls_canvas = tk.Canvas(
            controls_host, highlightthickness=0, width=365, borderwidth=0
        )
        self.controls_scrollbar = ttk.Scrollbar(
            controls_host, orient="vertical", command=self.controls_canvas.yview
        )
        self.controls_canvas.configure(yscrollcommand=self.controls_scrollbar.set)
        self.controls_scrollbar.pack(side="right", fill="y")
        self.controls_canvas.pack(side="left", fill="both", expand=True)
        controls = ttk.Frame(self.controls_canvas, padding=(0, 0, 8, 0))
        self.controls_window = self.controls_canvas.create_window(
            (0, 0), window=controls, anchor="nw"
        )
        controls.bind(
            "<Configure>",
            lambda _event: self.controls_canvas.configure(
                scrollregion=self.controls_canvas.bbox("all")
            ),
        )
        self.controls_canvas.bind(
            "<Configure>",
            lambda event: self.controls_canvas.itemconfigure(
                self.controls_window, width=max(330, event.width)
            ),
        )

        def controls_mousewheel(event: tk.Event) -> None:
            delta = int(getattr(event, "delta", 0) or 0)
            if delta:
                self.controls_canvas.yview_scroll(int(-delta / 120), "units")

        self.controls_canvas.bind(
            "<Enter>", lambda _event: self.bind_all("<MouseWheel>", controls_mousewheel)
        )
        self.controls_canvas.bind(
            "<Leave>", lambda _event: self.unbind_all("<MouseWheel>")
        )
        workspace = ttk.Frame(body)
'''
        if source.count(controls_old) != 1:
            raise SystemExit("scrollable controls anchor not found")
        source = source.replace(controls_old, controls_new, 1)

    # Add a dedicated serial monitor tab.
    tabs_old = '''        self.live_tab = ttk.Frame(self.notebook, padding=10)
        self.details_tab = ttk.Frame(self.notebook, padding=8)
        self.notebook.add(self.overview_tab, text="Übersicht")
        self.notebook.add(self.history_tab, text="Log-Historie")
        self.notebook.add(self.trends_tab, text="Trends")
        self.notebook.add(self.live_tab, text="Live-Anzeige")
        self.notebook.add(self.details_tab, text="Details / Rohdaten")
'''
    if "self.serial_tab" not in source:
        tabs_new = '''        self.live_tab = ttk.Frame(self.notebook, padding=10)
        self.serial_tab = ttk.Frame(self.notebook, padding=8)
        self.details_tab = ttk.Frame(self.notebook, padding=8)
        self.notebook.add(self.overview_tab, text="Übersicht")
        self.notebook.add(self.history_tab, text="Log-Historie")
        self.notebook.add(self.trends_tab, text="Trends")
        self.notebook.add(self.live_tab, text="Live-Anzeige")
        self.notebook.add(self.serial_tab, text="Serieller Monitor")
        self.notebook.add(self.details_tab, text="Details / Rohdaten")
'''
        if source.count(tabs_old) != 1:
            raise SystemExit("serial tab anchor not found")
        source = source.replace(tabs_old, tabs_new, 1)

    result_anchor = '''        self.result.insert("1.0", "Noch kein Log übertragen.")
        self.result.configure(state="disabled")

        history_actions = ttk.Frame(self.history_tab)
'''
    if "self.serial_monitor_text" not in source:
        serial_ui = '''        self.result.insert("1.0", "Noch kein Log übertragen.")
        self.result.configure(state="disabled")

        serial_toolbar = ttk.Frame(self.serial_tab)
        serial_toolbar.pack(fill="x", pady=(0, 7))
        ttk.Label(serial_toolbar, text="Port: Auswahl links · Baud").pack(side="left")
        self.serial_baud = ttk.Combobox(
            serial_toolbar,
            state="readonly",
            values=("9600", "19200", "38400", "57600", "115200", "230400", "460800", "921600"),
            width=9,
        )
        self.serial_baud.set("115200")
        self.serial_baud.pack(side="left", padx=(6, 10))
        self.serial_auto_scroll_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            serial_toolbar, text="Auto-Scroll", variable=self.serial_auto_scroll_var
        ).pack(side="left")
        self.serial_monitor_button = ttk.Button(
            serial_toolbar,
            text="Monitor starten",
            command=self.toggle_serial_monitor,
            style="Primary.TButton",
        )
        self.serial_monitor_button.pack(side="right")
        ttk.Button(
            serial_toolbar, text="Speichern unter …", command=self.save_serial_monitor
        ).pack(side="right", padx=(6, 6))
        ttk.Button(
            serial_toolbar, text="Anzeige löschen", command=self.clear_serial_monitor
        ).pack(side="right")

        serial_status_row = ttk.Frame(self.serial_tab)
        serial_status_row.pack(fill="x", pady=(0, 6))
        self.serial_monitor_status = ttk.Label(
            serial_status_row,
            text="Nicht verbunden · Sitzungslog wird beim Start automatisch gespeichert",
            style="Subtitle.TLabel",
        )
        self.serial_monitor_status.pack(side="left", fill="x", expand=True)

        serial_text_frame = ttk.Frame(self.serial_tab)
        serial_text_frame.pack(fill="both", expand=True)
        serial_y = ttk.Scrollbar(serial_text_frame, orient="vertical")
        serial_x = ttk.Scrollbar(serial_text_frame, orient="horizontal")
        self.serial_monitor_text = tk.Text(
            serial_text_frame,
            wrap="none",
            font=("Consolas", 9),
            yscrollcommand=serial_y.set,
            xscrollcommand=serial_x.set,
        )
        serial_y.configure(command=self.serial_monitor_text.yview)
        serial_x.configure(command=self.serial_monitor_text.xview)
        serial_y.pack(side="right", fill="y")
        serial_x.pack(side="bottom", fill="x")
        self.serial_monitor_text.pack(side="left", fill="both", expand=True)
        self.serial_monitor_text.insert(
            "end",
            "Serieller Monitor bereit. COM-Port links auswählen und Monitor starten.\\n",
        )

        serial_send = ttk.Frame(self.serial_tab)
        serial_send.pack(fill="x", pady=(7, 0))
        ttk.Label(serial_send, text="Senden").pack(side="left")
        self.serial_command = ttk.Entry(serial_send)
        self.serial_command.pack(side="left", fill="x", expand=True, padx=(6, 6))
        self.serial_command.bind("<Return>", lambda _event: self.send_serial_monitor_command())
        self.serial_send_newline_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            serial_send, text="CR/LF", variable=self.serial_send_newline_var
        ).pack(side="left", padx=(0, 6))
        ttk.Button(serial_send, text="Senden", command=self.send_serial_monitor_command).pack(side="right")

        history_actions = ttk.Frame(self.history_tab)
'''
        if source.count(result_anchor) != 1:
            raise SystemExit("serial monitor UI anchor not found")
        source = source.replace(result_anchor, serial_ui, 1)

    # Keep monitor colors readable across every theme.
    theme_anchor = '''        if hasattr(self, "ble_device"):
            self.ble_device.configure(
'''
    if "if hasattr(self, \"serial_monitor_text\")" not in source:
        theme_new = '''        if hasattr(self, "serial_monitor_text"):
            self.serial_monitor_text.configure(
                background=palette["panel_alt"],
                foreground=fg,
                insertbackground=fg,
                selectbackground=accent,
                font=(palette["mono"], 9),
            )
        if hasattr(self, "controls_canvas"):
            self.controls_canvas.configure(background=bg)
        if hasattr(self, "ble_device"):
            self.ble_device.configure(
'''
        if source.count(theme_anchor) != 1:
            raise SystemExit("serial monitor theme anchor not found")
        source = source.replace(theme_anchor, theme_new, 1)

    # Full serial-monitor implementation. The full byte stream is written to a
    # session file; the widget itself keeps only a rolling display window.
    if "    def toggle_serial_monitor(self)" not in source:
        monitor_methods = r'''    def serial_monitor_active(self) -> bool:
        return bool(self.serial_monitor_thread and self.serial_monitor_thread.is_alive())

    def toggle_serial_monitor(self) -> None:
        if self.serial_monitor_active():
            self.stop_serial_monitor()
        else:
            self.start_serial_monitor()

    def start_serial_monitor(self) -> None:
        port = self.selected_port()
        if not port:
            messagebox.showerror("Serieller Monitor", "Bitte links einen COM-Port auswählen.")
            return
        if self.worker and self.worker.is_alive():
            messagebox.showinfo(
                "Serieller Monitor",
                "Bitte den laufenden Download oder Firmwarevorgang zuerst beenden.",
            )
            return
        try:
            baud = int(self.serial_baud.get())
        except (TypeError, ValueError):
            baud = 115200
        self.serial_monitor_stop.clear()
        self.serial_monitor_bytes = 0
        safe_port = safe_filename(port.replace(":", "_"))
        self.serial_monitor_log_path = output_directory() / (
            f"Serial_Monitor_{safe_port}_{now_local():%Y-%m-%d_%H%M%S}.log"
        )
        self.serial_monitor_button.configure(text="Monitor stoppen")
        self.serial_monitor_status.configure(
            text=f"Verbinde {port} @ {baud} Baud …"
        )
        self.serial_monitor_thread = threading.Thread(
            target=self._serial_monitor_worker,
            args=(port, baud, self.serial_monitor_log_path),
            daemon=True,
        )
        self.serial_monitor_thread.start()

    def stop_serial_monitor(self) -> None:
        self.serial_monitor_stop.set()
        ser = self.serial_monitor_ser
        if ser is not None:
            with contextlib.suppress(Exception):
                ser.close()
        self.serial_monitor_button.configure(text="Monitor starten")
        self.serial_monitor_status.configure(text="Monitor wird beendet …")

    def _serial_monitor_worker(self, port: str, baud: int, log_path: pathlib.Path) -> None:
        ser: serial.Serial | None = None
        try:
            log_path.parent.mkdir(parents=True, exist_ok=True)
            with log_path.open("wb") as handle:
                header = (
                    f"# Jarnsen Node Service Tool v{APP_VERSION} build={APP_BUILD}\\r\\n"
                    f"# Serial monitor port={port} baud={baud} started={now_local().isoformat(timespec='seconds')}\\r\\n"
                    "# ------------------------------------------------------------\\r\\n"
                ).encode("utf-8")
                handle.write(header)
                handle.flush()
                ser = serial.Serial()
                ser.port = port
                ser.baudrate = baud
                ser.timeout = 0.10
                ser.write_timeout = 1.0
                ser.rtscts = False
                ser.dsrdtr = False
                ser.dtr = False
                ser.rts = False
                ser.open()
                self.serial_monitor_ser = ser
                self.events.put(("serial_monitor_started", (port, baud, str(log_path))))
                while not self.serial_monitor_stop.is_set():
                    try:
                        data = ser.read(4096)
                    except serial.SerialException:
                        if self.serial_monitor_stop.is_set():
                            break
                        raise
                    if not data:
                        continue
                    handle.write(data)
                    handle.flush()
                    self.serial_monitor_bytes += len(data)
                    self.events.put(
                        (
                            "serial_monitor_data",
                            (data.decode("utf-8", "replace"), self.serial_monitor_bytes),
                        )
                    )
        except Exception as exc:
            if not self.serial_monitor_stop.is_set():
                self.events.put(("serial_monitor_error", str(exc)))
        finally:
            if ser is not None:
                with contextlib.suppress(Exception):
                    ser.close()
            self.serial_monitor_ser = None
            self.serial_monitor_stop.set()
            self.events.put(("serial_monitor_stopped", str(log_path)))

    def clear_serial_monitor(self) -> None:
        self.serial_monitor_text.delete("1.0", "end")
        self.serial_monitor_text.insert(
            "end",
            "Anzeige gelöscht. Die vollständige Sitzungsdatei bleibt unverändert.\\n",
        )

    def save_serial_monitor(self) -> None:
        path = self.serial_monitor_log_path
        if path is None or not path.exists():
            messagebox.showinfo(
                "Serieller Monitor",
                "Noch keine Sitzungsdatei vorhanden. Monitor zuerst starten.",
            )
            return
        target = filedialog.asksaveasfilename(
            title="Serielles Log speichern unter",
            defaultextension=".log",
            filetypes=(("Logdateien", "*.log"), ("Textdateien", "*.txt"), ("Alle Dateien", "*.*")),
            initialfile=path.name,
        )
        if not target:
            return
        try:
            shutil.copy2(path, target)
            messagebox.showinfo("Serieller Monitor", f"Log gespeichert:\\n{target}")
        except OSError as exc:
            messagebox.showerror("Serieller Monitor", str(exc))

    def send_serial_monitor_command(self) -> None:
        ser = self.serial_monitor_ser
        if ser is None or not getattr(ser, "is_open", False):
            messagebox.showinfo("Serieller Monitor", "Monitor ist nicht verbunden.")
            return
        value = self.serial_command.get()
        if not value:
            return
        payload = value.encode("utf-8") + (b"\r\n" if self.serial_send_newline_var.get() else b"")
        try:
            ser.write(payload)
            ser.flush()
            self.serial_command.delete(0, "end")
            self.events.put(("serial_monitor_tx", value))
        except serial.SerialException as exc:
            messagebox.showerror("Serieller Monitor", str(exc))
'''
        source = insert_before_method(source, "start_download", monitor_methods)

    # USB log download and flashing must not fight the monitor for the same port.
    download_anchor = '''        if self.worker and self.worker.is_alive():
            return
        self.stop_event.clear()
        self.expected_device = self.device.get()
'''
    if "Seriellen Monitor zuerst stoppen" not in source:
        download_new = '''        if self.worker and self.worker.is_alive():
            return
        if self.serial_monitor_active():
            messagebox.showinfo("USB-Port belegt", "Seriellen Monitor zuerst stoppen.")
            return
        self.stop_event.clear()
        self.expected_device = self.device.get()
'''
        if source.count(download_anchor) < 1:
            raise SystemExit("USB download monitor-lock anchor not found")
        source = source.replace(download_anchor, download_new, 1)

    # The serial updater is injected by v1.3; guard it too.
    serial_update_anchor = '''        if self.worker and self.worker.is_alive():
            return
        device_code = self._selected_serial_hardware()
'''
    if "Firmwareupload kann den vom Monitor geöffneten COM-Port" not in source:
        serial_update_new = '''        if self.worker and self.worker.is_alive():
            return
        if self.serial_monitor_active():
            messagebox.showinfo(
                "USB-Port belegt",
                "Firmwareupload kann den vom Monitor geöffneten COM-Port nicht verwenden. Monitor zuerst stoppen.",
            )
            return
        device_code = self._selected_serial_hardware()
'''
        if source.count(serial_update_anchor) != 1:
            raise SystemExit("serial updater monitor-lock anchor not found")
        source = source.replace(serial_update_anchor, serial_update_new, 1)

    # Event-pump handling for monitor data. Keep at most ~12k visible lines;
    # the session file on disk remains complete.
    event_anchor = '                elif kind == "serial_update_result":\n'
    if 'elif kind == "serial_monitor_data":' not in source:
        monitor_events = '''                elif kind == "serial_monitor_started":
                    port, baud, path = value
                    self.serial_monitor_button.configure(text="Monitor stoppen")
                    self.serial_monitor_status.configure(
                        text=f"Verbunden: {port} @ {baud} Baud · Auto-Log: {path}"
                    )
                    self.status_level = "success"
                    self.status.configure(text=f"Serieller Monitor aktiv · {port}")
                    self._update_status_badge()
                elif kind == "serial_monitor_data":
                    text_value, byte_count = value
                    self.serial_monitor_text.insert("end", str(text_value))
                    try:
                        lines = int(self.serial_monitor_text.index("end-1c").split(".")[0])
                        if lines > 12000:
                            self.serial_monitor_text.delete("1.0", "2000.0")
                    except (ValueError, tk.TclError):
                        pass
                    if self.serial_auto_scroll_var.get():
                        self.serial_monitor_text.see("end")
                    size_kb = int(byte_count) / 1024.0
                    name = self.serial_monitor_log_path.name if self.serial_monitor_log_path else "--"
                    self.serial_monitor_status.configure(
                        text=f"Aufzeichnung {size_kb:.1f} KiB · {name}"
                    )
                elif kind == "serial_monitor_tx":
                    self.serial_monitor_text.insert("end", f"\\n[TX] {value}\\n")
                    if self.serial_auto_scroll_var.get():
                        self.serial_monitor_text.see("end")
                elif kind == "serial_monitor_error":
                    self.status_level = "error"
                    self.status.configure(text="Serieller Monitor getrennt")
                    self._update_status_badge()
                    self.serial_monitor_text.insert("end", f"\\n[MONITOR-FEHLER] {value}\\n")
                    self.serial_monitor_text.see("end")
                    messagebox.showwarning("Serieller Monitor", str(value))
                elif kind == "serial_monitor_stopped":
                    self.serial_monitor_button.configure(text="Monitor starten")
                    self.serial_monitor_status.configure(
                        text=f"Gestoppt · Sitzungslog: {value}"
                    )
'''
        if source.count(event_anchor) != 1:
            raise SystemExit("serial monitor event anchor not found")
        source = source.replace(event_anchor, monitor_events + event_anchor, 1)

    # Stop the monitor for app restart/close as well.
    restart_anchor = '''        self.stop_event.set()
        self.live_stop.set()
        self.update_idletasks()
'''
    if "self.serial_monitor_stop.set()\n        if self.serial_monitor_ser" not in source:
        restart_new = '''        self.stop_event.set()
        self.live_stop.set()
        self.serial_monitor_stop.set()
        if self.serial_monitor_ser is not None:
            with contextlib.suppress(Exception):
                self.serial_monitor_ser.close()
        self.update_idletasks()
'''
        if source.count(restart_anchor) != 1:
            raise SystemExit("restart monitor shutdown anchor not found")
        source = source.replace(restart_anchor, restart_new, 1)

    close_anchor = '''    def close_app(self) -> None:
        self.stop_event.set()
        self.live_stop.set()
        self.destroy()
'''
    if "self.serial_monitor_stop.set()" not in source[source.find("    def close_app(self)"):method_span(source, "close_app")[1]]:
        close_new = '''    def close_app(self) -> None:
        self.stop_event.set()
        self.live_stop.set()
        self.serial_monitor_stop.set()
        if self.serial_monitor_ser is not None:
            with contextlib.suppress(Exception):
                self.serial_monitor_ser.close()
        self.destroy()
'''
        if source.count(close_anchor) != 1:
            raise SystemExit("close_app anchor not found")
        source = source.replace(close_anchor, close_new, 1)

    # Call DPI awareness before Tk is created.
    main_old = '''    if "--self-test" in sys.argv:
        raise SystemExit(packaged_self_test())
    ServiceTool().mainloop()
'''
    if "enable_windows_dpi_awareness()\n    ServiceTool().mainloop()" not in source:
        main_new = '''    if "--self-test" in sys.argv:
        raise SystemExit(packaged_self_test())
    enable_windows_dpi_awareness()
    ServiceTool().mainloop()
'''
        if source.count(main_old) != 1:
            raise SystemExit("main DPI anchor not found")
        source = source.replace(main_old, main_new, 1)

    # Extend packaged self-test without creating a Tk window.
    selftest_anchor = '''        if set(HARDWARE_PROFILES) != {"TRACKER", "V3"}:
            raise RuntimeError("Hardwareprofile sind unvollständig")
'''
    if 'APP_VERSION != "1.4.0"' not in source:
        selftest_new = selftest_anchor + '''        if APP_VERSION != "1.4.0":
            raise RuntimeError("App-Version ist nicht v1.4.0")
        for method_name in (
            "toggle_serial_monitor",
            "start_serial_monitor",
            "stop_serial_monitor",
            "save_serial_monitor",
            "send_serial_monitor_command",
        ):
            if not hasattr(ServiceTool, method_name):
                raise RuntimeError(f"Serieller Monitor fehlt: {method_name}")
'''
        if source.count(selftest_anchor) != 1:
            raise SystemExit("v1.4 self-test anchor not found")
        source = source.replace(selftest_anchor, selftest_new, 1)

    required = (
        'APP_VERSION = "1.4.0"',
        "def enable_windows_dpi_awareness(",
        "self.controls_canvas",
        'text="Serieller Monitor"',
        "def toggle_serial_monitor(self)",
        "def _serial_monitor_worker(",
        "def save_serial_monitor(self)",
        "def send_serial_monitor_command(self)",
        'elif kind == "serial_monitor_data":',
        "enable_windows_dpi_awareness()",
    )
    for marker in required:
        if marker not in source:
            raise SystemExit(f"missing v1.4 marker: {marker}")
    return source


def main() -> None:
    target = Path(sys.argv[1] if len(sys.argv) > 1 else "tools/JARNSEN_NODE_SERVICE_TOOL.py")
    source = target.read_text(encoding="utf-8")
    target.write_text(patch(source), encoding="utf-8")
    print("Service tool patched to v1.4.0: adaptive scaling + serial monitor")


if __name__ == "__main__":
    main()
