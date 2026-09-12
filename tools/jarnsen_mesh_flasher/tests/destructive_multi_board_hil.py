from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import Any

from serial.tools import list_ports


APP_DIR = Path(__file__).resolve().parents[1]
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

REPORT_PATH = Path("ci-logs/destructive-multi-board-hil/report.json")
CONFIRM = "I_ACCEPT_DESTRUCTIVE_MULTI_BOARD_FLASH"

FUNCTION_BY_BOARD = {
    "tracker": "tak_tracker",
    "repeater": "tak_repeater",
    "tbeam_supreme": "tak",
}
NAME_BY_BOARD = {
    "tracker": ("JARNSEN HIL Tracker", "HT"),
    "repeater": ("JARNSEN HIL V3", "HV3"),
    "tbeam_supreme": ("JARNSEN HIL Supreme", "HSP"),
}


def _mapping(name: str) -> dict[str, str]:
    raw = os.environ.get(name, "").strip()
    result: dict[str, str] = {}
    for item in raw.split(","):
        key, sep, value = item.partition("=")
        if sep and key.strip() and value.strip():
            result[key.strip()] = value.strip()
    return result


def _write_report(report: dict[str, Any]) -> None:
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    temp = REPORT_PATH.with_suffix(".tmp")
    temp.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    temp.replace(REPORT_PATH)


def _usb_records() -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for item in list_ports.comports():
        port = str(getattr(item, "device", "") or "").strip()
        if not port:
            continue
        result.append(
            {
                "port": port,
                "serial": str(getattr(item, "serial_number", "") or ""),
                "vid": getattr(item, "vid", None),
                "pid": getattr(item, "pid", None),
                "location": str(getattr(item, "location", "") or ""),
                "description": str(getattr(item, "description", "") or ""),
                "hwid": str(getattr(item, "hwid", "") or ""),
            }
        )
    return result


def _usb(port: str) -> dict[str, Any]:
    wanted = str(port).strip().upper()
    for item in _usb_records():
        if str(item["port"]).strip().upper() == wanted:
            return item
    raise RuntimeError(f"{port}: USB-Port ist nicht physisch vorhanden.")


def _locate_expected_usb(
    configured_port: str,
    expected_serial: str,
    board_key: str,
    *,
    timeout: int = 30,
) -> tuple[str, dict[str, Any]]:
    """Resolve a configured HIL board by physical USB serial before any erase.

    Windows may reuse/renumber COM ports after native-USB resets. The configured
    COM number is therefore only the preferred locator; the expected USB serial
    is authoritative. A unique serial match may move to a new COM number, while
    ambiguous matches are rejected instead of guessing by VID/PID or board type.
    """
    wanted_port = str(configured_port or "").strip()
    wanted_serial = str(expected_serial or "").strip().casefold()
    if not wanted_port or not wanted_serial:
        raise RuntimeError(f"SAFETY STOP {board_key}: COM-Port oder USB-Seriennummer fehlt.")

    deadline = time.monotonic() + max(1, int(timeout))
    last_visible: list[tuple[str, str]] = []
    while time.monotonic() < deadline:
        records = _usb_records()
        last_visible = [(str(item["port"]), str(item["serial"])) for item in records]
        matches = [
            item
            for item in records
            if str(item.get("serial") or "").strip().casefold() == wanted_serial
        ]
        if len(matches) == 1:
            selected = matches[0]
            return str(selected["port"]), selected
        if len(matches) > 1:
            same_port = next(
                (
                    item
                    for item in matches
                    if str(item["port"]).strip().upper() == wanted_port.upper()
                ),
                None,
            )
            if same_port is not None:
                # Generic bridge serials (for example "0001") are safe only
                # when the explicitly configured port is still one of the exact
                # serial matches. Never pick another equal-serial bridge.
                return str(same_port["port"]), same_port
            raise RuntimeError(
                f"SAFETY STOP {board_key}: USB-Serial {expected_serial!r} ist mehrfach sichtbar "
                f"und {configured_port} ist keiner dieser Ports. Eindeutige Zuordnung unmöglich."
            )
        time.sleep(0.5)

    raise RuntimeError(
        f"SAFETY STOP {board_key}: physisches Gerät mit USB-Serial {expected_serial!r} "
        f"nicht gefunden (konfiguriert {configured_port}). Sichtbar={last_visible!r}"
    )


