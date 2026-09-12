"""Four editable, write-time-enforced JARNSEN-MESH functional profiles."""

from __future__ import annotations

import copy
import json
import time
from dataclasses import dataclass
from pathlib import Path
from tkinter import messagebox
from typing import Any, Iterable

import yaml


@dataclass(frozen=True)
class FunctionalProfile:
    identifier: str
    label: str
    meshtastic_role: str
    description: str
    firmware_rules: tuple[str, ...]
    locked_values: tuple[tuple[str, Any], ...]


# Locked values mirror the real role policies; hardware runtime owns sensor and sleep mechanics.
FUNCTIONAL_PROFILES: tuple[FunctionalProfile, ...] = (
    FunctionalProfile(
        "tak",
        "TAK",
        "TAK",
        "Führungselement: LoRa bleibt empfangsbereit, LightSleep wenn möglich.",
        (
            "LightSleep / LoRa-Empfang wird von der Firmware und der Hardwarefähigkeit gesteuert.",
            "Bluetooth-Service bleibt bei Nutzung aktiv und endet nach 120 Sekunden Inaktivität.",
        ),
        (
            ("device.role", "TAK"),
            ("power.is_power_saving", True),
            ("power.min_wake_secs", 1),
            ("power.ls_secs", 3600),
            ("power.wait_bluetooth_secs", 120),
            ("bluetooth.enabled", False),
            ("network.wifi_enabled", False),
        ),
    ),
    FunctionalProfile(
        "tak_tracker",
        "TAK TRACKER",
        "TAK_TRACKER",
        "Autonomer Tracker: Parkbetrieb nutzt die DeepSleep-Logik der Firmware.",
        (
            "DeepSleep, Bewegungs-Wakeup und Parkposition sind Firmwarefunktionen.",
            "Bluetooth-Service bleibt bei Nutzung aktiv und endet nach 120 Sekunden Inaktivität.",
        ),
        (
            ("device.role", "TAK_TRACKER"),
            ("power.is_power_saving", True),
            ("power.min_wake_secs", 1),
            ("power.ls_secs", 3600),
            ("power.wait_bluetooth_secs", 120),
            ("bluetooth.enabled", False),
            ("network.wifi_enabled", False),
        ),
    ),
    FunctionalProfile(
        "tak_repeater",
        "TAK REPEATER",
        "ROUTER_LATE",
        "Mobiler Repeater: ROUTER_LATE, LightSleep und Telefon-/Serviceposition.",
        (
            "ROUTER_LATE statt des alten REPEATER: Pakete werden normal verarbeitet und weitergeleitet.",
            "LightSleep mit LoRa-Wakeup bleibt aktiv; Bluetooth wird nur im Servicefenster eingeschaltet.",
            "Die V3-Firmware verwaltet die Telefonposition als kontrolliert gespeicherte Repeater-Position.",
        ),
        (
            ("device.role", "ROUTER_LATE"),
            ("device.rebroadcast_mode", "ALL"),
            ("device.led_heartbeat_disabled", True),
            ("position.fixed_position", True),
            ("power.is_power_saving", True),
            ("power.min_wake_secs", 1),
            ("power.ls_secs", 3600),
            ("power.wait_bluetooth_secs", 120),
            ("bluetooth.enabled", False),
            ("network.wifi_enabled", False),
            ("display.screen_on_secs", 1),
        ),
    ),
    FunctionalProfile(
        "drone_repeater",
        "DRONE REPEATER",
        "ROUTER_LATE",
        "Tracker-V1.1 Drone-Repeater: GNSS aktiv, dynamische Positionspolitik, kein Schlafbetrieb.",
        (
            "Diese Rolle benötigt die eigene Drone-Repeater-Firmware auf dem Heltec Tracker V1.1.",
            "GNSS bleibt aktiv; die Firmware steuert die dynamischen 30/10/7/5-s-Intervalle und die Airtime-Bremse.",
            "Bluetooth ist ein GPIO0-Servicefenster mit 120 Sekunden Inaktivitätszeit.",
        ),
        (
            ("device.role", "ROUTER_LATE"),
            ("device.rebroadcast_mode", "ALL"),
            ("device.button_gpio", 0),
            ("device.disable_triple_click", True),
            ("device.led_heartbeat_disabled", True),
            ("power.is_power_saving", False),
            ("bluetooth.enabled", False),
            ("network.wifi_enabled", False),
            ("display.screen_on_secs", 20),
            ("position.gps_mode", "ENABLED"),
            ("position.fixed_position", False),
            ("position.gps_update_interval", 1),
            ("position.position_broadcast_smart_enabled", True),
            ("position.broadcast_smart_minimum_distance", 25),
            ("position.broadcast_smart_minimum_interval_secs", 10),
            ("position.position_broadcast_secs", 30),
        ),
    ),
)

