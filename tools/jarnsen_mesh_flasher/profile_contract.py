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


def _protobuf_default_equivalent(expected: Any) -> bool:
    """Whether an omitted proto3 scalar represents the requested value."""
    if expected is False or expected is None:
        return True
    if isinstance(expected, (int, float)) and not isinstance(expected, bool):
        return expected == 0
    return isinstance(expected, str) and expected == ""


def _auto_tx_power_equivalent(key: str, expected: Any, current: Any) -> bool:
    """tx_power=0 is the profile contract for firmware/platform maximum."""
    normalized = ".".join(
        re.sub(r"[^a-z0-9]+", "", part.casefold()) for part in key.split(".")
    )
    if not normalized.endswith("config.lora.txpower"):
        return False
    if isinstance(expected, bool) or expected != 0:
        return False
    if current is None:
        return True
    # JARNSEN 1/2 are fixed US-region profiles. Meshtastic expands auto/zero
    # to the US regional ceiling (30 dBm) during radio initialisation and then
    # exposes that effective value through --info/--export-config.
    return (
        isinstance(current, (int, float))
        and not isinstance(current, bool)
        and current in {0, 30}
    )


def _normalized_flat(values: dict[str, Any]) -> dict[str, tuple[str, Any]]:
    return {
        ".".join(
            re.sub(r"[^a-z0-9]+", "", part.casefold()) for part in key.split(".")
        ): (key, value)
        for key, value in values.items()
    }


