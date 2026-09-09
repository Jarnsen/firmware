"""Wire Framework7 v3.10 profile/BLE hardening and strict state ownership."""
from __future__ import annotations

import pathlib
import sys


def replace_exact(text: str, old: str, new: str, label: str, count: int = 1) -> str:
    found = text.count(old)
    if found != count:
        raise RuntimeError(f"{label}: expected {count} anchor(s), found {found}")
    return text.replace(old, new)


def patch_entry(path: pathlib.Path) -> None:
    text = path.read_text(encoding="utf-8")
    if "install_feature_hardening" in text:
        return
    text = replace_exact(
        text,
        "from JARNSEN_FRAMEWORK7_FLASH_HARDENING import install_flash_hardening\n",
        "from JARNSEN_FRAMEWORK7_FLASH_HARDENING import install_flash_hardening\n"
        "from JARNSEN_FRAMEWORK7_FEATURE_HARDENING import install_feature_hardening\n",
        "Feature hardening import",
        2,
    )
    text = replace_exact(
        text,
        "        install_flash_hardening(base.LegacyBridge, base.ApiHandler)\n        install_runtime_fixes(base)\n",
        "        install_flash_hardening(base.LegacyBridge, base.ApiHandler)\n"
        "        install_feature_hardening(base.LegacyBridge, base.ApiHandler)\n"
        "        install_runtime_fixes(base)\n",
        "early Feature hardening install",
    )
    text = replace_exact(
        text,
        "install_flash_hardening(base.LegacyBridge, base.ApiHandler)\ninstall_runtime_fixes(base)\n",
        "install_flash_hardening(base.LegacyBridge, base.ApiHandler)\n"
        "install_feature_hardening(base.LegacyBridge, base.ApiHandler)\n"
        "install_runtime_fixes(base)\n",
        "frontend Feature hardening install",
    )
    path.write_text(text, encoding="utf-8")


def patch_state_ownership(compat_path: pathlib.Path, parity_path: pathlib.Path) -> None:
    text = compat_path.read_text(encoding="utf-8")
    if "_CallableGetAdapter" not in text:
        if "_guard_callable_mappings" in text:
            raise RuntimeError("callable mapping guard remains after adapter removal")
        if text.count("enforce_service_state_contracts(self.tool)") < 2:
            raise RuntimeError("strict state contract must guard bridge init and state collection")
    else:
        import_anchor = "from typing import Any\n"
        import_line = "from JARNSEN_FRAMEWORK7_STATE_CONTRACTS import enforce_service_state_contracts\n"
        if import_line not in text:
            if text.count(import_anchor) != 1:
                raise RuntimeError("state contract import anchor missing")
            text = text.replace(import_anchor, import_anchor + "\n" + import_line, 1)

        start = text.find("class _CallableGetAdapter:")
        end = text.find("def install_legacy_compat", start)
        if start < 0 or end < 0 or end <= start:
            raise RuntimeError("callable mapping compatibility block not found")
        text = text[:start] + text[end:]
        text = replace_exact(
            text,
            "_guard_callable_mappings(self.tool)",
            "enforce_service_state_contracts(self.tool)",
            "strict state contract hooks",
            2,
        )
        if "_CallableGetAdapter" in text or "_guard_callable_mappings" in text:
            raise RuntimeError("callable mapping adapter/guard was not fully removed")
        if text.count("enforce_service_state_contracts(self.tool)") < 2:
            raise RuntimeError("strict state contract hooks are incomplete")
        compat_path.write_text(text, encoding="utf-8")

    parity = parity_path.read_text(encoding="utf-8")
    old_import = "from JARNSEN_FRAMEWORK7_LEGACY_COMPAT import _guard_callable_mappings\n"
    new_import = "from JARNSEN_FRAMEWORK7_STATE_CONTRACTS import enforce_service_state_contracts\n"
    if old_import in parity:
        parity = replace_exact(parity, old_import, new_import, "parity state contract import")
    elif new_import not in parity:
        raise RuntimeError("parity state contract import missing")
    if "_guard_callable_mappings(tool)" in parity:
        parity = replace_exact(
            parity,
            "_guard_callable_mappings(tool)",
            "enforce_service_state_contracts(tool)",
            "parity strict state hook",
        )
    if "_guard_callable_mappings" in parity:
        raise RuntimeError("parity fixes still reference callable mapping guard")
    parity_path.write_text(parity, encoding="utf-8")


