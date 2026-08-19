#!/usr/bin/env python3

import subprocess
import sys

PROFILES = {
    "tracker": {
        "owned_prefixes": (
            ".github/",
            "docs/",
            "tools/jarnsen/",
            "src/vehicle/",
            "variants/esp32s3/heltec_wireless_tracker/TAK_LEADER.md",
            "variants/esp32s3/heltec_wireless_tracker/VEHICLE_MOTION_WAKE.md",
        ),
        "allowed_core": {
            "src/PowerFSM.cpp",
            "src/modules/PositionModule.h",
            "src/platform/extra_variants/heltec_wireless_tracker/variant.cpp",
            "variants/esp32s3/heltec_wireless_tracker/platformio.ini",
            "variants/esp32s3/heltec_wireless_tracker/variant.h",
        },
    },
    "repeater": {
        "owned_prefixes": (
            ".github/",
            "docs/",
            "tools/jarnsen/",
            "src/infrastructure/",
        ),
        "allowed_core": {
            "variants/esp32s3/heltec_v3/variant.h",
        },
    },
}


def changed_files(base: str) -> list[str]:
    output = subprocess.check_output(
        ["git", "diff", "--name-only", f"{base}...HEAD"],
        text=True,
    )
    return [line.strip() for line in output.splitlines() if line.strip()]


def main() -> int:
    if len(sys.argv) != 3 or sys.argv[1] not in PROFILES:
        print("usage: check_custom_core_touchpoints.py <tracker|repeater> <base-ref>")
        return 2

    profile_name = sys.argv[1]
    base = sys.argv[2]
    profile = PROFILES[profile_name]
    files = changed_files(base)

    expected_core = []
    unexpected = []
    owned = []

    for path in files:
        if path in profile["allowed_core"]:
            expected_core.append(path)
        elif any(path.startswith(prefix) for prefix in profile["owned_prefixes"]):
            owned.append(path)
        else:
            unexpected.append(path)

    print(f"Custom firmware profile: {profile_name}")
    print(f"Custom-owned files: {len(owned)}")
    print(f"Expected Meshtastic core touchpoints: {len(expected_core)}")
    for path in sorted(expected_core):
        print(f"  CORE  {path}")

    if unexpected:
        print("Unexpected Meshtastic core changes detected:")
        for path in sorted(unexpected):
            print(f"  NEW   {path}")
        print("Add a core change only deliberately, document why it is required, then update this guard.")
        return 1

    print("Core touchpoint guard: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
