from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest

APP_DIR = Path(__file__).resolve().parents[1]
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

import review_team_provisioning_v2 as provisioning
import transaction_flow


@pytest.fixture
def verifier(monkeypatch):
    monkeypatch.setattr(provisioning, "_INSTALLED", False)
    monkeypatch.setattr(provisioning, "_EXPECTED_JARNSEN_ROLE_BY_PORT", {})
    for name in (
        "_install_drone_contract",
        "_install_profile_stream",
        "_install_fast_backup",
    ):
        monkeypatch.setattr(provisioning, name, lambda _services: None)
    stability = types.ModuleType("profile_runtime_stability_v2")
    monkeypatch.setitem(sys.modules, "profile_runtime_stability_v2", stability)
    monkeypatch.setattr(
        transaction_flow, "_read_identity", transaction_flow._read_identity
    )
    monkeypatch.setattr(
        transaction_flow, "_verify_final_state", transaction_flow._verify_final_state
    )
    identity = types.SimpleNamespace(
        is_jarnsen=True, version="2.0.0-alpha.34", build=576
    )
    monkeypatch.setattr(provisioning, "_fast_read_identity", lambda *_args: identity)
    calls = []
    response = [""]

    def raw(port, command, **kwargs):
        calls.append((port, command))
        return response[0]

    monkeypatch.setattr(provisioning, "_raw_command", raw)
    services = types.SimpleNamespace(
        FlasherError=RuntimeError,
        BOARD_PROFILES={
            board: {"label": board}
            for board in (
                "tracker",
                "repeater",
                "heltec_v4",
                "tbeam",
                "tbeam_supreme",
                "wio",
            )
        },
        detect_board_from_text=lambda info: info.splitlines()[0],
        restore_profile=lambda *_args: None,
    )
    provisioning.install(services)
    return services, response, calls


def role_line(role, **flags):
    values = {"known": 1, "persisted": 1, "allowed": 1, "role_api": 1, **flags}
    return (
        "===JARNSEN_ROLE=== role="
        + role
        + " "
        + " ".join(f"{key}={value}" for key, value in values.items())
    )


MESHTASTIC_ROLE_BY_FUNCTION = {
    "tak": "TAK",
    "tak_tracker": "TAK_TRACKER",
    "tak_repeater": "ROUTER_LATE",
    "drone_repeater": "ROUTER_LATE",
}


def record_and_info(board="tracker", role="tak", *, metadata_role=None):
    expected_meshtastic_role = MESHTASTIC_ROLE_BY_FUNCTION[role]
    record = transaction_flow.TransactionRecord(
        "test",
        "full",
        "COM9",
        board_key=board,
        expected_role=expected_meshtastic_role,
        expected_long_name="Karsch",
        expected_short_name="K",
        expected_firmware_version="2.0.0-alpha.34",
        expected_firmware_build=576,
    )
    actual_metadata_role = (
        expected_meshtastic_role if metadata_role is None else metadata_role
    )
    info = (
        board
        + '\nOwner: Karsch (K)\nMetadata: {"role": "'
        + actual_metadata_role
        + '"}'
    )
    return record, info


@pytest.mark.parametrize(
    "board", ["tracker", "repeater", "heltec_v4", "tbeam", "tbeam_supreme", "wio"]
)
@pytest.mark.parametrize(
    "role", ["tak", "tak_tracker", "tak_repeater", "drone_repeater"]
)
def test_fresh_persistent_and_meshtastic_roles_must_both_match(
    verifier, board, role
):
    services, response, calls = verifier
    record, info = record_and_info(board, role)
    provisioning._EXPECTED_JARNSEN_ROLE_BY_PORT["COM9"] = role
    response[0] = role_line(role)
    transaction_flow._verify_final_state(services, record, info)
    assert calls == [("COM9", "JARNSEN_TOOL_ROLE_INFO")]
    assert record.final_role == MESHTASTIC_ROLE_BY_FUNCTION[role]
    assert record.final_board == board
    assert record.final_long_name == "Karsch" and record.final_short_name == "K"
    assert record.final_firmware_build == 576
    assert "COM9" not in provisioning._EXPECTED_JARNSEN_ROLE_BY_PORT


@pytest.mark.parametrize("flag", ["known", "persisted", "allowed", "role_api"])
def test_unconfirmed_persistent_role_is_rejected(verifier, flag):
    services, response, _calls = verifier
    record, info = record_and_info()
    provisioning._EXPECTED_JARNSEN_ROLE_BY_PORT["COM9"] = "tak"
    response[0] = role_line("tak", **{flag: 0})
    with pytest.raises(RuntimeError, match="Rollenprüfung"):
        transaction_flow._verify_final_state(services, record, info)


def test_actual_wrong_role_is_rejected(verifier):
    services, response, _calls = verifier
    record, info = record_and_info()
    provisioning._EXPECTED_JARNSEN_ROLE_BY_PORT["COM9"] = "tak"
    response[0] = role_line("tak_tracker")
    with pytest.raises(RuntimeError, match="Rollenprüfung"):
        transaction_flow._verify_final_state(services, record, info)


def test_persistent_role_cannot_mask_wrong_meshtastic_role(verifier):
    services, response, _calls = verifier
    record, info = record_and_info(
        board="repeater",
        role="tak_repeater",
        metadata_role="TAK_TRACKER",
    )
    provisioning._EXPECTED_JARNSEN_ROLE_BY_PORT["COM9"] = "tak_repeater"
    response[0] = role_line("tak_repeater")

    with pytest.raises(RuntimeError, match="Rolle erwartet ROUTER_LATE"):
        transaction_flow._verify_final_state(services, record, info)

    assert provisioning._EXPECTED_JARNSEN_ROLE_BY_PORT["COM9"] == "tak_repeater"


def test_persistent_role_does_not_bypass_name_verification(verifier):
    services, response, _calls = verifier
    record, info = record_and_info()
    provisioning._EXPECTED_JARNSEN_ROLE_BY_PORT["COM9"] = "tak"
    response[0] = role_line("tak")
    with pytest.raises(RuntimeError, match="Gerätenamen"):
        transaction_flow._verify_final_state(
            services, record, info.replace("Karsch", "Wrong")
        )
    assert provisioning._EXPECTED_JARNSEN_ROLE_BY_PORT["COM9"] == "tak"


def test_legacy_role_still_requires_matching_metadata(verifier):
    services, _response, calls = verifier
    record, info = record_and_info()
    with pytest.raises(RuntimeError, match="Rolle erwartet"):
        transaction_flow._verify_final_state(services, record, info)
    assert calls == []
