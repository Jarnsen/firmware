"""v2.1.13: profile role/channel display, editing and transfer button states."""
from __future__ import annotations
import re, sys
from pathlib import Path
APP_VERSION = "2.1.13"

def span(text, name):
    s = text.find(f"    def {name}(")
    if s < 0: raise SystemExit(f"method {name} not found")
    ends = [x for x in (text.find("\n    def ", s + 1), text.find("\n    @", s + 1)) if x >= 0]
    return s, min(ends) if ends else len(text)

def replace(text, name, body):
    s, e = span(text, name); return text[:s] + body.rstrip() + "\n" + text[e:]

def insert_before(text, name, body):
    s, _ = span(text, name); return text[:s] + body.rstrip() + "\n\n" + text[s:]

def patch(source):
    source = re.sub(r'APP_VERSION = "[^"]+"', f'APP_VERSION = "{APP_VERSION}"', source, count=1)
    source = source.replace('APP_VERSION != "2.1.12"', 'APP_VERSION != "2.1.13"')
    source = source.replace("App-Version ist nicht v2.1.12", "App-Version ist nicht v2.1.13")

    old = '''            for label, command in (
                ("Von Node einlesen", lambda selected=slot: self.start_config_profile_capture(selected)),
                ("Auf Node übertragen", lambda selected=slot: self.start_config_profile_apply(selected)),
                ("Umbenennen", lambda selected=slot: self._rename_config_profile(selected)),
                ("Löschen", lambda selected=slot: self._delete_config_profile(selected)),
            ):
'''
    new = '''            for label, command in (
                ("Einlesen / aktualisieren", lambda selected=slot: self.start_config_profile_capture(selected)),
                ("Auf Node übertragen", lambda selected=slot: self.start_config_profile_apply(selected)),
                ("Bearbeiten", lambda selected=slot: self._edit_config_profile(selected)),
                ("Umbenennen", lambda selected=slot: self._rename_config_profile(selected)),
                ("Löschen", lambda selected=slot: self._delete_config_profile(selected)),
            ):
'''
    if source.count(old) != 1: raise SystemExit("v2.1.13 action block missing")
    source = source.replace(old, new, 1)

    summary = r'''    def _profile_summary_text(self, profile: dict[str, object] | None) -> str:
        if not isinstance(profile, dict): return "Leer"
        hw = str(profile.get("source_hw") or "Hardware unbekannt")
        fw = str(profile.get("source_firmware") or "Firmware --")
        saved = str(profile.get("saved_at") or "--")
        psk = "enthalten" if profile.get("psk_included") else "nicht gespeichert"
        role, channels = "--", []
        try:
            from meshtastic.protobuf import channel_pb2, localonly_pb2
            cfg = profile.get("config", {}) if isinstance(profile.get("config"), dict) else {}
            encoded = str(cfg.get("device") or "")
            if encoded:
                local = localonly_pb2.LocalConfig(); local.device.ParseFromString(self._decode_protobuf_payload(encoded))
                field = local.device.DESCRIPTOR.fields_by_name.get("role")
                enum = field.enum_type.values_by_number.get(int(local.device.role)) if field else None
                role = enum.name if enum else str(int(local.device.role))
            stored = profile.get("channels", []) if isinstance(profile.get("channels"), list) else []
            for entry in stored:
                if not isinstance(entry, dict) or not entry.get("payload"): continue
                ch = channel_pb2.Channel(); ch.ParseFromString(self._decode_protobuf_payload(str(entry["payload"])))
                ch_role = channel_pb2.Channel.Role.Name(ch.role)
                if ch_role == "DISABLED": continue
                index = int(entry.get("index", ch.index) or 0); name = str(ch.settings.name or "").strip()
                channels.append(f"K{index}:{name} ({ch_role})" if name else f"K{index}:{ch_role}")
        except Exception as exc:
            tool_log("CONFIG_PROFILE_SUMMARY_V2113", error=exc)
        lora = profile.get("lora_summary", {}) if isinstance(profile.get("lora_summary"), dict) else {}
        extra = []
        if lora.get("hop_limit") not in (None, ""): extra.append(f"Hop {lora.get('hop_limit')}")
        if lora.get("tx_power") not in (None, ""): extra.append(f"TX {lora.get('tx_power')}")
        suffix = " · " + " · ".join(extra) if extra else ""
        return f"{hw} · {fw}\nRolle {role} · {', '.join(channels) if channels else 'keine aktiven Kanäle'}\n{saved} · PSK {psk}{suffix}"
'''
    refresh = r'''    def _refresh_config_profile_ui(self) -> None:
        if not hasattr(self, "config_profile_status_labels"): return
        profiles = self.config_profile_store.get("profiles", [])
        profiles = profiles if isinstance(profiles, list) else []
        buttons = getattr(self, "config_profile_action_buttons", [])
        for slot in range(4):
            profile = profiles[slot] if slot < len(profiles) else None
            ok = isinstance(profile, dict)
            if ok: self.config_profile_name_vars[slot].set(str(profile.get("name") or f"Profil {slot + 1}"))
            self.config_profile_status_labels[slot].configure(text=self._profile_summary_text(profile if ok else None))
            base = slot * 5
            if base + 5 <= len(buttons):
                buttons[base].configure(state="normal")
                for offset in range(1, 5): buttons[base + offset].configure(state="normal" if ok else "disabled")
'''
    state = r'''    def _set_config_profile_buttons_state(self, state: str) -> None:
        if state == "normal": self._refresh_config_profile_ui(); return
        for button in getattr(self, "config_profile_action_buttons", []):
            with contextlib.suppress(tk.TclError): button.configure(state=state)
'''
    source = replace(source, "_profile_summary_text", summary)
    source = replace(source, "_refresh_config_profile_ui", refresh)
    source = replace(source, "_set_config_profile_buttons_state", state)

    editor = r'''    def _edit_config_profile(self, slot: int) -> None:
        profiles = self.config_profile_store.get("profiles", [])
        profile = profiles[slot] if isinstance(profiles, list) and slot < len(profiles) else None
        if not isinstance(profile, dict): messagebox.showinfo("Grundprofil", "Dieser Profilplatz ist leer."); return
        try:
            from meshtastic.protobuf import channel_pb2, localonly_pb2
            local = localonly_pb2.LocalConfig(); cfg = profile.get("config", {}) if isinstance(profile.get("config"), dict) else {}
            encoded = str(cfg.get("device") or "")
            if encoded: local.device.ParseFromString(self._decode_protobuf_payload(encoded))
            rows = []
            for entry in profile.get("channels", []) if isinstance(profile.get("channels"), list) else []:
                if not isinstance(entry, dict) or not entry.get("payload"): continue
                ch = channel_pb2.Channel(); ch.ParseFromString(self._decode_protobuf_payload(str(entry["payload"]))); rows.append((entry, ch))
        except Exception as exc:
            messagebox.showerror("Grundprofil bearbeiten", str(exc)); return
        win = tk.Toplevel(self); win.title(f"Grundprofil {slot + 1} bearbeiten"); win.transient(self); win.grab_set(); win.geometry("760x520")
        body = ttk.Frame(win, padding=12); body.pack(fill="both", expand=True)
        name_var = tk.StringVar(value=str(profile.get("name") or f"Profil {slot + 1}"))
        ttk.Label(body, text="Profilname").grid(row=0, column=0, columnspan=3, sticky="w"); ttk.Entry(body, textvariable=name_var).grid(row=1, column=0, columnspan=3, sticky="ew", pady=(0, 8))
        field = local.device.DESCRIPTOR.fields_by_name.get("role"); roles = tuple(v.name for v in field.enum_type.values) if field else tuple(); enum = field.enum_type.values_by_number.get(int(local.device.role)) if field else None
        role_var = tk.StringVar(value=enum.name if enum else "--"); ttk.Label(body, text="Geräterolle").grid(row=2, column=0, sticky="w"); ttk.Combobox(body, state="readonly", values=roles, textvariable=role_var).grid(row=3, column=0, columnspan=3, sticky="ew", pady=(0, 8))
        box = ttk.LabelFrame(body, text="Kanäle", padding=8); box.grid(row=4, column=0, columnspan=3, sticky="nsew"); body.rowconfigure(4, weight=1); box.columnconfigure(2, weight=1)
        ttk.Label(box, text="Index").grid(row=0, column=0); ttk.Label(box, text="Rolle").grid(row=0, column=1); ttk.Label(box, text="Name").grid(row=0, column=2, sticky="w")
        vars_ = []
        for r, (entry, ch) in enumerate(rows, 1):
            rv = tk.StringVar(value=channel_pb2.Channel.Role.Name(ch.role)); nv = tk.StringVar(value=str(ch.settings.name or "")); idx = int(entry.get("index", ch.index) or 0)
            ttk.Label(box, text=f"K{idx}").grid(row=r, column=0); ttk.Combobox(box, state="readonly", values=("DISABLED", "PRIMARY", "SECONDARY"), textvariable=rv, width=14).grid(row=r, column=1, padx=6, pady=2); ttk.Entry(box, textvariable=nv).grid(row=r, column=2, sticky="ew", pady=2); vars_.append((entry, ch, rv, nv))
        def save():
            try:
                if field and role_var.get() in field.enum_type.values_by_name: local.device.role = field.enum_type.values_by_name[role_var.get()].number
                cfg2 = profile.setdefault("config", {}); cfg2["device"] = self._protobuf_payload(local.device)
                for entry, ch, rv, nv in vars_:
                    ch.role = channel_pb2.Channel.Role.Value(rv.get()); ch.settings.name = nv.get().strip(); entry["payload"] = self._protobuf_payload(ch)
                profile["name"] = name_var.get().strip() or f"Profil {slot + 1}"; profile["saved_at"] = now_local().isoformat(timespec="seconds")
                self._save_config_profile_store(); self._refresh_config_profile_ui(); tool_log("CONFIG_PROFILE_EDIT_V2113", slot=slot + 1); win.destroy()
            except Exception as exc: messagebox.showerror("Grundprofil bearbeiten", str(exc), parent=win)
        footer = ttk.Frame(body); footer.grid(row=5, column=0, columnspan=3, sticky="ew", pady=(8, 0)); ttk.Button(footer, text="Von Node neu einlesen", command=lambda: (win.destroy(), self.start_config_profile_capture(slot))).pack(side="left"); ttk.Button(footer, text="Abbrechen", command=win.destroy).pack(side="right"); ttk.Button(footer, text="Speichern", command=save).pack(side="right", padx=6)
        for c in range(3): body.columnconfigure(c, weight=1)
'''
    source = insert_before(source, "_rename_config_profile", editor)
    for marker in ('APP_VERSION = "2.1.13"', '"Einlesen / aktualisieren"', '"Bearbeiten"', "CONFIG_PROFILE_EDIT_V2113", "Rolle {role}", "base = slot * 5"):
        if marker not in source: raise SystemExit(f"v2.1.13 marker missing: {marker}")
    return source

def main():
    if len(sys.argv) != 2: raise SystemExit("usage: patch_jarnsen_service_tool_v2113.py <source.py>")
    p = Path(sys.argv[1]); p.write_text(patch(p.read_text(encoding="utf-8")), encoding="utf-8"); print(f"Patched {p} to v{APP_VERSION}")
if __name__ == "__main__": main()
