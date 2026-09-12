# ruff: noqa: E402
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import board_detection  # noqa: E402
import unified_board_support  # noqa: E402

PROFILES = {
    "tracker": {
        "pio_env": "heltec-wireless-tracker",
        "match": ("HELTEC_WIRELESS_TRACKER", "HELTEC WIRELESS TRACKER"),
    },
    "repeater": {
        "pio_env": "heltec-v3",
        "match": ("HELTEC_V3", "HELTEC V3"),
    },
    "wio": {
        "pio_env": "seeed_wio_tracker_L1",
        "match": ("WIO_TRACKER_L1", "WIO TRACKER L1"),
    },
    "heltec_v4": {
        "pio_env": "heltec-v4",
        "match": ("HELTEC_V4", "HELTEC V4"),
    },
    "tbeam": {
        "pio_env": "tbeam",
        "match": ("T_BEAM", "T-BEAM", "TBEAM"),
    },
    "tbeam_supreme": {
        "pio_env": "tbeam-s3-core",
        "match": ("T_BEAM_SUPREME", "T-BEAM SUPREME", "TBEAM-S3-CORE"),
    },
}


class FakeServices:
    BOARD_PROFILES = PROFILES


def main() -> int:
    # Install the same runtime wrapper used by the packaged flasher.
    unified_board_support._patch_board_detection(FakeServices)

    # Regression for the real COM17 failure: the connected device is a Heltec
    # Wireless Tracker, while a remote node later in the mesh database contains
    # a T-Beam Supreme identity. Remote hardware must never override the local
    # pioEnv/hwModel.
    tracker_with_remote_tbeam = """
Connected to radio
Owner: Bravo 1 MrsZg26 (B1)
My info: { "pioEnv": "heltec-wireless-tracker", "nodedbCount": 44 }
Metadata: { "hwModel": "HELTEC_WIRELESS_TRACKER", "role": "TAK_TRACKER" }

Nodes in mesh: {
  "!remote": {
    "user": { "longName": "Remote T-Beam" },
    "metadata": { "pioEnv": "tbeam-s3-core", "hwModel": "TBEAM-S3-CORE" }
  }
}
"""
    result = board_detection.detect(tracker_with_remote_tbeam, PROFILES)
    assert result.board_key == "tracker", result
    assert str(result.reason).startswith("structured "), result

    # A locally connected T-Beam Supreme must still be detected normally.
    local_tbeam_supreme = """
Connected to radio
My info: { "pioEnv": "tbeam-s3-core" }
Metadata: { "hwModel": "T_BEAM_SUPREME" }
Nodes in mesh: {}
"""
    result = board_detection.detect(local_tbeam_supreme, PROFILES)
    assert result.board_key == "tbeam_supreme", result

    print("board detection priority regression: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
