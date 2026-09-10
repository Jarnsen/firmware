"""Explicit role/name decisions before Framework7 profile writes.

The visible UI must decide between the current device role and the role stored in
the selected base profile. The decision is also enforced in the bridge so a
direct local API call cannot silently bypass it. Temporary role overrides are
applied to a deep-copied profile only for the worker being started; the saved
profile remains unchanged.

Blank target names are never delegated to the legacy profile apply path. They
preserve the currently known node identity instead; if that identity cannot be
read reliably, the apply is blocked rather than risking an empty owner name.
"""
from __future__ import annotations

import contextlib
import copy
import re
from typing import Any


def _role_name(message: Any) -> str:
    field = getattr(getattr(message, "DESCRIPTOR", None), "fields_by_name", {}).get("role")
    value = int(getattr(message, "role", 0) or 0)
    enum = field.enum_type.values_by_number.get(value) if field is not None and field.enum_type else None
    return str(enum.name if enum is not None else value).upper()


def _normalized_role(value: object) -> str:
    return re.sub(r"[^A-Z0-9]+", "_", str(value or "").strip().upper()).strip("_")


def _profile_at(tool: Any, slot: int) -> dict[str, Any]:
    store = tool.config_profile_store
    profiles = store.get("profiles", []) if isinstance(store, dict) else []
    profile = profiles[slot] if isinstance(profiles, list) and 0 <= slot < len(profiles) else None
    if not isinstance(profile, dict):
        raise RuntimeError(f"Grundprofil {slot + 1} ist leer")
    return profile


def _profile_role(tool: Any, profile: dict[str, Any]) -> str:
    try:
        message = tool._profile_message(profile, "config", "device")
        return _role_name(message)
    except Exception as exc:
        raise RuntimeError(f"Rolle im Grundprofil konnte nicht gelesen werden: {exc}") from exc


def _latest_node_values(tool: Any, node_id: str) -> dict[str, str]:
    result = {"role": "", "long_name": "", "short_name": "", "source": ""}
    repository = getattr(tool, "repository", None)
    latest = None
    if repository is not None:
        with contextlib.suppress(Exception):
            latest = repository.latest_log(node_id)
    if isinstance(latest, dict):
        metrics = latest.get("metrics") if isinstance(latest.get("metrics"), dict) else {}
        result.update(
            role=_normalized_role(metrics.get("role") or latest.get("role")),
            long_name=str(metrics.get("long_name") or latest.get("long_name") or "").strip(),
            short_name=str(metrics.get("short_name") or latest.get("short_name") or "").strip(),
            source="letzter Diagnose-Log",
        )
    return result


def _current_node_values(bridge: Any, node_id: str) -> dict[str, str]:
    """Prefer a direct USB read; use the latest node log as BLE/offline fallback."""
    tool = bridge.tool
    result = _latest_node_values(tool, node_id)
    port = ""
    if hasattr(bridge, "_current_usb_port"):
        with contextlib.suppress(Exception):
            port = str(bridge._current_usb_port(node_id) or "").strip()
    if not port or not hasattr(tool, "_connected_node_snapshot"):
        return result
    try:
        snapshot = tool._connected_node_snapshot(("USB", port, port))
    except Exception:
        return result
    if isinstance(snapshot, dict):
        result.update(
            role=_normalized_role(snapshot.get("role")) or result["role"],
            long_name=str(snapshot.get("long_name") or result["long_name"]).strip(),
            short_name=str(snapshot.get("short_name") or result["short_name"]).strip(),
            source=f"direkt über {port}",
        )
    return result


def _profile_with_role(tool: Any, profile: dict[str, Any], role_name: str) -> dict[str, Any]:
    cloned = copy.deepcopy(profile)
    message = tool._profile_message(cloned, "config", "device")
    field = getattr(getattr(message, "DESCRIPTOR", None), "fields_by_name", {}).get("role")
    enum_type = field.enum_type if field is not None else None
    normalized = _normalized_role(role_name)
    enum = enum_type.values_by_name.get(normalized) if enum_type is not None else None
    if enum is None:
        raise RuntimeError(f"Rolle {role_name!r} ist im Zielprofil nicht gültig")
    message.role = int(enum.number)
    config = cloned.get("config")
    if not isinstance(config, dict):
        config = {}
        cloned["config"] = config
    encoder = getattr(tool, "_protobuf_payload", None)
    if not callable(encoder):
        raise RuntimeError("Profil-Encoder ist im Servicekern nicht verfügbar")
    config["device"] = encoder(message)
    return cloned


def _name_changes(current: dict[str, str], payload: dict[str, Any]) -> list[dict[str, str]]:
    changes: list[dict[str, str]] = []
    desired_long = str(payload.get("long_name") or "").strip()
    desired_short = str(payload.get("short_name") or "").strip()
    if desired_long and desired_long != current.get("long_name", ""):
        changes.append({"field": "Long Name", "old": current.get("long_name", ""), "new": desired_long})
    if desired_short and desired_short[:4] != current.get("short_name", ""):
        changes.append({"field": "Short Name", "old": current.get("short_name", ""), "new": desired_short[:4]})
    return changes


