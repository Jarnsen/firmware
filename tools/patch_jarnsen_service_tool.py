"""Build-time v1.3 patcher for the shared Jarnsen Node Service Tool."""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

APP_VERSION = "1.3.0"


def function_span(text: str, name: str) -> tuple[int, int]:
    start = text.find(f"def {name}(")
    if start < 0:
        raise SystemExit(f"function {name} not found")
    next_def = text.find("\ndef ", start + 1)
    next_class = text.find("\nclass ", start + 1)
    candidates = [value for value in (next_def, next_class) if value >= 0]
    return start, min(candidates) if candidates else len(text)


def method_span(text: str, name: str) -> tuple[int, int]:
    start = text.find(f"    def {name}(")
    if start < 0:
        raise SystemExit(f"method {name} not found")
    next_method = text.find("\n    def ", start + 1)
    return start, next_method if next_method >= 0 else len(text)


def insert_before_method(text: str, name: str, code: str) -> str:
    start, _ = method_span(text, name)
    return text[:start] + code.rstrip() + "\n\n" + text[start:]


def replace_assignment(text: str, function_name: str, replacement: str) -> str:
    start, end = function_span(text, function_name)
    block = text[start:end]
    marker = "    ina = ("
    pos = block.find(marker)
    if pos < 0:
        match = re.search(r"(?m)^    ina = .*current_ina_state.*$", block)
        if not match:
            raise SystemExit(f"INA assignment not found in {function_name}")
        block = block[: match.start()] + replacement + block[match.end() :]
        return text[:start] + block + text[end:]
    scan = block.find("\n", pos)
    if scan < 0:
        scan = len(block)
    depth = block[pos:scan].count("(") - block[pos:scan].count(")")
    while depth > 0 and scan < len(block):
        next_end = block.find("\n", scan + 1)
        if next_end < 0:
            next_end = len(block)
        segment = block[scan + 1 : next_end]
        depth += segment.count("(") - segment.count(")")
        scan = next_end
    block = block[:pos] + replacement + block[scan:]
    return text[:start] + block + text[end:]


