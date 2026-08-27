"""v2.1.19: serial mass provisioning, managed-node DB and USB auto-log."""
from __future__ import annotations

import re
import sys
from pathlib import Path

APP_VERSION = "2.1.19"


def method_span(text: str, name: str) -> tuple[int, int]:
    start = text.find(f"    def {name}(")
    if start < 0:
        raise SystemExit(f"method {name} not found")
    next_method = text.find("\n    def ", start + 1)
    next_decorator = text.find("\n    @", start + 1)
    candidates = [value for value in (next_method, next_decorator) if value >= 0]
    return start, min(candidates) if candidates else len(text)


def class_span(text: str, name: str) -> tuple[int, int]:
    start = text.find(f"class {name}:")
    if start < 0:
        raise SystemExit(f"class {name} not found")
    next_class = text.find("\nclass ", start + 1)
    return start, next_class if next_class >= 0 else len(text)


def insert_before_method(text: str, name: str, code: str) -> str:
    start, _ = method_span(text, name)
    return text[:start] + code.rstrip() + "\n\n" + text[start:]


def replace_method(text: str, name: str, replacement: str) -> str:
    start, end = method_span(text, name)
    return text[:start] + replacement.rstrip() + "\n" + text[end:]


def patch(source: str) -> str:
    source = re.sub(r'APP_VERSION = "[^"]+"', f'APP_VERSION = "{APP_VERSION}"', source, count=1)
    source = source.replace('APP_VERSION != "2.1.18"', 'APP_VERSION != "2.1.19"')
    source = source.replace("App-Version ist nicht v2.1.18", "App-Version ist nicht v2.1.19")

    repo_start, repo_end = class_span(source, "NodeRepository")
    repo = source[repo_start:repo_end]
    if "self._create_management_schema()" not in repo:
        anchor = "        self._create_schema()\n"
        if repo.count(anchor) != 1:
            raise SystemExit("v2.1.19 repository init anchor missing or ambiguous")
        repo = repo.replace(anchor, anchor + "        self._create_management_schema()\n", 1)

    if "    def _create_management_schema(self)" not in repo:
        marker = "    @staticmethod\n    def _captured_at("
        pos = repo.find(marker)
        if pos < 0:
            raise SystemExit("v2.1.19 repository method insertion anchor missing")
        methods = r'''    def _create_management_schema(self) -> None:
        with contextlib.closing(self._connect()) as connection, connection:
            connection.executescript("""
                CREATE TABLE IF NOT EXISTS managed_nodes (
                    node_id TEXT PRIMARY KEY,
                    profile_slot INTEGER,
                    profile_name TEXT NOT NULL DEFAULT '',
                    role TEXT NOT NULL DEFAULT '',
                    firmware TEXT NOT NULL DEFAULT '',
                    firmware_build TEXT NOT NULL DEFAULT '',
                    hardware TEXT NOT NULL DEFAULT '',
                    usb_identity TEXT NOT NULL DEFAULT '',
                    last_port TEXT NOT NULL DEFAULT '',
                    configured_at TEXT NOT NULL DEFAULT '',
                    last_seen TEXT NOT NULL DEFAULT '',
                    last_firmware_update TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT '',
                    ota_ready INTEGER NOT NULL DEFAULT 0
                );
                CREATE INDEX IF NOT EXISTS managed_nodes_usb ON managed_nodes(usb_identity);
                CREATE TABLE IF NOT EXISTS firmware_events (
                    id INTEGER PRIMARY KEY,
                    node_id TEXT NOT NULL DEFAULT '',
                    captured_at TEXT NOT NULL,
                    transport TEXT NOT NULL DEFAULT '',
                    transport_identity TEXT NOT NULL DEFAULT '',
                    firmware TEXT NOT NULL DEFAULT '',
                    firmware_build TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT '',
                    detail TEXT NOT NULL DEFAULT ''
                );
                CREATE INDEX IF NOT EXISTS firmware_events_node_time ON firmware_events(node_id, captured_at);
            """)

    def upsert_managed_node(
        self, node_id: str, long_name: str, short_name: str, hardware: str,
        role: str = "", firmware: str = "", firmware_build: str = "",
        profile_slot: int | None = None, profile_name: str = "",
        usb_identity: str = "", last_port: str = "", status: str = "Eingerichtet",
        ota_ready: bool | None = None, configured: bool = False,
    ) -> None:
        node_id = normalize_node_id(node_id)
        if not node_id:
            return
        now = now_local().isoformat(timespec="seconds")
        with contextlib.closing(self._connect()) as connection, connection:
            connection.execute(
                """INSERT INTO nodes(node_id,long_name,short_name,device,first_seen,last_seen)
                   VALUES(?,?,?,?,?,?)
                   ON CONFLICT(node_id) DO UPDATE SET
                     long_name=CASE WHEN excluded.long_name<>'' THEN excluded.long_name ELSE nodes.long_name END,
                     short_name=CASE WHEN excluded.short_name<>'' THEN excluded.short_name ELSE nodes.short_name END,
                     device=CASE WHEN excluded.device<>'' THEN excluded.device ELSE nodes.device END,
                     last_seen=excluded.last_seen""",
                (node_id, long_name or node_id, short_name, hardware, now, now),
            )
            connection.execute(
                """INSERT INTO managed_nodes(
                       node_id,profile_slot,profile_name,role,firmware,firmware_build,hardware,
                       usb_identity,last_port,configured_at,last_seen,last_firmware_update,status,ota_ready)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(node_id) DO UPDATE SET
                     profile_slot=COALESCE(excluded.profile_slot,managed_nodes.profile_slot),
                     profile_name=CASE WHEN excluded.profile_name<>'' THEN excluded.profile_name ELSE managed_nodes.profile_name END,
                     role=CASE WHEN excluded.role<>'' THEN excluded.role ELSE managed_nodes.role END,
                     firmware=CASE WHEN excluded.firmware<>'' THEN excluded.firmware ELSE managed_nodes.firmware END,
                     firmware_build=CASE WHEN excluded.firmware_build<>'' THEN excluded.firmware_build ELSE managed_nodes.firmware_build END,
                     hardware=CASE WHEN excluded.hardware<>'' THEN excluded.hardware ELSE managed_nodes.hardware END,
                     usb_identity=CASE WHEN excluded.usb_identity<>'' THEN excluded.usb_identity ELSE managed_nodes.usb_identity END,
                     last_port=CASE WHEN excluded.last_port<>'' THEN excluded.last_port ELSE managed_nodes.last_port END,
                     configured_at=CASE WHEN excluded.configured_at<>'' THEN excluded.configured_at ELSE managed_nodes.configured_at END,
                     last_seen=excluded.last_seen,
                     last_firmware_update=CASE WHEN excluded.last_firmware_update<>'' THEN excluded.last_firmware_update ELSE managed_nodes.last_firmware_update END,
                     status=CASE WHEN excluded.status<>'' THEN excluded.status ELSE managed_nodes.status END,
                     ota_ready=CASE WHEN ? < 0 THEN managed_nodes.ota_ready ELSE excluded.ota_ready END""",
                (
                    node_id, profile_slot, profile_name, role, firmware, firmware_build, hardware,
                    usb_identity, last_port, now if configured else "", now,
                    now if firmware_build else "", status,
                    int(bool(ota_ready)) if ota_ready is not None else 0,
                    -1 if ota_ready is None else int(bool(ota_ready)),
                ),
            )

    def management_for_node(self, node_id: str) -> dict[str, object] | None:
        with contextlib.closing(self._connect()) as connection, connection:
            row = connection.execute(
                "SELECT * FROM managed_nodes WHERE node_id=?", (normalize_node_id(node_id),)
            ).fetchone()
        return dict(row) if row else None

    def managed_node_by_usb(self, usb_identity: str) -> dict[str, object] | None:
        if not usb_identity:
            return None
        with contextlib.closing(self._connect()) as connection, connection:
            row = connection.execute(
                "SELECT * FROM managed_nodes WHERE usb_identity=? ORDER BY last_seen DESC LIMIT 1",
                (usb_identity,),
            ).fetchone()
        return dict(row) if row else None

    def find_managed_node_by_hint(self, label: str = "", node_suffix: str = "", preferred_node_id: str = "") -> str:
        preferred = normalize_node_id(preferred_node_id)
        with contextlib.closing(self._connect()) as connection, connection:
            if preferred:
                row = connection.execute("SELECT node_id FROM managed_nodes WHERE node_id=?", (preferred,)).fetchone()
                if row:
                    return str(row["node_id"])
            suffix = re.sub(r"[^0-9a-fA-F]", "", node_suffix or "").lower()
            if suffix:
                rows = list(connection.execute(
                    "SELECT node_id FROM managed_nodes WHERE lower(replace(node_id,'!','')) LIKE ?", (f"%{suffix}",)
                ))
                if len(rows) == 1:
                    return str(rows[0]["node_id"])
            clean_label = str(label or "").split(" - ", 1)[0].replace("[OTA]", "").strip()
            if clean_label:
                rows = list(connection.execute(
                    """SELECT m.node_id FROM managed_nodes m JOIN nodes n ON n.node_id=m.node_id
                       WHERE lower(n.long_name)=lower(?) OR lower(n.short_name)=lower(?)""",
                    (clean_label, clean_label),
                ))
                if len(rows) == 1:
                    return str(rows[0]["node_id"])
        return ""

    def record_firmware_event(
        self, node_id: str, transport: str, firmware: str, firmware_build: str,
        status: str, transport_identity: str = "", detail: str = "",
    ) -> None:
        now = now_local().isoformat(timespec="seconds")
        normalized = normalize_node_id(node_id) if node_id else ""
        with contextlib.closing(self._connect()) as connection, connection:
            connection.execute(
                """INSERT INTO firmware_events(node_id,captured_at,transport,transport_identity,firmware,firmware_build,status,detail)
                   VALUES(?,?,?,?,?,?,?,?)""",
                (normalized, now, transport, transport_identity, firmware, firmware_build, status, detail),
            )
            if normalized:
                connection.execute(
                    """UPDATE managed_nodes SET
                         firmware=CASE WHEN ?<>'' THEN ? ELSE firmware END,
                         firmware_build=CASE WHEN ?<>'' THEN ? ELSE firmware_build END,
                         last_firmware_update=?, last_seen=?, status=? WHERE node_id=?""",
                    (firmware, firmware, firmware_build, firmware_build, now, now, status, normalized),
                )

    def update_managed_from_log(self, metrics: dict[str, object], captured_at: str) -> None:
        node_id = normalize_node_id(str(metrics.get("node_id") or ""))
        if not node_id:
            return
        self.upsert_managed_node(
            node_id=node_id, long_name=str(metrics.get("long_name") or node_id),
            short_name=str(metrics.get("short_name") or ""), hardware=str(metrics.get("device") or ""),
            role=str(metrics.get("role") or ""), firmware=str(metrics.get("firmware") or ""),
            firmware_build=str(metrics.get("build") or ""), status="Log aktuell",
        )
'''
        repo = repo[:pos] + methods.rstrip() + "\n\n" + repo[pos:]

    import_anchor = "        return True\n\n    def scan_logs(self)"
    if "self.update_managed_from_log(metrics, captured_at)" not in repo:
        if repo.count(import_anchor) != 1:
            raise SystemExit("v2.1.19 import management anchor missing or ambiguous")
        repo = repo.replace(import_anchor, "        self.update_managed_from_log(metrics, captured_at)\n        return True\n\n    def scan_logs(self)", 1)
    source = source[:repo_start] + repo + source[repo_end:]

    actions_old = '''            for label, command in (\n                ("Einlesen / aktualisieren", lambda selected=slot: self.start_config_profile_capture(selected)),\n                ("Auf Node übertragen", lambda selected=slot: self.start_config_profile_apply(selected)),\n                ("Bearbeiten", lambda selected=slot: self._edit_config_profile(selected)),\n                ("Umbenennen", lambda selected=slot: self._rename_config_profile(selected)),\n                ("Löschen", lambda selected=slot: self._delete_config_profile(selected)),\n            ):\n                button = ttk.Button(buttons, text=label, command=command)\n                button.pack(side="left", fill="x", expand=True, padx=2)\n                self.config_profile_action_buttons.append(button)\n'''
    actions_new = '''            for action_index, (label, command) in enumerate((\n                ("Einlesen / aktualisieren", lambda selected=slot: self.start_config_profile_capture(selected)),\n                ("Auf Node übertragen", lambda selected=slot: self.start_config_profile_apply(selected)),\n                ("Werkreset + dieses Profil", lambda selected=slot: self.start_config_profile_provision(selected)),\n                ("Bearbeiten", lambda selected=slot: self._edit_config_profile(selected)),\n                ("Umbenennen", lambda selected=slot: self._rename_config_profile(selected)),\n                ("Löschen", lambda selected=slot: self._delete_config_profile(selected)),\n            )):\n                button = ttk.Button(buttons, text=label, command=command)\n                button.grid(row=action_index // 3, column=action_index % 3, sticky="ew", padx=2, pady=2)\n                self.config_profile_action_buttons.append(button)\n            for action_column in range(3):\n                buttons.columnconfigure(action_column, weight=1)\n'''
    if source.count(actions_old) != 1:
        raise SystemExit("v2.1.19 profile action block missing or ambiguous")
    source = source.replace(actions_old, actions_new, 1)
    source = source.replace("            base = slot * 5\n", "            base = slot * 6\n", 1)
    source = source.replace("            if base + 5 <= len(buttons):\n", "            if base + 6 <= len(buttons):\n", 1)
    source = source.replace("                for offset in range(1, 5):", "                for offset in range(1, 6):", 1)

    serial_ui_anchor = '''        self.serial_update_button.grid(row=4, column=0, columnspan=2, sticky="ew", pady=(8, 0))\n        setup.columnconfigure(1, weight=1)\n'''
    if "self.auto_usb_log_var" not in source:
        serial_ui_new = '''        self.serial_update_button.grid(row=4, column=0, columnspan=2, sticky="ew", pady=(8, 0))\n        self.auto_usb_log_var = tk.BooleanVar(value=True)\n        ttk.Checkbutton(\n            setup, text="Log beim USB-Anstecken automatisch laden", variable=self.auto_usb_log_var,\n        ).grid(row=5, column=0, columnspan=2, sticky="w", pady=(6, 0))\n        setup.columnconfigure(1, weight=1)\n'''
        if source.count(serial_ui_anchor) != 1:
            raise SystemExit("v2.1.19 auto USB log UI anchor missing or ambiguous")
        source = source.replace(serial_ui_anchor, serial_ui_new, 1)

    helpers = r'''    @staticmethod
    def _serial_identity_key(identity: dict[str, object] | None) -> str:
        if not isinstance(identity, dict): return ""
        vid, pid = identity.get("vid"), identity.get("pid")
        serial_number = str(identity.get("serial_number") or "").strip()
        location = str(identity.get("location") or "").strip()
        hwid = str(identity.get("hwid") or "").strip()
        if serial_number: return f"usb:{vid!s}:{pid!s}:{serial_number}".lower()
        if location: return f"loc:{vid!s}:{pid!s}:{location}".lower()
        return f"hwid:{hwid}".lower() if hwid else ""

    @staticmethod
    def _serial_port_record(port_info: object) -> dict[str, object]:
        return {key: getattr(port_info, key, None) for key in ("device","description","manufacturer","serial_number","location","hwid","vid","pid")}

    def _serial_port_identity(self, port: str) -> dict[str, object]:
        for info in list_ports.comports():
            if str(getattr(info, "device", "")).lower() == str(port).lower():
                record = self._serial_port_record(info); record["identity_key"] = self._serial_identity_key(record); return record
        return {"device": port, "identity_key": ""}

    @staticmethod
    def _looks_like_node_usb(record: dict[str, object]) -> bool:
        vid = record.get("vid")
        if isinstance(vid, int) and vid in {0x303A, 0x10C4, 0x1A86}: return True
        text = " ".join(str(record.get(k) or "") for k in ("description","manufacturer","hwid")).lower()
        return any(t in text for t in ("esp32","espressif","cp210","silicon labs","usb jtag","usb serial"))

    def _wait_for_matching_serial_port(self, identity: dict[str, object], preferred_port: str = "", timeout: float = 60.0) -> str:
        deadline = time.monotonic() + timeout; last_candidates = []
        while time.monotonic() < deadline:
            records = [self._serial_port_record(info) for info in list_ports.comports()]; scored = []
            for record in records:
                device = str(record.get("device") or ""); score = 20 if preferred_port and device.lower() == preferred_port.lower() else 0
                if identity.get("serial_number") and identity.get("serial_number") == record.get("serial_number"): score += 120
                if identity.get("location") and identity.get("location") == record.get("location"): score += 90
                if identity.get("vid") is not None and identity.get("vid") == record.get("vid"): score += 20
                if identity.get("pid") is not None and identity.get("pid") == record.get("pid"): score += 20
                if device and score: scored.append((score, device))
            if scored:
                scored.sort(reverse=True)
                if len(scored) == 1 or scored[0][0] > scored[1][0]:
                    tool_log("SERIAL_REFIND_V2119", selected=scored[0][1], score=scored[0][0]); return scored[0][1]
            last_candidates = [str(r.get("device") or "") for r in records if self._looks_like_node_usb(r) and r.get("device")]
            if len(last_candidates) == 1: return last_candidates[0]
            time.sleep(0.75)
        raise RuntimeError("Die Node wurde nach dem Neustart nicht eindeutig als COM-Port wiedergefunden." + (f" Kandidaten: {', '.join(last_candidates)}" if last_candidates else ""))

    def _select_serial_port_in_ui(self, port: str) -> None:
        self.refresh_ports()
        for label, device in self.port_map.items():
            if str(device).lower() == str(port).lower(): self.port.set(label); return
        self.port.set(port)

    @staticmethod
    def _device_code_from_hw_text(value: str) -> str:
        upper = str(value or "").upper()
        if "TRACKER" in upper: return "TRACKER"
        if "V3" in upper or "HELTEC_V3" in upper: return "V3"
        return ""

    def _detect_connected_device_code(self, interface: object, profile: dict[str, object]) -> str:
        metadata = getattr(interface, "metadata", None)
        with contextlib.suppress(Exception):
            code = OTABT_HARDWARE_CODES.get(int(getattr(metadata, "hw_model", 0) or 0), "")
            if code: return code
        with contextlib.suppress(Exception):
            info = interface.getMyNodeInfo() or {}; user = info.get("user") if isinstance(info, dict) else None
            if isinstance(user, dict):
                code = self._device_code_from_hw_text(str(user.get("hwModel") or user.get("hw_model") or ""))
                if code: return code
        code = self._device_code_from_hw_text(str(profile.get("source_hw") or ""))
        if code: return code
        raise RuntimeError("Tracker/V3 konnte vor dem Flash nicht eindeutig erkannt werden.")

    def _connected_node_snapshot(self, connection: tuple[str, str, str]) -> dict[str, object]:
        interface = None
        try:
            interface, node = self._open_config_profile_interface(connection)
            node_num = int(getattr(node,"nodeNum",0) or getattr(getattr(interface,"localNode",None),"nodeNum",0) or 0)
            source_hw, source_firmware = self._config_profile_metadata(interface); metadata = getattr(interface,"metadata",None); device_code = ""
            with contextlib.suppress(Exception): device_code = OTABT_HARDWARE_CODES.get(int(getattr(metadata,"hw_model",0) or 0),"")
            hardware = str(HARDWARE_PROFILES.get(device_code,{}).get("device") or source_hw or ""); role = ""
            with contextlib.suppress(Exception):
                value = int(node.localConfig.device.role); field = node.localConfig.device.DESCRIPTOR.fields_by_name.get("role"); enum = field.enum_type.values_by_number.get(value) if field and field.enum_type else None; role = enum.name if enum else str(value)
            return {"node_id": f"!{node_num:08x}" if node_num else "", "long_name": str(interface.getLongName() or "").strip(), "short_name": str(interface.getShortName() or "").strip(), "hardware": hardware, "role": role, "firmware": source_firmware, "device_code": device_code}
        finally:
            if interface is not None:
                with contextlib.suppress(Exception): interface.close()

    def _register_connected_node(self, connection: tuple[str,str,str], profile_slot: int|None=None, profile_name: str="", firmware_build: str="", event: str="", ota_ready: bool|None=None, status: str="Eingerichtet", usb_identity: dict[str,object]|None=None) -> dict[str,object]:
        snapshot = self._connected_node_snapshot(connection); node_id = str(snapshot.get("node_id") or "")
        if not node_id: raise RuntimeError("Node-ID konnte nach der Einrichtung nicht gelesen werden.")
        identity_key = self._serial_identity_key(usb_identity) if connection[0] == "USB" else ""; port = connection[1] if connection[0] == "USB" else ""
        self.repository.upsert_managed_node(node_id=node_id, long_name=str(snapshot.get("long_name") or node_id), short_name=str(snapshot.get("short_name") or ""), hardware=str(snapshot.get("hardware") or ""), role=str(snapshot.get("role") or ""), firmware=str(snapshot.get("firmware") or ""), firmware_build=firmware_build, profile_slot=(profile_slot+1) if isinstance(profile_slot,int) else None, profile_name=profile_name, usb_identity=identity_key, last_port=port, status=status, ota_ready=ota_ready, configured=profile_slot is not None)
        if event: self.repository.record_firmware_event(node_id, connection[0], str(snapshot.get("firmware") or ""), firmware_build, event, identity_key or connection[1], profile_name)
        tool_log("MANAGED_NODE_UPSERT_V2119", node_id=node_id, profile=profile_name or "--", build=firmware_build[:8] if firmware_build else "--", transport=connection[0]); self.events.put(("nodes_refresh", node_id)); return snapshot

    def _record_ble_firmware_update_by_hint(self, label: str, device_code: str, verified_build: str, source_sha: str, address: str, node_suffix: str, preferred_node_id: str="") -> None:
        node_id = self.repository.find_managed_node_by_hint(label,node_suffix,preferred_node_id); hardware = str(HARDWARE_PROFILES.get(device_code,{}).get("device") or ""); firmware = ""
        if node_id:
            managed = self.repository.management_for_node(node_id) or {}; firmware = str(managed.get("firmware") or "")
            self.repository.upsert_managed_node(node_id,"","",hardware,firmware=firmware,firmware_build=source_sha or verified_build,status="Firmware aktuell",ota_ready=True)
        self.repository.record_firmware_event(node_id,"Bluetooth",firmware,source_sha or verified_build,"Firmware aktuell" if node_id else "Firmware aktualisiert · Node-Zuordnung offen",address or label,label)
        if node_id: self.events.put(("nodes_refresh", node_id))

    def _auto_usb_log_candidates(self) -> list[dict[str,object]]:
        records = [self._serial_port_record(info) for info in list_ports.comports()]; return [r for r in records if self._looks_like_node_usb(r)]

    def _poll_auto_usb_log(self) -> None:
        now = time.monotonic()
        if now - float(getattr(self,"_auto_usb_last_poll",0.0)) < 1.0: return
        self._auto_usb_last_poll = now; records = self._auto_usb_log_candidates(); current = {self._serial_identity_key(r) or str(r.get("device") or "").lower(): r for r in records}; seen = getattr(self,"_auto_usb_seen",set())
        if not isinstance(seen,set): seen=set()
        seen.intersection_update(current); new = [k for k in current if k not in seen]; seen.update(current); self._auto_usb_seen = seen
        if not bool(getattr(self,"auto_usb_log_var",tk.BooleanVar(value=False)).get()) or getattr(self,"_provision_active",False) or (self.worker and self.worker.is_alive()) or not new: return
        port = str(current[new[0]].get("device") or "")
        if port: self._start_auto_usb_download(port)

    def _start_auto_usb_download(self, port: str) -> None:
        if self.worker and self.worker.is_alive(): return
        self._select_serial_port_in_ui(port); self.stop_event.clear(); self.expected_device=""; self.start_button.configure(state="disabled"); self.cancel_button.configure(state="normal"); self.set_transfer_progress(None,"Auto-Log · warte auf Node",True); self.set_result(f"USB-Node auf {port} erkannt. Automatischer Logdownload wartet auf den Export …"); tool_log("AUTO_USB_LOG_START_V2119",port=port); self.worker=threading.Thread(target=self._download_worker,args=(port,True),daemon=True); self.worker.start()

    def start_config_profile_provision(self, slot: int) -> None:
        if self.worker and self.worker.is_alive(): messagebox.showinfo("Node neu einrichten","Bitte den laufenden Vorgang zuerst beenden."); return
        profiles=self.config_profile_store.get("profiles",[]); profile=profiles[slot] if isinstance(profiles,list) and slot < len(profiles) else None
        if not isinstance(profile,dict): messagebox.showinfo("Node neu einrichten","Dieser Profil-Slot ist noch leer."); return
        long_name=self.config_target_long_var.get().strip(); short_name=self.config_target_short_var.get().strip(); pin_text=str(getattr(self,"config_bt_pin_var",tk.StringVar(value="240180")).get()).strip()
        if not long_name: messagebox.showerror("Node neu einrichten","Bitte den Long Name der Ziel-Node eingeben."); return
        if not short_name or len(short_name)>4: messagebox.showerror("Node neu einrichten","Der Short Name muss 1 bis 4 Zeichen lang sein."); return
        if not re.fullmatch(r"\d{6}",pin_text): messagebox.showerror("Node neu einrichten","Der feste Bluetooth-PIN muss genau aus 6 Ziffern bestehen."); return
        port=self.selected_port()
        if not port or "bluetooth" in self.port.get().lower():
            candidates=self._auto_usb_log_candidates()
            if len(candidates)==1: port=str(candidates[0].get("device") or ""); self._select_serial_port_in_ui(port)
            else: messagebox.showerror("Node neu einrichten","Bitte den echten USB-COM-Port der Node auswählen. Bei mehreren angeschlossenen Nodes ist eine eindeutige Auswahl erforderlich."); return
        profile_name=str(profile.get("name") or f"Profil {slot+1}")
        if not messagebox.askyesno("Full Device Reset + Profil",f"{profile_name} auf der USB-Node {port} komplett neu einrichten?\n\nAblauf: Full Device Reset → aktuellste passende Jarnsen-Firmware von GitHub → otaBTupdate einrichten → COM automatisch wiederfinden → dieses Profil, PSK-Auswahl, Long/Short Name und fester BT-PIN übertragen → Rückprüfung → Tool-Datenbank.\n\nDer Full Device Reset löscht die bisherige Meshtastic-Geräteidentität und Konfiguration."): return
        self._provision_active=True; self._provision_context=None; self._set_config_profile_buttons_state("disabled"); self.stop_event.clear(); self.status_level="normal"; self.status.configure(text=f"Node auf {port} wird komplett neu eingerichtet …"); self._update_status_badge(); self.set_transfer_progress(1,"USB-Node identifizieren",False); self.worker=threading.Thread(target=self._config_profile_provision_worker,args=(slot,profile,port),daemon=True); self.worker.start()

    def _config_profile_provision_worker(self, slot: int, profile: dict[str,object], port: str) -> None:
        interface=None
        try:
            identity=self._serial_port_identity(port); identity_key=self._serial_identity_key(identity); self.events.put(("status",f"Grundprofil {slot+1}: Hardware auf {port} erkennen")); interface,node=self._open_config_profile_interface(("USB",port,port)); device_code=self._detect_connected_device_code(interface,profile); expected_device=str(HARDWARE_PROFILES[device_code]["device"]); source_hw,_=self._config_profile_metadata(interface); tool_log("PROVISION_IDENTIFY_V2119",slot=slot+1,port=port,device_code=device_code,hw=source_hw or "--",usb_identity=identity_key or "--")
            if self.stop_event.is_set(): raise RuntimeError("Einrichtung abgebrochen")
            self.events.put(("progress_detail",(8,"Full Device Reset",False))); self.events.put(("status",f"{HARDWARE_PROFILES[device_code]['label']}: Full Device Reset")); node.factoryReset(full=True); time.sleep(1.0)
            with contextlib.suppress(Exception): interface.close()
            interface=None; reset_port=self._wait_for_matching_serial_port(identity,port,75.0)
            if self.stop_event.is_set(): raise RuntimeError("Einrichtung abgebrochen")
            self.events.put(("progress_detail",(18,"Neueste Firmware von GitHub prüfen",False))); firmware,loader,manifest=self._download_serial_bundle(device_code); source_sha=str(manifest.get("source_sha") or "").lower()
            with tempfile.TemporaryDirectory() as temporary:
                directory=pathlib.Path(temporary); firmware_path=directory/"firmware.update.bin"; loader_path=directory/"otaBTupdate.bin"; firmware_path.write_bytes(firmware); loader_path.write_bytes(loader); self.events.put(("progress_detail",(30,"ESP32-S3 prüfen",False))); self._run_esptool(["--chip","esp32s3","--port",reset_port,"chip-id"])
                if self.stop_event.is_set(): raise RuntimeError("Einrichtung abgebrochen")
                self.events.put(("progress_detail",(42,"Firmware + otaBTupdate seriell flashen",False))); self._run_esptool(["--chip","esp32s3","--port",reset_port,"--baud","460800","--before","default-reset","--after","hard-reset","write-flash","0x10000",str(firmware_path),"0x340000",str(loader_path)]); self.events.put(("progress_detail",(66,"OTA-Bootwahl zurücksetzen",False))); self._run_esptool(["--chip","esp32s3","--port",reset_port,"--before","default-reset","--after","hard-reset","erase-region","0xE000","0x2000"])
            flashed_port=self._wait_for_matching_serial_port(identity,reset_port,90.0); self.events.put(("progress_detail",(74,"Node nach Flash wiederfinden",False))); verify_interface=None
            try:
                verify_interface,_=self._open_config_profile_interface(("USB",flashed_port,flashed_port)); detected=self._detect_connected_device_code(verify_interface,profile)
                if detected != device_code: raise RuntimeError(f"Hardwareprüfung nach Flash fehlgeschlagen: {detected} statt {device_code}")
            finally:
                if verify_interface is not None:
                    with contextlib.suppress(Exception): verify_interface.close()
            context={"slot":slot,"profile_name":str(profile.get("name") or f"Profil {slot+1}"),"port":flashed_port,"device_code":device_code,"device":expected_device,"source_sha":source_sha,"usb_identity":identity}; tool_log("PROVISION_FLASH_OK_V2119",slot=slot+1,port=flashed_port,device_code=device_code,build=source_sha[:8] or "--"); self.events.put(("provision_ready_for_profile",context))
        except Exception as exc:
            tool_log("PROVISION_ERROR_V2119",slot=slot+1,port=port,error_type=type(exc).__name__,error=exc); self.events.put(("provision_error",str(exc)))
        finally:
            if interface is not None:
                with contextlib.suppress(Exception): interface.close()

    def _handoff_provision_to_profile(self, context: dict[str,object]) -> None:
        if self.worker and self.worker.is_alive(): self.after(250,lambda:self._handoff_provision_to_profile(context)); return
        port=str(context.get("port") or ""); self._select_serial_port_in_ui(port); self.config_profile_transport_var.set("USB"); self._provision_context=dict(context); self.set_transfer_progress(78,"Grundprofil übertragen",False); self.start_config_profile_apply(int(context["slot"]))

    def _schedule_profile_registration(self, verified: bool) -> None:
        context=getattr(self,"_profile_apply_management_context",None)
        if not isinstance(context,dict): return
        if not verified:
            self._profile_apply_management_context=None
            if getattr(self,"_provision_active",False): self._provision_active=False; self._provision_context=None
            return
        self.after(400,lambda:self._start_profile_registration(context))

    def _start_profile_registration(self, context: dict[str,object]) -> None:
        if self.worker and self.worker.is_alive(): self.after(300,lambda:self._start_profile_registration(context)); return
        self.worker=threading.Thread(target=self._profile_registration_worker,args=(dict(context),),daemon=True); self.worker.start()

    def _profile_registration_worker(self, context: dict[str,object]) -> None:
        try:
            connection=tuple(context.get("connection") or ())
            if len(connection)!=3: raise RuntimeError("Verbindungsdaten zur Datenbankaufnahme fehlen.")
            provision=getattr(self,"_provision_context",None); firmware_build=""; ota_ready=None; usb_identity=None; event=""
            if isinstance(provision,dict):
                firmware_build=str(provision.get("source_sha") or ""); ota_ready=True; usb_identity=provision.get("usb_identity") if isinstance(provision.get("usb_identity"),dict) else None; event="Neu eingerichtet"
                if connection[0]=="USB":
                    port=self._wait_for_matching_serial_port(usb_identity or self._serial_port_identity(connection[1]),str(connection[1]),60.0); connection=("USB",port,port)
            snapshot=self._register_connected_node(connection,profile_slot=int(context.get("slot")) if context.get("slot") is not None else None,profile_name=str(context.get("profile_name") or ""),firmware_build=firmware_build,event=event,ota_ready=ota_ready,status="Eingerichtet",usb_identity=usb_identity); self.events.put(("managed_node_updated",snapshot))
            if isinstance(provision,dict): self.events.put(("provision_complete",(snapshot,dict(provision),connection)))
        except Exception as exc:
            tool_log("MANAGED_NODE_REGISTER_ERROR_V2119",error_type=type(exc).__name__,error=exc)
            if getattr(self,"_provision_active",False): self.events.put(("provision_error",f"Profil wurde übertragen, aber Datenbankaufnahme schlug fehl: {exc}"))
        finally: self._profile_apply_management_context=None
'''
    if "    def start_config_profile_provision(self, slot: int)" not in source:
        source = insert_before_method(source, "refresh_ports", helpers)

    start_begin,start_end=method_span(source,"start_config_profile_apply"); start_apply=source[start_begin:start_end]
    if "_profile_apply_management_context" not in start_apply:
        anchor='        self._set_config_profile_buttons_state("disabled")\n'
        insert='''        self._profile_apply_management_context = {\n            "slot": slot,\n            "profile_name": str(profile.get("name") or f"Profil {slot + 1}"),\n            "connection": connection,\n        }\n'''
        if start_apply.count(anchor)!=1: raise SystemExit("v2.1.19 profile management context anchor missing")
        start_apply=start_apply.replace(anchor,insert+anchor,1); source=source[:start_begin]+start_apply+source[start_end:]

    d0,d1=method_span(source,"_download_worker"); download=source[d0:d1]; download=download.replace("    def _download_worker(self, port: str) -> None:\n","    def _download_worker(self, port: str, auto_mode: bool = False) -> None:\n",1); download=download.replace("            deadline = time.monotonic() + 300\n","            deadline = time.monotonic() + (45 if auto_mode else 300)\n",1)
    old='''            raise RuntimeError(\n                "Kein Exportmarker empfangen. Export am Gerät erneut bestätigen."\n            )\n'''; new='''            if auto_mode:\n                tool_log("AUTO_USB_LOG_NO_EXPORT_V2119", port=port)\n                self.events.put(("auto_log_no_export", port))\n                return\n            raise RuntimeError(\n                "Kein Exportmarker empfangen. Export am Gerät erneut bestätigen."\n            )\n'''
    if "AUTO_USB_LOG_NO_EXPORT_V2119" not in download:
        if download.count(old)!=1: raise SystemExit("v2.1.19 auto log no-marker anchor missing")
        download=download.replace(old,new,1)
    old_exc='''        except serial.SerialException as exc:\n            raise_text = f"Port {port} konnte nicht geöffnet werden: {exc}\\nAlle Serial-Monitore schließen oder Blockersuche verwenden."\n            self.events.put(("error", raise_text))\n        except Exception as exc:\n            self.events.put(("error", str(exc)))\n'''; new_exc='''        except serial.SerialException as exc:\n            raise_text = f"Port {port} konnte nicht geöffnet werden: {exc}\\nAlle Serial-Monitore schließen oder Blockersuche verwenden."\n            self.events.put(("status_warning" if auto_mode else "error", raise_text))\n        except Exception as exc:\n            self.events.put(("status_warning" if auto_mode else "error", str(exc)))\n'''
    if download.count(old_exc)!=1: raise SystemExit("v2.1.19 auto log exception anchor missing")
    download=download.replace(old_exc,new_exc,1); source=source[:d0]+download+source[d1:]

    s0,s1=method_span(source,"_serial_update_worker"); sw=source[s0:s1]
    if "SERIAL_UPDATE_MANAGED_V2119" not in sw:
        a="        try:\n            profile = HARDWARE_PROFILES[device_code]\n"; b="        try:\n            identity = self._serial_port_identity(port)\n            profile = HARDWARE_PROFILES[device_code]\n"
        if sw.count(a)!=1: raise SystemExit("v2.1.19 serial updater identity anchor missing")
        sw=sw.replace(a,b,1); a='            source_sha = str(manifest.get("source_sha") or "")\n'; b='''            source_sha = str(manifest.get("source_sha") or "")\n            reconnected_port = self._wait_for_matching_serial_port(identity, port, timeout=75.0)\n            try:\n                snapshot = self._register_connected_node(("USB", reconnected_port, reconnected_port), firmware_build=source_sha, event="Serielles Firmwareupdate", ota_ready=True, status="Firmware aktuell", usb_identity=identity)\n                tool_log("SERIAL_UPDATE_MANAGED_V2119", node_id=snapshot.get("node_id", "--"), port=reconnected_port)\n            except Exception as register_exc:\n                managed = self.repository.managed_node_by_usb(self._serial_identity_key(identity)); node_id = str(managed.get("node_id") or "") if isinstance(managed, dict) else ""\n                self.repository.record_firmware_event(node_id, "USB", "", source_sha, "Firmware geflasht · Rücklesen offen", self._serial_identity_key(identity) or reconnected_port, str(register_exc))\n                tool_log("SERIAL_UPDATE_MANAGED_V2119", node_id=node_id or "--", port=reconnected_port, warning=register_exc)\n'''
        if sw.count(a)!=1: raise SystemExit("v2.1.19 serial updater DB anchor missing")
        sw=sw.replace(a,b,1); sw=sw.replace('f"{profile[\'label\']} erfolgreich über {port} aktualisiert.\\n"','f"{profile[\'label\']} erfolgreich über {reconnected_port} aktualisiert.\\n"',1); source=source[:s0]+sw+source[s1:]

    b0,b1=method_span(source,"_ble_update_fleet_async"); bw=source[b0:b1]
    if "_record_ble_firmware_update_by_hint" not in bw:
        a='''                    completed += 1\n                    self.events.put(\n                        (\n                            "status_success",\n                            f"Node {index}/{total} ist bereits aktuell ({installed_build})",\n                        )\n                    )\n'''; b='''                    completed += 1\n                    await asyncio.to_thread(self._record_ble_firmware_update_by_hint, label, device_code, installed_build, source_sha, str(getattr(entry["device"], "address", "") or ""), self._ble_identity_suffix(entry["device"]), self.selected_node_id if total == 1 else "")\n                    self.events.put(\n                        (\n                            "status_success",\n                            f"Node {index}/{total} ist bereits aktuell ({installed_build})",\n                        )\n                    )\n'''
        if bw.count(a)!=1: raise SystemExit("v2.1.19 BLE already-current DB anchor missing")
        bw=bw.replace(a,b,1); a='''                    verified_build = await self._verify_updated_firmware(\n                        device_code, source_sha, address\n                    )\n                    completed += 1\n'''; b='''                    verified_build = await self._verify_updated_firmware(\n                        device_code, source_sha, address\n                    )\n                    await asyncio.to_thread(self._record_ble_firmware_update_by_hint, label, device_code, verified_build, source_sha, address, name_suffix, self.selected_node_id if total == 1 else "")\n                    completed += 1\n'''
        if bw.count(a)!=1: raise SystemExit("v2.1.19 BLE verified DB anchor missing")
        bw=bw.replace(a,b,1); source=source[:b0]+bw+source[b1:]

    a0,a1=method_span(source,"refresh_all_nodes_overview"); all_nodes=source[a0:a1]
    if "management_for_node(node_id)" not in all_nodes:
        a='''            latest = self.repository.latest_log(node_id)\n            metrics = latest.get("metrics", {}) if latest else {}\n'''; b='''            latest = self.repository.latest_log(node_id)\n            managed = self.repository.management_for_node(node_id) or {}\n            metrics = latest.get("metrics", {}) if latest else {}\n'''
        if all_nodes.count(a)!=1: raise SystemExit("v2.1.19 all-nodes management anchor missing")
        all_nodes=all_nodes.replace(a,b,1); a='''            firmware = str(latest.get("firmware") or "--") if latest else "--"\n            build = str(latest.get("build") or "") if latest else ""\n'''; b='''            firmware = str(latest.get("firmware") or managed.get("firmware") or "--") if latest else str(managed.get("firmware") or "--")\n            build = str(latest.get("build") or managed.get("firmware_build") or "") if latest else str(managed.get("firmware_build") or "")\n'''
        if all_nodes.count(a)!=1: raise SystemExit("v2.1.19 all-nodes firmware anchor missing")
        all_nodes=all_nodes.replace(a,b,1); a='''            captured = str(latest.get("captured_at") or "--").replace("T", " ") if latest else "--"\n'''; b='''            captured = (str(latest.get("captured_at") or managed.get("last_seen") or "--").replace("T", " ") if latest else str(managed.get("last_seen") or "--").replace("T", " "))\n'''
        if all_nodes.count(a)!=1: raise SystemExit("v2.1.19 all-nodes last-seen anchor missing")
        all_nodes=all_nodes.replace(a,b,1); a='''            else:\n                positions = metrics.get("positions")\n                position = f"{int(positions)} Position(en)" if isinstance(positions, (int, float)) else "--"\n'''; b='''            else:\n                positions = metrics.get("positions")\n                if isinstance(positions, (int, float)):\n                    position = f"{int(positions)} Position(en)"\n                else:\n                    profile_text = str(managed.get("profile_name") or "").strip(); state_text = str(managed.get("status") or "").strip(); position = " · ".join(v for v in (profile_text, state_text) if v) or "--"\n'''
        if all_nodes.count(a)!=1: raise SystemExit("v2.1.19 all-nodes profile/status anchor missing")
        all_nodes=all_nodes.replace(a,b,1); source=source[:a0]+all_nodes+source[a1:]

    p0,p1=method_span(source,"_pump_events"); pump=source[p0:p1]
    if 'elif kind == "provision_ready_for_profile":' not in pump:
        anchor='                elif kind == "config_profile_apply_result":\n'; handlers=r'''                elif kind == "provision_ready_for_profile":
                    context = dict(value); self.status_level = "success"; self.status.configure(text="Firmware + otaBTupdate installiert · Grundprofil folgt"); self._update_status_badge(); self.set_transfer_progress(76, "COM wiedergefunden · Profil vorbereiten", False); self._handoff_provision_to_profile(context)
                elif kind == "provision_complete":
                    snapshot, provision, connection = value; self._provision_active = False; self._provision_context = None; node_id = str(snapshot.get("node_id") or ""); self.status_level = "success"; self.status.configure(text=f"Node vollständig eingerichtet · {node_id or '--'}"); self._update_status_badge(); self.set_transfer_progress(100, "Neuinstallation + Profil abgeschlossen", False); self.refresh_all_nodes_overview(); messagebox.showinfo("Node neu eingerichtet", f"{snapshot.get('long_name') or node_id} wurde vollständig eingerichtet.\n\nHardware: {snapshot.get('hardware') or '--'}\nFirmware-Build: {str(provision.get('source_sha') or '')[:8] or '--'}\nProfil: {provision.get('profile_name') or '--'}\notaBTupdate: vorbereitet\nTool-Datenbank: aktualisiert")
                    if bool(getattr(self, "auto_usb_log_var", tk.BooleanVar(value=False)).get()) and connection[0] == "USB": self.after(900, lambda selected_port=str(connection[1]): self._start_auto_usb_download(selected_port))
                elif kind == "provision_error":
                    self._provision_active = False; self._provision_context = None; self._profile_apply_management_context = None; self._set_config_profile_buttons_state("normal"); self.status_level = "error"; self.status.configure(text="Node-Neueinrichtung fehlgeschlagen"); self._update_status_badge(); self.set_result(str(value)); messagebox.showerror("Node neu einrichten", str(value))
                elif kind == "managed_node_updated":
                    snapshot = value if isinstance(value, dict) else {}; node_id = str(snapshot.get("node_id") or ""); self.selected_node_id = node_id or self.selected_node_id; self.refresh_nodes()
                    with contextlib.suppress(Exception): self.refresh_all_nodes_overview()
                elif kind == "auto_log_no_export":
                    self.status_level = "warning"; self.status.configure(text=f"Auto-Log: {value} erkannt, aber kein Export empfangen"); self._update_status_badge()
'''
        if pump.count(anchor)!=1: raise SystemExit("v2.1.19 event insertion anchor missing")
        pump=pump.replace(anchor,handlers+anchor,1)
    anchor='''                    if verified:\n                        messagebox.showinfo("Grundprofil übertragen", str(summary))\n                    else:\n                        messagebox.showwarning("Grundprofil übertragen", str(summary))\n'''
    if "self._schedule_profile_registration(bool(verified))" not in pump:
        if pump.count(anchor)!=1: raise SystemExit("v2.1.19 profile result registration anchor missing")
        pump=pump.replace(anchor,anchor+'                    self._schedule_profile_registration(bool(verified))\n',1)
    anchor="        self._continue_smart_action()\n        self.refresh_workflow_header()\n"
    if "self._poll_auto_usb_log()" not in pump:
        if pump.count(anchor)!=1: raise SystemExit("v2.1.19 event pump polling anchor missing")
        pump=pump.replace(anchor,"        self._continue_smart_action()\n        self._poll_auto_usb_log()\n        self.refresh_workflow_header()\n",1)
    source=source[:p0]+pump+source[p1:]

    required=('APP_VERSION = "2.1.19"','text="Werkreset + dieses Profil"',"def start_config_profile_provision(self, slot: int)","node.factoryReset(full=True)","Firmware + otaBTupdate seriell flashen","_wait_for_matching_serial_port","MANAGED_NODE_UPSERT_V2119","CREATE TABLE IF NOT EXISTS managed_nodes","CREATE TABLE IF NOT EXISTS firmware_events","SERIAL_UPDATE_MANAGED_V2119","_record_ble_firmware_update_by_hint",'text="Log beim USB-Anstecken automatisch laden"',"AUTO_USB_LOG_START_V2119","self._poll_auto_usb_log()","self._schedule_profile_registration(bool(verified))",'tk.StringVar(value="240180")',"fixed_bt_pin: int | None")
    missing=[marker for marker in required if marker not in source]
    if missing: raise SystemExit("v2.1.19 validation failed: "+", ".join(missing))
    return source


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: patch_jarnsen_service_tool_v2119.py <source.py>")
    path = Path(sys.argv[1]); path.write_text(patch(path.read_text(encoding="utf-8")), encoding="utf-8")
    print(f"Patched {path} to v{APP_VERSION}: serial provisioning + managed DB + USB auto-log")


if __name__ == "__main__":
    main()
