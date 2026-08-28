"""v2.1.22: one Jarnsen PIN, full-lock policy, RF naming and policy-last handoff."""
from __future__ import annotations

import re
import sys
from pathlib import Path

APP_VERSION = "2.1.22"


def method_span(text: str, name: str) -> tuple[int, int]:
    normal = text.find(f"    def {name}(")
    asynchronous = text.find(f"    async def {name}(")
    starts = [value for value in (normal, asynchronous) if value >= 0]
    if not starts:
        raise SystemExit(f"method {name} not found")
    start = min(starts)
    candidates = [p for p in (
        text.find("\n    def ", start + 1),
        text.find("\n    async def ", start + 1),
        text.find("\n    @", start + 1),
    ) if p >= 0]
    return start, min(candidates) if candidates else len(text)


def insert_before_method(text: str, name: str, code: str) -> str:
    start, _ = method_span(text, name)
    return text[:start] + code.rstrip() + "\n\n" + text[start:]


def patch(source: str) -> str:
    source = re.sub(r'APP_VERSION = "[^"]+"', f'APP_VERSION = "{APP_VERSION}"', source, count=1)
    source = source.replace('APP_VERSION != "2.1.21"', 'APP_VERSION != "2.1.22"')
    source = source.replace("App-Version ist nicht v2.1.21", "App-Version ist nicht v2.1.22")

    # Same RF names in tool and later firmware service menu.
    source = source.replace("Freigabe Frequenz A", "Jarnsen A")
    source = source.replace("Freigabe Frequenz B", "Jarnsen B")

    constants_anchor = "JARNSEN_AUTHORIZED_FREQUENCY_B_MHZ = 0.0"
    if "JARNSEN_DEFAULT_PIN" not in source:
        if constants_anchor not in source:
            raise SystemExit("v2.1.22 RF constants anchor missing")
        source = source.replace(
            constants_anchor,
            constants_anchor
            + '\nJARNSEN_DEFAULT_PIN = "240180"\n'
            + 'JARNSEN_ADMIN_UNLOCK_MINUTES = 15\n'
            + 'JARNSEN_FULL_LOCK_ALERT_DEFAULT = True\n'
            + 'JARNSEN_POLICY_PROTOCOL_VERSION = 1',
            1,
        )

    helpers = r'''    @staticmethod
    def _ensure_jarnsen_policy_defaults_v2122(profile: dict[str, object]) -> None:
        mode = str(profile.get("jarnsen_rf_mode") or "Standard")
        if mode == "Freigabe Frequenz A": mode = "Jarnsen A"
        if mode == "Freigabe Frequenz B": mode = "Jarnsen B"
        if mode not in ("Standard", "Jarnsen A", "Jarnsen B"): mode = "Standard"
        profile["jarnsen_rf_mode"] = mode
        profile["jarnsen_pin"] = JARNSEN_DEFAULT_PIN
        profile["jarnsen_admin_unlock_minutes"] = JARNSEN_ADMIN_UNLOCK_MINUTES
        profile.setdefault("jarnsen_full_lock_alert_mesh", JARNSEN_FULL_LOCK_ALERT_DEFAULT)
        profile["jarnsen_full_lock_gesture"] = "DOUBLE_CLICK_THIRD_HOLD_3S"
        profile.setdefault("jarnsen_full_lock_alert_retries", 3)

    @staticmethod
    def _force_jarnsen_bluetooth_pin_v2122(message) -> None:
        if hasattr(message, "fixed_pin"):
            message.fixed_pin = int(JARNSEN_DEFAULT_PIN)
        field = message.DESCRIPTOR.fields_by_name.get("mode") if hasattr(message, "DESCRIPTOR") else None
        if field and field.enum_type and "FIXED_PIN" in field.enum_type.values_by_name:
            message.mode = field.enum_type.values_by_name["FIXED_PIN"].number

    def _profile_render_jarnsen_security_v2122(self, parent, profile: dict[str, object]) -> None:
        self._ensure_jarnsen_policy_defaults_v2122(profile)
        card = ttk.LabelFrame(parent, text="[JARNSEN] PIN & Vollsperre", padding=12)
        card.grid(row=0, column=0, columnspan=2, sticky="ew", padx=5, pady=5)
        card.columnconfigure(1, weight=1)
        ttk.Label(card, text="Ein PIN für Bluetooth + Service/Admin + Vollsperre").grid(row=0, column=0, sticky="w")
        ttk.Label(card, text=JARNSEN_DEFAULT_PIN + " 🔒", style="Section.TLabel").grid(row=0, column=1, sticky="w")
        ttk.Label(card, text="Admin-Freigabe").grid(row=1, column=0, sticky="w", pady=2)
        ttk.Label(card, text=f"{JARNSEN_ADMIN_UNLOCK_MINUTES} Minuten").grid(row=1, column=1, sticky="w", pady=2)
        ttk.Label(card, text="Notfall-Vollsperre").grid(row=2, column=0, sticky="w", pady=2)
        ttk.Label(card, text="Doppelklick + 3. Druck 3 s halten").grid(row=2, column=1, sticky="w", pady=2)
        ttk.Label(card, text="Vollsperre bleibt nach Neustart aktiv; Funk/GPS/Tracking/Logging laufen weiter.", style="Subtitle.TLabel", wraplength=900).grid(row=3, column=0, columnspan=2, sticky="w", pady=(4, 6))
        alert_var = tk.BooleanVar(value=bool(profile.get("jarnsen_full_lock_alert_mesh", True)))
        ttk.Checkbutton(card, text="Vollsperren-Alarm über Mesh senden", variable=alert_var).grid(row=4, column=0, columnspan=2, sticky="w")
        ttk.Label(card, text="LOCKED_FULL/UNLOCKED · Name, Node-ID, Zeit und aktuelle/letzte Position; niemals PIN/PSK/Keys.", style="Subtitle.TLabel", wraplength=900).grid(row=5, column=0, columnspan=2, sticky="w", pady=(2, 6))
        def save_policy() -> None:
            profile["jarnsen_pin"] = JARNSEN_DEFAULT_PIN
            profile["jarnsen_admin_unlock_minutes"] = JARNSEN_ADMIN_UNLOCK_MINUTES
            profile["jarnsen_full_lock_alert_mesh"] = bool(alert_var.get())
            profile["jarnsen_full_lock_gesture"] = "DOUBLE_CLICK_THIRD_HOLD_3S"
            profile["saved_at"] = now_local().isoformat(timespec="seconds")
            self._save_config_profile_store(); self._refresh_config_profile_ui()
            tool_log("CONFIG_PROFILE_JARNSEN_POLICY_V2122", pin="fixed-240180", alert=bool(alert_var.get()))
        ttk.Button(card, text="Jarnsen-Schutz speichern", command=save_policy).grid(row=6, column=1, sticky="e", pady=(5, 0))

    def _jarnsen_policy_line_v2122(self, profile: dict[str, object]) -> str:
        self._ensure_jarnsen_policy_defaults_v2122(profile)
        mode = str(profile.get("jarnsen_rf_mode") or "Standard")
        if mode in ("Jarnsen A", "Jarnsen B") and not self._profile_rf_authorization_ready_v2121():
            mode = "Standard"
        rf = {"Standard": "STANDARD", "Jarnsen A": "AUTH_A", "Jarnsen B": "AUTH_B"}.get(mode, "STANDARD")
        alert = 1 if bool(profile.get("jarnsen_full_lock_alert_mesh", True)) else 0
        return f"JARNSEN_TOOL_POLICY {JARNSEN_POLICY_PROTOCOL_VERSION} PIN={JARNSEN_DEFAULT_PIN} ADMIN_MIN={JARNSEN_ADMIN_UNLOCK_MINUTES} FULL_ALERT={alert} LOCK_RETRIES=3 RF={rf}"

    def _apply_jarnsen_policy_serial_v2122(self, connection: tuple[str, str, str], profile: dict[str, object]) -> str:
        if connection[0] != "USB":
            return "Jarnsen PIN/RF/Vollsperren-Policy: bei USB-Provisionierung anwenden"
        port = str(connection[1] or "").strip()
        if not port:
            return "Jarnsen Policy: kein COM-Port"
        command = self._jarnsen_policy_line_v2122(profile)
        time.sleep(0.8)
        try:
            with serial.Serial(port, 115200, timeout=0.20, write_timeout=2.0) as ser:
                ser.reset_input_buffer(); ser.write((command + "\n").encode("ascii")); ser.flush()
                deadline = time.monotonic() + 2.2
                while time.monotonic() < deadline:
                    line = ser.readline().decode("utf-8", "replace").strip()
                    if line.startswith("JARNSEN_TOOL_POLICY_OK"):
                        tool_log("JARNSEN_POLICY_APPLY_V2122", port=port, result="ok")
                        return ""
                    if line.startswith("JARNSEN_TOOL_POLICY_ERR"):
                        raise RuntimeError(line)
            return "Jarnsen Policy: Firmware kennt POLICY v1 noch nicht; nach Firmwareupdate erneut anwenden"
        except Exception as exc:
            tool_log("JARNSEN_POLICY_APPLY_V2122", port=port, result="error", error=exc)
            return f"Jarnsen Policy: {exc}"
'''
    if "    def _ensure_jarnsen_policy_defaults_v2122(" not in source:
        source = insert_before_method(source, "_rename_config_profile", helpers)

    # Security tab card.
    e0, e1 = method_span(source, "_edit_config_profile")
    editor = source[e0:e1]
    profile_anchor = '            return\n        win = tk.Toplevel(self)'
    if "_ensure_jarnsen_policy_defaults_v2122(profile)" not in editor:
        if profile_anchor not in editor:
            raise SystemExit("v2.1.22 editor profile anchor missing")
        editor = editor.replace(profile_anchor, '            return\n        self._ensure_jarnsen_policy_defaults_v2122(profile)\n        win = tk.Toplevel(self)', 1)
    tab_old = '''            row_offset = 0\n            if tab_name == "Erweitert / Freigabe":\n                self._profile_render_rf_authorization_v2121(inner, profile)\n                row_offset = 1\n'''
    tab_new = '''            row_offset = 0\n            if tab_name == "Sicherheit":\n                self._profile_render_jarnsen_security_v2122(inner, profile)\n                row_offset = 1\n            elif tab_name == "Erweitert / Freigabe":\n                self._profile_render_rf_authorization_v2121(inner, profile)\n                row_offset = 1\n'''
    if tab_old not in editor:
        raise SystemExit("v2.1.22 editor tab anchor missing")
    editor = editor.replace(tab_old, tab_new, 1)
    source = source[:e0] + editor + source[e1:]

    # Force PIN for the normal Bluetooth config write and, if present, the deferred BLE write.
    w0, w1 = method_span(source, "_config_profile_apply_worker")
    worker = source[w0:w1]
    normal_parse = '                    desired.ParseFromString(self._decode_protobuf_payload(str(encoded)))\n'
    if normal_parse not in worker:
        raise SystemExit("v2.1.22 config parse anchor missing")
    worker = worker.replace(normal_parse, normal_parse + '                    if name == "bluetooth":\n                        self._force_jarnsen_bluetooth_pin_v2122(desired)\n', 1)

    deferred_parse = '                    desired.ParseFromString(self._decode_protobuf_payload(deferred_bluetooth))\n'
    if deferred_parse in worker:
        worker = worker.replace(deferred_parse, deferred_parse + '                    self._force_jarnsen_bluetooth_pin_v2122(desired)\n', 1)

    # Apply Jarnsen-specific policy last, immediately before the existing verification phase.
    verify_anchor = '            verification = "Rückprüfung nicht möglich"\n'
    if verify_anchor not in worker:
        raise SystemExit("v2.1.22 verification anchor missing")
    policy_block = '''            stage("Jarnsen PIN / Vollsperre / Funkprofil zuletzt anwenden")\n            self._ensure_jarnsen_policy_defaults_v2122(profile)\n            policy_note = self._apply_jarnsen_policy_serial_v2122(connection, profile)\n            if policy_note:\n                skipped.append(policy_note)\n\n'''
    worker = worker.replace(verify_anchor, policy_block + verify_anchor, 1)
    source = source[:w0] + worker + source[w1:]

    required = (
        'APP_VERSION = "2.1.22"', 'JARNSEN_DEFAULT_PIN = "240180"', "JARNSEN_TOOL_POLICY",
        "CONFIG_PROFILE_JARNSEN_POLICY_V2122", "Jarnsen PIN / Vollsperre / Funkprofil zuletzt anwenden",
        "Doppelklick + 3. Druck 3 s halten", "Vollsperren-Alarm über Mesh senden",
        '"Jarnsen A"', '"Jarnsen B"', "JARNSEN_TOOL_HELLO 1", "log_generation", "log_cursor",
    )
    missing = [marker for marker in required if marker not in source]
    if missing:
        raise SystemExit("v2.1.22 validation failed: " + ", ".join(missing))
    return source


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: patch_jarnsen_service_tool_v2122.py <source.py>")
    path = Path(sys.argv[1])
    path.write_text(patch(path.read_text(encoding="utf-8")), encoding="utf-8")
    print(f"Patched {path} to v{APP_VERSION}: one PIN + full-lock policy + RF mode + policy-last handoff")


if __name__ == "__main__":
    main()
