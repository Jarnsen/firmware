"""v2.1.15: Hop/TX profile display+editing directly on the proven v2.1.13 profile implementation."""
from __future__ import annotations

import re
import sys
from pathlib import Path

APP_VERSION = "2.1.15"


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
    source = source.replace('APP_VERSION != "2.1.13"', 'APP_VERSION != "2.1.15"')
    source = source.replace("App-Version ist nicht v2.1.13", "App-Version ist nicht v2.1.15")

    summary = r'''    def _profile_summary_text(self, profile: dict[str, object] | None) -> str:
        if not isinstance(profile, dict):
            return "Leer"
        hw = str(profile.get("source_hw") or "Hardware unbekannt")
        fw = str(profile.get("source_firmware") or "Firmware --")
        saved = str(profile.get("saved_at") or "--")
        psk = "enthalten" if profile.get("psk_included") else "nicht gespeichert"
        role = "--"
        hop = "--"
        tx = "--"
        channels: list[str] = []
        try:
            from meshtastic.protobuf import channel_pb2, localonly_pb2
            cfg = profile.get("config", {}) if isinstance(profile.get("config"), dict) else {}
            local = localonly_pb2.LocalConfig()
            device_encoded = str(cfg.get("device") or "")
            lora_encoded = str(cfg.get("lora") or "")
            if device_encoded:
                local.device.ParseFromString(self._decode_protobuf_payload(device_encoded))
                field = local.device.DESCRIPTOR.fields_by_name.get("role")
                enum = field.enum_type.values_by_number.get(int(local.device.role)) if field and field.enum_type else None
                role = enum.name if enum else str(int(local.device.role))
            if lora_encoded:
                local.lora.ParseFromString(self._decode_protobuf_payload(lora_encoded))
                hop = str(int(getattr(local.lora, "hop_limit", 0)))
                tx = str(int(getattr(local.lora, "tx_power", 0)))
            else:
                lora_summary = profile.get("lora_summary", {}) if isinstance(profile.get("lora_summary"), dict) else {}
                if lora_summary.get("hop_limit") not in (None, ""):
                    hop = str(lora_summary.get("hop_limit"))
                if lora_summary.get("tx_power") not in (None, ""):
                    tx = str(lora_summary.get("tx_power"))

            stored = profile.get("channels", []) if isinstance(profile.get("channels"), list) else []
            for entry in stored:
                if not isinstance(entry, dict) or not entry.get("payload"):
                    continue
                channel = channel_pb2.Channel()
                channel.ParseFromString(self._decode_protobuf_payload(str(entry["payload"])))
                channel_role = channel_pb2.Channel.Role.Name(channel.role)
                if channel_role == "DISABLED":
                    continue
                index = int(entry.get("index", channel.index) or 0)
                name = str(channel.settings.name or "").strip()
                channels.append(f"K{index}:{name} ({channel_role})" if name else f"K{index}:{channel_role}")
        except Exception as exc:
            tool_log("CONFIG_PROFILE_SUMMARY_V2115", error=exc)

        channel_text = ", ".join(channels) if channels else "keine aktiven Kanäle"
        return (
            f"{hw} · {fw}\n"
            f"Rolle {role} · Hop {hop} · TX {tx} dBm\n"
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
            device_encoded = str(cfg.get("device") or "")
            lora_encoded = str(cfg.get("lora") or "")
            if device_encoded:
                local.device.ParseFromString(self._decode_protobuf_payload(device_encoded))
            if lora_encoded:
                local.lora.ParseFromString(self._decode_protobuf_payload(lora_encoded))
            rows = []
            for entry in profile.get("channels", []) if isinstance(profile.get("channels"), list) else []:
                if not isinstance(entry, dict) or not entry.get("payload"):
                    continue
                channel = channel_pb2.Channel()
                channel.ParseFromString(self._decode_protobuf_payload(str(entry["payload"])))
                rows.append((entry, channel))
        except Exception as exc:
            messagebox.showerror("Grundprofil bearbeiten", str(exc))
            return

        win = tk.Toplevel(self)
        win.title(f"Grundprofil {slot + 1} bearbeiten")
        win.transient(self)
        win.grab_set()
        win.geometry("820x610")
        body = ttk.Frame(win, padding=12)
        body.pack(fill="both", expand=True)

        name_var = tk.StringVar(value=str(profile.get("name") or f"Profil {slot + 1}"))
        role_field = local.device.DESCRIPTOR.fields_by_name.get("role")
        roles = tuple(value.name for value in role_field.enum_type.values) if role_field and role_field.enum_type else tuple()
        role_enum = role_field.enum_type.values_by_number.get(int(local.device.role)) if role_field and role_field.enum_type else None
        role_var = tk.StringVar(value=role_enum.name if role_enum else "--")
        hop_var = tk.StringVar(value=str(int(getattr(local.lora, "hop_limit", 0))))
        tx_var = tk.StringVar(value=str(int(getattr(local.lora, "tx_power", 0))))

        ttk.Label(body, text="Profilname").grid(row=0, column=0, columnspan=4, sticky="w")
        ttk.Entry(body, textvariable=name_var).grid(row=1, column=0, columnspan=4, sticky="ew", pady=(0, 8))
        ttk.Label(body, text="Geräterolle").grid(row=2, column=0, columnspan=2, sticky="w")
        ttk.Label(body, text="Hop-Limit").grid(row=2, column=2, sticky="w")
        ttk.Label(body, text="TX-Leistung (dBm)").grid(row=2, column=3, sticky="w")
        ttk.Combobox(body, state="readonly", values=roles, textvariable=role_var).grid(
            row=3, column=0, columnspan=2, sticky="ew", padx=(0, 8), pady=(0, 8)
        )
        ttk.Entry(body, textvariable=hop_var, width=10).grid(row=3, column=2, sticky="ew", padx=(0, 8), pady=(0, 8))
        ttk.Entry(body, textvariable=tx_var, width=10).grid(row=3, column=3, sticky="ew", pady=(0, 8))

        box = ttk.LabelFrame(body, text="Kanäle", padding=8)
        box.grid(row=4, column=0, columnspan=4, sticky="nsew")
        body.rowconfigure(4, weight=1)
        box.columnconfigure(2, weight=1)
        ttk.Label(box, text="Index").grid(row=0, column=0)
        ttk.Label(box, text="Rolle").grid(row=0, column=1)
        ttk.Label(box, text="Name").grid(row=0, column=2, sticky="w")
        variables = []
        for row_index, (entry, channel) in enumerate(rows, 1):
            channel_role_var = tk.StringVar(value=channel_pb2.Channel.Role.Name(channel.role))
            channel_name_var = tk.StringVar(value=str(channel.settings.name or ""))
            index = int(entry.get("index", channel.index) or 0)
            ttk.Label(box, text=f"K{index}").grid(row=row_index, column=0)
            ttk.Combobox(
                box,
                state="readonly",
                values=("DISABLED", "PRIMARY", "SECONDARY"),
                textvariable=channel_role_var,
                width=14,
            ).grid(row=row_index, column=1, padx=6, pady=2)
            ttk.Entry(box, textvariable=channel_name_var).grid(row=row_index, column=2, sticky="ew", pady=2)
            variables.append((entry, channel, channel_role_var, channel_name_var))

        def save() -> None:
            try:
                hop_limit = int(hop_var.get().strip())
                tx_power = int(tx_var.get().strip())
                if hop_limit < 0:
                    raise ValueError("Hop-Limit darf nicht negativ sein.")
                if tx_power < 0:
                    raise ValueError("TX-Leistung darf nicht negativ sein.")
                if role_field and role_var.get() in role_field.enum_type.values_by_name:
                    local.device.role = role_field.enum_type.values_by_name[role_var.get()].number
                local.lora.hop_limit = hop_limit
                local.lora.tx_power = tx_power

                config = profile.setdefault("config", {})
                config["device"] = self._protobuf_payload(local.device)
                config["lora"] = self._protobuf_payload(local.lora)
                lora_summary = profile.get("lora_summary")
                if not isinstance(lora_summary, dict):
                    lora_summary = {}
                    profile["lora_summary"] = lora_summary
                lora_summary["hop_limit"] = hop_limit
                lora_summary["tx_power"] = tx_power

                for entry, channel, channel_role_var, channel_name_var in variables:
                    channel.role = channel_pb2.Channel.Role.Value(channel_role_var.get())
                    channel.settings.name = channel_name_var.get().strip()
                    entry["payload"] = self._protobuf_payload(channel)

                profile["name"] = name_var.get().strip() or f"Profil {slot + 1}"
                profile["saved_at"] = now_local().isoformat(timespec="seconds")
                self._save_config_profile_store()
                self._refresh_config_profile_ui()
                tool_log(
                    "CONFIG_PROFILE_EDIT_V2115",
                    slot=slot + 1,
                    role=role_var.get(),
                    hop=hop_limit,
                    tx=tx_power,
                )
                win.destroy()
            except Exception as exc:
                messagebox.showerror("Grundprofil bearbeiten", str(exc), parent=win)

        footer = ttk.Frame(body)
        footer.grid(row=5, column=0, columnspan=4, sticky="ew", pady=(8, 0))
        ttk.Button(
            footer,
            text="Von Node neu einlesen",
            command=lambda: (win.destroy(), self.start_config_profile_capture(slot)),
        ).pack(side="left")
        ttk.Button(footer, text="Abbrechen", command=win.destroy).pack(side="right")
        ttk.Button(footer, text="Speichern", command=save).pack(side="right", padx=6)
        for column in range(4):
            body.columnconfigure(column, weight=1)
'''

    source = replace_method(source, "_profile_summary_text", summary)
    source = replace_method(source, "_edit_config_profile", editor)

    # Current firmware has no serial command that emulates the physical OK/Mitte
    # action used by V3 log export. Do not send arbitrary CR/LF into the Meshtastic
    # serial link. The tool starts listening immediately and states what it waits for.
    source = source.replace(
        f'{{port}} offen - jetzt Export am Gerät bestätigen',
        f'{{port}} offen - warte auf Logexport der Node',
    )
    if "SERIAL_LOG_AUTO_ENTER" in source:
        raise SystemExit("v2.1.15 must not contain a fake serial auto-enter trigger")

    required = (
        'APP_VERSION = "2.1.15"',
        "CONFIG_PROFILE_SUMMARY_V2115",
        "CONFIG_PROFILE_EDIT_V2115",
        "Hop-Limit",
        "TX-Leistung (dBm)",
        'config["lora"] = self._protobuf_payload(local.lora)',
        "long_name = self.config_target_long_var.get().strip()",
        "short_name = self.config_target_short_var.get().strip()",
    )
    missing = [marker for marker in required if marker not in source]
    if missing:
        raise SystemExit("v2.1.15 validation failed: " + ", ".join(missing))
    return source


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: patch_jarnsen_service_tool_v2115.py <source.py>")
    path = Path(sys.argv[1])
    path.write_text(patch(path.read_text(encoding="utf-8")), encoding="utf-8")
    print(f"Patched {path} to v{APP_VERSION}: editable Hop/TX + safe serial listener")


if __name__ == "__main__":
    main()
