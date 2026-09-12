from __future__ import annotations

import sys
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

FINAL_FEATURES = (
    "device_session",
    "transaction_resume",
    "profile_contract",
    "profile_final_gate",
    "system_diagnostics",
    "artifact_validation",
    "recovery_probe",
    "series_report",
)


def _emit(message: str) -> None:
    try:
        import diagnostics
        diagnostics._emit(message)
    except Exception:
        pass


def _source_has(name: str, markers: tuple[str, ...]) -> None:
    path = Path(__file__).with_name(name)
    if not path.exists():
        if getattr(sys, "frozen", False):
            return
        raise AssertionError(f"Final hardening contract: source missing {name}")
    text = path.read_text(encoding="utf-8", errors="replace")
    for marker in markers:
        if marker not in text:
            raise AssertionError(
                f"Final hardening contract: {name} missing marker {marker!r}"
            )


def validate(services: Any) -> dict[str, dict[str, str]]:
    missing = [key for key in SUPPORTED_BOARDS if key not in services.BOARD_PROFILES]
    if missing:
        raise AssertionError(f"Final hardening contract: board profiles missing {missing}")

    required_flags = (
        "_jarnsen_device_core_v1",
        "_jarnsen_transaction_flow_v1",
        "_jarnsen_transaction_profile_verify",
        "_jarnsen_profile_contract_v2",
        "_jarnsen_system_diagnostics_v1",
        "_jarnsen_artifact_guard_v1",
        "_jarnsen_recovery_probe_v1",
        "_jarnsen_series_report_v1",
        "_jarnsen_reconnect_identity_guard",
        "_jarnsen_postflash_hardening",
        "_jarnsen_supreme_bootloader_hardening",
    )
    for flag in required_flags:
        if not bool(getattr(services, flag, False)):
            raise AssertionError(f"Final hardening contract: runtime layer missing {flag}")
    if not bool(getattr(services.GitHubFirmwareClient, "_jarnsen_unified_release_resolver", False)):
        raise AssertionError("Final hardening contract: GitHub release resolver is not active")

    required_calls = (
        "board_capabilities",
        "flash_transaction_resume_plan",
        "ensure_profile_contract",
        "check_profile_compatibility",
        "diff_profile_to_node",
        "verify_written_profile",
        "run_system_check",
        "validate_firmware_bundle",
        "recovery_probe",
        "series_report_summary",
        "wait_for_node_ready",
        "finish_supreme_application_start",
    )
    for name in required_calls:
        if not callable(getattr(services, name, None)):
            raise AssertionError(f"Final hardening contract: service hook missing {name}")

    matrix: dict[str, dict[str, str]] = {}
    for key in SUPPORTED_BOARDS:
        capability = services.board_capabilities(key)
        if str(getattr(capability, "key", "")) != key:
            raise AssertionError(f"Final hardening contract: capability mismatch for {key}")
        profile = services.BOARD_PROFILES[key]
        kind = str(profile.get("artifact_kind") or "esp32").lower()
        expected_transport = "uf2" if kind == "uf2" else "esptool"
        if str(getattr(capability, "flash_transport", "")) != expected_transport:
            raise AssertionError(
                f"Final hardening contract: {key} transport="
                f"{getattr(capability, 'flash_transport', '')!r}, expected {expected_transport!r}"
            )
        matrix[key] = {feature: "GREEN-CONTRACT" for feature in FINAL_FEATURES}

    _source_has(
        "transaction_flow.py",
        ("profile_verify", "profile-contract-final-gate=1", "selected-role-profile-verify=1"),
    )
    _source_has(
        "artifact_guard.py",
        ("ARTIFACT GUARD PASS", "SHA256", "image-magic=1", "board-gate=1"),
    )
    _source_has(
        "unified_release_resolver.py",
        ("package-manifest.json", "source_sha", "Firmwaregröße", "legacy-actions-ota=1"),
    )
    _source_has(
        "recovery_mode.py",
        ("esp-bootloader-ambiguous", "UF2", "read-only-probe=1", "ambiguous-flash-block=1"),
    )
    _source_has(
        "series_report.py",
        ("SERIES REPORT BEGIN", "SERIES REPORT SUCCESS", "SERIES REPORT FAIL", "transaction-resume=1"),
    )
    _source_has(
        "reconnect_identity_guard.py",
        ("vidpid-only-rebind=0", "multi-esp-ambiguity-block=1", "same-port-reuse-check=1"),
    )
    _source_has(
        "postflash_hardening.py",
        ("hash-before-reset=1", "flash-retry-after-reset=0", "application-ready-gate=1"),
    )
    _source_has(
        "supreme_bootloader_hardening.py",
        ("forced-1200=0", "post-reset-rom-probe=1", "physical-id-reconnect=1"),
    )

    services._jarnsen_final_hardening_contract_v1 = True
    _emit(
        "FINAL HARDENING CONTRACT PASS boards=6 features="
        + str(len(FINAL_FEATURES))
        + " transaction-profile-gate=1 artifact-guard=1 recovery=1 series-report=1 "
        + "physical-reconnect-id=1 postflash-ready=1 supreme-usb-reset=1"
    )
    print(
        "FINAL HARDENING CONTRACT PASS · boards=6 · features="
        + str(len(FINAL_FEATURES)),
        flush=True,
    )
    return matrix


def install(services: Any) -> None:
    if getattr(services, "_jarnsen_final_hardening_contract_v1", False):
        return

    # These are deliberately final runtime guards. port_reconnect_hardening has
    # already captured the ordinary logical-port I/O boundaries when this module
    # is installed; the physical identity guard now replaces only reconnect
    # selection, and the Supreme layer replaces only native USB bootloader entry.
    from reconnect_identity_guard import install as install_reconnect_identity_guard
    install_reconnect_identity_guard(services)

    from supreme_bootloader_hardening import install as install_supreme_bootloader_hardening
    install_supreme_bootloader_hardening(services)

    services.final_hardening_matrix = validate(services)
