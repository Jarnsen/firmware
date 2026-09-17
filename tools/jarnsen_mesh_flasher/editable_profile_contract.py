from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

_INSTALLED = False


def _emit(message: str) -> None:
    try:
        import diagnostics

        diagnostics._emit(message)
    except Exception:
        pass


def _normal_key(value: Any) -> str:
    return str(value or "").replace("_", "").replace("-", "").casefold()


def _is_device_role_path(path: Any) -> bool:
    if isinstance(path, str):
        parts = path.split(".")
    else:
        try:
            parts = [str(part) for part in path]
        except Exception:
            parts = [str(path)]
    visible = [
        part
        for part in parts
        if _normal_key(part) not in {"config", "moduleconfig"}
    ]
    return [_normal_key(part) for part in visible] == ["device", "role"]


def _install_functional_profile_policy(services: Any) -> None:
    import functional_profiles as profiles

    if getattr(profiles, "_jarnsen_editable_profile_contract", False):
        return

    legacy_normalise = profiles.normalise_profile_data
    profiles._jarnsen_legacy_normalise_profile_data = legacy_normalise

    def role_only_normalise(data: dict[str, Any], profile: Any) -> dict[str, Any]:
        """Keep the selected function role authoritative without resetting user settings."""
        item = profiles.functional_profile(profile)
        result = copy.deepcopy(data) if isinstance(data, dict) else {}
        root = profiles._config_root(result)
        profiles._set_relative(root, "device.role", item.meshtastic_role)
        return result

    def editable_locked_path(profile: Any, path: Any) -> bool:
        # The selected functional role stays coherent with the firmware role service.
        # Power, LoRa, Position, Bluetooth, Display, Network, modules, etc. are
        # ordinary user configuration and must remain editable.
        profiles.functional_profile(profile)
        return _is_device_role_path(path)

    def editable_locked_message(profile: Any) -> str:
        item = profiles.functional_profile(profile)
        return (
            f"{item.label}: Nur die Funktionsrolle wird über die Profilwahl gesteuert. "
            "Alle übrigen Grundeinstellungen sind bearbeitbar und werden nicht "
            "automatisch auf Preset-Werte zurückgesetzt."
        )

    def minimum_profile(item: Any) -> dict[str, Any]:
        return role_only_normalise({"config": {}}, item)

    def is_legacy_generated_only(data: dict[str, Any], item: Any) -> bool:
        try:
            return data == legacy_normalise({"config": {}}, item)
        except Exception:
            return False

    def ensure_editable_profiles(runtime_services: Any) -> None:
        """Create role-only seeds and never repair user-edited values back to presets."""
        directory = profiles.functional_directory(runtime_services)
        directory.mkdir(parents=True, exist_ok=True)
        created = 0
        migrated = 0
        role_fixed = 0

        for item in profiles.FUNCTIONAL_PROFILES:
            path = profiles.profile_path(runtime_services, item)
            try:
                if not path.exists():
                    profiles._write_yaml(path, minimum_profile(item))
                    created += 1
                    continue

                current = profiles._load_yaml(path)
                if is_legacy_generated_only(current, item):
                    profiles._write_yaml(path, minimum_profile(item))
                    migrated += 1
                    continue

                corrected = role_only_normalise(current, item)
                if corrected != current:
                    profiles._write_yaml(path, corrected)
                    role_fixed += 1
            except Exception as exc:
                _emit(
                    f"EDITABLE PROFILE ENSURE ERROR file={path.name!r} "
                    f"type={type(exc).__name__} message={exc}"
                )

        # If the old active profile was nothing but the generated fixed core,
        # migrate it as well.  Any profile containing additional/user values is
        # preserved exactly apart from the functional role.
        active_id = profiles.active_profile_id(runtime_services)
        active = Path(runtime_services.PATHS.active_profile)
        if active_id and active.exists():
            try:
                item = profiles.functional_profile(active_id)
                current = profiles._load_yaml(active)
                if is_legacy_generated_only(current, item):
                    profiles._write_yaml(active, minimum_profile(item))
                    migrated += 1
                else:
                    corrected = role_only_normalise(current, item)
                    if corrected != current:
                        profiles._write_yaml(active, corrected)
                        role_fixed += 1
            except Exception as exc:
                _emit(
                    f"EDITABLE PROFILE ACTIVE ERROR file={active.name!r} "
                    f"type={type(exc).__name__} message={exc}"
                )

        _emit(
            "EDITABLE FUNCTION PROFILES ready "
            f"created={created} migrated-legacy={migrated} role-fixed={role_fixed} "
            "firmware-defaults-first=1 user-settings-preserved=1 role-only-lock=1"
        )

    profiles.normalise_profile_data = role_only_normalise
    profiles.is_locked_path = editable_locked_path
    profiles.locked_field_message = editable_locked_message
    profiles.ensure_profiles = ensure_editable_profiles
    profiles._jarnsen_editable_profile_contract = True

    services._jarnsen_editable_profile_contract = True
    services._jarnsen_function_role_only_lock = True
    services._jarnsen_firmware_defaults_first = True

    _emit(
        "EDITABLE PROFILE CONTRACT functional-policy installed "
        "role-only-lock=1 fixed-power=0 fixed-bluetooth=0 fixed-lora=0 "
        "fixed-position=0 fixed-display=0 firmware-defaults-first=1"
    )


