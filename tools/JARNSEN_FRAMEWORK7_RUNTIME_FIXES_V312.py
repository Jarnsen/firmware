"""Framework7 startup preflight and true headless backend runtime.

Validates the full locally bundled UI before WebView2 opens. The backend no
longer creates tkinter.Tk, a hidden legacy window, or the old widget tree.
Framework7 owns presentation; the proven v2.1.x service methods are hosted by a
small headless adapter until they are progressively extracted into standalone
service components.
"""
from __future__ import annotations

import contextlib
import datetime as dt
import json
import os
import secrets
import subprocess
import sys
import time
import traceback
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any


def _startup_log_path() -> Path:
    """Return a writable log path that exists before legacy/device imports."""
    candidates: list[Path] = []
    local = str(os.environ.get("LOCALAPPDATA") or "").strip()
    if local:
        candidates.append(Path(local) / "Jarnsen" / "NodeServiceTool" / "Jarnsen-Service-Tool-startup.log")
    candidates.append(Path.home() / "Jarnsen-Service-Tool-startup.log")
    candidates.append(Path.cwd() / "Jarnsen-Service-Tool-startup.log")
    for path in candidates:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8"):
                pass
            return path
        except Exception:
            continue
    return Path.cwd() / "Jarnsen-Service-Tool-startup.log"


def _append_startup_log(message: str) -> None:
    path = _startup_log_path()
    stamp = dt.datetime.now().astimezone().isoformat(timespec="milliseconds")
    try:
        with path.open("a", encoding="utf-8", errors="replace") as handle:
            handle.write(f"[{stamp}] pid={os.getpid()} {message}\n")
            handle.flush()
    except Exception:
        pass


