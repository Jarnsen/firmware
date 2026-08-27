"""v2.1.18: configurable fixed Bluetooth PIN in the target-node row."""
from __future__ import annotations

import re
import sys
from pathlib import Path

APP_VERSION = "2.1.18"


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
    source = source.replace('APP_VERSION != "2.1.17"', 'APP_VERSION != "2.1.18"')
    source = source.replace("App-Version ist nicht v2.1.17", "App-Version ist nicht v2.1.18")

    pin_ui_old = '''        self.config_bt_pin_var = tk.StringVar(value="BT-PIN --")
        ttk.Label(target, textvariable=self.config_bt_pin_var, style="Subtitle.TLabel").grid(
            row=0, column=5, sticky="w"
        )
        ttk.Button(target, text="BT-PIN abrufen", command=self.start_config_bt_pin_read).grid(
            row=1, column=5, sticky="ew"
        )
        target.columnconfigure(1, weight=1)
'''
    pin_ui_new = '''        self.config_bt_pin_var = tk.StringVar(value="240180")
        self.config_apply_bt_pin_var = tk.BooleanVar(value=True)
        ttk.Label(target, text="Fester BT-PIN").grid(row=0, column=5, sticky="w")
        pin_controls = ttk.Frame(target)
        pin_controls.grid(row=1, column=5, sticky="ew", padx=(0, 8))
        ttk.Entry(pin_controls, textvariable=self.config_bt_pin_var, width=9).pack(
            side="left", fill="x", expand=True
        )
        ttk.Button(pin_controls, text="Auslesen", command=self.start_config_bt_pin_read).pack(
            side="left", padx=(5, 0)
        )
        ttk.Checkbutton(
            target,
            text="BT-PIN beim Übertragen setzen",
            variable=self.config_apply_bt_pin_var,
        ).grid(row=1, column=6, sticky="w")
        target.columnconfigure(1, weight=1)
'''
    if source.count(pin_ui_old) != 1:
        raise SystemExit("v2.1.18 BT-PIN UI anchor missing or ambiguous")
    source = source.replace(pin_ui_old, pin_ui_new, 1)

    # The reader now fills the numeric target field instead of replacing it with
    # a descriptive status sentence. v2.1.17 may include the saved PIN inside a
    # longer text when Bluetooth itself is disabled, therefore extract six digits.
    event_old = '''                    if hasattr(self, "config_bt_pin_var"):
                        self.config_bt_pin_var.set(f"BT-PIN {pin_text}" if str(pin_text).isdigit() else str(pin_text))
'''
    event_new = '''                    if hasattr(self, "config_bt_pin_var"):
                        pin_match = re.search(r"(?<!\\d)(\\d{6})(?!\\d)", str(pin_text))
                        if pin_match:
                            self.config_bt_pin_var.set(pin_match.group(1))
'''
    if source.count(event_old) != 1:
        raise SystemExit("v2.1.18 BT-PIN result anchor missing or ambiguous")
    source = source.replace(event_old, event_new, 1)

    # Validate the desired target PIN before starting the worker and pass it as a
    # numeric value. The default is 240180 but the user may enter any six digits.
    start_begin, start_end = method_span(source, "start_config_profile_apply")
    start_method = source[start_begin:start_end]
    apply_anchor = '''        apply_psk = bool(self.config_apply_psk_var.get()) and bool(profile.get("psk_included"))
        self._set_config_profile_buttons_state("disabled")
'''
    apply_replacement = '''        apply_psk = bool(self.config_apply_psk_var.get()) and bool(profile.get("psk_included"))
        fixed_bt_pin: int | None = None
        if bool(getattr(self, "config_apply_bt_pin_var", tk.BooleanVar(value=True)).get()):
            pin_text = str(getattr(self, "config_bt_pin_var", tk.StringVar(value="240180")).get()).strip()
            if not re.fullmatch(r"\\d{6}", pin_text):
                messagebox.showerror(
                    "Grundprofil übertragen",
                    "Der feste Bluetooth-PIN muss genau aus 6 Ziffern bestehen.",
                )
                return
            fixed_bt_pin = int(pin_text)
        self._set_config_profile_buttons_state("disabled")
'''
    if start_method.count(apply_anchor) != 1:
        raise SystemExit("v2.1.18 apply PIN validation anchor missing or ambiguous")
    start_method = start_method.replace(apply_anchor, apply_replacement, 1)
    args_old = '''            args=(slot, profile, long_name, short_name, apply_psk, frequency_override, connection),
'''
    args_new = '''            args=(slot, profile, long_name, short_name, apply_psk, frequency_override, fixed_bt_pin, connection),
'''
    if start_method.count(args_old) != 1:
        raise SystemExit("v2.1.18 worker args anchor missing or ambiguous")
    start_method = start_method.replace(args_old, args_new, 1)
    source = source[:start_begin] + start_method + source[start_end:]

    worker_begin, worker_end = method_span(source, "_config_profile_apply_worker")
    worker = source[worker_begin:worker_end]
    signature_old = '''        frequency_override: float | None,
        connection: tuple[str, str, str],
'''
    signature_new = '''        frequency_override: float | None,
        fixed_bt_pin: int | None,
        connection: tuple[str, str, str],
'''
    if worker.count(signature_old) != 1:
        raise SystemExit("v2.1.18 worker signature anchor missing or ambiguous")
    worker = worker.replace(signature_old, signature_new, 1)

    stage_anchor = '''            stage("Schreibtransaktion starten")
'''
    pin_helper = '''            def configure_fixed_bt_pin(bluetooth_config) -> None:
                if fixed_bt_pin is None:
                    return
                if not hasattr(bluetooth_config, "fixed_pin") or not hasattr(bluetooth_config, "mode"):
                    raise RuntimeError("Die Ziel-Firmware unterstützt keinen festen Bluetooth-PIN.")
                mode_field = bluetooth_config.DESCRIPTOR.fields_by_name.get("mode")
                fixed_enum = (
                    mode_field.enum_type.values_by_name.get("FIXED_PIN")
                    if mode_field is not None and mode_field.enum_type is not None
                    else None
                )
                if fixed_enum is None:
                    raise RuntimeError("Die Ziel-Firmware bietet den Bluetooth-Modus FIXED_PIN nicht an.")
                if hasattr(bluetooth_config, "enabled"):
                    bluetooth_config.enabled = True
                bluetooth_config.mode = fixed_enum.number
                bluetooth_config.fixed_pin = int(fixed_bt_pin)

            stage("Schreibtransaktion starten")
'''
    if worker.count(stage_anchor) != 1:
        raise SystemExit("v2.1.18 fixed PIN helper anchor missing or ambiguous")
    worker = worker.replace(stage_anchor, pin_helper, 1)

    desired_anchor = '''                    desired = type(section)()
                    desired.ParseFromString(self._decode_protobuf_payload(str(encoded)))

                    if name == "security":
'''
    desired_replacement = '''                    desired = type(section)()
                    desired.ParseFromString(self._decode_protobuf_payload(str(encoded)))
                    if name == "bluetooth":
                        configure_fixed_bt_pin(desired)

                    if name == "security":
'''
    if worker.count(desired_anchor) != 1:
        raise SystemExit("v2.1.18 Bluetooth desired-config anchor missing or ambiguous")
    worker = worker.replace(desired_anchor, desired_replacement, 1)

    module_anchor = '''            module_sections = profile.get("module_config", {})
'''
    missing_bluetooth = '''            if fixed_bt_pin is not None and not (
                isinstance(config_sections, dict) and "bluetooth" in config_sections
            ):
                section = getattr(node.localConfig, "bluetooth", None)
                if section is None:
                    raise RuntimeError("Die Ziel-Firmware stellt keine Bluetooth-Konfiguration bereit.")
                desired = type(section)()
                desired.CopyFrom(section)
                configure_fixed_bt_pin(desired)
                if connection[0] == "Bluetooth":
                    deferred_bluetooth = self._protobuf_payload(desired)
                else:
                    section.CopyFrom(desired)
                    stage("Festen Bluetooth-PIN schreiben")
                    if write_config_safe("bluetooth", "Config"):
                        expected_config["bluetooth"] = section.SerializeToString()
                    time.sleep(0.65)

            module_sections = profile.get("module_config", {})
'''
    if worker.count(module_anchor) != 1:
        raise SystemExit("v2.1.18 missing-Bluetooth anchor missing or ambiguous")
    worker = worker.replace(module_anchor, missing_bluetooth, 1)

    deferred_old = '''                    desired = type(section)()
                    desired.ParseFromString(self._decode_protobuf_payload(deferred_bluetooth))
                    section.CopyFrom(desired)
                    stage("Bluetooth zuletzt schreiben")
'''
    deferred_new = '''                    desired = type(section)()
                    desired.ParseFromString(self._decode_protobuf_payload(deferred_bluetooth))
                    configure_fixed_bt_pin(desired)
                    section.CopyFrom(desired)
                    stage("Bluetooth zuletzt schreiben")
'''
    if worker.count(deferred_old) != 1:
        raise SystemExit("v2.1.18 deferred Bluetooth anchor missing or ambiguous")
    worker = worker.replace(deferred_old, deferred_new, 1)

    source = source[:worker_begin] + worker + source[worker_end:]

    required = (
        'APP_VERSION = "2.1.18"',
        'tk.StringVar(value="240180")',
        'text="Fester BT-PIN"',
        'text="Auslesen"',
        'text="BT-PIN beim Übertragen setzen"',
        'fixed_bt_pin: int | None',
        'configure_fixed_bt_pin(desired)',
        'fixed_pin = int(fixed_bt_pin)',
        'CONFIG_PROFILE_UNSUPPORTED_WRITE_V2117',
        'PYINSTALLER_RESET_ENVIRONMENT',
    )
    missing = [marker for marker in required if marker not in source]
    if missing:
        raise SystemExit("v2.1.18 validation failed: " + ", ".join(missing))
    return source


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: patch_jarnsen_service_tool_v2118.py <source.py>")
    path = Path(sys.argv[1])
    path.write_text(patch(path.read_text(encoding="utf-8")), encoding="utf-8")
    print(f"Patched {path} to v{APP_VERSION}: configurable fixed Bluetooth PIN")


if __name__ == "__main__":
    main()
