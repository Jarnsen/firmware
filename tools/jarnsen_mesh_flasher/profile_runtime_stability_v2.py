from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Any

from profile_utils import summary_from_info_text


_INSTALLED = False
_PREFLIGHT_INFO: dict[str, tuple[float, Any]] = {}
_AUTO_REBOOT_PENDING: dict[str, str] = {}
_CHOICE_READ = threading.local()


def _emit(message: str) -> None:
    try:
        import diagnostics
        diagnostics._emit(message)
    except Exception:
        pass


def _key(port: str) -> str:
    return str(port or "").strip().upper()


def _record(services: Any, port: str) -> Any | None:
    manager = getattr(services, "flash_transactions", None)
    if manager is None:
        return None
    try:
        return manager.active(port)
    except Exception:
        return None


def _profile_callback(services: Any, fraction: float, stage: str, detail: str = "") -> None:
    callback = getattr(services, "_jarnsen_profile_progress_callback", None)
    if callable(callback):
        try:
            callback(max(0.0, min(1.0, fraction)), stage, detail)
        except Exception:
            pass


def _detach(services: Any, port: str, reason: str) -> None:
    """Remove a finished/failed live transaction but keep its JSON history on disk."""
    manager = getattr(services, "flash_transactions", None)
    if manager is None:
        return
    key = _key(port)
    try:
        active = getattr(manager, "_active", None)
        lock = getattr(manager, "_lock", None)
        if not isinstance(active, dict):
            return
        if lock is not None:
            with lock:
                old = active.pop(key, None)
        else:
            old = active.pop(key, None)
        if old is not None:
            _emit(
                f"PROFILE V2 TRANSACTION DETACH port={port} reason={reason!r} "
                f"status={getattr(old, 'status', '')!r} id={getattr(old, 'transaction_id', '')!r}"
            )
    except Exception as exc:
        _emit(f"PROFILE V2 TRANSACTION DETACH WARNING port={port} type={type(exc).__name__}:{exc}")


def _clear_pending(port: str) -> None:
    key = _key(port)
    _PREFLIGHT_INFO.pop(key, None)
    _AUTO_REBOOT_PENDING.pop(key, None)
    try:
        import profile_runtime_efficiency as efficiency
        import role_write_finalize
        import write_choice_guard
        efficiency._CURRENT_SUMMARY_BY_PORT.pop(key, None)
        efficiency._CANCELLED_DEFERRED.discard(key)
        role_write_finalize._PENDING_ROLE_BY_PORT.pop(key, None)
        write_choice_guard._ROLE_OVERRIDE_BY_PORT.pop(key, None)
    except Exception:
        pass


def _mark_auto_reboot(port: str, reason: str) -> None:
    _AUTO_REBOOT_PENDING[_key(port)] = reason
    _emit(f"PROFILE V2 AUTO REBOOT EXPECTED port={port} reason={reason!r} explicit-reboot=0")


def _settle_auto_reboot(
    services: Any,
    port: str,
    reason: str,
    *,
    wait_seconds: int = 12,
    stage: str = "Automatischer Neustart",
) -> None:
    """Wait for the reboot already scheduled by Meshtastic; never send --reboot."""
    started = time.monotonic()
    _emit(
        f"PROFILE V2 AUTO REBOOT WAIT port={port} reason={reason!r} "
        f"minimum={wait_seconds}s explicit-reboot=0"
    )
    for elapsed in range(max(1, int(wait_seconds))):
        remaining = max(0, int(wait_seconds) - elapsed)
        _profile_callback(
            services,
            min(0.98, 0.78 + 0.16 * ((elapsed + 1) / max(1, wait_seconds))),
            stage,
            f"Gerät übernimmt Änderungen · noch ca. {remaining}s",
        )
        time.sleep(1.0)
    try:
        services.wait_for_serial(port, timeout=90)
    except Exception as exc:
        _AUTO_REBOOT_PENDING.pop(_key(port), None)
        raise services.FlasherError(
            f"{port} ist nach dem automatischen Neustart nicht wieder erreichbar."
        ) from exc
    _AUTO_REBOOT_PENDING.pop(_key(port), None)
    _emit(
        f"PROFILE V2 AUTO REBOOT READY port={port} reason={reason!r} "
        f"elapsed={time.monotonic()-started:.2f}s explicit-reboot=0"
    )