def patch_feature_http(path: pathlib.Path) -> None:
    text = path.read_text(encoding="utf-8")
    old_paths = '        if path not in {"/api/profile/action", "/api/profile/section", "/api/live/action"}:\n'
    new_paths = '        if path not in {"/api/action", "/api/profile/action", "/api/profile/section", "/api/live/action", "/api/radio-authorization"}:\n'
    if old_paths in text:
        text = replace_exact(text, old_paths, new_paths, "final POST route set")
    elif new_paths not in text:
        raise RuntimeError("final POST route set missing")

    old_dispatch = '''            if path == "/api/profile/action":\n                self._send(200, self.bridge.profile_action(payload))\n            elif path == "/api/profile/section":\n                self._send(200, self.bridge.save_profile_section(payload))\n            else:\n                self._send(200, self.bridge.live_action(payload))\n'''
    new_dispatch = '''            if path == "/api/action":\n                self._send(200, self.bridge.action(payload))\n            elif path == "/api/profile/action":\n                self._send(200, self.bridge.profile_action(payload))\n            elif path == "/api/profile/section":\n                self._send(200, self.bridge.save_profile_section(payload))\n            elif path == "/api/live/action":\n                self._send(200, self.bridge.live_action(payload))\n            else:\n                self._send(200, self.bridge.save_radio_authorization(payload))\n'''
    if old_dispatch in text:
        text = replace_exact(text, old_dispatch, new_dispatch, "final POST dispatch")
    elif new_dispatch not in text:
        raise RuntimeError("final POST dispatch missing")
    path.write_text(text, encoding="utf-8")


def patch_build(path: pathlib.Path) -> None:
    text = path.read_text(encoding="utf-8")
    compile_anchor = "        'tools/JARNSEN_FRAMEWORK7_FLASH_HARDENING.py',\n"
    compile_addition = "        'tools/JARNSEN_FRAMEWORK7_FEATURE_HARDENING.py',\n"
    if compile_addition not in text:
        if text.count(compile_anchor) != 1:
            raise RuntimeError("build Feature hardening compile anchor missing")
        text = text.replace(compile_anchor, compile_anchor + compile_addition, 1)

    flash_block = (
        "        foreach ($capability in @('serial_flash_hardware_guard','serial_flash_preflight_bundle')) {\n"
        "            if (!$service.critical.$capability) { throw \"Flash critical capability missing: $capability\" }\n"
        "        }\n"
    )
    if "profile_provision_hardware_guard" not in text:
        feature_block = (
            "        foreach ($capability in @('profile_provision_hardware_guard','profile_provision_preflight_bundle','ble_ota_source_preflight','ble_recovery_signature')) {\n"
            "            if (!$service.critical.$capability) { throw \"Feature critical capability missing: $capability\" }\n"
            "        }\n"
        )
        if text.count(flash_block) != 1:
            raise RuntimeError("build Feature hardening smoke anchor missing")
        text = text.replace(flash_block, flash_block + feature_block, 1)
    path.write_text(text, encoding="utf-8")


def main() -> None:
    root = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "tools")
    patch_entry(root / "JARNSEN_FRAMEWORK7_SERVICE_TOOL_V31.py")
    patch_state_ownership(
        root / "JARNSEN_FRAMEWORK7_LEGACY_COMPAT.py",
        root / "JARNSEN_FRAMEWORK7_PARITY_FIXES.py",
    )
    patch_feature_http(root / "JARNSEN_FRAMEWORK7_FEATURE_HARDENING.py")
    patch_build(root / "ci" / "build_framework7_service_tool.ps1")
    print("Applied Framework7 v3.10 profile/BLE hardening + strict state/API ownership")


if __name__ == "__main__":
    main()
