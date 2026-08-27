"""v2.1.14: complete base-profile identity/radio/Bluetooth cloning and automatic serial log start."""
from __future__ import annotations

import re
import sys
from pathlib import Path

APP_VERSION = "2.1.14"


def method_span(text: str, name: str) -> tuple[int, int]:
    start = text.find(f"    def {name}(")
    if start < 0:
        raise SystemExit(f"method {name} not found")
    next_method = text.find("\n    def ", start + 1)
    next_decorator = text.find("\n    @", start + 1)
    candidates = [value for value in (next_method, next_decorator) if value >= 0]
    return start, min(candidates) if candidates else len(text)


def replace_method(text: str, name: str, replacement: str) -> str:
    start, end = method_span(text, name)
    return text[:start] + replacement.rstrip() + "\n" + text[end:]


def patch(source: str) -> str:
    source = re.sub(r'APP_VERSION = "[^"]+"', f'APP_VERSION = "{APP_VERSION}"', source, count=1)
    source = source.replace('APP_VERSION != "2.1.13"', 'APP_VERSION != "2.1.14"')
    source = source.replace("App-Version ist nicht v2.1.13", "App-Version ist nicht v2.1.14")

    summary = r'''    def _profile_summary_text(self, profile: dict[str, object] | None) -> str:
        if not isinstance(profile, dict):
            return "Leer"
        hw = str(profile.get("source_hw") or "Hardware unbekannt")
        fw = str(profile.get("source_firmware") or "Firmware --")
        saved = str(profile.get("saved_at") or "--")
        long_name = str(profile.get("source_long_name") or "--")
        short_name = str(profile.get("source_short_name") or "--")
        psk = "enthalten" if profile.get("psk_included") else "nicht gespeichert"
        role = "--"
        hop = "--"
        tx = "--"
        bt_text = "BT --"
        channels: list[str] = []
        try:
            from meshtastic.protobuf import channel_pb2, localonly_pb2

            cfg = profile.get("config", {}) if isinstance(profile.get("config"), dict) else {}
            local = localonly_pb2.LocalConfig()
            for section_name in ("device", "lora", "bluetooth"):
                encoded = str(cfg.get(section_name) or "")
                if encoded and hasattr(local, section_name):
                    getattr(local, section_name).ParseFromString(self._decode_protobuf_payload(encoded))

            field = local.device.DESCRIPTOR.fields_by_name.get("role")
            enum = field.enum_type.values_by_number.get(int(local.device.role)) if field and field.enum_type else None
            role = enum.name if enum else str(int(local.device.role))

            if hasattr(local, "lora"):
                hop = str(int(getattr(local.lora, "hop_limit", 0)))
                tx = str(int(getattr(local.lora, "tx_power", 0)))

            if hasattr(local, "bluetooth"):
                enabled = bool(getattr(local.bluetooth, "enabled", False))
                mode_field = local.bluetooth.DESCRIPTOR.fields_by_name.get("mode")
                mode_value = int(getattr(local.bluetooth, "mode", 0))
                mode_enum = mode_field.enum_type.values_by_number.get(mode_value) if mode_field and mode_field.enum_type else None
                mode_name = mode_enum.name if mode_enum else str(mode_value)
                if not enabled:
                    bt_text = "BT aus"
                else:
                    bt_text = f"BT {mode_name}"
                    if mode_name == "FIXED_PIN" and hasattr(local.bluetooth, "fixed_pin"):
                        bt_text += f" · PIN {int(local.bluetooth.fixed_pin):06d}"

            stored = profile.get("channels", []) if isinstance(profile.get("channels"), list) else []
            for entry in stored:
                if not isinstance(entry, dict) or not entry.get("payload"):
                    continue
                ch = channel_pb2.Channel()
                ch.ParseFromString(self._decode_protobuf_payload(str(entry["payload"])))
                ch_role = channel_pb2.Channel.Role.Name(ch.role)
                if ch_role == "DISABLED":
                    continue
                index = int(entry.get("index", ch.index) or 0)
                name = str(ch.settings.name or "").strip()
                channels.append(f"K{index}:{name} ({ch_role})" if name else f"K{index}:{ch_role}")
        except Exception as exc:
            tool_log("CONFIG_PROFILE_SUMMARY_V2114", error=exc)

        channel_text = ", ".join(channels) if channels else "keine aktiven Kanäle"
        return (
            f"{hw} · {fw}\n"
            f"{long_name} / {short_name} · Rolle {role}\n"
            f"Hop {hop} · TX {tx} dBm · {bt_text}\n"
            f"{channel_text}\n"
            f"{saved} · PSK {psk}"
        )
'''

    editor = r'''    def _edit_config_profile(self, slot: int) -> None:
        profiles = self.config_profile_store.get("profiles", [])
        profile = profiles[slot] if isinstance(profiles, list) and slot < len(profiles) else None
        if not isinstance(profile, dict):
            messagebox.showinfo("Grundprofil", "Dieser Profilplatz ist leer.")
            return
        try:
            from meshtastic.protobuf import channel_pb2, localonly_pb2

            local = localonly_pb2.LocalConfig()
            cfg = profile.get("config", {}) if isinstance(profile.get("config"), dict) else {}
            for section_name in ("device", "lora", "bluetooth"):
                encoded = str(cfg.get(section_name) or "")
                if encoded and hasattr(local, section_name):
                    getattr(local, section_name).ParseFromString(self._decode_protobuf_payload(encoded))

            rows = []
            for entry in profile.get("channels", []) if isinstance(profile.get("channels"), list) else []:
                if not isinstance(entry, dict) or not entry.get("payload"):
                    continue
                ch = channel_pb2.Channel()
                ch.ParseFromString(self._decode_protobuf_payload(str(entry["payload"])))
                rows.append((entry, ch))
        except Exception as exc:
            messagebox.showerror("Grundprofil bearbeiten", str(exc))
            return

        win = tk.Toplevel(self)
        win.title(f"Grundprofil {slot + 1} bearbeiten")
        win.transient(self)
        win.grab_set()
        win.geometry("920x650")
        body = ttk.Frame(win, padding=12)
        body.pack(fill="both", expand=True)

        name_var = tk.StringVar(value=str(profile.get("name") or f"Profil {slot + 1}"))
        long_var = tk.StringVar(value=str(profile.get("source_long_name") or ""))
        short_var = tk.StringVar(value=str(profile.get("source_short_name") or ""))

        role_field = local.device.DESCRIPTOR.fields_by_name.get("role")
        roles = tuple(v.name for v in role_field.enum_type.values) if role_field and role_field.enum_type else tuple()
        role_enum = role_field.enum_type.values_by_number.get(int(local.device.role)) if role_field and role_field.enum_type else None
        role_var = tk.StringVar(value=role_enum.name if role_enum else "--")

        hop_var = tk.StringVar(value=str(int(getattr(local.lora, "hop_limit", 0))))
        tx_var = tk.StringVar(value=str(int(getattr(local.lora, "tx_power", 0))))

        bt_enabled_var = tk.BooleanVar(value=bool(getattr(local.bluetooth, "enabled", False)))
        bt_mode_field = local.bluetooth.DESCRIPTOR.fields_by_name.get("mode")
        bt_modes = tuple(v.name for v in bt_mode_field.enum_type.values) if bt_mode_field and bt_mode_field.enum_type else tuple()
        bt_mode_value = int(getattr(local.bluetooth, "mode", 0))
        bt_mode_enum = bt_mode_field.enum_type.values_by_number.get(bt_mode_value) if bt_mode_field and bt_mode_field.enum_type else None
        bt_mode_var = tk.StringVar(value=bt_mode_enum.name if bt_mode_enum else (bt_modes[0] if bt_modes else "--"))
        bt_pin_value = int(getattr(local.bluetooth, "fixed_pin", 0) or 0)
        bt_pin_var = tk.StringVar(value=f"{bt_pin_value:06d}" if bt_pin_value else "")

        ttk.Label(body, text="Profilname").grid(row=0, column=0, columnspan=5, sticky="w")
        ttk.Entry(body, textvariable=name_var).grid(row=1, column=0, columnspan=5, sticky="ew", pady=(0, 8))

        ttk.Label(body, text="Long Name").grid(row=2, column=0, columnspan=2, sticky="w")
        ttk.Label(body, text="Short Name").grid(row=2, column=2, sticky="w")
        ttk.Label(body, text="Geräterolle").grid(row=2, column=3, columnspan=2, sticky="w")
        ttk.Entry(body, textvariable=long_var).grid(row=3, column=0, columnspan=2, sticky="ew", padx=(0, 6), pady=(0, 8))
        ttk.Entry(body, textvariable=short_var, width=10).grid(row=3, column=2, sticky="ew", padx=(0, 6), pady=(0, 8))
        ttk.Combobox(body, state="readonly", values=roles, textvariable=role_var).grid(
            row=3, column=3, columnspan=2, sticky="ew", pady=(0, 8)
        )

        ttk.Checkbutton(body, text="Bluetooth aktiviert", variable=bt_enabled_var).grid(row=4, column=0, sticky="w")
        ttk.Label(body, text="BT Pairing").grid(row=4, column=1, sticky="w")
        ttk.Label(body, text="Feste BT-PIN").grid(row=4, column=2, sticky="w")
        ttk.Label(body, text="Hop-Limit").grid(row=4, column=3, sticky="w")
        ttk.Label(body, text="TX (dBm)").grid(row=4, column=4, sticky="w")
        ttk.Label(body, text="").grid(row=5, column=0, sticky="ew")
        ttk.Combobox(body, state="readonly", values=bt_modes, textvariable=bt_mode_var).grid(
            row=5, column=1, sticky="ew", padx=(0, 6), pady=(0, 8)
        )
        ttk.Entry(body, textvariable=bt_pin_var).grid(row=5, column=2, sticky="ew", padx=(0, 6), pady=(0, 8))
        ttk.Entry(body, textvariable=hop_var).grid(row=5, column=3, sticky="ew", padx=(0, 6), pady=(0, 8))
        ttk.Entry(body, textvariable=tx_var).grid(row=5, column=4, sticky="ew", pady=(0, 8))

        box = ttk.LabelFrame(body, text="Kanäle", padding=8)
        box.grid(row=6, column=0, columnspan=5, sticky="nsew")
        body.rowconfigure(6, weight=1)
        box.columnconfigure(2, weight=1)
        ttk.Label(box, text="Index").grid(row=0, column=0)
        ttk.Label(box, text="Rolle").grid(row=0, column=1)
        ttk.Label(box, text="Name").grid(row=0, column=2, sticky="w")
        vars_ = []
        for row_index, (entry, ch) in enumerate(rows, 1):
            role_value = tk.StringVar(value=channel_pb2.Channel.Role.Name(ch.role))
            channel_name = tk.StringVar(value=str(ch.settings.name or ""))
            index = int(entry.get("index", ch.index) or 0)
            ttk.Label(box, text=f"K{index}").grid(row=row_index, column=0)
            ttk.Combobox(
                box,
                state="readonly",
                values=("DISABLED", "PRIMARY", "SECONDARY"),
                textvariable=role_value,
                width=14,
            ).grid(row=row_index, column=1, padx=6, pady=2)
            ttk.Entry(box, textvariable=channel_name).grid(row=row_index, column=2, sticky="ew", pady=2)
            vars_.append((entry, ch, role_value, channel_name))

        def save() -> None:
            try:
                long_name = long_var.get().strip()
                short_name = short_var.get().strip()
                if not long_name:
                    raise ValueError("Long Name darf nicht leer sein.")
                if not short_name or len(short_name) > 4:
                    raise ValueError("Short Name muss 1 bis 4 Zeichen lang sein.")

                hop_limit = int(hop_var.get().strip())
                tx_power = int(tx_var.get().strip())
                if not 0 <= hop_limit <= 7:
                    raise ValueError("Hop-Limit muss zwischen 0 und 7 liegen.")
                if not 0 <= tx_power <= 30:
                    raise ValueError("TX muss zwischen 0 und 30 dBm liegen.")

                if role_field and role_var.get() in role_field.enum_type.values_by_name:
                    local.device.role = role_field.enum_type.values_by_name[role_var.get()].number
                local.lora.hop_limit = hop_limit
                local.lora.tx_power = tx_power

                if hasattr(local.bluetooth, "enabled"):
                    local.bluetooth.enabled = bool(bt_enabled_var.get())
                if bt_mode_field and bt_mode_var.get() in bt_mode_field.enum_type.values_by_name:
                    local.bluetooth.mode = bt_mode_field.enum_type.values_by_name[bt_mode_var.get()].number
                pin_text = bt_pin_var.get().strip()
                if bt_mode_var.get() == "FIXED_PIN":
                    if not re.fullmatch(r"\d{6}", pin_text):
                        raise ValueError("Bei FIXED_PIN muss die Bluetooth-PIN genau 6 Ziffern haben.")
                    local.bluetooth.fixed_pin = int(pin_text)
                elif pin_text:
                    if not pin_text.isdigit() or len(pin_text) > 6:
                        raise ValueError("Bluetooth-PIN muss numerisch und höchstens 6-stellig sein.")
                    local.bluetooth.fixed_pin = int(pin_text)
                elif hasattr(local.bluetooth, "fixed_pin"):
                    local.bluetooth.fixed_pin = 0

                cfg2 = profile.setdefault("config", {})
                cfg2["device"] = self._protobuf_payload(local.device)
                cfg2["lora"] = self._protobuf_payload(local.lora)
                cfg2["bluetooth"] = self._protobuf_payload(local.bluetooth)

                for entry, ch, role_value, channel_name in vars_:
                    ch.role = channel_pb2.Channel.Role.Value(role_value.get())
                    ch.settings.name = channel_name.get().strip()
                    entry["payload"] = self._protobuf_payload(ch)

                profile["name"] = name_var.get().strip() or f"Profil {slot + 1}"
                profile["source_long_name"] = long_name
                profile["source_short_name"] = short_name[:4]
                profile["lora_summary"] = {
                    "hop_limit": int(local.lora.hop_limit),
                    "tx_power": int(local.lora.tx_power),
                    "override_frequency": float(getattr(local.lora, "override_frequency", 0.0) or 0.0),
                }
                profile["bluetooth_summary"] = {
                    "enabled": bool(getattr(local.bluetooth, "enabled", False)),
                    "mode": bt_mode_var.get(),
                    "fixed_pin": int(getattr(local.bluetooth, "fixed_pin", 0) or 0),
                }
                profile["saved_at"] = now_local().isoformat(timespec="seconds")
                self._save_config_profile_store()
                self._refresh_config_profile_ui()
                tool_log(
                    "CONFIG_PROFILE_EDIT_V2114",
                    slot=slot + 1,
                    role=role_var.get(),
                    hop=hop_limit,
                    tx=tx_power,
                    bt=bt_mode_var.get(),
                )
                win.destroy()
            except Exception as exc:
                messagebox.showerror("Grundprofil bearbeiten", str(exc), parent=win)

        footer = ttk.Frame(body)
        footer.grid(row=7, column=0, columnspan=5, sticky="ew", pady=(8, 0))
        ttk.Button(
            footer,
            text="Von Node neu einlesen",
            command=lambda: (win.destroy(), self.start_config_profile_capture(slot)),
        ).pack(side="left")
        ttk.Button(footer, text="Abbrechen", command=win.destroy).pack(side="right")
        ttk.Button(footer, text="Speichern", command=save).pack(side="right", padx=6)
        for column in range(5):
            body.columnconfigure(column, weight=1)
'''

    start_apply = r'''    def start_config_profile_apply(self, slot: int) -> None:
        if self.worker and self.worker.is_alive():
            messagebox.showinfo("Grundprofil", "Bitte den laufenden Vorgang zuerst beenden.")
            return
        profiles = self.config_profile_store.get("profiles", [])
        profile = profiles[slot] if isinstance(profiles, list) and slot < len(profiles) else None
        if not isinstance(profile, dict):
            messagebox.showinfo("Grundprofil", "Dieser Profil-Slot ist noch leer.")
            return

        # Since v2.1.14 Long/Short Name belong to the base profile. Existing
        # older profiles fall back to the target fields until they are re-read.
        long_name = str(profile.get("source_long_name") or self.config_target_long_var.get()).strip()
        short_name = str(profile.get("source_short_name") or self.config_target_short_var.get()).strip()
        if not long_name:
            messagebox.showerror(
                "Grundprofil übertragen",
                "Im Profil fehlt der Long Name. Profil bitte neu einlesen oder unter Bearbeiten ergänzen.",
            )
            return
        if not short_name or len(short_name) > 4:
            messagebox.showerror(
                "Grundprofil übertragen",
                "Im Profil fehlt ein gültiger Short Name (1 bis 4 Zeichen). Profil bitte bearbeiten.",
            )
            return
        self.config_target_long_var.set(long_name)
        self.config_target_short_var.set(short_name[:4])

        try:
            connection = self._config_profile_connection()
            frequency_override = self._selected_authorized_frequency()
        except Exception as exc:
            messagebox.showerror("Grundprofil übertragen", str(exc))
            return
        if frequency_override is not None:
            if not messagebox.askyesno(
                "Authorized 915",
                f"Für diese Übertragung wird exakt {frequency_override:g} MHz als override_frequency gesetzt.\n\n"
                "Diese Auswahl ist nur für die dafür angepasste Authorized-915-Firmware vorgesehen. Fortfahren?",
            ):
                return
        apply_psk = bool(self.config_apply_psk_var.get()) and bool(profile.get("psk_included"))
        self._set_config_profile_buttons_state("disabled")
        self.status_level = "normal"
        self.status.configure(text=f"Übertrage Grundprofil {slot + 1} auf {connection[2]} …")
        self._update_status_badge()
        self.worker = threading.Thread(
            target=self._config_profile_apply_worker,
            args=(slot, profile, long_name, short_name[:4], apply_psk, frequency_override, connection),
            daemon=True,
        )
        self.worker.start()
'''

    source = replace_method(source, "_profile_summary_text", summary)
    source = replace_method(source, "_edit_config_profile", editor)
    source = replace_method(source, "start_config_profile_apply", start_apply)

    capture_anchor = '''            source_hw, source_firmware = self._config_profile_metadata(interface)
            config_sections: dict[str, str] = {}
'''
    capture_replacement = '''            source_hw, source_firmware = self._config_profile_metadata(interface)
            source_long_name = str(interface.getLongName() or "").strip()
            source_short_name = str(interface.getShortName() or "").strip()[:4]
            config_sections: dict[str, str] = {}
'''
    if source.count(capture_anchor) != 1:
        raise SystemExit("v2.1.14 capture identity anchor missing or ambiguous")
    source = source.replace(capture_anchor, capture_replacement, 1)

    profile_anchor = '''            profile = {
                "schema": 1,
                "name": name,
                "saved_at": now_local().isoformat(timespec="seconds"),
                "source_hw": source_hw,
                "source_firmware": source_firmware,
                "psk_included": include_psk,
'''
    profile_replacement = '''            bluetooth = getattr(node.localConfig, "bluetooth", None)
            bluetooth_summary: dict[str, object] = {}
            if bluetooth is not None:
                mode_field = bluetooth.DESCRIPTOR.fields_by_name.get("mode")
                mode_value = int(getattr(bluetooth, "mode", 0))
                mode_enum = mode_field.enum_type.values_by_number.get(mode_value) if mode_field and mode_field.enum_type else None
                bluetooth_summary = {
                    "enabled": bool(getattr(bluetooth, "enabled", False)),
                    "mode": mode_enum.name if mode_enum else str(mode_value),
                    "fixed_pin": int(getattr(bluetooth, "fixed_pin", 0) or 0),
                }

            profile = {
                "schema": 1,
                "name": name,
                "saved_at": now_local().isoformat(timespec="seconds"),
                "source_hw": source_hw,
                "source_firmware": source_firmware,
                "source_long_name": source_long_name,
                "source_short_name": source_short_name,
                "psk_included": include_psk,
'''
    if source.count(profile_anchor) != 1:
        raise SystemExit("v2.1.14 profile identity anchor missing or ambiguous")
    source = source.replace(profile_anchor, profile_replacement, 1)

    profile_bt_anchor = '''                "channels": channels,
                "lora_summary": lora_summary,
                "exclusions": [
                    "node_id",
                    "owner_long_name",
                    "owner_short_name",
'''
    profile_bt_replacement = '''                "channels": channels,
                "lora_summary": lora_summary,
                "bluetooth_summary": bluetooth_summary,
                "exclusions": [
                    "node_id",
'''
    if source.count(profile_bt_anchor) != 1:
        raise SystemExit("v2.1.14 capture exclusions anchor missing or ambiguous")
    source = source.replace(profile_bt_anchor, profile_bt_replacement, 1)

    capture_log_anchor = '''                source_hw=source_hw or "--",
                psk=include_psk,
                channels=len(channels),
'''
    capture_log_replacement = '''                source_hw=source_hw or "--",
                long_name=source_long_name or "--",
                short_name=source_short_name or "--",
                psk=include_psk,
                channels=len(channels),
                bt=bluetooth_summary.get("mode", "--"),
'''
    if source.count(capture_log_anchor) != 1:
        raise SystemExit("v2.1.14 capture log anchor missing or ambiguous")
    source = source.replace(capture_log_anchor, capture_log_replacement, 1)

    mismatch_anchor = '''            skip_on_mismatch = {"display", "position", "power", "bluetooth"}
            if hardware_mismatch:
                warnings.append(
                    f"Hardware abweichend ({source_hw} → {target_hw}); Display/Position/Power/Bluetooth wurden übersprungen."
                )
'''
    mismatch_replacement = '''            # Bluetooth pairing policy is portable and intentionally cloned even
            # across Tracker/V3 profiles. Hardware-specific display/position/
            # power sections remain protected on a hardware mismatch.
            skip_on_mismatch = {"display", "position", "power"}
            if hardware_mismatch:
                warnings.append(
                    f"Hardware abweichend ({source_hw} → {target_hw}); Display/Position/Power wurden übersprungen."
                )
'''
    if source.count(mismatch_anchor) != 1:
        raise SystemExit("v2.1.14 hardware mismatch anchor missing or ambiguous")
    source = source.replace(mismatch_anchor, mismatch_replacement, 1)

    module_anchor = '''            module_sections = profile.get("module_config", {})
'''
    role_reinforce = '''            # Some Meshtastic builds acknowledge the generic device write but do not
            # persist a role change until the device section is written again at
            # the end of the LocalConfig transaction. Reinforce exactly the role
            # stored in the profile and include it in read-back verification.
            if isinstance(config_sections, dict) and config_sections.get("device"):
                device_section = getattr(node.localConfig, "device", None)
                if device_section is not None and hasattr(device_section, "role"):
                    desired_device = type(device_section)()
                    desired_device.ParseFromString(
                        self._decode_protobuf_payload(str(config_sections["device"]))
                    )
                    if hasattr(desired_device, "role"):
                        device_section.role = desired_device.role
                        try:
                            node.writeConfig("device")
                            expected_config["device"] = device_section.SerializeToString()
                            tool_log(
                                "CONFIG_PROFILE_ROLE_WRITE_V2114",
                                role=int(device_section.role),
                                transport=connection[0],
                            )
                            time.sleep(0.15)
                        except Exception as exc:
                            warnings.append(f"Geräterolle nicht erneut geschrieben: {exc}")

            module_sections = profile.get("module_config", {})
'''
    if source.count(module_anchor) != 1:
        raise SystemExit("v2.1.14 role reinforcement anchor missing or ambiguous")
    source = source.replace(module_anchor, role_reinforce, 1)

    serial_anchor = '''            ser.open()
            self.events.put(
                ("status", f"{port} offen - jetzt Export am Gerät bestätigen")
            )
            self.events.put(("progress_detail", (None, "Warte auf Export", True)))

            scan = bytearray()
'''
    serial_replacement = '''            ser.open()
            # The firmware already uses Enter as the serial export confirmation.
            # Trigger it from the tool so a USB log download needs only one click.
            try:
                time.sleep(0.12)
                ser.write(b"\r\n")
                ser.flush()
                self.events.put(
                    ("status", f"{port} offen - Logexport automatisch per Enter gestartet")
                )
                self.events.put(("progress_detail", (None, "Export automatisch gestartet", True)))
                tool_log("SERIAL_LOG_AUTO_ENTER_V2114", port=port, result="sent")
            except (OSError, serial.SerialException) as exc:
                self.events.put(
                    ("status", f"{port} offen - Auto-Enter fehlgeschlagen, Export bitte am Gerät bestätigen")
                )
                self.events.put(("progress_detail", (None, "Warte auf Export", True)))
                tool_log("SERIAL_LOG_AUTO_ENTER_V2114", port=port, result="fallback", error=exc)

            scan = bytearray()
'''
    if source.count(serial_anchor) != 1:
        raise SystemExit("v2.1.14 serial auto-enter anchor missing or ambiguous")
    source = source.replace(serial_anchor, serial_replacement, 1)

    old_dialog = "Node-ID, Long/Short Name, Device-Keys und feste Position wurden nicht übernommen."
    new_dialog = (
        "Long/Short Name, Rolle, Hop/TX und Bluetooth wurden mit eingelesen. "
        "Node-ID, Device-Keys und feste Position bleiben ausgeschlossen."
    )
    if old_dialog not in source:
        raise SystemExit("v2.1.14 saved-profile dialog anchor missing")
    source = source.replace(old_dialog, new_dialog, 1)

    required = (
        'APP_VERSION = "2.1.14"',
        "CONFIG_PROFILE_SUMMARY_V2114",
        "CONFIG_PROFILE_EDIT_V2114",
        "CONFIG_PROFILE_ROLE_WRITE_V2114",
        "SERIAL_LOG_AUTO_ENTER_V2114",
        '"source_long_name": source_long_name',
        '"source_short_name": source_short_name',
        '"bluetooth_summary": bluetooth_summary',
        'cfg2["bluetooth"] = self._protobuf_payload(local.bluetooth)',
        "Hop-Limit",
        "TX (dBm)",
        "Feste BT-PIN",
        'skip_on_mismatch = {"display", "position", "power"}',
        'ser.write(b"\\r\\n")',
    )
    missing = [marker for marker in required if marker not in source]
    if missing:
        raise SystemExit("v2.1.14 validation failed: " + ", ".join(missing))
    return source


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: patch_jarnsen_service_tool_v2114.py <source.py>")
    path = Path(sys.argv[1])
    source = path.read_text(encoding="utf-8")
    path.write_text(patch(source), encoding="utf-8")
    print(
        f"Patched {path} to v{APP_VERSION}: profile names/role/hop/TX/Bluetooth + serial auto-enter"
    )


if __name__ == "__main__":
    main()
