"""v2.0.1 accessibility fix for Bluetooth, serial, new nodes and GitHub checks."""
from __future__ import annotations

import re
import sys
from pathlib import Path

APP_VERSION = "2.0.1"


def method_span(text: str, name: str) -> tuple[int, int]:
    start = text.find(f"    def {name}(")
    if start < 0:
        raise SystemExit(f"method {name} not found")
    next_method = text.find("\n    def ", start + 1)
    return start, next_method if next_method >= 0 else len(text)


def replace_method(text: str, name: str, updater) -> str:
    start, end = method_span(text, name)
    return text[:start] + updater(text[start:end]) + text[end:]


def insert_before_method(text: str, name: str, code: str) -> str:
    start, _ = method_span(text, name)
    return text[:start] + code.rstrip() + "\n\n" + text[start:]


def patch(source: str) -> str:
    source = re.sub(r'APP_VERSION = "[^"]+"', f'APP_VERSION = "{APP_VERSION}"', source, count=1)
    source = source.replace('APP_VERSION != "2.0.0"', 'APP_VERSION != "2.0.1"')
    source = source.replace("App-Version ist nicht v2.0.0", "App-Version ist nicht v2.0.1")

    def patch_workflow_ui(method: str) -> str:
        header_anchor = '''        self.workflow_connection.pack(side="left", fill="x", expand=True)\n'''
        if "self.github_quick_button" not in method:
            header_buttons = header_anchor + '''        self.github_quick_button = ttk.Button(\n            header, text="GitHub prüfen", command=self.refresh_firmware_status\n        )\n        self.github_quick_button.pack(side="right", padx=(6, 0))\n        self.serial_quick_button = ttk.Button(\n            header, text="Seriell", command=self.open_serial_tools\n        )\n        self.serial_quick_button.pack(side="right", padx=(6, 0))\n        self.bluetooth_quick_button = ttk.Button(\n            header, text="Bluetooth", command=self.open_bluetooth_tools\n        )\n        self.bluetooth_quick_button.pack(side="right", padx=(6, 0))\n        self.add_node_quick_button = ttk.Button(\n            header, text="+ Node", command=self.add_new_node\n        )\n        self.add_node_quick_button.pack(side="right", padx=(6, 0))\n'''
            if method.count(header_anchor) != 1:
                raise SystemExit("v2.0.1 header action anchor not found")
            method = method.replace(header_anchor, header_buttons, 1)

        old_order = '''        order = (\n            self.overview_tab,\n            self.service_tab,\n            self.track_tab,\n            self.firmware_tab,\n            self.history_tab,\n            self.trends_tab,\n            self.live_tab,\n            self.details_tab,\n        )\n'''
        new_order = '''        order = (\n            self.overview_tab,\n            self.service_tab,\n            self.track_tab,\n            self.firmware_tab,\n            self.history_tab,\n            self.trends_tab,\n            self.live_tab,\n            self.serial_tab,\n            self.details_tab,\n        )\n'''
        if "self.serial_tab,\n            self.details_tab" not in method:
            if method.count(old_order) != 1:
                raise SystemExit("v2.0.1 notebook order anchor not found")
            method = method.replace(old_order, new_order, 1)

        serial_label_anchor = '        self.notebook.tab(self.live_tab, text="Live")\n'
        if 'self.notebook.tab(self.serial_tab, text="Seriell")' not in method:
            if method.count(serial_label_anchor) != 1:
                raise SystemExit("v2.0.1 serial tab label anchor not found")
            method = method.replace(
                serial_label_anchor,
                serial_label_anchor + '        self.notebook.tab(self.serial_tab, text="Seriell")\n',
                1,
            )

        old_actions = '''        actions = (\n            ("Log herunterladen", self.smart_log_download, "Primary.TButton"),\n            ("Live ansehen", self.smart_live_view, "Primary.TButton"),\n            ("Nodes suchen", self.scan_ble, "TButton"),\n            ("Firmware aktualisieren", self.smart_firmware_update, "Primary.TButton"),\n            ("Service-WLAN öffnen", self.open_service_wlan, "TButton"),\n            ("Erweiterte Verbindung", self.toggle_advanced_controls, "TButton"),\n        )\n'''
        new_actions = '''        actions = (\n            ("Log herunterladen", self.smart_log_download, "Primary.TButton"),\n            ("Live ansehen", self.smart_live_view, "Primary.TButton"),\n            ("+ Neue Node", self.add_new_node, "Primary.TButton"),\n            ("Bluetooth öffnen", self.open_bluetooth_tools, "TButton"),\n            ("Seriell öffnen", self.open_serial_tools, "TButton"),\n            ("Firmware aktualisieren", self.smart_firmware_update, "Primary.TButton"),\n            ("GitHub prüfen", self.refresh_firmware_status, "TButton"),\n            ("Service-WLAN öffnen", self.open_service_wlan, "TButton"),\n        )\n'''
        if '"+ Neue Node", self.add_new_node' not in method:
            if method.count(old_actions) != 1:
                raise SystemExit("v2.0.1 service actions anchor not found")
            method = method.replace(old_actions, new_actions, 1)
        return method

    source = replace_method(source, "_install_workflow_ui", patch_workflow_ui)

    if "    def open_bluetooth_tools(self)" not in source:
        helpers = r'''    def open_bluetooth_tools(self) -> None:
        if not self.advanced_visible:
            self.toggle_advanced_controls()
        self.show_controls_page("Bluetooth")
        self.notebook.select(self.service_tab)
        self.status.configure(text="Bluetooth geöffnet · Node markieren oder Suche starten")
        if BLE_AVAILABLE and not (self.worker and self.worker.is_alive()):
            self.scan_ble()

    def open_serial_tools(self) -> None:
        if not self.advanced_visible:
            self.toggle_advanced_controls()
        source_name = self.serial_source.get() if hasattr(self, "serial_source") else "USB / COM"
        self.show_controls_page("Bluetooth" if source_name == "Bluetooth" else "USB")
        self.notebook.select(self.serial_tab)
        self.update_serial_monitor_source_ui()
        self.status.configure(text="Serieller Monitor geöffnet · Quelle oben im Tab wählen")

    def add_new_node(self) -> None:
        if self.worker and self.worker.is_alive():
            self.status_level = "warning"
            self.status.configure(text="Ein anderer Vorgang läuft bereits")
            self._update_status_badge()
            return
        if not self.advanced_visible:
            self.toggle_advanced_controls()
        self.show_controls_page("Bluetooth")
        self.notebook.select(self.service_tab)
        with contextlib.suppress(tk.TclError):
            self.ble_device.selection_clear(0, "end")
        self.status_level = "normal"
        self.status.configure(
            text="Neue Node: Bluetooth-Suche läuft · Node markieren und Log laden; danach wird sie automatisch gespeichert"
        )
        self._update_status_badge()
        if BLE_AVAILABLE:
            self.scan_ble()
        else:
            messagebox.showerror("Neue Node", "Bluetooth-Unterstützung ist in dieser App nicht verfügbar.")
'''
        source = insert_before_method(source, "open_usb_recovery", helpers)

    # Keep the self-test aligned with the bugfix version and verify the access methods exist.
    selftest_pos = source.find("def packaged_self_test(")
    if selftest_pos < 0:
        raise SystemExit("packaged_self_test not found")
    if '"open_bluetooth_tools"' not in source[selftest_pos:]:
        anchor = '        for method_name in (\n'
        pos = source.find(anchor, selftest_pos)
        if pos < 0:
            raise SystemExit("v2.0.1 self-test method list anchor not found")
        insert_at = pos + len(anchor)
        source = source[:insert_at] + '            "open_bluetooth_tools",\n            "open_serial_tools",\n            "add_new_node",\n' + source[insert_at:]

    required = (
        'APP_VERSION = "2.0.1"',
        'text="GitHub prüfen"',
        'text="Bluetooth"',
        'text="Seriell"',
        'text="+ Node"',
        'self.serial_tab,\n            self.details_tab',
        'self.notebook.tab(self.serial_tab, text="Seriell")',
        'def open_bluetooth_tools(self)',
        'def open_serial_tools(self)',
        'def add_new_node(self)',
    )
    for marker in required:
        if marker not in source:
            raise SystemExit(f"missing v2.0.1 access marker: {marker}")
    return source


def main() -> None:
    target = Path(sys.argv[1] if len(sys.argv) > 1 else "tools/JARNSEN_NODE_SERVICE_TOOL.py")
    target.write_text(patch(target.read_text(encoding="utf-8")), encoding="utf-8")
    print("Service tool v2.0.1: direct Bluetooth, serial, new-node and GitHub access")


if __name__ == "__main__":
    main()
