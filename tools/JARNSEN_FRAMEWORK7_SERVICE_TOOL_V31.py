"""Framework7 v3.1.1 hotfix 2 entry point.

Loads the proven v3 launcher, installs the Framework7-native profile/live/map bridge,
adds packaged WebView runtime fixes, then applies the full-document startup fix.
"""
from __future__ import annotations

from pathlib import Path

import JARNSEN_FRAMEWORK7_SERVICE_TOOL as base
from JARNSEN_FRAMEWORK7_FEATURES import install
from JARNSEN_FRAMEWORK7_FIXES import install_fixes
from JARNSEN_FRAMEWORK7_RUNTIME_FIXES import install_runtime_fixes
from JARNSEN_FRAMEWORK7_RUNTIME_FIXES_V312 import install_runtime_fix_v312

base.APP_VERSION = "3.1.1"
install(base.LegacyBridge, base.ApiHandler)
install_fixes(base.LegacyBridge)
install_runtime_fixes(base)
install_runtime_fix_v312(base)


def _v31_self_test() -> int:
    """Validate the actual hotfix assets that the packaged WebView will load."""
    required = [
        base._resource_path("service_tool_web/index.html"),
        base._resource_path("service_tool_web/app.css"),
        base._resource_path("service_tool_web/v31.css"),
        base._resource_path("service_tool_web/app-v31.js"),
        base._resource_path("service_tool_web/vendor/framework7-bundle.min.css"),
        base._resource_path("service_tool_web/vendor/framework7-bundle.min.js"),
    ]
    missing = [str(path) for path in required if not path.exists()]
    problems: list[str] = []
    index = required[0]
    if index.exists():
        html = index.read_text(encoding="utf-8")
        if 'href="v31.css"' not in html:
            problems.append("index.html does not load v31.css")
        if 'src="app-v31.js"' not in html:
            problems.append("index.html does not load app-v31.js")
    output = Path.cwd() / "Jarnsen-Node-Service-Tool-self-test.txt"
    if missing or problems:
        detail = ["Framework7 v3.1.1 hotfix 2 self-test FAILED"]
        if missing:
            detail.extend(["Missing:", *missing])
        if problems:
            detail.extend(["Problems:", *problems])
        output.write_text("\n".join(detail) + "\n", encoding="utf-8")
        return 2
    output.write_text(
        "Framework7 v3.1.1 hotfix 2 self-test OK\n"
        "version=3.1.1\n"
        "shell=Framework7 9.1.3 / iOS theme\n"
        "ui=loopback-http + app-v31.js + v31.css\n"
        "startup_preflight=full-document + critical-assets\n"
        "features=profiles,profile-editor,provisioning,pixel-live,historical-track\n"
        "backend=hidden legacy Python service core\n",
        encoding="utf-8",
    )
    return 0


base._self_test = _v31_self_test

if __name__ == "__main__":
    raise SystemExit(base.main())
