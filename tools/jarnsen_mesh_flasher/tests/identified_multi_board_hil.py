from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import Any

APP_DIR = Path(__file__).resolve().parents[1]
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

REPORT_PATH = Path("ci-logs/identified-hil/report.json")
CONFIRM = "I_ACCEPT_IDENTIFIED_HARDWARE_FLASH"


def _ports() -> dict[str, str]:
    raw = os.environ.get("JARNSEN_IDENTIFIED_HIL_PORTS", "").strip()
    result: dict[str, str] = {}
    for item in raw.split(","):
        key, sep, port = item.partition("=")
        if sep and key.strip() and port.strip():
            result[key.strip()] = port.strip()
    return result


def _write_report(report: dict[str, Any]) -> None:
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(
        json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def _summary(info: str):
    from profile_utils import summary_from_info_text

    return summary_from_info_text(info)


def _role_info(
    provisioning: Any, services: Any, port: str
) -> tuple[str, dict[str, str]]:
    line = provisioning._raw_command(
        port,
        "JARNSEN_TOOL_ROLE_INFO",
        expected="===JARNSEN_ROLE===",
        timeout=5.0,
        attempts=2,
        services=services,
    )
    return line, provisioning._parse_role_info(line)


def _set_role(provisioning: Any, services: Any, port: str, role: str) -> None:
    result = provisioning._raw_command(
        port,
        f"JARNSEN_TOOL_ROLE_SET {role}",
        expected="===JARNSEN_ROLE_OK===",
        timeout=6.0,
        attempts=2,
        services=services,
    )
    if "verified=1" not in result:
        raise RuntimeError(
            f"ROLE_SET {role} wurde nicht eindeutig bestätigt: {result!r}"
        )
    _line, parsed = _role_info(provisioning, services, port)
    if str(parsed.get("role", "")).strip().casefold() != role.casefold():
        raise RuntimeError(
            f"ROLE_SET Readback falsch: erwartet={role!r} ist={parsed.get('role')!r}"
        )


def _alternate_role(board_key: str, current: str) -> str:
    preferred = "tak_tracker" if board_key == "tracker" else "tak_repeater"
    return "tak" if current.casefold() == preferred else preferred


def _assert_board(services: Any, board_key: str, port: str) -> str:
    info = services.verify_node(port)
    detected = services.detect_board_from_text(info)
    if detected != board_key:
        raise RuntimeError(
            f"SAFETY STOP {port}: erwartet={board_key!r}, erkannt={detected!r}. "
            "Kein Flash/Write ausgeführt."
        )
    return info


def main() -> int:
    if os.environ.get("JARNSEN_IDENTIFIED_HIL_CONFIRM", "").strip() != CONFIRM:
        raise RuntimeError(
            "Identified-board HIL ist nicht freigegeben. "
            f"JARNSEN_IDENTIFIED_HIL_CONFIRM={CONFIRM} fehlt."
        )

    ports = _ports()
    if not ports:
        raise RuntimeError("JARNSEN_IDENTIFIED_HIL_PORTS ist leer.")

    import _build_version  # noqa: F401 - installs complete runtime stack
    import review_team_provisioning_v2 as provisioning
    import services
    from hil_reference import resolve_reference_bundle
    from unified_service_v2 import flash_firmware_only_bundle

    report: dict[str, Any] = {
        "status": "running",
        "started": time.time(),
        "ports": ports,
        "devices": {},
    }
    _write_report(report)

    try:
        # Hard safety gate: every configured device must identify as the exact
        # expected board before the first destructive operation starts.
        initial_info: dict[str, str] = {}
        for board_key, port in ports.items():
            if board_key not in services.BOARD_PROFILES:
                raise RuntimeError(f"Unbekannter Board-Key: {board_key}")
            initial_info[board_key] = _assert_board(services, board_key, port)
            remember = getattr(
                getattr(services, "device_sessions", None), "remember", None
            )
            if callable(remember):
                remember(port)

        for index, (board_key, original_port) in enumerate(ports.items(), start=1):
            label = str(services.BOARD_PROFILES[board_key].get("label") or board_key)
            device_report: dict[str, Any] = {
                "board": board_key,
                "label": label,
                "original_port": original_port,
                "steps": [],
            }
            report["devices"][board_key] = device_report
            _write_report(report)

            before_info = initial_info[board_key]
            before_summary = _summary(before_info)
            original_long = str(getattr(before_summary, "long_name", "") or "").strip()
            original_short = str(
                getattr(before_summary, "short_name", "") or ""
            ).strip()
            original_role = (
                str(getattr(before_summary, "role", "") or "").strip().casefold()
            )
            before_identity = services.query_jarnsen_identity(original_port)
            device_report["before"] = {
                "long_name": original_long,
                "short_name": original_short,
                "role": original_role,
                "build": (
                    getattr(before_identity, "build", None) if before_identity else None
                ),
                "version": (
                    getattr(before_identity, "version", "") if before_identity else ""
                ),
            }

            bundle = resolve_reference_bundle(services, board_key)
            preflight = services.run_flash_preflight(
                original_port, board_key, bundle, "update"
            )
            if not preflight.ready:
                raise RuntimeError(
                    f"{board_key} Preflight fehlgeschlagen: {preflight.format()}"
                )
            device_report["steps"].append("preflight-passed")
            _write_report(report)

            def log(
                message: str, label: str = label, original_port: str = original_port
            ) -> None:
                print(f"[{label} {original_port}] {message}", flush=True)

            flash_firmware_only_bundle(services, original_port, board_key, bundle, log)
            live_port = services.wait_for_device_reconnect(
                original_port,
                timeout=120,
                expected_board=board_key,
            )
            device_report["live_port_after_flash"] = live_port
            after_info = _assert_board(services, board_key, live_port)
            after_identity = services.query_jarnsen_identity(live_port)
            if after_identity is None:
                raise RuntimeError(
                    f"{board_key} {live_port}: JARNSEN-Identität nach Flash fehlt."
                )
            if str(getattr(after_identity, "version", "")) != str(bundle.version):
                raise RuntimeError(
                    f"{board_key}: Version nach Flash falsch: "
                    f"{getattr(after_identity, 'version', None)!r} != {bundle.version!r}"
                )
            if int(getattr(after_identity, "build", 0) or 0) != int(bundle.run_number):
                raise RuntimeError(
                    f"{board_key}: Build nach Flash falsch: "
                    f"{getattr(after_identity, 'build', None)!r} != {bundle.run_number!r}"
                )
            device_report["steps"].append("firmware-update-readback-passed")

            preserved = _summary(after_info)
            if (
                original_long
                and str(getattr(preserved, "long_name", "") or "").strip()
                != original_long
            ):
                raise RuntimeError(
                    f"{board_key}: Long Name wurde durch Firmware-only Flash verändert."
                )
            if (
                original_short
                and str(getattr(preserved, "short_name", "") or "").strip()
                != original_short
            ):
                raise RuntimeError(
                    f"{board_key}: Short Name wurde durch Firmware-only Flash verändert."
                )
            if (
                original_role
                and str(getattr(preserved, "role", "") or "").strip().casefold()
                != original_role
            ):
                raise RuntimeError(
                    f"{board_key}: Rolle wurde durch Firmware-only Flash verändert."
                )
            device_report["steps"].append("settings-preserved")
            _write_report(report)

            # Reversible name write/readback test. Never run it if the original
            # identity cannot be restored exactly.
            if original_long and 1 <= len(original_short) <= 4:
                temp_long = f"HIL {label}"[:38].strip()
                temp_short = f"H{index}"[:4]
                try:
                    services.set_names(live_port, temp_long, temp_short)
                    check = _summary(
                        services.verify_node(live_port, expected_board=board_key)
                    )
                    if str(getattr(check, "long_name", "") or "").strip() != temp_long:
                        raise RuntimeError(
                            f"{board_key}: temporärer Long Name nicht lesbar."
                        )
                    if (
                        str(getattr(check, "short_name", "") or "").strip()
                        != temp_short
                    ):
                        raise RuntimeError(
                            f"{board_key}: temporärer Short Name nicht lesbar."
                        )
                    device_report["steps"].append(
                        "temporary-name-write-readback-passed"
                    )
                finally:
                    services.set_names(live_port, original_long, original_short)
                    restored = _summary(
                        services.verify_node(live_port, expected_board=board_key)
                    )
                    if (
                        str(getattr(restored, "long_name", "") or "").strip()
                        != original_long
                    ):
                        raise RuntimeError(
                            f"{board_key}: Long Name konnte nicht wiederhergestellt werden."
                        )
                    if (
                        str(getattr(restored, "short_name", "") or "").strip()
                        != original_short
                    ):
                        raise RuntimeError(
                            f"{board_key}: Short Name konnte nicht wiederhergestellt werden."
                        )
                    device_report["steps"].append("original-name-restored")
                    _write_report(report)

            # Reversible role service test. Only touch roles when role_api=1 is
            # explicitly confirmed on the installed firmware.
            role_line, role_data = _role_info(provisioning, services, live_port)
            if role_data.get("role_api") == "1" and role_data.get("role"):
                role_before = str(role_data["role"]).strip().casefold()
                role_temp = _alternate_role(board_key, role_before)
                try:
                    _set_role(provisioning, services, live_port, role_temp)
                    device_report["steps"].append(
                        f"temporary-role-{role_temp}-readback-passed"
                    )
                finally:
                    _set_role(provisioning, services, live_port, role_before)
                    device_report["steps"].append(
                        f"original-role-{role_before}-restored"
                    )
                    _write_report(report)
            else:
                device_report["steps"].append(f"role-write-skipped:{role_line[:120]}")

            final_info = _assert_board(services, board_key, live_port)
            final_summary = _summary(final_info)
            if (
                original_long
                and str(getattr(final_summary, "long_name", "") or "").strip()
                != original_long
            ):
                raise RuntimeError(f"{board_key}: finaler Long Name stimmt nicht.")
            if (
                original_short
                and str(getattr(final_summary, "short_name", "") or "").strip()
                != original_short
            ):
                raise RuntimeError(f"{board_key}: finaler Short Name stimmt nicht.")
            final_role = (
                str(getattr(final_summary, "role", "") or "").strip().casefold()
            )
            if original_role and final_role != original_role:
                raise RuntimeError(
                    f"{board_key}: finale Rolle stimmt nicht: {final_role!r} != {original_role!r}"
                )
            device_report["steps"].append("final-board-name-role-verify-passed")
            device_report["status"] = "passed"
            _write_report(report)

        report["status"] = "passed"
        report["finished"] = time.time()
        _write_report(report)
        print("IDENTIFIED MULTI-BOARD REAL HIL PASS", flush=True)
        return 0
    except Exception as exc:
        report["status"] = "failed"
        report["error_type"] = type(exc).__name__
        report["error"] = str(exc)
        report["finished"] = time.time()
        _write_report(report)
        raise


if __name__ == "__main__":
    raise SystemExit(main())
