from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest
import radio_profile_existing_slot_reuse as reuse
import radio_profile_node_sync as node_sync

COMPLETE = (
    "===JARNSEN_RADIO=== active={active} slots=3 " "standard=1 jarnsen1=1 jarnsen2=1"
)


def _runtime():
    return SimpleNamespace(wait_for_serial=Mock())


def _install_with_fake_radio(base_writer: Mock, *, fail_targets=(), fail_restore=False):
    state = {"active": "standard", "standard_calls": 0}
    selections: list[str] = []

    def select(_port, target, _services):
        selections.append(target)
        if target == "standard":
            state["standard_calls"] += 1
            if fail_restore and state["standard_calls"] >= 2:
                raise RuntimeError("restore unavailable")
        if target in fail_targets:
            raise RuntimeError(f"select {target} failed")
        state["active"] = target

    def raw(_port, command, *, expected, timeout=10.0):
        assert command == "JARNSEN_TOOL_RADIO_INFO"
        return COMPLETE.format(active=state["active"])

    services = _runtime()
    with patch.object(node_sync, "_write_firmware_slots", base_writer), patch.object(
        node_sync, "_read_active_profile", Mock()
    ):
        reuse.install(services)
        writer = node_sync._write_firmware_slots

    return services, writer, selections, select, raw


def test_complete_existing_slots_skip_radio_set_and_restore_active() -> None:
    base_writer = Mock()
    services, writer, selections, select, raw = _install_with_fake_radio(base_writer)

    with patch.object(node_sync, "_select_raw", side_effect=select), patch.object(
        node_sync, "_raw_command", side_effect=raw
    ):
        writer("COM9", {}, "standard", "EU_868", services)

    assert selections == ["standard", "jarnsen1", "jarnsen2", "standard"]
    base_writer.assert_not_called()


def test_full_profile_refreshes_standard_before_reusing_jarnsen_slots() -> None:
    base_writer = Mock()
    services, writer, selections, select, raw_info = _install_with_fake_radio(
        base_writer
    )
    services.flash_transactions = SimpleNamespace(
        active=lambda _port: SimpleNamespace(kind="full")
    )
    commands: list[str] = []

    def raw(_port, command, *, expected, timeout=10.0):
        commands.append(command)
        if command == "JARNSEN_TOOL_RADIO_CAPTURE_STANDARD":
            assert expected == node_sync.RADIO_OK_MARKER
            return "===JARNSEN_RADIO_OK=== action=capture profile=standard"
        return raw_info(_port, command, expected=expected, timeout=timeout)

    with patch.object(node_sync, "_select_raw", side_effect=select), patch.object(
        node_sync, "_raw_command", side_effect=raw
    ):
        writer("COM9", {}, "standard", "UNSET", services)

    assert commands[:2] == [
        "JARNSEN_TOOL_RADIO_INFO",
        "JARNSEN_TOOL_RADIO_CAPTURE_STANDARD",
    ]
    assert commands.count("JARNSEN_TOOL_RADIO_CAPTURE_STANDARD") == 1
    assert selections == ["standard", "jarnsen1", "jarnsen2", "standard"]
    base_writer.assert_not_called()


def test_full_profile_capture_failure_is_fail_closed_before_slot_select() -> None:
    base_writer = Mock()
    services, writer, selections, select, raw_info = _install_with_fake_radio(
        base_writer
    )
    services.flash_transactions = SimpleNamespace(
        active=lambda _port: SimpleNamespace(kind="full")
    )

    def raw(_port, command, *, expected, timeout=10.0):
        if command == "JARNSEN_TOOL_RADIO_CAPTURE_STANDARD":
            raise RuntimeError("capture unavailable")
        return raw_info(_port, command, expected=expected, timeout=timeout)

    with patch.object(node_sync, "_select_raw", side_effect=select), patch.object(
        node_sync, "_raw_command", side_effect=raw
    ):
        with pytest.raises(RuntimeError, match="capture unavailable"):
            writer("COM9", {}, "standard", "UNSET", services)

    assert selections == []
    base_writer.assert_not_called()


