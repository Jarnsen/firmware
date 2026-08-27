"""v2.1.16: make base-profile writes persistent, prefer USB, and read BT PIN."""
from __future__ import annotations

import re
import sys
from pathlib import Path

APP_VERSION = "2.1.16"


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


def insert_before_method(text: str, name: str, code: str) -> str:
    start, _ = method_span(text, name)
    return text[:start] + code.rstrip() + "\n\n" + text[start:]


def patch(source: str) -> str:
    source = re.sub(r'APP_VERSION = "[^"]+"', f'APP_VERSION = "{APP_VERSION}"', source, count=1)
    source = source.replace('APP_VERSION != "2.1.15"', 'APP_VERSION != "2.1.16"')
    source = source.replace("App-Version ist nicht v2.1.15", "App-Version ist nicht v2.1.16")

    # In automatic mode an explicitly selected COM port must win over a BLE
    # advertisement. This is especially important while provisioning a node over USB.
    connection = r'''    def _config_profile_connection(self) -> tuple[str, str, str]:
        if not MESHTASTIC_CONFIG_AVAILABLE:
            raise RuntimeError("Meshtastic-Python-Schnittstelle ist in dieser Tool-Version nicht verfügbar.")
        requested = self.config_profile_transport_var.get()

        if requested in ("Automatisch", "USB"):
            selected_port = self.port.get().strip() if hasattr(self, "port") else ""
            port = str(self.port_map.get(selected_port, selected_port) or "").strip()
            if port:
                tool_log("CONFIG_PROFILE_TRANSPORT_V2116", requested=requested, selected="USB", target=port)
                return "USB", port, port
            if requested == "USB":
                raise RuntimeError("Bitte zuerst einen COM-Port auswählen.")

        if requested in ("Automatisch", "Bluetooth"):
            selected = self.selected_ble_devices()
            if len(selected) == 1:
                label, device = selected[0]
                address = str(getattr(device, "address", "") or "").strip()
                if not address:
                    raise RuntimeError("Der markierte Bluetooth-Eintrag hat keine verwendbare Adresse.")
                tool_log("CONFIG_PROFILE_TRANSPORT_V2116", requested=requested, selected="Bluetooth", target=address)
                return "Bluetooth", address, label
            if requested == "Bluetooth":
                raise RuntimeError("Für die Konfiguration bitte genau eine Bluetooth-Node markieren.")
            if len(self.ble_map) == 1:
                label, device = next(iter(self.ble_map.items()))
                address = str(getattr(device, "address", "") or "").strip()
                if address:
                    tool_log("CONFIG_PROFILE_TRANSPORT_V2116", requested=requested, selected="Bluetooth", target=address)
                    return "Bluetooth", address, label

        raise RuntimeError("Keine eindeutige USB-/Bluetooth-Verbindung ausgewählt.")
'''
    source = replace_method(source, "_config_profile_connection", connection)

    # Add an explicit PIN reader next to the target-node controls. Reading the
    # config over USB also works before Windows has paired the BLE device.
    pin_anchor = '''        ttk.Checkbutton(
            target,
            text="PSK beim Übertragen anwenden",
            variable=self.config_apply_psk_var,
        ).grid(row=1, column=4, sticky="w")
        target.columnconfigure(1, weight=1)
'''
    pin_replacement = '''        ttk.Checkbutton(
            target,
            text="PSK beim Übertragen anwenden",
            variable=self.config_apply_psk_var,
        ).grid(row=1, column=4, sticky="w", padx=(0, 8))
        self.config_bt_pin_var = tk.StringVar(value="BT-PIN --")
        ttk.Label(target, textvariable=self.config_bt_pin_var, style="Subtitle.TLabel").grid(
            row=0, column=5, sticky="w"
        )
        ttk.Button(target, text="BT-PIN abrufen", command=self.start_config_bt_pin_read).grid(
            row=1, column=5, sticky="ew"
        )
        target.columnconfigure(1, weight=1)
'''
    if source.count(pin_anchor) != 1:
        raise SystemExit("v2.1.16 BT-PIN UI anchor missing or ambiguous")
    source = source.replace(pin_anchor, pin_replacement, 1)

    pin_methods = r'''    def start_config_bt_pin_read(self) -> None:
        if self.worker and self.worker.is_alive():
            messagebox.showinfo("BT-PIN", "Bitte den laufenden Vorgang zuerst beenden.")
            return
        try:
            connection = self._config_profile_connection()
        except Exception as exc:
            messagebox.showerror("BT-PIN abrufen", str(exc))
            return
        self._set_config_profile_buttons_state("disabled")
        self.status_level = "normal"
        self.status.configure(text=f"Lese Bluetooth-PIN von {connection[2]} …")
        self._update_status_badge()
        self.worker = threading.Thread(
            target=self._config_bt_pin_read_worker,
            args=(connection,),
            daemon=True,
        )
        self.worker.start()

    def _config_bt_pin_read_worker(self, connection: tuple[str, str, str]) -> None:
        interface = None
        try:
            interface, node = self._open_config_profile_interface(connection)
            bluetooth = getattr(node.localConfig, "bluetooth", None)
            if bluetooth is None:
                raise RuntimeError("Die Ziel-Firmware stellt keine Bluetooth-Konfiguration bereit.")
            mode_field = bluetooth.DESCRIPTOR.fields_by_name.get("mode")
            mode_value = int(getattr(bluetooth, "mode", 0) or 0)
            mode_enum = mode_field.enum_type.values_by_number.get(mode_value) if mode_field and mode_field.enum_type else None
            mode_name = mode_enum.name if mode_enum else str(mode_value)
            enabled = bool(getattr(bluetooth, "enabled", False))
            fixed_pin = int(getattr(bluetooth, "fixed_pin", 0) or 0)
            if not enabled:
                text = "Bluetooth ist auf der Node deaktiviert"
            elif mode_name == "FIXED_PIN" and fixed_pin:
                text = f"{fixed_pin:06d}"
            elif mode_name == "FIXED_PIN":
                text = "FIXED_PIN aktiv, aber kein gültiger PIN gespeichert"
            else:
                text = f"Kein fester PIN · Modus {mode_name}"
            tool_log(
                "CONFIG_BT_PIN_READ_V2116",
                transport=connection[0],
                mode=mode_name,
                enabled=enabled,
                fixed_pin=f"{fixed_pin:06d}" if fixed_pin else "--",
            )
            self.events.put(("config_bt_pin_result", (text, mode_name, connection[0])))
        except Exception as exc:
            tool_log(
                "CONFIG_BT_PIN_ERROR_V2116",
                transport=connection[0],
                error_type=type(exc).__name__,
                error=exc,
            )
            hint = ""
            if connection[0] == "Bluetooth":
                hint = "\n\nWenn die Node noch nicht mit Windows gekoppelt ist, den PIN bitte per USB/COM auslesen."
            self.events.put(("config_profile_error", f"BT-PIN konnte nicht gelesen werden: {exc}{hint}"))
        finally:
            if interface is not None:
                with contextlib.suppress(Exception):
                    interface.close()
            self.events.put(("config_profile_idle", None))
'''
    source = insert_before_method(source, "_normalize_authorized_frequency", pin_methods)

    # Follow the same timing/order as Meshtastic's official --configure path:
    # transaction, owner, 0.5s-spaced config writes, commit. Critically, do NOT
    # schedule a reboot 250ms later: that could discard every queued admin write.
    apply_worker = r'''    def _config_profile_apply_worker(
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
        expected_config: dict[str, bytes] = {}
        expected_modules: dict[str, bytes] = {}
        expected_channels: dict[int, bytes] = {}
        skipped: list[str] = []
        try:
            interface, node = self._open_config_profile_interface(connection)
            target_hw, _target_firmware = self._config_profile_metadata(interface)
            source_hw = str(profile.get("source_hw") or "")
            hardware_mismatch = bool(source_hw and target_hw and source_hw != target_hw)
            skip_on_mismatch = {"display", "position", "power"}
            if hardware_mismatch:
                skipped.append(
                    f"Hardware abweichend ({source_hw} → {target_hw}); Display/Position/Power nicht übertragen"
                )

            def stage(label: str) -> None:
                self.events.put(("status", f"Grundprofil {slot + 1}: {label}"))
                tool_log(
                    "CONFIG_PROFILE_WRITE_STAGE_V2116",
                    slot=slot + 1,
                    transport=connection[0],
                    stage=label,
                )

            stage("Schreibtransaktion starten")
            node.beginSettingsTransaction()
            time.sleep(0.65)

            # Target names are deliberately NOT part of the reusable profile.
            # The two target fields in the UI are authoritative for every apply.
            stage("Long/Short Name schreiben")
            node.setOwner(long_name=long_name, short_name=short_name[:4])
            time.sleep(0.75)

            config_sections = profile.get("config", {})
            deferred_bluetooth: str | None = None
            if isinstance(config_sections, dict):
                for raw_name, encoded in config_sections.items():
                    name = str(raw_name)
                    if hardware_mismatch and name in skip_on_mismatch:
                        continue
                    if connection[0] == "Bluetooth" and name == "bluetooth":
                        # Changing pairing policy can disconnect this very link.
                        # Commit all other settings first and send Bluetooth last.
                        deferred_bluetooth = str(encoded)
                        continue
                    section = getattr(node.localConfig, name, None)
                    if section is None:
                        skipped.append(f"Config {name}: von Ziel-Firmware nicht unterstützt")
                        continue
                    desired = type(section)()
                    desired.ParseFromString(self._decode_protobuf_payload(str(encoded)))

                    if name == "security":
                        known = section.DESCRIPTOR.fields_by_name
                        for identity_field in ("private_key", "public_key", "admin_key"):
                            if identity_field not in known:
                                continue
                            if identity_field == "admin_key":
                                target_values = [bytes(item) for item in getattr(section, identity_field)]
                                target_field = getattr(desired, identity_field)
                                del target_field[:]
                                target_field.extend(target_values)
                            else:
                                setattr(desired, identity_field, bytes(getattr(section, identity_field)))
                    if name == "position" and hasattr(section, "fixed_position"):
                        desired.fixed_position = bool(section.fixed_position)
                    if name == "lora" and frequency_override is not None:
                        if not hasattr(desired, "override_frequency"):
                            raise RuntimeError("Die Ziel-Firmware unterstützt override_frequency nicht.")
                        desired.override_frequency = float(frequency_override)

                    section.CopyFrom(desired)
                    stage(f"Config {name} schreiben")
                    node.writeConfig(name)
                    expected_config[name] = section.SerializeToString()
                    time.sleep(0.65)

            module_sections = profile.get("module_config", {})
            if isinstance(module_sections, dict):
                for raw_name, encoded in module_sections.items():
                    name = str(raw_name)
                    section = getattr(node.moduleConfig, name, None)
                    if section is None:
                        skipped.append(f"Modul {name}: von Ziel-Firmware nicht unterstützt")
                        continue
                    desired = type(section)()
                    desired.ParseFromString(self._decode_protobuf_payload(str(encoded)))
                    section.CopyFrom(desired)
                    stage(f"Modul {name} schreiben")
                    node.writeConfig(name)
                    expected_modules[name] = section.SerializeToString()
                    time.sleep(0.65)

            stage("Konfiguration committen")
            node.commitSettingsTransaction()
            time.sleep(1.50)

            channels = profile.get("channels", [])
            if isinstance(channels, list):
                for entry in channels:
                    if not isinstance(entry, dict):
                        continue
                    index = int(entry.get("index", -1))
                    if index < 0 or not node.channels or index >= len(node.channels):
                        skipped.append(f"Kanal {index}: auf Ziel-Node nicht vorhanden")
                        continue
                    target_channel = node.channels[index]
                    existing_psk = bytes(target_channel.settings.psk)
                    desired_channel = type(target_channel)()
                    desired_channel.ParseFromString(
                        self._decode_protobuf_payload(str(entry.get("payload") or ""))
                    )
                    if not apply_psk:
                        desired_channel.settings.psk = existing_psk
                    target_channel.CopyFrom(desired_channel)
                    stage(f"Kanal {index} schreiben")
                    node.writeChannel(index)
                    expected_channels[index] = target_channel.SerializeToString()
                    time.sleep(0.75)

            if deferred_bluetooth is not None:
                section = getattr(node.localConfig, "bluetooth", None)
                if section is not None:
                    desired = type(section)()
                    desired.ParseFromString(self._decode_protobuf_payload(deferred_bluetooth))
                    section.CopyFrom(desired)
                    stage("Bluetooth zuletzt schreiben")
                    try:
                        node.writeConfig("bluetooth")
                        expected_config["bluetooth"] = section.SerializeToString()
                        time.sleep(1.25)
                    except Exception as exc:
                        # A changed PIN/pairing mode may intentionally tear down
                        # the BLE link immediately after the write was accepted.
                        skipped.append(f"Bluetooth-Rückmeldung nach Write: {exc}")

            # Give the local admin/serial queue enough time to drain. No explicit
            # reboot here; Meshtastic handles config persistence/required restarts.
            stage("Schreibpuffer abschließen")
            time.sleep(2.50)
            interface.close()
            interface = None

            verification = "Rückprüfung nicht möglich"
            verify_error = ""
            final_mismatches: list[str] = []
            for attempt in range(4):
                time.sleep(3.0 if attempt == 0 else 2.5)
                verify_interface = None
                attempt_mismatches: list[str] = []
                try:
                    stage(f"Rückprüfung {attempt + 1}/4")
                    verify_interface, verify_node = self._open_config_profile_interface(connection)
                    if str(verify_interface.getLongName() or "").strip() != long_name:
                        attempt_mismatches.append("Long Name")
                    if str(verify_interface.getShortName() or "").strip() != short_name[:4]:
                        attempt_mismatches.append("Short Name")
                    for name, expected in expected_config.items():
                        section = getattr(verify_node.localConfig, name, None)
                        if section is None or section.SerializeToString() != expected:
                            attempt_mismatches.append(f"Config {name}")
                    for name, expected in expected_modules.items():
                        section = getattr(verify_node.moduleConfig, name, None)
                        if section is None or section.SerializeToString() != expected:
                            attempt_mismatches.append(f"Modul {name}")
                    for index, expected in expected_channels.items():
                        if not verify_node.channels or index >= len(verify_node.channels):
                            attempt_mismatches.append(f"Kanal {index}")
                        elif verify_node.channels[index].SerializeToString() != expected:
                            attempt_mismatches.append(f"Kanal {index}")

                    final_mismatches = sorted(set(attempt_mismatches))
                    if not final_mismatches:
                        verification = "Rückprüfung OK"
                        verify_error = ""
                        break
                    verification = "Noch abweichend: " + ", ".join(final_mismatches)
                except Exception as exc:
                    verify_error = str(exc)
                finally:
                    if verify_interface is not None:
                        with contextlib.suppress(Exception):
                            verify_interface.close()

            if verify_error and verification == "Rückprüfung nicht möglich":
                verification += f": {verify_error}"

            success = verification == "Rückprüfung OK"
            summary = (
                f"Profil {slot + 1} geschrieben · Ziel {long_name} / {short_name[:4]}\n"
                f"PSK: {'übernommen' if apply_psk else 'Ziel-PSK beibehalten'}\n"
                f"{verification}"
            )
            if frequency_override is not None:
                summary += f"\nAuthorized 915: {frequency_override:g} MHz"
            if skipped:
                summary += "\n\nHinweise:\n- " + "\n- ".join(skipped)
            tool_log(
                "CONFIG_PROFILE_APPLY_V2116",
                slot=slot + 1,
                transport=connection[0],
                target_hw=target_hw or "--",
                long_name=long_name,
                short_name=short_name[:4],
                psk=apply_psk,
                verification=verification,
                success=success,
                mismatches=";".join(final_mismatches) if final_mismatches else "--",
            )
            self.events.put(("config_profile_apply_result", (summary, success)))
        except Exception as exc:
            tool_log(
                "CONFIG_PROFILE_ERROR_V2116",
                action="apply",
                slot=slot + 1,
                transport=connection[0],
                error_type=type(exc).__name__,
                error=exc,
            )
            self.events.put(("config_profile_error", f"Profil konnte nicht geschrieben werden: {exc}"))
        finally:
            if interface is not None:
                with contextlib.suppress(Exception):
                    interface.close()
            self.events.put(("config_profile_idle", None))
'''
    source = replace_method(source, "_config_profile_apply_worker", apply_worker)

    # Add the PIN result to the existing UI event pump.
    event_anchor = '''                elif kind == "config_profile_idle":
                    self._set_config_profile_buttons_state("normal")
'''
    event_replacement = '''                elif kind == "config_bt_pin_result":
                    pin_text, mode_name, transport = value
                    if hasattr(self, "config_bt_pin_var"):
                        self.config_bt_pin_var.set(f"BT-PIN {pin_text}" if str(pin_text).isdigit() else str(pin_text))
                    self.status_level = "success"
                    self.status.configure(text=f"Bluetooth-Konfiguration gelesen · {transport}")
                    self._update_status_badge()
                    messagebox.showinfo("BT-PIN", f"Modus: {mode_name}\n{pin_text}")
                elif kind == "config_profile_idle":
                    self._set_config_profile_buttons_state("normal")
'''
    if source.count(event_anchor) != 1:
        raise SystemExit("v2.1.16 event anchor missing or ambiguous")
    source = source.replace(event_anchor, event_replacement, 1)

    required = (
        'APP_VERSION = "2.1.16"',
        "CONFIG_PROFILE_TRANSPORT_V2116",
        'text="BT-PIN abrufen"',
        "CONFIG_BT_PIN_READ_V2116",
        "CONFIG_PROFILE_WRITE_STAGE_V2116",
        "CONFIG_PROFILE_APPLY_V2116",
        "node.beginSettingsTransaction()",
        "node.commitSettingsTransaction()",
        "time.sleep(0.65)",
        "time.sleep(0.75)",
        'node.setOwner(long_name=long_name, short_name=short_name[:4])',
        "Rückprüfung OK",
    )
    missing = [marker for marker in required if marker not in source]
    if missing:
        raise SystemExit("v2.1.16 validation failed: " + ", ".join(missing))

    apply_start, apply_end = method_span(source, "_config_profile_apply_worker")
    apply_text = source[apply_start:apply_end]
    if "node.reboot(" in apply_text:
        raise SystemExit("v2.1.16 apply worker must not force an immediate reboot")
    return source


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: patch_jarnsen_service_tool_v2116.py <source.py>")
    path = Path(sys.argv[1])
    path.write_text(patch(path.read_text(encoding="utf-8")), encoding="utf-8")
    print(f"Patched {path} to v{APP_VERSION}: persistent profile writes + BT PIN read")


if __name__ == "__main__":
    main()
