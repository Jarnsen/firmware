"""Wire generic serial flash/recovery hardening into the Framework7 package."""
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
    if "install_flash_hardening" in text:
        return
    text = replace_exact(
        text,
        "from JARNSEN_FRAMEWORK7_SERIES_HARDENING import install_series_hardening\n",
        "from JARNSEN_FRAMEWORK7_SERIES_HARDENING import install_series_hardening\n"
        "from JARNSEN_FRAMEWORK7_FLASH_HARDENING import install_flash_hardening\n",
        "Flash hardening import",
        2,
    )
    text = replace_exact(
        text,
        "        install_series_hardening(base.LegacyBridge, base.ApiHandler)\n        install_runtime_fixes(base)\n",
        "        install_series_hardening(base.LegacyBridge, base.ApiHandler)\n"
        "        install_flash_hardening(base.LegacyBridge, base.ApiHandler)\n"
        "        install_runtime_fixes(base)\n",
        "early Flash hardening install",
    )
    text = replace_exact(
        text,
        "install_series_hardening(base.LegacyBridge, base.ApiHandler)\ninstall_runtime_fixes(base)\n",
        "install_series_hardening(base.LegacyBridge, base.ApiHandler)\n"
        "install_flash_hardening(base.LegacyBridge, base.ApiHandler)\n"
        "install_runtime_fixes(base)\n",
        "frontend Flash hardening install",
    )
    path.write_text(text, encoding="utf-8")


def patch_build(path: pathlib.Path) -> None:
    text = path.read_text(encoding="utf-8")
    marker = "        'tools/JARNSEN_FRAMEWORK7_SERIES_HARDENING.py',\n"
    addition = "        'tools/JARNSEN_FRAMEWORK7_FLASH_HARDENING.py',\n"
    if addition not in text:
        if text.count(marker) != 1:
            raise RuntimeError("build Flash hardening compile anchor missing")
        text = text.replace(marker, marker + addition, 1)
    capability_anchor = "        foreach ($capability in @('series_provisioning','series_pre_destructive_bundle','series_update_image_only')) {\n"
    if "serial_flash_hardware_guard" not in text:
        addition = (
            "        foreach ($capability in @('serial_flash_hardware_guard','serial_flash_preflight_bundle')) {\n"
            "            if (!$service.critical.$capability) { throw \"Flash critical capability missing: $capability\" }\n"
            "        }\n"
        )
        if text.count(capability_anchor) != 1:
            raise RuntimeError("build Flash hardening status anchor missing")
        block_end = "        }\n"
        start = text.index(capability_anchor)
        end = text.index(block_end, start) + len(block_end)
        text = text[:end] + addition + text[end:]
    path.write_text(text, encoding="utf-8")


def main() -> None:
    root = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "tools")
    patch_entry(root / "JARNSEN_FRAMEWORK7_SERVICE_TOOL_V31.py")
    patch_build(root / "ci" / "build_framework7_service_tool.ps1")
    print("Applied Framework7 serial flash/recovery hardening wiring")


if __name__ == "__main__":
    main()
