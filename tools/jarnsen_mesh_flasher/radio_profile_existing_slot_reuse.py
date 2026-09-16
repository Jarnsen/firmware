from __future__ import annotations

import os
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


def _hil_trace(message: str) -> None:
    """Expose slot sequencing only in the exact physical GitHub HIL runtime."""

    if str(os.environ.get("GITHUB_ACTIONS") or "").strip().lower() != "true":
        return
    if not str(os.environ.get("JARNSEN_TRACKER_SERIAL") or "").strip():
        return
    print(f"TRACKER_FULL_HIL | RADIO SLOT | {message}", flush=True)


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


def _radio_info(port: str, services: Any) -> tuple[str, str]:
    """Read RADIO_INFO with one local retry for transient read-only failures."""

    for attempt in (1, 2):
        try:
            line = node_sync._raw_command(
                port,
                "JARNSEN_TOOL_RADIO_INFO",
                expected=node_sync.RADIO_INFO_MARKER,
                timeout=8.0,
            )
            break
        except (node_sync.serial.SerialTimeoutException, TimeoutError) as exc:
            if attempt >= 2:
                raise
            _emit(
                "RADIO SLOT REUSE info-retry "
                f"port={port} attempt={attempt}/2 read-only=1 "
                f"type={type(exc).__name__} message={exc}"
            )
            _hil_trace(
                f"INFO RETRY port={port} attempt={attempt}/2 "
                f"type={type(exc).__name__}"
            )
            try:
                services.wait_for_serial(port, timeout=20)
            except Exception as wait_exc:
                _emit(
                    "RADIO SLOT REUSE info-retry-wait-warning "
                    f"port={port} type={type(wait_exc).__name__} message={wait_exc}"
                )

    match = node_sync.ACTIVE_RE.search(line)
    if not match:
        raise RuntimeError(f"RADIO_SLOT_REUSE_ACTIVE_MISSING: {line}")
    return match.group(1).lower(), line


def _is_full_profile_write(services: Any, port: str) -> bool:
    # The production one-pass profile writer marks exactly the synchronous
    # configure call that owns the fresh Standard LoRa values. The packaged/HIL
    # runtime does not require transaction_flow, so this context is authoritative
    # before the optional transaction-manager fallback below.
    try:
        import profile_runtime_efficiency as profile_efficiency

        if bool(getattr(profile_efficiency._FAST_PROFILE_CONTEXT, "enabled", False)):
            return True
    except Exception:
        pass

    manager = getattr(services, "flash_transactions", None)
    if manager is None:
        return False
    try:
        record = manager.active(port)
    except Exception:
        return False
    return str(getattr(record, "kind", "") or "") == "full"


def _probe_existing_slots(
    port: str,
    active_before: str,
    services: Any,
    *,
    refresh_standard: bool = False,
) -> bool:
    try:
        active_initial, info_initial = _radio_info(port, services)
    except Exception as exc:
        _emit(
            "RADIO SLOT REUSE unavailable "
            f"port={port} stage=info type={type(exc).__name__} message={exc}"
        )
        _hil_trace(
            f"INFO FAIL port={port} type={type(exc).__name__} message={exc}"
        )
        return False

    _hil_trace(
        f"INFO INITIAL port={port} active={active_initial} "
        f"refresh-standard={int(refresh_standard)} line={info_initial!r}"
    )

    if not _declares_complete_slots(info_initial):
        _emit(
            "RADIO SLOT REUSE unavailable "
            f"port={port} reason=incomplete-slot-declaration info={info_initial!r}"
        )
        _hil_trace(f"SLOTS INCOMPLETE port={port} line={info_initial!r}")
        return False

    # A full profile write has just changed the live Standard LoRa settings.
    # Capture that fresh state before SELECT is allowed to activate the persisted
    # Standard slot; otherwise an old slot can silently restore stale values
    # such as hop_limit=3 over the newly written hop_limit=7. J1/J2 stay intact.
    if refresh_standard:
        _hil_trace(f"CAPTURE STANDARD START port={port}")
        response = node_sync._raw_command(
            port,
            "JARNSEN_TOOL_RADIO_CAPTURE_STANDARD",
            expected=node_sync.RADIO_OK_MARKER,
            timeout=8.0,
        )
        _hil_trace(f"CAPTURE STANDARD PASS port={port} response={response!r}")
        _emit(
            "RADIO SLOT REUSE standard-refresh "
            f"port={port} status=PASS response={response!r} "
            "reason=full-profile-write jarnsen1-set=0 jarnsen2-set=0"
        )
    else:
        _hil_trace(f"CAPTURE STANDARD SKIP port={port} refresh-standard=0")

    restore_target = (
        active_before
        if active_before in radio_profiles.PROFILE_KEYS
        else (
            active_initial
            if active_initial in radio_profiles.PROFILE_KEYS
            else radio_profiles.PROFILE_STANDARD
        )
    )
    failures: list[str] = []
    results: list[str] = []

    for target in radio_profiles.PROFILE_KEYS:
        try:
            _hil_trace(f"SELECT START port={port} target={target}")
            node_sync._select_raw(port, target, services)
            active_after, info_after = _radio_info(port, services)
            if active_after != target:
                raise RuntimeError(
                    "RADIO_SLOT_REUSE_READBACK_MISMATCH "
                    f"target={target} active={active_after} info={info_after}"
                )
            results.append(f"{target}=ok")
            _hil_trace(
                f"SELECT PASS port={port} target={target} active={active_after} "
                f"line={info_after!r}"
            )
            _emit(
                "RADIO SLOT REUSE select-readback "
                f"port={port} target={target} active={active_after} status=PASS"
            )
        except Exception as exc:
            failure = f"{target}:{type(exc).__name__}:{exc}"
            failures.append(failure)
            results.append(f"{target}=fail")
            _hil_trace(
                f"SELECT FAIL port={port} target={target} "
                f"type={type(exc).__name__} message={exc}"
            )
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
        _hil_trace(f"RESTORE START port={port} target={restore_target}")
        node_sync._select_raw(port, restore_target, services)
        active_restored, restore_info = _radio_info(port, services)
        if active_restored != restore_target:
            raise RuntimeError(
                "RADIO_SLOT_REUSE_RESTORE_READBACK_MISMATCH "
                f"target={restore_target} active={active_restored} info={restore_info}"
            )
        _hil_trace(
            f"RESTORE PASS port={port} target={restore_target} "
            f"active={active_restored} line={restore_info!r}"
        )
    except Exception as exc:
        _hil_trace(
            f"RESTORE FAIL port={port} target={restore_target} "
            f"type={type(exc).__name__} message={exc}"
        )
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
        _hil_trace(
            f"FALLBACK WRITE port={port} active-restored={restore_target} "
            f"results={','.join(results)} failures={len(failures)}"
        )
        return False

    _emit(
        "RADIO SLOT REUSE complete "
        f"port={port} results={','.join(results)} "
        f"active-restored={restore_target} radio-set=0 "
        f"capture-standard={int(refresh_standard)}"
    )
    _hil_trace(
        f"COMPLETE port={port} results={','.join(results)} "
        f"active-restored={restore_target} capture-standard={int(refresh_standard)}"
    )
    return True


