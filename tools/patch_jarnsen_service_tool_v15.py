"""v1.5 additions for the shared Jarnsen Node Service Tool.

Adds self-update, diagnostic bundles, enhanced serial monitoring/live power,
firmware comparison, recovery guidance, generic hardware profiles,
configuration snapshots, anomaly detection and user-selectable UI zoom.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

APP_VERSION = "1.5.0"


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
    source = source.replace('APP_VERSION != "1.4.0"', 'APP_VERSION != "1.5.0"')
    source = source.replace('App-Version ist nicht v1.4.0', 'App-Version ist nicht v1.5.0')

    if "import zipfile\n" not in source:
        anchor = "import urllib.request\nimport zlib\n"
        if source.count(anchor) != 1:
            raise SystemExit("zipfile import anchor not found")
        source = source.replace(anchor, "import urllib.request\nimport zipfile\nimport zlib\n", 1)

    # Turn hardware selection into a real profile layer. Future boards only
    # need one profile entry plus release/manifest data.
    profile_old = '''HARDWARE_PROFILES = {
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
    profile_new = '''HARDWARE_PROFILES = {
    "TRACKER": {
        "label": "Tracker V1.1",
        "device": "HELTEC_TRACKER_V1.1",
        "release": "jarnsen-tracker-latest",
        "chip": "esp32s3",
        "firmware_offset": "0x10000",
        "ota_loader_offset": "0x340000",
        "boot_select_offset": "0xE000",
        "boot_select_size": "0x2000",
        "power_provider": "INA226",
        "supports_ble_ota": True,
        "supports_serial_flash": True,
    },
    "V3": {
        "label": "Heltec V3",
        "device": "HELTEC_V3_REPEATER",
        "release": "jarnsen-v3-latest",
        "chip": "esp32s3",
        "firmware_offset": "0x10000",
        "ota_loader_offset": "0x340000",
        "boot_select_offset": "0xE000",
        "boot_select_size": "0x2000",
        "power_provider": "INA226/INTERNAL",
        "supports_ble_ota": True,
        "supports_serial_flash": True,
    },
}
'''
    if profile_old in source:
        source = source.replace(profile_old, profile_new, 1)
    elif '"firmware_offset": "0x10000"' not in source:
        raise SystemExit("hardware profile anchor not found")

    # Cross-log analytics: firmware A/B comparison and conservative anomaly
    # detection based on the node's own history instead of fixed device limits.
    if "def firmware_change_summary(" not in source:
        insert_at = source.find("\ndef add_power_analysis_cards(")
        if insert_at < 0:
            raise SystemExit("power card helper anchor not found")
        helpers = r'''


def firmware_change_summary(logs: list[dict[str, object]]) -> dict[str, object] | None:
    if len(logs) < 2:
        return None
    ordered = sorted(logs, key=lambda item: str(item.get("captured_at") or ""))
    current = ordered[-1]
    current_build = str(current.get("build") or "")
    previous = None
    for candidate in reversed(ordered[:-1]):
        if str(candidate.get("build") or "") != current_build:
            previous = candidate
            break
    if previous is None:
        return None
    window = power_window_summary([previous, current], None)
    previous_metrics = previous.get("metrics") if isinstance(previous.get("metrics"), dict) else {}
    current_metrics = current.get("metrics") if isinstance(current.get("metrics"), dict) else {}
    return {
        "from_build": str(previous.get("build") or "--")[:8],
        "to_build": current_build[:8] or "--",
        "from_firmware": str(previous.get("firmware") or "--"),
        "to_firmware": str(current.get("firmware") or "--"),
        "avg_ma": window.get("avg_ma") if window else None,
        "mah_per_day": window.get("mah_per_day") if window else None,
        "battery_delta": (
            float(current_metrics.get("battery_pct")) - float(previous_metrics.get("battery_pct"))
            if isinstance(current_metrics.get("battery_pct"), (int, float))
            and isinstance(previous_metrics.get("battery_pct"), (int, float))
            else None
        ),
    }


def anomaly_summary(logs: list[dict[str, object]]) -> list[str]:
    if len(logs) < 3:
        return []
    day = power_window_summary(logs, 24.0)
    week = power_window_summary(logs, 168.0)
    all_time = power_window_summary(logs, None)
    findings: list[str] = []
    if day and week and isinstance(day.get("avg_ma"), (int, float)) and isinstance(week.get("avg_ma"), (int, float)):
        current = float(day["avg_ma"])
        baseline = float(week["avg_ma"])
        if baseline > 0 and current > baseline * 1.25 and current - baseline >= 3.0:
            findings.append(f"24-h-Verbrauch +{(current / baseline - 1.0) * 100:.0f} % gegenüber 7-Tage-Niveau")
        elif baseline > 0 and current < baseline * 0.75:
            findings.append(f"24-h-Verbrauch {(1.0 - current / baseline) * 100:.0f} % unter 7-Tage-Niveau")
    if day and all_time:
        day_shares = day.get("shares") or {}
        all_shares = all_time.get("shares") or {}
        if isinstance(day_shares, dict) and isinstance(all_shares, dict):
            for key in ("GPS", "BLE", "Display"):
                current = day_shares.get(key)
                baseline = all_shares.get(key)
                if isinstance(current, (int, float)) and isinstance(baseline, (int, float)) and current > baseline + 5.0 and current > baseline * 1.5:
                    findings.append(f"{key}-Laufzeit ungewöhnlich hoch: {current:.1f} % statt {baseline:.1f} % Verlauf")
    capacities = []
    for item in logs[:-1]:
        metrics = item.get("metrics")
        value = metrics.get("capacity") if isinstance(metrics, dict) else None
        if isinstance(value, (int, float)) and value > 0:
            capacities.append(float(value))
    latest_metrics = logs[-1].get("metrics") if isinstance(logs[-1].get("metrics"), dict) else {}
    latest_capacity = latest_metrics.get("capacity")
    if capacities and isinstance(latest_capacity, (int, float)) and latest_capacity > 0:
        baseline = sum(capacities[-5:]) / len(capacities[-5:])
        if baseline > 0 and float(latest_capacity) < baseline * 0.90:
            findings.append(f"Gelernte Akkukapazität liegt {(1.0 - float(latest_capacity) / baseline) * 100:.0f} % unter den letzten Lernwerten")
    return findings[:5]


def add_v15_analysis_cards(cards: dict[str, object], logs: list[dict[str, object]]) -> dict[str, object]:
    comparison = firmware_change_summary(logs)
    if comparison:
        lines = [
            f"{comparison['from_build']} → {comparison['to_build']}",
            f"Firmware {comparison['from_firmware']} → {comparison['to_firmware']}",
        ]
        if isinstance(comparison.get("avg_ma"), (int, float)):
            lines.append(f"Ø seit Wechsel {float(comparison['avg_ma']):.1f} mA · {float(comparison['mah_per_day']):.0f} mAh/Tag")
        cards["firmware_vergleich"] = {
            "title": "Vorher / Nachher Firmware",
            "lines": lines,
            "level": "accent",
        }
    anomalies = anomaly_summary(logs)
    cards["anomalien"] = {
        "title": "Keine Auffälligkeiten" if not anomalies else f"{len(anomalies)} Auffälligkeit(en)",
        "lines": anomalies or ["Verbrauch und Laufzeiten liegen im eigenen bisherigen Bereich."],
        "level": "success" if not anomalies else "warning",
    }
    return cards
'''
        source = source[:insert_at] + helpers + source[insert_at:]

    dashboard_anchor = '''            cards = add_power_analysis_cards(cards, power_logs, self.last_payload)
            cards = {"softwarestand": firmware_card, **cards}
'''
    if "cards = add_v15_analysis_cards(cards, power_logs)" not in source:
        dashboard_new = '''            cards = add_power_analysis_cards(cards, power_logs, self.last_payload)
            cards = add_v15_analysis_cards(cards, power_logs)
            cards = {"softwarestand": firmware_card, **cards}
'''
        if source.count(dashboard_anchor) != 1:
            raise SystemExit("v1.5 dashboard anchor not found")
        source = source.replace(dashboard_anchor, dashboard_new, 1)

    # Runtime state.
    state_anchor = '''        self.serial_monitor_bytes = 0
        self.style = ttk.Style(self)
'''
    if "self.app_update_manifest" not in source:
        state_new = '''        self.serial_monitor_bytes = 0
        self.serial_display_paused = False
        self.serial_pending_text = ""
        self.serial_power_samples: list[tuple[float, float | None, float | None, float | None]] = []
        self.serial_markers: list[str] = []
        self.app_update_manifest: dict[str, object] = {}
        self.app_update_url = ""
        self.app_update_available = False
        self.base_tk_scaling = float(self.tk.call("tk", "scaling"))
        self.settings_path = output_directory() / "Jarnsen_Node_Service_Settings.json"
        self.style = ttk.Style(self)
'''
        if source.count(state_anchor) != 1:
            raise SystemExit("v1.5 runtime state anchor not found")
        source = source.replace(state_anchor, state_new, 1)

    start_checks_anchor = '''        self.after(800, self.refresh_firmware_status)
'''
    if "self.after(1600, self.check_app_update)" not in source:
        if source.count(start_checks_anchor) != 1:
            raise SystemExit("startup check anchor not found")
        source = source.replace(
            start_checks_anchor,
            start_checks_anchor + '        self.after(1600, self.check_app_update)\n',
            1,
        )

    # Title-row controls: update state + manual UI zoom.
    restart_anchor = '''        self.restart_button.pack(side="right", padx=(8, 8))'''
    if "self.app_update_button" not in source:
        title_extra = '''        self.restart_button.pack(side="right", padx=(8, 8))
        self.app_update_button = ttk.Button(
            title_row,
            text="App-Update prüfen",
            command=lambda: self.check_app_update(interactive=True),
        )
        self.app_update_button.pack(side="right", padx=(8, 0))
        self.ui_zoom = ttk.Combobox(
            title_row,
            state="readonly",
            values=("80 %", "90 %", "100 %", "110 %", "125 %"),
            width=7,
        )
        self.ui_zoom.set("100 %")
        self.ui_zoom.pack(side="right", padx=(8, 0))
        self.ui_zoom.bind("<<ComboboxSelected>>", lambda _event: self.apply_ui_zoom())
        ttk.Label(title_row, text="Zoom").pack(side="right", padx=(8, 0))'''
        if source.count(restart_anchor) != 1:
            raise SystemExit("title controls anchor not found")
        source = source.replace(restart_anchor, title_extra, 1)

    # Service actions in the scrollable left column.
    setup_anchor = '''        setup = ttk.LabelFrame(controls, text="USB / seriell", padding=6)
'''
    if "text=\"Diagnosepaket erstellen\"" not in source:
        service_ui = '''        service = ttk.LabelFrame(controls, text="Service / Recovery", padding=6)
        service.pack(fill="x", pady=(0, 6))
        ttk.Button(
            service, text="Diagnosepaket erstellen", command=self.create_diagnostic_bundle
        ).pack(fill="x")
        ttk.Button(
            service, text="Recovery-Assistent", command=self.open_recovery_assistant,
            style="Primary.TButton",
        ).pack(fill="x", pady=(6, 0))
        ttk.Button(
            service, text="Konfig-Snapshot sichern", command=self.save_config_snapshot
        ).pack(fill="x", pady=(6, 0))

        setup = ttk.LabelFrame(controls, text="USB / seriell", padding=6)
'''
        if source.count(setup_anchor) != 1:
            raise SystemExit("service UI anchor not found")
        source = source.replace(setup_anchor, service_ui, 1)

    # Serial filter/search/pause/live-power panel.
    serial_status_anchor = '''        self.serial_monitor_status.pack(side="left", fill="x", expand=True)

        serial_text_frame = ttk.Frame(self.serial_tab)
'''
    if "self.serial_filter" not in source:
        serial_extra = '''        self.serial_monitor_status.pack(side="left", fill="x", expand=True)

        serial_tools = ttk.Frame(self.serial_tab)
        serial_tools.pack(fill="x", pady=(0, 6))
        ttk.Label(serial_tools, text="Filter").pack(side="left")
        self.serial_filter = ttk.Entry(serial_tools, width=22)
        self.serial_filter.pack(side="left", padx=(5, 8))
        ttk.Label(serial_tools, text="Suche").pack(side="left")
        self.serial_search = ttk.Entry(serial_tools, width=20)
        self.serial_search.pack(side="left", padx=(5, 5))
        ttk.Button(serial_tools, text="Nächstes", command=self.find_next_serial_text).pack(side="left")
        self.serial_pause_button = ttk.Button(
            serial_tools, text="Anzeige pausieren", command=self.toggle_serial_display_pause
        )
        self.serial_pause_button.pack(side="right")
        ttk.Button(serial_tools, text="Marker", command=self.add_serial_marker).pack(side="right", padx=(0, 6))

        power_row = ttk.LabelFrame(self.serial_tab, text="Live Power", padding=6)
        power_row.pack(fill="x", pady=(0, 6))
        self.serial_power_label = ttk.Label(
            power_row,
            text="Noch keine INA/BATTERY-Messwerte empfangen",
            style="Status.TLabel",
        )
        self.serial_power_label.pack(side="left", fill="x", expand=True)
        self.serial_power_canvas = tk.Canvas(power_row, height=58, width=360, highlightthickness=0)
        self.serial_power_canvas.pack(side="right", fill="x", expand=False)

        serial_text_frame = ttk.Frame(self.serial_tab)
'''
        if source.count(serial_status_anchor) != 1:
            raise SystemExit("serial tools anchor not found")
        source = source.replace(serial_status_anchor, serial_extra, 1)

    # Right-click in serial text creates a timestamped marker.
    text_pack_anchor = '''        self.serial_monitor_text.pack(side="left", fill="both", expand=True)
'''
    if 'self.serial_monitor_text.bind("<Button-3>"' not in source:
        source = source.replace(
            text_pack_anchor,
            text_pack_anchor + '        self.serial_monitor_text.bind("<Button-3>", lambda _event: self.add_serial_marker())\n',
            1,
        )

    # Theme tag colors and power chart background.
    theme_anchor = '''            self.serial_monitor_text.configure(
                background=palette["panel_alt"],
                foreground=fg,
                insertbackground=fg,
                selectbackground=accent,
                font=(palette["mono"], 9),
            )
'''
    if 'tag_configure("serial_error"' not in source:
        theme_new = theme_anchor + '''            self.serial_monitor_text.tag_configure("serial_error", foreground=palette["error"])
            self.serial_monitor_text.tag_configure("serial_warn", foreground=palette["warning"])
            self.serial_monitor_text.tag_configure("serial_marker", foreground=palette["accent"])
            self.serial_monitor_text.tag_configure("serial_tx", foreground=palette["success"])
            if hasattr(self, "serial_power_canvas"):
                self.serial_power_canvas.configure(background=palette["panel_alt"])
'''
        if source.count(theme_anchor) != 1:
            raise SystemExit("serial theme tag anchor not found")
        source = source.replace(theme_anchor, theme_new, 1)

    # Generic serial flash offsets from the profile rather than hard-coded board
    # assumptions.
    serial_worker_start, serial_worker_end = method_span(source, "_serial_update_worker")
    serial_worker = source[serial_worker_start:serial_worker_end]
    if 'chip = str(profile.get("chip")' not in serial_worker:
        serial_worker = serial_worker.replace(
            '''            profile = HARDWARE_PROFILES[device_code]
            self.events.put(("status", f"{profile['label']}: Firmware von GitHub laden ..."))
''',
            '''            profile = HARDWARE_PROFILES[device_code]
            chip = str(profile.get("chip") or "esp32s3")
            firmware_offset = str(profile.get("firmware_offset") or "0x10000")
            ota_loader_offset = str(profile.get("ota_loader_offset") or "0x340000")
            boot_select_offset = str(profile.get("boot_select_offset") or "0xE000")
            boot_select_size = str(profile.get("boot_select_size") or "0x2000")
            self.events.put(("status", f"{profile['label']}: Firmware von GitHub laden ..."))
''',
            1,
        )
        serial_worker = serial_worker.replace('["--chip", "esp32s3", "--port", port, "chip-id"]', '["--chip", chip, "--port", port, "chip-id"]')
        serial_worker = serial_worker.replace('"--chip", "esp32s3", "--port", port, "--baud", "460800",', '"--chip", chip, "--port", port, "--baud", "460800",')
        serial_worker = serial_worker.replace('"0x10000", str(firmware_path), "0x340000", str(loader_path),', 'firmware_offset, str(firmware_path), ota_loader_offset, str(loader_path),')
        serial_worker = serial_worker.replace('"--chip", "esp32s3", "--port", port,', '"--chip", chip, "--port", port,')
        serial_worker = serial_worker.replace('"erase-region", "0xE000", "0x2000",', '"erase-region", boot_select_offset, boot_select_size,')
        serial_worker = serial_worker.replace('"Hauptfirmware: 0x10000 · OTA-Loader: 0x340000 · Bootwahl zurückgesetzt.",', 'f"Hauptfirmware: {firmware_offset} · OTA-Loader: {ota_loader_offset} · Bootwahl zurückgesetzt.",')
        source = source[:serial_worker_start] + serial_worker + source[serial_worker_end:]

    # New service/update/serial helper methods.
    if "    def check_app_update(self" not in source:
        methods = r'''    @staticmethod
    def _version_tuple(value: str) -> tuple[int, ...]:
        return tuple(int(part) for part in re.findall(r"\d+", value)[:4]) or (0,)

    def check_app_update(self, interactive: bool = False) -> None:
        if getattr(self, "app_update_button", None):
            self.app_update_button.configure(text="App-Update wird geprüft …", state="disabled")
        threading.Thread(target=self._check_app_update_worker, args=(interactive,), daemon=True).start()

    def _check_app_update_worker(self, interactive: bool) -> None:
        try:
            release_url = f"https://api.github.com/repos/{GITHUB_REPOSITORY}/releases/tags/jarnsen-service-tool-latest"
            request = urllib.request.Request(release_url, headers={"User-Agent": "Jarnsen-Node-Service-Tool"})
            with contextlib.closing(urllib.request.urlopen(request, timeout=20)) as response:  # nosec B310  # nosemgrep
                release = json.load(response)
            assets = {
                str(asset.get("name") or ""): str(asset.get("browser_download_url") or "")
                for asset in release.get("assets", []) if isinstance(asset, dict)
            }
            manifest_url = assets.get("jarnsen-node-service-tool.json", "")
            executable_url = assets.get("Jarnsen-Node-Service-Tool.exe", "")
            if not manifest_url or not executable_url:
                raise RuntimeError("Shared-App-Release ist unvollständig")
            manifest_request = urllib.request.Request(manifest_url, headers={"User-Agent": "Jarnsen-Node-Service-Tool"})
            with contextlib.closing(urllib.request.urlopen(manifest_request, timeout=20)) as response:  # nosec B310  # nosemgrep
                manifest = json.load(response)
            if not isinstance(manifest, dict) or int(manifest.get("schema", 0)) != 1:
                raise RuntimeError("App-Manifest ist ungültig")
            remote = str(manifest.get("version") or "0")
            available = self._version_tuple(remote) > self._version_tuple(APP_VERSION)
            self.events.put(("app_update_status", (available, manifest, executable_url, interactive)))
        except Exception as exc:
            self.events.put(("app_update_error", (str(exc), interactive)))

    def install_app_update(self) -> None:
        if not self.app_update_available or not self.app_update_url or not self.app_update_manifest:
            self.check_app_update(interactive=True)
            return
        if not getattr(sys, "frozen", False):
            messagebox.showinfo("App-Update", "Selbstupdate ist nur in der gepackten EXE aktiv.")
            return
        remote = str(self.app_update_manifest.get("version") or "--")
        if not messagebox.askyesno("App-Update", f"Jarnsen Node Service Tool auf v{remote} aktualisieren und neu starten?"):
            return
        threading.Thread(target=self._install_app_update_worker, daemon=True).start()

    def _install_app_update_worker(self) -> None:
        try:
            current = pathlib.Path(sys.executable).resolve()
            new_path = current.with_suffix(".new.exe")
            request = urllib.request.Request(self.app_update_url, headers={"User-Agent": "Jarnsen-Node-Service-Tool"})
            with contextlib.closing(urllib.request.urlopen(request, timeout=120)) as response:  # nosec B310  # nosemgrep
                data = response.read(80 * 1024 * 1024)
            expected_size = int(self.app_update_manifest.get("executable_size") or 0)
            expected_hash = str(self.app_update_manifest.get("executable_sha256") or "").lower()
            if not data or (expected_size and len(data) != expected_size):
                raise RuntimeError("Heruntergeladene App-Größe stimmt nicht mit dem Manifest überein")
            if not re.fullmatch(r"[0-9a-f]{64}", expected_hash) or hashlib.sha256(data).hexdigest() != expected_hash:
                raise RuntimeError("SHA-256-Prüfung des App-Updates fehlgeschlagen")
            new_path.write_bytes(data)
            script = pathlib.Path(tempfile.gettempdir()) / "jarnsen-node-service-update.cmd"
            script.write_text(
                "@echo off\r\n"
                "setlocal\r\n"
                "timeout /t 2 /nobreak >nul\r\n"
                f':retry\r\ncopy /y "{new_path}" "{current}" >nul 2>&1\r\n'
                "if errorlevel 1 (timeout /t 1 /nobreak >nul & goto retry)\r\n"
                f'del /q "{new_path}" >nul 2>&1\r\nstart "" "{current}"\r\n'
                "del /q \"%~f0\"\r\n",
                encoding="utf-8",
            )
            self.events.put(("app_update_ready", str(script)))
        except Exception as exc:
            self.events.put(("app_update_error", (str(exc), True)))

    def apply_ui_zoom(self) -> None:
        match = re.search(r"\d+", self.ui_zoom.get() if hasattr(self, "ui_zoom") else "100")
        percent = int(match.group(0)) if match else 100
        percent = max(70, min(140, percent))
        self.tk.call("tk", "scaling", self.base_tk_scaling * percent / 100.0)
        self.apply_theme()
        try:
            settings = {"ui_zoom_percent": percent, "theme": self.theme.get()}
            self.settings_path.write_text(json.dumps(settings, indent=2), encoding="utf-8")
        except OSError:
            pass

    def _config_snapshot_data(self) -> dict[str, object]:
        node_id = self.selected_node_id
        latest = self.repository.latest_log(node_id) if node_id else None
        data: dict[str, object] = {
            "schema": 1,
            "scope": "diagnostic-log-derived",
            "note": "Kein vollständiger Meshtastic-Konfigurationsdump; enthält die im Diagnose-Log sichtbaren Einstellungen.",
            "created_at": now_local().isoformat(timespec="seconds"),
            "app_version": APP_VERSION,
            "app_build": APP_BUILD,
            "node_id": node_id,
            "settings_lines": [],
        }
        if latest:
            path = pathlib.Path(str(latest.get("path") or ""))
            data["latest_log"] = str(path)
            data["firmware"] = str(latest.get("firmware") or "")
            data["build"] = str(latest.get("build") or "")
            data["metrics"] = latest.get("metrics") if isinstance(latest.get("metrics"), dict) else {}
            if path.exists():
                text = path.read_text(encoding="utf-8", errors="replace")
                selected = []
                for line in text.splitlines():
                    upper = line.upper()
                    if any(token in upper for token in (" SETTINGS:", " SETTING ", "CONFIG=", "HARDWARE |", "ANT_BOOT", "POWER | MONITOR INITIALIZED")):
                        selected.append(line)
                data["settings_lines"] = selected[-200:]
        return data

    def _auto_config_snapshot(self, reason: str) -> pathlib.Path | None:
        if not self.selected_node_id:
            return None
        target = output_directory() / f"Config_Snapshot_{safe_filename(self.selected_node_id)}_{safe_filename(reason)}_{now_local():%Y-%m-%d_%H%M%S}.json"
        try:
            target.write_text(json.dumps(self._config_snapshot_data(), ensure_ascii=False, indent=2), encoding="utf-8")
            return target
        except OSError:
            return None

    def save_config_snapshot(self) -> None:
        if not self.selected_node_id:
            messagebox.showinfo("Konfig-Snapshot", "Bitte zuerst links eine Node auswählen.")
            return
        target = self._auto_config_snapshot("manual")
        if target:
            messagebox.showinfo("Konfig-Snapshot", f"Snapshot gespeichert:\n{target}\n\nHinweis: Das ist ein Diagnose-Log-Snapshot, kein vollständiger Meshtastic-Konfigurationsdump.")
        else:
            messagebox.showerror("Konfig-Snapshot", "Snapshot konnte nicht gespeichert werden.")

    def create_diagnostic_bundle(self) -> None:
        target = output_directory() / f"Jarnsen_Diagnosepaket_{now_local():%Y-%m-%d_%H%M%S}.zip"
        try:
            app_info = {
                "app_version": APP_VERSION,
                "app_build": APP_BUILD,
                "app_channel": APP_CHANNEL,
                "created_at": now_local().isoformat(timespec="seconds"),
                "selected_node": self.selected_node_id,
                "ports": list(self.port_map),
                "hardware_profiles": HARDWARE_PROFILES,
            }
            with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                archive.writestr("app-info.json", json.dumps(app_info, ensure_ascii=False, indent=2))
                archive.writestr("config-snapshot.json", json.dumps(self._config_snapshot_data(), ensure_ascii=False, indent=2))
                if self.selected_node_id:
                    logs = self.repository.logs_for_node(self.selected_node_id)
                    for index, item in enumerate(logs[-5:], start=1):
                        path = pathlib.Path(str(item.get("path") or ""))
                        if path.exists():
                            archive.write(path, f"node-logs/{index:02d}-{path.name}")
                if self.serial_monitor_log_path and self.serial_monitor_log_path.exists():
                    archive.write(self.serial_monitor_log_path, f"serial/{self.serial_monitor_log_path.name}")
                if self.firmware_cache_path.exists():
                    archive.write(self.firmware_cache_path, "app/Jarnsen_Firmware_Status.json")
                if self.settings_path.exists():
                    archive.write(self.settings_path, "app/Jarnsen_Node_Service_Settings.json")
            messagebox.showinfo("Diagnosepaket", f"Diagnosepaket erstellt:\n{target}")
        except Exception as exc:
            messagebox.showerror("Diagnosepaket", str(exc))

    def open_recovery_assistant(self) -> None:
        dialog = tk.Toplevel(self)
        dialog.title("Jarnsen Recovery-Assistent")
        dialog.transient(self)
        dialog.grab_set()
        frame = ttk.Frame(dialog, padding=16)
        frame.pack(fill="both", expand=True)
        selected_ble = self.selected_ble_devices()
        ota_waiting = any(label.startswith("[OTA]") for label, _device in selected_ble)
        port = self.selected_port()
        recommendation = (
            "OTA-Loader erkannt: Bluetooth-Recovery ist der erste Versuch."
            if ota_waiting
            else ("USB-Port gewählt: USB-Recovery ist der zuverlässigste Weg." if port else "Bitte BLE-Node oder USB-Port auswählen.")
        )
        ttk.Label(frame, text=recommendation, wraplength=480, justify="left").pack(anchor="w", pady=(0, 12))
        ttk.Label(frame, text="Der Assistent löscht standardmäßig weder NVS noch Diagnose-Logs.", style="Subtitle.TLabel").pack(anchor="w", pady=(0, 12))
        buttons = ttk.Frame(frame)
        buttons.pack(fill="x")

        def run_ble() -> None:
            dialog.destroy()
            self.start_ble_update()

        def run_usb() -> None:
            dialog.destroy()
            self.start_serial_update()

        ttk.Button(buttons, text="Bluetooth-Recovery", command=run_ble, style="Primary.TButton").pack(fill="x")
        ttk.Button(buttons, text="USB-Recovery", command=run_usb, style="Primary.TButton").pack(fill="x", pady=(6, 0))
        ttk.Button(buttons, text="Abbrechen", command=dialog.destroy).pack(fill="x", pady=(6, 0))
        self.wait_window(dialog)

    def toggle_serial_display_pause(self) -> None:
        self.serial_display_paused = not self.serial_display_paused
        self.serial_pause_button.configure(text="Anzeige fortsetzen" if self.serial_display_paused else "Anzeige pausieren")
        self.serial_monitor_status.configure(
            text="Anzeige pausiert · Aufzeichnung läuft weiter" if self.serial_display_paused else "Anzeige aktiv"
        )

    def find_next_serial_text(self) -> None:
        needle = self.serial_search.get().strip()
        if not needle:
            return
        start = self.serial_monitor_text.index("insert +1c")
        found = self.serial_monitor_text.search(needle, start, stopindex="end", nocase=True)
        if not found:
            found = self.serial_monitor_text.search(needle, "1.0", stopindex="end", nocase=True)
        if found:
            end = f"{found}+{len(needle)}c"
            self.serial_monitor_text.tag_remove("sel", "1.0", "end")
            self.serial_monitor_text.tag_add("sel", found, end)
            self.serial_monitor_text.mark_set("insert", end)
            self.serial_monitor_text.see(found)

    def add_serial_marker(self) -> None:
        stamp = now_local().isoformat(timespec="seconds")
        marker = f"[MARKER {stamp}]"
        self.serial_markers.append(marker)
        self.serial_monitor_text.insert("end", marker + "\n", "serial_marker")
        self.serial_monitor_text.see("end")
        if self.serial_monitor_log_path:
            sidecar = self.serial_monitor_log_path.with_suffix(self.serial_monitor_log_path.suffix + ".markers.txt")
            try:
                with sidecar.open("a", encoding="utf-8") as handle:
                    handle.write(marker + "\n")
            except OSError:
                pass

    def _append_serial_line(self, line: str) -> None:
        if self.serial_display_paused:
            return
        filter_value = self.serial_filter.get().strip().lower() if hasattr(self, "serial_filter") else ""
        if filter_value and filter_value not in line.lower():
            return
        upper = line.upper()
        tag = ""
        if any(token in upper for token in ("GURU MEDITATION", "ERROR", "FAILED", "PANIC", "EXCEPTION")):
            tag = "serial_error"
        elif any(token in upper for token in ("WARN", "MISSING", "NACK", "TIMEOUT")):
            tag = "serial_warn"
        self.serial_monitor_text.insert("end", line + "\n", tag)

    def _parse_serial_power(self, text_value: str) -> None:
        combined = self.serial_pending_text + text_value
        lines = combined.splitlines(keepends=True)
        if lines and not lines[-1].endswith(("\n", "\r")):
            self.serial_pending_text = lines.pop()
        else:
            self.serial_pending_text = ""
        for raw in lines:
            line = raw.rstrip("\r\n")
            self._append_serial_line(line)
            voltage = current = power = None
            sample = re.search(r"INA226:\s*SAMPLE[^\r\n]*bus=(\d+)mV[^\r\n]*current=(-?\d+(?:\.\d+)?)mA(?:[^\r\n]*power=(\d+(?:\.\d+)?)mW)?", line, re.IGNORECASE)
            if sample:
                voltage = float(sample.group(1)) / 1000.0
                current = float(sample.group(2))
                power = float(sample.group(3)) if sample.group(3) else None
            elif "BATTERY" in line.upper():
                vm = re.search(r"(?:^|\s)(\d+)mV(?:\s|$)", line)
                cm = re.search(r"(?:^|\s)current=(-?\d+(?:\.\d+)?)mA", line, re.IGNORECASE)
                pm = re.search(r"(?:^|\s)power=(\d+(?:\.\d+)?)mW", line, re.IGNORECASE)
                voltage = float(vm.group(1)) / 1000.0 if vm else None
                current = float(cm.group(1)) if cm else None
                power = float(pm.group(1)) if pm else None
            if current is not None or voltage is not None or power is not None:
                self.serial_power_samples.append((time.time(), voltage, current, power))
                self.serial_power_samples = self.serial_power_samples[-240:]
        self.render_serial_power()

    def render_serial_power(self) -> None:
        if not self.serial_power_samples:
            return
        _stamp, voltage, current, power = self.serial_power_samples[-1]
        currents = [sample[2] for sample in self.serial_power_samples if isinstance(sample[2], (int, float))]
        avg_current = sum(currents) / len(currents) if currents else None
        parts = []
        if voltage is not None:
            parts.append(f"{voltage:.3f} V")
        if current is not None:
            parts.append(f"{current:.1f} mA")
        if power is not None:
            parts.append(f"{power:.1f} mW")
        if avg_current is not None:
            parts.append(f"Ø Session {avg_current:.1f} mA")
        self.serial_power_label.configure(text=" · ".join(parts) or "Power-Daten empfangen")
        canvas = self.serial_power_canvas
        canvas.delete("all")
        values = currents[-120:]
        if len(values) < 2:
            return
        width = max(100, canvas.winfo_width())
        height = max(40, canvas.winfo_height())
        low, high = min(values), max(values)
        span = max(1.0, high - low)
        points = []
        for index, value in enumerate(values):
            x = 3 + index * (width - 6) / max(1, len(values) - 1)
            y = height - 3 - (value - low) * (height - 6) / span
            points.extend((x, y))
        canvas.create_line(*points, width=2)
        canvas.create_text(5, 5, anchor="nw", text=f"{low:.1f}…{high:.1f} mA")

    def handle_serial_monitor_data(self, text_value: str, byte_count: int) -> None:
        self._parse_serial_power(text_value)
        try:
            lines = int(self.serial_monitor_text.index("end-1c").split(".")[0])
            if lines > 12000:
                self.serial_monitor_text.delete("1.0", "2000.0")
        except (ValueError, tk.TclError):
            pass
        if self.serial_auto_scroll_var.get() and not self.serial_display_paused:
            self.serial_monitor_text.see("end")
        size_kb = int(byte_count) / 1024.0
        name = self.serial_monitor_log_path.name if self.serial_monitor_log_path else "--"
        suffix = " · Anzeige pausiert" if self.serial_display_paused else ""
        self.serial_monitor_status.configure(text=f"Aufzeichnung {size_kb:.1f} KiB · {name}{suffix}")
'''
        source = insert_before_method(source, "serial_monitor_active", methods)

    # Route monitor events through the enhanced filter/power parser.
    event_pattern = re.compile(
        r'''                elif kind == "serial_monitor_data":\n.*?(?=                elif kind == "serial_monitor_tx":\n)''',
        re.DOTALL,
    )
    if "self.handle_serial_monitor_data(str(text_value), int(byte_count))" not in source:
        replacement = '''                elif kind == "serial_monitor_data":
                    text_value, byte_count = value
                    self.handle_serial_monitor_data(str(text_value), int(byte_count))
'''
        source, count = event_pattern.subn(replacement, source, count=1)
        if count != 1:
            raise SystemExit("serial monitor event replacement failed")

    # Automatic config snapshots before firmware writes.
    serial_start, serial_end = method_span(source, "start_serial_update")
    serial_start_block = source[serial_start:serial_end]
    if '_auto_config_snapshot("before-usb-update")' not in serial_start_block:
        marker = '''        profile = HARDWARE_PROFILES[device_code]
'''
        if marker not in serial_start_block:
            raise SystemExit("serial snapshot anchor not found")
        serial_start_block = serial_start_block.replace(marker, marker + '        self._auto_config_snapshot("before-usb-update")\n', 1)
        source = source[:serial_start] + serial_start_block + source[serial_end:]

    ble_start, ble_end = method_span(source, "start_ble_update")
    ble_block = source[ble_start:ble_end]
    if '_auto_config_snapshot("before-ble-update")' not in ble_block:
        marker = '''        if self.worker and self.worker.is_alive():
            return
'''
        if marker not in ble_block:
            raise SystemExit("BLE snapshot anchor not found")
        ble_block = ble_block.replace(marker, marker + '        self._auto_config_snapshot("before-ble-update")\n', 1)
        source = source[:ble_start] + ble_block + source[ble_end:]

    # App-update events.
    update_event_anchor = '                elif kind == "serial_monitor_started":\n'
    if 'elif kind == "app_update_status":' not in source:
        update_events = '''                elif kind == "app_update_status":
                    available, manifest, executable_url, interactive = value
                    self.app_update_manifest = dict(manifest)
                    self.app_update_url = str(executable_url)
                    self.app_update_available = bool(available)
                    remote = str(self.app_update_manifest.get("version") or "--")
                    if available:
                        self.app_update_button.configure(text=f"Update v{remote}", state="normal", command=self.install_app_update)
                        self.status_level = "warning"
                        self.status.configure(text=f"App-Update v{remote} verfügbar")
                        self._update_status_badge()
                        if interactive:
                            messagebox.showinfo("App-Update", f"Version {remote} ist verfügbar. Über den Update-Button kann sie SHA-256-geprüft installiert werden.")
                    else:
                        self.app_update_button.configure(text="App aktuell", state="normal", command=lambda: self.check_app_update(interactive=True))
                        if interactive:
                            messagebox.showinfo("App-Update", f"v{APP_VERSION} ist aktuell.")
                elif kind == "app_update_error":
                    error, interactive = value
                    self.app_update_button.configure(text="App-Update prüfen", state="normal", command=lambda: self.check_app_update(interactive=True))
                    if interactive:
                        messagebox.showwarning("App-Update", str(error))
                elif kind == "app_update_ready":
                    script = str(value)
                    self.serial_monitor_stop.set()
                    if self.serial_monitor_ser is not None:
                        with contextlib.suppress(Exception):
                            self.serial_monitor_ser.close()
                    subprocess.Popen(["cmd.exe", "/c", script], creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                    self.destroy()
'''
        if source.count(update_event_anchor) != 1:
            raise SystemExit("app update event anchor not found")
        source = source.replace(update_event_anchor, update_events + update_event_anchor, 1)

    # Extend self-test with all v1.5 features without opening Tk.
    selftest_anchor = '''        if APP_VERSION != "1.5.0":
            raise RuntimeError("App-Version ist nicht v1.5.0")
'''
    if '"create_diagnostic_bundle"' not in source[source.find("def packaged_self_test"):]:
        addition = selftest_anchor + '''        for method_name in (
            "check_app_update",
            "install_app_update",
            "create_diagnostic_bundle",
            "save_config_snapshot",
            "open_recovery_assistant",
            "apply_ui_zoom",
            "toggle_serial_display_pause",
            "find_next_serial_text",
            "add_serial_marker",
            "render_serial_power",
        ):
            if not hasattr(ServiceTool, method_name):
                raise RuntimeError(f"v1.5-Funktion fehlt: {method_name}")
        for profile in HARDWARE_PROFILES.values():
            for key in ("chip", "firmware_offset", "ota_loader_offset", "boot_select_offset", "boot_select_size"):
                if key not in profile:
                    raise RuntimeError(f"Hardwareprofil ohne {key}")
'''
        if source.count(selftest_anchor) != 1:
            raise SystemExit("v1.5 self-test anchor not found")
        source = source.replace(selftest_anchor, addition, 1)

    required = (
        'APP_VERSION = "1.5.0"',
        '"firmware_offset": "0x10000"',
        "def firmware_change_summary(",
        "def anomaly_summary(",
        "def check_app_update(self",
        "def create_diagnostic_bundle(self)",
        "def open_recovery_assistant(self)",
        "def apply_ui_zoom(self)",
        "self.serial_filter",
        "self.serial_power_canvas",
        "def handle_serial_monitor_data(self",
        'text="Diagnosepaket erstellen"',
        'text="Recovery-Assistent"',
        'text="Konfig-Snapshot sichern"',
        'elif kind == "app_update_status":',
    )
    for marker in required:
        if marker not in source:
            raise SystemExit(f"missing v1.5 marker: {marker}")
    return source


def main() -> None:
    target = Path(sys.argv[1] if len(sys.argv) > 1 else "tools/JARNSEN_NODE_SERVICE_TOOL.py")
    source = target.read_text(encoding="utf-8")
    target.write_text(patch(source), encoding="utf-8")
    print("Service tool patched to v1.5.0: self-update, diagnostics, recovery, live power and advanced serial tools")


if __name__ == "__main__":
    main()
