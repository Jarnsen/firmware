"""v2.0 final UI safeguards for the task-oriented Service Tool."""
from __future__ import annotations

import sys
from pathlib import Path


def method_span(text: str, name: str) -> tuple[int, int]:
    start = text.find(f"    def {name}(")
    if start < 0:
        raise SystemExit(f"method {name} not found")
    next_method = text.find("\n    def ", start + 1)
    return start, next_method if next_method >= 0 else len(text)


def replace_method(text: str, name: str, updater) -> str:
    start, end = method_span(text, name)
    return text[:start] + updater(text[start:end]) + text[end:]


def patch(source: str) -> str:
    def add_cancel(method: str) -> str:
        if "self.workflow_cancel" in method:
            return method
        anchor = '''        self.advanced_button = ttk.Button(header, text="Erweitert", command=self.toggle_advanced_controls)\n        self.advanced_button.pack(side="right")\n'''
        replacement = '''        self.advanced_button = ttk.Button(header, text="Erweitert", command=self.toggle_advanced_controls)\n        self.advanced_button.pack(side="right")\n        self.workflow_cancel = ttk.Button(header, text="Abbrechen", command=self.cancel, state="disabled")\n        self.workflow_cancel.pack(side="right", padx=(0, 6))\n'''
        if method.count(anchor) != 1:
            raise SystemExit("persistent cancel-button anchor not found")
        return method.replace(anchor, replacement, 1)

    source = replace_method(source, "_install_workflow_ui", add_cancel)

    def sync_cancel(method: str) -> str:
        if "self.workflow_cancel.configure" in method:
            return method
        anchor = '''        self._continue_smart_action()\n        self.refresh_workflow_header()\n        self.after(100, self._pump_events)\n'''
        replacement = '''        self._continue_smart_action()\n        self.refresh_workflow_header()\n        if hasattr(self, "workflow_cancel") and hasattr(self, "cancel_button"):\n            self.workflow_cancel.configure(state=str(self.cancel_button.cget("state")))\n        self.after(100, self._pump_events)\n'''
        if method.count(anchor) != 1:
            raise SystemExit("persistent cancel sync anchor not found")
        return method.replace(anchor, replacement, 1)

    source = replace_method(source, "_pump_events", sync_cancel)

    # A known Node must never silently select a different single BLE device.
    # Only auto-select a lone BLE result when no Node identity is known yet.
    def harden_ble_selection(method: str) -> str:
        old = '''        elif len(labels) == 1:\n            index = 0\n'''
        new = '''        elif not preferred and len(labels) == 1:\n            index = 0\n'''
        if new in method:
            return method
        if method.count(old) != 1:
            raise SystemExit("smart BLE single-device anchor not found")
        return method.replace(old, new, 1)

    source = replace_method(source, "_select_preferred_ble_device", harden_ble_selection)

    # Do not rebuild/reset the selector every 100 ms while the user is opening it.
    # Refresh it only when the Node list or selected Node actually changes.
    def stop_selector_churn(method: str) -> str:
        line = '        self.refresh_node_selector()\n'
        if line in method:
            method = method.replace(line, "", 1)
        return method

    source = replace_method(source, "refresh_workflow_header", stop_selector_churn)

    def sync_selector_on_selection(method: str) -> str:
        marker = '        self.refresh_workflow_header()\n'
        addition = '        self.refresh_node_selector()\n'
        if addition in method:
            return method
        if method.count(marker) != 1:
            raise SystemExit("node-selection selector-sync anchor not found")
        return method.replace(marker, addition + marker, 1)

    source = replace_method(source, "on_node_selected", sync_selector_on_selection)

    # The position status is packed before track_canvas; both are direct children
    # of track_tab in v1.9. Keep a source-level invariant so later layout patches
    # cannot silently break that relationship.
    for marker in (
        'self.track_canvas = tk.Canvas(\n            self.track_tab',
        'self.position_status_label.pack(fill="x", pady=(0, 6), before=self.track_canvas)',
        'self.workflow_cancel = ttk.Button',
        'self.workflow_cancel.configure(state=str(self.cancel_button.cget("state")))',
        'elif not preferred and len(labels) == 1:',
    ):
        if marker not in source:
            raise SystemExit(f"missing v2.0 final UI marker: {marker}")

    start, end = method_span(source, "refresh_workflow_header")
    if "self.refresh_node_selector()" in source[start:end]:
        raise SystemExit("Node selector is still refreshed from the 100ms header loop")
    start, end = method_span(source, "on_node_selected")
    if "self.refresh_node_selector()" not in source[start:end]:
        raise SystemExit("Node selector is not synchronized on Node selection")
    return source


def main() -> None:
    target = Path(sys.argv[1] if len(sys.argv) > 1 else "tools/JARNSEN_NODE_SERVICE_TOOL.py")
    target.write_text(patch(target.read_text(encoding="utf-8")), encoding="utf-8")
    print("Service tool v2.0 final UI: safe BLE selection + stable selector + persistent cancel")


if __name__ == "__main__":
    main()
