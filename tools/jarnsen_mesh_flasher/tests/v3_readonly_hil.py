from __future__ import annotations

import json
import sys
import time
from pathlib import Path

APP_DIR = Path(__file__).resolve().parents[1]
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

REPORT_PATH = Path("ci-logs/v3-readonly-hil/report.json")


def _write_report(payload: dict) -> None:
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    import _build_version  # noqa: F401 - install production runtime stack
    import native_actions
    import review_team_provisioning_v2 as provisioning
    import services
    from profile_utils import summary_from_info_text

    report = {
        "status": "scanning",
        "started": time.time(),
        "devices": [],
    }
    _write_report(report)

    devices = list(services.scan_devices(probe_timeout=8))
    report["devices"] = [
        {
            "port": str(getattr(item, "port", "")),
            "board": str(getattr(item, "board_key", "") or ""),
        }
        for item in devices
    ]
    v3 = [item for item in devices if getattr(item, "board_key", None) == "repeater"]
    if not v3:
        report["status"] = "skipped"
        report["reason"] = "no-heltec-v3-detected"
        report["finished"] = time.time()
        _write_report(report)
        print("V3 READONLY HIL SKIP | no Heltec V3 detected", flush=True)
        return 0
    if len(v3) != 1:
        raise RuntimeError(
            f"V3 READONLY HIL erwartet genau einen Heltec V3, erkannt={len(v3)}"
        )

    device = v3[0]
    port = str(device.port)
    info = services.verify_node(port, expected_board="repeater")
    summary = summary_from_info_text(info)
    role_line = provisioning._raw_command(
        port,
        "JARNSEN_TOOL_ROLE_INFO",
        expected="===JARNSEN_ROLE===",
        timeout=5.0,
        attempts=2,
        services=services,
    )
    role = provisioning._parse_role_info(role_line)
    settings = native_actions._basic_settings_from_info(info)

    service_role = str(role.get("role", "") or "").strip().casefold()
    if service_role not in {"tak", "tak_repeater"}:
        raise RuntimeError(
            f"V3 meldet unzulässige JARNSEN-Rolle {service_role!r}; "
            "zulässig sind tak und tak_repeater."
        )
    identifier = native_actions._functional_identifier_from_node(
        service_role, summary.role, "repeater"
    )
    if identifier != service_role:
        raise RuntimeError(
            f"V3 Rollenabbildung inkonsistent: service={service_role!r}, "
            f"meshtastic={summary.role!r}, mapped={identifier!r}"
        )

    expected_meshtastic = "TAK" if service_role == "tak" else "ROUTER_LATE"
    role_consistent = str(summary.role or "").strip().upper() == expected_meshtastic

    report.update(
        {
            "status": "passed",
            "port": port,
            "role_service": service_role,
            "meshtastic_role": summary.role,
            "expected_meshtastic_role": expected_meshtastic,
            "role_consistent": role_consistent,
            "long_name": summary.long_name,
            "short_name": summary.short_name,
            "settings": settings,
            "finished": time.time(),
        }
    )
    _write_report(report)
    print(
        "V3 READONLY HIL PASS | "
        f"port={port} role={service_role} meshtastic={summary.role} "
        f"long={summary.long_name!r} short={summary.short_name!r} "
        f"settings={settings} role_consistent={int(role_consistent)}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
