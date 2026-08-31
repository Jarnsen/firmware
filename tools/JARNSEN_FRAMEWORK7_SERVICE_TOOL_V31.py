"""Framework7 v3.1.1 focus hotfix entry point.

Loads the proven v3 launcher, installs the Framework7-native profile/live/map bridge,
keeps the WebView startup fixes, adds the focused low-overhead runtime, carries
frequency-bound Jarnsen radio authorization across every profile, and exposes all
operator-facing functions of the stable Service Tool through Framework7.
"""
from __future__ import annotations

from pathlib import Path

import JARNSEN_FRAMEWORK7_SERVICE_TOOL as base
from JARNSEN_FRAMEWORK7_FEATURES import install
from JARNSEN_FRAMEWORK7_FIXES import install_fixes
from JARNSEN_FRAMEWORK7_LEGACY_COMPAT import install_legacy_compat
from JARNSEN_FRAMEWORK7_PARITY import install_parity
from JARNSEN_FRAMEWORK7_PARITY_FIXES import install_parity_fixes
from JARNSEN_FRAMEWORK7_RADIO_AUTH import install_radio_authorization
from JARNSEN_FRAMEWORK7_RUNTIME_FIXES import install_runtime_fixes
from JARNSEN_FRAMEWORK7_PERF_FOCUS import install_performance_focus
from JARNSEN_FRAMEWORK7_RUNTIME_FIXES_V312 import install_runtime_fix_v312

base.APP_VERSION = "3.1.1"
install(base.LegacyBridge, base.ApiHandler)
install_fixes(base.LegacyBridge)
install_radio_authorization(base.LegacyBridge, base.ApiHandler)
install_legacy_compat(base.LegacyBridge)
install_parity(base.LegacyBridge, base.ApiHandler)
install_parity_fixes(base.LegacyBridge)
install_runtime_fixes(base)
install_performance_focus(base)
install_runtime_fix_v312(base)


def _v31_self_test() -> int:
    """Validate the complete Framework7 assets that the packaged WebView will load."""
    required = [
        base._resource_path("service_tool_web/index.html"),
        base._resource_path("service_tool_web/app.css"),
        base._resource_path("service_tool_web/v31.css"),
        base._resource_path("service_tool_web/focus.css"),
        base._resource_path("service_tool_web/map-settings-v32.css"),
        base._resource_path("service_tool_web/radio-auth-v33.css"),
        base._resource_path("service_tool_web/parity-v35.css"),
        base._resource_path("service_tool_web/app-v31.js"),
        base._resource_path("service_tool_web/map-settings-v32.js"),
        base._resource_path("service_tool_web/radio-auth-v33.js"),
        base._resource_path("service_tool_web/legacy-compat-v34.js"),
        base._resource_path("service_tool_web/parity-v35.js"),
        base._resource_path("service_tool_web/vendor/framework7-bundle.min.css"),
        base._resource_path("service_tool_web/vendor/framework7-bundle.min.js"),
        base._resource_path("service_tool_web/vendor/leaflet.css"),
        base._resource_path("service_tool_web/vendor/leaflet.js"),
        base._resource_path("service_tool_web/vendor/mgrs.min.js"),
    ]
    missing = [str(path) for path in required if not path.exists()]
    problems: list[str] = []
    index = required[0]
    if index.exists():
        html = index.read_text(encoding="utf-8")
        for reference in (
            'href="v31.css"',
            'href="focus.css"',
            'href="map-settings-v32.css"',
            'href="radio-auth-v33.css"',
            'href="parity-v35.css"',
            'src="vendor/leaflet.js"',
            'src="vendor/mgrs.min.js"',
            'src="map-settings-v32.js"',
            'src="radio-auth-v33.js"',
            'src="app-v31.js"',
            'src="legacy-compat-v34.js"',
            'src="parity-v35.js"',
        ):
            if reference not in html:
                problems.append(f"index.html missing {reference}")
    output = Path.cwd() / "Jarnsen-Node-Service-Tool-self-test.txt"
    if missing or problems:
        detail = ["Framework7 v3.1.1 full-parity self-test FAILED"]
        if missing:
            detail.extend(["Missing:", *missing])
        if problems:
            detail.extend(["Problems:", *problems])
        output.write_text("\n".join(detail) + "\n", encoding="utf-8")
        return 2
    output.write_text(
        "Framework7 v3.1.1 full-parity self-test OK\n"
        "version=3.1.1\n"
        "shell=Framework7 9.1.3 / iOS theme\n"
        "ui=loopback-http + app-v31 + map-settings-v32 + radio-auth-v33 + legacy-compat-v34 + parity-v35\n"
        "startup_preflight=full-document + critical-assets\n"
        "performance=deduplicated-render + 7s-background-poll + 650ms-live-poll + short-state-cache\n"
        "features=profiles,profile-editor,provisioning,pixel-live,interactive-map,mgrs-point-pick,radio-settings,global-radio-authorization,serial-monitor,serial-flash,full-log-resync,diagnostic-bundle,config-snapshot,recovery,app-self-update,full-lock-policy,serial-filter-search-pause,serial-power-view,serial-session-export,ui-zoom\n"
        "radio_policy=standard-max7 + exact-A-B-max20 + duty-cycle-frequency-bound + tx-power-frequency-bound\n"
        "parity=stable-v2.2.1-operator-functions + v2.2.4-backend-fixes\n"
        "backend=hidden legacy Python service core\n",
        encoding="utf-8",
    )
    return 0


base._self_test = _v31_self_test

if __name__ == "__main__":
    raise SystemExit(base.main())
