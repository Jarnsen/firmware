from __future__ import annotations

import hashlib
import json
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

PROFILE_SCHEMA_VERSION = 2


def _emit(message: str) -> None:
    try:
        import diagnostics
        diagnostics._emit(message)
    except Exception:
        pass


def _key(path: Path) -> str:
    try:
        return str(path.resolve()).casefold()
    except Exception:
        return str(path.absolute()).casefold()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().lower()


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(path)
    data = yaml.safe_load(path.read_text(encoding="utf-8", errors="replace")) or {}
    if not isinstance(data, dict):
        raise ValueError("Profil muss eine YAML-Zuordnung enthalten.")
    return data


def _flatten(value: Any, prefix: str = "") -> dict[str, Any]:
    found: dict[str, Any] = {}
    if isinstance(value, dict):
        for key, item in value.items():
            name = f"{prefix}.{key}" if prefix else str(key)
            if isinstance(item, dict):
                found.update(_flatten(item, name))
            elif isinstance(item, list):
                found[name] = item
            else:
                found[name] = item
    elif prefix:
        found[prefix] = value
    return found


def _normalize_scalar(value: Any) -> Any:
    if isinstance(value, str):
        return value.strip()
    return value


def _ignored_key(key: str) -> bool:
    lowered = key.casefold()
    volatile = (
        "owner.longname",
        "owner.shortname",
        "owner.long_name",
        "owner.short_name",
        "metadata",
        "node_num",
        "node_id",
        "last_heard",
        "snr",
        "rssi",
        "uptime",
    )
    return any(lowered == item or lowered.startswith(item + ".") for item in volatile)


