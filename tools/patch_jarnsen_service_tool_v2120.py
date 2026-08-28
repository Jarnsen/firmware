"""v2.1.20: complete profile editor, symmetric config writes and delta USB log sync."""
from __future__ import annotations

import re
import sys
from pathlib import Path

APP_VERSION = "2.1.20"


def method_span(text: str, name: str) -> tuple[int, int]:
    normal = text.find(f"    def {name}(")
    asynchronous = text.find(f"    async def {name}(")
    starts = [value for value in (normal, asynchronous) if value >= 0]
    if not starts:
        raise SystemExit(f"method {name} not found")
    start = min(starts)
    next_method = text.find("\n    def ", start + 1)
    next_async = text.find("\n    async def ", start + 1)
    next_decorator = text.find("\n    @", start + 1)
    candidates = [value for value in (next_method, next_async, next_decorator) if value >= 0]
    return start, min(candidates) if candidates else len(text)


def class_span(text: str, name: str) -> tuple[int, int]:
    start = text.find(f"class {name}:")
    if start < 0:
        raise SystemExit(f"class {name} not found")
    next_class = text.find("\nclass ", start + 1)
    return start, next_class if next_class >= 0 else len(text)


def replace_method(text: str, name: str, replacement: str) -> str:
    start, end = method_span(text, name)
    return text[:start] + replacement.rstrip() + "\n" + text[end:]


def insert_before_method(text: str, name: str, code: str) -> str:
    start, _ = method_span(text, name)
    return text[:start] + code.rstrip() + "\n\n" + text[start:]


