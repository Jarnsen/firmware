from __future__ import annotations

from types import SimpleNamespace

import profile_runtime_efficiency as profile_efficiency
import radio_profile_existing_slot_reuse as reuse


def test_one_pass_profile_context_refreshes_standard_without_transaction_manager(
    monkeypatch,
) -> None:
    services = SimpleNamespace()
    monkeypatch.setattr(
        profile_efficiency._FAST_PROFILE_CONTEXT,
        "enabled",
        True,
        raising=False,
    )

    assert reuse._is_full_profile_write(services, "COM9") is True


def test_inactive_profile_context_without_transaction_manager_does_not_refresh(
    monkeypatch,
) -> None:
    services = SimpleNamespace()
    monkeypatch.setattr(
        profile_efficiency._FAST_PROFILE_CONTEXT,
        "enabled",
        False,
        raising=False,
    )

    assert reuse._is_full_profile_write(services, "COM9") is False
