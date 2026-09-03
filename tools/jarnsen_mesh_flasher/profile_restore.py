from __future__ import annotations

import copy
import re
import subprocess
import time
from pathlib import Path
from typing import Any


def _emit(message: str) -> None:
    try:
        import diagnostics

        diagnostics._emit(message)
    except Exception:
        pass


def _decode(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def _pop_case_insensitive(mapping: dict[str, Any], wanted: str) -> Any:
    wanted_norm = wanted.replace("_", "").replace("-", "").lower()
    for key in list(mapping):
        norm = str(key).replace("_", "").replace("-", "").lower()
        if norm == wanted_norm:
            return mapping.pop(key)
    return None


def _remove_device_identity(mapping: dict[str, Any]) -> list[str]:
    removed: list[str] = []
    for root_name in ("config", None):
        root = mapping.get(root_name) if root_name else mapping
        if not isinstance(root, dict):
            continue
        security = root.get("security")
        if not isinstance(security, dict):
            continue
        for key in list(security):
            norm = str(key).replace("_", "").replace("-", "").lower()
            if norm in {"privatekey", "publickey"}:
                security.pop(key, None)
                removed.append(f"{root_name + '.' if root_name else ''}security.{key}")
    return removed


def _remove_owner_fields(mapping: dict[str, Any]) -> None:
    # The app writes the requested Long/Short Name explicitly after the safe
    # profile stage. Avoid changing names twice while the node is being restored.
    for key in list(mapping):
        norm = str(key).replace("_", "").replace("-", "").lower()
        if norm in {"owner", "ownershort", "longname", "shortname"}:
            mapping.pop(key, None)


def split_profile_data(data: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any], list[str]]:
    """Split an exported Meshtastic profile into safe and final activation stages.

    Stage 1 contains channels and ordinary configuration while keeping the node
    awake over USB. Stage 2 contains only the role and the power-saving enable
    flag because those settings can make a tracker/repeater reboot or sleep.
    Device-unique public/private crypto identity is deliberately not cloned.
    """
    safe = copy.deepcopy(data)
    final: dict[str, Any] = {}
    removed_identity = _remove_device_identity(safe)
    _remove_owner_fields(safe)

    def split_root(root_key: str | None) -> None:
        safe_root = safe.get(root_key) if root_key else safe
        if not isinstance(safe_root, dict):
            return

        final_root: dict[str, Any] = {}

        device = safe_root.get("device")
        if isinstance(device, dict):
            role = _pop_case_insensitive(device, "role")
            if role is not None:
                final_root.setdefault("device", {})["role"] = role
            if not device:
                safe_root.pop("device", None)

        power = safe_root.get("power")
        if isinstance(power, dict):
            for key in list(power):
                norm = str(key).replace("_", "").replace("-", "").lower()
                if norm == "ispowersaving":
                    final_root.setdefault("power", {})[key] = power.pop(key)
            if not power:
                safe_root.pop("power", None)

        if final_root:
            if root_key:
                final[root_key] = final_root
            else:
                final.update(final_root)

    split_root("config")
    # Older/hand-written profiles may place device/power directly at the root.
    split_root(None)

    # Avoid empty config containers after moving role/power to the final stage.
    if isinstance(safe.get("config"), dict) and not safe["config"]:
        safe.pop("config", None)

    return safe, final, removed_identity


def _write_yaml(path: Path, data: dict[str, Any]) -> None:
    import yaml

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(data, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )


def _final_expectations(final: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    roots: list[dict[str, Any]] = []
    config = final.get("config")
    if isinstance(config, dict):
        roots.append(config)
    roots.append(final)

    for root in roots:
        device = root.get("device")
        if isinstance(device, dict) and "role" in device and "role" not in result:
            result["role"] = device.get("role")
        power = root.get("power")
        if isinstance(power, dict) and "power_saving" not in result:
            for key, value in power.items():
                norm = str(key).replace("_", "").replace("-", "").lower()
                if norm == "ispowersaving":
                    result["power_saving"] = value
                    break
    return result


def _as_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    text = str(value or "").strip().lower()
    if text in {"true", "1", "yes", "on"}:
        return True
    if text in {"false", "0", "no", "off"}:
        return False
    return None


def _local_role(info: str) -> str:
    metadata = re.search(r'(?im)^Metadata:\s*\{[^\n]*?"role"\s*:\s*"([^"]+)"', info or "")
    if metadata:
        return metadata.group(1).strip()
    prefs = re.search(
        r'(?is)Preferences:\s*\{.*?"device"\s*:\s*\{.*?"role"\s*:\s*"([^"]+)"',
        info or "",
    )
    return prefs.group(1).strip() if prefs else ""


def _local_power_saving(info: str) -> bool | None:
    match = re.search(r'"isPowerSaving"\s*:\s*(true|false)', info or "", re.IGNORECASE)
    if not match:
        match = re.search(r'"is_power_saving"\s*:\s*(true|false)', info or "", re.IGNORECASE)
    if not match:
        return None
    return match.group(1).lower() == "true"


def install(services: Any) -> None:
    base_restore_profile = services.restore_profile
    base_reboot_node = services.reboot_node
    base_verify_node = services.verify_node
    pending_final: dict[str, Path] = {}
    expected_final: dict[str, dict[str, Any]] = {}
    work_dir = services.PATHS.root / "restore-work"
    work_dir.mkdir(parents=True, exist_ok=True)

    def restore_profile(port: str, profile: Path | None = None) -> None:
        source = Path(profile or services.PATHS.active_profile)
        if not source.exists():
            raise services.FlasherError("Kein aktives Grundeinstellungs-Profil vorhanden.")

        try:
            import yaml

            raw = yaml.safe_load(source.read_text(encoding="utf-8", errors="replace")) or {}
        except Exception as exc:
            raise services.FlasherError(f"Profil konnte nicht als YAML gelesen werden: {exc}") from exc

        if not isinstance(raw, dict):
            raise services.FlasherError("Profil hat kein gültiges YAML-Objekt als Wurzel.")

        safe, final, removed_identity = split_profile_data(raw)
        stamp = str(int(time.time() * 1000))
        safe_path = work_dir / f"{port}-{stamp}-safe.yaml"
        final_path = work_dir / f"{port}-{stamp}-final.yaml"

        _write_yaml(safe_path, safe)
        if final:
            _write_yaml(final_path, final)

        _emit(
            f"PROFILE RESTORE SPLIT port={port} source={source.name!r} "
            f"safe={safe_path.name!r} final_present={bool(final)} "
            f"identity_fields_removed={removed_identity!r}"
        )

        try:
            if safe:
                _emit(f"PROFILE RESTORE SAFE START port={port} timeout=300s")
                services.meshtastic(port, "--configure", str(safe_path), timeout=300)
                _emit(f"PROFILE RESTORE SAFE OK port={port}")
            else:
                _emit(f"PROFILE RESTORE SAFE SKIP port={port} reason=empty")
        except subprocess.TimeoutExpired as exc:
            out = "\n".join(filter(None, (_decode(exc.stdout), _decode(exc.stderr))))
            _emit(f"PROFILE RESTORE SAFE TIMEOUT port={port} output_chars={len(out)}")
            raise services.FlasherError(
                "Grundeinstellungen konnten nicht vollständig übertragen werden: "
                "der USB-Konfigurationsschritt hat das Zeitlimit erreicht."
            ) from exc
        finally:
            try:
                safe_path.unlink(missing_ok=True)
            except Exception:
                pass

        key = port.upper()
        old = pending_final.pop(key, None)
        if old:
            try:
                old.unlink(missing_ok=True)
            except Exception:
                pass
        expected_final.pop(key, None)
        if final:
            pending_final[key] = final_path
            expected_final[key] = _final_expectations(final)
            _emit(
                f"PROFILE RESTORE FINAL DEFERRED port={port} file={final_path.name!r} "
                f"expect={expected_final[key]!r}"
            )
        else:
            try:
                final_path.unlink(missing_ok=True)
            except Exception:
                pass

    def reboot_node(port: str) -> None:
        key = port.upper()
        final_path = pending_final.pop(key, None)
        if final_path is None:
            return base_reboot_node(port)

        timed_out = False
        try:
            _emit(f"PROFILE RESTORE FINAL START port={port} timeout=45s")
            services.meshtastic(port, "--configure", str(final_path), timeout=45)
            _emit(f"PROFILE RESTORE FINAL OK port={port}")
        except subprocess.TimeoutExpired as exc:
            # Applying role / isPowerSaving is intentionally the last write. A
            # reboot or sleep transition may remove USB before the CLI exits.
            # The normal app flow immediately waits for serial and performs a
            # full board/config verification afterwards, so this is not itself
            # a failure.
            timed_out = True
            out = "\n".join(filter(None, (_decode(exc.stdout), _decode(exc.stderr))))
            _emit(
                f"PROFILE RESTORE FINAL EXPECTED DISCONNECT port={port} "
                f"output_chars={len(out)}"
            )
        finally:
            try:
                final_path.unlink(missing_ok=True)
            except Exception:
                pass

        if not timed_out:
            # A clean configure return does not guarantee a reboot on every CLI
            # release, therefore issue the normal reboot command as well.
            base_reboot_node(port)

    def verify_node(port: str, expected_board: str | None = None) -> str:
        info = base_verify_node(port, expected_board=expected_board)
        key = port.upper()
        expected = expected_final.get(key)
        if not expected:
            return info

        wanted_role = expected.get("role")
        if isinstance(wanted_role, str) and wanted_role.strip():
            actual_role = _local_role(info)
            if actual_role.upper() != wanted_role.strip().upper():
                raise services.FlasherError(
                    f"Endprüfung: Rolle nicht übernommen. Erwartet {wanted_role}, "
                    f"gelesen {actual_role or 'unbekannt'}."
                )

        if "power_saving" in expected:
            wanted_power = _as_bool(expected.get("power_saving"))
            actual_power = _local_power_saving(info)
            if wanted_power is not None and actual_power is not wanted_power:
                raise services.FlasherError(
                    "Endprüfung: Power-Saving nicht korrekt übernommen. "
                    f"Erwartet {wanted_power}, gelesen {actual_power}."
                )

        _emit(
            f"PROFILE RESTORE FINAL VERIFY OK port={port} expected={expected!r} "
            f"role={_local_role(info)!r} power_saving={_local_power_saving(info)!r}"
        )
        expected_final.pop(key, None)
        return info

    services.restore_profile = restore_profile
    services.reboot_node = reboot_node
    services.verify_node = verify_node

    _emit(
        "PROFILE RESTORE installed staged=1 safe-first=1 role-power-last=1 "
        "device-identity-clone=0 final-timeout-verified-later=1 final-role-power-verify=1"
    )
