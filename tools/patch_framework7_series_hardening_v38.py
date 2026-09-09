"""Wire Series v3.8 hardening into the Framework7 build and smoke contract."""
from __future__ import annotations

import pathlib
import sys

import patch_framework7_flash_hardening_v39 as flash_v39
import patch_framework7_worker_lifecycle_v311 as lifecycle_v311
import patch_framework7_safe_close_v312 as safe_close_v312


def replace_exact(text: str, old: str, new: str, label: str, count: int = 1) -> str:
    found = text.count(old)
    if found != count:
        raise RuntimeError(f"{label}: expected {count} anchor(s), found {found}")
    return text.replace(old, new)


def patch_entry(path: pathlib.Path) -> None:
    text = path.read_text(encoding="utf-8")
    if "install_series_hardening" in text:
        return
    # The entry point has two install paths: one inside _run_backend_early() and
    # one at module scope. Match the leading newline + indentation explicitly so
    # injected imports remain syntactically inside the early try-block.
    text = replace_exact(
        text,
        "\n        from JARNSEN_FRAMEWORK7_SERIES import install_series\n",
        "\n        from JARNSEN_FRAMEWORK7_SERIES import install_series\n"
        "        from JARNSEN_FRAMEWORK7_SERIES_HARDENING import install_series_hardening\n",
        "early Series hardening import",
    )
    text = replace_exact(
        text,
        "\nfrom JARNSEN_FRAMEWORK7_SERIES import install_series\n",
        "\nfrom JARNSEN_FRAMEWORK7_SERIES import install_series\n"
        "from JARNSEN_FRAMEWORK7_SERIES_HARDENING import install_series_hardening\n",
        "frontend Series hardening import",
    )
    text = replace_exact(
        text,
        "        install_series(base.LegacyBridge, base.ApiHandler)\n        install_runtime_fixes(base)\n",
        "        install_series(base.LegacyBridge, base.ApiHandler)\n"
        "        install_series_hardening(base.LegacyBridge, base.ApiHandler)\n"
        "        install_runtime_fixes(base)\n",
        "early Series hardening install",
    )
    text = replace_exact(
        text,
        "install_series(base.LegacyBridge, base.ApiHandler)\ninstall_runtime_fixes(base)\n",
        "install_series(base.LegacyBridge, base.ApiHandler)\n"
        "install_series_hardening(base.LegacyBridge, base.ApiHandler)\n"
        "install_runtime_fixes(base)\n",
        "frontend Series hardening install",
    )
    path.write_text(text, encoding="utf-8")


def patch_series_guard(path: pathlib.Path) -> None:
    text = path.read_text(encoding="utf-8")
    old = '''def _guard(tool: Any, job_id: str) -> None:\n    deadline = time.monotonic() + 20 * 60\n    seen = False\n    while time.monotonic() < deadline:\n        job = tool.__dict__.get("_framework7_series_job")\n        if not isinstance(job, dict) or str(job.get("id") or "") != job_id:\n            return\n        active = bool(getattr(tool, "_provision_active", False))\n        alive = _worker_alive(tool)\n        seen = seen or active or alive\n        if seen and not active and not alive:\n'''
    new = '''def _guard(tool: Any, job_id: str) -> None:\n    deadline = time.monotonic() + 20 * 60\n    while time.monotonic() < deadline:\n        job = tool.__dict__.get("_framework7_series_job")\n        if not isinstance(job, dict) or str(job.get("id") or "") != job_id:\n            return\n        active = bool(getattr(tool, "_provision_active", False))\n        alive = _worker_alive(tool)\n        # The worker is started before this guard thread. If it already finished\n        # (including an immediate failure) before our first poll, evaluate the\n        # captured completion/error state now instead of waiting 20 minutes.\n        if not active and not alive:\n'''
    if old in text:
        text = replace_exact(text, old, new, "Series immediate-worker guard")
    elif new not in text:
        raise RuntimeError("Series immediate-worker guard anchor missing")
    path.write_text(text, encoding="utf-8")


def patch_series_js(path: pathlib.Path) -> None:
    text = path.read_text(encoding="utf-8")
    text = text.replace(
        "Lokales ZIP mit Manifest oder eindeutig benannte ESP32-S3 .bin verwenden.",
        "Lokales ZIP mit OTA-Manifest oder eindeutig benannte .update.bin verwenden.",
    )
    path.write_text(text, encoding="utf-8")


def insert_after(text: str, anchor: str, addition: str, label: str) -> str:
    if addition.strip() in text:
        return text
    if text.count(anchor) != 1:
        raise RuntimeError(f"{label}: expected one anchor, found {text.count(anchor)}")
    return text.replace(anchor, anchor + addition, 1)