class ProfileContractManager:
    def __init__(self, services: Any) -> None:
        self.services = services
        self.path = Path(services.PATHS.profiles) / "profile-contracts.json"

    def _load(self) -> dict[str, Any]:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                data.setdefault("schema", PROFILE_SCHEMA_VERSION)
                data.setdefault("profiles", {})
                return data
        except Exception:
            pass
        return {"schema": PROFILE_SCHEMA_VERSION, "profiles": {}}

    def _save(self, data: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.path.with_suffix(".tmp")
        temp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temp.replace(self.path)

    def ensure(self, profile: Path, board_key: str | None = None) -> dict[str, Any]:
        profile = Path(profile)
        data = _load_yaml(profile)
        flat = _flatten(data)
        catalog_board = None
        try:
            from profile_catalog import board_for_profile
            catalog_board = board_for_profile(profile)
        except Exception:
            pass
        effective_board = board_key or catalog_board or ""
        if effective_board and effective_board not in self.services.BOARD_PROFILES:
            raise self.services.FlasherError(f"Profilvertrag: unbekanntes Board {effective_board!r}.")

        store = self._load()
        profiles = store.setdefault("profiles", {})
        key = _key(profile)
        previous = profiles.get(key) if isinstance(profiles.get(key), dict) else {}
        previous_schema = int(previous.get("schema") or 0)
        entry = {
            "schema": PROFILE_SCHEMA_VERSION,
            "path": str(profile),
            "filename": profile.name,
            "sha256": _sha256(profile),
            "board_key": effective_board,
            "role_present": any(
                item.casefold().endswith("device.role") or item.casefold() == "role"
                for item in flat
            ),
            "scalar_keys": sum(1 for value in flat.values() if not isinstance(value, (dict, list))),
            "updated_at": datetime.now().isoformat(timespec="seconds"),
            "migrated_from": previous_schema if previous_schema < PROFILE_SCHEMA_VERSION else previous.get("migrated_from", 0),
        }
        profiles[key] = entry
        store["schema"] = PROFILE_SCHEMA_VERSION
        self._save(store)
        _emit(
            f"PROFILE CONTRACT ensure file={profile.name!r} schema={PROFILE_SCHEMA_VERSION} "
            f"migrated_from={entry['migrated_from']} board={effective_board!r} keys={len(flat)}"
        )
        return dict(entry)

    def compatibility(
        self,
        profile: Path,
        board_key: str | None = None,
        firmware_identity: Any = None,
    ) -> dict[str, Any]:
        profile = Path(profile)
        entry = self.ensure(profile, board_key)
        warnings: list[str] = []
        errors: list[str] = []

        assigned = str(entry.get("board_key") or "")
        if board_key and assigned and assigned != board_key:
            errors.append(
                f"Profil ist {self.services.BOARD_PROFILES[assigned]['label']} zugeordnet, "
                f"Ziel ist {self.services.BOARD_PROFILES[board_key]['label']}."
            )
        if not bool(entry.get("role_present")):
            warnings.append("Profil enthält keine explizite device.role; aktuelle Rolle bleibt maßgeblich.")
        if firmware_identity is not None and not bool(getattr(firmware_identity, "is_jarnsen", False)):
            warnings.append("Installierte Firmware meldet keinen JARNSEN-Servicevertrag.")

        return {
            "compatible": not errors,
            "schema": PROFILE_SCHEMA_VERSION,
            "entry": entry,
            "warnings": warnings,
            "errors": errors,
        }

    def diff_against_node(self, port: str, profile: Path) -> list[dict[str, Any]]:
        profile = Path(profile)
        wanted = _flatten(_load_yaml(profile))
        work = Path(self.services.PATHS.root) / "profile-diff"
        work.mkdir(parents=True, exist_ok=True)
        target = work / (
            "node-"
            + re.sub(r"[^A-Za-z0-9_.-]+", "-", str(port))
            + f"-{time.time_ns()}.yaml"
        )
        try:
            self.services.meshtastic(port, "--export-config", str(target), timeout=90)
            if not target.exists():
                raise self.services.FlasherError("Node-Konfiguration konnte für den Profilvergleich nicht exportiert werden.")
            actual = _flatten(_load_yaml(target))
        finally:
            try:
                target.unlink(missing_ok=True)
            except Exception:
                pass

        differences: list[dict[str, Any]] = []
        for key, expected in wanted.items():
            if _ignored_key(key):
                continue
            if key not in actual:
                differences.append({"key": key, "expected": expected, "actual": "<fehlt>"})
                continue
            current = actual[key]
            if _normalize_scalar(current) != _normalize_scalar(expected):
                differences.append({"key": key, "expected": expected, "actual": current})
        _emit(
            f"PROFILE DIFF port={port} file={profile.name!r} differences={len(differences)} "
            f"compared={len(wanted)}"
        )
        return differences


def install(services: Any) -> None:
    if getattr(services, "_jarnsen_profile_contract_v2", False):
        return

    manager = ProfileContractManager(services)
    services.profile_contracts = manager
    services.ensure_profile_contract = manager.ensure
    services.check_profile_compatibility = manager.compatibility
    services.diff_profile_to_node = manager.diff_against_node

    base_restore = services.restore_profile

    def restore_profile(port: str, profile=None):
        profile_path = Path(profile) if profile is not None else Path(services.PATHS.active_profile)
        board_key = ""
        try:
            from profile_catalog import board_for_profile
            board_key = str(board_for_profile(profile_path) or "")
        except Exception:
            pass
        compatibility = manager.compatibility(profile_path, board_key or None)
        if not compatibility["compatible"]:
            raise services.FlasherError(
                "Profil/Firmware-Kompatibilitätsprüfung fehlgeschlagen:\n"
                + "\n".join(str(item) for item in compatibility["errors"])
            )
        for warning in compatibility["warnings"]:
            _emit(f"PROFILE CONTRACT WARNING port={port} warning={warning!r}")
        return base_restore(port, profile)

    services.restore_profile = restore_profile
    services._jarnsen_profile_contract_v2 = True
    services._jarnsen_profile_schema_version = PROFILE_SCHEMA_VERSION
    _emit(
        "PROFILE CONTRACT installed schema=2 sidecar-migration=1 yaml-foreign-fields=0 "
        "node-diff=1 compatibility-gate=1"
    )
