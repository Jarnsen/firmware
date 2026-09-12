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


def _usb(port: str) -> dict[str, Any]:
    wanted = str(port).strip().upper()
    for item in list_ports.comports():
        if str(getattr(item, "device", "") or "").strip().upper() != wanted:
            continue
        return {
            "port": str(item.device),
            "serial": str(getattr(item, "serial_number", "") or ""),
            "vid": getattr(item, "vid", None),
            "pid": getattr(item, "pid", None),
            "location": str(getattr(item, "location", "") or ""),
            "description": str(getattr(item, "description", "") or ""),
            "hwid": str(getattr(item, "hwid", "") or ""),
        }
    raise RuntimeError(f"{port}: USB-Port ist nicht physisch vorhanden.")


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

    report: dict[str, Any] = {
        "status": "running",
        "started": time.time(),
        "ports": ports,
        "serials": serials,
        "devices": {},
    }
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
            "logical_port": port,
            "steps": [],
            "status": "running",
        }
        report["devices"][board_key] = device
        _write_report(report)

        try:
            usb = _usb(port)
            device["usb_before"] = usb
            if usb["serial"].casefold() != serials[board_key].casefold():
                raise RuntimeError(
                    f"SAFETY STOP {board_key}: {port} USB-Serial={usb['serial']!r}, "
                    f"erwartet={serials[board_key]!r}."
                )
            remember = getattr(getattr(services, "device_sessions", None), "remember", None)
            if callable(remember):
                remember(port)
            device["steps"].append("physical-usb-identity-pinned")

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

            usb_after = _usb(_resolve_port_name(services, port))
            if usb_after["serial"].casefold() != serials[board_key].casefold():
                raise RuntimeError(
                    f"{board_key}: physische USB-Identität wechselte unerwartet auf {usb_after['serial']!r}."
                )
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
