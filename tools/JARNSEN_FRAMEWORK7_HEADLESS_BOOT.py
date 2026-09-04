"""Boot the Framework7 API before headless service-core initialization.

The listener is created before importing or constructing the legacy-derived
service core. /health therefore distinguishes HTTP/process startup from service
initialization and reports the current bootstrap stage. Framework7 remains the
only UI; no Tcl/Tk interpreter, Tk root, window or mainloop is created.

v2.1.28 is the cumulative functional reference. During the migration away from
the monolithic historical module we still import its mature service methods.
The historical module declares Tk based classes at import time, so a tiny pure
Python compatibility module is installed only for those declarations when the
real tkinter package is unavailable. This is not a GUI backend: it creates no
interpreter and no widgets and all runtime state is provided by the headless
service-core proxies.
"""
from __future__ import annotations

import contextlib
import sys
import threading
import time
import types
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


def _install_headless_tk_compat() -> bool:
    """Install a declaration-only tkinter shim when tkinter is unavailable.

    The cumulative v2.1.28 module still contains presentation class declarations
    such as ``class ServiceTool(tk.Tk)``. The headless runtime never invokes their
    GUI constructors, but Python must be able to resolve those names while the
    module is imported. On the embeddable CI/runtime Python distribution tkinter
    is intentionally absent. This shim satisfies only those declarations.

    Returns True when a shim was installed and False when real tkinter already
    exists. No Tcl interpreter is created in either case.
    """
    try:
        __import__("tkinter")
        return False
    except ModuleNotFoundError:
        pass

    class _Var:
        def __init__(self, value: Any = None, *_args: Any, **_kwargs: Any) -> None:
            self._value = value

        def get(self) -> Any:
            return self._value

        def set(self, value: Any) -> None:
            self._value = value

        def trace_add(self, *_args: Any, **_kwargs: Any) -> str:
            return "headless-tk-compat-trace"

        def trace_remove(self, *_args: Any, **_kwargs: Any) -> None:
            return None

    class _Widget:
        def __init__(self, *_args: Any, **_kwargs: Any) -> None:
            self._value = ""
            self._config: dict[str, Any] = {}

        def __getattr__(self, _name: str) -> Any:
            return lambda *_args, **_kwargs: None

        def configure(self, **kwargs: Any) -> None:
            self._config.update(kwargs)

        config = configure

        def cget(self, key: str) -> Any:
            return self._config.get(key, "")

        def get(self, *_args: Any) -> Any:
            return self._value

        def set(self, value: Any) -> None:
            self._value = value

        def insert(self, *_args: Any) -> None:
            if _args:
                self._value = str(_args[-1])

        def delete(self, *_args: Any) -> None:
            self._value = ""

        def winfo_toplevel(self) -> Any:
            return self

        def winfo_exists(self) -> bool:
            return False

        def after(self, _ms: int, callback: Any = None, *args: Any) -> str:
            if callback is not None:
                callback(*args)
            return "headless-tk-compat-after"

        after_idle = after

    tk = types.ModuleType("tkinter")
    ttk = types.ModuleType("tkinter.ttk")
    messagebox = types.ModuleType("tkinter.messagebox")
    filedialog = types.ModuleType("tkinter.filedialog")
    simpledialog = types.ModuleType("tkinter.simpledialog")
    font = types.ModuleType("tkinter.font")
    constants = types.ModuleType("tkinter.constants")

    # Classes needed at import/class-definition time. Runtime Framework7 state is
    # supplied by JARNSEN_FRAMEWORK7_HEADLESS_CORE rather than these placeholders.
    for name in (
        "Tk", "Tcl", "Misc", "Widget", "Frame", "Label", "Button", "Canvas",
        "Text", "Entry", "Listbox", "Scrollbar", "Menu", "Toplevel", "PhotoImage",
        "Checkbutton", "Radiobutton", "Scale", "Spinbox", "PanedWindow", "LabelFrame",
    ):
        setattr(tk, name, _Widget)
    for name in ("StringVar", "BooleanVar", "IntVar", "DoubleVar", "Variable"):
        setattr(tk, name, _Var)

    ttk_names = (
        "Style", "Frame", "Label", "Button", "Entry", "Combobox", "Notebook",
        "Progressbar", "Treeview", "Scrollbar", "Checkbutton", "Radiobutton",
        "Separator", "Panedwindow", "LabelFrame", "Scale", "Spinbox",
    )
    for name in ttk_names:
        setattr(ttk, name, _Widget)
    ttk.__getattr__ = lambda _name: _Widget  # type: ignore[attr-defined]

    messagebox.showinfo = lambda *_a, **_k: None  # type: ignore[attr-defined]
    messagebox.showwarning = lambda *_a, **_k: None  # type: ignore[attr-defined]
    messagebox.showerror = lambda *_a, **_k: None  # type: ignore[attr-defined]
    messagebox.askokcancel = lambda *_a, **_k: True  # type: ignore[attr-defined]
    messagebox.askyesno = lambda *_a, **_k: True  # type: ignore[attr-defined]
    messagebox.askretrycancel = lambda *_a, **_k: False  # type: ignore[attr-defined]
    messagebox.askquestion = lambda *_a, **_k: "yes"  # type: ignore[attr-defined]
    messagebox.askyesnocancel = lambda *_a, **_k: True  # type: ignore[attr-defined]
    filedialog.askopenfilename = lambda *_a, **_k: ""  # type: ignore[attr-defined]
    filedialog.asksaveasfilename = lambda *_a, **_k: ""  # type: ignore[attr-defined]
    filedialog.askdirectory = lambda *_a, **_k: ""  # type: ignore[attr-defined]
    simpledialog.askstring = lambda *_a, **_k: None  # type: ignore[attr-defined]
    simpledialog.askinteger = lambda *_a, **_k: None  # type: ignore[attr-defined]
    font.Font = _Widget  # type: ignore[attr-defined]

    constant_values = {
        "END": "end", "INSERT": "insert", "NORMAL": "normal", "DISABLED": "disabled",
        "ACTIVE": "active", "BOTH": "both", "X": "x", "Y": "y", "LEFT": "left",
        "RIGHT": "right", "TOP": "top", "BOTTOM": "bottom", "N": "n", "S": "s",
        "E": "e", "W": "w", "NW": "nw", "NE": "ne", "SW": "sw", "SE": "se",
        "CENTER": "center", "HORIZONTAL": "horizontal", "VERTICAL": "vertical",
        "WORD": "word", "NONE": "none", "SUNKEN": "sunken", "RAISED": "raised",
        "FLAT": "flat", "RIDGE": "ridge", "GROOVE": "groove", "SOLID": "solid",
        "TRUE": True, "FALSE": False,
    }
    for name, value in constant_values.items():
        setattr(tk, name, value)
        setattr(constants, name, value)

    tk.TkVersion = 8.6  # type: ignore[attr-defined]
    tk.TclVersion = 8.6  # type: ignore[attr-defined]
    tk.ttk = ttk  # type: ignore[attr-defined]
    tk.messagebox = messagebox  # type: ignore[attr-defined]
    tk.filedialog = filedialog  # type: ignore[attr-defined]
    tk.simpledialog = simpledialog  # type: ignore[attr-defined]
    tk.font = font  # type: ignore[attr-defined]

    sys.modules["tkinter"] = tk
    sys.modules["tkinter.ttk"] = ttk
    sys.modules["tkinter.messagebox"] = messagebox
    sys.modules["tkinter.filedialog"] = filedialog
    sys.modules["tkinter.simpledialog"] = simpledialog
    sys.modules["tkinter.font"] = font
    sys.modules["tkinter.constants"] = constants
    return True


def install_headless_boot(base: Any) -> None:
    def _backend(port: int, token: str) -> int:
        deferred = _DeferredBridge()

        class BootApiHandler(base.ApiHandler):
            bridge = deferred

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

        BootApiHandler.token = token

        # This is intentionally the first potentially blocking operation. No
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
            deferred.set_stage("installing-headless-tk-compat")
            shimmed = _install_headless_tk_compat()
            deferred.set_stage("importing-v2.1.28-service-core")
            import JARNSEN_NODE_SERVICE_TOOL as legacy
            from JARNSEN_FRAMEWORK7_HEADLESS_CORE import build_headless_tool

            deferred.set_stage("v2.1.28-service-core-imported" if not shimmed else "v2.1.28-service-core-imported-no-tk")
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

            deferred.set_stage("constructing-headless-v2.1.28-core")
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