_BY_ID = {profile.identifier: profile for profile in FUNCTIONAL_PROFILES}
_BY_LABEL = {profile.label: profile for profile in FUNCTIONAL_PROFILES}
SELECT_PLACEHOLDER = "Funktionsprofil wählen …"
_FILENAME = {
    "tak": "TAK.yaml",
    "tak_tracker": "TAK-TRACKER.yaml",
    "tak_repeater": "TAK-REPEATER.yaml",
    "drone_repeater": "DRONE-REPEATER.yaml",
}


def _emit(message: str) -> None:
    try:
        import diagnostics

        diagnostics._emit(message)
    except Exception:
        pass


def functional_profile(profile: str | FunctionalProfile) -> FunctionalProfile:
    if isinstance(profile, FunctionalProfile):
        return profile
    key = str(profile or "").strip().lower()
    if key in _BY_ID:
        return _BY_ID[key]
    by_label = _BY_LABEL.get(str(profile or "").strip().upper())
    if by_label is not None:
        return by_label
    raise KeyError(f"Unbekanntes Funktionsprofil: {profile!r}")


def labels() -> list[str]:
    return [profile.label for profile in FUNCTIONAL_PROFILES]


def is_selectable_label(value: Any) -> bool:
    return str(value or "").strip().upper() in _BY_LABEL


def functional_directory(services: Any) -> Path:
    return Path(services.PATHS.profiles) / "functional"


def profile_path(services: Any, profile: str | FunctionalProfile) -> Path:
    item = functional_profile(profile)
    return functional_directory(services) / _FILENAME[item.identifier]


def _state_path(services: Any) -> Path:
    return Path(services.PATHS.profiles) / "functional-profile-state.json"


def _load_state(services: Any) -> dict[str, Any]:
    try:
        state = json.loads(_state_path(services).read_text(encoding="utf-8"))
        return state if isinstance(state, dict) else {}
    except Exception:
        return {}


def _save_state(services: Any, profile_id: str) -> None:
    target = _state_path(services)
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.with_suffix(".tmp")
    temp.write_text(
        json.dumps({"version": 1, "active": profile_id}, ensure_ascii=False, indent=2)
        + "\n",
        encoding="utf-8",
    )
    temp.replace(target)


def _clear_state(services: Any) -> None:
    try:
        _state_path(services).unlink(missing_ok=True)
    except Exception:
        pass


def active_profile_id(services: Any) -> str | None:
    value = str(_load_state(services).get("active") or "").strip().lower()
    return value if value in _BY_ID else None


def active_profile(services: Any) -> FunctionalProfile | None:
    profile_id = active_profile_id(services)
    return _BY_ID.get(profile_id or "")


def _normal_key(value: str) -> str:
    return str(value or "").replace("_", "").replace("-", "").casefold()


def _matching_key(mapping: dict[str, Any], wanted: str) -> str | None:
    wanted_key = _normal_key(wanted)
    return next(
        (str(key) for key in mapping if _normal_key(str(key)) == wanted_key), None
    )


def _config_root(data: dict[str, Any]) -> dict[str, Any]:
    config_key = _matching_key(data, "config")
    if config_key is not None and isinstance(data.get(config_key), dict):
        return data[config_key]
    return data


def _set_relative(root: dict[str, Any], dotted_path: str, value: Any) -> None:
    parts = dotted_path.split(".")
    node: dict[str, Any] = root
    for part in parts[:-1]:
        key = _matching_key(node, part) or part
        child = node.get(key)
        if not isinstance(child, dict):
            child = {}
            node[key] = child
        node = child
    leaf = _matching_key(node, parts[-1]) or parts[-1]
    node[leaf] = copy.deepcopy(value)


