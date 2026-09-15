from __future__ import annotations

import os
import re
import sys
import time
from pathlib import Path
from typing import Any

from serial.tools import list_ports

APP_DIR = Path(__file__).resolve().parents[1]
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

EXPECTED_BOARD = "tracker"
EXPECTED_SERIAL = os.environ.get("JARNSEN_TRACKER_SERIAL", "F0:9E:9E:76:07:10")
EXPECTED_VERSION = "2.0.0-alpha.31"
EXPECTED_BUILD = 185
SEQUENCE = ("standard", "jarnsen1", "jarnsen2", "standard")


def _log(message: str) -> None:
    print(f"TRACKER_RADIO_PROBE | {message}", flush=True)


def _norm(value: object) -> str:
    return "".join(ch for ch in str(value or "") if ch.isalnum()).upper()


def _exact_tracker():
    expected = _norm(EXPECTED_SERIAL)
    matches = [
        item
        for item in list_ports.comports()
        if getattr(item, "vid", None) == 0x303A
        and getattr(item, "pid", None) == 0x1001
        and _norm(getattr(item, "serial_number", "")) == expected
    ]
    if len(matches) != 1:
        raise RuntimeError(f"EXACT_TRACKER_MATCH_COUNT={len(matches)}")
    return matches[0]


def _rebind_exact(services: Any, previous_port: str, timeout: float = 60.0) -> str:
    deadline = time.monotonic() + timeout
    last_error: BaseException | None = None
    while time.monotonic() < deadline:
        try:
            item = _exact_tracker()
            port = str(item.device)
            info = services.verify_node(port, expected_board=EXPECTED_BOARD)
            if services.detect_board_from_text(info) != EXPECTED_BOARD:
                raise RuntimeError("EXACT_TRACKER_BOARD_MISMATCH")
            fingerprint = services.device_sessions.remember(port)
            if fingerprint is None or _norm(fingerprint.serial_number) != _norm(
                EXPECTED_SERIAL
            ):
                raise RuntimeError("EXACT_TRACKER_PHYSICAL_REBIND_FAILED")
            if port != previous_port:
                _log(f"PORT_CHANGE before={previous_port} after={port}")
            return port
        except Exception as exc:
            last_error = exc
            time.sleep(1.0)
    raise RuntimeError(
        "EXACT_TRACKER_NOT_READY: "
        f"{type(last_error).__name__ if last_error else 'unknown'}: {last_error}"
    ) from last_error


def _radio_info(radio_sync: Any, port: str) -> tuple[str, str]:
    line = radio_sync._raw_command(
        port,
        "JARNSEN_TOOL_RADIO_INFO",
        expected=radio_sync.RADIO_INFO_MARKER,
        timeout=8.0,
    )
    match = radio_sync.ACTIVE_RE.search(line)
    if not match:
        raise RuntimeError(f"RADIO_ACTIVE_MISSING={line}")
    return match.group(1).lower(), line


def main() -> int:
    # Match the packaged Flasher bootstrap so all runtime hardening layers are active.
    import _build_version  # noqa: F401
    import functional_profiles  # noqa: F401
    import radio_profile_node_sync as radio_sync
    import review_team_provisioning_v2 as provisioning  # noqa: F401
    import services
    import unified_service_v2  # noqa: F401
    import usb_log_download  # noqa: F401

    tracker = _exact_tracker()
    port = str(tracker.device)
    fingerprint = services.device_sessions.remember(port)
    if fingerprint is None or _norm(fingerprint.serial_number) != _norm(EXPECTED_SERIAL):
        raise RuntimeError("TRACKER_PHYSICAL_LOCK_FAILED")
    _log(
        f"LOCK port={port} vidpid=303A:1001 serial={EXPECTED_SERIAL} "
        f"location={getattr(tracker, 'location', '')!r}"
    )

    info = services.verify_node(port, expected_board=EXPECTED_BOARD)
    if services.detect_board_from_text(info) != EXPECTED_BOARD:
        raise RuntimeError("TRACKER_BOARD_MISMATCH")
    identity = services.query_jarnsen_identity(port)
    if identity is None:
        raise RuntimeError("JARNSEN_IDENTITY_MISSING")
    if (
        getattr(identity, "version", "") != EXPECTED_VERSION
        or getattr(identity, "build", None) != EXPECTED_BUILD
    ):
        raise RuntimeError(
            "WRONG_REFERENCE_FIRMWARE "
            f"version={getattr(identity, 'version', '')!r} "
            f"build={getattr(identity, 'build', None)!r}"
        )
    _log(f"REFERENCE_OK version={identity.version} build={identity.build}")

    active_start, start_line = _radio_info(radio_sync, port)
    _log(f"START active={active_start} info={start_line}")

    failures: list[str] = []
    results: list[str] = []
    for target in SEQUENCE:
        try:
            port = _rebind_exact(services, port, timeout=30.0)
            radio_sync._select_raw(port, target, services)
            port = _rebind_exact(services, port, timeout=60.0)
            active, line = _radio_info(radio_sync, port)
            if active != target:
                raise RuntimeError(
                    f"READBACK_MISMATCH target={target!r} active={active!r} info={line}"
                )
            result = f"target={target} active={active} status=PASS"
            results.append(result)
            _log(f"SWITCH {result} info={line}")
        except Exception as exc:
            result = (
                f"target={target} status=FAIL type={type(exc).__name__} "
                f"message={str(exc)[:500]}"
            )
            results.append(result)
            failures.append(result)
            _log(f"SWITCH {result}")

    # Fail closed, but always try to leave the physical Tracker on Standard.
    try:
        port = _rebind_exact(services, port, timeout=30.0)
        active, line = _radio_info(radio_sync, port)
        if active != "standard":
            radio_sync._select_raw(port, "standard", services)
            port = _rebind_exact(services, port, timeout=60.0)
            active, line = _radio_info(radio_sync, port)
        if active != "standard":
            raise RuntimeError(f"FINAL_STANDARD_RESTORE_MISMATCH active={active!r}")
        _log(f"FINAL active=standard status=PASS info={line}")
    except Exception as exc:
        failure = (
            f"final-standard status=FAIL type={type(exc).__name__} "
            f"message={str(exc)[:500]}"
        )
        failures.append(failure)
        _log(f"FINAL {failure}")

    _log("SUMMARY " + " | ".join(results))
    if failures:
        raise RuntimeError("THREE_PROFILE_SWITCH_CONTRACT_FAILED: " + " || ".join(failures))

    _log("RESULT=THREE_PROFILE_SWITCH_CONTRACT_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