def patch_build(path: pathlib.Path) -> None:
    text = path.read_text(encoding="utf-8")
    text = insert_after(
        text,
        "        'tools/JARNSEN_FRAMEWORK7_RUNTIME_FIXES_V312.py',\n",
        "        'tools/JARNSEN_FRAMEWORK7_SERIES.py',\n"
        "        'tools/JARNSEN_FRAMEWORK7_SERIES_HARDENING.py',\n",
        "build compile Series modules",
    )
    if "        'tools/service_tool_web/series-v37.js'" not in text:
        text = replace_exact(
            text,
            "        'tools/service_tool_web/parity-enhance-v36.js'\n",
            "        'tools/service_tool_web/parity-enhance-v36.js',\n"
            "        'tools/service_tool_web/series-v37.js'\n",
            "build JS Series check",
        )
    text = insert_after(
        text,
        "        'tools/service_tool_web/parity-enhance-v36.css',\n",
        "        'tools/service_tool_web/series-v37.css',\n",
        "build Series CSS asset",
    )
    old_refs = "'parity-v35.js','parity-enhance-v36.js'"
    if "'series-v37.js'" not in text.split("$appJs", 1)[0]:
        if old_refs not in text:
            raise RuntimeError("build index Series reference anchor missing")
        text = text.replace(old_refs, "'parity-v35.js','parity-enhance-v36.js','series-v37.css','series-v37.js'", 1)
    old_ui_refs = "'parity-v35.js','parity-enhance-v36.js','leaflet.js'"
    if old_ui_refs in text:
        text = text.replace(old_ui_refs, "'parity-v35.js','parity-enhance-v36.js','series-v37.js','leaflet.js'", 1)
    critical_anchor = "            @{ Path='/ui/parity-enhance-v36.css'; Marker='serial-enhance-tools' },\n"
    if "Path='/ui/series-v37.js'" not in text:
        text = insert_after(
            text,
            critical_anchor,
            "            @{ Path='/ui/series-v37.js'; Marker='/api/series/status' },\n"
            "            @{ Path='/ui/series-v37.css'; Marker='series-page' },\n",
            "build Series critical assets",
        )
    service_anchor = "        if ($null -eq $service.parity -or $service.parity.Count -lt 7) { throw 'v2.1.28 feature parity matrix incomplete' }\n"
    if "$seriesStatus" not in text:
        series_smoke = (
            "        $seriesStatus = Invoke-RestMethod -Uri \"http://127.0.0.1:$port/api/series/status\" -Headers $headers -TimeoutSec 20\n"
            "        if (!$seriesStatus.ok) { throw 'Series status is not healthy' }\n"
            "        if ($seriesStatus.capabilities.pre_destructive_bundle -ne $true -and $service.series.pre_destructive_bundle -ne $true) { throw 'Series pre-destructive bundle guard missing' }\n"
            "        if ($service.series.hardening -ne '3.8') { throw 'Series hardening v3.8 not installed' }\n"
            "        foreach ($capability in @('series_provisioning','series_pre_destructive_bundle','series_update_image_only')) {\n"
            "            if (!$service.critical.$capability) { throw \"Series critical capability missing: $capability\" }\n"
            "        }\n"
        )
        text = insert_after(text, service_anchor, series_smoke, "build Series API smoke")
    path.write_text(text, encoding="utf-8")


def main() -> None:
    root = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "tools")
    patch_entry(root / "JARNSEN_FRAMEWORK7_SERVICE_TOOL_V31.py")
    patch_series_guard(root / "JARNSEN_FRAMEWORK7_SERIES.py")
    patch_series_js(root / "service_tool_web" / "series-v37.js")
    patch_build(root / "ci" / "build_framework7_service_tool.ps1")
    flash_v39.patch_entry(root / "JARNSEN_FRAMEWORK7_SERVICE_TOOL_V31.py")
    flash_v39.patch_build(root / "ci" / "build_framework7_service_tool.ps1")
    lifecycle_v311.patch_feature(root / "JARNSEN_FRAMEWORK7_FEATURE_HARDENING.py")
    lifecycle_v311.patch_validator(root / "ci" / "validate_framework7_hardening_contracts.py")
    safe_close_v312.patch_runtime(root / "JARNSEN_FRAMEWORK7_RUNTIME_FIXES_V312.py")
    safe_close_v312.patch_validator(root / "ci" / "validate_framework7_hardening_contracts.py")
    print("Applied Framework7 Series/flash hardening + lifecycle/safe-close guards")


if __name__ == "__main__":
    main()
