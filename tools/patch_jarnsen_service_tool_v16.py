"""v1.6 additions for the shared Jarnsen Node Service Tool.

Adds human-readable runtimes, serial log filenames with the node long name,
copy-complete-log clipboard support and remote node diagnostic-log clearing.
Runs after the v1.5 patcher.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

APP_VERSION = "1.6.0"


def method_span(text: str, name: str) -> tuple[int, int]:
    start = text.find(f"    def {name}(")
    if start < 0:
        raise SystemExit(f"method {name} not found")
    next_method = text.find("\n    def ", start + 1)
    return start, next_method if next_method >= 0 else len(text)


def function_span(text: str, name: str) -> tuple[int, int]:
    start = text.find(f"def {name}(")
    if start < 0:
        raise SystemExit(f"function {name} not found")
    next_def = text.find("\ndef ", start + 1)
    next_class = text.find("\nclass ", start + 1)
    candidates = [value for value in (next_def, next_class) if value >= 0]
    return start, min(candidates) if candidates else len(text)


def insert_before_method(text: str, name: str, code: str) -> str:
    start, _ = method_span(text, name)
    return text[:start] + code.rstrip() + "\n\n" + text[start:]


def patch(source: str) -> str:
    source = re.sub(r'APP_VERSION = "[^"]+"', f'APP_VERSION = "{APP_VERSION}"', source, count=1)
    source = source.replace('APP_VERSION != "1.5.0"', 'APP_VERSION != "1.6.0"')
    source = source.replace('App-Version ist nicht v1.5.0', 'App-Version ist nicht v1.6.0')

    if "def format_duration_seconds(" not in source:
        insert_at = source.find("\ndef snapshot_metrics(")
        if insert_at < 0:
            raise SystemExit("snapshot_metrics anchor not found")
        helper = r'''


def format_duration_seconds(value: object, compact: bool = False) -> str:
    """Format a seconds counter as days/hours/minutes instead of a raw integer."""
    if isinstance(value, str):
        raw = value.strip()
        match = re.fullmatch(r"(-?\d+(?:\.\d+)?)s", raw, re.IGNORECASE)
        if not match:
            return raw or "--"
        seconds = int(round(float(match.group(1))))
    elif isinstance(value, (int, float)):
        seconds = int(round(float(value)))
    else:
        return "--"

    sign = "-" if seconds < 0 else ""
    seconds = abs(seconds)
    days, remainder = divmod(seconds, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes, secs = divmod(remainder, 60)

    if days:
        parts = [f"{days} d", f"{hours} h"]
        if not compact:
            parts.append(f"{minutes} min")
    elif hours:
        parts = [f"{hours} h", f"{minutes} min"]
        if not compact and secs:
            parts.append(f"{secs} s")
    elif minutes:
        parts = [f"{minutes} min"]
        if not compact or minutes < 10:
            parts.append(f"{secs} s")
    else:
        parts = [f"{secs} s"]
    return sign + " ".join(parts)
'''
        source = source[:insert_at] + helper + source[insert_at:]

    start, end = function_span(source, "diagnostic_snapshot")
    block = source[start:end]
    replacements = {
        '''f"Funk hören / Service  {token('listen')} / {token('service')}"''':
            '''f"Funk hören / Service  {format_duration_seconds(token('listen'))} / {format_duration_seconds(token('service'))}"''',
        '''f"BLE / Display  {token('ble')} / {token('disp')}"''':
            '''f"BLE / Display  {format_duration_seconds(token('ble'))} / {format_duration_seconds(token('disp'))}"''',
        '''f"Messzeit  {first_token('on', 'measured')}"''':
            '''f"Messzeit  {format_duration_seconds(first_token('on', 'measured'))}"''',
        '''f"Bewegt / Park  {token('move')} / {token('park')}"''':
            '''f"Bewegt / Park  {format_duration_seconds(token('move'))} / {format_duration_seconds(token('park'))}"''',
        '''f"GPS / BLE  {token('gps')} / {token('ble')}"''':
            '''f"GPS / BLE  {format_duration_seconds(token('gps'))} / {format_duration_seconds(token('ble'))}"''',
        '''f"Display / TX  {token('disp')} / {token('tx')}"''':
            '''f"Display / TX  {format_duration_seconds(token('disp'))} / {token('tx')}"''',
        '''f"Light / Deep  {token('lightSleep')} / {token('deepSleep')}"''':
            '''f"Light / Deep  {format_duration_seconds(token('lightSleep'))} / {format_duration_seconds(token('deepSleep'))}"''',
    }
    for old, new in replacements.items():
        if old in block:
            block = block.replace(old, new, 1)
    source = source[:start] + block + source[end:]

    start, end = method_span(source, "render_trend")
    block = source[start:end]
    old_axis = '''                text=f"{value:.0f}",'''
    if old_axis in block and "format_duration_seconds(value, compact=True)" not in block:
        block = block.replace(
            old_axis,
            '''                text=(format_duration_seconds(value, compact=True) if unit == "s" else f"{value:.0f}"),''',
            1,
        )
    old_summary = '''        self.trend_summary.configure(
            text=f"{len(points)} Messpunkte · zuletzt {values[-1]:.0f} {unit} · {change_label} {delta:+.0f} {unit}"
        )
'''
    if old_summary in block:
        new_summary = '''        if unit == "s":
            last_value_text = format_duration_seconds(values[-1], compact=True)
            delta_value_text = format_duration_seconds(delta, compact=True)
            if delta > 0:
                delta_value_text = "+" + delta_value_text
        else:
            last_value_text = f"{values[-1]:.0f} {unit}".strip()
            delta_value_text = f"{delta:+.0f} {unit}".strip()
        self.trend_summary.configure(
            text=f"{len(points)} Messpunkte · zuletzt {last_value_text} · {change_label} {delta_value_text}"
        )
'''
        block = block.replace(old_summary, new_summary, 1)
    source = source[:start] + block + source[end:]

    if "    def _serial_monitor_long_name(self)" not in source:
        method = r'''    def _serial_monitor_long_name(self) -> str:
        if self.selected_node_id:
            latest = self.repository.latest_log(self.selected_node_id)
            if latest:
                metrics = latest.get("metrics") if isinstance(latest, dict) else None
                if isinstance(metrics, dict):
                    name = str(metrics.get("long_name") or "").strip()
                    if name:
                        return name
        if self.last_payload:
            name = header_value(self.last_payload, b"long_name").strip()
            if name:
                return name
        return self.selected_node_id or "Node"
'''
        source = insert_before_method(source, "start_serial_monitor", method)

    start, end = method_span(source, "start_serial_monitor")
    block = source[start:end]
    old_name = '''        safe_port = safe_filename(port.replace(":", "_"))
        self.serial_monitor_log_path = output_directory() / (
            f"Serial_Monitor_{safe_port}_{now_local():%Y-%m-%d_%H%M%S}.log"
        )
'''
    if old_name in block:
        new_name = '''        safe_port = safe_filename(port.replace(":", "_"))
        node_long_name = self._serial_monitor_long_name()
        safe_node = safe_filename(node_long_name)
        self.serial_monitor_log_path = output_directory() / (
            f"Serial_Monitor_{safe_node}_{safe_port}_{now_local():%Y-%m-%d_%H%M%S}.log"
        )
'''
        block = block.replace(old_name, new_name, 1)
    source = source[:start] + block + source[end:]

    serial_save_anchor = '''        ttk.Button(
            serial_toolbar, text="Speichern unter …", command=self.save_serial_monitor
        ).pack(side="right", padx=(6, 6))
'''
    if 'text="Kompletten Log kopieren"' not in source:
        serial_save_new = '''        ttk.Button(
            serial_toolbar, text="Speichern unter …", command=self.save_serial_monitor
        ).pack(side="right", padx=(6, 6))
        ttk.Button(
            serial_toolbar, text="Kompletten Log kopieren", command=self.copy_complete_serial_log
        ).pack(side="right", padx=(6, 0))
'''
        if source.count(serial_save_anchor) != 1:
            raise SystemExit("serial copy button anchor not found")
        source = source.replace(serial_save_anchor, serial_save_new, 1)

    if "    def copy_complete_serial_log(self)" not in source:
        method = r'''    def copy_complete_serial_log(self) -> None:
        path = self.serial_monitor_log_path
        if path is None or not path.exists():
            messagebox.showinfo(
                "Serieller Monitor",
                "Noch keine vollständige Sitzungsdatei vorhanden. Monitor zuerst starten.",
            )
            return
        try:
            content = path.read_text(encoding="utf-8", errors="replace")
            self.clipboard_clear()
            self.clipboard_append(content)
            self.update()
            self.serial_monitor_status.configure(
                text=f"Kompletter Log kopiert · {len(content):,} Zeichen · {path.name}".replace(",", ".")
            )
        except (OSError, tk.TclError) as exc:
            messagebox.showerror("Serieller Monitor", f"Log konnte nicht kopiert werden:\n{exc}")
'''
        source = insert_before_method(source, "save_serial_monitor", method)

    snapshot_button = '''        ttk.Button(
            service, text="Konfig-Snapshot sichern", command=self.save_config_snapshot
        ).pack(fill="x", pady=(6, 0))
'''
    if 'text="Node-Log löschen"' not in source:
        new_buttons = snapshot_button + '''        ttk.Button(
            service, text="Node-Log löschen", command=self.clear_node_log
        ).pack(fill="x", pady=(6, 0))
'''
        if source.count(snapshot_button) != 1:
            raise SystemExit("node-log clear button anchor not found")
        source = source.replace(snapshot_button, new_buttons, 1)

    if "    def clear_node_log(self)" not in source:
        methods = r'''    def clear_node_log(self) -> None:
        if not BLE_AVAILABLE:
            messagebox.showerror("Node-Log löschen", "Bluetooth ist in dieser App-Ausgabe nicht verfügbar.")
            return
        ble_devices = self.selected_ble_devices()
        if len(ble_devices) != 1:
            messagebox.showinfo(
                "Node-Log löschen",
                "Bitte genau einen Bluetooth-Node markieren. Der Löschbefehl wird absichtlich nie an mehrere Nodes gleichzeitig gesendet.",
            )
            return
        if self.worker and self.worker.is_alive():
            messagebox.showinfo("Node-Log löschen", "Bitte den laufenden Vorgang zuerst beenden.")
            return
        label, ble_device = ble_devices[0]
        backup_path = None
        if self.last_payload:
            backup_name = self._serial_monitor_long_name()
            backup_path = output_directory() / (
                f"Before_Clear_{safe_filename(backup_name)}_{now_local():%Y-%m-%d_%H%M%S}.log"
            )
            try:
                backup_path.write_bytes(self.last_payload)
            except OSError:
                backup_path = None
        backup_note = (
            f"\n\nDer zuletzt im Tool geladene Log wurde zusätzlich lokal gesichert:\n{backup_path}"
            if backup_path
            else "\n\nEs ist aktuell kein geladener Log für eine zusätzliche lokale Sicherheitskopie verfügbar."
        )
        if not messagebox.askyesno(
            "Node-Log wirklich löschen?",
            f"{label}\n\nNur der Diagnose-Logspeicher der Node wird geleert. "
            "Meshtastic-Konfiguration, NVS, Kanäle und Schlüssel bleiben unverändert."
            + backup_note
            + "\n\nFortfahren?",
            icon="warning",
        ):
            return
        self.status_level = "warning"
        self.status.configure(text=f"Node-Log wird gelöscht · {label}")
        self._update_status_badge()
        self.worker = threading.Thread(
            target=self._clear_node_log_worker,
            args=(label, ble_device, str(backup_path) if backup_path else ""),
            daemon=True,
        )
        self.worker.start()

    def _clear_node_log_worker(self, label: str, ble_device: object, backup_path: str) -> None:
        try:
            response = asyncio.run(self._clear_node_log_async(ble_device))
            self.events.put(("node_log_cleared", (label, response, backup_path)))
        except Exception as exc:
            self.events.put(("node_log_clear_error", (label, str(exc))))

    async def _clear_node_log_async(self, ble_device: object) -> str:
        async with BleakClient(
            ble_device,
            timeout=45.0,
            pair=False,
            winrt={"use_cached_services": False},
        ) as client:
            characteristic = client.services.get_characteristic(JARNSEN_DIAG_CONTROL_UUID)
            if characteristic is None:
                raise RuntimeError("Jarnsen-Diagnose-Steuerung fehlt in dieser Firmware.")
            await client.write_gatt_char(
                JARNSEN_DIAG_CONTROL_UUID, b"CLEARLOG", response=True
            )
            await asyncio.sleep(0.15)
            response = bytes(
                await client.read_gatt_char(JARNSEN_DIAG_CONTROL_UUID)
            ).decode("ascii", "replace").strip()
            if response != "CLEARED":
                raise RuntimeError(
                    "Firmware unterstützt den Remote-Löschbefehl noch nicht "
                    f"oder hat ihn abgelehnt ({response or '--'})."
                )
            return response
'''
        source = insert_before_method(source, "check_app_update", methods)

    event_anchor = '                elif kind == "app_update_status":\n'
    if 'elif kind == "node_log_cleared":' not in source:
        events = '''                elif kind == "node_log_cleared":
                    label, response, backup_path = value
                    self.status_level = "success"
                    self.status.configure(text=f"Node-Log gelöscht · {label}")
                    self._update_status_badge()
                    detail = f"\\n\\nLokales Backup: {backup_path}" if backup_path else ""
                    messagebox.showinfo(
                        "Node-Log gelöscht",
                        f"Diagnose-Log der Node wurde erfolgreich geleert ({response})."
                        f"{detail}\\n\\nBeim nächsten Logeintrag beginnt die Node mit einem frischen Diagnose-Log.",
                    )
                elif kind == "node_log_clear_error":
                    label, error = value
                    self.status_level = "error"
                    self.status.configure(text=f"Node-Log konnte nicht gelöscht werden · {label}")
                    self._update_status_badge()
                    messagebox.showerror("Node-Log löschen", str(error))
'''
        if source.count(event_anchor) != 1:
            raise SystemExit("node-log clear event anchor not found")
        source = source.replace(event_anchor, events + event_anchor, 1)

    selftest_anchor = '''        if APP_VERSION != "1.6.0":
            raise RuntimeError("App-Version ist nicht v1.6.0")
'''
    if '"copy_complete_serial_log"' not in source[source.find("def packaged_self_test"):]:
        addition = selftest_anchor + '''        if format_duration_seconds(16094856) != "186 d 6 h 47 min":
            raise RuntimeError("Laufzeitformatierung ist fehlerhaft")
        for method_name in (
            "copy_complete_serial_log",
            "_serial_monitor_long_name",
            "clear_node_log",
            "_clear_node_log_worker",
            "_clear_node_log_async",
        ):
            if not hasattr(ServiceTool, method_name):
                raise RuntimeError(f"v1.6-Funktion fehlt: {method_name}")
'''
        if source.count(selftest_anchor) != 1:
            raise SystemExit("v1.6 self-test anchor not found")
        source = source.replace(selftest_anchor, addition, 1)

    required = (
        'APP_VERSION = "1.6.0"',
        "def format_duration_seconds(",
        'text="Kompletten Log kopieren"',
        "def copy_complete_serial_log(self)",
        "def _serial_monitor_long_name(self)",
        'text="Node-Log löschen"',
        "def clear_node_log(self)",
        'b"CLEARLOG"',
        'elif kind == "node_log_cleared":',
        "format_duration_seconds(token('move'))",
    )
    for marker in required:
        if marker not in source:
            raise SystemExit(f"missing v1.6 marker: {marker}")
    return source


def main() -> None:
    target = Path(sys.argv[1] if len(sys.argv) > 1 else "tools/JARNSEN_NODE_SERVICE_TOOL.py")
    source = target.read_text(encoding="utf-8")
    target.write_text(patch(source), encoding="utf-8")
    print("Service tool patched to v1.6.0: readable runtimes, named serial logs, clipboard copy and node-log clear")


if __name__ == "__main__":
    main()
