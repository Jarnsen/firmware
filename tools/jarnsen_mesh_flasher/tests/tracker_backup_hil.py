from __future__ import annotations

import hashlib
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import backup_stability
import device_core
import reconnect_identity_guard
import services
import unified_service_v2
from serial.tools import list_ports

EXPECTED_SERIAL = os.environ.get("JARNSEN_TRACKER_SERIAL", "F0:9E:9E:76:07:10")


def _norm(value: object) -> str:
    return "".join(ch for ch in str(value or "") if ch.isalnum()).upper()


def _exact_tracker():
    expected = _norm(EXPECTED_SERIAL)
    matches = [
        port
        for port in list_ports.comports()
        if _norm(getattr(port, "serial_number", "")) == expected
        and getattr(port, "vid", None) == 0x303A
        and getattr(port, "pid", None) == 0x1001
    ]
    if len(matches) != 1:
        raise RuntimeError(f"EXACT_TRACKER_MATCH_COUNT={len(matches)}")
    return matches[0]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().lower()


def main() -> int:
    tracker = _exact_tracker()
    port = str(tracker.device)
    print(
        f"TRACKER_LOCK port={port} serial_match=1 vidpid=303A:1001 "
        f"location={getattr(tracker, 'location', '')!r}"
    )

    unified_service_v2.install(services)
    device_core.install(services)
    reconnect_identity_guard.install(services)
    backup_stability.install(services)

    fingerprint = services.device_sessions.remember(port)
    if fingerprint is None or _norm(fingerprint.serial_number) != _norm(EXPECTED_SERIAL):
        raise RuntimeError("TRACKER_PHYSICAL_LOCK_FAILED")

    target = Path(services.backup_flash(port, "tracker")).resolve()
    size = target.stat().st_size
    if size <= 0:
        raise RuntimeError("BACKUP_FILE_EMPTY")
    digest = _sha256(target)

    deadline = time.monotonic() + 45
    returned = None
    while time.monotonic() < deadline:
        try:
            returned = _exact_tracker()
            break
        except RuntimeError:
            time.sleep(1)
    if returned is None:
        raise RuntimeError("EXACT_TRACKER_NOT_RETURNED_AFTER_BACKUP")

    live_port = str(returned.device)
    info = services.verify_node(live_port, "tracker")
    if services.detect_board_from_text(info) != "tracker":
        raise RuntimeError("TRACKER_POST_BACKUP_BOARD_VERIFY_FAILED")

    print(f"BACKUP_RESULT_NAME={target.name}")
    print(f"BACKUP_RESULT_BYTES={size}")
    print(f"BACKUP_RESULT_SHA256={digest}")
    print(f"BACKUP_RESULT_DIRECTORY={target.parent}")
    print(f"TRACKER_RETURNED_PORT={live_port}")
    print("RESULT=TRACKER_ACTUAL_FLASHER_BACKUP_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
