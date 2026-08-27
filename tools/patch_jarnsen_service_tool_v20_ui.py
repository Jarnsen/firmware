"""v2.0 workflow UI: persistent node selector and task-oriented service pages."""
from __future__ import annotations

import sys
from pathlib import Path


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
    if "self._install_workflow_ui()" not in source:
        start, end = method_span(source, "_build_ui")
        build = source[start:end]
        install_anchor = "        self.render_track_map()\n"
        if build.count(install_anchor) != 1:
            raise SystemExit("workflow install anchor not found in _build_ui")
        build = build.replace(
            install_anchor,
            "        self._install_workflow_ui()\n" + install_anchor,
            1,
        )
        source = source[:start] + build + source[end:]

    methods = r'''    def _install_workflow_ui(self) -> None:
        workspace = self.notebook.master
        self.controls_host = self.controls_nav.master if hasattr(self, "controls_nav") else None
        self.body_pane = self.controls_host.master if self.controls_host is not None else None
        self.advanced_visible = True
        self.pending_smart_action = ""
        self.node_selector_map: dict[str, str] = {}

        header = ttk.Frame(workspace, padding=(0, 0, 0, 8))
        header.pack(fill="x", before=self.notebook)
        ttk.Label(header, text="Node", style="Subtitle.TLabel").pack(side="left")
        self.node_selector = ttk.Combobox(header, state="readonly", width=36)
        self.node_selector.pack(side="left", padx=(6, 10))
        self.node_selector.bind("<<ComboboxSelected>>", self.select_node_from_selector)
        self.workflow_device = ttk.Label(header, text="Kein Node", style="Section.TLabel")
        self.workflow_device.pack(side="left", padx=(0, 10))
        self.workflow_connection = ttk.Label(header, text="Bereit", style="Subtitle.TLabel")
        self.workflow_connection.pack(side="left", fill="x", expand=True)
        self.advanced_button = ttk.Button(header, text="Erweitert", command=self.toggle_advanced_controls)
        self.advanced_button.pack(side="right")

        self.service_tab = ttk.Frame(self.notebook, padding=12)
        self.firmware_tab = ttk.Frame(self.notebook, padding=12)
        self.notebook.add(self.service_tab, text="Service")
        self.notebook.add(self.firmware_tab, text="Firmware")
        order = (
            self.overview_tab,
            self.service_tab,
            self.track_tab,
            self.firmware_tab,
            self.history_tab,
            self.trends_tab,
            self.live_tab,
            self.details_tab,
        )
        for index, tab in enumerate(order):
            self.notebook.insert(index, tab)
        self.notebook.tab(self.overview_tab, text="Übersicht")
        self.notebook.tab(self.track_tab, text="Position")
        self.notebook.tab(self.history_tab, text="Historie")
        self.notebook.tab(self.live_tab, text="Live")
        self.notebook.tab(self.details_tab, text="Rohdaten")

        ttk.Label(self.service_tab, text="Schnellaktionen", style="Section.TLabel").pack(anchor="w")
        self.service_context = ttk.Label(
            self.service_tab,
            text="Node auswählen",
            style="Subtitle.TLabel",
            justify="left",
        )
        self.service_context.pack(anchor="w", pady=(3, 12))
        grid = ttk.Frame(self.service_tab)
        grid.pack(fill="x")
        actions = (
            ("Log herunterladen", self.smart_log_download, "Primary.TButton"),
            ("Live ansehen", self.smart_live_view, "Primary.TButton"),
            ("Nodes suchen", self.scan_ble, "TButton"),
            ("Firmware aktualisieren", self.smart_firmware_update, "Primary.TButton"),
            ("Service-WLAN öffnen", self.open_service_wlan, "TButton"),
            ("Erweiterte Verbindung", self.toggle_advanced_controls, "TButton"),
        )
        for index, (label, command, style) in enumerate(actions):
            row, column = divmod(index, 2)
            ttk.Button(grid, text=label, command=command, style=style).grid(
                row=row,
                column=column,
                sticky="ew",
                padx=(0 if column == 0 else 5, 5 if column == 0 else 0),
                pady=5,
            )
        grid.columnconfigure(0, weight=1)
        grid.columnconfigure(1, weight=1)
        ttk.Separator(self.service_tab).pack(fill="x", pady=14)
        ttk.Label(
            self.service_tab,
            text=(
                "Normal: Node wählen → Log herunterladen → Übersicht und Position werden automatisch aktualisiert. "
                "COM-Port, Windows-Kopplung, Recovery und Debug bleiben unter Erweitert verfügbar."
            ),
            wraplength=850,
            justify="left",
        ).pack(anchor="w")

        ttk.Label(self.firmware_tab, text="Firmware", style="Section.TLabel").pack(anchor="w")
        self.workflow_firmware = ttk.Label(
            self.firmware_tab,
            text="Node auswählen",
            style="Subtitle.TLabel",
            justify="left",
            wraplength=850,
        )
        self.workflow_firmware.pack(anchor="w", pady=(4, 14))
        fw = ttk.Frame(self.firmware_tab)
        fw.pack(fill="x")
        ttk.Button(fw, text="GitHub-Stand prüfen", command=self.refresh_firmware_status).pack(
            side="left", fill="x", expand=True
        )
        ttk.Button(
            fw,
            text="Update installieren",
            command=self.smart_firmware_update,
            style="Primary.TButton",
        ).pack(side="left", fill="x", expand=True, padx=6)
        ttk.Button(fw, text="USB / Recovery", command=self.open_usb_recovery).pack(
            side="left", fill="x", expand=True
        )

        self.position_status_label = ttk.Label(
            self.track_tab,
            text="Positionsstatus wird aus dem letzten Log gelesen",
            style="Subtitle.TLabel",
            justify="left",
        )
        self.position_status_label.pack(fill="x", pady=(0, 6), before=self.track_canvas)
        self.refresh_node_selector()
        self.refresh_workflow_header()
        if self.body_pane is not None and self.controls_host is not None:
            with contextlib.suppress(tk.TclError):
                self.body_pane.forget(self.controls_host)
                self.advanced_visible = False

    def refresh_node_selector(self) -> None:
        if not hasattr(self, "node_selector") or not hasattr(self, "node_tree"):
            return
        mapping: dict[str, str] = {}
        selected = ""
        for item in self.node_tree.get_children():
            values = self.node_tree.item(item, "values")
            label = f"{values[0] if values else item} · {values[1] if len(values) > 1 else ''} · {item}"
            mapping[label] = str(item)
            if str(item) == self.selected_node_id:
                selected = label
        self.node_selector_map = mapping
        self.node_selector.configure(values=tuple(mapping))
        self.node_selector.set(selected or (next(iter(mapping)) if mapping else ""))

    def select_node_from_selector(self, _event: object | None = None) -> None:
        node_id = self.node_selector_map.get(self.node_selector.get(), "")
        if node_id and self.node_tree.exists(node_id):
            self.node_tree.selection_set(node_id)
            self.node_tree.focus(node_id)
            self.node_tree.see(node_id)
            self.on_node_selected()

    def toggle_advanced_controls(self) -> None:
        if self.body_pane is None or self.controls_host is None:
            return
        try:
            if self.advanced_visible:
                self.body_pane.forget(self.controls_host)
                self.advanced_visible = False
                self.advanced_button.configure(text="Erweitert")
            else:
                self.body_pane.insert(0, self.controls_host, weight=0)
                self.advanced_visible = True
                self.advanced_button.configure(text="Erweitert ausblenden")
        except tk.TclError:
            pass

    def _preferred_ble_name(self) -> str:
        if self.node_logs and isinstance(self.node_logs[-1].get("metrics"), dict):
            return str(self.node_logs[-1]["metrics"].get("long_name") or "")
        return ""

    def _select_preferred_ble_device(self) -> bool:
        labels = list(self.ble_map)
        if not labels:
            return False
        preferred = self._preferred_ble_name()
        matched = [i for i, label in enumerate(labels) if preferred and preferred.lower() in label.lower()]
        if len(matched) == 1:
            index = matched[0]
        elif len(labels) == 1:
            index = 0
        else:
            selected = list(self.ble_device.curselection())
            if len(selected) == 1 and 0 <= selected[0] < len(labels):
                selected_label = labels[selected[0]]
                if preferred and preferred.lower() in selected_label.lower():
                    return True
            return False
        self.ble_device.selection_clear(0, "end")
        self.ble_device.selection_set(index)
        self.ble_device.see(index)
        return True

    def _queue_smart_ble_action(self, action: str) -> None:
        if self.worker and self.worker.is_alive():
            self.status_level = "warning"
            self.status.configure(text="Ein anderer Vorgang läuft bereits")
            self._update_status_badge()
            return
        if self._select_preferred_ble_device():
            self.pending_smart_action = action
            self._continue_smart_action()
            return
        if BLE_AVAILABLE:
            self.pending_smart_action = action
            self.status.configure(text="Bluetooth-Nodes werden automatisch gesucht …")
            self.scan_ble()
            return
        self.pending_smart_action = action
        self._continue_smart_action()

    def _continue_smart_action(self) -> None:
        action = self.pending_smart_action
        if not action or (self.worker and self.worker.is_alive()):
            return
        if self._select_preferred_ble_device():
            self.pending_smart_action = ""
            if action == "download":
                self.start_ble_download()
            elif action == "live":
                self.notebook.select(self.live_tab)
                self.toggle_live()
            elif action == "update":
                self.notebook.select(self.firmware_tab)
                self.start_ble_update()
            return
        if self.ble_map:
            self.pending_smart_action = ""
            if not self.advanced_visible:
                self.toggle_advanced_controls()
            self.show_controls_page("Bluetooth")
            self.notebook.select(self.service_tab)
            self.status_level = "warning"
            self.status.configure(text="Mehrere Nodes gefunden – bitte den gewünschten Bluetooth-Node markieren")
            self._update_status_badge()
            return
        if BLE_AVAILABLE and getattr(self, "ble_scan_button", None) is not None and str(self.ble_scan_button.cget("state")) == "disabled":
            return
        self.pending_smart_action = ""
        if action == "download" and self.port.get() and self.port.get() in self.port_map:
            self.start_download()
            return
        if action == "live":
            if not self.advanced_visible:
                self.toggle_advanced_controls()
            self.show_controls_page("Bluetooth")
            self.status_level = "warning"
            self.status.configure(text="Keine passende BLE-Node gefunden – Service am Gerät öffnen und erneut suchen")
            self._update_status_badge()
            return
        self.open_usb_recovery()
        if action == "update":
            self.status_level = "warning"
            self.status.configure(text="Keine passende BLE-Node gefunden – USB / Recovery für Firmwareupdate geöffnet")
            self._update_status_badge()

    def smart_log_download(self) -> None:
        self._queue_smart_ble_action("download")

    def smart_live_view(self) -> None:
        self._queue_smart_ble_action("live")

    def smart_firmware_update(self) -> None:
        self._queue_smart_ble_action("update")

    def open_usb_recovery(self) -> None:
        if not self.advanced_visible:
            self.toggle_advanced_controls()
        self.show_controls_page("USB")
        self.status.configure(text="USB / Recovery geöffnet")

    def open_service_wlan(self) -> None:
        messagebox.showinfo(
            "Service-WLAN",
            "Am Node im Service-Menü WLAN Service starten.\n\nWLAN-Passwort: 24011980\n\n"
            "Nach dem Verbinden öffnet sich die Service-Webseite unter 192.168.4.1.",
        )
        if sys.platform == "win32":
            with contextlib.suppress(OSError):
                os.startfile("http://192.168.4.1")  # type: ignore[attr-defined]

    def refresh_workflow_header(self) -> None:
        if not hasattr(self, "workflow_device"):
            return
        self.refresh_node_selector()
        if not self.node_logs:
            self.workflow_device.configure(text="Kein Node")
            self.workflow_connection.configure(text="Node auswählen oder Log herunterladen")
            self.service_context.configure(text="Noch kein Node ausgewählt")
            self.workflow_firmware.configure(text="Noch kein Node ausgewählt")
            self.position_status_label.configure(text="Keine Positionsdaten")
            return
        metrics = self.node_logs[-1].get("metrics", {})
        if not isinstance(metrics, dict):
            return
        name = str(metrics.get("long_name") or self.selected_node_id or "Node")
        device_key = str(metrics.get("device") or "")
        device = DEVICE_NAMES.get(device_key, device_key or "--")
        battery = f"{float(metrics['battery_pct']):.0f} %" if metrics.get("battery_pct") is not None else "--"
        build = str(metrics.get("build") or "")
        state, detail, _level = self.firmware_state(device_key, build)
        connection = "LIVE verbunden" if self.live_connected else (f"{len(self.ble_map)} BLE-Node(s) gefunden" if self.ble_map else "Bereit")
        self.workflow_device.configure(text=f"{name} · {device} · Akku {battery}")
        self.workflow_connection.configure(text=f"{connection} · Firmware {state}")
        self.service_context.configure(text=f"{name} ({self.selected_node_id})\n{device} · Akku {battery} · {connection}")
        self.workflow_firmware.configure(text=f"Installiert: {metrics.get('firmware') or '--'} · Build {build or '--'}\n{detail}")
        pos_state = str(metrics.get("position_state") or "")
        if pos_state:
            label = {"moving": "Bewegung", "stabilizing": "Stabilisierung", "stationary": "Stationär"}.get(pos_state, pos_state)
            self.position_status_label.configure(
                text=(
                    f"Zustand: {label} · GPS {metrics.get('reported_accuracy') if metrics.get('reported_accuracy') is not None else '--'} m / "
                    f"geschätzt {metrics.get('estimated_accuracy') if metrics.get('estimated_accuracy') is not None else '--'} m · "
                    f"Abstand Fix {metrics.get('fixed_difference') if metrics.get('fixed_difference') is not None else '--'} m · "
                    f"Live-TX {int(metrics.get('live_positions') or 0)}"
                )
            )
        else:
            self.position_status_label.configure(
                text=f"Trackpunkte: {len(self.track_points)} · letzter Log {self.node_logs[-1].get('captured_at', '--')}"
            )'''
    if "    def _install_workflow_ui(self)" not in source:
        source = insert_before_method(source, "_resize_dashboard", methods)

    for method_name, marker, addition in (
        ("refresh_nodes", "            self.on_node_selected()\n", "        self.refresh_node_selector()\n"),
        ("on_node_selected", "        self.update_track_points()\n", "        self.refresh_workflow_header()\n"),
    ):
        start, end = method_span(source, method_name)
        body = source[start:end]
        if addition.strip() not in body:
            if marker not in body:
                raise SystemExit(f"{method_name} sync anchor missing")
            body = body.replace(marker, marker + addition, 1)
            source = source[:start] + body + source[end:]

    start, end = method_span(source, "_pump_events")
    body = source[start:end]
    if "self._continue_smart_action()" not in body:
        marker = "        self.after(100, self._pump_events)\n"
        if marker not in body:
            raise SystemExit("event pump tail missing")
        body = body.replace(
            marker,
            "        self._continue_smart_action()\n        self.refresh_workflow_header()\n" + marker,
            1,
        )
        source = source[:start] + body + source[end:]

    report = "Übersichtsparser V3/Tracker geprüft\\n"
    if "Workflow-UI geprüft" not in source:
        source = source.replace(
            report,
            "Übersichtsparser V3/Tracker, Workflow-UI geprüft\\n",
            1,
        )
        anchor = '        report.write_text(\n            "OK: BLE, Papierkorb, Datenbank, Positionskarte, fünf Layouts; Übersichtsparser V3/Tracker, Workflow-UI geprüft\\n",\n'
        tests = '''        for method_name in ("_install_workflow_ui", "smart_log_download", "smart_live_view", "smart_firmware_update", "toggle_advanced_controls"):\n            if not hasattr(ServiceTool, method_name):\n                raise RuntimeError(f"v2.0 Workflow-Funktion fehlt: {method_name}")\n'''
        if anchor not in source:
            raise SystemExit("workflow self-test anchor missing")
        source = source.replace(anchor, tests + anchor, 1)

    required = (
        "def smart_log_download(self)",
        "Service-WLAN öffnen",
        "self.node_selector",
        "Workflow-UI geprüft",
    )
    for marker in required:
        if marker not in source:
            raise SystemExit(f"missing v2.0 UI marker: {marker}")
    return source


def main() -> None:
    target = Path(sys.argv[1] if len(sys.argv) > 1 else "tools/JARNSEN_NODE_SERVICE_TOOL.py")
    target.write_text(patch(target.read_text(encoding="utf-8")), encoding="utf-8")
    print("Service tool v2.0 UI: persistent node selector + task-oriented workflow")


if __name__ == "__main__":
    main()
