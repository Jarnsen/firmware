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


def patch(source: str) -> str:
    start, end = method_span(source, "_install_workflow_ui")
    method = source[start:end]
    if "self.workflow_cancel" not in method:
        anchor = '''        self.advanced_button = ttk.Button(header, text="Erweitert", command=self.toggle_advanced_controls)\n        self.advanced_button.pack(side="right")\n'''
        replacement = '''        self.advanced_button = ttk.Button(header, text="Erweitert", command=self.toggle_advanced_controls)\n        self.advanced_button.pack(side="right")\n        self.workflow_cancel = ttk.Button(header, text="Abbrechen", command=self.cancel, state="disabled")\n        self.workflow_cancel.pack(side="right", padx=(0, 6))\n'''
        if method.count(anchor) != 1:
            raise SystemExit("persistent cancel-button anchor not found")
        method = method.replace(anchor, replacement, 1)
        source = source[:start] + method + source[end:]

    start, end = method_span(source, "_pump_events")
    method = source[start:end]
    if "self.workflow_cancel.configure" not in method:
        anchor = '''        self._continue_smart_action()\n        self.refresh_workflow_header()\n        self.after(100, self._pump_events)\n'''
        replacement = '''        self._continue_smart_action()\n        self.refresh_workflow_header()\n        if hasattr(self, "workflow_cancel") and hasattr(self, "cancel_button"):\n            self.workflow_cancel.configure(state=str(self.cancel_button.cget("state")))\n        self.after(100, self._pump_events)\n'''
        if method.count(anchor) != 1:
            raise SystemExit("persistent cancel sync anchor not found")
        method = method.replace(anchor, replacement, 1)
        source = source[:start] + method + source[end:]

    # The position status is packed before track_canvas; both are direct children
    # of track_tab in v1.9. Keep a source-level invariant so later layout patches
    # cannot silently break that relationship.
    for marker in (
        'self.track_canvas = tk.Canvas(\n            self.track_tab',
        'self.position_status_label.pack(fill="x", pady=(0, 6), before=self.track_canvas)',
        'self.workflow_cancel = ttk.Button',
        'self.workflow_cancel.configure(state=str(self.cancel_button.cget("state")))',
    ):
        if marker not in source:
            raise SystemExit(f"missing v2.0 final UI marker: {marker}")
    return source


def main() -> None:
    target = Path(sys.argv[1] if len(sys.argv) > 1 else "tools/JARNSEN_NODE_SERVICE_TOOL.py")
    target.write_text(patch(target.read_text(encoding="utf-8")), encoding="utf-8")
    print("Service tool v2.0 final UI: persistent cancel + position-layout invariant")


if __name__ == "__main__":
    main()