def install(services: Any) -> None:
    """All-board stabilization for profile writes: visible start, one reboot, clean final state."""
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True

    import profile_runtime_efficiency as efficiency
    import radio_profile_node_sync as node_sync
    import radio_profiles
    import role_write_finalize
    import write_choice_guard

    manager = getattr(services, "flash_transactions", None)

    # 1) Reuse the mandatory role/name --info for the worker's board check.
    base_meshtastic = services.meshtastic

    def meshtastic(port: str, *args: str, **kwargs: Any):
        key = _key(port)
        is_info = tuple(str(x) for x in args) == ("--info",)
        if is_info and threading.current_thread().name == "jarnsen-profile-only":
            cached = _PREFLIGHT_INFO.pop(key, None)
            if cached is not None and time.monotonic() - cached[0] <= 45.0:
                _emit(
                    f"PROFILE V2 PREFLIGHT INFO REUSE port={port} "
                    f"age={time.monotonic()-cached[0]:.2f}s second-info=0"
                )
                return cached[1]
        result = base_meshtastic(port, *args, **kwargs)
        if is_info and bool(getattr(_CHOICE_READ, "active", False)):
            _PREFLIGHT_INFO[key] = (time.monotonic(), result)
            _emit(f"PROFILE V2 PREFLIGHT INFO CACHE port={port} source=write-choice")
        return result

    services.meshtastic = meshtastic

    base_choice_read = write_choice_guard._read_current_summary

    def choice_read(runtime_services: Any, device: Any):
        stale = _record(runtime_services, device.port)
        if stale is not None and str(getattr(stale, "status", "") or "") == "failed":
            _detach(runtime_services, device.port, "stale-before-new-write")
        _CHOICE_READ.active = True
        try:
            return base_choice_read(runtime_services, device)
        finally:
            _CHOICE_READ.active = False

    write_choice_guard._read_current_summary = choice_read

    # 2) Keep the delta export, but never leave the user staring at a frozen 15%.
    base_export = efficiency._export_current_profile

    def export_with_heartbeat(runtime_services: Any, port: str, work_dir: Path):
        stop = threading.Event()
        started = time.monotonic()
        _profile_callback(runtime_services, 0.02, "Profilvergleich", "Aktuelle Node-Konfiguration lesen")

        def heartbeat() -> None:
            tick = 0
            while not stop.wait(2.0):
                tick += 1
                _profile_callback(
                    runtime_services,
                    min(0.15, 0.03 + tick * 0.01),
                    "Profilvergleich",
                    f"Aktuelle Node-Konfiguration lesen · {int(time.monotonic()-started)}s",
                )

        threading.Thread(target=heartbeat, name="profile-v2-export-heartbeat", daemon=True).start()
        try:
            return base_export(runtime_services, port, work_dir)
        finally:
            stop.set()
            _emit(
                f"PROFILE V2 DELTA EXPORT END port={port} "
                f"elapsed={time.monotonic()-started:.2f}s visible-heartbeat=1"
            )

    efficiency._export_current_profile = export_with_heartbeat

    # 3) The JARNSEN radio preflight gets one short attempt, not four 2s retries.
    base_read_active = node_sync._read_active_profile

    def read_active_profile(port: str, runtime_services: Any) -> str:
        record = _record(runtime_services, port)
        if str(getattr(record, "kind", "") or "") != "profile_only":
            return base_read_active(port, runtime_services)
        started = time.monotonic()
        try:
            line = node_sync._raw_command(
                port,
                "JARNSEN_TOOL_RADIO_INFO",
                expected=node_sync.RADIO_INFO_MARKER,
                timeout=2.2,
            )
            match = node_sync.ACTIVE_RE.search(line)
            if not match:
                raise RuntimeError(f"Ungültige Funkprofil-Antwort: {line}")
            active = match.group(1).lower()
            _emit(
                f"PROFILE V2 RADIO PREFLIGHT port={port} active={active} "
                f"elapsed={time.monotonic()-started:.2f}s attempts=1"
            )
            return active
        except Exception as exc:
            _emit(
                f"PROFILE V2 RADIO PREFLIGHT FALLBACK port={port} active=standard "
                f"elapsed={time.monotonic()-started:.2f}s attempts=1 type={type(exc).__name__}"
            )
            return radio_profiles.PROFILE_STANDARD

    node_sync._read_active_profile = read_active_profile

    # 4) Mark every real owner write as an automatic-reboot source. Existing
    #    profile_runtime_efficiency already performs Long+Short atomically.
    base_combined_name_write = efficiency._combined_name_write

    def combined_name_write(runtime_services: Any, port: str, long_name: str, short_name: str) -> None:
        base_combined_name_write(runtime_services, port, long_name, short_name)
        _mark_auto_reboot(port, "owner-write")

    efficiency._combined_name_write = combined_name_write

    # Existing name recovery called _plain_reboot after rewriting the owner.
    # Replace only that helper: the firmware already scheduled its own reboot.
    def no_extra_reboot(runtime_services: Any, port: str) -> None:
        reason = _AUTO_REBOOT_PENDING.get(_key(port), "name-recovery")
        _settle_auto_reboot(runtime_services, port, reason, stage="Namen übernehmen")

    efficiency._plain_reboot = no_extra_reboot

    # 5) After a changed --configure transaction, let its scheduled reboot settle
    #    before opening the owner-write CLI. This converts a silent 20s connect
    #    wait into visible progress and avoids overlapping reboots.
    base_restore_profile = services.restore_profile

    def restore_profile(port: str, profile=None):
        key = _key(port)
        was_dirty = key in efficiency._PROFILE_DIRTY
        try:
            result = base_restore_profile(port, profile)
        except Exception:
            _clear_pending(port)
            _detach(services, port, "profile-restore-failed")
            raise
        record = _record(services, port)
        if (
            str(getattr(record, "kind", "") or "") == "profile_only"
            and not was_dirty
            and key in efficiency._PROFILE_DIRTY
        ):
            _mark_auto_reboot(port, "profile-config")
            _settle_auto_reboot(services, port, "profile-config", stage="Profil übernommen")
        return result

    services.restore_profile = restore_profile

    # 6) Keep set_names from the efficient layer, but cleanly detach on failure.
    base_set_names = services.set_names

    def set_names(port: str, long_name: str, short_name: str) -> None:
        try:
            return base_set_names(port, long_name, short_name)
        except Exception:
            _clear_pending(port)
            _detach(services, port, "name-write-failed")
            raise

    services.set_names = set_names

    # 7) Reboot stage: if a write already scheduled a reboot, wait for it. For
    #    profile-only with no pending reboot, the configure reboot was already
    #    settled above, so this stage is a logical no-op. Never stack --reboot.
    base_reboot_node = services.reboot_node

    def reboot_node(port: str):
        record = _record(services, port)
        kind = str(getattr(record, "kind", "") or "") if record is not None else ""
        pending = _AUTO_REBOOT_PENDING.get(_key(port))
        if record is not None and (pending or kind == "profile_only"):
            try:
                if manager is not None:
                    manager.stage_start(record, "reboot")
                if pending:
                    _settle_auto_reboot(services, port, pending)
                else:
                    _emit(
                        f"PROFILE V2 REBOOT STAGE port={port} action=noop "
                        "reason=configure-reboot-already-settled explicit-reboot=0"
                    )
                if manager is not None:
                    manager.stage_ok(record, "reboot")
                return None
            except Exception as exc:
                if manager is not None:
                    manager.stage_fail(record, "reboot", exc)
                _clear_pending(port)
                _detach(services, port, "auto-reboot-wait-failed")
                raise
        return base_reboot_node(port)

    services.reboot_node = reboot_node

    # 8) Role recovery is targeted: rewrite role once, wait for the firmware's
    #    own reboot, then rerun the authoritative final verification.
    base_verify_node = services.verify_node
    role_retry: set[str] = set()

    def verify_node(port: str, expected_board: str | None = None) -> str:
        key = _key(port)
        try:
            try:
                info = base_verify_node(port, expected_board=expected_board)
            except Exception as exc:
                record = _record(services, port)
                expected_role = str(getattr(record, "expected_role", "") or "").strip() if record else ""
                if (
                    expected_role
                    and key not in role_retry
                    and ("Rolle erwartet" in str(exc) or "Rolle konnte nicht" in str(exc))
                ):
                    role_retry.add(key)
                    _emit(
                        f"PROFILE V2 ROLE RECOVERY port={port} expected={expected_role!r} "
                        "retry=1/1 explicit-reboot=0"
                    )
                    role_write_finalize._set_role_explicit(services, port, expected_role)
                    _mark_auto_reboot(port, "role-recovery")
                    _settle_auto_reboot(services, port, "role-recovery", stage="Rolle übernehmen")
                    info = base_verify_node(port, expected_board=expected_board)
                else:
                    raise
            return info
        except Exception:
            _clear_pending(port)
            _detach(services, port, "final-verify-failed")
            raise
        finally:
            # On success base_verify_node has already marked the persisted
            # transaction complete. Detach it so NODE-LOG/firmware status cannot
            # accidentally resume an old profile transaction in the same app run.
            record = _record(services, port)
            if record is not None and str(getattr(record, "status", "") or "") == "success":
                _clear_pending(port)
                _detach(services, port, "verify-success")
            role_retry.discard(key)

    services.verify_node = verify_node
    services._jarnsen_profile_runtime_stability_v2 = True
    services._jarnsen_profile_auto_reboot_only = True
    services._jarnsen_profile_preflight_info_reuse_v2 = True
    services._jarnsen_profile_transaction_detach_v2 = True
    _emit(
        "PROFILE RUNTIME STABILITY V2 installed all-boards=1 preflight-info-reuse=1 "
        "visible-export-heartbeat=1 radio-preflight-attempts=1 firmware-auto-reboot=1 "
        "explicit-profile-reboot=0 targeted-role-recovery=1 targeted-name-recovery=1 "
        "failed-transaction-detach=1 service-stale-resume-blocked=1"
    )
