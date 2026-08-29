"""Framework7 v3.1 entry point.

Loads the proven v3 launcher, installs the Framework7-native profile/live/map bridge,
and then delegates startup to the original launcher.
"""
from __future__ import annotations

from pathlib import Path

import JARNSEN_FRAMEWORK7_SERVICE_TOOL as base
from JARNSEN_FRAMEWORK7_FEATURES import install
from JARNSEN_FRAMEWORK7_FIXES import install_fixes

base.APP_VERSION = "3.1.0"
install(base.LegacyBridge, base.ApiHandler)
install_fixes(base.LegacyBridge)


def _v31_self_test() -> int:
    """Validate the actual v3.1 assets that the packaged WebView will load."""
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
        detail = ["Framework7 v3.1 self-test FAILED"]
        if missing:
            detail.extend(["Missing:", *missing])
        if problems:
            detail.extend(["Problems:", *problems])
        output.write_text("\n".join(detail) + "\n", encoding="utf-8")
        return 2
    output.write_text(
        "Framework7 v3.1 self-test OK\n"
        "version=3.1.0\n"
        "shell=Framework7 9.1.3 / iOS theme\n"
        "ui=app-v31.js + v31.css\n"
        "features=profiles,profile-editor,provisioning,pixel-live,historical-track\n"
        "backend=legacy Python service core\n",
        encoding="utf-8",
    )
    return 0


base._self_test = _v31_self_test

if __name__ == "__main__":
    raise SystemExit(base.main())
