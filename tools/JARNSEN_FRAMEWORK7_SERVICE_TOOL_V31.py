"""Framework7 v3.1.1 entry point for the Jarnsen Node Service Tool.

Framework7 is the only presentation layer.  The cumulative, known-good v2.1.28
Service Tool behavior is the functional reference while device/service logic is
hosted headlessly and progressively extracted from the legacy module.  Newer
Framework7-only capabilities such as frequency-bound Jarnsen radio authorization
and guarded serial-series provisioning remain additive and must not regress
v2.1.28 workflows.
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
        web / "series-v37.css",
        web / "app-v31.js",
        web / "map-settings-v32.js",
        web / "radio-auth-v33.js",
        web / "legacy-compat-v34.js",
        web / "parity-v35.js",
        web / "parity-enhance-v36.js",
        web / "series-v37.js",
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
            'href="series-v37.css"',
            'data-view="series"',
            'src="vendor/leaflet.js"',
            'src="vendor/mgrs.min.js"',
            'src="map-settings-v32.js"',
            'src="radio-auth-v33.js"',
            'src="app-v31.js"',
            'src="legacy-compat-v34.js"',
            'src="parity-v35.js"',
            'src="parity-enhance-v36.js"',
            'src="series-v37.js"',
        ):
            if reference not in html:
                problems.append(f"index.html missing {reference}")

    series_js = web / "series-v37.js"
    if series_js.exists():
        source = series_js.read_text(encoding="utf-8")
        for marker in (
            "/api/series/status",
            "/api/series/action",
            "/api/series/github",
            "seriesFirmwareSource",
            "seriesTemplateSave",
            "seriesStart",
            "SHA-256",
            "Soll/Ist",
        ):
            if marker not in source:
                problems.append(f"series-v37.js missing {marker}")

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
        "ui=loopback-http + app-v31 + map-settings-v32 + radio-auth-v33 + legacy-compat-v34 + parity-v35 + parity-enhance-v36 + series-v37\n"
        "startup_preflight=full-document + critical-assets + series-v37-markers\n"
        "performance=deduplicated-render + 7s-background-poll + 650ms-live-poll + short-state-cache\n"
        "features=profiles,profile-editor,provisioning,series-provisioning,series-templates,firmware-source-selection,local-firmware-sha256,pixel-live,interactive-map,mgrs-point-pick,radio-settings,global-radio-authorization,serial-monitor,serial-flash,full-log-resync,diagnostic-bundle,config-snapshot,recovery,app-self-update,full-lock-policy,serial-filter-search-pause,serial-power-view,serial-session-export,ui-zoom\n"
        "series=repeat-names-only + latest-github-local + hardware-guard + postcondition-readback + managed-history\n"
        "radio_policy=standard-max7 + exact-A-B-max20 + duty-cycle-frequency-bound + tx-power-frequency-bound\n"
        "parity=v2.1.28-cumulative-or-improved\n"
        "backend=headless-service-core-no-tk-mainloop\n",
        encoding="utf-8",
    )
    return 0


def _cli_value(name: str, default: str = "") -> str:
    try:
        index = sys.argv.index(name)
    except ValueError:
        return default
    if index + 1 >= len(sys.argv):
        return default
    return str(sys.argv[index + 1])


def _run_backend_early() -> int:
    """Start backend mode before frontend/WebView startup is entered.

    Packaged CI previously stayed alive for minutes without ever opening /health.
    That proved the process was blocking in the common frontend/runtime import and
    install chain before base.main() could dispatch --f7-backend. Backend mode is
    split at the entry point: a tiny stdlib listener comes up immediately, then the
    API/bridge layers plus the loopback static-UI HTTP route are installed. The
    runtime module is safe to install here because its WebView/Tk startup helpers
    are only executed by _frontend/_backend; install_headless_boot replaces that
    backend immediately afterwards, so no Tk root or WebView is created.
    """
    import contextlib
    import json
    import threading
    import time
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    port_text = _cli_value("--port")
    token = _cli_value("--token")
    try:
        port = int(port_text)
    except (TypeError, ValueError):
        raise SystemExit("--f7-backend benötigt einen gültigen --port")
    if port <= 0 or not token:
        raise SystemExit("--f7-backend benötigt --port und --token")

    state: dict[str, object] = {
        "stage": "entry-listener-ready",
        "error": "",
    }

    class EntryHealthHandler(BaseHTTPRequestHandler):
        def log_message(self, *_args: object) -> None:
            return

        def do_GET(self) -> None:  # noqa: N802
            if self.path.split("?", 1)[0] != "/health":
                self.send_response(503)
                self.end_headers()
                return
            body = json.dumps(
                {
                    "ok": True,
                    "ready": False,
                    "stage": state.get("stage", "entry-starting"),
                    "error": state.get("error", ""),
                    "version": "3.1.1",
                }
            ).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    entry_server = ThreadingHTTPServer(("127.0.0.1", port), EntryHealthHandler)
    entry_server.daemon_threads = True
    entry_thread = threading.Thread(
        target=entry_server.serve_forever,
        name="framework7-entry-health",
        daemon=True,
    )
    entry_thread.start()

    try:
        state["stage"] = "import-base-api"
        import JARNSEN_FRAMEWORK7_SERVICE_TOOL as base

        state["stage"] = "import-feature-bridge"
        from JARNSEN_FRAMEWORK7_FEATURES import install
        from JARNSEN_FRAMEWORK7_FIXES import install_fixes
        from JARNSEN_FRAMEWORK7_HEADLESS_BOOT import install_headless_boot
        from JARNSEN_FRAMEWORK7_LEGACY_COMPAT import install_legacy_compat
        from JARNSEN_FRAMEWORK7_PARITY import install_parity
        from JARNSEN_FRAMEWORK7_PARITY_FIXES import install_parity_fixes
        from JARNSEN_FRAMEWORK7_RADIO_AUTH import install_radio_authorization
        from JARNSEN_FRAMEWORK7_RUNTIME_FIXES import install_runtime_fixes

        state["stage"] = "install-feature-bridge"
        base.APP_VERSION = "3.1.1"
        install(base.LegacyBridge, base.ApiHandler)
        install_fixes(base.LegacyBridge)
        install_radio_authorization(base.LegacyBridge, base.ApiHandler)
        install_legacy_compat(base.LegacyBridge)
        install_parity(base.LegacyBridge, base.ApiHandler)
        install_parity_fixes(base.LegacyBridge)
        install_runtime_fixes(base)
        install_headless_boot(base)
        state["stage"] = "handoff-headless-core"
    except Exception as exc:  # noqa: BLE001
        detail = f"{type(exc).__name__}: {exc}"
        state["stage"] = "entry-failed"
        state["error"] = detail
        with contextlib.suppress(Exception):
            (Path.cwd() / "Framework7-backend-bootstrap-error.txt").write_text(
                detail + "\n", encoding="utf-8"
            )
        deadline = time.monotonic() + 30.0
        while time.monotonic() < deadline:
            time.sleep(0.1)
        return 2

    # Release the bootstrap socket only after every backend bridge component has
    # loaded.  The headless backend immediately re-binds the same loopback port.
    entry_server.shutdown()
    entry_server.server_close()
    entry_thread.join(timeout=2.0)
    time.sleep(0.05)
    return base._backend(port, token)


# Keep CI self-test completely isolated from desktop/BLE/service imports.
if __name__ == "__main__" and "--self-test" in sys.argv:
    raise SystemExit(_early_self_test())

# Backend children must never traverse the frontend/WebView startup chain.
if __name__ == "__main__" and "--f7-backend" in sys.argv:
    raise SystemExit(_run_backend_early())

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
# Last backend override for normal frontend-spawned child processes.  The direct
# --f7-backend path above already uses the same headless implementation.
install_headless_boot(base)


def _v31_self_test() -> int:
    return _early_self_test()


base._self_test = _v31_self_test

if __name__ == "__main__":
    raise SystemExit(base.main())
