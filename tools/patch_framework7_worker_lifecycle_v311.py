"""Framework7 v3.11 worker lifecycle cleanup for destructive/provision actions."""
from __future__ import annotations

import pathlib
import sys


def replace_exact(text: str, old: str, new: str, label: str, count: int = 1) -> str:
    found = text.count(old)
    if found != count:
        raise RuntimeError(f"{label}: expected {count} anchor(s), found {found}")
    return text.replace(old, new)


def patch_feature(path: pathlib.Path) -> None:
    text = path.read_text(encoding="utf-8")
    if "def _clear_profile_bundle_after_worker" not in text:
        anchor = "\ndef _node_device_code(tool: Any, node_id: str) -> str:\n"
        helper = '''\ndef _clear_profile_bundle_after_worker(tool: Any) -> None:\n    """Clear profile-provision firmware state after success, failure or cancel."""\n    import threading as _threading\n\n    worker = tool.__dict__.get("worker")\n    checker = getattr(worker, "is_alive", None)\n    if not callable(checker):\n        _clear_profile_bundle(tool)\n        return\n    try:\n        active = bool(checker())\n    except Exception:\n        active = False\n    if not active:\n        _clear_profile_bundle(tool)\n        return\n\n    def wait_and_clear() -> None:\n        try:\n            joiner = getattr(worker, "join", None)\n            if callable(joiner):\n                joiner()\n        finally:\n            _clear_profile_bundle(tool)\n\n    _threading.Thread(\n        target=wait_and_clear,\n        daemon=True,\n        name="framework7-profile-bundle-cleanup",\n    ).start()\n\n'''
        if text.count(anchor) != 1:
            raise RuntimeError("profile lifecycle helper anchor missing")
        text = text.replace(anchor, helper + anchor, 1)

    old = '''        try:\n            result = previous_profile_action(self, guarded)\n            if isinstance(result, dict):\n                result["hardware_verified"] = code\n                result["preflight_bundle"] = True\n                result["preflight_port"] = port\n            return result\n        except Exception:\n            _clear_profile_bundle(self.tool)\n            raise\n'''
    new = '''        try:\n            result = previous_profile_action(self, guarded)\n            if isinstance(result, dict):\n                result["hardware_verified"] = code\n                result["preflight_bundle"] = True\n                result["preflight_port"] = port\n        except Exception:\n            _clear_profile_bundle(self.tool)\n            raise\n        _clear_profile_bundle_after_worker(self.tool)\n        return result\n'''
    if old in text:
        text = replace_exact(text, old, new, "profile worker lifecycle cleanup")
    elif new not in text:
        raise RuntimeError("profile worker lifecycle cleanup contract missing")
    path.write_text(text, encoding="utf-8")


def patch_validator(path: pathlib.Path) -> None:
    text = path.read_text(encoding="utf-8")
    marker = '        "_prepare_profile_provision_bundle(self, payload)",\n'
    additions = (
        '        "def _clear_profile_bundle_after_worker",\n'
        '        "_clear_profile_bundle_after_worker(self.tool)",\n'
        '        "def _restore_ble_bundle_after_worker",\n'
        '        "_restore_ble_bundle_after_worker(self.tool, restore)",\n'
    )
    if '"def _clear_profile_bundle_after_worker"' not in text:
        if text.count(marker) != 1:
            raise RuntimeError("hardening validator lifecycle marker missing")
        text = text.replace(marker, marker + additions, 1)

    function_marker = "def test_series_guard_immediate_exit() -> None:"
    if function_marker not in text:
        insert = '''\n\ndef test_series_guard_immediate_exit() -> None:\n    source = (ROOT / "JARNSEN_FRAMEWORK7_SERIES.py").read_text(encoding="utf-8")\n    if "if seen and not active and not alive:" in source:\n        raise AssertionError("Series guard can still miss an immediate worker failure")\n    if "if not active and not alive:" not in source:\n        raise AssertionError("Series guard has no immediate terminal-state evaluation")\n    print("OK immediate Series worker exit")\n'''
        main_anchor = "\ndef main() -> None:\n"
        if text.count(main_anchor) != 1:
            raise RuntimeError("hardening validator main anchor missing")
        text = text.replace(main_anchor, insert + main_anchor, 1)

    call_marker = "    test_series_guard_immediate_exit()\n"
    if call_marker not in text:
        build_call = "    test_build_smoke_contract()\n"
        if text.count(build_call) != 1:
            raise RuntimeError(
                "hardening validator Series guard call anchor missing: "
                f"expected 1 build-smoke call, found {text.count(build_call)}"
            )
        text = text.replace(build_call, call_marker + build_call, 1)

    path.write_text(text, encoding="utf-8")


def main() -> None:
    root = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "tools")
    patch_feature(root / "JARNSEN_FRAMEWORK7_FEATURE_HARDENING.py")
    patch_validator(root / "ci" / "validate_framework7_hardening_contracts.py")
    print("Applied Framework7 v3.11 destructive worker lifecycle cleanup")


if __name__ == "__main__":
    main()
