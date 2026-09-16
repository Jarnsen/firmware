from __future__ import annotations

import copy
import threading
import time
from pathlib import Path
from typing import Any

import yaml
from profile_utils import summary_from_info_text

_INSTALLED = False
_CANCELLED_DEFERRED: set[str] = set()
_REPLACING_DEFERRED: set[str] = set()
_CURRENT_SUMMARY_BY_PORT: dict[str, Any] = {}
_PROFILE_DIRTY: set[str] = set()
_PENDING_NAMES_BY_PORT: dict[str, tuple[str, str]] = {}
_FAST_PROFILE_CONTEXT = threading.local()


def _emit(message: str) -> None:
    try:
        import diagnostics

        diagnostics._emit(message)
    except Exception:
        pass


def _key(port: str) -> str:
    return str(port or "").strip().upper()


def _decode(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def _result_text(value: Any) -> str:
    return "\n".join(
        part
        for part in (
            _decode(getattr(value, "stdout", "")),
            _decode(getattr(value, "stderr", "")),
            _decode(getattr(value, "output", "")),
        )
        if part
    )


def _active_record(services: Any, port: str) -> Any | None:
    manager = getattr(services, "flash_transactions", None)
    if manager is None:
        return None
    try:
        return manager.active(port)
    except Exception:
        return None


def _is_profile_only(services: Any, port: str) -> bool:
    record = _active_record(services, port)
    return str(getattr(record, "kind", "") or "") == "profile_only"


def _cancel_pending(services: Any, port: str, reason: str) -> None:
    key = _key(port)
    _CANCELLED_DEFERRED.add(key)
    try:
        import role_write_finalize

        role_write_finalize._PENDING_ROLE_BY_PORT.pop(key, None)
    except Exception:
        pass
    try:
        import write_choice_guard

        write_choice_guard._ROLE_OVERRIDE_BY_PORT.pop(key, None)
    except Exception:
        pass
    _emit(
        f"PROFILE EFFICIENCY CANCEL port={port} reason={reason!r} stale-finalizer-blocked=1"
    )


def _combined_name_write(
    services: Any, port: str, long_name: str, short_name: str
) -> None:
    """Persist Long+Short in one CLI connection instead of two 20s sessions."""
    result = services.meshtastic(
        port,
        "--set-owner",
        long_name,
        "--set-owner-short",
        short_name,
        "--wait-to-disconnect",
        "3",
        timeout=75,
        check=False,
    )
    output = _result_text(result)
    returncode = int(getattr(result, "returncode", 0) or 0)
    _emit(
        f"PROFILE EFFICIENCY NAME WRITE port={port} exit={returncode} "
        f"long={long_name!r} short={short_name!r} combined=1 wait_disconnect=3s "
        f"output_chars={len(output)}"
    )
    if returncode != 0:
        raise services.FlasherError(
            "Long-/Short-Name konnten nicht gemeinsam geschrieben werden.\n\n"
            + (output[-1800:] if output else f"Exit {returncode}")
        )


def _read_names_once(services: Any, port: str) -> tuple[str, str]:
    output = ""
    try:
        result = services.meshtastic(port, "--info", timeout=35, check=False)
        output = _result_text(result)
    except Exception as exc:
        output = _result_text(exc)
        if not output:
            raise
    summary = summary_from_info_text(output)
    long_name = str(summary.long_name or "").strip()
    short_name = str(summary.short_name or "").strip()
    _emit(
        f"PROFILE EFFICIENCY NAME READ port={port} long={long_name!r} "
        f"short={short_name!r} chars={len(output)}"
    )
    return long_name, short_name


def _norm_key(value: Any) -> str:
    return str(value or "").replace("_", "").replace("-", "").casefold()


def _matching_key(mapping: dict[str, Any], wanted: str) -> str | None:
    wanted_key = _norm_key(wanted)
    for key in mapping:
        if _norm_key(key) == wanted_key:
            return str(key)
    return None


def _values_equal(left: Any, right: Any) -> bool:
    if isinstance(left, bool) or isinstance(right, bool):
        return left is right
    if isinstance(left, (int, float)) and isinstance(right, (int, float)):
        try:
            return abs(float(left) - float(right)) < 0.000001
        except Exception:
            pass
    if isinstance(left, str) and isinstance(right, str):
        return left.strip() == right.strip()
    return left == right


_NO_CHANGE = object()


def _delta_value(wanted: Any, current: Any) -> Any:
    """Return only target-owned values that differ from the node export."""
    if isinstance(wanted, dict):
        if not isinstance(current, dict):
            return copy.deepcopy(wanted)
        delta: dict[str, Any] = {}
        for key, value in wanted.items():
            actual_key = _matching_key(current, str(key))
            if actual_key is None:
                delta[str(key)] = copy.deepcopy(value)
                continue
            child = _delta_value(value, current[actual_key])
            if child is not _NO_CHANGE:
                delta[str(key)] = child
        return delta if delta else _NO_CHANGE

    if isinstance(wanted, list):
        return _NO_CHANGE if _values_equal(wanted, current) else copy.deepcopy(wanted)

    return _NO_CHANGE if _values_equal(wanted, current) else copy.deepcopy(wanted)


def _merge_mapping(target: dict[str, Any], extra: dict[str, Any]) -> dict[str, Any]:
    for key, value in extra.items():
        existing_key = _matching_key(target, str(key))
        use_key = existing_key if existing_key is not None else str(key)
        if isinstance(value, dict) and isinstance(target.get(use_key), dict):
            _merge_mapping(target[use_key], value)
        else:
            target[use_key] = copy.deepcopy(value)
    return target


def _set_profile_role(data: dict[str, Any], role: str) -> None:
    role = str(role or "").strip()
    if not role:
        return
    root = data.get("config") if isinstance(data.get("config"), dict) else data
    device = root.get("device")
    if not isinstance(device, dict):
        device = {}
        root["device"] = device
    role_key = _matching_key(device, "role") or "role"
    device[role_key] = role


def _profile_role(data: dict[str, Any]) -> str:
    root = data.get("config") if isinstance(data.get("config"), dict) else data
    device = root.get("device") if isinstance(root, dict) else None
    if not isinstance(device, dict):
        return ""
    key = _matching_key(device, "role")
    return str(device.get(key) or "").strip() if key else ""


def _profile_power_saving(data: dict[str, Any]) -> bool | None:
    root = data.get("config") if isinstance(data.get("config"), dict) else data
    power = root.get("power") if isinstance(root, dict) else None
    if not isinstance(power, dict):
        return None
    key = _matching_key(power, "is_power_saving")
    if not key:
        return None
    value = power.get(key)
    if isinstance(value, bool):
        return value
    text = str(value or "").strip().lower()
    if text in {"true", "1", "yes", "on"}:
        return True
    if text in {"false", "0", "no", "off"}:
        return False
    return None


def _complete_profile_payload(
    source: dict[str, Any],
    *,
    role: str = "",
    long_name: str = "",
    short_name: str = "",
) -> dict[str, Any]:
    """Build the single authoritative payload without mutating the saved profile."""
    payload = copy.deepcopy(source)
    if str(role or "").strip():
        _set_profile_role(payload, str(role).strip())
    if str(long_name or "").strip() and str(short_name or "").strip():
        payload["owner"] = str(long_name).strip()
        payload["owner_short"] = str(short_name).strip()
    return payload


def _ensure_lora_region(delta: dict[str, Any], wanted: dict[str, Any]) -> None:
    """Keep region in the small YAML so the radio wrapper never exports it again."""
    wanted_root = (
        wanted.get("config") if isinstance(wanted.get("config"), dict) else wanted
    )
    if not isinstance(wanted_root, dict):
        return
    wanted_lora = wanted_root.get("lora")
    if not isinstance(wanted_lora, dict):
        return
    region_key = _matching_key(wanted_lora, "region")
    if not region_key:
        return
    region = wanted_lora.get(region_key)
    if region in (None, ""):
        return

    if isinstance(wanted.get("config"), dict):
        root = delta.setdefault("config", {})
    else:
        root = delta
    if not isinstance(root, dict):
        return
    lora = root.setdefault("lora", {})
    if isinstance(lora, dict):
        lora[_matching_key(lora, "region") or "region"] = copy.deepcopy(region)


def _load_yaml(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8", errors="replace")) or {}
    if not isinstance(data, dict):
        raise ValueError("YAML-Wurzel ist kein Mapping")
    return data


def _export_current_profile(services: Any, port: str, work_dir: Path) -> dict[str, Any]:
    target = work_dir / f"{_key(port).replace(':', '-')}-{time.time_ns()}-current.yaml"
    try:
        result = services.meshtastic(
            port,
            "--export-config",
            str(target),
            timeout=90,
            check=False,
        )
        output = _result_text(result)
        returncode = int(getattr(result, "returncode", 0) or 0)
        if returncode != 0 or not target.exists():
            raise services.FlasherError(
                "Aktuelle Node-Konfiguration konnte für den Delta-Vergleich nicht gelesen werden.\n\n"
                + (output[-1400:] if output else f"Exit {returncode}")
            )
        data = _load_yaml(target)
        _emit(
            f"PROFILE DELTA EXPORT port={port} keys={len(data)} bytes={target.stat().st_size} "
            "single-read=1"
        )
        return data
    finally:
        try:
            target.unlink(missing_ok=True)
        except Exception:
            pass


def _write_delta_profile(work_dir: Path, port: str, delta: dict[str, Any]) -> Path:
    path = work_dir / f"{_key(port).replace(':', '-')}-{time.time_ns()}-delta.yaml"
    path.write_text(
        yaml.safe_dump(delta, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )
    return path


def _plain_reboot(services: Any, port: str) -> None:
    result = services.meshtastic(port, "--reboot", timeout=35, check=False)
    output = _result_text(result)
    returncode = int(getattr(result, "returncode", 0) or 0)
    if (
        returncode != 0
        and "reboot" not in output.casefold()
        and "disconnect" not in output.casefold()
    ):
        raise services.FlasherError(
            output[-1400:] if output else f"Neustart fehlgeschlagen (Exit {returncode})"
        )


def install(services: Any) -> None:
    """Write one complete profile transaction for every profile-writing operation."""
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True

    import profile_restore as restore_core
    import radio_profile_node_sync as node_sync
    import radio_profiles
    import role_write_finalize
    import write_choice_guard

    manager = getattr(services, "flash_transactions", None)
    work_dir = Path(services.PATHS.root) / "restore-work"
    work_dir.mkdir(parents=True, exist_ok=True)

    # Cache the one fresh role/name read that the mandatory choice dialog already
    # performs. This lets the later writer skip an owner write when the selected
    # names are already present on the node.
    base_choice_read = write_choice_guard._read_current_summary

    def choice_read(runtime_services: Any, device: Any):
        summary = base_choice_read(runtime_services, device)
        _CURRENT_SUMMARY_BY_PORT[_key(device.port)] = summary
        return summary

    write_choice_guard._read_current_summary = choice_read

    # profile_restore historically writes role/power in a second configure pass.
    # A complete profile write commits every field, including role/power/owner,
    # in the same firmware settings transaction.
    base_split_profile_data = restore_core.split_profile_data

    def split_profile_data(data: dict[str, Any]):
        safe, final, removed_identity = base_split_profile_data(data)
        if bool(getattr(_FAST_PROFILE_CONTEXT, "enabled", False)) and final:
            _merge_mapping(safe, final)
            _emit(
                "PROFILE FULL FINAL MERGE role-power-in-same-transaction=1 "
                f"final-keys={len(final)}"
            )
            return safe, {}, removed_identity
        return safe, final, removed_identity

    restore_core.split_profile_data = split_profile_data

    # ------------------------------------------------------------------ radio profile-only path
    # The normal YAML restores the Standard LoRa config. J1/J2 live in persistent
    # firmware slots and must not be rebuilt on every ordinary profile write.
    base_read_active = node_sync._read_active_profile
    base_write_slots = node_sync._write_firmware_slots

    def read_active_profile(port: str, runtime_services: Any) -> str:
        if not _is_profile_only(runtime_services, port):
            return base_read_active(port, runtime_services)

        started = time.monotonic()
        try:
            runtime_services.wait_for_serial(port, timeout=15)
            line = node_sync._raw_command(
                port,
                "JARNSEN_TOOL_RADIO_INFO",
                expected=node_sync.RADIO_INFO_MARKER,
                timeout=6.5,
            )
            match = node_sync.ACTIVE_RE.search(line)
            if not match:
                raise RuntimeError(f"Ungültige Funkprofil-Antwort: {line}")
            active = match.group(1).lower()
            _emit(
                f"PROFILE EFFICIENCY RADIO PREFLIGHT port={port} active={active} "
                f"elapsed={time.monotonic()-started:.2f}s profile-only=1 extra-info=0 extra-reboot=0"
            )
            return active
        except Exception as exc:
            _emit(
                f"PROFILE EFFICIENCY RADIO PREFLIGHT FALLBACK port={port} active=standard "
                f"elapsed={time.monotonic()-started:.2f}s type={type(exc).__name__} "
                "profile-only=1 extra-info=0 extra-reboot=0"
            )
            return radio_profiles.PROFILE_STANDARD

    def write_slots(
        port: str,
        settings: dict[str, Any],
        active_before: str,
        standard_region: str,
        runtime_services: Any,
    ) -> None:
        if not _is_profile_only(runtime_services, port):
            return base_write_slots(
                port, settings, active_before, standard_region, runtime_services
            )

        if active_before in {
            radio_profiles.PROFILE_JARNSEN_1,
            radio_profiles.PROFILE_JARNSEN_2,
        }:
            try:
                node_sync._select_raw(port, active_before, runtime_services)
                _emit(
                    f"PROFILE EFFICIENCY RADIO ACTIVE RESTORED port={port} active={active_before} "
                    "slot-rewrite=0"
                )
            except Exception as exc:
                _emit(
                    f"PROFILE EFFICIENCY RADIO ACTIVE WARNING port={port} active={active_before} "
                    f"type={type(exc).__name__} slot-rewrite=0"
                )
        _emit(
            f"PROFILE EFFICIENCY RADIO SLOTS SKIP port={port} profile-only=1 "
            f"active-before={active_before} standard-region={standard_region or 'unknown'} "
            "jarnsen1-rewrite=0 jarnsen2-rewrite=0 region-bounce=0"
        )

    node_sync._read_active_profile = read_active_profile
    node_sync._write_firmware_slots = write_slots

    # ------------------------------------------------------------------ complete single-pass profile path
    base_restore_profile = services.restore_profile
    base_reboot_node = services.reboot_node
    base_verify_node = services.verify_node

    def restore_profile(port: str, profile=None):
        key = _key(port)
        record = _active_record(services, port)
        # Full flash already has an active transaction from backup/firmware. No
        # active record here means this call is the reference-dashboard profile-only path.
        if record is None and manager is not None:
            record = manager.ensure(port, "profile_only")

        source = (
            Path(profile)
            if profile is not None
            else Path(services.PATHS.active_profile)
        )
        if not source.exists():
            raise services.FlasherError(
                "Kein aktives Grundeinstellungs-Profil vorhanden."
            )

        source_data = _load_yaml(source)
        override_role = str(
            write_choice_guard._ROLE_OVERRIDE_BY_PORT.get(key, "") or ""
        ).strip()
        selected_role = override_role or _profile_role(source_data)

        pending_names = _PENDING_NAMES_BY_PORT.pop(key, ("", ""))
        expected_long = str(pending_names[0] or "").strip()
        expected_short = str(pending_names[1] or "").strip()
        wanted = _complete_profile_payload(
            source_data,
            role=selected_role,
            long_name=expected_long,
            short_name=expected_short,
        )

        cached = _CURRENT_SUMMARY_BY_PORT.get(key)
        # If the operator explicitly chose the already active role, suppress the
        # old override wrapper: there is nothing to write and no role retry is needed.
        if (
            str(getattr(record, "kind", "") or "") == "profile_only"
            and override_role
            and cached is not None
        ):
            current_role = str(getattr(cached, "role", "") or "").strip()
            if current_role.casefold() == override_role.casefold():
                write_choice_guard._ROLE_OVERRIDE_BY_PORT.pop(key, None)
                role_write_finalize._PENDING_ROLE_BY_PORT.pop(key, None)
                _emit(
                    f"PROFILE DELTA ROLE SKIP port={port} role={override_role!r} "
                    "reason=selected-role-already-active"
                )

        if record is not None:
            record.expected_profile = str(source)
            record.expected_role = selected_role
            record.expected_long_name = expected_long
            record.expected_short_name = expected_short
            try:
                manager._save(record)
            except Exception:
                pass

        full_path: Path | None = None
        try:
            total_target = len(restore_core._planned_leaf_paths(wanted))
            _emit(
                f"PROFILE FULL PLAN port={port} target={total_target} one-configure=1 "
                f"owner-in-transaction={int(bool(expected_long and expected_short))} delta-export=0"
            )
            callback = getattr(services, "_jarnsen_profile_progress_callback", None)
            if callable(callback):
                try:
                    callback(
                        0.04,
                        "Profil vorbereiten",
                        f"{total_target} Profilwerte vollständig",
                    )
                except Exception:
                    pass
            full_path = work_dir / f"{key.replace(':', '-')}-{time.time_ns()}-full.yaml"
            full_path.write_text(
                yaml.safe_dump(wanted, allow_unicode=True, sort_keys=False),
                encoding="utf-8",
            )
            _FAST_PROFILE_CONTEXT.enabled = True
            result = base_restore_profile(port, full_path)
            _PROFILE_DIRTY.add(key)
            _CANCELLED_DEFERRED.discard(key)
            if record is not None:
                # Nested transaction_flow sees the temporary complete file. Restore
                # the real profile/role so the final post-reboot check remains authoritative.
                record.expected_profile = str(source)
                record.expected_role = selected_role
                try:
                    manager._save(record)
                except Exception:
                    pass
            return result
        except Exception:
            _cancel_pending(services, port, "full-restore-failed")
            raise
        finally:
            _FAST_PROFILE_CONTEXT.enabled = False
            if full_path is not None:
                try:
                    full_path.unlink(missing_ok=True)
                except Exception:
                    pass

    # ------------------------------------------------------------------ names were already part of the one configure transaction
    def set_names(port: str, long_name: str, short_name: str) -> None:
        expected_long = str(long_name or "").strip()
        expected_short = str(short_name or "").strip()
        if not expected_long:
            raise services.FlasherError("Long Name fehlt.")
        if not (1 <= len(expected_short) <= 4):
            raise services.FlasherError("Short Name muss 1 bis 4 Zeichen lang sein.")

        record = manager.active(port) if manager is not None else None
        if record is None and manager is not None:
            record = manager.ensure(port, "profile_only")
        if record is not None:
            record.expected_long_name = expected_long
            record.expected_short_name = expected_short
            manager.stage_start(record, "names")

        if record is not None:
            manager.stage_ok(record, "names")
        _emit(
            f"PROFILE FULL NAME INCLUDED port={port} long={expected_long!r} short={expected_short!r} "
            "separate-owner-write=0"
        )

    # ------------------------------------------------------------------ one final reboot / existing role recovery
    def reboot_node(port: str):
        key = _key(port)
        record = _active_record(services, port)
        failed = str(getattr(record, "status", "") or "") == "failed"
        if key in _CANCELLED_DEFERRED and (failed or key in _REPLACING_DEFERRED):
            _emit(
                f"PROFILE EFFICIENCY STALE REBOOT BYPASS port={port} "
                f"transaction-status={getattr(record, 'status', None)!r} deferred-role-power=blocked"
            )
            return services.meshtastic(port, "--reboot", timeout=30, check=False)
        return base_reboot_node(port)

    def verify_node(port: str, expected_board: str | None = None) -> str:
        key = _key(port)
        info = base_verify_node(port, expected_board=expected_board)

        # Power-Saving was intentionally merged into the one profile transaction;
        # transaction_flow already verifies board/role/names. Check power here too.
        record = _active_record(services, port)
        if (
            record is not None
            and str(getattr(record, "kind", "") or "") == "profile_only"
        ):
            try:
                source = Path(str(getattr(record, "expected_profile", "") or ""))
                wanted_power = (
                    _profile_power_saving(_load_yaml(source))
                    if source.exists()
                    else None
                )
            except Exception:
                wanted_power = None
            if wanted_power is not None:
                import re

                match = re.search(
                    r'"isPowerSaving"\s*:\s*(true|false)', info or "", re.IGNORECASE
                )
                if not match:
                    match = re.search(
                        r'"is_power_saving"\s*:\s*(true|false)',
                        info or "",
                        re.IGNORECASE,
                    )
                actual_power = match.group(1).lower() == "true" if match else None
                if actual_power is not wanted_power:
                    raise services.FlasherError(
                        "Endprüfung: Power-Saving nicht korrekt übernommen. "
                        f"Erwartet {wanted_power}, gelesen {actual_power}."
                    )
        _PROFILE_DIRTY.discard(key)
        _CURRENT_SUMMARY_BY_PORT.pop(key, None)
        return info

    services.restore_profile = restore_profile
    services.set_names = set_names
    services.reboot_node = reboot_node
    services.verify_node = verify_node

    def prepare_profile_write(port: str, long_name: str, short_name: str) -> None:
        if manager is not None and manager.active(port) is None:
            manager.ensure(port, "profile_only")
        _PENDING_NAMES_BY_PORT[_key(port)] = (
            str(long_name or "").strip(),
            str(short_name or "").strip(),
        )
        _emit(
            f"PROFILE FULL PREPARE port={port} owner={bool(long_name)} "
            "complete-profile=1 delta-export=0 max-reboots=1"
        )

    services.prepare_profile_write = prepare_profile_write
    services.cancel_pending_profile_write = (
        lambda port, reason="manual": _cancel_pending(services, port, str(reason))
    )

    # Explicit role recovery stays available for the rare case where the one
    # settings transaction did not persist the selected role.
    def set_role_explicit(runtime_services: Any, port: str, role: str) -> None:
        result = runtime_services.meshtastic(
            port,
            "--set",
            "device.role",
            role,
            "--wait-to-disconnect",
            "3",
            timeout=70,
            check=False,
        )
        output = _result_text(result)
        returncode = int(getattr(result, "returncode", 0) or 0)
        transient = role_write_finalize._transient_disconnect_text(output)
        _emit(
            f"PROFILE EFFICIENCY ROLE SET port={port} role={role!r} exit={returncode} "
            f"wait_disconnect=3s transient={int(transient)}"
        )
        if returncode != 0 and not transient:
            raise runtime_services.FlasherError(
                "Rolle konnte nicht explizit geschrieben werden.\n\n"
                + (output[-1800:] if output else f"Exit {returncode}")
            )

    role_write_finalize._set_role_explicit = set_role_explicit

    services._jarnsen_profile_runtime_efficiency = True
    services._jarnsen_profile_delta_write = False
    services._jarnsen_profile_full_write = True
    _emit(
        "PROFILE RUNTIME EFFICIENCY installed delta-export=0 complete-profile=1 "
        "profile-only-radio-slot-rewrite=0 role-power-owner-one-configure=1 "
        "immediate-name-readback=0 final-name-readback=1 recovery-writes=0 "
        "role-explicit-wait=3s stale-finalizer-guard=1 full-flash-radio-path=unchanged"
    )