def install_runtime_fix_v312(base: Any) -> None:
    def _get(url: str, *, timeout: float = 8.0) -> tuple[int, str, bytes]:
        request = urllib.request.Request(url, headers={"Cache-Control": "no-cache"})
        with urllib.request.urlopen(request, timeout=timeout) as response:
            data = response.read()
            status = int(getattr(response, "status", 200) or 200)
            content_type = str(response.headers.get("Content-Type") or "")
            return status, content_type, data

    def _wait_for_real_backend(base_url: str, backend: Any, *, timeout: float = 120.0) -> None:
        """Wait for the final API server, not only the bootstrap health listener."""
        deadline = time.monotonic() + max(1.0, float(timeout))
        last_stage = "starting"
        last_error = ""
        logged_stage = ""
        while time.monotonic() < deadline:
            if backend.poll() is not None:
                _append_startup_log(
                    f"backend exited code={backend.returncode} stage={last_stage} error={last_error or '-'}"
                )
                raise RuntimeError(
                    f"Framework7 Backend wurde vorzeitig beendet (Code {backend.returncode}; "
                    f"Stufe {last_stage}{': ' + last_error if last_error else ''})"
                )
            try:
                status, content_type, body = _get(base_url + "/health", timeout=1.5)
                if status == 200:
                    payload: dict[str, Any] = {}
                    if "json" in content_type.lower():
                        with contextlib.suppress(Exception):
                            payload = json.loads(body.decode("utf-8", errors="replace"))
                    last_stage = str(payload.get("stage") or last_stage)
                    last_error = str(payload.get("error") or last_error)
                    if last_stage != logged_stage:
                        logged_stage = last_stage
                        _append_startup_log(
                            f"backend health stage={last_stage} ready={payload.get('ready')} error={last_error or '-'}"
                        )
                    if payload.get("ready") is not False:
                        _append_startup_log("backend final API ready")
                        return
            except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError) as exc:
                # A short connection-refused window is expected while the bootstrap
                # listener releases the port and the real API re-binds it.
                if last_stage != logged_stage:
                    logged_stage = last_stage
                    _append_startup_log(f"backend handoff stage={last_stage}: {type(exc).__name__}: {exc}")
            time.sleep(0.10)
        _append_startup_log(
            f"backend readiness timeout stage={last_stage} error={last_error or '-'} timeout={timeout}s"
        )
        raise RuntimeError(
            f"Framework7 Backend wurde nicht rechtzeitig bereit (Stufe {last_stage}"
            f"{': ' + last_error if last_error else ''})"
        )

    def _validate_ui(base_url: str, index_url: str) -> None:
        _append_startup_log("validating Framework7 UI")
        status, content_type, body = _get(index_url)
        html = body.decode("utf-8", errors="replace")
        if status != 200:
            raise RuntimeError(f"Framework7 Startseite liefert HTTP {status}")
        if "text/html" not in content_type.lower():
            raise RuntimeError(f"Framework7 Startseite hat falschen Content-Type: {content_type}")

        required_refs = (
            "vendor/framework7-bundle.min.css",
            "vendor/framework7-bundle.min.js",
            "vendor/leaflet.css",
            "vendor/leaflet.js",
            "vendor/mgrs.min.js",
            "v31.css",
            "focus.css",
            "map-settings-v32.css",
            "map-settings-v32.js",
            "radio-auth-v33.css",
            "radio-auth-v33.js",
            "app-v31.js",
            "legacy-compat-v34.js",
            "parity-v35.css",
            "parity-v35.js",
            "parity-enhance-v36.css",
            "parity-enhance-v36.js",
            "series-v37.css",
            "series-v37.js",
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
            ("/ui/series-v37.css", "text/css", b"series-page"),
            ("/ui/series-v37.js", "javascript", b"/api/series/status"),
        )
        for path, expected_type, marker in assets:
            asset_status, asset_type, asset_body = _get(base_url + path)
            if asset_status != 200 or not asset_body:
                raise RuntimeError(f"Framework7 Asset konnte nicht geladen werden: {path}")
            if expected_type not in asset_type.lower():
                raise RuntimeError(f"Framework7 Asset hat falschen Content-Type: {path} ({asset_type})")
            if marker and marker.lower() not in asset_body.lower():
                raise RuntimeError(f"Framework7 Asset ist unvollständig: {path}")
        _append_startup_log("Framework7 UI validation OK")

    def _backend(port: int, token: str) -> int:
        """Run the local API on a real headless service object."""
        _append_startup_log(f"backend runtime entered port={port}")
        import JARNSEN_NODE_SERVICE_TOOL as legacy
        _append_startup_log("legacy service module imported")
        from JARNSEN_FRAMEWORK7_HEADLESS_CORE import build_headless_tool

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

        _append_startup_log("constructing headless service object")
        tool = build_headless_tool(legacy)
        _append_startup_log("headless service object ready")

        bridge_lock = base.threading.RLock()

        def direct_call_ui(self: Any, callback: Any, timeout: float = 90.0) -> Any:
            del timeout
            with bridge_lock:
                return callback()

        base.LegacyBridge.call_ui = direct_call_ui
        bridge = base.LegacyBridge(tool)

        handler = type(
            "JarnsenApiHandler",
            (base.ApiHandler,),
            {"bridge": bridge, "token": token},
        )
        server = base.ThreadingHTTPServer(("127.0.0.1", port), handler)
        server.daemon_threads = True
        server.timeout = 0.25
        _append_startup_log("final backend HTTP server bound")

        def finish_deferred_startup() -> None:
            _append_startup_log("deferred repository log scan started")
            try:
                tool.repository.scan_logs()
                _append_startup_log("deferred repository log scan finished")
            except Exception:
                _append_startup_log("deferred repository log scan failed\n" + traceback.format_exc())

        scan_thread = base.threading.Thread(
            target=finish_deferred_startup,
            name="framework7-log-index",
            daemon=True,
        )
        scan_thread.start()

        try:
            while not bridge._shutdown and not bool(getattr(tool, "_headless_destroyed", False)):
                server.handle_request()
        finally:
            _append_startup_log("backend shutdown")
            with contextlib.suppress(Exception):
                tool.destroy()
            server.server_close()
            if messagebox is not None:
                for name, function in saved_dialogs.items():
                    setattr(messagebox, name, function)
        return 0

    def _show_start_error(message: str) -> None:
        if os.name != "nt":
            return
        with contextlib.suppress(Exception):
            import ctypes
            ctypes.windll.user32.MessageBoxW(
                0,
                message + "\n\nStartlog:\n" + str(_startup_log_path()),
                "Jarnsen Node Service Tool - Startfehler",
                0x10,
            )

    def _frontend(debug: bool = False) -> int:
        _append_startup_log("=== frontend startup begin ===")
        log_path = _startup_log_path()
        backend: Any = None
        log_handle: Any = None
        try:
            import webview
            _append_startup_log("pywebview imported")

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
            log_handle = log_path.open("a", encoding="utf-8", errors="replace", buffering=1)
            log_handle.write(f"backend command={command!r}\n")
            log_handle.flush()
            backend = subprocess.Popen(
                command,
                creationflags=flags,
                stdout=log_handle,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
            )
            _append_startup_log(f"backend child spawned pid={backend.pid}")

            _wait_for_real_backend(base_url, backend, timeout=120.0)
            query = urllib.parse.urlencode({"api": base_url, "token": token, "version": base.APP_VERSION})
            url = f"{base_url}/ui/index.html?{query}"
            _validate_ui(base_url, url)

            _append_startup_log("creating WebView window")
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
            _append_startup_log("WebView closed normally")

            with contextlib.suppress(Exception):
                request = urllib.request.Request(
                    f"{base_url}/api/action",
                    data=json.dumps({"command": "shutdown"}).encode("utf-8"),
                    headers={"Content-Type": "application/json", "X-Jarnsen-Token": token},
                    method="POST",
                )
                urllib.request.urlopen(request, timeout=1.0).read()
            return 0
        except Exception as exc:  # noqa: BLE001
            detail = f"{type(exc).__name__}: {exc}"
            _append_startup_log("FATAL frontend startup error: " + detail + "\n" + traceback.format_exc())
            _show_start_error(detail)
            return 2
        finally:
            if backend is not None:
                with contextlib.suppress(Exception):
                    backend.wait(timeout=3.0)
                if backend.poll() is None:
                    with contextlib.suppress(Exception):
                        backend.terminate()
                    _append_startup_log("backend child terminated by frontend cleanup")
            if log_handle is not None:
                with contextlib.suppress(Exception):
                    log_handle.flush()
                    log_handle.close()
            _append_startup_log("=== frontend startup end ===")

    base._framework7_wait_for_real_backend_v312 = _wait_for_real_backend
    base._framework7_validate_ui_v312 = _validate_ui
    base._framework7_startup_log_path_v312 = _startup_log_path
    base._framework7_append_startup_log_v312 = _append_startup_log
    base._backend = _backend
    base._frontend = _frontend
