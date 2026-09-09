"""Regression checks for Framework7 headless state ownership."""
from __future__ import annotations

import pathlib
import sys
from types import SimpleNamespace

TOOLS = pathlib.Path(__file__).resolve().parents[1]
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

from JARNSEN_FRAMEWORK7_HEADLESS_CORE import build_headless_tool
from JARNSEN_FRAMEWORK7_STATE_CONTRACTS import enforce_service_state_contracts


class _FakeRepository:
    def scan_logs(self) -> None:
        return None


class _FakeServiceTool:
    def _load_config_profile_store(self) -> dict[str, object]:
        return {
            "schema": 1,
            "authorized_915": {"a_mhz": "", "b_mhz": ""},
            "profiles": [{"name": "CI profile"}],
        }


class _BrokenCallable:
    def __call__(self, _key: str) -> dict[str, object]:
        return {}


def _fake_legacy() -> object:
    return SimpleNamespace(
        ServiceTool=_FakeServiceTool,
        NodeRepository=_FakeRepository,
        output_directory=lambda: pathlib.Path.cwd(),
    )


def _expect_runtime_error(callback: object, marker: str) -> None:
    try:
        callback()
    except RuntimeError as exc:
        if marker not in str(exc):
            raise AssertionError(f"Expected {marker!r} in error, got: {exc}") from exc
    else:
        raise AssertionError(f"Expected RuntimeError containing {marker!r}")


def main() -> int:
    tool = build_headless_tool(_fake_legacy())
    try:
        assert isinstance(tool.node_sync_state_v2132, dict)
        assert not callable(tool.node_sync_state_v2132)
        assert isinstance(tool.config_profile_store, dict)
        assert not callable(tool.config_profile_store)
        assert tool.config_profile_store["profiles"][0]["name"] == "CI profile"
        assert len(tool.config_profile_store["profiles"]) >= 4

        original_store = tool.config_profile_store
        original_sync = tool.node_sync_state_v2132
        enforce_service_state_contracts(tool)
        assert tool.config_profile_store is original_store
        assert tool.node_sync_state_v2132 is original_sync

        saved = tool.config_profile_store
        tool.config_profile_store = lambda: saved
        enforce_service_state_contracts(tool)
        assert tool.config_profile_store is saved
        assert not callable(tool.config_profile_store)

        tool.node_sync_state_v2132 = _BrokenCallable()
        _expect_runtime_error(
            lambda: enforce_service_state_contracts(tool),
            "node_sync_state_v2132",
        )

        tool.node_sync_state_v2132 = {}
        tool.config_profile_store = lambda: "not-a-mapping"
        _expect_runtime_error(
            lambda: enforce_service_state_contracts(tool),
            "config_profile_store",
        )

        tool.config_profile_store = {"schema": 1, "profiles": "wrong"}
        _expect_runtime_error(
            lambda: enforce_service_state_contracts(tool),
            "config_profile_store.profiles",
        )
    finally:
        tool.destroy()

    compat = (TOOLS / "JARNSEN_FRAMEWORK7_LEGACY_COMPAT.py").read_text(encoding="utf-8")
    parity = (TOOLS / "JARNSEN_FRAMEWORK7_PARITY_FIXES.py").read_text(encoding="utf-8")
    for name, source in (("legacy compat", compat), ("parity fixes", parity)):
        if "_CallableGetAdapter" in source or "_guard_callable_mappings" in source:
            raise AssertionError(f"{name} still references the legacy callable mapping adapter/guard")
    if compat.count("enforce_service_state_contracts(self.tool)") < 2:
        raise AssertionError("LegacyBridge does not enforce concrete mapping state at init and state collection")
    if "enforce_service_state_contracts(tool)" not in parity:
        raise AssertionError("Parity fixes do not enforce concrete mapping state")

    print("Framework7 state contracts OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
