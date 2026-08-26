"""v1.9 overview compatibility and position-map validation for the shared Service Tool.

Runs after the v1.8 patcher. Besides the movement-filtered position map this
hotfix aligns the overview/parser with the current Heltec V3 and Tracker V1.1
BATTERY formats. The app version intentionally remains 1.9.0 so the existing
shared-release workflow and manifest stay compatible.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

APP_VERSION = "1.9.0"


def function_span(text: str, name: str) -> tuple[int, int]:
    start = text.find(f"def {name}(")
    if start < 0:
        raise SystemExit(f"function {name} not found")
    next_def = text.find("\ndef ", start + 1)
    next_class = text.find("\nclass ", start + 1)
    candidates = [value for value in (next_def, next_class) if value >= 0]
    return start, min(candidates) if candidates else len(text)


def patch(source: str) -> str:
    source = re.sub(
        r'APP_VERSION = "[^"]+"', f'APP_VERSION = "{APP_VERSION}"', source, count=1
    )
    source = source.replace('APP_VERSION != "1.8.0"', 'APP_VERSION != "1.9.0"')
    source = source.replace(
        "App-Version ist nicht v1.8.0", "App-Version ist nicht v1.9.0"
    )

    # Persist the fields that the current firmware already emits. Historical
    # and LIVE V3 battery lines are merged so a LIVE snapshot does not hide the
    # average-current fields from the most recent periodic BATTERY record.
    snapshot_new = r'''def snapshot_metrics(payload: bytes) -> dict[str, object]:
    basic = log_metrics(payload)
    text = payload.decode("utf-8", "replace")
    historical = list(re.finditer(r"\| BATTERY\s+\| ([^\r\n]+)", text))
    live = list(re.finditer(r"(?m)^LIVE \| BATTERY\s+\| ([^\r\n]+)", text))
    historical_battery = historical[-1].group(1) if historical else ""
    live_battery = live[-1].group(1) if live else ""
    battery = live_battery or historical_battery
    tokens: dict[str, str] = {}
    if historical_battery:
        tokens.update(
            re.findall(r"(?:^|\s)([A-Za-z][A-Za-z0-9]*)=([^\s]+)", historical_battery)
        )
    if live_battery:
        tokens.update(
            re.findall(r"(?:^|\s)([A-Za-z][A-Za-z0-9]*)=([^\s]+)", live_battery)
        )

    def number(name: str) -> float | None:
        return numeric_value(tokens.get(name, ""))

    estimate = re.search(
        r"(?:^|\s)est=(.*?)(?=\s+(?:ina|current)=|$)", battery
    )
    remaining_secs = None
    if estimate and "learning" not in estimate.group(1).lower():
        value = estimate.group(1).strip()
        days_match = re.search(r"(\d+)d", value)
        hours_match = re.search(r"(\d+)h", value)
        minutes_match = re.search(r"(\d+)min", value)
        days = numeric_value(days_match.group(1)) if days_match else 0
        hours = numeric_value(hours_match.group(1)) if hours_match else 0
        minutes = numeric_value(minutes_match.group(1)) if minutes_match else 0
        remaining_secs = (
            float(days or 0) * 86400
            + float(hours or 0) * 3600
            + float(minutes or 0) * 60
        )

    warning_count = int("incomplete sent=" in text)
    antenna_boots = re.findall(r"\| ANT_BOOT\s+\|[^\r\n]*txLock=(\d)", text)
    if antenna_boots and antenna_boots[-1] == "1":
        warning_count += 1
    basic.update(
        {
            "node_id": normalize_node_id(str(basic["node_id"])),
            "role": header_value(payload, b"role"),
            "remaining_secs": remaining_secs,
            "measured_secs": number("on") or number("measured"),
            "moving_secs": number("move"),
            "parked_secs": number("park"),
            "listen_secs": number("listen"),
            "service_secs": number("service"),
            "gps_secs": number("gps"),
            "ble_secs": number("ble"),
            "display_secs": number("disp"),
            "light_sleep_secs": number("lightSleep"),
            "deep_sleep_secs": number("deepSleep"),
            "current_ma": number("current"),
            "power_mw": number("power"),
            "consumed_mah": number("total") or number("used"),
            "sleep_estimated_mah": number("sleepEst"),
            "remaining_capacity_mah": number("left"),
            "capacity_cycles": number("cycles"),
            "avg_listen_ma": number("avgListen"),
            "avg_service_ma": number("avgService"),
            "avg_ble_ma": number("avgBle"),
            "avg_display_ma": number("avgDisplay"),
            "ina_state": tokens.get("ina", ""),
            "vbus_state": tokens.get("vbus", ""),
            "power_source": tokens.get("src", ""),
            "auto_positions": number("auto"),
            "manual_positions": number("manual"),
            "warning_count": warning_count,
            "raw_size": len(payload),
        }
    )
    for key in (
        "battery_mv",
        "battery_pct",
        "capacity",
        "confidence",
        "tx",
        "motion",
        "positions",
    ):
        basic[key] = numeric_value(str(basic.get(key, "")))
    if basic["measured_secs"] is None:
        basic["measured_secs"] = sum(
            float(basic.get(key) or 0)
            for key in ("moving_secs", "parked_secs", "listen_secs", "service_secs")
        )
    return basic
'''
    start, end = function_span(source, "snapshot_metrics")
    source = source[:start] + snapshot_new.rstrip() + "\n\n" + source[end:].lstrip("\n")

    dashboard_new = r'''def diagnostic_snapshot(payload: bytes, comparison: str = "") -> dict[str, object]:
    text = payload.decode("utf-8", "replace")
    historical = list(re.finditer(r"\| BATTERY\s+\| ([^\r\n]+)", text))
    live = list(re.finditer(r"(?m)^LIVE \| BATTERY\s+\| ([^\r\n]+)", text))
    historical_battery = historical[-1].group(1) if historical else ""
    live_battery = live[-1].group(1) if live else ""
    battery = live_battery or historical_battery
    latest_battery = bool(battery)
    tokens: dict[str, str] = {}
    if historical_battery:
        tokens.update(
            re.findall(r"(?:^|\s)([A-Za-z][A-Za-z0-9]*)=([^\s]+)", historical_battery)
        )
    if live_battery:
        tokens.update(
            re.findall(r"(?:^|\s)([A-Za-z][A-Za-z0-9]*)=([^\s]+)", live_battery)
        )
    voltage = re.search(r"(?:^|\s)(\d+)mV(?:\s|$)", battery)
    percent = re.search(r"(?:^|\s)(\d+)%", battery)
    device = header_value(payload, b"device")
    is_v3 = device == "HELTEC_V3_REPEATER"
    motion = len(re.findall(r"\| MOTION\s+\| confirmed", text))
    if is_v3:
        automatic_positions = len(re.findall(r"\| POSITION_AUTO\s+\|", text))
        manual_positions = len(re.findall(r"\| POSITION_MAN\s+\|", text))
        positions = automatic_positions + manual_positions
        fresh = automatic_positions
    else:
        automatic_positions = 0
        manual_positions = 0
        positions = len(re.findall(r"\| POSITION_TX\s+\|", text))
        fresh = len(re.findall(r"\| POSITION_TX\s+\|.*fresh=1", text))
    boots = len(re.findall(r"\| BOOT\s+\|", text))

    ina_raw = tokens.get("ina", "").upper()
    if is_v3:
        if ina_raw in {"ACTIVE", "OFF"}:
            ina = ina_raw
        elif "INA226: ACTIVE" in text:
            ina = "ACTIVE"
        elif "INA226: OFF" in text or "INA226 --" in text:
            ina = "OFF"
        else:
            ina = "--"
        ina_ok = ina == "ACTIVE"
    else:
        if ina_raw in {"OK", "WAIT", "MISSING", "OFF"}:
            ina = ina_raw
        elif re.search(r"\| INA226\s+\|[^\r\n]*READY", text):
            ina = "OK"
        else:
            ina = "--"
        ina_ok = ina == "OK"

    warnings = []
    if "incomplete sent=" in text:
        warnings.append("Historisch unvollständiger Export")
    antenna_boots = re.findall(r"\| ANT_BOOT\s+\|[^\r\n]*txLock=(\d)", text)
    if antenna_boots and antenna_boots[-1] == "1":
        warnings.append("Antennen-TX-Sperre aktiv")
    if not latest_battery:
        warnings.append("Keine Batteriedaten im Export")

    def token(name: str, fallback: str = "--") -> str:
        return tokens.get(name, fallback)

    def first_token(*names: str, fallback: str = "--") -> str:
        for name in names:
            if name in tokens:
                return tokens[name]
        return fallback

    estimate_match = re.search(
        r"(?:^|\s)est=(.*?)(?=\s+(?:ina|current)=|$)", battery
    )
    estimate_text = estimate_match.group(1).strip() if estimate_match else token("est")
    battery_source = "LIVE" if live_battery else ("letzter BATTERY-Logwert" if historical_battery else "--")

    battery_title = "--"
    if voltage or percent:
        battery_title = " / ".join(
            value
            for value in (
                f"{int(voltage.group(1)) / 1000:.3f} V" if voltage else "",
                f"{percent.group(1)} %" if percent else "",
            )
            if value
        )
    history = comparison.replace("Vergleich zum letzten Log:\n", "").strip()

    if is_v3:
        battery_lines = [
            f"Kapazität  {('nicht verfügbar (INA226)' if ina == 'OFF' else first_token('capacity', 'cap'))}",
            f"Restkapazität  {('nicht verfügbar' if ina == 'OFF' else token('left'))}",
            f"Prognose  {estimate_text}",
            f"Vertrauen / Zyklen  {first_token('confidence', 'conf')} / {token('cycles')}",
            f"Datenstand  {battery_source}",
        ]
        power_lines = [
            f"Quelle / VBUS  {token('src')} / {token('vbus')}",
            f"Strom / Leistung  {token('current')} / {token('power')}",
            f"Verbrauch  {first_token('used', 'total')}",
            f"USB / Laden  {token('usb')} / {token('charge')}",
        ]
        runtime_lines = [
            f"Funk hören / Service  {format_duration_seconds(token('listen'))} / {format_duration_seconds(token('service'))}",
            f"BLE / Display  {format_duration_seconds(token('ble'))} / {format_duration_seconds(token('disp'))}",
            f"Messzeit  {format_duration_seconds(first_token('on', 'measured'))}",
            f"Position-TX  {token('tx')}",
            f"Ø Listen / Service  {token('avgListen')} / {token('avgService')}",
            f"Ø BLE / Display  {token('avgBle')} / {token('avgDisplay')}",
        ]
    else:
        battery_lines = [
            f"Kapazität  {first_token('cap', 'capacity')}",
            f"Prognose  {estimate_text}",
            f"Vertrauen  {first_token('conf', 'confidence')}",
            f"Datenstand  {battery_source}",
        ]
        power_lines = [
            f"INA / VBUS  {ina} / {token('vbus')}",
            f"Strom  {token('current')}",
            f"Gesamtverbrauch  {first_token('total', 'used')}",
            f"Sleep-Anteil  {token('sleepEst')}",
            f"USB / Laden  {token('usb')} / {token('charge')}",
        ]
        runtime_lines = [
            f"Bewegt / Park  {format_duration_seconds(token('move'))} / {format_duration_seconds(token('park'))}",
            f"GPS / BLE  {format_duration_seconds(token('gps'))} / {format_duration_seconds(token('ble'))}",
            f"Display / TX  {format_duration_seconds(token('disp'))} / {token('tx')}",
            f"Light / Deep  {format_duration_seconds(token('lightSleep'))} / {format_duration_seconds(token('deepSleep'))}",
        ]

    return {
        "node": {
            "title": header_value(payload, b"long_name") or "Unbekannte Node",
            "lines": [
                f"ID  {header_value(payload, b'node_id') or '--'}",
                f"Short  {header_value(payload, b'short_name') or '--'}",
                f"Gerät  {DEVICE_NAMES.get(header_value(payload, b'device'), header_value(payload, b'device') or '--')}",
            ],
            "level": "accent",
        },
        "firmware": {
            "title": header_value(payload, b"firmware") or "--",
            "lines": [
                f"Build  {header_value(payload, b'build') or '--'}",
                f"Rolle  {header_value(payload, b'role') or '--'}",
                f"Boots  {boots}",
            ],
            "level": "normal",
        },
        "battery": {
            "title": battery_title,
            "lines": battery_lines,
            "level": (
                "warning"
                if not latest_battery or (percent and int(percent.group(1)) <= 20)
                else "success"
            ),
        },
        "power": {
            "title": f"INA226 {ina}",
            "lines": power_lines,
            "level": "success" if ina_ok else "warning",
        },
        "runtime": {
            "title": "Laufzeiten",
            "lines": runtime_lines,
            "level": "normal",
        },
        "events": {
            "title": (
                f"{first_token('auto', fallback=str(automatic_positions))} automatisch / "
                f"{first_token('manual', fallback=str(manual_positions))} manuell"
                if is_v3
                else f"{positions} Positionen"
            ),
            "lines": (
                [
                    f"Automatisch  {first_token('auto', fallback=str(automatic_positions))}",
                    f"Manuell  {first_token('manual', fallback=str(manual_positions))}",
                    f"TX-Zähler  {token('tx')}",
                ]
                if is_v3
                else [
                    f"Frisch  {fresh}",
                    f"Motion  {motion}",
                    f"TX-Zähler  {token('tx')}",
                ]
            ),
            "level": "success" if positions == 0 or fresh else "warning",
        },
        "health": {
            "title": (
                "Keine Warnungen" if not warnings else f"{len(warnings)} Hinweis(e)"
            ),
            "lines": warnings or ["Export und Prüfsummen plausibel"],
            "level": "success" if not warnings else "warning",
        },
        "history": {
            "title": "Historie",
            "lines": history.splitlines()[:5] if history else ["Noch kein Vergleich"],
            "level": "normal",
        },
    }
'''
    start, end = function_span(source, "diagnostic_snapshot")
    source = source[:start] + dashboard_new.rstrip() + "\n\n" + source[end:].lstrip("\n")

    # Extend the packaged test with the two real battery syntaxes. This catches
    # the Tracker ina=OK mismatch, multi-token ETA truncation and V3 LIVE-vs-
    # historical field merging before PyInstaller uploads an EXE.
    test_anchor = '''        report.write_text(\n            "OK: BLE, Papierkorb, Datenbank, Positionskarte und fünf Layouts\\n",\n            encoding="utf-8",\n        )\n'''
    if "Aktuelle V3-/Tracker-Übersicht ist fehlerhaft" not in source:
        test_extra = r'''        tracker_cards = diagnostic_snapshot(payload)
        tracker_battery = "\n".join(str(value) for value in tracker_cards["battery"]["lines"])
        tracker_power = "\n".join(str(value) for value in tracker_cards["power"]["lines"])
        if "1d 02h 03min" not in tracker_battery:
            raise RuntimeError("Tracker-Restlaufzeit wird in der Übersicht abgeschnitten")

        tracker_current = (
            b"# device=HELTEC_TRACKER_V1.1\n# node_id=!aabbccdd\n# long_name=Tracker Current\n"
            b"# short_name=TRK\n# firmware=2.8.0.test\n# build=11223344\n# role=TAK\n"
            b"0 | BATTERY | 4010mV 80% usb=0 charge=0 est=2d 03h 04min ina=OK vbus=OK "
            b"current=12.3mA total=1.2mAh sleepEst=0.4mAh lightSleep=7s deepSleep=8s "
            b"cap=12500mAh conf=80% move=10s park=20s gps=3s ble=4s disp=5s tx=6\n"
        )
        tracker_current_cards = diagnostic_snapshot(tracker_current)
        tracker_current_power = "\n".join(
            str(value) for value in tracker_current_cards["power"]["lines"]
        )
        if tracker_current_cards["power"]["title"] != "INA226 OK":
            raise RuntimeError("Tracker INA226-Status OK wird nicht erkannt")
        if "Sleep-Anteil  0.4mAh" not in tracker_current_power:
            raise RuntimeError("Tracker Sleep-Verbrauch fehlt in der Übersicht")
        tracker_metrics = snapshot_metrics(tracker_current)
        if tracker_metrics.get("light_sleep_secs") != 7 or tracker_metrics.get("deep_sleep_secs") != 8:
            raise RuntimeError("Tracker Light-/Deep-Sleep-Werte werden nicht gespeichert")

        v3_current = (
            b"# device=HELTEC_V3_REPEATER\n# node_id=!01020304\n# long_name=V3 Current\n"
            b"# short_name=V3\n# firmware=2.8.0.test\n# build=55667788\n# role=REPEATER\n"
            b"0 | BATTERY | src=INA226 ina=ACTIVE vbus=OK 3990mV 78% usb=0 charge=0 "
            b"est=3d 01h 02min current=11mA power=44mW used=22mAh/88mWh capacity=5000mAh "
            b"left=3900mAh confidence=75% cycles=2 avgListen=8mA avgService=20mA avgBle=17mA "
            b"avgDisplay=25mA listen=100s service=20s ble=10s disp=5s tx=7\n"
            b"LIVE | BATTERY | src=INA226 ina=ACTIVE vbus=OK 4020mV 80% usb=0 charge=0 "
            b"est=3d 05h 06min current=12mA power=48mW used=23mAh/92mWh capacity=5000mAh "
            b"left=4000mAh confidence=80% cycles=3 on=140s listen=110s service=30s ble=11s disp=6s "
            b"tx=8 auto=2 manual=1\n"
        )
        v3_cards = diagnostic_snapshot(v3_current)
        v3_battery = "\n".join(str(value) for value in v3_cards["battery"]["lines"])
        v3_power = "\n".join(str(value) for value in v3_cards["power"]["lines"])
        v3_runtime = "\n".join(str(value) for value in v3_cards["runtime"]["lines"])
        if "Restkapazität  4000mAh" not in v3_battery or "3d 05h 06min" not in v3_battery:
            raise RuntimeError("V3 Restkapazität oder Restlaufzeit fehlt in der Übersicht")
        if "12mA / 48mW" not in v3_power:
            raise RuntimeError("V3 Strom/Leistung fehlt in der Übersicht")
        if "8mA / 20mA" not in v3_runtime or "17mA / 25mA" not in v3_runtime:
            raise RuntimeError("V3 Durchschnittsströme werden durch LIVE-Daten verdeckt")
        v3_metrics = snapshot_metrics(v3_current)
        if v3_metrics.get("remaining_capacity_mah") != 4000 or v3_metrics.get("capacity_cycles") != 3:
            raise RuntimeError("V3 Restkapazität/Zyklen werden nicht gespeichert")

        if "INA226 OK" not in tracker_current_cards["power"]["title"] or "INA226 ACTIVE" not in v3_cards["power"]["title"]:
            raise RuntimeError("Aktuelle V3-/Tracker-Übersicht ist fehlerhaft")

        report.write_text(
            "OK: BLE, Papierkorb, Datenbank, Positionskarte, fünf Layouts und aktuelle V3-/Tracker-Übersicht\n",
            encoding="utf-8",
        )
'''
        if source.count(test_anchor) != 1:
            raise SystemExit("v1.9 packaged self-test anchor not found")
        source = source.replace(test_anchor, test_extra, 1)

    required = (
        'APP_VERSION = "1.9.0"',
        "def parse_track_points(",
        "def update_track_points(self)",
        "def fit_track_map(self)",
        "def zoom_track_map(self, factor: float)",
        "def render_track_map(self)",
        "Positionskarte",
        "Positionsverlauf wird nicht korrekt gelesen",
        "def reset_transfer_progress(self)",
        '"sleep_estimated_mah": number("sleepEst")',
        '"remaining_capacity_mah": number("left")',
        'ina_raw in {"OK", "WAIT", "MISSING", "OFF"}',
        'f"Restkapazität  {',
        'f"Sleep-Anteil  {token(\'sleepEst\')}"',
        'f"Ø Listen / Service  {token(\'avgListen\')} / {token(\'avgService\')}"',
        "Aktuelle V3-/Tracker-Übersicht ist fehlerhaft",
    )
    for marker in required:
        if marker not in source:
            raise SystemExit(f"missing v1.9 marker: {marker}")
    return source


def main() -> None:
    target = Path(
        sys.argv[1] if len(sys.argv) > 1 else "tools/JARNSEN_NODE_SERVICE_TOOL.py"
    )
    source = target.read_text(encoding="utf-8")
    target.write_text(patch(source), encoding="utf-8")
    print(
        "Service tool patched to v1.9.0: position map + current V3/Tracker overview parser"
    )


if __name__ == "__main__":
    main()
