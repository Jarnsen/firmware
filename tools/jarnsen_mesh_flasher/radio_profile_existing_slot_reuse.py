from __future__ import annotations

import re
from typing import Any

import radio_profile_node_sync as node_sync
import radio_profiles

_PRESENT_VALUES = {"1", "true", "yes", "present", "ready", "ok"}
_FIELD_RE = re.compile(r"\b([A-Za-z][A-Za-z0-9_]*)=([^\s]+)")


def _emit(message: str) -> None:
    try:
        import diagnostics

        diagnostics._emit(message)
    except Exception:
        pass


def _parse_info_fields(line: str) -> dict[str, str]:
    return {
        match.group(1).strip().lower(): match.group(2).strip().lower()
        for match in _FIELD_RE.finditer(str(line or ""))
    }


def _declares_complete_slots(line: str) -> bool:
    fields = _parse_info_fields(line)
    try:
        slot_count = int(fields.get("slots", "0"))
    except ValueError:
        return False
    if slot_count < len(radio_profiles.PROFILE_KEYS):
        return False
    return all(
        fields.get(profile, "") in _PRESENT_VALUES
        for profile in radio_profiles.PROFILE_KEYS
    )


def _radio_info(port: str) -> tuple[str, str]:
    line = node_sync._raw_command(
        port,
        "JARNSEN_TOOL_RADIO_INFO",
        expected=node_sync.RADIO_INFO_MARKER,
        timeout=8.0,
    )
    match = node_sync.ACTIVE_RE.search(line)
    if not match:
        raise RuntimeError(f"RADIO_SLOT_REUSE_ACTIVE_MISSING: {line}")
    return match.group(1).lower(), line


def _probe_existing_slots(
    port: str,
    active_before: str,
    services: Any,
) -> bool:
    try:
        active_initial, info_initial = _radio_info(port)
    except Exception as exc:
        _emit(
            "RADIO SLOT REUSE unavailable "
            f"port={port} stage=info type={type(exc).__name__} message={exc}"
        )
        return False

    if not _declares_complete_slots(info_initial):
        _emit(
            "RADIO SLOT REUSE unavailable "
            f"port={port} reason=incomplete-slot-declaration info={info_initial!r}"
        )
        return False

    restore_target = (
        active_before
        if active_before in radio_profiles.PROFILE_KEYS
        else active_initial
        if active_initial in radio_profiles.PROFILE_KEYS
        else radio_profiles.PROFILE_STANDARD
    )
    failures: list[str] = []
    results: list[str] = []

    for target in radio_profiles.PROFILE_KEYS:
        try:
            node_sync._select_raw(port, target, services)
            active_after, info_after = _radio_info(port)
            if active_after != target:
                raise RuntimeError(
                    "RADIO_SLOT_REUSE_READBACK_MISMATCH "
                    f"target={target} active={active_after} info={info_after}"
                )
            results.append(f"{target}=ok")
            _emit(
                "RADIO SLOT REUSE select-readback "
                f"port={port} target={target} active={active_after} status=PASS"
            )
        except Exception as exc:
            failure = f"{target}:{type(exc).__name__}:{exc}"
            failures.append(failure)
            results.append(f"{target}=fail")
            _emit(
                "RADIO SLOT REUSE select-readback "
                f"port={port} target={target} status=FAIL "
                f"type={type(exc).__name__} message={exc}"
            )
            try:
                services.wait_for_serial(port, timeout=20)
            except Exception:
                pass

    try:
        node_sync._select_raw(port, restore_target, services)
        active_restored, restore_info = _radio_info(port)
        if active_restored != restore_target:
            raise RuntimeError(
                "RADIO_SLOT_REUSE_RESTORE_READBACK_MISMATCH "
                f"target={restore_target} active={active_restored} info={restore_info}"
            )
    except Exception as exc:
        raise RuntimeError(
            "RADIO_SLOT_REUSE_RESTORE_FAILED: "
            f"port={port} target={restore_target} "
            f"type={type(exc).__name__} message={exc}. "
            "RADIO_SET wird aus Sicherheitsgruenden nicht gestartet."
        ) from exc

    if failures:
        _emit(
            "RADIO SLOT REUSE fallback-write "
            f"port={port} active-restored={restore_target} "
            f"results={','.join(results)} failures={len(failures)}"
        )
        return False

    _emit(
        "RADIO SLOT REUSE complete "
        f"port={port} results={','.join(results)} "
        f"active-restored={restore_target} radio-set=0 capture-standard=0"
    )
    return True


def install(services: Any) -> None:
    if getattr(services, "_jarnsen_existing_radio_slot_reuse", False):
        return

    base_write_slots = node_sync._write_firmware_slots

    def write_slots(
        port: str,
        settings: dict[str, Any],
        active_before: str,
        standard_region: str,
        runtime_services: Any,
    ) -> None:
        if _probe_existing_slots(port, active_before, runtime_services):
            return
        return base_write_slots(
            port,
            settings,
            active_before,
            standard_region,
            runtime_services,
        )

    def verify_persisted_radio_profiles(
        port: str,
        active_before: str | None = None,
    ) -> bool:
        current = active_before
        if current not in radio_profiles.PROFILE_KEYS:
            current, _ = _radio_info(port)
        return _probe_existing_slots(port, current, services)

    node_sync._write_firmware_slots = write_slots
    services.verify_persisted_radio_profiles = verify_persisted_radio_profiles
    services._jarnsen_existing_radio_slot_reuse = True

    _emit(
        "RADIO SLOT REUSE installed selection-readback=1 all-slots-required=1 "
        "radio-set-skipped-when-usable=1 fallback-write=1 restore-fail-closed=1"
    )