def test_first_radio_info_write_timeout_retries_before_slot_fallback() -> None:
    base_writer = Mock()
    services, writer, selections, select, raw_ok = _install_with_fake_radio(base_writer)
    calls = {"count": 0}

    def raw(_port, command, *, expected, timeout=10.0):
        calls["count"] += 1
        if calls["count"] == 1:
            raise node_sync.serial.SerialTimeoutException("Write timeout")
        return raw_ok(_port, command, expected=expected, timeout=timeout)

    with patch.object(node_sync, "_select_raw", side_effect=select), patch.object(
        node_sync, "_raw_command", side_effect=raw
    ):
        writer("COM9", {}, "standard", "EU_868", services)

    services.wait_for_serial.assert_called_once_with("COM9", timeout=20)
    assert selections == ["standard", "jarnsen1", "jarnsen2", "standard"]
    base_writer.assert_not_called()


def test_active_profile_reader_retries_info_after_single_reboot() -> None:
    base_writer = Mock()
    services = _runtime()
    replies = [
        node_sync.serial.SerialTimeoutException("Write timeout"),
        COMPLETE.format(active="standard"),
    ]

    with patch.object(node_sync, "_write_firmware_slots", base_writer), patch.object(
        node_sync, "_read_active_profile", Mock()
    ), patch.object(node_sync, "_reboot_to_raw") as reboot, patch.object(
        node_sync, "_raw_command", side_effect=replies
    ) as raw:
        reuse.install(services)
        reader = node_sync._read_active_profile
        active = reader("COM9", services)

    assert active == "standard"
    reboot.assert_called_once_with("COM9", services)
    assert raw.call_count == 2
    services.wait_for_serial.assert_called_once_with("COM9", timeout=20)


def test_failed_j1_select_still_checks_j2_before_write_fallback() -> None:
    base_writer = Mock()
    services, writer, selections, select, raw = _install_with_fake_radio(
        base_writer,
        fail_targets={"jarnsen1"},
    )

    with patch.object(node_sync, "_select_raw", side_effect=select), patch.object(
        node_sync, "_raw_command", side_effect=raw
    ):
        writer("COM9", {"selected": "standard"}, "standard", "EU_868", services)

    assert selections == ["standard", "jarnsen1", "jarnsen2", "standard"]
    base_writer.assert_called_once_with(
        "COM9",
        {"selected": "standard"},
        "standard",
        "EU_868",
        services,
    )


def test_restore_failure_is_fail_closed_before_radio_set() -> None:
    base_writer = Mock()
    services, writer, selections, select, raw = _install_with_fake_radio(
        base_writer,
        fail_targets={"jarnsen1"},
        fail_restore=True,
    )

    with patch.object(node_sync, "_select_raw", side_effect=select), patch.object(
        node_sync, "_raw_command", side_effect=raw
    ):
        with pytest.raises(RuntimeError, match="RADIO_SLOT_REUSE_RESTORE_FAILED"):
            writer("COM9", {}, "standard", "EU_868", services)

    assert "jarnsen2" in selections
    base_writer.assert_not_called()


def test_incomplete_slot_declaration_uses_existing_writer_without_select() -> None:
    base_writer = Mock()
    services = _runtime()
    with patch.object(node_sync, "_write_firmware_slots", base_writer), patch.object(
        node_sync, "_read_active_profile", Mock()
    ):
        reuse.install(services)
        writer = node_sync._write_firmware_slots

    incomplete = (
        "===JARNSEN_RADIO=== active=standard slots=2 "
        "standard=1 jarnsen1=1 jarnsen2=0"
    )
    with patch.object(node_sync, "_raw_command", return_value=incomplete), patch.object(
        node_sync, "_select_raw"
    ) as select:
        writer("COM9", {}, "standard", "EU_868", services)

    select.assert_not_called()
    base_writer.assert_called_once()