def _guard_target_names(
    current: dict[str, str], payload: dict[str, Any]
) -> tuple[dict[str, Any], list[str]]:
    """Preserve current names whenever an apply payload leaves them blank.

    The legacy profile bridge writes both target-name variables unconditionally.
    Therefore a blank value must be resolved before delegation. If the current
    identity is unavailable, fail safe instead of silently clearing a node name.
    """
    guarded = dict(payload)
    preserved: list[str] = []
    fields = (
        ("long_name", "Long Name"),
        ("short_name", "Short Name"),
    )
    for key, label in fields:
        desired = str(payload.get(key) or "").strip()
        if desired:
            continue
        existing = str(current.get(key) or "").strip()
        if not existing:
            raise RuntimeError(
                f"{label} der Ziel-Node konnte nicht sicher gelesen werden; "
                "Profil wurde nicht übertragen, damit kein leerer Name geschrieben wird"
            )
        guarded[key] = existing[:4] if key == "short_name" else existing
        preserved.append(key)
    return guarded, preserved


def install_profile_decisions(LegacyBridge: type) -> None:
    if bool(getattr(LegacyBridge, "_framework7_profile_decisions_installed", False)):
        return
    previous_profile_action = LegacyBridge.profile_action
    previous_status = LegacyBridge.service_status

    def profile_action(self: Any, payload: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise RuntimeError("Profilaktion muss ein JSON-Objekt sein")
        command = str(payload.get("command") or "").strip()
        if command not in {"preflight", "apply"}:
            return previous_profile_action(self, payload)

        try:
            slot = int(payload.get("slot", -1))
        except (TypeError, ValueError) as exc:
            raise RuntimeError("Ungültiger Grundprofil-Slot") from exc
        node_id = str(payload.get("node_id") or "").strip()
        if not node_id:
            raise RuntimeError("Bitte eine Ziel-Node auswählen")
        profile = _profile_at(self.tool, slot)
        current = self.call_ui(lambda: _current_node_values(self, node_id), timeout=30.0)
        profile_role = self.call_ui(lambda: _profile_role(self.tool, profile), timeout=15.0)
        current_role = _normalized_role(current.get("role"))
        profile_role = _normalized_role(profile_role)
        mismatch = bool(current_role and profile_role and current_role != profile_role)
        changes = _name_changes(current, payload)

        decision = {
            "ok": True,
            "node_id": node_id,
            "slot": slot,
            "profile_name": str(profile.get("name") or f"Profil {slot + 1}"),
            "current_role": current_role,
            "profile_role": profile_role,
            "role_mismatch": mismatch,
            "current_long_name": current.get("long_name", ""),
            "current_short_name": current.get("short_name", ""),
            "name_changes": changes,
            "source": current.get("source", ""),
        }
        if command == "preflight":
            return decision

        chosen_role = _normalized_role(payload.get("role_choice"))
        if mismatch:
            allowed = {current_role, profile_role}
            if chosen_role not in allowed:
                raise RuntimeError(
                    f"Rollenentscheidung erforderlich: {current_role} oder {profile_role} auswählen"
                )
        elif chosen_role and chosen_role not in {current_role, profile_role}:
            raise RuntimeError("Die ausgewählte Rolle gehört nicht zu diesem Profilauftrag")
        if changes and not bool(payload.get("confirm_name_change", False)):
            detail = ", ".join(f"{x['field']}: {x['old'] or '—'} → {x['new']}" for x in changes)
            raise RuntimeError("Namensänderung muss bestätigt werden: " + detail)

        guarded_payload, preserved_names = _guard_target_names(current, payload)

        # Keep the stored profile immutable. start_config_profile_apply captures
        # the profile object synchronously as the worker argument; restore the
        # slot immediately after that worker has been started.
        store = self.tool.config_profile_store
        profiles = store.get("profiles", []) if isinstance(store, dict) else []
        if not isinstance(profiles, list) or not (0 <= slot < len(profiles)):
            raise RuntimeError("Grundprofil-Speicher ist nicht verfügbar")
        original = profiles[slot]
        if mismatch and chosen_role == current_role:
            profiles[slot] = _profile_with_role(self.tool, profile, current_role)
        try:
            result = previous_profile_action(self, guarded_payload)
        finally:
            profiles[slot] = original
        if isinstance(result, dict):
            result["role_choice"] = chosen_role or profile_role
            result["role_mismatch"] = mismatch
            result["name_change_confirmed"] = bool(changes)
            result["preserved_name_fields"] = preserved_names
        return result

    LegacyBridge.profile_action = profile_action

    def service_status(self: Any) -> dict[str, Any]:
        data = previous_status(self)
        critical = data.setdefault("critical", {})
        critical["profile_role_confirmation"] = True
        critical["profile_name_confirmation"] = True
        critical["profile_blank_name_preservation"] = True
        data["ok"] = all(bool(value) for value in critical.values())
        return data

    LegacyBridge.service_status = service_status
    LegacyBridge._framework7_profile_decisions_installed = True
