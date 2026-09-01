"""Framework7 v3.1.1 entry point for the Jarnsen Node Service Tool.

Framework7 is the only presentation layer.  The cumulative, known-good v2.1.28
Service Tool behavior is the functional reference while device/service logic is
hosted headlessly and progressively extracted from the legacy module.  Newer
Framework7-only capabilities such as frequency-bound Jarnsen radio authorization
remain additive and must not regress v2.1.28 workflows.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path


def _resource_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return Path(__file__).resolve().parent


def _early_self_test() -> int:
    """Validate packaged Framework7 assets without starting device services."""
    root = _resource_root()
    web = root / "service_tool_web"
    required = [
        web / "index.html",
        web / "app.css",
        web / "v31.css",
        web / "focus.css",
        web / "map-settings-v32.css",
        web / "radio-auth-v33.css",
        web / "parity-v35.css",
        web / "parity-enhance-v36.css",
        web / "app-v31.js",
        web / "map-settings-v32.js",
        web / "radio-auth-v33.js",
        web / "legacy-compat-v34.js",
        web / "parity-v35.js",
        web / "parity-enhance-v36.js",
        web / "vendor" / "framework7-bundle.min.css",
        web / "vendor" / "framework7-bundle.min.js",
        web / "vendor" / "leaflet.css",
        web / "vendor" / "leaflet.js",
        web / "vendor" / "mgrs.min.js",
    ]
    missing = [str(path) for path in required if not path.exists()]
    problems: list[str] = []
    index = web / "index.html"
    if index.exists():
        html = index.read_text(encoding="utf-8")
        for reference in (
            'href="v31.css"',
            'href="focus.css"',
            'href="map-settings-v32.css"',
            'href="radio-auth-v33.css"',
            'href="parity-v35.css"',
            'href="parity-enhance-v36.css"',
            'src="vendor/leaflet.js"',
            'src="vendor/mgrs.min.js"',
            'src="map-settings-v32.js"',
            'src="radio-auth-v33.js"',
            'src="app-v31.js"',
            'src="legacy-compat-v34.js"',
            'src="parity-v35.js"',
            'src="parity-enhance-v36.js"',
        ):
            if reference not in html:
                problems.append(f"index.html missing {reference}")
    output = Path.cwd() / "Jarnsen-Node-Service-Tool-self-test.txt"
    if missing or problems:
        detail = ["Framework7 v3.1.1 v2.1.28-parity self-test FAILED"]
        if missing:
            detail.extend(["Missing:", *missing])
        if problems:
            detail.extend(["Problems:", *problems])
        output.write_text("\n".join(detail) + "\n", encoding="utf-8")
        return 2
    output.write_text(
        "Framework7 v3.1.1 v2.1.28-parity self-test OK\n"
        "version=3.1.1\n"
        "functional_reference=v2.1.28-cumulative\n"
        "shell=Framework7 9.1.3 / iOS theme\n"
        "ui=loopback-http + app-v31 + map-settings-v32 + radio-auth-v33 + legacy-compat-v34 + parity-v35 + parity-enhance-v36\n"
        "startup_preflight=full-document + critical-assets\n"
        "performance=deduplicated-render + 7s-background-poll + 650ms-live-poll + short-state-cache\n"
        "features=profiles,profile-editor,provisioning,pixel-live,interactive-map,mgrs-point-pick,radio-settings,global-radio-authorization,serial-monitor,serial-flash,full-log-resync,diagnostic-bundle,config-snapshot,recovery,app-self-update,full-lock-policy,serial-filter-search-pause,serial-power-view,serial-session-export,ui-zoom\n"
        "radio_policy=standard-max7 + exact-A-B-max20 + duty-cycle-frequency-bound + tx-power-frequency-bound\n"
        "parity=v2.1.28-cumulative-or-improved\n"
        "backend=headless-service-core-no-tk-mainloop\n",
        encoding="utf-8",
    )
    return 0


# Keep CI self-test completely isolated from desktop/BLE/service imports.
if __name__ == "__main__" and "--self-test" in sys.argv:
    raise SystemExit(_early_self_test())

import JARNSEN_FRAMEWORK7_SERVICE_TOOL as base
from JARNSEN_FRAMEWORK7_FEATURES import install
from JARNSEN_FRAMEWORK7_FIXES import install_fixes
from JARNSEN_FRAMEWORK7_HEADLESS_BOOT import install_headless_boot
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
# Last backend override: the process listens first, then constructs the headless
# service core.  No Tk root or legacy mainloop is created.
install_headless_boot(base)


def _v31_self_test() -> int:
    return _early_self_test()


base._self_test = _v31_self_test

if __name__ == "__main__":
    raise SystemExit(base.main())
