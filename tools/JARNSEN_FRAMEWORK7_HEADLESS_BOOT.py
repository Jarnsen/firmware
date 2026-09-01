"""Boot the Framework7 API before headless service-core initialization.

The /health listener is brought up first so Windows CI can distinguish HTTP
startup problems from service-core construction failures.  Framework7 remains
the only UI; no Tk root or mainloop is created.
"""
from __future__ import annotations

import contextlib
import threading
import time
from pathlib import Path
from typing import Any


class _BootFailureBridge:
    def __init__(self, message: str) -> None:
        self.message = message
        self._shutdown = False

    def __getattr__(self, _name: str) -> Any:
        def failed(*_args: Any, **_kwargs: Any) -> Any:
            raise RuntimeError(f"Headless backend bootstrap failed: {self.message}")
        return failed


def install_headless_boot(base: Any) -> None:
    def _backend(port: int, token: str) -> int:
        import JARNSEN_NODE_SERVICE_TOOL as legacy
        from JARNSEN_FRAMEWORK7_HEADLESS_CORE import build_headless_tool

        # Start the listener before constructing repository/profile/device state.
        # /health is deliberately bridge-independent in ApiHandler.
        handler = type(
            "JarnsenApiHandler",
            (base.ApiHandler,),
            {"bridge": _BootFailureBridge("service core is still starting"), "token": token},
        )
        server = base.ThreadingHTTPServer(("127.0.0.1", port), handler)
        server.daemon_threads = True
        server_thread = threading.Thread(
            target=server.serve_forever,
            name="framework7-api",
            daemon=True,
        )
        server_thread.start()

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
                if function is not None:
                    saved_dialogs[name] = function
                    setattr(messagebox, name, lambda *_a, _result=result, **_k: _result)

        tool = None
        bridge = None
        try:
            tool = build_headless_tool(legacy)
            bridge_lock = threading.RLock()

            def direct_call_ui(self: Any, callback: Any, timeout: float = 90.0) -> Any:
                del timeout
                with bridge_lock:
                    return callback()

            base.LegacyBridge.call_ui = direct_call_ui
            bridge = base.LegacyBridge(tool)
            handler.bridge = bridge

            def scan_logs() -> None:
                with contextlib.suppress(Exception):
                    tool.repository.scan_logs()

            threading.Thread(
                target=scan_logs,
                name="framework7-log-index",
                daemon=True,
            ).start()

            while not bridge._shutdown and not bool(getattr(tool, "_headless_destroyed", False)):
                time.sleep(0.1)
            return 0
        except Exception as exc:  # noqa: BLE001
            detail = f"{type(exc).__name__}: {exc}"
            handler.bridge = _BootFailureBridge(detail)
            with contextlib.suppress(Exception):
                (Path.cwd() / "Framework7-backend-bootstrap-error.txt").write_text(
                    detail + "\n", encoding="utf-8"
                )
            # Keep the listener alive briefly so CI's next authenticated API call
            # receives the concrete bootstrap error instead of another timeout.
            deadline = time.monotonic() + 30.0
            while time.monotonic() < deadline:
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