def patch(source: str) -> str:
    source = re.sub(r'APP_VERSION = "[^"]+"', f'APP_VERSION = "{APP_VERSION}"', source, count=1)
    source = source.replace('APP_VERSION != "2.1.19"', 'APP_VERSION != "2.1.20"')
    source = source.replace("App-Version ist nicht v2.1.19", "App-Version ist nicht v2.1.20")

    # --- Managed-node schema: add persistent delta-log cursor state without rebuilding the DB.
    repo_start, repo_end = class_span(source, "NodeRepository")
    repo = source[repo_start:repo_end]
    schema_start, schema_end = method_span(repo, "_create_management_schema")
    schema = repo[schema_start:schema_end]
    if "log_generation" not in schema:
        insertion = '''\n            existing = {str(row[1]) for row in connection.execute("PRAGMA table_info(managed_nodes)")}\n            for column, ddl in (\n                ("log_generation", "INTEGER NOT NULL DEFAULT 0"),\n                ("log_cursor", "INTEGER NOT NULL DEFAULT 0"),\n                ("log_sync_status", "TEXT NOT NULL DEFAULT ''"),\n                ("last_log_sync", "TEXT NOT NULL DEFAULT ''"),\n                ("last_log_path", "TEXT NOT NULL DEFAULT ''"),\n            ):\n                if column not in existing:\n                    connection.execute(f"ALTER TABLE managed_nodes ADD COLUMN {column} {ddl}")\n'''
        schema = schema.rstrip() + insertion + "\n"
        repo = repo[:schema_start] + schema + repo[schema_end:]

    if "    def update_log_sync(" not in repo:
        marker = "    def update_managed_from_log("
        pos = repo.find(marker)
        if pos < 0:
            raise SystemExit("v2.1.20 managed DB insertion anchor missing")
        methods = r'''    def update_log_sync(
        self, node_id: str, generation: int, cursor: int, status: str,
        path: str = "", usb_identity: str = "", last_port: str = "",
    ) -> None:
        normalized = normalize_node_id(node_id)
        if not normalized:
            return
        now = now_local().isoformat(timespec="seconds")
        with contextlib.closing(self._connect()) as connection, connection:
            connection.execute(
                """UPDATE managed_nodes SET log_generation=?,log_cursor=?,log_sync_status=?,last_log_sync=?,
                   last_log_path=CASE WHEN ?<>'' THEN ? ELSE last_log_path END,
                   usb_identity=CASE WHEN ?<>'' THEN ? ELSE usb_identity END,
                   last_port=CASE WHEN ?<>'' THEN ? ELSE last_port END,last_seen=? WHERE node_id=?""",
                (int(generation), int(cursor), status, now, path, path, usb_identity, usb_identity,
                 last_port, last_port, now, normalized),
            )

    def log_sync_for_usb(self, usb_identity: str) -> tuple[str, int, int]:
        row = self.managed_node_by_usb(usb_identity)
        if not row:
            return "", 0, 0
        return (
            str(row.get("node_id") or ""),
            int(row.get("log_generation") or 0),
            int(row.get("log_cursor") or 0),
        )

'''
        repo = repo[:pos] + methods + repo[pos:]
    source = source[:repo_start] + repo + source[repo_end:]

    # --- Full reusable profile editor. Every stored protobuf section can be edited as JSON.
    editor_helpers = r'''    def _profile_message(self, profile: dict[str, object], kind: str, name: str):
        from meshtastic.protobuf import channel_pb2, localonly_pb2
        if kind == "config":
            container = localonly_pb2.LocalConfig()
            encoded = str((profile.get("config") or {}).get(name) or "")
            message = getattr(container, name)
        elif kind == "module":
            container = localonly_pb2.LocalModuleConfig()
            encoded = str((profile.get("module_config") or {}).get(name) or "")
            message = getattr(container, name)
        else:
            channels = profile.get("channels", []) if isinstance(profile.get("channels"), list) else []
            entry = next((item for item in channels if isinstance(item, dict) and int(item.get("index", -1)) == int(name)), None)
            if entry is None:
                raise KeyError(f"Kanal {name} fehlt")
            message = channel_pb2.Channel()
            encoded = str(entry.get("payload") or "")
        if encoded:
            message.ParseFromString(self._decode_protobuf_payload(encoded))
        return message

    def _save_profile_message(self, profile: dict[str, object], kind: str, name: str, message) -> None:
        if kind == "config":
            profile.setdefault("config", {})[name] = self._protobuf_payload(message)
        elif kind == "module":
            profile.setdefault("module_config", {})[name] = self._protobuf_payload(message)
        else:
            channels = profile.get("channels", []) if isinstance(profile.get("channels"), list) else []
            entry = next((item for item in channels if isinstance(item, dict) and int(item.get("index", -1)) == int(name)), None)
            if entry is None:
                raise KeyError(f"Kanal {name} fehlt")
            entry["payload"] = self._protobuf_payload(message)
        profile["saved_at"] = now_local().isoformat(timespec="seconds")
        self._save_config_profile_store()
        self._refresh_config_profile_ui()

    @staticmethod
    def _profile_section_title(kind: str, name: str) -> str:
        if kind == "channel": return f"Kanal {name}"
        return f"{'Modul' if kind == 'module' else 'Config'} · {name}"

    def _edit_profile_json_section(self, profile: dict[str, object], kind: str, name: str, parent) -> None:
        from google.protobuf import json_format
        try:
            message = self._profile_message(profile, kind, name)
            data = json_format.MessageToDict(message, preserving_proto_field_name=True)
        except Exception as exc:
            messagebox.showerror("Grundprofil bearbeiten", str(exc), parent=parent)
            return
        win = tk.Toplevel(parent); win.title(self._profile_section_title(kind, name)); win.transient(parent); win.grab_set(); win.geometry("760x650")
        info = []
        if kind == "config" and name == "position": info.append("Position ins Mesh: EIN · Firmware fest")
        if kind == "module" and name == "neighbor_info": info.append("Neighbor Info: standardmäßig EIN · nur direkt im Node-Service-Menü abschaltbar")
        if kind == "config" and name == "security": info.append("Private/Public/Admin Device-Keys bleiben beim Übertragen immer node-spezifisch.")
        if kind == "channel": info.append("PSK ist ein geheimer Kanalschlüssel. Änderungen werden nur bei aktivem 'PSK anwenden' übertragen.")
        if info:
            ttk.Label(win, text="\n".join(info), style="Subtitle.TLabel", justify="left", wraplength=720).pack(fill="x", padx=10, pady=(10,4))
        text = tk.Text(win, wrap="none", font=("Consolas", 10), undo=True)
        text.pack(fill="both", expand=True, padx=10, pady=6)
        text.insert("1.0", json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True))
        footer = ttk.Frame(win); footer.pack(fill="x", padx=10, pady=(0,10))
        def save() -> None:
            try:
                raw = json.loads(text.get("1.0", "end-1c"))
                updated = type(message)()
                json_format.ParseDict(raw, updated, ignore_unknown_fields=False)
                if kind == "config" and name == "position":
                    if hasattr(updated, "position_broadcast_secs") and int(updated.position_broadcast_secs) <= 0:
                        updated.position_broadcast_secs = max(1, int(getattr(message, "position_broadcast_secs", 900) or 900))
                    if hasattr(updated, "position_broadcast_smart_enabled"):
                        updated.position_broadcast_smart_enabled = True
                if kind == "module" and name == "neighbor_info":
                    if hasattr(updated, "enabled"): updated.enabled = True
                    if hasattr(updated, "transmit_over_lora"): updated.transmit_over_lora = True
                    if hasattr(updated, "update_interval") and int(updated.update_interval) < 14400: updated.update_interval = 14400
                self._save_profile_message(profile, kind, name, updated)
                win.destroy()
            except Exception as exc:
                messagebox.showerror("Ungültige Konfiguration", str(exc), parent=win)
        ttk.Button(footer, text="Abbrechen", command=win.destroy).pack(side="right")
        ttk.Button(footer, text="Speichern", command=save).pack(side="right", padx=6)

    def _open_profile_category(self, profile: dict[str, object], title: str, items: list[tuple[str,str]], parent) -> None:
        win = tk.Toplevel(parent); win.title(title); win.transient(parent); win.grab_set(); win.geometry("570x560")
        ttk.Label(win, text=title, style="Section.TLabel").pack(anchor="w", padx=12, pady=(12,4))
        ttk.Label(win, text="Jeder eingelesene Wert dieser Bereiche kann geöffnet, geändert und wieder gespeichert werden.", style="Subtitle.TLabel", wraplength=530).pack(fill="x", padx=12, pady=(0,8))
        body = ttk.Frame(win, padding=(12,0,12,12)); body.pack(fill="both", expand=True)
        for row, (kind, name) in enumerate(items):
            label = self._profile_section_title(kind, name)
            ttk.Button(body, text=label, command=lambda k=kind,n=name: self._edit_profile_json_section(profile,k,n,win)).grid(row=row,column=0,sticky="ew",pady=2)
        body.columnconfigure(0, weight=1)
        ttk.Button(win, text="Schließen", command=win.destroy).pack(side="bottom", pady=(0,10))

    def _profile_category_items(self, profile: dict[str, object], category: str) -> list[tuple[str,str]]:
        configs = sorted((profile.get("config") or {}).keys()) if isinstance(profile.get("config"), dict) else []
        modules = sorted((profile.get("module_config") or {}).keys()) if isinstance(profile.get("module_config"), dict) else []
        channel_ids = [str(int(item.get("index", 0))) for item in (profile.get("channels") or []) if isinstance(item, dict)]
        mapping = {
            "Gerät & Mesh": [("config", n) for n in configs if n in ("device","network","security")],
            "LoRa & Funk": [("config", n) for n in configs if n == "lora"],
            "Kanäle & PSK": [("channel", n) for n in channel_ids],
            "Position & GPS": [("config", n) for n in configs if n == "position"],
            "Bluetooth": [("config", n) for n in configs if n == "bluetooth"],
            "Module": [("module", n) for n in modules],
            "Strom & Display": [("config", n) for n in configs if n in ("power","display")],
        }
        if category == "Erweitert / Alle Werte":
            return [("config", n) for n in configs] + [("module", n) for n in modules] + [("channel", n) for n in channel_ids]
        return mapping.get(category, [])
'''
    source = insert_before_method(source, "_rename_config_profile", editor_helpers)

    editor = r'''    def _edit_config_profile(self, slot: int) -> None:
        profiles = self.config_profile_store.get("profiles", [])
        profile = profiles[slot] if isinstance(profiles, list) and slot < len(profiles) else None
        if not isinstance(profile, dict):
            messagebox.showinfo("Grundprofil", "Dieser Profilplatz ist leer.")
            return
        win = tk.Toplevel(self); win.title(f"Grundprofil {slot + 1} vollständig bearbeiten"); win.transient(self); win.grab_set(); win.geometry("900x620")
        body = ttk.Frame(win, padding=14); body.pack(fill="both", expand=True)
        name_var = tk.StringVar(value=str(profile.get("name") or f"Profil {slot + 1}"))
        ttk.Label(body, text="Profilname", style="Section.TLabel").grid(row=0,column=0,columnspan=2,sticky="w")
        ttk.Entry(body, textvariable=name_var).grid(row=1,column=0,columnspan=2,sticky="ew",pady=(2,10))
        rules = (
            "Feste Regeln: Position ins Mesh = EIN (Firmware) · Neighbor Info = EIN/LoRa EIN, nur im Node-Service-Menü abschaltbar · "
            "Long/Short Name leer = vorhandenen Zielnamen behalten · Device-Identitätskeys werden nie kopiert."
        )
        ttk.Label(body, text=rules, style="Subtitle.TLabel", justify="left", wraplength=840).grid(row=2,column=0,columnspan=2,sticky="ew",pady=(0,12))
        categories = ("Gerät & Mesh","LoRa & Funk","Kanäle & PSK","Position & GPS","Bluetooth","Module","Strom & Display","Erweitert / Alle Werte")
        for index, category in enumerate(categories):
            items = self._profile_category_items(profile, category)
            button = ttk.Button(body, text=f"{category}\n{len(items)} Bereich(e)", command=lambda c=category: self._open_profile_category(profile,c,self._profile_category_items(profile,c),win))
            button.grid(row=3 + index//2,column=index%2,sticky="nsew",padx=5,pady=5,ipady=10)
        footer=ttk.Frame(body); footer.grid(row=7,column=0,columnspan=2,sticky="ew",pady=(12,0))
        def save_name():
            profile["name"] = name_var.get().strip() or f"Profil {slot + 1}"
            profile["saved_at"] = now_local().isoformat(timespec="seconds")
            self._save_config_profile_store(); self._refresh_config_profile_ui(); win.destroy()
        ttk.Button(footer,text="Von Node neu einlesen",command=lambda:(win.destroy(),self.start_config_profile_capture(slot))).pack(side="left")
        ttk.Button(footer,text="Schließen",command=save_name).pack(side="right")
        body.columnconfigure(0,weight=1); body.columnconfigure(1,weight=1)
        for row in range(3,7): body.rowconfigure(row,weight=1)
'''
    source = replace_method(source, "_edit_config_profile", editor)

    # --- Blank Long/Short target fields preserve the current node names.
    s0, s1 = method_span(source, "start_config_profile_apply")
    start_apply = source[s0:s1]
    start_apply = start_apply.replace(
        '''        if not long_name:\n            messagebox.showerror("Grundprofil übertragen", "Bitte den Long Name der Ziel-Node eingeben.")\n            return\n        if not short_name or len(short_name) > 4:\n            messagebox.showerror("Grundprofil übertragen", "Der Short Name muss 1 bis 4 Zeichen lang sein.")\n            return\n''',
        '''        if short_name and len(short_name) > 4:\n            messagebox.showerror("Grundprofil übertragen", "Der Short Name darf maximal 4 Zeichen lang sein.")\n            return\n''',
        1,
    )
    source = source[:s0] + start_apply + source[s1:]

    p0, p1 = method_span(source, "start_config_profile_provision")
    provision_start = source[p0:p1]
    provision_start = provision_start.replace(
        '''        if not long_name: messagebox.showerror("Node neu einrichten","Bitte den Long Name der Ziel-Node eingeben."); return\n        if not short_name or len(short_name)>4: messagebox.showerror("Node neu einrichten","Der Short Name muss 1 bis 4 Zeichen lang sein."); return\n''',
        '''        if short_name and len(short_name)>4: messagebox.showerror("Node neu einrichten","Der Short Name darf maximal 4 Zeichen lang sein."); return\n''',
        1,
    )
    source = source[:p0] + provision_start + source[p1:]

    # --- Profile writes: direct AdminMessage fallback for module sections missing in meshtastic-python 2.7.11.
    w0, w1 = method_span(source, "_config_profile_apply_worker")
    worker = source[w0:w1]
    old_safe = '''            def write_config_safe(name: str, kind: str) -> bool:\n                try:\n                    node.writeConfig(name)\n                    return True\n'''
    new_safe = '''            def write_config_safe(name: str, kind: str) -> bool:\n                try:\n                    if kind == "Modul" and name in ("statusmessage", "tak"):\n                        from meshtastic.protobuf import admin_pb2\n                        admin = admin_pb2.AdminMessage()\n                        destination = getattr(admin.set_module_config, name, None)\n                        source_section = getattr(node.moduleConfig, name, None)\n                        if destination is None or source_section is None:\n                            raise RuntimeError(f"Admin-Protobuf für Modul {name} fehlt")\n                        destination.CopyFrom(source_section)\n                        node._sendAdmin(admin)\n                        tool_log("CONFIG_PROFILE_DIRECT_ADMIN_V2120", slot=slot + 1, transport=connection[0], name=name)\n                    else:\n                        node.writeConfig(name)\n                    return True\n'''
    if old_safe not in worker:
        raise SystemExit("v2.1.20 safe writer anchor missing")
    worker = worker.replace(old_safe, new_safe, 1)

    owner_anchor = '''            stage("Long/Short Name schreiben")\n            node.setOwner(long_name=long_name, short_name=short_name[:4])\n            time.sleep(0.75)\n'''
    owner_new = '''            current_long_name = str(interface.getLongName() or "").strip()\n            current_short_name = str(interface.getShortName() or "").strip()\n            long_name = long_name or current_long_name\n            short_name = short_name or current_short_name\n            if not long_name:\n                long_name = current_long_name or "Meshtastic"\n            if not short_name:\n                short_name = current_short_name or long_name[:4]\n            if self.config_target_long_var.get().strip() or self.config_target_short_var.get().strip():\n                stage("Long/Short Name schreiben")\n                node.setOwner(long_name=long_name, short_name=short_name[:4])\n                time.sleep(0.75)\n            else:\n                stage("Long/Short Name beibehalten")\n'''
    if owner_anchor not in worker:
        raise SystemExit("v2.1.20 owner preservation anchor missing")
    worker = worker.replace(owner_anchor, owner_new, 1)

    # Normalize firmware-owned safety rules before writes.
    desired_anchor = '''                    if name == "security":\n'''
    desired_rules = '''                    if name == "position":\n                        if hasattr(desired, "position_broadcast_secs") and int(desired.position_broadcast_secs) <= 0:\n                            desired.position_broadcast_secs = max(1, int(getattr(section, "position_broadcast_secs", 900) or 900))\n                        if hasattr(desired, "position_broadcast_smart_enabled"):\n                            desired.position_broadcast_smart_enabled = True\n\n                    if name == "security":\n'''
    if desired_anchor not in worker:
        raise SystemExit("v2.1.20 position rule anchor missing")
    worker = worker.replace(desired_anchor, desired_rules, 1)

    module_parse = '''                    desired = type(section)()\n                    desired.ParseFromString(self._decode_protobuf_payload(str(encoded)))\n                    section.CopyFrom(desired)\n                    stage(f"Modul {name} schreiben")\n'''
    module_rules = '''                    desired = type(section)()\n                    desired.ParseFromString(self._decode_protobuf_payload(str(encoded)))\n                    if name == "neighbor_info":\n                        if hasattr(desired, "enabled"): desired.enabled = True\n                        if hasattr(desired, "transmit_over_lora"): desired.transmit_over_lora = True\n                        if hasattr(desired, "update_interval") and int(desired.update_interval) < 14400: desired.update_interval = 14400\n                    section.CopyFrom(desired)\n                    stage(f"Modul {name} schreiben")\n'''
    if module_parse not in worker:
        raise SystemExit("v2.1.20 module rule anchor missing")
    worker = worker.replace(module_parse, module_rules, 1)

    # Firmware-owned fields must not produce false whole-protobuf mismatches.
    verify_config_old = '''                    for name, expected in expected_config.items():\n                        section = getattr(verify_node.localConfig, name, None)\n                        if section is None or section.SerializeToString() != expected:\n                            attempt_mismatches.append(f"Config {name}")\n'''
    verify_config_new = '''                    for name, expected in expected_config.items():\n                        section = getattr(verify_node.localConfig, name, None)\n                        if section is None:\n                            attempt_mismatches.append(f"Config {name}")\n                            continue\n                        expected_msg = type(section)(); expected_msg.ParseFromString(expected)\n                        if name == "bluetooth":\n                            for field_name in ("enabled", "mode", "fixed_pin"):\n                                if hasattr(expected_msg, field_name) and getattr(section, field_name) != getattr(expected_msg, field_name):\n                                    attempt_mismatches.append("Config bluetooth"); break\n                        elif name == "position":\n                            actual_cmp = type(section)(); actual_cmp.CopyFrom(section)\n                            expected_cmp = type(section)(); expected_cmp.CopyFrom(expected_msg)\n                            for field_name in ("position_broadcast_secs", "position_broadcast_smart_enabled"):\n                                if hasattr(actual_cmp, field_name): setattr(actual_cmp, field_name, getattr(expected_cmp, field_name))\n                            if actual_cmp.SerializeToString() != expected_cmp.SerializeToString(): attempt_mismatches.append("Config position")\n                        elif section.SerializeToString() != expected:\n                            attempt_mismatches.append(f"Config {name}")\n'''
    if verify_config_old not in worker:
        raise SystemExit("v2.1.20 config verification anchor missing")
    worker = worker.replace(verify_config_old, verify_config_new, 1)

    verify_module_old = '''                    for name, expected in expected_modules.items():\n                        section = getattr(verify_node.moduleConfig, name, None)\n                        if section is None or section.SerializeToString() != expected:\n                            attempt_mismatches.append(f"Modul {name}")\n'''
    verify_module_new = '''                    for name, expected in expected_modules.items():\n                        section = getattr(verify_node.moduleConfig, name, None)\n                        if section is None:\n                            attempt_mismatches.append(f"Modul {name}")\n                            continue\n                        if name == "neighbor_info":\n                            expected_msg = type(section)(); expected_msg.ParseFromString(expected)\n                            if hasattr(section, "update_interval") and int(section.update_interval) != int(expected_msg.update_interval):\n                                attempt_mismatches.append("Modul neighbor_info")\n                        elif section.SerializeToString() != expected:\n                            attempt_mismatches.append(f"Modul {name}")\n'''
    if verify_module_old not in worker:
        raise SystemExit("v2.1.20 module verification anchor missing")
    worker = worker.replace(verify_module_old, verify_module_new, 1)
    source = source[:w0] + worker + source[w1:]

    # --- USB sync UI: explicit full resync button next to automatic delta sync.
    auto_ui = '''        ttk.Checkbutton(\n            setup, text="Log beim USB-Anstecken automatisch laden", variable=self.auto_usb_log_var,\n        ).grid(row=5, column=0, columnspan=2, sticky="w", pady=(6, 0))\n'''
    if auto_ui in source and "Vollständigen Log neu synchronisieren" not in source:
        source = source.replace(auto_ui, auto_ui + '''        ttk.Button(\n            setup, text="Vollständigen Log neu synchronisieren", command=self.start_full_usb_log_sync,\n        ).grid(row=6, column=0, columnspan=2, sticky="ew", pady=(6, 0))\n''', 1)

    sync_helpers = r'''    def _usb_identity_for_port_v2120(self, port: str) -> str:
        for info in list_ports.comports():
            if str(getattr(info, "device", "") or "") == str(port):
                return self._serial_identity_key(self._serial_port_record(info))
        return ""

    def start_full_usb_log_sync(self) -> None:
        if self.worker and self.worker.is_alive():
            messagebox.showinfo("Log-Synchronisierung", "Bitte den laufenden Vorgang zuerst beenden.")
            return
        port = self.selected_port()
        if not port:
            messagebox.showerror("Log-Synchronisierung", "Bitte eine USB-Node/COM-Port auswählen.")
            return
        self._select_serial_port_in_ui(port)
        self.stop_event.clear(); self.start_button.configure(state="disabled"); self.cancel_button.configure(state="normal")
        self.set_transfer_progress(None, "Vollständiger Log-Sync", True)
        self.worker = threading.Thread(target=self._download_worker, args=(port, True, True), daemon=True)
        self.worker.start()
'''
    source = insert_before_method(source, "start_config_profile_provision", sync_helpers)

    # Extend the already v2.1.19-patched download worker with the handshake and DB cursor commit.
    d0, d1 = method_span(source, "_download_worker")
    download = source[d0:d1]
    download = download.replace(
        "    def _download_worker(self, port: str, auto_mode: bool = False) -> None:\n",
        "    def _download_worker(self, port: str, auto_mode: bool = False, force_full: bool = False) -> None:\n",
        1,
    )
    open_anchor = '''            ser.open()\n'''
    handshake = '''            ser.open()\n            sync_usb_identity = self._usb_identity_for_port_v2120(port)\n            sync_managed_node_id = ""\n            sync_generation = 0\n            sync_cursor = 0\n            if auto_mode:\n                if sync_usb_identity:\n                    sync_managed_node_id, sync_generation, sync_cursor = self.repository.log_sync_for_usb(sync_usb_identity)\n                command = (\n                    "JARNSEN_TOOL_FULL 1\\n" if force_full\n                    else f"JARNSEN_TOOL_HELLO 1 {int(sync_generation)} {int(sync_cursor)}\\n"\n                )\n                ser.write(command.encode("ascii")); ser.flush()\n                tool_log("USB_LOG_HANDSHAKE_V2120", port=port, usb_identity=sync_usb_identity, node_id=sync_managed_node_id or "--", generation=sync_generation, cursor=sync_cursor, full=force_full)\n'''
    if download.count(open_anchor) != 1:
        raise SystemExit("v2.1.20 serial open anchor missing")
    download = download.replace(open_anchor, handshake, 1)

    # _finish_payload is the common save/import point, so commit cursor there for serial delta payloads by setting a transient context.
    finish_call = '''            self._finish_payload(\n'''
    if finish_call not in download:
        raise SystemExit("v2.1.20 serial finish anchor missing")
    download = download.replace(
        finish_call,
        '''            self._delta_sync_context_v2120 = {"port": port, "usb_identity": sync_usb_identity, "managed_node_id": sync_managed_node_id} if auto_mode else None\n            self._finish_payload(\n''',
        1,
    )
    source = source[:d0] + download + source[d1:]

    # After a verified payload is saved/imported, record the firmware-provided end cursor.
    f0, f1 = method_span(source, "_finish_payload")
    finish = source[f0:f1]
    tail_anchor = '''        if completion_status:\n            self.events.put(("status_success", completion_status))\n'''
    cursor_commit = '''        sync_context = getattr(self, "_delta_sync_context_v2120", None)\n        if isinstance(sync_context, dict):\n            generation_text = header_value(payload, b"log_generation")\n            cursor_text = header_value(payload, b"cursor_end")\n            sync_mode = header_value(payload, b"sync_mode") or "full"\n            metrics = snapshot_metrics(payload)\n            node_id = normalize_node_id(str(metrics.get("node_id") or sync_context.get("managed_node_id") or ""))\n            try:\n                generation = int(generation_text or 0); cursor = int(cursor_text or 0)\n            except ValueError:\n                generation, cursor = 0, 0\n            if node_id and generation > 0 and cursor >= 0:\n                self.repository.update_log_sync(\n                    node_id, generation, cursor, f"{sync_mode} synchronisiert",\n                    path=str(output), usb_identity=str(sync_context.get("usb_identity") or ""),\n                    last_port=str(sync_context.get("port") or ""),\n                )\n                tool_log("USB_LOG_CURSOR_COMMIT_V2120", node_id=node_id, generation=generation, cursor=cursor, mode=sync_mode)\n            self._delta_sync_context_v2120 = None\n        if completion_status:\n            self.events.put(("status_success", completion_status))\n'''
    if tail_anchor not in finish:
        raise SystemExit("v2.1.20 finish payload tail anchor missing")
    finish = finish.replace(tail_anchor, cursor_commit, 1)
    source = source[:f0] + finish + source[f1:]

    # Richer All-Nodes summary using managed DB even before a first diagnostic log exists.
    a0, a1 = method_span(source, "refresh_all_nodes_overview")
    all_nodes = source[a0:a1]
    latest_anchor = '''            latest = self.repository.latest_log(node_id)\n'''
    if latest_anchor in all_nodes and "management = self.repository.management_for_node" not in all_nodes:
        all_nodes = all_nodes.replace(latest_anchor, latest_anchor + '''            management = self.repository.management_for_node(node_id) or {}\n''', 1)
        all_nodes = all_nodes.replace(
            '''            firmware = str(latest.get("firmware") or "--") if latest else "--"\n            build = str(latest.get("build") or "") if latest else ""\n''',
            '''            firmware = str((management.get("firmware") or (latest.get("firmware") if latest else "")) or "--")\n            build = str((management.get("firmware_build") or (latest.get("build") if latest else "")) or "")\n''',
            1,
        )
        all_nodes = all_nodes.replace(
            '''            captured = str(latest.get("captured_at") or "--").replace("T", " ") if latest else "--"\n''',
            '''            captured = str((latest.get("captured_at") if latest else "") or management.get("last_seen") or "--").replace("T", " ")\n''',
            1,
        )
        # Append management info to the existing position/status text before row insertion.
        insert_marker = '''            warnings = int(metrics.get("warning_count") or 0)\n'''
        if insert_marker in all_nodes:
            all_nodes = all_nodes.replace(insert_marker, '''            profile_name = str(management.get("profile_name") or "").strip()\n            sync_state = str(management.get("log_sync_status") or "").strip()\n            managed_status = str(management.get("status") or "").strip()\n            extras = [value for value in (profile_name and f"Profil:{profile_name}", sync_state, managed_status) if value]\n            if extras:\n                position = (position + " · " if position and position != "--" else "") + " · ".join(extras)\n            warnings = int(metrics.get("warning_count") or 0)\n''', 1)
        source = source[:a0] + all_nodes + source[a1:]

    required = (
        'APP_VERSION = "2.1.20"',
        "CONFIG_PROFILE_DIRECT_ADMIN_V2120",
        "Erweitert / Alle Werte",
        "Long/Short Name beibehalten",
        "USB_LOG_HANDSHAKE_V2120",
        "USB_LOG_CURSOR_COMMIT_V2120",
        "Vollständigen Log neu synchronisieren",
        "log_generation",
        "log_cursor",
    )
    missing = [marker for marker in required if marker not in source]
    if missing:
        raise SystemExit("v2.1.20 validation failed: " + ", ".join(missing))
    return source


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: patch_jarnsen_service_tool_v2120.py <source.py>")
    path = Path(sys.argv[1])
    path.write_text(patch(path.read_text(encoding="utf-8")), encoding="utf-8")
    print(f"Patched {path} to v{APP_VERSION}: full profile editor + symmetric writes + delta log sync")


if __name__ == "__main__":
    main()
