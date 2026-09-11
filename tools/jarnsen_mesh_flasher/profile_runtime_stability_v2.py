from __future__ import annotations

import threading
import time
import re
from pathlib import Path
from typing import Any

from profile_utils import summary_from_info_text


_INSTALLED = False
_PREFLIGHT_INFO: dict[str, tuple[float, Any]] = {}
_AUTO_REBOOT_PENDING: dict[str, str] = {}
_ROLE_SERVICE_REBOOT_PENDING: set[str] = set()
_CHOICE_READ = threading.local()

_JARNSEN_ROLE_BY_FUNCTION = {
    "tak": "TAK",
    "tak_tracker": "TAK_TRACKER",
    "tak_repeater": "TAK_REPEATER",
    "drone_repeater": "DRONE_REPEATER",
}


def _normalize_firmware_role(value: Any) -> str:
    """Return the canonical spelling used by the four functional roles."""
    return re.sub(r"[^A-Z0-9]+", "_", str(value or "").strip().upper()).strip("_")


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
    _ROLE_SERVICE_REBOOT_PENDING.discard(key)
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
    wait_seconds: int = 30,
    stage: str = "Automatischer Neustart",
    explicit_reboot: bool = False,
) -> None:
    """Wait for the one firmware-scheduled reboot and a stable serial return."""
    started = time.monotonic()
    observed_disconnect = False

    def port_present() -> bool:
        try:
            ports = getattr(services, "list_ports", None)
            if ports is not None:
                return any(
                    str(getattr(item, "device", "")).strip().upper() == _key(port)
                    for item in ports.comports()
                )
        except Exception:
            pass
        checker = getattr(services, "live_serial_port", None)
        if callable(checker):
            try:
                return bool(checker(port))
            except Exception:
                pass
        # Some transports do not expose presence polling.  They still receive
        # the complete quiet period before the normal reconnect waiter runs.
        return True

    _emit(
        f"PROFILE V2 AUTO REBOOT WAIT port={port} reason={reason!r} "
        f"minimum={wait_seconds}s explicit-reboot={int(explicit_reboot)}"
    )
    for elapsed in range(max(1, int(wait_seconds))):
        if not port_present():
            observed_disconnect = True
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
    # A port that never disappears (common with CP210x bridges) received the
    # full quiet period above. For native USB this also prevents the
    # first transient re-enumeration from being treated as application-ready.
    stable_started = time.monotonic()
    stable_seconds = 3
    stable_deadline = time.monotonic() + 90
    while time.monotonic() - stable_started < stable_seconds:
        if not port_present():
            observed_disconnect = True
            stable_started = time.monotonic()
        if time.monotonic() >= stable_deadline:
            _AUTO_REBOOT_PENDING.pop(_key(port), None)
            raise services.FlasherError(
                f"{port} ist nach dem automatischen Neustart nicht stabil erreichbar."
            )
        time.sleep(0.25)
    _emit(
        f"PROFILE V2 AUTO REBOOT READY port={port} reason={reason!r} "
        f"elapsed={time.monotonic()-started:.2f}s observed-disconnect={int(observed_disconnect)} "
        f"stable-present={stable_seconds}s explicit-reboot={int(explicit_reboot)}"
    )


def _sync_firmware_role(services: Any, port: str) -> None:
    """Use the persistent role service introduced after legacy Build 167."""
    record = _record(services, port)
    if str(getattr(record, "kind", "") or "") != "profile_only":
        return
    try:
        from functional_profiles import active_profile

        selected = active_profile(services)
        wanted = _JARNSEN_ROLE_BY_FUNCTION.get(str(getattr(selected, "identifier", "") or ""))
    except Exception:
        wanted = None
    if not wanted:
        return

    # Build 167 has no persistent role service and intentionally continues to
    # use config.device.role through JarnsenLegacyStatusBridge.  Build 168+
    # advertises role_api=1 and must update its authoritative role store too.
    try:
        identity = services.query_jarnsen_identity(port, timeout=2.2)
        build = int(getattr(identity, "build", 0) or 0)
    except Exception:
        build = 0
    if build < 168:
        _emit(
            f"PROFILE V2 ROLE PATH port={port} build={build or 'unknown'} "
            f"role={wanted} api=legacy-device-role"
        )
        return

    import radio_profile_node_sync as node_sync

    try:
        line = node_sync._raw_command(
            port,
            "JARNSEN_TOOL_ROLE_INFO",
            expected="===JARNSEN_ROLE===",
            timeout=3.0,
        )
        # Build 168 currently reports the active value in lower case (for
        # example ``role=tak``), while the profile catalogue uses ``TAK``.
        # Compare canonical values for every functional role so an unchanged
        # role never triggers a redundant ROLE_SET transaction.
        match = re.search(r"\brole=([A-Z0-9_-]+)\b", line, re.IGNORECASE)
        current = _normalize_firmware_role(match.group(1) if match else "")
        wanted_canonical = _normalize_firmware_role(wanted)
        if "role_api=1" not in line:
            raise RuntimeError("Firmware meldet role_api=1 nicht")
        if current == wanted_canonical and "known=1" in line and "allowed=1" in line:
            persisted = 1 if "persisted=1" in line else 0
            _emit(
                f"PROFILE V2 ROLE PATH port={port} build={build} role={wanted} "
                f"api=1 write=skip reason=already-current persisted={persisted}"
            )
            return
        result = node_sync._raw_command(
            port,
            f"JARNSEN_TOOL_ROLE_SET {wanted}",
            expected="===JARNSEN_ROLE_OK===",
            timeout=4.0,
        )
        result_match = re.search(r"\brole=([A-Z0-9_-]+)\b", result, re.IGNORECASE)
        confirmed = _normalize_firmware_role(result_match.group(1) if result_match else "")
        if confirmed != wanted_canonical or "verified=1" not in result:
            raise RuntimeError(f"Rollenbestätigung unvollständig: {result}")
        _ROLE_SERVICE_REBOOT_PENDING.add(_key(port))
        _emit(
            f"PROFILE V2 ROLE PATH port={port} build={build} role={wanted} "
            "api=1 write=ok reboot=deferred"
        )
    except Exception as exc:
        raise services.FlasherError(
            f"Die Funktionsrolle {wanted} konnte über den Firmware-Rollendienst nicht gespeichert werden."
        ) from exc


