"""Runtime fixes for the packaged Framework7 desktop shell.

The v3.1 preview exposed two Windows-only packaging issues that CI did not catch:
1. WebView2 was pointed at a file:// URL inside a PyInstaller onefile extraction dir.
2. The legacy Tk service core could become visible before/after withdraw().

This layer serves the bundled web UI from the existing loopback HTTP server and
keeps every legacy Tk root/toplevel hidden for the entire backend lifetime.
"""
from __future__ import annotations

import contextlib
import json
import mimetypes
import os
import secrets
import socket
import subprocess
import sys
import threading
import time
import urllib.parse
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path, PurePosixPath
from typing import Any


def install_runtime_fixes(base: Any) -> None:
    """Patch the v3 launcher after all feature routes have been installed."""

    previous_do_get = base.ApiHandler.do_GET

    def _send_static(handler: Any, file_path: Path) -> None:
        try:
            data = file_path.read_bytes()
        except OSError:
            handler.send_response(404)
            handler.send_header("Content-Length", "0")
            handler.end_headers()
            return

        suffix = file_path.suffix.lower()
        if suffix == ".html":
            content_type = "text/html; charset=utf-8"
        elif suffix == ".css":
            content_type = "text/css; charset=utf-8"
        elif suffix == ".js":
            content_type = "application/javascript; charset=utf-8"
        elif suffix == ".json":
            content_type = "application/json; charset=utf-8"
        else:
            content_type = mimetypes.guess_type(str(file_path))[0] or "application/octet-stream"

        handler.send_response(200)
        handler.send_header("Content-Type", content_type)
        handler.send_header("Content-Length", str(len(data)))
        handler.send_header("Cache-Control", "no-store")
        handler.send_header("X-Content-Type-Options", "nosniff")
        handler.end_headers()
        handler.wfile.write(data)

    def do_GET(self: Any) -> None:  # noqa: N802
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path in {"/", "/ui", "/ui/"}:
            requested = "index.html"
        elif parsed.path.startswith("/ui/"):
            requested = urllib.parse.unquote(parsed.path[len("/ui/") :]) or "index.html"
        else:
            return previous_do_get(self)

        relative = PurePosixPath(requested)
        if relative.is_absolute() or any(part in {"", ".", ".."} for part in relative.parts):
            self.send_response(400)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return

        web_root = base._resource_path("service_tool_web").resolve()
        target = (web_root / Path(*relative.parts)).resolve()
        if target != web_root and web_root not in target.parents:
            self.send_response(403)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        if not target.is_file():
            self.send_response(404)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        _send_static(self, target)

    base.ApiHandler.do_GET = do_GET

    def _install_hidden_tk_policy() -> None:
        """Withdraw Tk windows at creation time so the backend never flashes onscreen."""
        import tkinter as tk

        if getattr(tk, "_jarnsen_framework7_hidden_policy", False):
            return
        tk._jarnsen_framework7_hidden_policy = True

        original_tk_init = tk.Tk.__init__
        original_toplevel_init = tk.Toplevel.__init__

        def _hide(widget: Any) -> None:
            with contextlib.suppress(Exception):
                widget.withdraw()
            with contextlib.suppress(Exception):
                widget.attributes("-alpha", 0.0)

        def hidden_tk_init(self: Any, *args: Any, **kwargs: Any) -> None:
            original_tk_init(self, *args, **kwargs)
            _hide(self)

        def hidden_toplevel_init(self: Any, *args: Any, **kwargs: Any) -> None:
            original_toplevel_init(self, *args, **kwargs)
            _hide(self)

        tk.Tk.__init__ = hidden_tk_init
        tk.Toplevel.__init__ = hidden_toplevel_init

    def _keep_hidden(host: Any) -> None:
        """Guard against legacy code that calls deiconify() after startup."""
        def hide_again() -> None:
            if not host:
                return
            with contextlib.suppress(Exception):
                host.withdraw()
            with contextlib.suppress(Exception):
                host.attributes("-alpha", 0.0)
            with contextlib.suppress(Exception):
                host.after(150, hide_again)

        hide_again()

    def _backend(port: int, token: str) -> int:
        _install_hidden_tk_policy()
        import JARNSEN_NODE_SERVICE_TOOL as legacy

        # Disable previous presentation shells; this process is service-only.
        if hasattr(legacy.ServiceTool, "_install_mac_shell_v220"):
            legacy.ServiceTool._install_mac_shell_v220 = lambda self: None

        tool = legacy.ServiceTool()
        host = base.LegacyBridge._resolve_tk_host(tool)
        _keep_hidden(host)
        bridge = base.LegacyBridge(tool)

        handler = type("JarnsenApiHandler", (base.ApiHandler,), {"bridge": bridge, "token": token})
        server = ThreadingHTTPServer(("127.0.0.1", port), handler)
        server.daemon_threads = True
        server_thread = threading.Thread(target=server.serve_forever, name="framework7-api", daemon=True)
        server_thread.start()
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
            command = [sys.executable, str(Path(__file__).resolve().parent / "JARNSEN_FRAMEWORK7_SERVICE_TOOL_V31.py"), "--f7-backend", "--port", str(port), "--token", token]

        flags = 0
        if os.name == "nt":
            flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        backend = subprocess.Popen(command, creationflags=flags)
        try:
            base._wait_for_backend(base_url)
            query = urllib.parse.urlencode({"api": base_url, "token": token, "version": base.APP_VERSION})
            url = f"{base_url}/ui/index.html?{query}"

            # Validate the exact URL WebView2 is about to open.  This converts a
            # packaging/path problem into a clear startup error instead of a blank browser page.
            with urllib.request.urlopen(url, timeout=5.0) as response:
                html = response.read(4096).decode("utf-8", errors="replace")
                if response.status != 200 or "app-v31.js" not in html:
                    raise RuntimeError("Framework7 Startseite konnte nicht korrekt geladen werden")

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

    base._backend = _backend
    base._frontend = _frontend
