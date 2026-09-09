"""Wire Framework7 v3.10 profile/BLE hardening into runtime and build smoke tests."""
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


def patch_build(path: pathlib.Path) -> None:
    text = path.read_text(encoding="utf-8")
    compile_anchor = "        'tools/JARNSEN_FRAMEWORK7_FLASH_HARDENING.py',\n"
    compile_addition = "        'tools/JARNSEN_FRAMEWORK7_FEATURE_HARDENING.py',\n"
    if compile_addition not in text:
        if text.count(compile_anchor) != 1:
            raise RuntimeError("build Feature hardening compile anchor missing")
        text = text.replace(compile_anchor, compile_anchor + compile_addition, 1)

    # v3.9 adds this capability block. Put the feature assertions immediately after it.
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
    patch_build(root / "ci" / "build_framework7_service_tool.ps1")
    print("Applied Framework7 v3.10 profile/BLE feature hardening wiring")


if __name__ == "__main__":
    main()
