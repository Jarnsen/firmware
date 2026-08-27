"""v2.0 diagnostic extensions for current V3 and Tracker firmware."""
from __future__ import annotations

import re
import sys
from pathlib import Path

APP_VERSION = "2.0.0"


def method_span(text: str, name: str) -> tuple[int, int]:
    start = text.find(f"    def {name}(")
    if start < 0:
        raise SystemExit(f"method {name} not found")
    next_method = text.find("\n    def ", start + 1)
    return start, next_method if next_method >= 0 else len(text)


def patch(source: str) -> str:
    source = re.sub(r'APP_VERSION = "[^"]+"', f'APP_VERSION = "{APP_VERSION}"', source, count=1)
    source = source.replace('APP_VERSION != "1.9.0"', 'APP_VERSION != "2.0.0"')
    source = source.replace("App-Version ist nicht v1.9.0", "App-Version ist nicht v2.0.0")

    # log_metrics/snapshot_metrics are defined before NodeRepository, so wrap them there.
    class_pos = source.find("\nclass NodeRepository")
    if class_pos < 0:
        raise SystemExit("NodeRepository anchor not found")
    if "_v20_base_log_metrics = log_metrics" not in source:
        metric_extension = r'''
_v20_base_log_metrics = log_metrics
_v20_base_snapshot_metrics = snapshot_metrics


def _v20_position_detail(text: str) -> str:
    matches = list(re.finditer(r"\| PHONE_POS_EST\s+\| ([^\r\n]+)", text))
    return matches[-1].group(1) if matches else ""


def _v20_detail_value(detail: str, name: str) -> str:
    match = re.search(rf"(?:^|\s){re.escape(name)}=([^\s]+)", detail)
    return match.group(1) if match else ""


def _v20_learning_detail(text: str) -> str:
    matches = list(re.finditer(r"\| BATTERY_LEARN\s+\| ([^\r\n]+)", text))
    return matches[-1].group(1) if matches else ""


def log_metrics(payload: bytes) -> dict[str, str]:
    result = dict(_v20_base_log_metrics(payload))
    text = payload.decode("utf-8", "replace")
    detail = _v20_position_detail(text)
    learn = _v20_learning_detail(text)
    live_positions = len(re.findall(r"\| PHONE_POS_LIVE\s+\|[^\r\n]*\btx=1\b", text))
    cycles = re.search(r"(?:^|\s)cycles=(\d+)", learn)
    sample = re.search(r"(?:^|\s)sample=(\d+)mAh", learn)
    battery = current_battery_line(text)
    left = re.search(r"(?:^|\s)left=([^\s]+)", battery)
    battery_cycles = re.search(r"(?:^|\s)cycles=(\d+)", battery)
    result.update({
        "remaining_capacity": left.group(1) if left else "",
        "capacity_cycles": battery_cycles.group(1) if battery_cycles else (cycles.group(1) if cycles else ""),
        "capacity_sample": sample.group(1) if sample else "",
        "live_positions": str(live_positions),
        "position_state": _v20_detail_value(detail, "state"),
        "position_samples": _v20_detail_value(detail, "samples"),
        "stabilize": _v20_detail_value(detail, "stabilize"),
        "stabilize_remaining": _v20_detail_value(detail, "remain"),
        "movement_step": _v20_detail_value(detail, "step"),
        "reported_accuracy": _v20_detail_value(detail, "reported"),
        "estimated_accuracy": _v20_detail_value(detail, "estimate").lstrip("?"),
        "fixed_difference": _v20_detail_value(detail, "fixed-diff").lstrip("?"),
        "phone_age": _v20_detail_value(detail, "phone-age"),
    })
    if header_value(payload, b"device") == "HELTEC_V3_REPEATER":
        try:
            result["positions"] = str(int(result.get("positions") or "0") + live_positions)
        except ValueError:
            pass
    return result


def snapshot_metrics(payload: bytes) -> dict[str, object]:
    result = dict(_v20_base_snapshot_metrics(payload))
    extended = log_metrics(payload)
    for key in (
        "remaining_capacity", "capacity_cycles", "capacity_sample", "live_positions",
        "position_samples", "stabilize_remaining", "movement_step", "reported_accuracy",
        "estimated_accuracy", "fixed_difference", "phone_age",
    ):
        result[key] = numeric_value(str(extended.get(key, "")))
    result["position_state"] = extended.get("position_state", "")
    result["stabilize"] = extended.get("stabilize", "")
    result["positions"] = numeric_value(str(extended.get("positions", "")))
    return result
'''
        source = source[:class_pos] + "\n" + metric_extension.strip() + "\n\n" + source[class_pos + 1:]

    # diagnostic_snapshot is defined later, directly before ServiceTool. Wrap it only there.
    service_pos = source.find("\nclass ServiceTool")
    if service_pos < 0:
        raise SystemExit("ServiceTool anchor not found")
    if "_v20_base_diagnostic_snapshot = diagnostic_snapshot" not in source:
        dashboard_extension = r'''
_v20_base_diagnostic_snapshot = diagnostic_snapshot


def diagnostic_snapshot(payload: bytes, comparison: str = "") -> dict[str, object]:
    cards = dict(_v20_base_diagnostic_snapshot(payload, comparison))
    text = payload.decode("utf-8", "replace")
    is_v3 = header_value(payload, b"device") == "HELTEC_V3_REPEATER"
    if is_v3:
        detail = _v20_position_detail(text)
        state_raw = _v20_detail_value(detail, "state") or "unknown"
        state_label = {"moving": "Bewegung", "stabilizing": "Stabilisierung", "stationary": "Stationär"}.get(state_raw, "Unbekannt")
        live_positions = len(re.findall(r"\| PHONE_POS_LIVE\s+\|[^\r\n]*\btx=1\b", text))
        cards["position"] = {
            "title": state_label,
            "lines": [
                f"Samples / Stabilisierung  {_v20_detail_value(detail, 'samples') or '--'} / {_v20_detail_value(detail, 'stabilize') or '--'}",
                f"Restzeit / Schritt  {_v20_detail_value(detail, 'remain') or '--'} / {_v20_detail_value(detail, 'step') or '--'}",
                f"GPS gemeldet / geschätzt  {_v20_detail_value(detail, 'reported') or '--'} / {_v20_detail_value(detail, 'estimate') or '--'}",
                f"Abstand feste Position  {_v20_detail_value(detail, 'fixed-diff') or '--'}",
                f"Phone-Alter / Live-TX  {_v20_detail_value(detail, 'phone-age') or '--'} / {live_positions}",
            ],
            "level": "warning" if state_raw == "stabilizing" else ("accent" if state_raw == "moving" else "success"),
        }
        auto_count = len(re.findall(r"\| POSITION_AUTO\s+\|", text))
        manual_count = len(re.findall(r"\| POSITION_MAN\s+\|", text))
        tx_match = re.search(r"(?:^|\s)tx=([^\s]+)", current_battery_line(text))
        cards["events"] = {
            "title": f"{auto_count} auto / {manual_count} manuell / {live_positions} live",
            "lines": [
                f"Automatisch fest  {auto_count}",
                f"Manuell fest  {manual_count}",
                f"Live während Fahrt  {live_positions}",
                f"TX-Zähler  {tx_match.group(1) if tx_match else '--'}",
            ],
            "level": "success",
        }
        ordered = {}
        for key in ("node", "position", "firmware", "battery", "power", "runtime", "events", "health", "history"):
            if key in cards:
                ordered[key] = cards[key]
        cards = ordered
    else:
        learn = _v20_learning_detail(text)
        battery = current_battery_line(text)
        cycles = re.search(r"(?:^|\s)cycles=(\d+)", battery) or re.search(r"(?:^|\s)cycles=(\d+)", learn)
        sample = re.search(r"(?:^|\s)sample=(\d+)mAh", learn)
        left = re.search(r"(?:^|\s)left=([^\s]+)", battery)
        if "battery" in cards:
            lines = list(cards["battery"].get("lines", []))
            if left:
                lines.insert(1, f"Restkapazität  {left.group(1)}")
            lines.append(f"Lernzyklen  {cycles.group(1) if cycles else '--'}")
            lines.append(f"Letztes Lernsample  {sample.group(1) + 'mAh' if sample else '--'}")
            cards["battery"]["lines"] = lines
    return cards
'''
        source = source[:service_pos] + "\n" + dashboard_extension.strip() + "\n\n" + source[service_pos + 1:]

    # History comparisons should surface the new diagnostic dimensions.
    start, end = method_span(source, "history_comparison")
    method = source[start:end]
    if "V3 Live-TX" not in method:
        marker = '            ("confidence", "Vertrauen"),\n'
        addition = marker + '            ("capacity_cycles", "Lernzyklen"),\n            ("live_positions", "V3 Live-TX"),\n            ("position_state", "V3 Bewegungszustand"),\n            ("reported_accuracy", "GPS-Genauigkeit"),\n            ("estimated_accuracy", "GPS-Schätzung"),\n            ("fixed_difference", "Abstand Fixposition"),\n'
        if marker not in method:
            raise SystemExit("history comparison anchor missing")
        method = method.replace(marker, addition, 1)
        source = source[:start] + method + source[end:]

    trend_values = '''                "Position-TX",
            ),'''
    if "V3 GPS geschätzt" not in source:
        if trend_values not in source:
            raise SystemExit("trend values anchor missing")
        source = source.replace(trend_values, '''                "Position-TX",
                "V3 Live-TX",
                "V3 GPS gemeldet",
                "V3 GPS geschätzt",
                "V3 Abstand Fixposition",
                "V3 Bewegungsschritt",
                "Tracker Lernzyklen",
            ),''', 1)
    trend_map = '''            "Position-TX": ("tx", ""),
        }'''
    if '"V3 Live-TX": ("live_positions"' not in source:
        if trend_map not in source:
            raise SystemExit("trend map anchor missing")
        source = source.replace(trend_map, '''            "Position-TX": ("tx", ""),
            "V3 Live-TX": ("live_positions", ""),
            "V3 GPS gemeldet": ("reported_accuracy", "m"),
            "V3 GPS geschätzt": ("estimated_accuracy", "m"),
            "V3 Abstand Fixposition": ("fixed_difference", "m"),
            "V3 Bewegungsschritt": ("movement_step", "m"),
            "Tracker Lernzyklen": ("capacity_cycles", ""),
        }''', 1)

    required = (
        'APP_VERSION = "2.0.0"',
        "_v20_base_log_metrics",
        "_v20_base_diagnostic_snapshot",
        "Live während Fahrt",
        "V3 GPS geschätzt",
        "Tracker Lernzyklen",
    )
    for marker in required:
        if marker not in source:
            raise SystemExit(f"missing v2.0 metrics marker: {marker}")
    return source


def main() -> None:
    target = Path(sys.argv[1] if len(sys.argv) > 1 else "tools/JARNSEN_NODE_SERVICE_TOOL.py")
    target.write_text(patch(target.read_text(encoding="utf-8")), encoding="utf-8")
    print("Service tool v2.0 diagnostics: V3 motion/GPS/live TX + Tracker learning")


if __name__ == "__main__":
    main()
