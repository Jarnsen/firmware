from __future__ import annotations

import os
import re
import sys
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from serial.tools import list_ports

APP_DIR = Path(__file__).resolve().parents[1]
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

EXPECTED_BOARD = "tracker"
EXPECTED_SERIAL = os.environ.get("JARNSEN_TRACKER_SERIAL", "F0:9E:9E:76:07:10")
TEST_FUNCTION = "tak_tracker"
TEST_ROLE = "tak_tracker"
TEST_LONG_NAME = "JARNSEN HIL Tracker"
TEST_SHORT_NAME = "HIL"


def _log(message: str) -> None:
    print(f"TRACKER_FULL_HIL | {message}", flush=True)


@contextmanager
def _phase(name: str) -> Iterator[None]:
    started = time.monotonic()
    _log(f"PHASE START | {name}")
    try:
        yield
    except Exception as exc:
        _log(
            f"PHASE FAIL | {name} | {time.monotonic() - started:.2f}s | "
            f"{type(exc).__name__}: {str(exc)[:500]}"
        )
        raise
    else:
        _log(f"PHASE OK | {name} | {time.monotonic() - started:.2f}s")


def _norm(value: object) -> str:
    return "".join(ch for ch in str(value or "") if ch.isalnum()).upper()


def _role_key(value: object) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(value or "").strip().casefold()).strip("_")


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


def _wait_exact(services: Any, previous_port: str, timeout: int = 120) -> str:
    deadline = time.monotonic() + max(10, timeout)
    last_error: BaseException | None = None
    while time.monotonic() < deadline:
        try:
            item = _exact_tracker()
            port = str(item.device)
            info = services.verify_node(port, expected_board=EXPECTED_BOARD)
            if services.detect_board_from_text(info) != EXPECTED_BOARD:
                raise RuntimeError("EXACT_TRACKER_BOARD_MISMATCH")
            fingerprint = services.device_sessions.remember(port)
            if fingerprint is None or _norm(fingerprint.serial_number) != _norm(EXPECTED_SERIAL):
                raise RuntimeError("EXACT_TRACKER_PHYSICAL_REBIND_FAILED")
            if port != previous_port:
                _log(f"PORT CHANGE | {previous_port} -> {port}")
            return port
        except Exception as exc:
            last_error = exc
            time.sleep(1.0)
    raise RuntimeError(
        "EXACT_TRACKER_NOT_READY_AFTER_OPERATION: "
        f"{type(last_error).__name__ if last_error else 'unknown'}: {last_error}"
    ) from last_error


def _raw_role(provisioning: Any, services: Any, port: str) -> dict[str, str]:
    line = provisioning._raw_command(
        port,
        "JARNSEN_TOOL_ROLE_INFO",
        expected="===JARNSEN_ROLE===",
        timeout=5.0,
        attempts=3,
        services=services,
    )
    return provisioning._parse_role_info(line)


def _set_raw_role(provisioning: Any, services: Any, port: str, role: str) -> None:
    wanted = _role_key(role)
    if not wanted:
        return
    result = provisioning._raw_command(
        port,
        f"JARNSEN_TOOL_ROLE_SET {wanted}",
        expected="===JARNSEN_ROLE_OK===",
        timeout=6.0,
        attempts=3,
        services=services,
    )
    if "verified=1" not in result:
        raise RuntimeError(f"ROLE_SET_NOT_VERIFIED: {result}")
    readback = _raw_role(provisioning, services, port)
    if _role_key(readback.get("role")) != wanted:
        raise RuntimeError(f"ROLE_READBACK_MISMATCH={readback}")


