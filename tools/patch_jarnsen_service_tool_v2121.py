"""v2.1.21: tabbed full profile editor with descriptor-driven controls and gated RF authorization UI."""
from __future__ import annotations

import re
import sys
from pathlib import Path

APP_VERSION = "2.1.21"


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


def replace_method(text: str, name: str, replacement: str) -> str:
    start, end = method_span(text, name)
    return text[:start] + replacement.rstrip() + "\n" + text[end:]


def insert_before_method(text: str, name: str, code: str) -> str:
    start, _ = method_span(text, name)
    return text[:start] + code.rstrip() + "\n\n" + text[start:]


def patch(source: str) -> str:
    source = re.sub(r'APP_VERSION = "[^"]+"', f'APP_VERSION = "{APP_VERSION}"', source, count=1)
    source = source.replace('APP_VERSION != "2.1.20"', 'APP_VERSION != "2.1.21"')
    source = source.replace("App-Version ist nicht v2.1.20", "App-Version ist nicht v2.1.21")

    version_anchor = f'APP_VERSION = "{APP_VERSION}"'
    if "JARNSEN_AUTHORIZED_RF_ENABLED" not in source:
        source = source.replace(
            version_anchor,
            version_anchor
            + '\n\n# Authorized RF extension stays hard-disabled until the exact A/B frequencies and matching firmware are configured.\n'
            + 'JARNSEN_AUTHORIZED_RF_ENABLED = False\n'
            + 'JARNSEN_AUTHORIZED_FREQUENCY_A_MHZ = 0.0\n'
            + 'JARNSEN_AUTHORIZED_FREQUENCY_B_MHZ = 0.0\n',
            1,
        )

    helpers = r'''    @staticmethod
    def _profile_field_label_v2121(path: str) -> str:
        labels = {
            "role": "Geräterolle", "rebroadcast_mode": "Rebroadcast", "node_info_broadcast_secs": "Node-Info Intervall",
            "region": "Region", "modem_preset": "Modem-Preset", "use_preset": "Preset verwenden",
            "hop_limit": "Hop-Limit", "tx_power": "TX-Leistung (dBm)", "override_frequency": "Frequenz-Override (MHz)",
            "bandwidth": "Bandbreite", "spread_factor": "Spread Factor", "coding_rate": "Coding Rate",
            "frequency_offset": "Frequenz-Offset", "override_duty_cycle": "Sendelimit/Duty-Cycle Override",
            "enabled": "Aktiviert", "mode": "Modus", "fixed_pin": "Fester PIN",
            "position_broadcast_secs": "Positionsintervall (s)", "position_broadcast_smart_enabled": "Smart Position",
            "broadcast_smart_minimum_distance": "Smart Mindeststrecke (m)",
            "broadcast_smart_minimum_interval_secs": "Smart Mindestintervall (s)", "gps_update_interval": "GPS-Updateintervall",
            "fixed_position": "Feste Position", "position_flags": "Positionsflags", "update_interval": "Updateintervall (s)",
            "transmit_over_lora": "Über LoRa senden", "name": "Name", "uplink_enabled": "Uplink aktiviert",
            "downlink_enabled": "Downlink aktiviert", "position_precision": "Positionsgenauigkeit", "index": "Index",
        }
        leaf = path.rsplit(".", 1)[-1]
        return labels.get(leaf, leaf.replace("_", " ").strip().title())

    @staticmethod
    def _profile_badge_v2121(kind: str, name: str) -> str:
        if (kind, name) in (("config", "position"), ("module", "neighbor_info")):
            return "JARNSEN"
        return "STANDARD"

    @staticmethod
    def _profile_rf_authorization_ready_v2121() -> bool:
        try:
            return bool(
                JARNSEN_AUTHORIZED_RF_ENABLED
                and float(JARNSEN_AUTHORIZED_FREQUENCY_A_MHZ) > 0.0
                and float(JARNSEN_AUTHORIZED_FREQUENCY_B_MHZ) > 0.0
            )
        except Exception:
            return False

    def _profile_rf_mode_active_v2121(self, profile: dict[str, object]) -> bool:
        return self._profile_rf_authorization_ready_v2121() and str(profile.get("jarnsen_rf_mode") or "Standard") in (
            "Freigabe Frequenz A", "Freigabe Frequenz B"
        )

    @staticmethod
    def _profile_tab_items_v2121(profile: dict[str, object], tab: str) -> list[tuple[str, str]]:
        configs = sorted((profile.get("config") or {}).keys()) if isinstance(profile.get("config"), dict) else []
        modules = sorted((profile.get("module_config") or {}).keys()) if isinstance(profile.get("module_config"), dict) else []
        channels = [str(int(item.get("index", 0))) for item in (profile.get("channels") or []) if isinstance(item, dict)]
        if tab == "Allgemein":
            return [("config", n) for n in configs if n in ("device", "network")]
        if tab == "Funk & Kanal":
            return [("config", n) for n in configs if n == "lora"] + [("channel", n) for n in channels]
        if tab == "Mesh / Routing":
            return [("config", n) for n in configs if n in ("device", "network")] + [("module", n) for n in modules if n in ("routing", "neighbor_info")]
        if tab == "Position / GPS":
            return [("config", n) for n in configs if n == "position"]
        if tab == "Bluetooth":
            return [("config", n) for n in configs if n == "bluetooth"]
        if tab == "Display & Energie":
            return [("config", n) for n in configs if n in ("display", "power")]
        if tab == "Module":
            return [("module", n) for n in modules]
        if tab == "Sicherheit":
            return [("config", n) for n in configs if n == "security"]
        return [("config", n) for n in configs] + [("module", n) for n in modules] + [("channel", n) for n in channels]

    @staticmethod
    def _profile_scroll_tab_v2121(notebook, title: str):
        shell = ttk.Frame(notebook)
        notebook.add(shell, text=title)
        canvas = tk.Canvas(shell, highlightthickness=0, borderwidth=0)
        scrollbar = ttk.Scrollbar(shell, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)
        inner = ttk.Frame(canvas, padding=10)
        window_id = canvas.create_window((0, 0), window=inner, anchor="nw")
        inner.bind("<Configure>", lambda _event: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda event: canvas.itemconfigure(window_id, width=event.width))
        inner.columnconfigure(0, weight=1); inner.columnconfigure(1, weight=1)
        return inner

    @staticmethod
    def _profile_parent_for_path_v2121(message, path: tuple[str, ...]):
        parent = message
        for part in path[:-1]:
            parent = getattr(parent, part)
        return parent

    @staticmethod
    def _profile_security_locked_v2121(kind: str, name: str, path: str) -> bool:
        if kind != "config" or name != "security":
            return False
        lowered = path.lower()
        return any(token in lowered for token in ("private", "public", "admin", "key"))

    def _profile_apply_controls_v2121(self, profile: dict[str, object], kind: str, name: str, message, controls, parent) -> None:
        import base64
        try:
            from google.protobuf.descriptor import FieldDescriptor
            for path, field, variable, control_kind in controls:
                owner = self._profile_parent_for_path_v2121(message, path)
                raw = str(variable.get()).strip()
                full_path = ".".join(path)
                if self._profile_security_locked_v2121(kind, name, full_path):
                    continue
                if kind == "module" and name == "neighbor_info" and field.name in ("enabled", "transmit_over_lora"):
                    setattr(owner, field.name, True)
                    continue
                if field.type == FieldDescriptor.TYPE_BOOL:
                    value = raw in ("Ein", "True", "true", "1")
                elif field.type == FieldDescriptor.TYPE_ENUM:
                    enum_value = field.enum_type.values_by_name.get(raw)
                    if enum_value is None:
                        raise ValueError(f"{self._profile_field_label_v2121(full_path)}: ungültiger Wert {raw}")
                    value = enum_value.number
                elif field.type == FieldDescriptor.TYPE_BYTES:
                    value = base64.b64decode(raw.encode("ascii"), validate=True) if raw else b""
                elif field.type in (
                    FieldDescriptor.TYPE_INT32, FieldDescriptor.TYPE_INT64, FieldDescriptor.TYPE_UINT32,
                    FieldDescriptor.TYPE_UINT64, FieldDescriptor.TYPE_SINT32, FieldDescriptor.TYPE_SINT64,
                    FieldDescriptor.TYPE_FIXED32, FieldDescriptor.TYPE_FIXED64, FieldDescriptor.TYPE_SFIXED32,
                    FieldDescriptor.TYPE_SFIXED64,
                ):
                    value = int(raw or 0)
                elif field.type in (FieldDescriptor.TYPE_FLOAT, FieldDescriptor.TYPE_DOUBLE):
                    value = float(raw.replace(",", ".") or 0.0)
                else:
                    value = raw
                if kind == "config" and name == "lora" and field.name == "hop_limit":
                    max_hops = 20 if self._profile_rf_mode_active_v2121(profile) else 7
                    if not 0 <= int(value) <= max_hops:
                        raise ValueError(f"Hop-Limit muss in diesem Modus zwischen 0 und {max_hops} liegen.")
                if kind == "config" and name == "lora" and field.name == "override_duty_cycle" and bool(value) and not self._profile_rf_mode_active_v2121(profile):
                    raise ValueError("Sendelimit/Duty-Cycle Override ist nur mit hinterlegter Frequenzfreigabe A/B verfügbar.")
                if kind == "config" and name == "position" and field.name == "position_broadcast_secs" and int(value) <= 0:
                    raise ValueError("Position ins Mesh bleibt aktiv: Positionsintervall muss größer als 0 sein.")
                setattr(owner, field.name, value)
            if kind == "module" and name == "neighbor_info":
                if hasattr(message, "enabled"): message.enabled = True
                if hasattr(message, "transmit_over_lora"): message.transmit_over_lora = True
                if hasattr(message, "update_interval") and int(message.update_interval) < 14400: message.update_interval = 14400
            self._save_profile_message(profile, kind, name, message)
            tool_log("CONFIG_PROFILE_CARD_SAVE_V2121", kind=kind, name=name)
        except Exception as exc:
            messagebox.showerror("Grundprofil bearbeiten", str(exc), parent=parent)

    def _profile_render_card_v2121(self, parent, profile: dict[str, object], kind: str, name: str, index: int) -> None:
        import base64
        from google.protobuf.descriptor import FieldDescriptor
        try:
            message = self._profile_message(profile, kind, name)
        except Exception as exc:
            card = ttk.LabelFrame(parent, text=self._profile_section_title(kind, name), padding=10)
            card.grid(row=index // 2, column=index % 2, sticky="new", padx=5, pady=5)
            ttk.Label(card, text=f"Nicht lesbar: {exc}", wraplength=480).pack(anchor="w")
            return
        badge = self._profile_badge_v2121(kind, name)
        card = ttk.LabelFrame(parent, text=f"[{badge}] {self._profile_section_title(kind, name)}", padding=10)
        card.grid(row=index // 2, column=index % 2, sticky="new", padx=5, pady=5)
        card.columnconfigure(1, weight=1)
        controls = []
        advanced = [False]
        row = [0]

        if kind == "config" and name == "position":
            ttk.Label(card, text="Position ins Mesh: EIN · firmwareseitig geschützt", style="Subtitle.TLabel", wraplength=470).grid(row=row[0], column=0, columnspan=2, sticky="w", pady=(0, 6)); row[0] += 1
        if kind == "module" and name == "neighbor_info":
            ttk.Label(card, text="Neighbor Info + LoRa: EIN · im Tool gesperrt; Abschalten nur direkt im Node-Service-Menü", style="Subtitle.TLabel", wraplength=470).grid(row=row[0], column=0, columnspan=2, sticky="w", pady=(0, 6)); row[0] += 1
        if kind == "config" and name == "security":
            ttk.Label(card, text="Geräteidentität sowie private/public/admin Schlüssel bleiben node-spezifisch.", style="Subtitle.TLabel", wraplength=470).grid(row=row[0], column=0, columnspan=2, sticky="w", pady=(0, 6)); row[0] += 1

        def add_fields(container, prefix: tuple[str, ...] = (), depth: int = 0) -> None:
            for field in container.DESCRIPTOR.fields:
                path = prefix + (field.name,)
                full_path = ".".join(path)
                if field.label == FieldDescriptor.LABEL_REPEATED:
                    advanced[0] = True
                    continue
                if field.type == FieldDescriptor.TYPE_MESSAGE:
                    if depth < 1:
                        add_fields(getattr(container, field.name), path, depth + 1)
                    else:
                        advanced[0] = True
                    continue
                locked = self._profile_security_locked_v2121(kind, name, full_path)
                if kind == "module" and name == "neighbor_info" and field.name in ("enabled", "transmit_over_lora"):
                    locked = True
                label = self._profile_field_label_v2121(full_path)
                ttk.Label(card, text=label).grid(row=row[0], column=0, sticky="w", padx=(0, 8), pady=2)
                value = getattr(container, field.name)
                if locked:
                    shown = "Ein 🔒" if kind == "module" and name == "neighbor_info" else "node-spezifisch 🔒"
                    ttk.Label(card, text=shown).grid(row=row[0], column=1, sticky="w", pady=2)
                    row[0] += 1
                    continue
                variable = tk.StringVar()
                widget = None
                control_kind = "entry"
                if field.type == FieldDescriptor.TYPE_BOOL:
                    variable.set("Ein" if bool(value) else "Aus")
                    widget = ttk.Combobox(card, textvariable=variable, state="readonly", values=("Aus", "Ein"))
                    control_kind = "bool"
                elif field.type == FieldDescriptor.TYPE_ENUM:
                    enum_value = field.enum_type.values_by_number.get(int(value))
                    variable.set(enum_value.name if enum_value else str(int(value)))
                    widget = ttk.Combobox(card, textvariable=variable, state="readonly", values=tuple(item.name for item in field.enum_type.values))
                    control_kind = "enum"
                elif field.type == FieldDescriptor.TYPE_BYTES:
                    variable.set(base64.b64encode(bytes(value)).decode("ascii") if value else "")
                    widget = ttk.Entry(card, textvariable=variable)
                    control_kind = "bytes"
                elif kind == "config" and name == "lora" and field.name == "hop_limit":
                    max_hops = 20 if self._profile_rf_mode_active_v2121(profile) else 7
                    variable.set(str(int(value)))
                    widget = ttk.Combobox(card, textvariable=variable, state="readonly", values=tuple(str(i) for i in range(0, max_hops + 1)))
                    control_kind = "int"
                else:
                    variable.set(str(value))
                    widget = ttk.Entry(card, textvariable=variable)
                widget.grid(row=row[0], column=1, sticky="ew", pady=2)
                controls.append((path, field, variable, control_kind))
                row[0] += 1

        add_fields(message)
        footer = ttk.Frame(card); footer.grid(row=row[0], column=0, columnspan=2, sticky="ew", pady=(8, 0)); footer.columnconfigure(0, weight=1)
        ttk.Button(footer, text="Alle Werte / JSON", command=lambda: self._edit_profile_json_section(profile, kind, name, card)).grid(row=0, column=0, sticky="w")
        ttk.Button(footer, text="Bereich speichern", command=lambda: self._profile_apply_controls_v2121(profile, kind, name, message, controls, card)).grid(row=0, column=1, sticky="e", padx=(8, 0))
        if advanced[0]:
            ttk.Label(card, text="Verschachtelte/mehrfache Felder zusätzlich unter „Alle Werte / JSON“.", style="Subtitle.TLabel", wraplength=470).grid(row=row[0] + 1, column=0, columnspan=2, sticky="w", pady=(5, 0))

    def _profile_render_rf_authorization_v2121(self, parent, profile: dict[str, object]) -> None:
        ready = self._profile_rf_authorization_ready_v2121()
        card = ttk.LabelFrame(parent, text="[FREIGABE] Erweiterte Frequenzprofile A / B", padding=12)
        card.grid(row=0, column=0, columnspan=2, sticky="ew", padx=5, pady=5)
        card.columnconfigure(1, weight=1)
        a_text = f"{float(JARNSEN_AUTHORIZED_FREQUENCY_A_MHZ):.6f} MHz" if ready else "noch nicht hinterlegt"
        b_text = f"{float(JARNSEN_AUTHORIZED_FREQUENCY_B_MHZ):.6f} MHz" if ready else "noch nicht hinterlegt"
        warning = (
            "Freigabe aktiv: Sonderparameter gelten ausschließlich für die hinterlegten Frequenzen A/B und passende Jarnsen-Firmware."
            if ready else
            "Noch gesperrt: Exakte Frequenzen A/B und die dazu passende Firmwarefreigabe fehlen. Bis dahin gelten ausschließlich die normalen Meshtastic-/Regionsbegrenzungen."
        )
        ttk.Label(card, text=warning, style="Subtitle.TLabel", justify="left", wraplength=1000).grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 8))
        ttk.Label(card, text="Frequenz A").grid(row=1, column=0, sticky="w"); ttk.Label(card, text=a_text).grid(row=1, column=1, sticky="w")
        ttk.Label(card, text="Frequenz B").grid(row=2, column=0, sticky="w"); ttk.Label(card, text=b_text).grid(row=2, column=1, sticky="w")
        mode_values = ("Standard", "Freigabe Frequenz A", "Freigabe Frequenz B") if ready else ("Standard",)
        mode_value = str(profile.get("jarnsen_rf_mode") or "Standard")
        if mode_value not in mode_values: mode_value = "Standard"
        mode_var = tk.StringVar(value=mode_value)
        hop_value = int(profile.get("jarnsen_rf_hop_limit") or 7)
        hop_var = tk.StringVar(value=str(max(0, min(20, hop_value))))
        no_limit_var = tk.StringVar(value="Ein" if bool(profile.get("jarnsen_rf_no_send_limit")) else "Aus")
        ttk.Label(card, text="Frequenzmodus").grid(row=3, column=0, sticky="w", pady=(8, 2))
        ttk.Combobox(card, textvariable=mode_var, state="readonly", values=mode_values).grid(row=3, column=1, sticky="ew", pady=(8, 2))
        ttk.Label(card, text="Hop-Limit Freigabe (0–20)").grid(row=4, column=0, sticky="w", pady=2)
        hop_box = ttk.Combobox(card, textvariable=hop_var, state="readonly" if ready else "disabled", values=tuple(str(i) for i in range(0, 21)))
        hop_box.grid(row=4, column=1, sticky="ew", pady=2)
        ttk.Label(card, text="Sendelimit/Duty-Cycle Override").grid(row=5, column=0, sticky="w", pady=2)
        limit_box = ttk.Combobox(card, textvariable=no_limit_var, state="readonly" if ready else "disabled", values=("Aus", "Ein"))
        limit_box.grid(row=5, column=1, sticky="ew", pady=2)
        ttk.Label(card, text="Bandbreite, SF, CR, TX-Leistung, Frequenz-Offset und weitere vorhandene LoRa-Felder stehen vollständig in der LoRa-Kachel zur Verfügung.", style="Subtitle.TLabel", wraplength=980).grid(row=6, column=0, columnspan=2, sticky="w", pady=(6, 4))

        def save_rf() -> None:
            try:
                mode = mode_var.get()
                if mode != "Standard" and not ready:
                    raise ValueError("Frequenzfreigabe A/B ist noch nicht hinterlegt.")
                lora = self._profile_message(profile, "config", "lora")
                if mode == "Standard":
                    if hasattr(lora, "hop_limit") and int(lora.hop_limit) > 7: lora.hop_limit = 7
                    if hasattr(lora, "override_duty_cycle"): lora.override_duty_cycle = False
                    profile["jarnsen_rf_mode"] = "Standard"
                    profile["jarnsen_rf_hop_limit"] = min(7, int(getattr(lora, "hop_limit", 7) or 7))
                    profile["jarnsen_rf_no_send_limit"] = False
                else:
                    hop = int(hop_var.get())
                    if not 0 <= hop <= 20: raise ValueError("Hop-Limit muss zwischen 0 und 20 liegen.")
                    frequency = float(JARNSEN_AUTHORIZED_FREQUENCY_A_MHZ if mode.endswith(" A") else JARNSEN_AUTHORIZED_FREQUENCY_B_MHZ)
                    if hasattr(lora, "override_frequency"): lora.override_frequency = frequency
                    if hasattr(lora, "hop_limit"): lora.hop_limit = hop
                    if hasattr(lora, "override_duty_cycle"): lora.override_duty_cycle = no_limit_var.get() == "Ein"
                    profile["jarnsen_rf_mode"] = mode
                    profile["jarnsen_rf_hop_limit"] = hop
                    profile["jarnsen_rf_no_send_limit"] = no_limit_var.get() == "Ein"
                self._save_profile_message(profile, "config", "lora", lora)
                tool_log("CONFIG_PROFILE_RF_MODE_V2121", mode=profile.get("jarnsen_rf_mode"), ready=ready)
            except Exception as exc:
                messagebox.showerror("Frequenzfreigabe", str(exc), parent=card)

        ttk.Button(card, text="Frequenzmodus speichern", command=save_rf).grid(row=7, column=1, sticky="e", pady=(8, 0))
'''
    source = insert_before_method(source, "_rename_config_profile", helpers)

    editor = r'''    def _edit_config_profile(self, slot: int) -> None:
        profiles = self.config_profile_store.get("profiles", [])
        profile = profiles[slot] if isinstance(profiles, list) and slot < len(profiles) else None
        if not isinstance(profile, dict):
            messagebox.showinfo("Grundprofil", "Dieser Profilplatz ist leer.")
            return
        win = tk.Toplevel(self)
        win.title(f"Grundprofil {slot + 1} · Grundeinstellungen")
        win.transient(self)
        win.grab_set()
        win.geometry("1180x780")
        win.minsize(980, 680)

        header = ttk.Frame(win, padding=(12, 12, 12, 6)); header.pack(fill="x")
        name_var = tk.StringVar(value=str(profile.get("name") or f"Profil {slot + 1}"))
        ttk.Label(header, text="Profilname", style="Section.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Entry(header, textvariable=name_var).grid(row=1, column=0, sticky="ew", pady=(2, 4))
        header.columnconfigure(0, weight=1)
        ttk.Label(
            header,
            text=("STANDARD = normale Meshtastic-Einstellung · JARNSEN = firmwareseitige feste Regel · FREIGABE = erst nach hinterlegter A/B-Frequenzfreigabe.  "
                  "Long/Short Name leer beim Übertragen = vorhandenen Zielnamen behalten."),
            style="Subtitle.TLabel", justify="left", wraplength=1120,
        ).grid(row=2, column=0, sticky="ew", pady=(2, 2))

        notebook = ttk.Notebook(win)
        notebook.pack(fill="both", expand=True, padx=12, pady=(4, 6))
        tabs = (
            "Allgemein", "Funk & Kanal", "Mesh / Routing", "Position / GPS", "Bluetooth",
            "Display & Energie", "Module", "Sicherheit", "Erweitert / Freigabe",
        )
        for tab_name in tabs:
            inner = self._profile_scroll_tab_v2121(notebook, tab_name)
            row_offset = 0
            if tab_name == "Erweitert / Freigabe":
                self._profile_render_rf_authorization_v2121(inner, profile)
                row_offset = 1
            items = self._profile_tab_items_v2121(profile, tab_name)
            if not items:
                ttk.Label(inner, text="Für dieses Profil wurden in diesem Bereich keine Werte eingelesen.", style="Subtitle.TLabel").grid(row=row_offset, column=0, columnspan=2, sticky="w", padx=5, pady=10)
            for item_index, (kind, name) in enumerate(items):
                self._profile_render_card_v2121(inner, profile, kind, name, item_index + row_offset * 2)

        footer = ttk.Frame(win, padding=(12, 6, 12, 12)); footer.pack(fill="x")
        ttk.Label(footer, text="Änderungen werden je Kachel gespeichert. „Alle Werte / JSON“ bleibt für seltene und neue Protobuf-Felder verfügbar.", style="Subtitle.TLabel").pack(side="left")
        def close_editor() -> None:
            profile["name"] = name_var.get().strip() or f"Profil {slot + 1}"
            profile["saved_at"] = now_local().isoformat(timespec="seconds")
            self._save_config_profile_store(); self._refresh_config_profile_ui(); win.destroy()
        ttk.Button(footer, text="Von Node neu einlesen", command=lambda: (win.destroy(), self.start_config_profile_capture(slot))).pack(side="right", padx=(6, 0))
        ttk.Button(footer, text="Schließen", command=close_editor).pack(side="right")
        tool_log("CONFIG_PROFILE_TABBED_EDITOR_V2121", slot=slot + 1)
'''
    source = replace_method(source, "_edit_config_profile", editor)

    required = (
        'APP_VERSION = "2.1.21"',
        "CONFIG_PROFILE_TABBED_EDITOR_V2121",
        "Erweitert / Freigabe",
        "Funk & Kanal",
        "Mesh / Routing",
        "JARNSEN_AUTHORIZED_RF_ENABLED = False",
        "Hop-Limit Freigabe (0–20)",
        "Sendelimit/Duty-Cycle Override",
        "Alle Werte / JSON",
        "Position ins Mesh: EIN",
        "Neighbor Info + LoRa: EIN",
        "node-spezifisch 🔒",
    )
    missing = [marker for marker in required if marker not in source]
    if missing:
        raise SystemExit("v2.1.21 validation failed: " + ", ".join(missing))
    return source


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: patch_jarnsen_service_tool_v2121.py <source.py>")
    path = Path(sys.argv[1])
    path.write_text(patch(path.read_text(encoding="utf-8")), encoding="utf-8")
    print(f"Patched {path} to v{APP_VERSION}: tabbed profile editor + gated A/B RF controls")


if __name__ == "__main__":
    main()