def _remember_physical(services: Any, port: str, board_key: str) -> None:
    remember = getattr(getattr(services, "device_sessions", None), "remember", None)
    if not callable(remember):
        raise RuntimeError(f"SAFETY STOP {board_key}: device_sessions.remember fehlt.")
    fingerprint = remember(port)
    if fingerprint is None:
        raise RuntimeError(f"SAFETY STOP {board_key}: USB-Fingerprint für {port} konnte nicht gespeichert werden.")


def _require_pinned_device(
    services: Any,
    logical_port: str,
    expected_serial: str,
    board_key: str,
    *,
    timeout: int = 45,
) -> tuple[str, dict[str, Any]]:
    """Reacquire only the already pinned physical board before destructive I/O."""
    waiter = getattr(services, "wait_for_device_reconnect", None)
    if not callable(waiter):
        raise RuntimeError(f"SAFETY STOP {board_key}: sichere Reconnect-Sperre fehlt.")
    live = str(
        waiter(logical_port, timeout=max(1, int(timeout)), expected_board=board_key) or ""
    ).strip()
    if not live:
        raise RuntimeError(f"SAFETY STOP {board_key}: kein sicherer Live-Port für {logical_port}.")
    usb = _usb(live)
    if str(usb.get("serial") or "").strip().casefold() != str(expected_serial).strip().casefold():
        raise RuntimeError(
            f"SAFETY STOP {board_key}: {live} USB-Serial={usb.get('serial')!r}, "
            f"erwartet={expected_serial!r}."
        )
    return live, usb


def _summary(info: str):
    from profile_utils import summary_from_info_text

    return summary_from_info_text(info)


def _identity_dict(identity: Any) -> dict[str, Any]:
    return {
        "is_jarnsen": bool(getattr(identity, "is_jarnsen", False)) if identity is not None else False,
        "version": str(getattr(identity, "version", "") or "") if identity is not None else "",
        "build": getattr(identity, "build", None) if identity is not None else None,
        "hardware": str(getattr(identity, "hardware", "") or "") if identity is not None else "",
        "sha": str(getattr(identity, "sha", "") or "") if identity is not None else "",
    }


def _activate_profile(services: Any, functional_profiles: Any, board_key: str) -> Path:
    profile_id = FUNCTION_BY_BOARD[board_key]
    functional_profiles.ensure_profiles(services)
    path = Path(functional_profiles.profile_path(services, profile_id))
    if not path.exists():
        raise RuntimeError(f"{board_key}: Funktionsprofil {profile_id!r} fehlt: {path}")
    services.import_profile_file(path)
    functional_profiles._save_state(services, profile_id)
    return path


def _log(board_key: str, port: str, message: str) -> None:
    print(f"[{board_key} {port}] {message}", flush=True)


