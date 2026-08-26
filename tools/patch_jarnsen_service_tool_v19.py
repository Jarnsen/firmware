"""v1.9 position map plus current V3/Tracker overview compatibility."""

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
    ends = [value for value in (next_def, next_class) if value >= 0]
    return start, min(ends) if ends else len(text)


def patch(source: str) -> str:
    source = re.sub(r'APP_VERSION = "[^"]+"', f'APP_VERSION = "{APP_VERSION}"', source, count=1)
    source = source.replace('APP_VERSION != "1.8.0"', 'APP_VERSION != "1.9.0"')
    source = source.replace("App-Version ist nicht v1.8.0", "App-Version ist nicht v1.9.0")

    overview = r'''def diagnostic_snapshot(payload: bytes, comparison: str = "") -> dict[str, object]:
    text = payload.decode("utf-8", "replace")
    # A V3 BLE export contains a fresh LIVE line. Merge it over the most recent
    # normal BATTERY line so fields omitted by LIVE (notably avg* currents) are
    # still available. Do not accidentally count LIVE itself as historical.
    historical = list(
        re.finditer(
            r"(?m)^(?!LIVE \|)[^|\r\n]+\| BATTERY\s+\| ([^\r\n]+)", text
        )
    )
    live = list(re.finditer(r"(?m)^LIVE \| BATTERY\s+\| ([^\r\n]+)", text))
    historical_battery = historical[-1].group(1) if historical else ""
    live_battery = live[-1].group(1) if live else ""
    battery = live_battery or historical_battery
    tokens: dict[str, str] = {}
    for detail in (historical_battery, live_battery):
        if detail:
            tokens.update(
                re.findall(r"(?:^|\s)([A-Za-z][A-Za-z0-9]*)=([^\s]+)", detail)
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
        automatic_positions = manual_positions = 0
        positions = len(re.findall(r"\| POSITION_TX\s+\|", text))
        fresh = len(re.findall(r"\| POSITION_TX\s+\|.*fresh=1", text))
    boots = len(re.findall(r"\| BOOT\s+\|", text))

    def token(name: str, fallback: str = "--") -> str:
        return tokens.get(name, fallback)

    def first_token(*names: str, fallback: str = "--") -> str:
        for name in names:
            if name in tokens:
                return tokens[name]
        return fallback

    ina_raw = token("ina", "").upper()
    if is_v3:
        ina = ina_raw if ina_raw in {"ACTIVE", "OFF"} else "--"
        ina_ok = ina == "ACTIVE"
    else:
        # Current Tracker firmware emits OK / WAIT / MISSING / OFF, not ACTIVE.
        ina = ina_raw if ina_raw in {"OK", "WAIT", "MISSING", "OFF"} else "--"
        if ina == "--" and re.search(r"\| INA226\s+\|[^\r\n]*READY", text):
            ina = "OK"
        ina_ok = ina == "OK"

    estimate = re.search(r"(?:^|\s)est=(.*?)(?=\s+(?:ina|current)=|$)", battery)
    estimate_text = estimate.group(1).strip() if estimate else token("est")
    battery_source = "LIVE" if live_battery else ("letzter BATTERY-Logwert" if historical_battery else "--")

    warnings: list[str] = []
    if "incomplete sent=" in text:
        warnings.append("Historisch unvollständiger Export")
    antenna_boots = re.findall(r"\| ANT_BOOT\s+\|[^\r\n]*txLock=(\d)", text)
    if antenna_boots and antenna_boots[-1] == "1":
        warnings.append("Antennen-TX-Sperre aktiv")
    if not battery:
        warnings.append("Keine Batteriedaten im Export")

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

    if is_v3:
        battery_lines = [
            f"Kapazität  {first_token('capacity', 'cap')}",
            f"Restkapazität  {token('left')}",
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

    history = comparison.replace("Vergleich zum letzten Log:\n", "").strip()
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
            "level": "warning" if not battery or (percent and int(percent.group(1)) <= 20) else "success",
        },
        "power": {
            "title": f"INA226 {ina}",
            "lines": power_lines,
            "level": "success" if ina_ok else "warning",
        },
        "runtime": {"title": "Laufzeiten", "lines": runtime_lines, "level": "normal"},
        "events": {
            "title": (
                f"{first_token('auto', fallback=str(automatic_positions))} automatisch / "
                f"{first_token('manual', fallback=str(manual_positions))} manuell"
                if is_v3 else f"{positions} Positionen"
            ),
            "lines": (
                [
                    f"Automatisch  {first_token('auto', fallback=str(automatic_positions))}",
                    f"Manuell  {first_token('manual', fallback=str(manual_positions))}",
                    f"TX-Zähler  {token('tx')}",
                ]
                if is_v3 else [f"Frisch  {fresh}", f"Motion  {motion}", f"TX-Zähler  {token('tx')}"]
            ),
            "level": "success" if positions == 0 or fresh else "warning",
        },
        "health": {
            "title": "Keine Warnungen" if not warnings else f"{len(warnings)} Hinweis(e)",
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
    source = source[:start] + overview.rstrip() + "\n\n" + source[end:].lstrip("\n")

    test_anchor = '''        report.write_text(\n            "OK: BLE, Papierkorb, Datenbank, Positionskarte und fünf Layouts\\n",\n            encoding="utf-8",\n        )\n'''
    if "Übersichtsparser V3/Tracker geprüft" not in source:
        tests = r'''        tracker_now = (
            b"# device=HELTEC_TRACKER_V1.1\n# node_id=!aabbccdd\n# long_name=Tracker\n# short_name=TRK\n"
            b"# firmware=test\n# build=11223344\n# role=TAK\n"
            b"0 | BATTERY | 4010mV 80% usb=0 charge=0 est=2d 03h 04min ina=OK vbus=OK current=12.3mA "
            b"total=1.2mAh sleepEst=0.4mAh lightSleep=7s deepSleep=8s cap=12500mAh conf=80% "
            b"move=10s park=20s gps=3s ble=4s disp=5s tx=6\n"
        )
        tracker_cards = diagnostic_snapshot(tracker_now)
        if tracker_cards["power"]["title"] != "INA226 OK":
            raise RuntimeError("Tracker INA226-Status OK wird nicht erkannt")
        if "2d 03h 04min" not in "\n".join(tracker_cards["battery"]["lines"]):
            raise RuntimeError("Tracker-Restlaufzeit wird abgeschnitten")
        if "Sleep-Anteil  0.4mAh" not in "\n".join(tracker_cards["power"]["lines"]):
            raise RuntimeError("Tracker Sleep-Verbrauch fehlt")

        v3_now = (
            b"# device=HELTEC_V3_REPEATER\n# node_id=!01020304\n# long_name=V3\n# short_name=V3\n"
            b"# firmware=test\n# build=55667788\n# role=REPEATER\n"
            b"0 | BATTERY | src=INA226 ina=ACTIVE vbus=OK 3990mV 78% usb=0 charge=0 est=3d 01h 02min "
            b"current=11mA power=44mW used=22mAh/88mWh capacity=5000mAh left=3900mAh confidence=75% "
            b"cycles=2 avgListen=8mA avgService=20mA avgBle=17mA avgDisplay=25mA listen=100s service=20s ble=10s disp=5s tx=7\n"
            b"LIVE | BATTERY | src=INA226 ina=ACTIVE vbus=OK 4020mV 80% usb=0 charge=0 est=3d 05h 06min "
            b"current=12mA power=48mW used=23mAh/92mWh capacity=5000mAh left=4000mAh confidence=80% cycles=3 "
            b"on=140s listen=110s service=30s ble=11s disp=6s tx=8 auto=2 manual=1\n"
        )
        v3_cards = diagnostic_snapshot(v3_now)
        v3_all = "\n".join(v3_cards["battery"]["lines"] + v3_cards["power"]["lines"] + v3_cards["runtime"]["lines"])
        for expected_text in ("Restkapazität  4000mAh", "3d 05h 06min", "12mA / 48mW", "8mA / 20mA", "17mA / 25mA"):
            if expected_text not in v3_all:
                raise RuntimeError(f"V3 Übersichtsdatum fehlt: {expected_text}")

        report.write_text(
            "OK: BLE, Papierkorb, Datenbank, Positionskarte, fünf Layouts; Übersichtsparser V3/Tracker geprüft\n",
            encoding="utf-8",
        )
'''
        if source.count(test_anchor) != 1:
            raise SystemExit("v1.9 self-test anchor not found")
        source = source.replace(test_anchor, tests, 1)

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
        'ina_raw in {"OK", "WAIT", "MISSING", "OFF"}',
        "Restkapazität",
        "Sleep-Anteil",
        "avgListen",
        "Übersichtsparser V3/Tracker geprüft",
    )
    for marker in required:
        if marker not in source:
            raise SystemExit(f"missing v1.9 marker: {marker}")
    return source


def main() -> None:
    target = Path(sys.argv[1] if len(sys.argv) > 1 else "tools/JARNSEN_NODE_SERVICE_TOOL.py")
    source = target.read_text(encoding="utf-8")
    target.write_text(patch(source), encoding="utf-8")
    print("Service tool patched to v1.9.0: position map + current V3/Tracker overview")


if __name__ == "__main__":
    main()
