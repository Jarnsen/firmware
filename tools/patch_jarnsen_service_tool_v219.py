"""v2.1.9: four persistent Meshtastic base profiles with optional PSK and Authorized-915 slots."""
from __future__ import annotations

import re
import sys
from pathlib import Path

APP_VERSION = "2.1.9"


def method_span(text: str, name: str) -> tuple[int, int]:
    start = text.find(f"    def {name}(")
    if start < 0:
        raise SystemExit(f"method {name} not found")
    next_method = text.find("\n    def ", start + 1)
    next_decorator = text.find("\n    @", start + 1)
    candidates = [value for value in (next_method, next_decorator) if value >= 0]
    return start, min(candidates) if candidates else len(text)


def replace_method(text: str, name: str, updater) -> str:
    start, end = method_span(text, name)
    return text[:start] + updater(text[start:end]) + text[end:]


def insert_before_method(text: str, name: str, code: str) -> str:
    start, _ = method_span(text, name)
    return text[:start] + code.rstrip() + "\n\n" + text[start:]


def patch(source: str) -> str:
    source = re.sub(r'APP_VERSION = "[^"]+"', f'APP_VERSION = "{APP_VERSION}"', source, count=1)
    source = source.replace('APP_VERSION != "2.1.8"', 'APP_VERSION != "2.1.9"')
    source = source.replace("App-Version ist nicht v2.1.8", "App-Version ist nicht v2.1.9")

    if "import base64\n" not in source:
        anchor = "import asyncio\n"
        if anchor not in source:
            raise SystemExit("v2.1.9 import anchor missing")
        source = source.replace(anchor, anchor + "import base64\n", 1)

    if "MESHTASTIC_CONFIG_AVAILABLE" not in source:
        anchor = "from serial.tools import list_ports\n"
        if anchor not in source:
            raise SystemExit("v2.1.9 serial import anchor missing")
        imports = r'''

try:
    from meshtastic.ble_interface import BLEInterface as MeshtasticBLEInterface
    from meshtastic.serial_interface import SerialInterface as MeshtasticSerialInterface

    MESHTASTIC_CONFIG_AVAILABLE = True
except ImportError:
    MeshtasticBLEInterface = None
    MeshtasticSerialInterface = None
    MESHTASTIC_CONFIG_AVAILABLE = False
'''
        source = source.replace(anchor, anchor + imports, 1)

    def patch_workflow_ui(method: str) -> str:
        if "self._build_config_profiles_ui()" in method:
            return method
        anchor = "        self.refresh_node_selector()\n"
        if anchor not in method:
            raise SystemExit("v2.1.9 workflow UI anchor missing")
        return method.replace(anchor, "        self._build_config_profiles_ui()\n" + anchor, 1)

    source = replace_method(source, "_install_workflow_ui", patch_workflow_ui)

    methods = r'''    def _config_profile_store_path(self) -> pathlib.Path:
        local_app_data = os.environ.get("LOCALAPPDATA", "").strip()
        if local_app_data:
            directory = pathlib.Path(local_app_data) / "Jarnsen Node Service Tool"
        else:
            directory = output_directory() / "Tool-Config"
        directory.mkdir(parents=True, exist_ok=True)
        return directory / "grundkonfigurationen.json"

    def _default_config_profile_store(self) -> dict[str, object]:
        return {
            "schema": 1,
            "authorized_915": {"a_mhz": "", "b_mhz": ""},
            "profiles": [None, None, None, None],
        }

    def _load_config_profile_store(self) -> dict[str, object]:
        store = self._default_config_profile_store()
        path = self._config_profile_store_path()
        try:
            loaded = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        except (OSError, ValueError, TypeError) as exc:
            tool_log("CONFIG_PROFILE_LOAD_V219", result="fallback", error=exc)
            loaded = {}
        if isinstance(loaded, dict):
            authorized = loaded.get("authorized_915")
            if isinstance(authorized, dict):
                store["authorized_915"] = {
                    "a_mhz": str(authorized.get("a_mhz") or ""),
                    "b_mhz": str(authorized.get("b_mhz") or ""),
                }
            profiles = loaded.get("profiles")
            if isinstance(profiles, list):
                normalized = list(profiles[:4])
                while len(normalized) < 4:
                    normalized.append(None)
                store["profiles"] = normalized
        return store

    def _save_config_profile_store(self) -> None:
        path = self._config_profile_store_path()
        temporary = path.with_suffix(".tmp")
        payload = json.dumps(
            self.config_profile_store,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        temporary.write_text(payload, encoding="utf-8")
        temporary.replace(path)
        tool_log("CONFIG_PROFILE_STORE_V219", path=path)

    def _build_config_profiles_ui(self) -> None:
        if hasattr(self, "config_profiles_tab"):
            return
        self.config_profile_store = self._load_config_profile_store()
        self.config_profiles_tab = ttk.Frame(self.notebook, padding=10)
        self.notebook.add(self.config_profiles_tab, text="Grundprofile")
        try:
            self.notebook.insert(self.notebook.index(self.firmware_tab), self.config_profiles_tab)
        except tk.TclError:
            pass

        title = ttk.Frame(self.config_profiles_tab)
        title.pack(fill="x", pady=(0, 6))
        ttk.Label(title, text="Meshtastic-Grundkonfigurationen", style="Section.TLabel").pack(side="left")
        ttk.Label(
            title,
            text="4 lokale Profile · Geräte-ID/Keys/feste Position werden nicht kopiert",
            style="Subtitle.TLabel",
        ).pack(side="right")

        target = ttk.LabelFrame(self.config_profiles_tab, text="Ziel-Node", padding=7)
        target.pack(fill="x", pady=(0, 6))
        self.config_profile_transport_var = tk.StringVar(value="Automatisch")
        ttk.Label(target, text="Verbindung").grid(row=0, column=0, sticky="w")
        self.config_profile_transport = ttk.Combobox(
            target,
            state="readonly",
            width=14,
            values=("Automatisch", "USB", "Bluetooth"),
            textvariable=self.config_profile_transport_var,
        )
        self.config_profile_transport.grid(row=1, column=0, sticky="ew", padx=(0, 8))
        self.config_target_long_var = tk.StringVar()
        self.config_target_short_var = tk.StringVar()
        ttk.Label(target, text="Long Name").grid(row=0, column=1, sticky="w")
        ttk.Entry(target, textvariable=self.config_target_long_var, width=30).grid(
            row=1, column=1, sticky="ew", padx=(0, 8)
        )
        ttk.Label(target, text="Short Name (max. 4)").grid(row=0, column=2, sticky="w")
        ttk.Entry(target, textvariable=self.config_target_short_var, width=10).grid(
            row=1, column=2, sticky="ew", padx=(0, 8)
        )
        self.config_store_psk_var = tk.BooleanVar(value=True)
        self.config_apply_psk_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            target,
            text="PSK beim Einlesen speichern",
            variable=self.config_store_psk_var,
        ).grid(row=1, column=3, sticky="w", padx=(0, 8))
        ttk.Checkbutton(
            target,
            text="PSK beim Übertragen anwenden",
            variable=self.config_apply_psk_var,
        ).grid(row=1, column=4, sticky="w")
        target.columnconfigure(1, weight=1)

        authorized = ttk.LabelFrame(
            self.config_profiles_tab,
            text="Authorized 915 · nur die zwei ausdrücklich freigegebenen Frequenzen",
            padding=7,
        )
        authorized.pack(fill="x", pady=(0, 6))
        saved_authorized = self.config_profile_store.get("authorized_915", {})
        if not isinstance(saved_authorized, dict):
            saved_authorized = {}
        self.authorized_freq_a_var = tk.StringVar(value=str(saved_authorized.get("a_mhz") or ""))
        self.authorized_freq_b_var = tk.StringVar(value=str(saved_authorized.get("b_mhz") or ""))
        ttk.Label(authorized, text="Frequenz A (MHz)").grid(row=0, column=0, sticky="w")
        ttk.Entry(authorized, textvariable=self.authorized_freq_a_var, width=15).grid(
            row=1, column=0, sticky="w", padx=(0, 8)
        )
        ttk.Label(authorized, text="Frequenz B (MHz)").grid(row=0, column=1, sticky="w")
        ttk.Entry(authorized, textvariable=self.authorized_freq_b_var, width=15).grid(
            row=1, column=1, sticky="w", padx=(0, 8)
        )
        ttk.Button(
            authorized,
            text="Frequenzen speichern",
            command=self._save_authorized_frequencies,
        ).grid(row=1, column=2, sticky="w", padx=(0, 14))
        ttk.Label(authorized, text="Beim Übertragen").grid(row=0, column=3, sticky="w")
        self.config_frequency_mode_var = tk.StringVar(value="Profilwert")
        self.config_frequency_mode = ttk.Combobox(
            authorized,
            state="readonly",
            width=38,
            textvariable=self.config_frequency_mode_var,
        )
        self.config_frequency_mode.grid(row=1, column=3, sticky="ew")
        authorized.columnconfigure(3, weight=1)

        self.config_profile_name_vars: list[tk.StringVar] = []
        self.config_profile_status_labels: list[ttk.Label] = []
        self.config_profile_action_buttons: list[ttk.Button] = []
        grid = ttk.Frame(self.config_profiles_tab)
        grid.pack(fill="both", expand=True)
        for slot in range(4):
            row, column = divmod(slot, 2)
            card = ttk.LabelFrame(grid, text=f"Profil {slot + 1}", padding=8)
            card.grid(
                row=row,
                column=column,
                sticky="nsew",
                padx=(0 if column == 0 else 5, 5 if column == 0 else 0),
                pady=(0 if row == 0 else 5, 5 if row == 0 else 0),
            )
            name_var = tk.StringVar(value=f"Profil {slot + 1}")
            self.config_profile_name_vars.append(name_var)
            ttk.Entry(card, textvariable=name_var).pack(fill="x")
            status = ttk.Label(
                card,
                text="Leer",
                style="Subtitle.TLabel",
                justify="left",
                wraplength=420,
            )
            status.pack(fill="x", pady=(5, 6))
            self.config_profile_status_labels.append(status)
            buttons = ttk.Frame(card)
            buttons.pack(fill="x")
            for label, command in (
                ("Von Node einlesen", lambda selected=slot: self.start_config_profile_capture(selected)),
                ("Auf Node übertragen", lambda selected=slot: self.start_config_profile_apply(selected)),
                ("Umbenennen", lambda selected=slot: self._rename_config_profile(selected)),
                ("Löschen", lambda selected=slot: self._delete_config_profile(selected)),
            ):
                button = ttk.Button(buttons, text=label, command=command)
                button.pack(side="left", fill="x", expand=True, padx=2)
                self.config_profile_action_buttons.append(button)
        for index in range(2):
            grid.columnconfigure(index, weight=1)
            grid.rowconfigure(index, weight=1)

        ttk.Label(
            self.config_profiles_tab,
            text=(
                "PSK = Kanalschlüssel. Wenn er nicht gespeichert/angewendet wird, bleibt der vorhandene PSK der Ziel-Node erhalten. "
                "Gespeicherte PSKs liegen lokal in der Profil-Datei; private/public/admin Device-Keys werden niemals übernommen."
            ),
            style="Subtitle.TLabel",
            justify="left",
            wraplength=1100,
        ).pack(fill="x", pady=(6, 0))
        self._refresh_authorized_frequency_choices()
        self._refresh_config_profile_ui()

    def _normalize_authorized_frequency(self, raw: str) -> str:
        value_text = str(raw or "").strip().replace(",", ".")
        if not value_text:
            return ""
        value = float(value_text)
        if not 900.0 <= value <= 930.0:
            raise ValueError("Authorized-915-Frequenzen müssen zwischen 900 und 930 MHz liegen.")
        return f"{value:.6f}".rstrip("0").rstrip(".")

    def _save_authorized_frequencies(self) -> None:
        try:
            a_mhz = self._normalize_authorized_frequency(self.authorized_freq_a_var.get())
            b_mhz = self._normalize_authorized_frequency(self.authorized_freq_b_var.get())
        except (TypeError, ValueError) as exc:
            messagebox.showerror("Authorized 915", str(exc))
            return
        if a_mhz and b_mhz and a_mhz == b_mhz:
            messagebox.showerror("Authorized 915", "Frequenz A und B müssen unterschiedlich sein.")
            return
        self.authorized_freq_a_var.set(a_mhz)
        self.authorized_freq_b_var.set(b_mhz)
        self.config_profile_store["authorized_915"] = {"a_mhz": a_mhz, "b_mhz": b_mhz}
        self._save_config_profile_store()
        self._refresh_authorized_frequency_choices()
        self.status_level = "success"
        self.status.configure(text="Authorized-915-Frequenzen lokal gespeichert")
        self._update_status_badge()

    def _refresh_authorized_frequency_choices(self) -> None:
        if not hasattr(self, "config_frequency_mode"):
            return
        choices = ["Profilwert"]
        authorized = self.config_profile_store.get("authorized_915", {})
        if isinstance(authorized, dict):
            a_mhz = str(authorized.get("a_mhz") or "")
            b_mhz = str(authorized.get("b_mhz") or "")
            if a_mhz:
                choices.append(f"Authorized 915 A · {a_mhz} MHz")
            if b_mhz:
                choices.append(f"Authorized 915 B · {b_mhz} MHz")
        self.config_frequency_mode.configure(values=tuple(choices))
        if self.config_frequency_mode_var.get() not in choices:
            self.config_frequency_mode_var.set("Profilwert")

    def _selected_authorized_frequency(self) -> float | None:
        selected = self.config_frequency_mode_var.get()
        if selected == "Profilwert":
            return None
        authorized = self.config_profile_store.get("authorized_915", {})
        if not isinstance(authorized, dict):
            return None
        key = "a_mhz" if selected.startswith("Authorized 915 A") else "b_mhz"
        value = str(authorized.get(key) or "").strip()
        return float(value) if value else None

    def _profile_summary_text(self, profile: dict[str, object] | None) -> str:
        if not isinstance(profile, dict):
            return "Leer"
        source_hw = str(profile.get("source_hw") or "Hardware unbekannt")
        firmware = str(profile.get("source_firmware") or "Firmware --")
        saved_at = str(profile.get("saved_at") or "--")
        psk = "enthalten" if profile.get("psk_included") else "nicht gespeichert"
        channels = profile.get("channels")
        channel_count = len(channels) if isinstance(channels, list) else 0
        lora = profile.get("lora_summary")
        lora_text = ""
        if isinstance(lora, dict):
            frequency = lora.get("override_frequency")
            hop = lora.get("hop_limit")
            tx = lora.get("tx_power")
            extras = []
            if frequency not in (None, 0, 0.0, ""):
                extras.append(f"Freq {frequency} MHz")
            if hop not in (None, ""):
                extras.append(f"Hop {hop}")
            if tx not in (None, ""):
                extras.append(f"TX {tx}")
            if extras:
                lora_text = " · " + " · ".join(extras)
        return f"{source_hw} · {firmware}\n{saved_at} · {channel_count} Kanäle · PSK {psk}{lora_text}"

    def _refresh_config_profile_ui(self) -> None:
        if not hasattr(self, "config_profile_status_labels"):
            return
        profiles = self.config_profile_store.get("profiles", [])
        if not isinstance(profiles, list):
            profiles = []
        for slot in range(4):
            profile = profiles[slot] if slot < len(profiles) else None
            if isinstance(profile, dict):
                self.config_profile_name_vars[slot].set(str(profile.get("name") or f"Profil {slot + 1}"))
            elif not self.config_profile_name_vars[slot].get().strip():
                self.config_profile_name_vars[slot].set(f"Profil {slot + 1}")
            self.config_profile_status_labels[slot].configure(
                text=self._profile_summary_text(profile if isinstance(profile, dict) else None)
            )

    def _rename_config_profile(self, slot: int) -> None:
        profiles = self.config_profile_store.get("profiles", [])
        if not isinstance(profiles, list) or slot >= len(profiles) or not isinstance(profiles[slot], dict):
            messagebox.showinfo("Grundprofil", "Dieser Profil-Slot ist noch leer.")
            return
        name = self.config_profile_name_vars[slot].get().strip()
        if not name:
            messagebox.showerror("Grundprofil", "Bitte einen Profilnamen eingeben.")
            return
        profiles[slot]["name"] = name
        self._save_config_profile_store()
        self._refresh_config_profile_ui()

    def _delete_config_profile(self, slot: int) -> None:
        profiles = self.config_profile_store.get("profiles", [])
        if not isinstance(profiles, list) or slot >= len(profiles) or not isinstance(profiles[slot], dict):
            return
        if not messagebox.askyesno("Grundprofil löschen", f"Profil {slot + 1} wirklich löschen?"):
            return
        profiles[slot] = None
        self._save_config_profile_store()
        self._refresh_config_profile_ui()

    def _set_config_profile_buttons_state(self, state: str) -> None:
        for button in getattr(self, "config_profile_action_buttons", []):
            with contextlib.suppress(tk.TclError):
                button.configure(state=state)

    def _config_profile_connection(self) -> tuple[str, str, str]:
        if not MESHTASTIC_CONFIG_AVAILABLE:
            raise RuntimeError("Meshtastic-Python-Schnittstelle ist in dieser Tool-Version nicht verfügbar.")
        requested = self.config_profile_transport_var.get()
        if requested in ("Automatisch", "Bluetooth"):
            selected = self.selected_ble_devices()
            if len(selected) == 1:
                label, device = selected[0]
                address = str(getattr(device, "address", "") or "").strip()
                if not address:
                    raise RuntimeError("Der markierte Bluetooth-Eintrag hat keine verwendbare Adresse.")
                return "Bluetooth", address, label
            if requested == "Bluetooth":
                raise RuntimeError("Für die Konfiguration bitte genau eine Bluetooth-Node markieren.")
            if len(self.ble_map) == 1:
                label, device = next(iter(self.ble_map.items()))
                address = str(getattr(device, "address", "") or "").strip()
                if address:
                    return "Bluetooth", address, label
        if requested in ("Automatisch", "USB"):
            selected_port = self.port.get().strip() if hasattr(self, "port") else ""
            port = str(self.port_map.get(selected_port, selected_port) or "").strip()
            if port:
                return "USB", port, port
            if requested == "USB":
                raise RuntimeError("Bitte zuerst einen COM-Port auswählen.")
        raise RuntimeError("Keine eindeutige USB-/Bluetooth-Verbindung ausgewählt.")

    def _open_config_profile_interface(self, connection: tuple[str, str, str]):
        transport, target, _label = connection
        if transport == "Bluetooth":
            if MeshtasticBLEInterface is None:
                raise RuntimeError("Meshtastic-BLE-Unterstützung fehlt.")
            interface = MeshtasticBLEInterface(target, noNodes=True, timeout=90)
        else:
            if MeshtasticSerialInterface is None:
                raise RuntimeError("Meshtastic-USB-Unterstützung fehlt.")
            interface = MeshtasticSerialInterface(devPath=target, noNodes=True, timeout=90)
        node = interface.localNode
        if node is None or not node.waitForConfig("channels"):
            interface.close()
            raise RuntimeError("Meshtastic-Konfiguration wurde nicht vollständig von der Node empfangen.")
        return interface, node

    def _config_profile_metadata(self, interface) -> tuple[str, str]:
        source_hw = ""
        source_firmware = ""
        with contextlib.suppress(Exception):
            info = interface.getMyNodeInfo() or {}
            user = info.get("user") if isinstance(info, dict) else None
            if isinstance(user, dict):
                source_hw = str(user.get("hwModel") or user.get("hw_model") or "")
        metadata = getattr(interface, "metadata", None)
        if metadata is not None:
            source_firmware = str(
                getattr(metadata, "firmware_version", "")
                or getattr(metadata, "firmwareVersion", "")
                or ""
            )
        return source_hw, source_firmware

    def _protobuf_payload(self, message) -> str:
        return base64.b64encode(message.SerializeToString()).decode("ascii")

    def _decode_protobuf_payload(self, encoded: str) -> bytes:
        return base64.b64decode(str(encoded).encode("ascii"), validate=True)

    def start_config_profile_capture(self, slot: int) -> None:
        if self.worker and self.worker.is_alive():
            messagebox.showinfo("Grundprofil", "Bitte den laufenden Vorgang zuerst beenden.")
            return
        try:
            connection = self._config_profile_connection()
        except Exception as exc:
            messagebox.showerror("Grundprofil einlesen", str(exc))
            return
        name = self.config_profile_name_vars[slot].get().strip() or f"Profil {slot + 1}"
        include_psk = bool(self.config_store_psk_var.get())
        self._set_config_profile_buttons_state("disabled")
        self.status_level = "normal"
        self.status.configure(text=f"Lese Grundprofil {slot + 1} von {connection[2]} …")
        self._update_status_badge()
        self.worker = threading.Thread(
            target=self._config_profile_capture_worker,
            args=(slot, name, include_psk, connection),
            daemon=True,
        )
        self.worker.start()

    def _config_profile_capture_worker(
        self,
        slot: int,
        name: str,
        include_psk: bool,
        connection: tuple[str, str, str],
    ) -> None:
        interface = None
        try:
            interface, node = self._open_config_profile_interface(connection)
            source_hw, source_firmware = self._config_profile_metadata(interface)
            config_sections: dict[str, str] = {}
            for field in node.localConfig.DESCRIPTOR.fields:
                section = getattr(node.localConfig, field.name)
                clone = type(section)()
                clone.CopyFrom(section)
                if field.name == "security":
                    known = clone.DESCRIPTOR.fields_by_name
                    for identity_field in ("private_key", "public_key", "admin_key"):
                        if identity_field in known:
                            clone.ClearField(identity_field)
                config_sections[field.name] = self._protobuf_payload(clone)

            module_sections: dict[str, str] = {}
            for field in node.moduleConfig.DESCRIPTOR.fields:
                section = getattr(node.moduleConfig, field.name)
                clone = type(section)()
                clone.CopyFrom(section)
                module_sections[field.name] = self._protobuf_payload(clone)

            channels: list[dict[str, object]] = []
            for index, channel in enumerate(node.channels or []):
                clone = type(channel)()
                clone.CopyFrom(channel)
                if not include_psk and hasattr(clone, "settings"):
                    clone.settings.psk = b""
                channels.append({"index": index, "payload": self._protobuf_payload(clone)})

            lora = getattr(node.localConfig, "lora", None)
            lora_summary: dict[str, object] = {}
            if lora is not None:
                for key in ("region", "override_frequency", "hop_limit", "tx_power"):
                    if hasattr(lora, key):
                        value = getattr(lora, key)
                        if isinstance(value, (int, float, str, bool)):
                            lora_summary[key] = value

            profile = {
                "schema": 1,
                "name": name,
                "saved_at": now_local().isoformat(timespec="seconds"),
                "source_hw": source_hw,
                "source_firmware": source_firmware,
                "psk_included": include_psk,
                "config": config_sections,
                "module_config": module_sections,
                "channels": channels,
                "lora_summary": lora_summary,
                "exclusions": [
                    "node_id",
                    "owner_long_name",
                    "owner_short_name",
                    "security.private_key",
                    "security.public_key",
                    "security.admin_key",
                    "fixed_position_coordinates",
                ],
            }
            tool_log(
                "CONFIG_PROFILE_CAPTURE_V219",
                slot=slot + 1,
                transport=connection[0],
                source_hw=source_hw or "--",
                psk=include_psk,
                channels=len(channels),
            )
            self.events.put(("config_profile_saved", (slot, profile)))
        except Exception as exc:
            tool_log(
                "CONFIG_PROFILE_ERROR_V219",
                action="capture",
                slot=slot + 1,
                error_type=type(exc).__name__,
                error=exc,
            )
            self.events.put(("config_profile_error", f"Profil konnte nicht eingelesen werden: {exc}"))
        finally:
            if interface is not None:
                with contextlib.suppress(Exception):
                    interface.close()
            self.events.put(("config_profile_idle", None))

    def start_config_profile_apply(self, slot: int) -> None:
        if self.worker and self.worker.is_alive():
            messagebox.showinfo("Grundprofil", "Bitte den laufenden Vorgang zuerst beenden.")
            return
        profiles = self.config_profile_store.get("profiles", [])
        profile = profiles[slot] if isinstance(profiles, list) and slot < len(profiles) else None
        if not isinstance(profile, dict):
            messagebox.showinfo("Grundprofil", "Dieser Profil-Slot ist noch leer.")
            return
        long_name = self.config_target_long_var.get().strip()
        short_name = self.config_target_short_var.get().strip()
        if not long_name:
            messagebox.showerror("Grundprofil übertragen", "Bitte den Long Name der Ziel-Node eingeben.")
            return
        if not short_name or len(short_name) > 4:
            messagebox.showerror("Grundprofil übertragen", "Der Short Name muss 1 bis 4 Zeichen lang sein.")
            return
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
            args=(slot, profile, long_name, short_name, apply_psk, frequency_override, connection),
            daemon=True,
        )
        self.worker.start()

    def _config_profile_apply_worker(
        self,
        slot: int,
        profile: dict[str, object],
        long_name: str,
        short_name: str,
        apply_psk: bool,
        frequency_override: float | None,
        connection: tuple[str, str, str],
    ) -> None:
        interface = None
        warnings: list[str] = []
        expected_config: dict[str, bytes] = {}
        expected_modules: dict[str, bytes] = {}
        expected_channels: dict[int, bytes] = {}
        try:
            interface, node = self._open_config_profile_interface(connection)
            target_hw, _target_firmware = self._config_profile_metadata(interface)
            source_hw = str(profile.get("source_hw") or "")
            hardware_mismatch = bool(source_hw and target_hw and source_hw != target_hw)
            skip_on_mismatch = {"display", "position", "power", "bluetooth"}
            if hardware_mismatch:
                warnings.append(
                    f"Hardware abweichend ({source_hw} → {target_hw}); Display/Position/Power/Bluetooth wurden übersprungen."
                )

            if hasattr(node, "beginSettingsTransaction"):
                with contextlib.suppress(Exception):
                    node.beginSettingsTransaction()
                    time.sleep(0.15)

            config_sections = profile.get("config", {})
            if isinstance(config_sections, dict):
                for name, encoded in config_sections.items():
                    name = str(name)
                    if hardware_mismatch and name in skip_on_mismatch:
                        continue
                    section = getattr(node.localConfig, name, None)
                    if section is None:
                        warnings.append(f"Config '{name}' wird von der Ziel-Firmware nicht unterstützt.")
                        continue
                    preserved_security: dict[str, object] = {}
                    preserved_fixed_position = None
                    if name == "security":
                        known = section.DESCRIPTOR.fields_by_name
                        for identity_field in ("private_key", "public_key", "admin_key"):
                            if identity_field not in known:
                                continue
                            value = getattr(section, identity_field)
                            if identity_field == "admin_key":
                                preserved_security[identity_field] = [bytes(item) for item in value]
                            else:
                                preserved_security[identity_field] = bytes(value)
                    if name == "position" and hasattr(section, "fixed_position"):
                        preserved_fixed_position = bool(section.fixed_position)
                    section.Clear()
                    section.ParseFromString(self._decode_protobuf_payload(str(encoded)))
                    if name == "security":
                        for identity_field, value in preserved_security.items():
                            if identity_field == "admin_key":
                                field = getattr(section, identity_field)
                                del field[:]
                                field.extend(value)
                            else:
                                setattr(section, identity_field, value)
                    if preserved_fixed_position is not None:
                        section.fixed_position = preserved_fixed_position
                    if name == "lora" and frequency_override is not None:
                        if not hasattr(section, "override_frequency"):
                            raise RuntimeError("Die Ziel-Firmware unterstützt override_frequency nicht.")
                        section.override_frequency = float(frequency_override)
                    try:
                        node.writeConfig(name)
                        expected_config[name] = section.SerializeToString()
                        time.sleep(0.10)
                    except Exception as exc:
                        warnings.append(f"Config '{name}' nicht geschrieben: {exc}")

            module_sections = profile.get("module_config", {})
            if isinstance(module_sections, dict):
                for name, encoded in module_sections.items():
                    name = str(name)
                    section = getattr(node.moduleConfig, name, None)
                    if section is None:
                        warnings.append(f"Modul '{name}' wird von der Ziel-Firmware nicht unterstützt.")
                        continue
                    section.Clear()
                    section.ParseFromString(self._decode_protobuf_payload(str(encoded)))
                    try:
                        node.writeConfig(name)
                        expected_modules[name] = section.SerializeToString()
                        time.sleep(0.10)
                    except Exception as exc:
                        warnings.append(f"Modul '{name}' nicht geschrieben: {exc}")

            node.setOwner(long_name=long_name, short_name=short_name)
            time.sleep(0.15)

            channels = profile.get("channels", [])
            if isinstance(channels, list):
                for entry in channels:
                    if not isinstance(entry, dict):
                        continue
                    index = int(entry.get("index", -1))
                    if index < 0 or not node.channels or index >= len(node.channels):
                        continue
                    target_channel = node.channels[index]
                    existing_psk = bytes(target_channel.settings.psk)
                    target_channel.Clear()
                    target_channel.ParseFromString(
                        self._decode_protobuf_payload(str(entry.get("payload") or ""))
                    )
                    if not apply_psk:
                        target_channel.settings.psk = existing_psk
                    try:
                        node.writeChannel(index)
                        expected_channels[index] = target_channel.SerializeToString()
                        time.sleep(0.10)
                    except Exception as exc:
                        warnings.append(f"Kanal {index} nicht geschrieben: {exc}")

            if hasattr(node, "commitSettingsTransaction"):
                with contextlib.suppress(Exception):
                    node.commitSettingsTransaction()
                    time.sleep(0.20)
            node.reboot(2)
            time.sleep(0.25)
            interface.close()
            interface = None

            verification = "Rückprüfung nach Neustart nicht möglich"
            mismatches: list[str] = []
            verify_error = ""
            for attempt in range(3):
                time.sleep(4.0 if attempt == 0 else 3.0)
                verify_interface = None
                try:
                    verify_interface, verify_node = self._open_config_profile_interface(connection)
                    if str(verify_interface.getLongName() or "") != long_name:
                        mismatches.append("Long Name")
                    if str(verify_interface.getShortName() or "") != short_name[:4]:
                        mismatches.append("Short Name")
                    for name, expected in expected_config.items():
                        section = getattr(verify_node.localConfig, name, None)
                        if section is not None and section.SerializeToString() != expected:
                            mismatches.append(f"Config {name}")
                    for name, expected in expected_modules.items():
                        section = getattr(verify_node.moduleConfig, name, None)
                        if section is not None and section.SerializeToString() != expected:
                            mismatches.append(f"Modul {name}")
                    for index, expected in expected_channels.items():
                        if verify_node.channels and index < len(verify_node.channels):
                            if verify_node.channels[index].SerializeToString() != expected:
                                mismatches.append(f"Kanal {index}")
                    verification = (
                        "Rückprüfung OK"
                        if not mismatches
                        else "Rückprüfung mit Abweichungen: " + ", ".join(sorted(set(mismatches)))
                    )
                    break
                except Exception as exc:
                    verify_error = str(exc)
                finally:
                    if verify_interface is not None:
                        with contextlib.suppress(Exception):
                            verify_interface.close()
            if verification == "Rückprüfung nach Neustart nicht möglich" and verify_error:
                warnings.append(f"Rückprüfung: {verify_error}")

            summary = (
                f"Profil {slot + 1} übertragen · {long_name} / {short_name[:4]}\n"
                f"PSK: {'übernommen' if apply_psk else 'Ziel-PSK beibehalten'}"
            )
            if frequency_override is not None:
                summary += f" · Authorized 915: {frequency_override:g} MHz"
            summary += f"\n{verification}"
            if warnings:
                summary += "\n\nHinweise:\n- " + "\n- ".join(warnings)
            tool_log(
                "CONFIG_PROFILE_APPLY_V219",
                slot=slot + 1,
                transport=connection[0],
                target_hw=target_hw or "--",
                psk=apply_psk,
                frequency=frequency_override if frequency_override is not None else "profile",
                verification=verification,
                warnings=len(warnings),
            )
            self.events.put(("config_profile_apply_result", (summary, not mismatches and not verify_error)))
        except Exception as exc:
            tool_log(
                "CONFIG_PROFILE_ERROR_V219",
                action="apply",
                slot=slot + 1,
                error_type=type(exc).__name__,
                error=exc,
            )
            self.events.put(("config_profile_error", f"Profil konnte nicht übertragen werden: {exc}"))
        finally:
            if interface is not None:
                with contextlib.suppress(Exception):
                    interface.close()
            self.events.put(("config_profile_idle", None))
'''
    if "    def _build_config_profiles_ui(self)" not in source:
        source = insert_before_method(source, "_resize_dashboard", methods)

    def patch_events(method: str) -> str:
        if 'elif kind == "config_profile_saved":' in method:
            return method
        anchor = '                elif kind == "done":\n'
        if anchor not in method:
            raise SystemExit("v2.1.9 event anchor missing")
        handlers = r'''                elif kind == "config_profile_saved":
                    slot, profile = value
                    profiles = self.config_profile_store.get("profiles", [])
                    if not isinstance(profiles, list):
                        profiles = [None, None, None, None]
                        self.config_profile_store["profiles"] = profiles
                    while len(profiles) < 4:
                        profiles.append(None)
                    profiles[int(slot)] = dict(profile)
                    self._save_config_profile_store()
                    self._refresh_config_profile_ui()
                    self.status_level = "success"
                    self.status.configure(text=f"Grundprofil {int(slot) + 1} gespeichert")
                    self._update_status_badge()
                    messagebox.showinfo(
                        "Grundprofil gespeichert",
                        f"Profil {int(slot) + 1} wurde von der Node eingelesen.\n\n"
                        f"PSK: {'enthalten' if profile.get('psk_included') else 'nicht gespeichert'}\n"
                        "Node-ID, Long/Short Name, Device-Keys und feste Position wurden nicht übernommen.",
                    )
                elif kind == "config_profile_apply_result":
                    summary, verified = value
                    self.set_result(str(summary))
                    self.status_level = "success" if verified else "warning"
                    self.status.configure(
                        text="Grundkonfiguration übertragen und geprüft"
                        if verified
                        else "Grundkonfiguration übertragen · Rückprüfung mit Hinweis"
                    )
                    self._update_status_badge()
                    if verified:
                        messagebox.showinfo("Grundprofil übertragen", str(summary))
                    else:
                        messagebox.showwarning("Grundprofil übertragen", str(summary))
                elif kind == "config_profile_error":
                    self.status_level = "error"
                    self.status.configure(text="Grundkonfiguration fehlgeschlagen")
                    self._update_status_badge()
                    self.set_result(str(value))
                    messagebox.showerror("Grundkonfiguration", str(value))
                elif kind == "config_profile_idle":
                    self._set_config_profile_buttons_state("normal")
'''
        return method.replace(anchor, handlers + anchor, 1)

    source = replace_method(source, "_pump_events", patch_events)

    if "Meshtastic-Profil-Schnittstelle fehlt" not in source:
        anchor = '        if not RECYCLE_AVAILABLE:\n            raise RuntimeError("send2trash ist nicht verfügbar")\n'
        if anchor not in source:
            raise SystemExit("v2.1.9 self-test dependency anchor missing")
        source = source.replace(
            anchor,
            anchor
            + '        if not MESHTASTIC_CONFIG_AVAILABLE:\n'
            + '            raise RuntimeError("Meshtastic-Profil-Schnittstelle fehlt")\n',
            1,
        )

    required = (
        'APP_VERSION = "2.1.9"',
        "MESHTASTIC_CONFIG_AVAILABLE",
        'text="Grundprofile"',
        "def start_config_profile_capture(self, slot: int)",
        "def start_config_profile_apply(self, slot: int)",
        "PSK beim Einlesen speichern",
        "PSK beim Übertragen anwenden",
        "Authorized 915 A",
        "Authorized 915 B",
        "CONFIG_PROFILE_CAPTURE_V219",
        "CONFIG_PROFILE_APPLY_V219",
        "private_key",
        "public_key",
        "admin_key",
        "fixed_position",
    )
    missing = [item for item in required if item not in source]
    if missing:
        raise SystemExit("v2.1.9 validation failed: " + ", ".join(missing))
    return source


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: patch_jarnsen_service_tool_v219.py <source.py>")
    path = Path(sys.argv[1])
    source = path.read_text(encoding="utf-8")
    patched = patch(source)
    path.write_text(patched, encoding="utf-8")
    print(f"Patched {path} to v{APP_VERSION}: four Meshtastic base profiles + Authorized-915 slots")


if __name__ == "__main__":
    main()
