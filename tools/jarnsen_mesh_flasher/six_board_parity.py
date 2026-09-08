from __future__ import annotations

from pathlib import Path
from typing import Any


SUPPORTED_BOARDS = (
    "tracker",
    "repeater",
    "wio",
    "heltec_v4",
    "tbeam",
    "tbeam_supreme",
)

EXPECTED_PIO = {
    "tracker": "heltec-wireless-tracker",
    "repeater": "heltec-v3",
    "wio": "seeed_wio_tracker_L1",
    "heltec_v4": "heltec-v4",
    "tbeam": "tbeam",
    "tbeam_supreme": "tbeam-s3-core",
}

USER_FEATURES = (
    "board_detection",
    "manual_board_fallback",
    "firmware_identity",
    "github_update_resolution",
    "backup",
    "automatic_flash",
    "firmware_only",
    "local_firmware",
    "profile_read",
    "profile_write",
    "role_choice",
    "role_readback",
    "name_choice",
    "name_write",
    "name_readback",
    "reboot_reconnect",
    "usb_node_log",
    "radio_profiles",
    "series_flash",
    "final_verify",
    "serial_arbitration",
)


def _source(name: str) -> str:
    return (Path(__file__).with_name(name)).read_text(encoding="utf-8", errors="replace")


def validate(services: Any) -> dict[str, dict[str, str]]:
    """Hard runtime/build gate for equal user-visible support on all six boards.

    This validates the common architecture without pretending that a source-level
    gate replaces physical hardware testing. Board-specific transport code is
    allowed only when it falls back to the common action for every other board.
    """
    missing = [key for key in SUPPORTED_BOARDS if key not in services.BOARD_PROFILES]
    if missing:
        raise AssertionError(f"Six-board parity: missing board profiles: {missing}")

    labels: set[str] = set()
    for key in SUPPORTED_BOARDS:
        profile = services.BOARD_PROFILES[key]
        for field in ("label", "pio_env", "branch", "workflow_path", "artifact_prefix", "match"):
            if not profile.get(field):
                raise AssertionError(f"Six-board parity: {key} missing profile field {field}")
        if profile["pio_env"] != EXPECTED_PIO[key]:
            raise AssertionError(
                f"Six-board parity: {key} pio_env={profile['pio_env']!r}, expected {EXPECTED_PIO[key]!r}"
            )
        if profile["branch"] != services.UNIFIED_BRANCH:
            raise AssertionError(f"Six-board parity: {key} not pinned to Unified Core branch")
        if profile["workflow_path"] != services.UNIFIED_WORKFLOW_PATH:
            raise AssertionError(f"Six-board parity: {key} not pinned to Unified Core workflow")
        label = str(profile["label"]).strip()
        if label in labels:
            raise AssertionError(f"Six-board parity: duplicate board label {label!r}")
        labels.add(label)

    expected_artifact_kinds = {
        "tracker": "esp32",
        "repeater": "esp32",
        "wio": "uf2",
        "heltec_v4": "esp32",
        "tbeam": "esp32",
        "tbeam_supreme": "esp32",
    }
    for key, kind in expected_artifact_kinds.items():
        actual = str(services.BOARD_PROFILES[key].get("artifact_kind") or "esp32").lower()
        if actual != kind:
            raise AssertionError(f"Six-board parity: {key} artifact_kind={actual!r}, expected {kind!r}")

    required_service_calls = (
        "scan_devices",
        "detect_board_from_text",
        "backup_flash",
        "flash_bundle",
        "export_profile",
        "restore_profile",
        "set_names",
        "reboot_node",
        "wait_for_serial",
        "verify_node",
    )
    missing_calls = [name for name in required_service_calls if not callable(getattr(services, name, None))]
    if missing_calls:
        raise AssertionError(f"Six-board parity: common service calls missing: {missing_calls}")

    if not getattr(services, "_jarnsen_serial_arbitration_v2", False):
        raise AssertionError("Six-board parity: per-port serial arbitration is not active")
    if not getattr(services, "_jarnsen_role_write_finalize", False):
        raise AssertionError("Six-board parity: role readback/finalize layer is not active")
    if not getattr(services, "_jarnsen_name_write_finalize", False):
        raise AssertionError("Six-board parity: Long/Short-name readback/finalize layer is not active")

    for hook in (
        "load_radio_profile_settings",
        "save_radio_profile_settings",
        "validate_radio_profile_settings",
        "radio_profile_summary",
        "apply_radio_profile_overlay",
    ):
        if not callable(getattr(services, hook, None)):
            raise AssertionError(f"Six-board parity: radio-profile hook missing: {hook}")

    import native_actions
    import reference_dashboard

    for module, name in (
        (native_actions, "start_usb_log"),
        (native_actions, "start_firmware_only"),
        (reference_dashboard, "start_usb_log"),
        (reference_dashboard, "start_firmware_only"),
    ):
        if not callable(getattr(module, name, None)):
            raise AssertionError(f"Six-board parity: action missing: {module.__name__}.{name}")

    write_guard = _source("write_choice_guard.py")
    for marker in (
        "flash_button",
        "profile_only_button",
        "WRITE CHOICE GUARD UI ready flash=1 profile_only=1",
    ):
        if marker not in write_guard:
            raise AssertionError(f"Six-board parity: write guard missing marker {marker!r}")

    role_finalize = _source("role_write_finalize.py")
    for marker in ("device.role", "final-readback=1", "ROLE FINALIZE OK"):
        if marker not in role_finalize:
            raise AssertionError(f"Six-board parity: role finalization missing marker {marker!r}")

    name_finalize = _source("name_write_finalize.py")
    for marker in ("NAME FINALIZE OK", "retry-write=1", "final-readback=1"):
        if marker not in name_finalize:
            raise AssertionError(f"Six-board parity: name finalization missing marker {marker!r}")

    radio_sync = _source("radio_profile_node_sync.py")
    for command in (
        "JARNSEN_TOOL_RADIO_INFO",
        "JARNSEN_TOOL_RADIO_CAPTURE_STANDARD",
        "JARNSEN_TOOL_RADIO_SET",
        "JARNSEN_TOOL_RADIO_SELECT",
    ):
        if command not in radio_sync:
            raise AssertionError(f"Six-board parity: radio service command missing: {command}")

    v3_log = _source("v3_usb_log_stability.py")
    if 'if board_key != "repeater":' not in v3_log or "return base_start_usb_log" not in v3_log:
        raise AssertionError(
            "Six-board parity: V3 log specialization must fall back to the common all-board log action"
        )

    unified_service = _source("unified_service_v2.py")
    for marker in (
        "board_key not in runtime_services.BOARD_PROFILES",
        "USB-LOG START",
        "start_firmware_only",
        "jarnsen_serial_guard",
    ):
        if marker not in unified_service:
            raise AssertionError(f"Six-board parity: unified service missing marker {marker!r}")

    series_support = _source("wio_series.py")
    for board_key in SUPPORTED_BOARDS:
        if f'"{board_key}"' not in series_support:
            raise AssertionError(f"Six-board parity: series manual fallback missing {board_key}")
    if "6-board manual confirmation" not in series_support:
        raise AssertionError("Six-board parity: six-board series fallback is not installed")

    matrix = {
        key: {feature: "GREEN-CONTRACT" for feature in USER_FEATURES}
        for key in SUPPORTED_BOARDS
    }
    print(
        "SIX BOARD PARITY PASS · boards=6 · features="
        + str(len(USER_FEATURES))
        + " · "
        + ", ".join(services.BOARD_PROFILES[key]["label"] for key in SUPPORTED_BOARDS),
        flush=True,
    )
    return matrix
