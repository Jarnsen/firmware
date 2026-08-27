"""v2.0 final UI safeguards and regression checks for the task-oriented Service Tool."""
from __future__ import annotations

import sys
from pathlib import Path


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


def replace_method(text: str, name: str, updater) -> str:
    start, end = method_span(text, name)
    return text[:start] + updater(text[start:end]) + text[end:]


def replace_function(text: str, name: str, updater) -> str:
    start, end = function_span(text, name)
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

    def harden_ble_selection(method: str) -> str:
        old = '''        elif len(labels) == 1:\n            index = 0\n'''
        new = '''        elif not preferred and len(labels) == 1:\n            index = 0\n'''
        if new in method:
            return method
        if method.count(old) != 1:
            raise SystemExit("smart BLE single-device anchor not found")
        return method.replace(old, new, 1)

    source = replace_method(source, "_select_preferred_ble_device", harden_ble_selection)

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

    def add_v20_regression_tests(function: str) -> str:
        if "v20_v3_payload" in function:
            return function
        anchor = '''        report.write_text(\n'''
        if function.count(anchor) != 1:
            raise SystemExit("v2.0 self-test report anchor not found")
        tests = r'''        v20_v3_payload = (
            b"# device=HELTEC_V3_REPEATER\n# node_id=!01020304\n# long_name=V3 Test\n# short_name=V3T\n"
            b"# firmware=test\n# build=12345678\n# role=REPEATER\n"
            b"LIVE | BATTERY | src=INA226 ina=ACTIVE vbus=OK 4020mV 80% usb=0 charge=0 est=3d 05h 06min "
            b"current=12mA power=48mW used=23mAh/92mWh capacity=5000mAh left=4000mAh confidence=80% cycles=3 "
            b"avgListen=8mA avgService=20mA avgBle=17mA avgDisplay=25mA on=140s listen=110s service=30s ble=11s disp=6s "
            b"tx=8 auto=2 manual=1\n"
            b"100 | PHONE_POS_EST | state=moving samples=4 stabilize=0/3 remain=0s step=38m reported=6m estimate=9m "
            b"fixed-diff=147m phone-age=2s\n"
            b"101 | PHONE_POS_LIVE | saved-diff=147m step=80m tx=1 min=75m/30s smart=1 stale-embedded=0\n"
        )
        v20_v3_metrics = snapshot_metrics(v20_v3_payload)
        if v20_v3_metrics.get("position_state") != "moving":
            raise RuntimeError("V3 Bewegungszustand wird nicht gespeichert")
        if v20_v3_metrics.get("live_positions") != 1.0:
            raise RuntimeError("V3 Live-Positionen werden nicht gezählt")
        if v20_v3_metrics.get("reported_accuracy") != 6.0 or v20_v3_metrics.get("estimated_accuracy") != 9.0:
            raise RuntimeError("V3 GPS-Qualität wird nicht gespeichert")
        if v20_v3_metrics.get("fixed_difference") != 147.0 or v20_v3_metrics.get("movement_step") != 38.0:
            raise RuntimeError("V3 Bewegungs-/Fixabstand wird nicht gespeichert")
        v20_v3_cards = diagnostic_snapshot(v20_v3_payload)
        if v20_v3_cards.get("position", {}).get("title") != "Bewegung":
            raise RuntimeError("V3 Positionskarte der Übersicht zeigt Bewegungszustand nicht")
        if "Live während Fahrt  1" not in "\n".join(v20_v3_cards.get("events", {}).get("lines", [])):
            raise RuntimeError("V3 Live-TX fehlt in der Ereignisübersicht")

        v20_tracker_payload = (
            b"# device=HELTEC_TRACKER_V1.1\n# node_id=!aabbccdd\n# long_name=Tracker Test\n# short_name=TRK\n"
            b"# firmware=test\n# build=87654321\n# role=TAK_TRACKER\n"
            b"LIVE | BATTERY | 4010mV 80% usb=0 charge=0 est=2d 03h 04min ina=OK vbus=OK current=12.3mA "
            b"total=1.2mAh sleepEst=0.4mAh lightSleep=7s deepSleep=8s cap=12500mAh left=10000mAh conf=80% "
            b"cycles=5 on=30s move=10s park=20s gps=3s ble=4s disp=5s tx=6\n"
            b"10 | BATTERY_LEARN | capacity=12500mAh sample=12400mAh drop=20% confidence=80% cycles=5\n"
        )
        v20_tracker_metrics = snapshot_metrics(v20_tracker_payload)
        if v20_tracker_metrics.get("remaining_capacity") != 10000.0:
            raise RuntimeError("Tracker Restkapazität aus LIVE BATTERY fehlt")
        if v20_tracker_metrics.get("capacity_cycles") != 5.0 or v20_tracker_metrics.get("capacity_sample") != 12400.0:
            raise RuntimeError("Tracker Kapazitätslernen wird nicht gespeichert")
        v20_tracker_cards = diagnostic_snapshot(v20_tracker_payload)
        tracker_battery_lines = "\n".join(v20_tracker_cards.get("battery", {}).get("lines", []))
        for expected in ("Restkapazität  10000mAh", "Lernzyklen  5", "Letztes Lernsample  12400mAh"):
            if expected not in tracker_battery_lines:
                raise RuntimeError(f"Tracker v2.0 Übersicht fehlt: {expected}")

'''
        return function.replace(anchor, tests + anchor, 1)

    source = replace_function(source, "packaged_self_test", add_v20_regression_tests)

    for marker in (
        'self.track_canvas = tk.Canvas(\n            self.track_tab',
        'self.position_status_label.pack(fill="x", pady=(0, 6), before=self.track_canvas)',
        'self.workflow_cancel = ttk.Button',
        'self.workflow_cancel.configure(state=str(self.cancel_button.cget("state")))',
        'elif not preferred and len(labels) == 1:',
        "v20_v3_payload",
        "v20_tracker_payload",
    ):
        if marker not in source:
            raise SystemExit(f"missing v2.0 final marker: {marker}")

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
    print("Service tool v2.0 final: workflow UX + V3/Tracker regression self-tests")


if __name__ == "__main__":
    main()