def _install_role_sync() -> None:
    """Keep config.device.role in the same transaction as the JARNSEN role service."""
    import profile_runtime_efficiency as efficiency

    if getattr(efficiency, "_jarnsen_editable_role_sync", False):
        return

    def merge_fast_final_payload(
        safe: dict[str, Any],
        final: dict[str, Any],
        *,
        role_api_authoritative: bool,
    ) -> dict[str, Any]:
        # Build 168+ has a persistent JARNSEN role service, but Meshtastic still
        # exposes config.device.role and final verification reads that value.
        # Do not drop device.role merely because role_api=1 exists.  Writing both
        # authoritative stores to the same selected role prevents the
        # TAK-vs-TAK_TRACKER split seen in the physical profile-only run.
        merged = efficiency._merge_mapping(safe, copy.deepcopy(final))
        if role_api_authoritative and efficiency._profile_role(final):
            _emit(
                "EDITABLE PROFILE ROLE SYNC merge role-api=1 "
                "meshtastic-device-role=kept same-transaction=1"
            )
        return merged

    efficiency._merge_fast_final_payload = merge_fast_final_payload
    efficiency._jarnsen_editable_role_sync = True
    _emit(
        "EDITABLE PROFILE CONTRACT role-sync installed "
        "role-api-and-device-role=1 same-transaction=1"
    )


def _install_editor_copy() -> None:
    """Make the editor wording match the editable runtime contract."""
    import profile_editor as editor

    if getattr(editor, "_jarnsen_editable_profile_editor", False):
        return

    base_open = editor.open_profile_editor

    def open_profile_editor(root: Any, services: Any, source: Path):
        original_label = editor.ctk.CTkLabel

        def editable_label(*args: Any, **kwargs: Any):
            text = kwargs.get("text")
            if isinstance(text, str):
                if "Funktionskern ist gesperrt" in text:
                    prefix = text.split(": Funktionskern", 1)[0]
                    kwargs["text"] = (
                        f"{prefix}: Funktionsrolle wird über die Profilwahl gesteuert. "
                        "Alle übrigen Grundeinstellungen sind frei bearbeitbar und "
                        "werden beim Speichern nicht auf Preset-Werte zurückgesetzt."
                    )
                elif text == "Funktionskern - nicht änderbar":
                    kwargs["text"] = "Funktionsrolle - über Profilwahl gesteuert"
            return original_label(*args, **kwargs)

        editor.ctk.CTkLabel = editable_label
        try:
            return base_open(root, services, source)
        finally:
            editor.ctk.CTkLabel = original_label

    editor.open_profile_editor = open_profile_editor
    editor._jarnsen_editable_profile_editor = True
    _emit(
        "EDITABLE PROFILE CONTRACT editor installed "
        "settings-editable=1 role-selection-owned=1 misleading-lock-text=0"
    )


def install(services: Any) -> None:
    """Switch functional profiles from immutable presets to editable configuration.

    Firmware defaults remain the first source of ordinary settings.  Functional
    profile files only guarantee the selected role; later values saved/read by the
    Flasher remain user-owned.  The role is written to both the JARNSEN persistent
    role service and Meshtastic config.device.role.
    """
    global _INSTALLED
    if _INSTALLED and getattr(services, "_jarnsen_editable_profile_contract", False):
        return

    _install_functional_profile_policy(services)
    _install_role_sync()
    _install_editor_copy()

    _INSTALLED = True
    services._jarnsen_editable_profile_contract = True
    _emit(
        "EDITABLE PROFILE CONTRACT installed "
        "firmware-defaults-first=1 later-flasher-editable=1 "
        "role-sync=1 profile-preset-reset=0"
    )