def main() -> int:
    # Same ordered runtime bootstrap used by the packaged Windows EXE.
    import _build_version  # noqa: F401
    import functional_profiles
    import radio_profile_node_sync as radio_sync
    import review_team_provisioning_v2 as provisioning
    import services
    import unified_service_v2
    from hil_reference import resolve_reference_bundle
    from profile_utils import summary_from_info_text

    services._jarnsen_ui_log_callback = lambda message: _log("UI | " + str(message))
    services._jarnsen_profile_progress_callback = (
        lambda fraction, stage, detail="": _log(
            f"PROGRESS | {float(fraction):.3f} | {stage} | {detail}"
        )
    )

    tracker = _exact_tracker()
    port = str(tracker.device)
    _log(
        f"LOCK | port={port} vidpid=303A:1001 serial_match=1 "
        f"location={getattr(tracker, 'location', '')!r}"
    )
    fingerprint = services.device_sessions.remember(port)
    if fingerprint is None or _norm(fingerprint.serial_number) != _norm(EXPECTED_SERIAL):
        raise RuntimeError("TRACKER_PHYSICAL_LOCK_FAILED")

    with _phase("baseline-read-and-profile-export"):
        baseline_info = services.verify_node(port, expected_board=EXPECTED_BOARD)
        baseline_summary = summary_from_info_text(baseline_info)
        baseline_role = _raw_role(provisioning, services, port)
        baseline_profile = Path(services.export_profile(port)).resolve()
        if not baseline_profile.exists() or baseline_profile.stat().st_size < 20:
            raise RuntimeError("BASELINE_PROFILE_EXPORT_FAILED")
        _log(
            "BASELINE | "
            f"long={baseline_summary.long_name!r} short={baseline_summary.short_name!r} "
            f"role={baseline_role.get('role')!r} profile={baseline_profile.name}"
        )

    with _phase("activate-tak-tracker-profile"):
        functional_profiles.ensure_profiles(services)
        test_profile = Path(functional_profiles.profile_path(services, TEST_FUNCTION)).resolve()
        if not test_profile.exists():
            raise RuntimeError(f"TEST_PROFILE_MISSING={test_profile}")
        services.import_profile_file(test_profile)
        if functional_profiles.active_profile_id(services) != TEST_FUNCTION:
            raise RuntimeError("TEST_PROFILE_NOT_ACTIVE")

    with _phase("resolve-reference-firmware-and-preflight"):
        bundle = resolve_reference_bundle(services, EXPECTED_BOARD)
        _log(
            f"TARGET | version={bundle.version} build={bundle.run_number} "
            f"factory={bundle.factory.name} update={bundle.update.name}"
        )
        preflight = services.run_flash_preflight(port, EXPECTED_BOARD, bundle, "provision")
        for line in preflight.format().splitlines():
            if line:
                _log("PREFLIGHT | " + line)
        if not preflight.ready:
            raise RuntimeError(preflight.format())

    with _phase("safety-backup"):
        backup = Path(services.backup_flash(port, EXPECTED_BOARD)).resolve()
        if not backup.exists() or backup.stat().st_size != 8 * 1024 * 1024:
            raise RuntimeError(f"BACKUP_INVALID={backup}")
        _log(f"BACKUP | name={backup.name} bytes={backup.stat().st_size}")
        port = _wait_exact(services, port, timeout=60)

    with _phase("full-factory-flash"):
        services.flash_bundle(
            port,
            bundle,
            log=lambda message: _log("FLASH | " + str(message)),
        )
        port = _wait_exact(services, port, timeout=150)
        identity = services.query_jarnsen_identity(port)
        _log(
            f"FULL FLASH ID | version={getattr(identity, 'version', '')} "
            f"build={getattr(identity, 'build', None)}"
        )

    # The resolved bundle is already a fully local on-disk FirmwareBundle. A
    # second full write exercises the local-image path without another download.
    with _phase("local-firmware-image-full-flash"):
        if not Path(bundle.factory).is_file() or not Path(bundle.update).is_file():
            raise RuntimeError("LOCAL_FIRMWARE_FILES_MISSING")
        _log(f"LOCAL SOURCE | root={Path(bundle.root).name} factory={Path(bundle.factory).name}")
        services.flash_bundle(
            port,
            bundle,
            log=lambda message: _log("LOCAL FLASH | " + str(message)),
        )
        port = _wait_exact(services, port, timeout=150)

    with _phase("profile-role-write-and-verify"):
        prepare = getattr(services, "prepare_profile_write", None)
        if callable(prepare):
            prepare(port, TEST_LONG_NAME, TEST_SHORT_NAME)
        services.restore_profile(port, test_profile)
        port = _wait_exact(services, port, timeout=120)
        services.verify_written_profile(port, test_profile, board_key=EXPECTED_BOARD)
        role = _raw_role(provisioning, services, port)
        if _role_key(role.get("role")) != TEST_ROLE:
            raise RuntimeError(f"TEST_ROLE_MISMATCH={role}")
        _log(f"ROLE | {role}")

    with _phase("name-write-and-readback"):
        services.set_names(port, TEST_LONG_NAME, TEST_SHORT_NAME)
        port = _wait_exact(services, port, timeout=90)
        info = services.verify_node(port, expected_board=EXPECTED_BOARD)
        summary = summary_from_info_text(info)
        if summary.long_name != TEST_LONG_NAME or summary.short_name != TEST_SHORT_NAME:
            raise RuntimeError(
                f"NAME_READBACK_MISMATCH long={summary.long_name!r} short={summary.short_name!r}"
            )
        _log(f"NAMES | long={summary.long_name!r} short={summary.short_name!r}")

    with _phase("usb-service-contract"):
        tool_info = provisioning._raw_command(
            port,
            "JARNSEN_TOOL_INFO",
            expected="===JARNSEN_INFO===",
            timeout=5.0,
            attempts=3,
            services=services,
        )
        if "role_api=1" not in tool_info:
            raise RuntimeError(f"TOOL_INFO_ROLE_API_MISSING={tool_info}")
        role = _raw_role(provisioning, services, port)
        if role.get("role_api") != "1":
            raise RuntimeError(f"ROLE_API_NOT_READY={role}")
        radio_line = radio_sync._raw_command(
            port,
            "JARNSEN_TOOL_RADIO_INFO",
            expected=radio_sync.RADIO_INFO_MARKER,
            timeout=8.0,
        )
        _log(f"TOOL INFO OK | {tool_info[:300]}")
        _log(f"RADIO INFO OK | {radio_line[:300]}")

    with _phase("radio-slot-sync-preserve-active"):
        active_before = services.read_active_radio_profile_stable(port)
        services.sync_radio_profiles_to_node(port)
        port = _wait_exact(services, port, timeout=120)
        active_after = services.read_active_radio_profile_stable(port)
        if active_after != active_before:
            raise RuntimeError(
                f"RADIO_ACTIVE_CHANGED before={active_before!r} after={active_after!r}"
            )
        _log(f"RADIO ACTIVE | before={active_before} after={active_after}")

    with _phase("firmware-only-update-preserves-profile-role-names"):
        unified_service_v2.flash_firmware_only_bundle(
            services,
            port,
            EXPECTED_BOARD,
            bundle,
            lambda message: _log("FW-ONLY | " + str(message)),
        )
        port = _wait_exact(services, port, timeout=150)
        identity = services.query_jarnsen_identity(port)
        if identity is None:
            raise RuntimeError("FW_ONLY_IDENTITY_MISSING")
        if getattr(identity, "version", "") != bundle.version:
            raise RuntimeError(
                f"FW_ONLY_VERSION_MISMATCH={getattr(identity, 'version', '')!r} expected={bundle.version!r}"
            )
        if getattr(identity, "build", None) != bundle.run_number:
            raise RuntimeError(
                f"FW_ONLY_BUILD_MISMATCH={getattr(identity, 'build', None)!r} expected={bundle.run_number!r}"
            )
        info = services.verify_node(port, expected_board=EXPECTED_BOARD)
        summary = summary_from_info_text(info)
        role = _raw_role(provisioning, services, port)
        if summary.long_name != TEST_LONG_NAME or summary.short_name != TEST_SHORT_NAME:
            raise RuntimeError("FW_ONLY_NAMES_NOT_PRESERVED")
        if _role_key(role.get("role")) != TEST_ROLE:
            raise RuntimeError(f"FW_ONLY_ROLE_NOT_PRESERVED={role}")
        services.verify_written_profile(port, test_profile, board_key=EXPECTED_BOARD)
        _log(
            f"FW-ONLY VERIFIED | version={identity.version} build={identity.build} "
            f"names={summary.long_name!r}/{summary.short_name!r} role={role.get('role')!r}"
        )

    with _phase("restore-baseline-node-state"):
        # Cleanup deliberately uses the exported baseline directly. This avoids
        # re-applying the temporary functional-profile overlay while restoring.
        services.meshtastic(port, "--configure", str(baseline_profile), timeout=180)
        port = _wait_exact(services, port, timeout=120)
        if baseline_summary.long_name and baseline_summary.short_name:
            services.set_names(port, baseline_summary.long_name, baseline_summary.short_name)
            port = _wait_exact(services, port, timeout=90)
        original_role = _role_key(baseline_role.get("role"))
        if original_role:
            _set_raw_role(provisioning, services, port, original_role)
            port = _wait_exact(services, port, timeout=90)
        final_info = services.verify_node(port, expected_board=EXPECTED_BOARD)
        final_summary = summary_from_info_text(final_info)
        final_role = _raw_role(provisioning, services, port)
        if baseline_summary.long_name and final_summary.long_name != baseline_summary.long_name:
            raise RuntimeError("BASELINE_LONG_NAME_RESTORE_FAILED")
        if baseline_summary.short_name and final_summary.short_name != baseline_summary.short_name:
            raise RuntimeError("BASELINE_SHORT_NAME_RESTORE_FAILED")
        if original_role and _role_key(final_role.get("role")) != original_role:
            raise RuntimeError(f"BASELINE_ROLE_RESTORE_FAILED={final_role}")
        _log(
            f"RESTORED | long={final_summary.long_name!r} short={final_summary.short_name!r} "
            f"role={final_role.get('role')!r}"
        )

    _log(f"RESULT=TRACKER_FULL_FLASHER_HIL_OK port={port}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
