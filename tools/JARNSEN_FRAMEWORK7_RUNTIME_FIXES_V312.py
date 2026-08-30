"""Framework7 v3.1.2 startup fix.

Replaces the v3.1.1 WebView preflight that only inspected the first 4096 bytes of
index.html. The script tag for app-v31.js is intentionally near the end of the
page, so the old check could reject a perfectly valid UI.

This layer validates the complete start document and the concrete assets that
WebView2 will load from the loopback server, then opens the Framework7 window.
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
            'v31.css',
            'app-v31.js',
        )
        missing_refs = [ref for ref in required_refs if ref not in html]
        if missing_refs:
            raise RuntimeError("Framework7 Startseite ist unvollständig: " + ", ".join(missing_refs))

        assets = (
            ("/ui/vendor/framework7-bundle.min.css", "text/css", None),
            ("/ui/vendor/framework7-bundle.min.js", "javascript", b"Framework7"),
            ("/ui/v31.css", "text/css", None),
            ("/ui/app-v31.js", "javascript", b"theme: 'ios'"),
        )
        for path, expected_type, marker in assets:
            asset_status, asset_type, asset_body = _get(base_url + path)
            if asset_status != 200 or not asset_body:
                raise RuntimeError(f"Framework7 Asset konnte nicht geladen werden: {path}")
            if expected_type not in asset_type.lower():
                raise RuntimeError(f"Framework7 Asset hat falschen Content-Type: {path} ({asset_type})")
            if marker and marker not in asset_body:
                raise RuntimeError(f"Framework7 Asset ist unvollständig: {path}")

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
            base._wait_for_backend(base_url)
            query = urllib.parse.urlencode({"api": base_url, "token": token, "version": base.APP_VERSION})
            url = f"{base_url}/ui/index.html?{query}"

            # Validate exactly what WebView2 will load. Unlike v3.1.1 this reads
            # the complete HTML document and verifies every critical asset.
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
    base._frontend = _frontend