def install(services: Any) -> None:
    if getattr(services, "_jarnsen_existing_radio_slot_reuse", False):
        return

    base_write_slots = node_sync._write_firmware_slots

    def read_active_profile(port: str, runtime_services: Any) -> str:
        # Build 186 can leave the USB CDC endpoint present but briefly unable to
        # accept the first write after a configuration-triggered reboot. Keep
        # the existing single reboot, then retry only the read-only RADIO_INFO
        # command locally. Never replay RADIO_SET/CAPTURE/SELECT here.
        node_sync._reboot_to_raw(port, runtime_services)
        active, line = _radio_info(port, runtime_services)
        _hil_trace(f"ACTIVE BEFORE port={port} active={active} line={line!r}")
        _emit(
            "RADIO SLOT REUSE active-before "
            f"port={port} active={active} info-retry-safe=1"
        )
        return active

    def write_slots(
        port: str,
        settings: dict[str, Any],
        active_before: str,
        standard_region: str,
        runtime_services: Any,
    ) -> None:
        refresh_standard = _is_full_profile_write(runtime_services, port)
        manager = getattr(runtime_services, "flash_transactions", None)
        try:
            record = manager.active(port) if manager is not None else None
        except Exception:
            record = None
        transaction_kind = str(getattr(record, "kind", "") or "none")
        try:
            import profile_runtime_efficiency as profile_efficiency

            fast_context = bool(
                getattr(profile_efficiency._FAST_PROFILE_CONTEXT, "enabled", False)
            )
        except Exception:
            fast_context = False
        _hil_trace(
            f"WRITE SLOTS ENTER port={port} active-before={active_before} "
            f"standard-region={standard_region or 'UNSET'} "
            f"refresh-standard={int(refresh_standard)} "
            f"transaction={transaction_kind} fast-context={int(fast_context)}"
        )
        if _probe_existing_slots(
            port,
            active_before,
            runtime_services,
            refresh_standard=refresh_standard,
        ):
            return
        _hil_trace(f"BASE WRITER START port={port}")
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
            current, _ = _radio_info(port, services)
        return _probe_existing_slots(port, current, services)

    node_sync._read_active_profile = read_active_profile
    node_sync._write_firmware_slots = write_slots
    services.verify_persisted_radio_profiles = verify_persisted_radio_profiles
    services._jarnsen_existing_radio_slot_reuse = True

    _emit(
        "RADIO SLOT REUSE installed selection-readback=1 all-slots-required=1 "
        "radio-set-skipped-when-usable=1 fallback-write=1 restore-fail-closed=1 "
        "radio-info-local-retry=1 destructive-command-retry=0 "
        "full-standard-refresh-before-select=1"
    )