def main() -> int:
    if os.environ.get("JARNSEN_DESTRUCTIVE_HIL_CONFIRM", "").strip() != CONFIRM:
        raise RuntimeError(f"Destructive HIL gesperrt; {CONFIRM} fehlt.")

    ports = _mapping("JARNSEN_DESTRUCTIVE_HIL_PORTS")
    serials = _mapping("JARNSEN_DESTRUCTIVE_HIL_SERIALS")
    if not ports:
        raise RuntimeError("JARNSEN_DESTRUCTIVE_HIL_PORTS ist leer.")
    missing_serials = sorted(set(ports).difference(serials))
    if missing_serials:
        raise RuntimeError(f"USB-Seriennummern fehlen für: {', '.join(missing_serials)}")

    import _build_version  # noqa: F401 - install exact packaged runtime stack
    import functional_profiles
    import services
    from unified_service_v2 import flash_firmware_only_bundle

    unknown = sorted(set(ports).difference(FUNCTION_BY_BOARD))
    if unknown:
        raise RuntimeError(f"Destructive HIL hat keine Funktionszuordnung für: {unknown}")

    configured_ports = dict(ports)
    report: dict[str, Any] = {
        "status": "prebinding",
        "started": time.time(),
        "configured_ports": configured_ports,
        "ports": dict(ports),
        "serials": serials,
        "initial_bindings": {},
        "devices": {},
    }
    _write_report(report)

    # Critical safety barrier: pin every physical device before the first board
    # is backed up, erased or flashed. If Supreme already disappeared after a
    # previous run, the Tracker/V3 must not be touched first and leave us with a
    # partially modified test matrix.
    try:
        for board_key in ("tbeam_supreme", "tracker", "repeater"):
            if board_key not in ports:
                continue
            live, usb = _locate_expected_usb(
                configured_ports[board_key],
                serials[board_key],
                board_key,
                timeout=30,
            )
            ports[board_key] = live
            _remember_physical(services, live, board_key)
            report["initial_bindings"][board_key] = {
                "configured_port": configured_ports[board_key],
                "live_port": live,
                "usb": usb,
            }
            report["ports"] = dict(ports)
            _write_report(report)
            print(
                f"HIL PREBIND | {board_key} configured={configured_ports[board_key]} "
                f"live={live} serial={usb['serial']}",
                flush=True,
            )
    except Exception as exc:
        report["status"] = "failed"
        report["phase"] = "initial-physical-prebind"
        report["finished"] = time.time()
        report["failures"] = [f"initial-physical-prebind: {type(exc).__name__}: {exc}"]
        _write_report(report)
        print(f"DESTRUCTIVE HIL SAFETY STOP | {type(exc).__name__}: {exc}", flush=True)
        return 1

    report["status"] = "running"
    report["phase"] = "full-cycle"
    _write_report(report)
    failures: list[str] = []

    for board_key in ("tracker", "repeater", "tbeam_supreme"):
        if board_key not in ports:
            continue
        port = ports[board_key]
        label = str(services.BOARD_PROFILES.get(board_key, {}).get("label") or board_key)
        device: dict[str, Any] = {
            "board": board_key,
            "label": label,
            "configured_port": configured_ports[board_key],
            "logical_port": port,
            "steps": ["all-devices-prebound-before-destructive-work"],
            "status": "running",
        }
        report["devices"][board_key] = device
        _write_report(report)

        try:
            live_before, usb = _require_pinned_device(
                services,
                port,
                serials[board_key],
                board_key,
            )
            device["live_port_before"] = live_before
            device["usb_before"] = usb
            device["steps"].append("physical-usb-identity-pinned-and-reacquired")

            current_info = ""
            current_detected = None
            try:
                current_info = services.verify_node(port)
                current_detected = services.detect_board_from_text(current_info)
            except Exception as exc:
                device["pre_flash_read_error"] = f"{type(exc).__name__}: {exc}"
            device["detected_before"] = current_detected
            try:
                device["identity_before"] = _identity_dict(services.query_jarnsen_identity(port))
            except Exception as exc:
                device["identity_before"] = _identity_dict(None)
                device["identity_before_error"] = f"{type(exc).__name__}: {exc}"

            recovery_from_pinned_identity = current_detected != board_key
            if recovery_from_pinned_identity:
                # This is deliberately HIL-only recovery. The board/port pair was
                # configured explicitly, destructive execution was explicitly
                # armed, and the physical USB serial was checked above. That is
                # sufficient to recover an unreadable or wrongly flashed test
                # node without weakening normal product auto-detection.
                device["steps"].append(
                    f"pinned-recovery-armed-from-detected:{current_detected or 'unknown'}"
                )

            profile = _activate_profile(services, functional_profiles, board_key)
            long_name, short_name = NAME_BY_BOARD[board_key]
            bundle = services.GitHubFirmwareClient().resolve_latest(board_key)
            device["target"] = {
                "version": str(bundle.version),
                "build": int(bundle.run_number),
                "artifact": str(bundle.artifact_name),
                "profile": profile.name,
                "long_name": long_name,
                "short_name": short_name,
            }

            preflight = services.run_flash_preflight(port, board_key, bundle, "provision")
            device["preflight"] = preflight.format()
            if not preflight.ready and not recovery_from_pinned_identity:
                raise RuntimeError(f"{board_key}: Provision-Preflight fehlgeschlagen: {preflight.format()}")
            if not preflight.ready:
                device["steps"].append("recovery-preflight-bypassed-after-usb-serial-pin")
            else:
                device["steps"].append("provision-preflight-passed")
            _write_report(report)

            live_backup, usb_backup = _require_pinned_device(
                services,
                port,
                serials[board_key],
                board_key,
            )
            device["live_port_before_backup"] = live_backup
            device["usb_before_backup"] = usb_backup
            try:
                backup = Path(services.backup_flash(port, board_key))
                if not backup.exists() or backup.stat().st_size <= 0:
                    raise RuntimeError(f"{board_key}: Sicherheitsbackup fehlt oder ist leer: {backup}")
                device["backup"] = {"name": backup.name, "bytes": backup.stat().st_size}
                device["steps"].append("full-backup-passed")
            except Exception as exc:
                if not recovery_from_pinned_identity:
                    raise
                device["backup_error"] = f"{type(exc).__name__}: {exc}"
                device["steps"].append("recovery-backup-unavailable-explicitly-authorized")
            _write_report(report)

            live_flash, usb_flash = _require_pinned_device(
                services,
                port,
                serials[board_key],
                board_key,
            )
            device["live_port_before_flash"] = live_flash
            device["usb_before_flash"] = usb_flash
            device["steps"].append("physical-usb-identity-rechecked-before-flash")

            services.flash_bundle(
                port,
                bundle,
                log=lambda message, b=board_key, p=port: _log(b, p, str(message)),
            )

            ready_port, post_flash_info, post_flash_identity = services.wait_for_node_ready(
                port,
                expected_board=board_key,
                timeout=120,
                require_jarnsen=True,
                expected_version=str(bundle.version),
                expected_build=int(bundle.run_number),
            )
            device["live_after_factory_flash"] = ready_port
            device["steps"].append("factory-erase-flash-passed")

            if services.detect_board_from_text(post_flash_info) != board_key:
                raise RuntimeError(f"{board_key}: Board nach Factory-Flash nicht korrekt erkannt.")
            identity_data = _identity_dict(post_flash_identity)
            device["identity_after_factory_flash"] = identity_data
            if identity_data["version"] != str(bundle.version):
                raise RuntimeError(
                    f"{board_key}: Version nach Factory-Flash {identity_data['version']!r} != {bundle.version!r}"
                )
            if int(identity_data["build"] or 0) != int(bundle.run_number):
                raise RuntimeError(
                    f"{board_key}: Build nach Factory-Flash {identity_data['build']!r} != {bundle.run_number!r}"
                )
            device["steps"].append("factory-firmware-readback-passed")

            prepare = getattr(services, "prepare_profile_write", None)
            if callable(prepare):
                prepare(port, long_name, short_name)
            services.restore_profile(port, profile)
            device["steps"].append("profile-role-write-passed")

            services.set_names(port, long_name, short_name)
            device["steps"].append("name-write-readback-passed")

            services.reboot_node(port)
            _live, final_info, _final_identity = services.wait_for_node_ready(
                port,
                expected_board=board_key,
                timeout=90,
                require_jarnsen=True,
                expected_version=str(bundle.version),
                expected_build=int(bundle.run_number),
            )
            services.verify_written_profile(port, profile, board_key=board_key)
            final = _summary(final_info)
            if str(final.long_name or "").strip() != long_name:
                raise RuntimeError(
                    f"{board_key}: finaler Long Name {final.long_name!r} != {long_name!r}"
                )
            if str(final.short_name or "").strip() != short_name:
                raise RuntimeError(
                    f"{board_key}: finaler Short Name {final.short_name!r} != {short_name!r}"
                )
            expected_role = str(functional_profiles.functional_profile(FUNCTION_BY_BOARD[board_key]).meshtastic_role)
            if str(final.role or "").strip().casefold() != expected_role.casefold():
                raise RuntimeError(
                    f"{board_key}: finale Rolle {final.role!r} != {expected_role!r}"
                )
            if getattr(services.flash_transactions, "active", lambda _p: None)(port) is not None:
                raise RuntimeError(f"{board_key}: Transaktion wurde nach Erfolg nicht freigegeben.")
            device["steps"].append("full-transaction-final-verify-passed")
            _write_report(report)

            # Re-test the non-destructive firmware-only path after a clean full
            # provision. It must preserve the just-written profile, role and names.
            flash_firmware_only_bundle(
                services,
                port,
                board_key,
                bundle,
                lambda message, b=board_key, p=port: _log(b, p, str(message)),
            )
            _live, update_info, update_identity_obj = services.wait_for_node_ready(
                port,
                expected_board=board_key,
                timeout=120,
                require_jarnsen=True,
                expected_version=str(bundle.version),
                expected_build=int(bundle.run_number),
            )
            update_summary = _summary(update_info)
            if str(update_summary.long_name or "").strip() != long_name:
                raise RuntimeError(f"{board_key}: Firmware-only änderte den Long Name.")
            if str(update_summary.short_name or "").strip() != short_name:
                raise RuntimeError(f"{board_key}: Firmware-only änderte den Short Name.")
            if str(update_summary.role or "").strip().casefold() != expected_role.casefold():
                raise RuntimeError(f"{board_key}: Firmware-only änderte die Rolle.")
            update_identity = _identity_dict(update_identity_obj)
            device["identity_after_update"] = update_identity
            if update_identity["version"] != str(bundle.version) or int(update_identity["build"] or 0) != int(bundle.run_number):
                raise RuntimeError(f"{board_key}: Firmware-only Readback stimmt nicht mit Zielartefakt überein.")
            device["steps"].append("firmware-only-preserves-profile-role-names")

            live_after, usb_after = _require_pinned_device(
                services,
                port,
                serials[board_key],
                board_key,
            )
            device["live_port_after"] = live_after
            device["usb_after"] = usb_after
            device["steps"].append("physical-usb-identity-stable")
            device["status"] = "passed"
        except Exception as exc:
            device["status"] = "failed"
            device["error_type"] = type(exc).__name__
            device["error"] = str(exc)
            failures.append(f"{board_key}: {type(exc).__name__}: {exc}")
        finally:
            _write_report(report)

    report["finished"] = time.time()
    report["status"] = "failed" if failures else "passed"
    report["phase"] = "complete"
    report["failures"] = failures
    _write_report(report)
    if failures:
        for failure in failures:
            print("DESTRUCTIVE HIL FAIL | " + failure, flush=True)
        return 1
    print("DESTRUCTIVE MULTI-BOARD HIL PASS", flush=True)
    return 0


def _resolve_port_name(services: Any, port: str) -> str:
    resolver = getattr(services, "resolve_live_port", None)
    if callable(resolver):
        try:
            value = str(resolver(port) or "").strip()
            if value:
                return value
        except Exception:
            pass
    return str(port)


if __name__ == "__main__":
    raise SystemExit(main())