def _ignored_key(key: str) -> bool:
    lowered = key.casefold()
    normalized = ".".join(
        re.sub(r"[^a-z0-9]+", "", part) for part in lowered.split(".")
    )
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
    if normalized.endswith("security.privatekey") or normalized.endswith(
        "security.publickey"
    ):
        return True
    if normalized in {"owner", "ownershort", "longname", "shortname"}:
        return True
    return any(
        lowered == item
        or lowered.startswith(item + ".")
        or lowered.endswith("." + item)
        for item in volatile
    )


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
        temp.write_text(
            json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
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
            raise self.services.FlasherError(
                f"Profilvertrag: unbekanntes Board {effective_board!r}."
            )

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
            "scalar_keys": sum(
                1 for value in flat.values() if not isinstance(value, (dict, list))
            ),
            "updated_at": datetime.now().isoformat(timespec="seconds"),
            "migrated_from": (
                previous_schema
                if previous_schema < PROFILE_SCHEMA_VERSION
                else previous.get("migrated_from", 0)
            ),
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
            warnings.append(
                "Profil enthält keine explizite device.role; aktuelle Rolle bleibt maßgeblich."
            )
        if firmware_identity is not None and not bool(
            getattr(firmware_identity, "is_jarnsen", False)
        ):
            warnings.append(
                "Installierte Firmware meldet keinen JARNSEN-Servicevertrag."
            )

        return {
            "compatible": not errors,
            "schema": PROFILE_SCHEMA_VERSION,
            "entry": entry,
            "warnings": warnings,
            "errors": errors,
        }

    def _firmware_managed_keys(self, board_key: str | None) -> set[str]:
        """Fields whose effective value is owned by the selected role runtime."""
        if str(board_key or "").strip().casefold() != "tracker":
            return set()
        try:
            from functional_profiles import active_profile

            selected = active_profile(self.services)
            identifier = (
                str(getattr(selected, "identifier", "") or "").strip().casefold()
            )
        except Exception:
            identifier = ""
        if identifier not in {"tak", "tak_tracker"}:
            return set()
        # Unified-Core Tracker policy derives these from the configured park
        # interval and its 120-second GPIO service window. It intentionally
        # reapplies the effective values after every boot.
        return {
            "config.power.lssecs",
            "config.power.waitbluetoothsecs",
        }

    def diff_against_node(
        self, port: str, profile: Path, board_key: str | None = None
    ) -> list[dict[str, Any]]:
        profile = Path(profile)
        wanted_data = _load_yaml(profile)
        load_radio = getattr(self.services, "load_radio_profile_settings", None)
        apply_radio = getattr(self.services, "apply_radio_profile_overlay", None)
        if callable(load_radio) and callable(apply_radio):
            try:
                wanted_data = apply_radio(wanted_data, load_radio())
            except Exception as exc:
                raise self.services.FlasherError(
                    f"Aktives Funkprofil konnte für die Endprüfung nicht angewendet werden: {exc}"
                ) from exc
        wanted = _flatten(wanted_data)
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
                raise self.services.FlasherError(
                    "Node-Konfiguration konnte für den Profilvergleich nicht exportiert werden."
                )
            actual = _flatten(_load_yaml(target))
        finally:
            try:
                target.unlink(missing_ok=True)
            except Exception:
                pass

        differences: list[dict[str, Any]] = []
        normalized_actual = _normalized_flat(actual)
        firmware_managed = self._firmware_managed_keys(board_key)
        for key, expected in wanted.items():
            if _ignored_key(key):
                continue
            normalized_key = ".".join(
                re.sub(r"[^a-z0-9]+", "", part.casefold()) for part in key.split(".")
            )
            if normalized_key in firmware_managed:
                _emit(
                    f"PROFILE DIFF SEMANTIC port={port} key={key!r} "
                    f"expected={expected!r} result=firmware-managed board={board_key!r}"
                )
                continue
            actual_record = normalized_actual.get(normalized_key)
            if actual_record is None:
                if _protobuf_default_equivalent(expected) or _auto_tx_power_equivalent(
                    key, expected, None
                ):
                    _emit(
                        f"PROFILE DIFF SEMANTIC port={port} key={key!r} "
                        f"expected={expected!r} actual='<omitted-default>' result=equal"
                    )
                    continue
                differences.append(
                    {"key": key, "expected": expected, "actual": "<fehlt>"}
                )
                continue
            current = actual_record[1]
            if _auto_tx_power_equivalent(key, expected, current):
                _emit(
                    f"PROFILE DIFF SEMANTIC port={port} key={key!r} "
                    f"expected=auto actual={current!r} result=equal"
                )
                continue
            if _normalize_scalar(current) != _normalize_scalar(expected):
                differences.append(
                    {"key": key, "expected": expected, "actual": current}
                )
                _emit(
                    f"PROFILE DIFF MISMATCH port={port} key={key!r} "
                    f"expected={expected!r} actual={current!r}"
                )
        _emit(
            f"PROFILE DIFF port={port} file={profile.name!r} differences={len(differences)} "
            f"compared={len(wanted)}"
        )
        return differences

    def verify_written(
        self, port: str, profile: Path | None = None, board_key: str | None = None
    ) -> list[dict[str, Any]]:
        source = (
            Path(profile)
            if profile is not None
            else Path(self.services.PATHS.active_profile)
        )
        differences = self.diff_against_node(port, source, board_key=board_key)
        if differences:
            keys = ", ".join(str(item["key"]) for item in differences[:8])
            remainder = (
                f" und {len(differences) - 8} weitere" if len(differences) > 8 else ""
            )
            raise self.services.FlasherError(
                "Endprüfung: Das geschriebene Profil weicht vom Node ab. "
                f"Abweichungen: {keys}{remainder}."
            )
        _emit(f"PROFILE WRITE VERIFY OK port={port} file={source.name!r} differences=0")
        return differences


def install(services: Any) -> None:
    if getattr(services, "_jarnsen_profile_contract_v2", False):
        return

    manager = ProfileContractManager(services)
    services.profile_contracts = manager
    services.ensure_profile_contract = manager.ensure
    services.check_profile_compatibility = manager.compatibility
    services.diff_profile_to_node = manager.diff_against_node
    services.verify_written_profile = manager.verify_written

    base_restore = services.restore_profile

    def restore_profile(port: str, profile=None):
        profile_path = (
            Path(profile)
            if profile is not None
            else Path(services.PATHS.active_profile)
        )
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
        "node-diff=1 post-write-verification=1 compatibility-gate=1"
    )
