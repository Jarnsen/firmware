from __future__ import annotations

import time
from typing import Any

from profile_utils import summary_from_info_text


_INSTALLED = False
_CANCELLED_DEFERRED: set[str] = set()
_REPLACING_DEFERRED: set[str] = set()


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
    _emit(f"PROFILE EFFICIENCY CANCEL port={port} reason={reason!r} stale-finalizer-blocked=1")


def _combined_name_write(services: Any, port: str, long_name: str, short_name: str) -> None:
    """Write Long+Short atomically and keep the CLI alive long enough to persist them.

    Meshtastic accepts both owner arguments in one invocation. On a local serial
    target the CLI can otherwise close immediately after queuing the admin packet;
    on V3/CP210x that close can reset the node before the owner change is saved.
    """
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


def install(services: Any) -> None:
    """Remove redundant profile-only reconnect/reboot work without weakening checks."""
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True

    import radio_profile_node_sync as node_sync
    import radio_profiles
    import role_write_finalize

    manager = getattr(services, "flash_transactions", None)

    # ------------------------------------------------------------------ radio profile-only path
    # A normal profile-only write updates the Standard LoRa settings from YAML.
    # Jarnsen 1/2 are persistent firmware slots and do not need to be rebuilt on
    # every profile write. Full flash/manual slot sync retain the existing path.
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

    def write_slots(port: str, settings: dict[str, Any], active_before: str,
                    standard_region: str, runtime_services: Any) -> None:
        if not _is_profile_only(runtime_services, port):
            return base_write_slots(port, settings, active_before, standard_region, runtime_services)

        # The YAML write above already restored Standard. Preserve a previously
        # active J1/J2 selection when the service probe succeeded, but do not
        # rewrite either slot or bounce EU_868 -> US -> EU_868.
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

    # ------------------------------------------------------------------ stale deferred profile finalizer guard
    # profile_restore keeps role/power deferred until services.reboot_node(). If a
    # later stage fails (e.g. names), an unrelated Service/USB reboot must never
    # consume that stale role/power transaction.
    base_restore_profile = services.restore_profile
    base_reboot_node = services.reboot_node

    def restore_profile(port: str, profile=None):
        key = _key(port)
        _REPLACING_DEFERRED.add(key)
        try:
            result = base_restore_profile(port, profile)
        except Exception:
            _cancel_pending(services, port, "restore-failed")
            raise
        else:
            # profile_restore has now replaced any old deferred file with the
            # current operation's final role/power payload.
            _CANCELLED_DEFERRED.discard(key)
            return result
        finally:
            _REPLACING_DEFERRED.discard(key)

    def reboot_node(port: str):
        key = _key(port)
        record = _active_record(services, port)
        failed = str(getattr(record, "status", "") or "") == "failed"
        if key in _CANCELLED_DEFERRED and (failed or key in _REPLACING_DEFERRED):
            _emit(
                f"PROFILE EFFICIENCY STALE REBOOT BYPASS port={port} "
                f"transaction-status={getattr(record, 'status', None)!r} deferred-role-power=blocked"
            )
            # Physical/service reboot only. Deliberately bypass the layered
            # profile finalizer and the failed transaction bookkeeping.
            return services.meshtastic(port, "--reboot", timeout=30, check=False)
        return base_reboot_node(port)

    services.restore_profile = restore_profile
    services.reboot_node = reboot_node
    services.cancel_pending_profile_write = lambda port, reason="manual": _cancel_pending(
        services, port, str(reason)
    )

    # ------------------------------------------------------------------ names: one connection, one readback, one retry max
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

        try:
            _combined_name_write(services, port, expected_long, expected_short)
            services.wait_for_serial(port, timeout=45)
            actual_long, actual_short = _read_names_once(services, port)

            if actual_long != expected_long or actual_short != expected_short:
                _emit(
                    f"PROFILE EFFICIENCY NAME RETRY port={port} "
                    f"expected={expected_long!r}/{expected_short!r} "
                    f"actual={actual_long!r}/{actual_short!r} retry=1/1"
                )
                _combined_name_write(services, port, expected_long, expected_short)
                services.wait_for_serial(port, timeout=45)
                actual_long, actual_short = _read_names_once(services, port)

            if actual_long != expected_long or actual_short != expected_short:
                raise services.FlasherError(
                    "Namensprüfung fehlgeschlagen: "
                    f"erwartet Long={expected_long!r}, Short={expected_short!r}; "
                    f"gelesen Long={actual_long!r}, Short={actual_short!r}."
                )

            if record is not None:
                manager.stage_ok(record, "names")
            _emit(
                f"PROFILE EFFICIENCY NAME OK port={port} long={actual_long!r} "
                f"short={actual_short!r} combined=1 verified=1"
            )
        except Exception as exc:
            if record is not None:
                manager.stage_fail(record, "names", exc)
            _cancel_pending(services, port, "names-failed")
            raise

    services.set_names = set_names

    # Explicit role retry has the same local-admin close race as owner writes.
    # Keep the existing single-retry/final-readback policy, but allow the node to
    # persist the setting before the helper closes its serial connection.
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
    _emit(
        "PROFILE RUNTIME EFFICIENCY installed profile-only-radio-slot-rewrite=0 "
        "v3-extra-info-preflight=0 combined-names=1 wait-disconnect=3s name-retry-max=1 "
        "role-explicit-wait=3s stale-finalizer-guard=1 full-flash-radio-path=unchanged"
    )
