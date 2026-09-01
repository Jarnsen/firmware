"""Boot the Framework7 API before headless service-core initialization.

The listener is created before importing or constructing the legacy-derived
service core.  /health therefore distinguishes HTTP/process startup from service
initialization and reports the current bootstrap stage.  Framework7 remains the
only UI; no Tk root or mainloop is created.
"""
from __future__ import annotations

import contextlib
import threading
import time
import urllib.parse
from pathlib import Path
from typing import Any


class _DeferredBridge:
    """Bridge proxy that becomes live when the headless service core is ready."""

    def __init__(self) -> None:
        self._event = threading.Event()
        self._lock = threading.RLock()
        self._target: Any | None = None
        self._error = ""
        self._stage = "listener-starting"
        self._shutdown = False

    @property
    def ready(self) -> bool:
        with self._lock:
            return self._target is not None and not self._error

    @property
    def error(self) -> str:
        with self._lock:
            return self._error

    @property
    def stage(self) -> str:
        with self._lock:
            return self._stage

    def set_stage(self, value: str) -> None:
        with self._lock:
            self._stage = str(value or "")

    def set_target(self, target: Any) -> None:
        with self._lock:
            self._target = target
            self._error = ""
            self._stage = "ready"
        self._event.set()

    def set_error(self, message: str) -> None:
        with self._lock:
            self._target = None
            self._error = str(message or "unknown bootstrap error")
            self._stage = "failed"
        self._event.set()

    def _require_target(self, timeout: float = 45.0) -> Any:
        if not self._event.wait(timeout=max(0.1, float(timeout))):
            raise RuntimeError(f"Headless backend is still starting ({self.stage})")
        with self._lock:
            if self._error:
                raise RuntimeError(f"Headless backend bootstrap failed: {self._error}")
            if self._target is None:
                raise RuntimeError("Headless backend did not publish a service bridge")
            return self._target

    def __getattr__(self, name: str) -> Any:
        def dispatch(*args: Any, **kwargs: Any) -> Any:
            target = self._require_target()
            value = getattr(target, name)(*args, **kwargs)
            if name == "action":
                payload = args[0] if args else kwargs.get("payload")
                if isinstance(payload, dict) and str(payload.get("command") or "") == "shutdown":
                    self._shutdown = True
            return value

        return dispatch


def install_headless_boot(base: Any) -> None:
    def _backend(port: int, token: str) -> int:
        deferred = _DeferredBridge()

        class BootApiHandler(base.ApiHandler):
            bridge = deferred
            token = token

            def do_GET(self) -> None:  # noqa: N802
                parsed = urllib.parse.urlparse(self.path)
                if parsed.path == "/health":
                    self._send(
                        200,
                        {
                            "ok": True,
                            "ready": deferred.ready,
                            "stage": deferred.stage,
                            "error": deferred.error,
                            "version": base.APP_VERSION,
                        },
                    )
                    return
                super().do_GET()

        # This is intentionally the first potentially blocking operation.  No
        # legacy/Tk/BLE/service module import happens before the socket listens.
        server = base.ThreadingHTTPServer(("127.0.0.1", port), BootApiHandler)
        server.daemon_threads = True
        server_thread = threading.Thread(
            target=server.serve_forever,
            name="framework7-api",
            daemon=True,
        )
        server_thread.start()
        deferred.set_stage("listener-ready")

        tool = None
        messagebox = None
        saved_dialogs: dict[str, Any] = {}
        try:
            deferred.set_stage("importing-service-core")
            import JARNSEN_NODE_SERVICE_TOOL as legacy
            from JARNSEN_FRAMEWORK7_HEADLESS_CORE import build_headless_tool

            deferred.set_stage("service-core-imported")
            messagebox = getattr(legacy, "messagebox", None)
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
                    if function is not None:
                        saved_dialogs[name] = function
                        setattr(messagebox, name, lambda *_a, _result=result, **_k: _result)

            deferred.set_stage("constructing-headless-core")
            tool = build_headless_tool(legacy)
            deferred.set_stage("installing-bridge")
            bridge_lock = threading.RLock()

            def direct_call_ui(self: Any, callback: Any, timeout: float = 90.0) -> Any:
                del timeout
                with bridge_lock:
                    return callback()

            base.LegacyBridge.call_ui = direct_call_ui
            bridge = base.LegacyBridge(tool)
            deferred.set_target(bridge)

            def scan_logs() -> None:
                with contextlib.suppress(Exception):
                    tool.repository.scan_logs()

            threading.Thread(
                target=scan_logs,
                name="framework7-log-index",
                daemon=True,
            ).start()

            while (
                not deferred._shutdown
                and not bridge._shutdown
                and not bool(getattr(tool, "_headless_destroyed", False))
            ):
                time.sleep(0.1)
            return 0
        except Exception as exc:  # noqa: BLE001
            detail = f"{type(exc).__name__}: {exc}"
            deferred.set_error(detail)
            with contextlib.suppress(Exception):
                (Path.cwd() / "Framework7-backend-bootstrap-error.txt").write_text(
                    detail + "\n", encoding="utf-8"
                )
            # Keep HTTP diagnostics available long enough for CI to retrieve the
            # concrete bootstrap failure instead of reporting a generic timeout.
            deadline = time.monotonic() + 30.0
            while time.monotonic() < deadline and not deferred._shutdown:
                time.sleep(0.1)
            return 2
        finally:
            if tool is not None:
                with contextlib.suppress(Exception):
                    tool.destroy()
            server.shutdown()
            server.server_close()
            if messagebox is not None:
                for name, function in saved_dialogs.items():
                    setattr(messagebox, name, function)

    base._backend = _backend