def patch(source: str, build_sha: str) -> str:
    serial_anchor = "import serial\nfrom serial.tools import list_ports\n"
    if "ESPTOOL_AVAILABLE" not in source:
        serial_import = '''import serial
from serial.tools import list_ports

try:
    import esptool

    ESPTOOL_AVAILABLE = True
except ImportError:
    esptool = None
    ESPTOOL_AVAILABLE = False
'''
        if source.count(serial_anchor) != 1:
            raise SystemExit("serial import anchor not found exactly once")
        source = source.replace(serial_anchor, serial_import, 1)

    hw_anchor = '''OTABT_HARDWARE_CODES = {
    43: "V3",
    48: "TRACKER",
}
'''
    if "HARDWARE_PROFILES =" not in source:
        hw_block = hw_anchor + '''HARDWARE_PROFILES = {
    "TRACKER": {
        "label": "Tracker V1.1",
        "device": "HELTEC_TRACKER_V1.1",
        "release": "jarnsen-tracker-latest",
    },
    "V3": {
        "label": "Heltec V3",
        "device": "HELTEC_V3_REPEATER",
        "release": "jarnsen-v3-latest",
    },
}
'''
        if source.count(hw_anchor) != 1:
            raise SystemExit("hardware anchor not found exactly once")
        source = source.replace(hw_anchor, hw_block, 1)

    repo_anchor = 'GITHUB_REPOSITORY = "Jarnsen/firmware"'
    version_block = (
        repo_anchor
        + f'\nAPP_VERSION = "{APP_VERSION}"'
        + f'\nAPP_BUILD = "{build_sha[:8] or "unknown"}"'
        + '\nAPP_CHANNEL = "shared"'
    )
    if "APP_VERSION =" in source:
        source = re.sub(
            r'GITHUB_REPOSITORY = "Jarnsen/firmware"\nAPP_VERSION = "[^"]+"\nAPP_BUILD = "[^"]+"(?:\nAPP_CHANNEL = "[^"]+")?',
            version_block,
            source,
            count=1,
        )
    else:
        if source.count(repo_anchor) != 1:
            raise SystemExit("repository anchor not found exactly once")
        source = source.replace(repo_anchor, version_block, 1)

    if "def current_ina_state(" not in source:
        insert_at = source.find("\ndef log_metrics(")
        if insert_at < 0:
            raise SystemExit("log_metrics anchor not found")
        helpers = r'''


def current_ina_state(text: str, unknown: str = "--") -> str:
    """Return the newest INA226 state in actual log order."""
    state = unknown
    mapping = {
        "ACTIVE": "ACTIVE",
        "OK": "ACTIVE",
        "WAIT": "WAIT",
        "MISSING": "MISSING",
        "OFF": "OFF",
    }
    for line in text.splitlines():
        upper = line.upper()
        if "BATTERY" in upper:
            match = re.search(
                r"(?:^|\s)ina=(ACTIVE|OK|WAIT|MISSING|OFF)(?:\s|$)",
                line,
                re.IGNORECASE,
            )
            if match:
                state = mapping[match.group(1).upper()]
        if "INA226" not in upper:
            continue
        if re.search(r"\b(?:READY|SAMPLE|ACTIVE)\b", upper):
            state = "ACTIVE"
        elif any(
            token in upper
            for token in (
                "ACK FAIL",
                "SENSOR MISSING",
                "SENSOR NOT READY",
                "ENABLED BUT SENSOR",
                "NOT FOUND",
            )
        ):
            state = "MISSING"
        elif any(token in upper for token in ("INA226=OFF", "INA226: OFF", "INA226 | OFF")):
            state = "OFF"
    return state


def enrich_power_metrics(metrics: dict[str, object], text: str, battery: str) -> dict[str, object]:
    """Normalize power data independent of the concrete sensor hardware."""
    tokens = dict(re.findall(r"(?:^|\s)([A-Za-z][A-Za-z0-9]*)=([^\s]+)", battery or ""))

    def number_token(*names: str) -> float | None:
        for name in names:
            if name in tokens:
                return numeric_value(tokens[name])
        return None

    ina_state = current_ina_state(text)
    metrics["power_source"] = tokens.get("src") or ("INA226" if ina_state == "ACTIVE" else "INTERNAL")
    metrics["ina_state"] = ina_state
    metrics["capacity_cycles"] = number_token("cycles")
    metrics["remaining_capacity_mah"] = number_token("left", "remaining")
    metrics["sleep_estimated_mah"] = number_token("sleepEst")
    metrics["light_sleep_secs"] = number_token("lightSleep")
    metrics["deep_sleep_secs"] = number_token("deepSleep")
    metrics["listen_secs"] = number_token("listen")
    metrics["service_secs"] = number_token("service")
    metrics["charged_mah"] = number_token("charged", "chargeIn")
    metrics["power_mw"] = number_token("power")

    learning = list(
        re.finditer(
            r"\|\s*BATTERY_LEARN\s*\|[^\r\n]*capacity=(\d+)mAh[^\r\n]*"
            r"sample=(\d+)mAh[^\r\n]*drop=(\d+)%[^\r\n]*"
            r"confidence=(\d+)%[^\r\n]*cycles=(\d+)",
            text,
            re.IGNORECASE,
        )
    )
    if learning:
        last = learning[-1]
        metrics["capacity_sample_mah"] = float(last.group(2))
        metrics["capacity_drop_pct"] = float(last.group(3))
        metrics["capacity_cycles"] = float(last.group(5))
    else:
        metrics["capacity_sample_mah"] = None
        metrics["capacity_drop_pct"] = None

    if metrics.get("remaining_capacity_mah") is None:
        cap = metrics.get("capacity")
        pct = metrics.get("battery_pct")
        if isinstance(cap, (int, float)) and cap > 0 and isinstance(pct, (int, float)) and 0 <= pct <= 100:
            metrics["remaining_capacity_mah"] = float(cap) * float(pct) / 100.0
    return metrics


def _capture_time(value: object) -> dt.datetime | None:
    try:
        parsed = dt.datetime.fromisoformat(str(value))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=dt.timezone.utc)
        return parsed
    except (TypeError, ValueError):
        return None


def power_window_summary(logs: list[dict[str, object]], hours: float | None = None) -> dict[str, object] | None:
    """Use counter deltas; never estimate average current from one spot sample."""
    rows = []
    for item in logs:
        stamp = _capture_time(item.get("captured_at"))
        metrics = item.get("metrics")
        if stamp is not None and isinstance(metrics, dict):
            rows.append((stamp, metrics))
    if len(rows) < 2:
        return None
    rows.sort(key=lambda item: item[0])
    end_time, end = rows[-1]
    if hours is None:
        candidates = rows[:-1]
    else:
        cutoff = end_time - dt.timedelta(hours=hours)
        inside = [item for item in rows[:-1] if item[0] >= cutoff]
        before = [item for item in rows[:-1] if item[0] < cutoff]
        candidates = inside or before[-1:]
    if not candidates:
        return None
    start_time, start = candidates[0]
    elapsed_h = (end_time - start_time).total_seconds() / 3600.0
    if elapsed_h <= 0:
        return None

    def delta(name: str) -> float | None:
        a, b = start.get(name), end.get(name)
        if not isinstance(a, (int, float)) or not isinstance(b, (int, float)):
            return None
        value = float(b) - float(a)
        return value if value >= 0 else None

    consumed = delta("consumed_mah")
    avg_ma = consumed / elapsed_h if consumed is not None else None
    result: dict[str, object] = {
        "hours": elapsed_h,
        "avg_ma": avg_ma,
        "mah_per_day": avg_ma * 24.0 if avg_ma is not None else None,
        "consumed_mah": consumed,
    }
    measured = delta("measured_secs")
    denominator = measured if measured and measured > 0 else elapsed_h * 3600.0
    shares = {}
    for key, label in (
        ("moving_secs", "Bewegung"),
        ("parked_secs", "Park"),
        ("listen_secs", "Listen"),
        ("service_secs", "Service"),
        ("gps_secs", "GPS"),
        ("ble_secs", "BLE"),
        ("display_secs", "Display"),
        ("light_sleep_secs", "Light"),
        ("deep_sleep_secs", "Deep"),
    ):
        value = delta(key)
        if value is not None and denominator > 0:
            shares[label] = max(0.0, min(100.0, value * 100.0 / denominator))
    result["shares"] = shares
    tx = delta("tx")
    result["tx_per_hour"] = tx / elapsed_h if tx is not None else None
    return result


def add_power_analysis_cards(cards: dict[str, object], logs: list[dict[str, object]], payload: bytes) -> dict[str, object]:
    metrics = snapshot_metrics(payload)

    def fmt(value: object, digits: int = 1, suffix: str = "") -> str:
        return f"{float(value):.{digits}f}{suffix}" if isinstance(value, (int, float)) else "--"

    cap = metrics.get("capacity")
    conf = metrics.get("confidence")
    cycles = metrics.get("capacity_cycles")
    drop = metrics.get("capacity_drop_pct")
    remaining = metrics.get("remaining_capacity_mah")
    cards["akku_lernen"] = {
        "title": "Kapazitätslernen" if isinstance(cap, (int, float)) and cap > 0 else "Lernphase läuft",
        "lines": [
            f"Gelernte Kapazität  {fmt(cap, 0, ' mAh')}",
            f"Restkapazität  {fmt(remaining, 0, ' mAh')}",
            f"Vertrauen  {fmt(conf, 0, ' %')}",
            f"Lernzyklen  {fmt(cycles, 0)} · letzter Bereich {fmt(drop, 0, ' %')}",
        ],
        "level": "success" if isinstance(conf, (int, float)) and conf >= 40 else "warning",
    }

    day = power_window_summary(logs, 24.0)
    week = power_window_summary(logs, 168.0)
    all_time = power_window_summary(logs, None)
    lines = [f"Quelle  {metrics.get('power_source') or '--'} · INA226 {metrics.get('ina_state') or '--'}"]
    if day:
        lines.append(f"Ø 24 h  {fmt(day.get('avg_ma'), 1, ' mA')} · {fmt(day.get('mah_per_day'), 0, ' mAh/Tag')}")
    if week:
        lines.append(f"Ø 7 Tage  {fmt(week.get('avg_ma'), 1, ' mA')} · {fmt(week.get('mah_per_day'), 0, ' mAh/Tag')}")
    if all_time:
        lines.append(f"Ø Verlauf  {fmt(all_time.get('avg_ma'), 1, ' mA')} · Δ {fmt(all_time.get('consumed_mah'), 1, ' mAh')}")
    if len(lines) == 1:
        lines.append("Mindestens zwei Logs werden für Durchschnittswerte benötigt.")
    cards["power_analyse"] = {"title": "Verbrauch & Durchschnitt", "lines": lines, "level": "success" if metrics.get("ina_state") == "ACTIVE" else "normal"}

    runtime = day or all_time
    if runtime:
        shares = runtime.get("shares") or {}
        duty_lines = []
        if isinstance(shares, dict) and shares:
            ordered = sorted(shares.items(), key=lambda item: item[1], reverse=True)
            duty_lines.append(" · ".join(f"{name} {value:.1f} %" for name, value in ordered[:4]))
        tx_rate = runtime.get("tx_per_hour")
        if isinstance(tx_rate, (int, float)):
            duty_lines.append(f"TX-Rate  {tx_rate:.2f}/h")
        if duty_lines:
            cards["duty_cycle"] = {"title": "Laufzeitanteile", "lines": duty_lines, "level": "accent"}
    return cards
'''
        source = source[:insert_at] + helpers + source[insert_at:]

    start, end = function_span(source, "snapshot_metrics")
    block = source[start:end]
    if "return enrich_power_metrics(basic, text, battery)" not in block:
        if "    return basic\n" not in block:
            raise SystemExit("snapshot_metrics return anchor not found")
        block = block.replace("    return basic\n", "    return enrich_power_metrics(basic, text, battery)\n", 1)
        source = source[:start] + block + source[end:]

    source = replace_assignment(source, "analyse_log", '    ina = current_ina_state(text, "nicht ermittelt")')
    source = replace_assignment(source, "diagnostic_snapshot", "    ina = current_ina_state(text)")

    dashboard_old = '''            cards = diagnostic_snapshot(self.last_payload, self.last_comparison)
            firmware_card = self.firmware_card(
                header_value(self.last_payload, b"device"),
                header_value(self.last_payload, b"build"),
            )
            cards = {"softwarestand": firmware_card, **cards}
'''
    dashboard_new = '''            cards = diagnostic_snapshot(self.last_payload, self.last_comparison)
            firmware_card = self.firmware_card(
                header_value(self.last_payload, b"device"),
                header_value(self.last_payload, b"build"),
            )
            node_id = normalize_node_id(header_value(self.last_payload, b"node_id"))
            power_logs = self.repository.logs_for_node(node_id) if node_id else []
            cards = add_power_analysis_cards(cards, power_logs, self.last_payload)
            cards = {"softwarestand": firmware_card, **cards}
'''
    if dashboard_old in source:
        source = source.replace(dashboard_old, dashboard_new, 1)
    elif "cards = add_power_analysis_cards(cards, power_logs, self.last_payload)" not in source:
        raise SystemExit("dashboard analysis anchor not found")

    title_anchor = '        self.title_label.pack(side="left")'
    if "self.app_version_label" not in source:
        version_ui = '''        self.title_label.pack(side="left")
        self.app_version_label = ttk.Label(
            title_row,
            text=f"App v{APP_VERSION} · Build {APP_BUILD} · {APP_CHANNEL}",
            style="Subtitle.TLabel",
        )
        self.app_version_label.pack(side="left", padx=(12, 0))'''
        if source.count(title_anchor) != 1:
            raise SystemExit("title anchor not found exactly once")
        source = source.replace(title_anchor, version_ui, 1)

    theme_anchor = '        self.theme.pack(side="right")'
    if "self.restart_button" not in source:
        restart_ui = '''        self.theme.pack(side="right")
        self.restart_button = ttk.Button(
            title_row, text="App neu starten", command=self.restart_app
        )
        self.restart_button.pack(side="right", padx=(8, 8))'''
        if source.count(theme_anchor) != 1:
            raise SystemExit("theme anchor not found exactly once")
        source = source.replace(theme_anchor, restart_ui, 1)

    if "    def choose_hardware_dialog(self" not in source:
        dialog_method = r'''    def choose_hardware_dialog(self, title: str = "Hardware auswählen", message: str = "") -> str:
        result = {"value": ""}
        dialog = tk.Toplevel(self)
        dialog.title(title)
        dialog.transient(self)
        dialog.grab_set()
        dialog.resizable(False, False)
        frame = ttk.Frame(dialog, padding=16)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text=message or "Bitte den Gerätetyp auswählen.", justify="left", wraplength=430).pack(anchor="w", pady=(0, 14))
        buttons = ttk.Frame(frame)
        buttons.pack(fill="x")

        def choose(value: str) -> None:
            result["value"] = value
            dialog.destroy()

        ttk.Button(buttons, text="Heltec V3", command=lambda: choose("V3"), style="Primary.TButton").pack(side="left", fill="x", expand=True, padx=(0, 5))
        ttk.Button(buttons, text="Tracker V1.1", command=lambda: choose("TRACKER"), style="Primary.TButton").pack(side="left", fill="x", expand=True, padx=5)
        ttk.Button(buttons, text="Abbrechen", command=lambda: choose("")).pack(side="left", fill="x", expand=True, padx=(5, 0))
        dialog.protocol("WM_DELETE_WINDOW", lambda: choose(""))
        dialog.update_idletasks()
        x = self.winfo_rootx() + max(0, (self.winfo_width() - dialog.winfo_width()) // 2)
        y = self.winfo_rooty() + max(0, (self.winfo_height() - dialog.winfo_height()) // 2)
        dialog.geometry(f"+{x}+{y}")
        self.wait_window(dialog)
        return str(result["value"])
'''
        source = insert_before_method(source, "start_ble_update", dialog_method)

    old_recovery = '''            answer = messagebox.askyesnocancel(
                "OTA-Gerätetyp bestätigen",
                "Der OTA-Loader meldet keinen eindeutigen Gerätetyp.\\n\\n"
                "Ist das wartende Gerät ein Heltec V3?\\n\\n"
                "Ja = Heltec V3\\nNein = Tracker V1.1\\nAbbrechen = nichts ändern",
            )
            if answer is None:
                return
            recovery_device_code = "V3" if answer else "TRACKER"
'''
    new_recovery = '''            recovery_device_code = self.choose_hardware_dialog(
                "OTA-Gerätetyp auswählen",
                "Der wartende OTA-Loader meldet keinen eindeutigen Gerätetyp.\\nBitte die Hardware auswählen:",
            )
            if not recovery_device_code:
                return
'''
    if old_recovery in source:
        source = source.replace(old_recovery, new_recovery, 1)
    elif '"OTA-Gerätetyp auswählen"' not in source:
        raise SystemExit("OTA recovery anchor not found")

    serial_ui_anchor = '''        self.start_button.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(8, 0))
        setup.columnconfigure(1, weight=1)
'''
    if "self.serial_update_button" not in source:
        serial_ui = '''        self.start_button.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(8, 0))
        self.serial_update_button = ttk.Button(
            setup,
            text="Firmware + OTA-Loader über USB aktualisieren",
            command=self.start_serial_update,
        )
        self.serial_update_button.grid(row=4, column=0, columnspan=2, sticky="ew", pady=(8, 0))
        setup.columnconfigure(1, weight=1)
'''
        if source.count(serial_ui_anchor) != 1:
            raise SystemExit("serial UI anchor not found exactly once")
        source = source.replace(serial_ui_anchor, serial_ui, 1)

    if "    def start_serial_update(self)" not in source:
        serial_methods = r'''    def _selected_serial_hardware(self) -> str:
        selected = self.device.get()
        if selected == "Tracker V1.1":
            return "TRACKER"
        if selected == "Heltec V3":
            return "V3"
        if self.selected_node_id:
            latest = self.repository.latest_log(self.selected_node_id)
            if latest and isinstance(latest.get("metrics"), dict):
                device = str(latest["metrics"].get("device") or "")
                if device == "HELTEC_TRACKER_V1.1":
                    return "TRACKER"
                if device == "HELTEC_V3_REPEATER":
                    return "V3"
        return self.choose_hardware_dialog(
            "USB-Firmware auswählen",
            "Tracker und V3 verwenden beide einen ESP32-S3. Der Chip allein kann die Hardware nicht unterscheiden.",
        )

    @staticmethod
    def _download_serial_bundle(device_code: str) -> tuple[bytes, bytes, dict[str, object]]:
        firmware, manifest = ServiceTool._download_otabt_bundle(device_code)
        config = OTABT_RELEASES.get(device_code)
        if not config:
            raise RuntimeError(f"Unbekannter Gerätetyp {device_code}")
        request = urllib.request.Request(
            f"https://api.github.com/repos/{GITHUB_REPOSITORY}/releases/tags/{config['tag']}",
            headers={"User-Agent": "Jarnsen-Node-Service-Tool"},
        )
        with contextlib.closing(urllib.request.urlopen(request, timeout=30)) as response:  # nosec B310  # nosemgrep
            release = json.load(response)
        assets = {
            str(asset.get("name") or ""): str(asset.get("browser_download_url") or "")
            for asset in release.get("assets", []) if isinstance(asset, dict)
        }
        loader_name = str(manifest.get("ota_loader_asset") or "otaBTupdate.bin")
        loader_hash = str(manifest.get("ota_loader_sha256") or "").lower()
        loader_url = assets.get(loader_name, "")
        if not loader_url or not re.fullmatch(r"[0-9a-f]{64}", loader_hash):
            raise RuntimeError("OTA-Loader im GitHub-Manifest ist unvollständig")
        loader_request = urllib.request.Request(loader_url, headers={"User-Agent": "Jarnsen-Node-Service-Tool"})
        with contextlib.closing(urllib.request.urlopen(loader_request, timeout=90)) as response:  # nosec B310  # nosemgrep
            loader = response.read(0x200000)
        if not loader or loader[0] != 0xE9:
            raise RuntimeError("OTA-Loader ist kein gültiges ESP32-S3-Abbild")
        if hashlib.sha256(loader).hexdigest() != loader_hash:
            raise RuntimeError("SHA-256-Prüfung des OTA-Loaders fehlgeschlagen")
        return firmware, loader, manifest

    @staticmethod
    def _run_esptool(args: list[str]) -> None:
        if not ESPTOOL_AVAILABLE or esptool is None:
            raise RuntimeError("esptool ist in dieser App-Ausgabe nicht enthalten")
        try:
            esptool.main(args)
        except SystemExit as exc:
            code = int(exc.code or 0)
            if code != 0:
                raise RuntimeError(f"esptool wurde mit Fehlercode {code} beendet") from exc

    def start_serial_update(self) -> None:
        if not ESPTOOL_AVAILABLE:
            messagebox.showerror("Serieller Firmwareupload", "Diese App-Ausgabe enthält esptool nicht.")
            return
        port = self.selected_port()
        if not port:
            messagebox.showerror("Kein Port", "Bitte einen COM-Port auswählen.")
            return
        if "bluetooth" in self.port.get().lower():
            messagebox.showerror(
                "Falscher COM-Port",
                "Ein Windows-Bluetooth-Seriell-Port darf nicht zum Flashen verwendet werden. Bitte den echten USB-Port des ESP32-S3 auswählen.",
            )
            return
        if self.worker and self.worker.is_alive():
            return
        device_code = self._selected_serial_hardware()
        if not device_code:
            return
        profile = HARDWARE_PROFILES[device_code]
        if not messagebox.askyesno(
            "USB-Firmwareupdate",
            f"{profile['label']} auf {port} aktualisieren?\\n\\n"
            "Hauptfirmware und OTA-Bootloader werden direkt von GitHub geladen und per SHA-256 geprüft.\\n"
            "NVS, Meshtastic-Einstellungen und Diagnose-Logs werden nicht gelöscht.",
        ):
            return
        self.stop_event.clear()
        self.start_button.configure(state="disabled")
        self.serial_update_button.configure(state="disabled")
        self.ble_update_button.configure(state="disabled")
        self.cancel_button.configure(state="normal")
        self.set_transfer_progress(None, "GitHub-Paket prüfen", True)
        self.worker = threading.Thread(target=self._serial_update_worker, args=(port, device_code), daemon=True)
        self.worker.start()

    def _serial_update_worker(self, port: str, device_code: str) -> None:
        try:
            profile = HARDWARE_PROFILES[device_code]
            self.events.put(("status", f"{profile['label']}: Firmware von GitHub laden ..."))
            firmware, loader, manifest = self._download_serial_bundle(device_code)
            if self.stop_event.is_set():
                raise RuntimeError("Firmwareupdate abgebrochen")
            with tempfile.TemporaryDirectory() as temporary:
                directory = pathlib.Path(temporary)
                firmware_path = directory / "firmware.update.bin"
                loader_path = directory / "otaBTupdate.bin"
                firmware_path.write_bytes(firmware)
                loader_path.write_bytes(loader)
                self.events.put(("progress_detail", (10, "ESP32-S3 prüfen", False)))
                self._run_esptool(["--chip", "esp32s3", "--port", port, "chip-id"])
                if self.stop_event.is_set():
                    raise RuntimeError("Firmwareupdate abgebrochen")
                self.events.put(("progress_detail", (25, "Firmware + OTA-Loader flashen", False)))
                self._run_esptool([
                    "--chip", "esp32s3", "--port", port, "--baud", "460800",
                    "--before", "default-reset", "--after", "hard-reset", "write-flash",
                    "0x10000", str(firmware_path), "0x340000", str(loader_path),
                ])
                self.events.put(("progress_detail", (90, "OTA-Bootwahl zurücksetzen", False)))
                self._run_esptool([
                    "--chip", "esp32s3", "--port", port,
                    "--before", "default-reset", "--after", "hard-reset",
                    "erase-region", "0xE000", "0x2000",
                ])
            source_sha = str(manifest.get("source_sha") or "")
            self.events.put((
                "serial_update_result",
                f"{profile['label']} erfolgreich über {port} aktualisiert.\\n"
                f"GitHub-Build: {source_sha[:8] or '--'}\\n"
                "Hauptfirmware: 0x10000 · OTA-Loader: 0x340000 · Bootwahl zurückgesetzt.",
            ))
        except Exception as exc:
            self.events.put(("serial_update_error", str(exc)))
        finally:
            self.events.put(("done", None))
'''
        source = insert_before_method(source, "scan_ble", serial_methods)

    if "    def restart_app(self)" not in source:
        restart_method = r'''    def restart_app(self) -> None:
        if not messagebox.askyesno("App neu starten", "Jarnsen Node Service Tool jetzt neu starten? Laufende Downloads werden beendet."):
            return
        self.stop_event.set()
        self.live_stop.set()
        self.update_idletasks()
        try:
            if getattr(sys, "frozen", False):
                argv = [sys.executable, *sys.argv[1:]]
            else:
                argv = [sys.executable, os.path.abspath(sys.argv[0]), *sys.argv[1:]]
            os.execv(sys.executable, argv)
        except Exception as exc:
            messagebox.showerror("Neustart fehlgeschlagen", str(exc))
'''
        source = insert_before_method(source, "close_app", restart_method)

    ota_event_anchor = '                elif kind == "ota_queue_result":\n'
    if 'elif kind == "serial_update_result":' not in source:
        serial_events = '''                elif kind == "serial_update_result":
                    self.status_level = "success"
                    self.status.configure(text="USB-Firmwareupdate abgeschlossen")
                    self._update_status_badge()
                    self.set_transfer_progress(100, "Firmwareupdate abgeschlossen", False)
                    self.set_result(str(value))
                    messagebox.showinfo("USB-Firmwareupdate", str(value))
                elif kind == "serial_update_error":
                    self.status_level = "error"
                    self.status.configure(text="USB-Firmwareupdate fehlgeschlagen")
                    self._update_status_badge()
                    self.set_result(str(value))
                    messagebox.showerror("USB-Firmwareupdate", str(value))
'''
        if source.count(ota_event_anchor) != 1:
            raise SystemExit("event anchor not found exactly once")
        source = source.replace(ota_event_anchor, serial_events + ota_event_anchor, 1)

    done_anchor = '                    self.start_button.configure(state="normal")\n'
    if 'self.serial_update_button.configure(state="normal")' not in source:
        if source.count(done_anchor) != 1:
            raise SystemExit("done anchor not found exactly once")
        source = source.replace(done_anchor, done_anchor + '                    self.serial_update_button.configure(state="normal")\n', 1)

    selftest_anchor = '''        if not RECYCLE_AVAILABLE:
            raise RuntimeError("send2trash ist nicht verfügbar")
'''
    if 'raise RuntimeError("esptool ist nicht verfügbar")' not in source:
        extra = selftest_anchor + '''        if not ESPTOOL_AVAILABLE:
            raise RuntimeError("esptool ist nicht verfügbar")
        if set(HARDWARE_PROFILES) != {"TRACKER", "V3"}:
            raise RuntimeError("Hardwareprofile sind unvollständig")
        if current_ina_state("0 | BATTERY | ina=OFF\\n1 | INA226 | READY addr=0x44") != "ACTIVE":
            raise RuntimeError("INA226-Zustandslogik ist fehlerhaft")
'''
        if source.count(selftest_anchor) != 1:
            raise SystemExit("self-test anchor not found exactly once")
        source = source.replace(selftest_anchor, extra, 1)

    required = (
        f'APP_VERSION = "{APP_VERSION}"',
        'APP_CHANNEL = "shared"',
        "HARDWARE_PROFILES =",
        "def current_ina_state(",
        "def enrich_power_metrics(",
        "def power_window_summary(",
        "def add_power_analysis_cards(",
        "self.app_version_label",
        'text="App neu starten"',
        "def restart_app(self)",
        "def choose_hardware_dialog(",
        '"OTA-Gerätetyp auswählen"',
        "def start_serial_update(self)",
        "def _serial_update_worker(",
        "esptool.main(args)",
        'text="Firmware + OTA-Loader über USB aktualisieren"',
        'elif kind == "serial_update_result":',
    )
    for marker in required:
        if marker not in source:
            raise SystemExit(f"missing patched source marker: {marker}")
    return source


def main() -> None:
    target = Path(sys.argv[1] if len(sys.argv) > 1 else "tools/JARNSEN_NODE_SERVICE_TOOL.py")
    source = target.read_text(encoding="utf-8")
    build_sha = os.environ.get("APP_BUILD_SHA", "unknown")
    target.write_text(patch(source, build_sha), encoding="utf-8")
    print(f"Service tool patched to v{APP_VERSION}: shared build, power analytics, OTA recovery and serial updater")


if __name__ == "__main__":
    main()