def install(services: Any) -> None:
    """All-board stabilization for profile writes: visible start, one reboot, clean final state."""
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True

    import profile_runtime_efficiency as efficiency
    import radio_profile_node_sync as node_sync
    import radio_profiles
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

    # 2) The JARNSEN radio preflight gets one short attempt, not four 2s retries.
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

    # 4) Build 168+ keeps a separate authoritative role store. Set it before the
    # complete YAML transaction; the following commit supplies the only reboot.
    # Build 167 continues to use config.device.role in the YAML.
    base_restore_profile = services.restore_profile

    def restore_profile(port: str, profile=None):
        key = _key(port)
        was_dirty = key in efficiency._PROFILE_DIRTY
        try:
            if str(getattr(_record(services, port), "kind", "") or "") == "profile_only":
                _sync_firmware_role(services, port)
            result = base_restore_profile(port, profile)
        except Exception:
            _clear_pending(port)
            _detach(services, port, "profile-restore-failed")
            raise
        record = _record(services, port)
        if str(getattr(record, "kind", "") or "") in {"profile_only", "full"}:
            if not was_dirty and key in efficiency._PROFILE_DIRTY:
                _mark_auto_reboot(port, "profile-config")
        return result

    services.restore_profile = restore_profile

    # 5) set_names is bookkeeping only; owner data was part of --configure.
    base_set_names = services.set_names

    def set_names(port: str, long_name: str, short_name: str) -> None:
        try:
            return base_set_names(port, long_name, short_name)
        except Exception:
            _clear_pending(port)
            _detach(services, port, "name-write-failed")
            raise

    services.set_names = set_names

    # 6) Wait for the single reboot scheduled by the profile commit. Never stack
    # an additional --reboot onto the normal profile-only path.
    base_reboot_node = services.reboot_node

    def reboot_node(port: str):
        record = _record(services, port)
        kind = str(getattr(record, "kind", "") or "") if record is not None else ""
        pending = _AUTO_REBOOT_PENDING.get(_key(port))
        role_service_pending = _key(port) in _ROLE_SERVICE_REBOOT_PENDING
        if record is not None and (pending or role_service_pending or kind in {"profile_only", "full"}):
            try:
                if manager is not None:
                    manager.stage_start(record, "reboot")
                if pending:
                    _settle_auto_reboot(services, port, pending)
                    _ROLE_SERVICE_REBOOT_PENDING.discard(_key(port))
                elif role_service_pending:
                    # ROLE_SET persists immediately but asks for one restart.
                    # If owner names changed, their scheduled reboot above has
                    # already covered this; only unchanged names need an explicit one.
                    services.meshtastic(port, "--reboot", timeout=35, check=False)
                    _settle_auto_reboot(
                        services,
                        port,
                        "firmware-role",
                        stage="Funktionsrolle übernehmen",
                        explicit_reboot=True,
                    )
                    _ROLE_SERVICE_REBOOT_PENDING.discard(_key(port))
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

    # 7) Verification is read-only. A mismatch is reported and never repaired
    # automatically; recovery writes caused the repeated reboot loop.
    base_verify_node = services.verify_node

    def verify_node(port: str, expected_board: str | None = None) -> str:
        try:
            return base_verify_node(port, expected_board=expected_board)
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

    services.verify_node = verify_node
    services._jarnsen_profile_runtime_stability_v2 = True
    services._jarnsen_profile_auto_reboot_only = True
    services._jarnsen_profile_preflight_info_reuse_v2 = True
    services._jarnsen_profile_transaction_detach_v2 = True
    _emit(
        "PROFILE RUNTIME STABILITY V2 installed all-boards=1 preflight-info-reuse=1 "
        "full-profile-write=1 radio-preflight-attempts=1 firmware-auto-reboot=1 "
        "explicit-profile-reboot=0 recovery-writes=0 owner-in-configure=1 "
        "failed-transaction-detach=1 service-stale-resume-blocked=1"
    )