def normalise_profile_data(
    data: dict[str, Any], profile: str | FunctionalProfile
) -> dict[str, Any]:
    """Return a copy with the non-editable functional core restored."""
    item = functional_profile(profile)
    result = copy.deepcopy(data) if isinstance(data, dict) else {}
    root = _config_root(result)
    for path, value in item.locked_values:
        _set_relative(root, path, value)
    return result


def _load_yaml(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8", errors="replace")) or {}
    if not isinstance(data, dict):
        raise ValueError("Profil muss ein YAML-Mapping enthalten.")
    return data


def _write_yaml(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(
        yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )
    temp.replace(path)


def ensure_profiles(services: Any) -> None:
    """Create the four editable canonical files and repair their fixed cores."""
    directory = functional_directory(services)
    directory.mkdir(parents=True, exist_ok=True)
    for item in FUNCTIONAL_PROFILES:
        path = profile_path(services, item)
        try:
            current = _load_yaml(path) if path.exists() else {"config": {}}
            normalised = normalise_profile_data(current, item)
            if not path.exists() or normalised != current:
                _write_yaml(path, normalised)
        except Exception as exc:
            _emit(
                f"FUNCTION PROFILE ENSURE ERROR file={path.name!r} "
                f"type={type(exc).__name__} message={exc}"
            )
    _emit(
        "FUNCTION PROFILES ready count=4 selectable=TAK,TAK_TRACKER,TAK_REPEATER,DRONE_REPEATER"
    )


def function_id_for_path(path: Path | str, services: Any) -> str | None:
    source = Path(path)
    try:
        source_key = str(source.resolve()).casefold()
    except Exception:
        source_key = str(source.absolute()).casefold()
    for item in FUNCTIONAL_PROFILES:
        candidate = profile_path(services, item)
        try:
            candidate_key = str(candidate.resolve()).casefold()
        except Exception:
            candidate_key = str(candidate.absolute()).casefold()
        if source_key == candidate_key:
            return item.identifier
    return None


def is_functional_profile_path(path: Path | str, services: Any) -> bool:
    return function_id_for_path(path, services) is not None


def is_locked_path(profile: str | FunctionalProfile, path: Iterable[str] | str) -> bool:
    """Whether a profile-editor field is part of the immutable role contract."""
    item = functional_profile(profile)
    parts = (
        str(path).split(".") if isinstance(path, str) else [str(part) for part in path]
    )
    visible = [
        part for part in parts if _normal_key(part) not in {"config", "moduleconfig"}
    ]
    needle = ".".join(_normal_key(part) for part in visible)
    return needle in {
        ".".join(_normal_key(part) for part in locked_path.split("."))
        for locked_path, _value in item.locked_values
    }


def locked_field_message(profile: str | FunctionalProfile) -> str:
    item = functional_profile(profile)
    return "\n".join(f"• {rule}" for rule in item.firmware_rules)


def compatibility_for_board(
    profile: str | FunctionalProfile,
    board_key: str | None,
    services: Any,
) -> tuple[bool, str]:
    """Return a user-facing capability decision based on Unified Core facts."""
    item = functional_profile(profile)
    board = str(board_key or "").strip().lower()
    if not board:
        return True, "Board wird beim Schreiben geprüft."
    if board not in services.BOARD_PROFILES:
        return False, f"Unbekanntes Zielboard: {board_key!r}."
    label = str(services.BOARD_PROFILES[board].get("label") or board)

    if item.identifier == "drone_repeater" and board != "tracker":
        return (
            False,
            "DRONE REPEATER ist in der aktuellen Unified-Core-Firmware nur für "
            "Heltec Wireless Tracker V1.1 freigegeben - nicht für "
            f"{label}.",
        )
    if item.identifier == "tak_tracker" and board in {"repeater", "heltec_v4"}:
        return (
            True,
            f"{label}: TAK TRACKER funktioniert nur, wenn die externe GNSS-Hardware "
            "in der Unified-Core-Firmware erkannt und konfiguriert ist.",
        )
    return True, f"{item.label} ist für {label} als Funktionsprofil zulässig."


def firmware_compatibility_for_board(
    profile: str | FunctionalProfile,
    board_key: str | None,
    services: Any,
) -> tuple[bool, str]:
    """Whether the current Unified-Core first-flash artifact can realise it.

    Drone Repeater remains a dedicated Tracker V1.1 firmware line until its
    runtime policy is migrated into Unified Core.  A profile-only write to an
    already-installed legacy Drone build is valid; a first flash with the
    normal Unified artifact is deliberately refused.
    """
    item = functional_profile(profile)
    allowed, message = compatibility_for_board(item, board_key, services)
    if not allowed:
        return allowed, message
    if item.identifier == "drone_repeater":
        return (
            False,
            "DRONE REPEATER benötigt beim Erstflash weiterhin die dedizierte "
            "Heltec-Tracker-V1.1-Drone-Repeater-Firmware. Das normale Unified-Core-Paket "
            "wird dafür nicht verwendet, bis die Runtime-Policy migriert und auf Hardware geprüft ist.",
        )
    return True, message


def require_compatible_board(
    profile: str | FunctionalProfile, board_key: str | None, services: Any
) -> str:
    allowed, message = compatibility_for_board(profile, board_key, services)
    if not allowed:
        raise services.FlasherError(message)
    return message


def _merge_mapping(target: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
    for key, value in incoming.items():
        current_key = _matching_key(target, str(key)) or str(key)
        current = target.get(current_key)
        if isinstance(current, dict) and isinstance(value, dict):
            _merge_mapping(current, value)
        else:
            target[current_key] = copy.deepcopy(value)
    return target


def merge_compatible_settings(
    target: dict[str, Any], incoming: dict[str, Any], profile: str | FunctionalProfile
) -> dict[str, Any]:
    """Copy mesh-wide settings without cloning target-hardware state or identity."""
    result = normalise_profile_data(target, profile)
    for key in ("channels", "canned_messages", "ringtone"):
        source_key = _matching_key(incoming, key)
        if source_key is None:
            continue
        value = incoming[source_key]
        target_key = _matching_key(result, key) or key
        if isinstance(value, dict) and isinstance(result.get(target_key), dict):
            _merge_mapping(result[target_key], value)
        else:
            result[target_key] = copy.deepcopy(value)

    source_root = _config_root(incoming)
    target_root = _config_root(result)
    source_key = _matching_key(source_root, "lora")
    if source_key is not None:
        value = source_root[source_key]
        target_key = _matching_key(target_root, "lora") or "lora"
        if isinstance(value, dict) and isinstance(target_root.get(target_key), dict):
            _merge_mapping(target_root[target_key], value)
        else:
            target_root[target_key] = copy.deepcopy(value)

    source_key = _matching_key(source_root, "security")
    if source_key is not None and isinstance(source_root[source_key], dict):
        identity_keys = {"privatekey", "publickey", "sessionpasskey"}
        safe_security = {
            key: copy.deepcopy(value)
            for key, value in source_root[source_key].items()
            if _normal_key(str(key)) not in identity_keys
        }
        target_key = _matching_key(target_root, "security") or "security"
        if isinstance(target_root.get(target_key), dict):
            _merge_mapping(target_root[target_key], safe_security)
        else:
            target_root[target_key] = safe_security

    return normalise_profile_data(result, profile)


def _update_app_profile(
    app: Any, services: Any, item: FunctionalProfile, path: Path, *, source: str
) -> None:
    from profile_utils import format_summary, summary_from_profile_file

    summary = summary_from_profile_file(path)
    if hasattr(app, "profile_path_var"):
        app.profile_path_var.set(str(path))
    if hasattr(app, "profile_summary_var"):
        app.profile_summary_var.set(format_summary(summary))
    if hasattr(app, "functional_profile_var"):
        app.functional_profile_var.set(item.label)
    if summary.long_name and hasattr(app, "long_name_var"):
        app.long_name_var.set(summary.long_name)
    if summary.short_name and hasattr(app, "short_name_var"):
        app.short_name_var.set(summary.short_name)
    if hasattr(app, "_append_log"):
        app._append_log(
            f"{source} · {item.label} · Rolle={item.meshtastic_role} · Datei={path.name}"
        )
    if hasattr(app, "_set_status"):
        app._set_status(f"{source} · {item.label}")


def activate_functional_profile(
    app: Any, services: Any, selected: str | FunctionalProfile
) -> Path | None:
    item = functional_profile(selected)
    board_key = (
        app._selected_board_key() if hasattr(app, "_selected_board_key") else None
    )
    allowed, reason = compatibility_for_board(item, board_key, services)
    if not allowed:
        messagebox.showerror("Funktionsprofil nicht verfügbar", reason, parent=app)
        return None

    ensure_profiles(services)
    source = profile_path(services, item)
    try:
        services.import_profile_file(source)
        _save_state(services, item.identifier)
        _update_app_profile(
            app, services, item, source, source="Funktionsprofil übernommen"
        )
        if "nur, wenn" in reason and hasattr(app, "_append_log"):
            app._append_log("FUNKTIONSKOMPATIBILITÄT · " + reason)
        return source
    except Exception as exc:
        if hasattr(app, "_show_error"):
            app._show_error(exc)
        else:
            messagebox.showerror("Funktionsprofil", str(exc), parent=app)
        return None


def activate_selected_functional_profile(app: Any, services: Any) -> Path | None:
    selected = ""
    try:
        selected = str(app.functional_profile_var.get() or "")
    except Exception:
        pass
    if not is_selectable_label(selected):
        messagebox.showwarning(
            "Funktionsprofil auswählen",
            "Beim Erstflash bitte zuerst auswählen, als was dieses Board arbeiten soll: "
            "TAK, TAK TRACKER, TAK REPEATER oder DRONE REPEATER.",
            parent=app,
        )
        return None
    return activate_functional_profile(app, services, selected)


def read_master_into_functional_profile(app: Any, services: Any) -> None:
    """Import a master as a compatible-settings overlay, never as a fifth role."""
    device = app._selected_device() if hasattr(app, "_selected_device") else None
    if device is None:
        messagebox.showwarning(
            "Kein Gerät", "Bitte zuerst einen Master-Node verbinden.", parent=app
        )
        return
    if bool(getattr(app, "busy", False)):
        return

    selected = ""
    try:
        selected = str(app.functional_profile_var.get() or "")
    except Exception:
        pass
    if not is_selectable_label(selected):
        messagebox.showwarning(
            "Funktionsprofil auswählen",
            "Bitte zuerst das Funktionsprofil auswählen. Der Master wird dann als kompatible "
            "Basis für genau dieses Profil übernommen.",
            parent=app,
        )
        return
    item = functional_profile(selected)
    app._set_busy(True)

    def worker() -> None:
        try:
            app._set_status(
                f"Master {device.port} einlesen und kompatible Einstellungen übernehmen …"
            )
            exported = Path(services.export_profile(device.port))
            incoming = _load_yaml(exported)
            canonical = profile_path(services, item)
            current = _load_yaml(canonical) if canonical.exists() else {}
            merged = merge_compatible_settings(current, incoming, item)
            _write_yaml(canonical, merged)
            services.import_profile_file(canonical)
            _save_state(services, item.identifier)

            from profile_utils import summary_from_info_text, summary_from_profile_file

            functional_summary = summary_from_profile_file(canonical)
            master_summary = summary_from_profile_file(exported).with_fallback(
                summary_from_info_text(str(getattr(device, "model_text", "") or ""))
            )

            def update() -> None:
                _update_app_profile(
                    app,
                    services,
                    item,
                    canonical,
                    source="Master kompatibel übernommen",
                )
                if master_summary.long_name and hasattr(app, "long_name_var"):
                    app.long_name_var.set(master_summary.long_name)
                if master_summary.short_name and hasattr(app, "short_name_var"):
                    app.short_name_var.set(master_summary.short_name)
                if hasattr(app, "profile_summary_var"):
                    app.profile_summary_var.set(
                        f"Long Name: {master_summary.long_name or '-'}   ·   "
                        f"Short: {master_summary.short_name or '-'}   ·   "
                        f"Rolle: {functional_summary.role or item.meshtastic_role}"
                    )

            app.after(0, update)
            if hasattr(app, "_append_log"):
                app._append_log(
                    "MASTER KOMPATIBEL · "
                    f"Quelle={exported.name} · Ziel={item.label} · "
                    "übernommen=Kanäle,LoRa,sichere-Verwaltung"
                )
            app._set_status(
                f"Master übernommen · {item.label} · Kanäle und Funkprofil bleiben kompatibel"
            )
        except Exception as exc:
            app._show_error(exc)
        finally:
            app._set_busy(False)

    import threading

    threading.Thread(
        target=worker, name="jarnsen-functional-master", daemon=True
    ).start()


def _source_is_active_or_runtime_work(source: Path, services: Any) -> bool:
    active = Path(services.PATHS.active_profile)
    try:
        if source.resolve() == active.resolve():
            return True
    except Exception:
        if source == active:
            return True
    root = Path(services.PATHS.root)
    try:
        return source.resolve().is_relative_to(root.resolve())
    except (AttributeError, OSError):
        return str(source).casefold().startswith(str(root).casefold())


def _normalised_restore_copy(
    services: Any, source: Path, item: FunctionalProfile
) -> Path:
    data = _load_yaml(source)
    normalised = normalise_profile_data(data, item)
    work = Path(services.PATHS.root) / "functional-profile-work"
    work.mkdir(parents=True, exist_ok=True)
    safe = "".join(ch for ch in source.stem if ch.isalnum() or ch in "-_") or "profile"
    target = work / f"{safe}-{time.time_ns()}-functional.yaml"
    _write_yaml(target, normalised)
    return target


def install(services: Any) -> None:
    """Install persistence and write-time enforcement for the four profiles."""
    if getattr(services, "_jarnsen_functional_profiles_installed", False):
        return
    ensure_profiles(services)

    base_import = services.import_profile_file

    def import_profile_file(source: Path) -> Path:
        source = Path(source)
        selected_id = function_id_for_path(source, services)
        result = base_import(source)
        if selected_id is None:
            _clear_state(services)
            return result
        item = _BY_ID[selected_id]
        canonical = profile_path(services, item)
        for path in (canonical, Path(services.PATHS.active_profile)):
            if path.exists():
                _write_yaml(path, normalise_profile_data(_load_yaml(path), item))
        _save_state(services, selected_id)
        _emit(f"FUNCTION PROFILE SELECT id={selected_id!r} file={canonical.name!r}")
        return result

    services.import_profile_file = import_profile_file

    base_restore = services.restore_profile

    def restore_profile(port: str, profile: Path | None = None) -> None:
        source = Path(profile or services.PATHS.active_profile)
        selected_id = function_id_for_path(source, services)
        if selected_id is None and _source_is_active_or_runtime_work(source, services):
            selected_id = active_profile_id(services)
        if selected_id is None:
            return base_restore(port, profile)

        item = _BY_ID[selected_id]
        active = Path(services.PATHS.active_profile)
        try:
            source_is_active = source.resolve() == active.resolve()
        except Exception:
            source_is_active = source == active
        if source_is_active:
            _write_yaml(source, normalise_profile_data(_load_yaml(source), item))
        staged = _normalised_restore_copy(services, source, item)
        _emit(
            f"FUNCTION PROFILE ENFORCE port={port} id={selected_id!r} "
            f"role={item.meshtastic_role!r} source={source.name!r}"
        )
        try:
            return base_restore(port, staged)
        finally:
            try:
                staged.unlink(missing_ok=True)
            except Exception:
                pass

    services.restore_profile = restore_profile
    services.functional_profiles = FUNCTIONAL_PROFILES
    services.functional_profile_labels = labels
    services.functional_profile_path = lambda value: profile_path(services, value)
    services.functional_profile_active = lambda: active_profile(services)
    services.functional_profile_compatibility = (
        lambda value, board: compatibility_for_board(value, board, services)
    )
    services.functional_profile_firmware_compatibility = (
        lambda value, board: firmware_compatibility_for_board(value, board, services)
    )
    services._jarnsen_functional_profiles_installed = True
    _emit(
        "FUNCTION PROFILE RUNTIME installed fixed-core=1 master-compatible-merge=1 write-enforcement=1"
    )
