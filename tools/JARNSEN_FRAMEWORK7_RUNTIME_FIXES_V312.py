"""Framework7 startup preflight for the packaged desktop shell.

Validates the full start document plus all critical locally bundled assets before
WebView2 opens. This catches packaging errors as a clear startup error instead of
showing a blank browser page. The backend bootstrap deliberately avoids building
the old hidden Tk presentation tree; Framework7 owns presentation and the legacy
module is retained only as a temporary source of service logic while that logic is
moved into headless components.
"""
from __future__ import annotations

import contextlib
import json
import os
import secrets
import subprocess
import sys
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any


def install_runtime_fix_v312(base: Any) -> None:
    def _get(url: str, *, timeout: float = 8.0) -> tuple[int, str, bytes]:
        request = urllib.request.Request(url, headers={"Cache-Control": "no-cache"})
        with urllib.request.urlopen(request, timeout=timeout) as response:
            data = response.read()
            status = int(getattr(response, "status", 200) or 200)
            content_type = str(response.headers.get("Content-Type") or "")
            return status, content_type, data

    def _validate_ui(base_url: str, index_url: str) -> None:
        status, content_type, body = _get(index_url)
        html = body.decode("utf-8", errors="replace")
        if status != 200:
            raise RuntimeError(f"Framework7 Startseite liefert HTTP {status}")
        if "text/html" not in content_type.lower():
            raise RuntimeError(f"Framework7 Startseite hat falschen Content-Type: {content_type}")

        required_refs = (
            'vendor/framework7-bundle.min.css',
            'vendor/framework7-bundle.min.js',
            'vendor/leaflet.css',
            'vendor/leaflet.js',
            'vendor/mgrs.min.js',
            'v31.css',
            'focus.css',
            'map-settings-v32.css',
            'map-settings-v32.js',
            'radio-auth-v33.css',
            'radio-auth-v33.js',
            'app-v31.js',
            'legacy-compat-v34.js',
            'parity-v35.css',
            'parity-v35.js',
            'parity-enhance-v36.css',
            'parity-enhance-v36.js',
        )
        missing_refs = [ref for ref in required_refs if ref not in html]
        if missing_refs:
            raise RuntimeError("Framework7 Startseite ist unvollständig: " + ", ".join(missing_refs))

        assets = (
            ("/ui/vendor/framework7-bundle.min.css", "text/css", None),
            ("/ui/vendor/framework7-bundle.min.js", "javascript", b"Framework7"),
            ("/ui/vendor/leaflet.css", "text/css", b"leaflet"),
            ("/ui/vendor/leaflet.js", "javascript", b"Leaflet"),
            ("/ui/vendor/mgrs.min.js", "javascript", b"forward"),
            ("/ui/v31.css", "text/css", None),
            ("/ui/focus.css", "text/css", None),
            ("/ui/map-settings-v32.css", "text/css", b"interactive-map"),
            ("/ui/map-settings-v32.js", "javascript", b"OpenTopoMap"),
            ("/ui/radio-auth-v33.css", "text/css", b"radio-auth-global-card"),
            ("/ui/radio-auth-v33.js", "javascript", b"/api/radio-authorization"),
            ("/ui/app-v31.js", "javascript", b"theme: 'ios'"),
            ("/ui/legacy-compat-v34.js", "javascript", b"usb-log"),
            ("/ui/parity-v35.css", "text/css", b"parity-overlay"),
            ("/ui/parity-v35.js", "javascript", b"/api/service-status"),
            ("/ui/parity-enhance-v36.css", "text/css", b"serial-enhance-tools"),
            ("/ui/parity-enhance-v36.js", "javascript", b"serial_monitor_export"),
        )
        for path, expected_type, marker in assets:
            asset_status, asset_type, asset_body = _get(base_url + path)
            if asset_status != 200 or not asset_body:
                raise RuntimeError(f"Framework7 Asset konnte nicht geladen werden: {path}")
            if expected_type not in asset_type.lower():
                raise RuntimeError(f"Framework7 Asset hat falschen Content-Type: {path} ({asset_type})")
            if marker and marker.lower() not in asset_body.lower():
                raise RuntimeError(f"Framework7 Asset ist unvollständig: {path}")

    def _backend(port: int, token: str) -> int:
        """Start the service core without constructing the hidden legacy UI.

        The old Tk widget tree was the dominant bootstrap cost and is not part of
        the Framework7 product.  Keep the root only as a temporary scheduler for
        service methods that have not yet been extracted; do not construct the
        old pages, map, dashboard or control panes.  Repository/profile state is
        initialized explicitly so read-only Framework7 APIs remain available.
        """
        import JARNSEN_NODE_SERVICE_TOOL as legacy

        if hasattr(legacy.ServiceTool, "_install_mac_shell_v220"):
            legacy.ServiceTool._install_mac_shell_v220 = lambda self: None

        messagebox = getattr(legacy, "messagebox", None)
        saved_dialogs: dict[str, Any] = {}
        if messagebox is not None:
            defaults = {
                "showinfo": None,
                "showwarning": None,
                "showerror": None,
                "askokcancel": True,
                "askyesno": True,
                "askretrycancel": False,
                "askquestion": "yes",
                "askyesnocancel": True,
            }
            for name, result in defaults.items():
                function = getattr(messagebox, name, None)
                if function is None:
                    continue
                saved_dialogs[name] = function
                setattr(messagebox, name, lambda *_a, _result=result, **_k: _result)

        # Constructor-only deferral.  _build_ui is intentionally included: the
        # Framework7 shell must not pay for or depend on the old hidden widget
        # hierarchy.  Service/data methods remain present on the instance.
        deferred: dict[str, Any] = {}
        deferred_names = (
            "_build_ui",
            "refresh_ports",
            "refresh_nodes",
            "apply_theme",
            "render_dashboard",
            "render_track_map",
            "refresh_all_nodes_overview",
            "render_node_tiles_v2132",
        )
        for name in deferred_names:
            function = getattr(legacy.ServiceTool, name, None)
            if function is not None:
                deferred[name] = function
                setattr(legacy.ServiceTool, name, lambda self, *_a, **_k: None)
        repository_cls = getattr(legacy, "NodeRepository", None)
        repository_scan = getattr(repository_cls, "scan_logs", None) if repository_cls else None
        if repository_scan is not None:
            deferred["repository_scan_logs"] = repository_scan
            setattr(repository_cls, "scan_logs", lambda self, *_a, **_k: (0, 0))

        try:
            tool = legacy.ServiceTool()
        finally:
            for name, function in deferred.items():
                if name == "repository_scan_logs":
                    setattr(repository_cls, "scan_logs", function)
                else:
                    setattr(legacy.ServiceTool, name, function)
            if messagebox is not None:
                for name, function in saved_dialogs.items():
                    setattr(messagebox, name, function)

        # The old profile UI used to create this store as a side effect.  In the
        # headless bootstrap the data store is service state, so initialize it
        # directly instead of rebuilding a hidden tab just to obtain the object.
        if not hasattr(tool, "config_profile_store") and hasattr(tool, "_load_config_profile_store"):
            with contextlib.suppress(Exception):
                tool.config_profile_store = tool._load_config_profile_store()
        if not hasattr(tool, "config_profile_store"):
            tool.config_profile_store = {
                "schema": 1,
                "authorized_915": {"a_mhz": "", "b_mhz": ""},
                "profiles": [None, None, None, None],
            }

        host = base.LegacyBridge._resolve_tk_host(tool)
        with contextlib.suppress(Exception):
            host.withdraw()
        bridge = base.LegacyBridge(tool)

        handler = type(
            "JarnsenApiHandler",
            (base.ApiHandler,),
            {"bridge": bridge, "token": token},
        )
        server = base.ThreadingHTTPServer(("127.0.0.1", port), handler)
        server.daemon_threads = True
        server_thread = base.threading.Thread(
            target=server.serve_forever,
            name="framework7-api",
            daemon=True,
        )
        server_thread.start()

        def finish_deferred_startup() -> None:
            # Filesystem indexing is service work and remains useful without the
            # legacy pages. UI refresh functions are deliberately not called.
            with contextlib.suppress(Exception):
                if repository_scan is not None:
                    repository_scan(tool.repository)

        with contextlib.suppress(Exception):
            host.after(1, finish_deferred_startup)
        try:
            host.mainloop()
        finally:
            server.shutdown()
            server.server_close()
        return 0

    def _frontend(debug: bool = False) -> int:
        import webview

        port = base._free_port()
        token = secrets.token_urlsafe(24)
        base_url = f"http://127.0.0.1:{port}"
        if getattr(sys, "frozen", False):
            command = [sys.executable, "--f7-backend", "--port", str(port), "--token", token]
        else:
            command = [
                sys.executable,
                str(Path(__file__).resolve().parent / "JARNSEN_FRAMEWORK7_SERVICE_TOOL_V31.py"),
                "--f7-backend",
                "--port",
                str(port),
                "--token",
                token,
            ]

        flags = 0
        if os.name == "nt":
            flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        backend = subprocess.Popen(command, creationflags=flags)
        try:
            # One-file extraction remains, but backend readiness no longer waits
            # for construction of the obsolete Tk presentation tree.
            base._wait_for_backend(base_url, timeout=45.0)
            query = urllib.parse.urlencode({"api": base_url, "token": token, "version": base.APP_VERSION})
            url = f"{base_url}/ui/index.html?{query}"

            _validate_ui(base_url, url)

            webview.create_window(
                "Jarnsen Node Service Tool",
                url=url,
                width=1600,
                height=980,
                min_size=(1120, 720),
                background_color="#F5F7FB",
                confirm_close=False,
            )
            webview.start(debug=debug)

            with contextlib.suppress(Exception):
                request = urllib.request.Request(
                    f"{base_url}/api/action",
                    data=json.dumps({"command": "shutdown"}).encode("utf-8"),
                    headers={"Content-Type": "application/json", "X-Jarnsen-Token": token},
                    method="POST",
                )
                urllib.request.urlopen(request, timeout=1.0).read()
            return 0
        finally:
            with contextlib.suppress(Exception):
                backend.wait(timeout=3.0)
            if backend.poll() is None:
                backend.terminate()

    base._framework7_validate_ui_v312 = _validate_ui
    base._backend = _backend
    base._frontend = _frontend
