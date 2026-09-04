"""Build-time full diagnostics for Framework7 USB crash isolation.

This is intentionally verbose. It gives frontend and backend one timestamped
session log under Downloads/Meshtastic-Logs/Tool-Logs, records HTTP/API traffic,
backend bootstrap stages, USB target changes, headless events and scheduler
exceptions, and fills presentation-only controls still touched by legacy USB
workers.
"""
from __future__ import annotations

import pathlib
import sys


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one anchor, found {count}")
    return text.replace(old, new, 1)


def patch_runtime(path: pathlib.Path) -> None:
    text = path.read_text(encoding="utf-8")
    old = '''def _startup_log_path() -> Path:\n    """Return a writable log path that exists before legacy/device imports."""\n    candidates: list[Path] = []\n    local = str(os.environ.get("LOCALAPPDATA") or "").strip()\n    if local:\n        candidates.append(Path(local) / "Jarnsen" / "NodeServiceTool" / "Jarnsen-Service-Tool-startup.log")\n    candidates.append(Path.home() / "Jarnsen-Service-Tool-startup.log")\n    candidates.append(Path.cwd() / "Jarnsen-Service-Tool-startup.log")\n    for path in candidates:\n        try:\n            path.parent.mkdir(parents=True, exist_ok=True)\n            with path.open("a", encoding="utf-8"):\n                pass\n            return path\n        except Exception:\n            continue\n    return Path.cwd() / "Jarnsen-Service-Tool-startup.log"\n'''
    new = '''def _startup_log_path() -> Path:\n    """Return one timestamped session log shared by frontend and backend."""\n    inherited = str(os.environ.get("JARNSEN_TOOL_LOG_PATH") or "").strip()\n    if inherited:\n        path = Path(inherited)\n        try:\n            path.parent.mkdir(parents=True, exist_ok=True)\n            path.touch(exist_ok=True)\n            return path\n        except Exception:\n            pass\n\n    stamp = dt.datetime.now().astimezone().strftime("%Y-%m-%d_%H-%M-%S")\n    candidates = [\n        Path.home() / "Downloads" / "Meshtastic-Logs" / "Tool-Logs" / f"Jarnsen-Service-Tool_{stamp}.log",\n        Path.home() / f"Jarnsen-Service-Tool_{stamp}.log",\n        Path.cwd() / f"Jarnsen-Service-Tool_{stamp}.log",\n    ]\n    for path in candidates:\n        try:\n            path.parent.mkdir(parents=True, exist_ok=True)\n            path.touch(exist_ok=True)\n            os.environ["JARNSEN_TOOL_LOG_PATH"] = str(path)\n            return path\n        except Exception:\n            continue\n    return Path.cwd() / f"Jarnsen-Service-Tool_{stamp}.log"\n'''
    if "one timestamped session log shared" not in text:
        text = replace_once(text, old, new, "runtime log path")
    text = replace_once(
        text,
        '        log_path = _startup_log_path()\n        backend: Any = None\n',
        '        log_path = _startup_log_path()\n        os.environ["JARNSEN_TOOL_LOG_PATH"] = str(log_path)\n        _append_startup_log(f"diagnostic session log={log_path}")\n        backend: Any = None\n',
        "runtime session path export",
    )
    text = replace_once(
        text,
        '            webview.start(debug=debug)\n            _append_startup_log("WebView closed normally")\n',
        '            _append_startup_log("WebView event loop entering")\n            webview.start(debug=debug)\n            _append_startup_log(f"WebView event loop returned; backend_poll={backend.poll() if backend is not None else None}")\n',
        "runtime webview timeline",
    )
    path.write_text(text, encoding="utf-8")


def patch_headless_boot(path: pathlib.Path) -> None:
    text = path.read_text(encoding="utf-8")
    if "def _diag(message: str)" not in text:
        text = replace_once(
            text,
            'import contextlib\nimport sys\nimport threading\nimport time\nimport types\nimport urllib.parse\n',
            'import contextlib\nimport datetime as dt\nimport os\nimport sys\nimport threading\nimport time\nimport traceback\nimport types\nimport urllib.parse\n',
            "headless boot imports",
        )
        helper = '''\n\ndef _diag(message: str) -> None:\n    """Append a diagnostic record to the shared frontend/backend session log."""\n    path_text = str(os.environ.get("JARNSEN_TOOL_LOG_PATH") or "").strip()\n    if not path_text:\n        return\n    stamp = dt.datetime.now().astimezone().isoformat(timespec="milliseconds")\n    try:\n        path = Path(path_text)\n        path.parent.mkdir(parents=True, exist_ok=True)\n        with path.open("a", encoding="utf-8", errors="replace") as handle:\n            handle.write(f"[{stamp}] pid={os.getpid()} thread={threading.current_thread().name} {message}\\n")\n            handle.flush()\n    except Exception:\n        pass\n'''
        text = replace_once(text, '\n\nclass _DeferredBridge:', helper + '\n\nclass _DeferredBridge:', "headless diag helper")

    text = replace_once(
        text,
        '    def set_stage(self, value: str) -> None:\n        with self._lock:\n            self._stage = str(value or "")\n',
        '    def set_stage(self, value: str) -> None:\n        with self._lock:\n            self._stage = str(value or "")\n        _diag(f"BOOT stage={self._stage}")\n',
        "headless stage logging",
    )
    text = replace_once(
        text,
        '        self._event.set()\n\n    def set_error(self, message: str) -> None:\n',
        '        self._event.set()\n        _diag("BOOT bridge target ready")\n\n    def set_error(self, message: str) -> None:\n',
        "headless ready logging",
    )
    text = replace_once(
        text,
        '        self._event.set()\n\n    def _require_target(self, timeout: float = 45.0) -> Any:\n',
        '        self._event.set()\n        _diag(f"BOOT ERROR {self._error}")\n\n    def _require_target(self, timeout: float = 45.0) -> Any:\n',
        "headless error logging",
    )
    text = replace_once(
        text,
        '            def do_GET(self) -> None:  # noqa: N802\n                parsed = urllib.parse.urlparse(self.path)\n',
        '            def do_GET(self) -> None:  # noqa: N802\n                _diag(f"HTTP GET {self.path}")\n                parsed = urllib.parse.urlparse(self.path)\n',
        "headless GET logging",
    )
    if "HTTP POST" not in text:
        text = replace_once(
            text,
            '        BootApiHandler.token = token\n',
            '            def do_POST(self) -> None:  # noqa: N802\n                _diag(f"HTTP POST {self.path} length={self.headers.get(\'Content-Length\', \'0\')}")\n                try:\n                    return super().do_POST()\n                except Exception:\n                    _diag("HTTP POST exception\\n" + traceback.format_exc())\n                    raise\n\n        BootApiHandler.token = token\n',
            "headless POST logging",
        )
    text = replace_once(
        text,
        '        server_thread.start()\n        deferred.set_stage("listener-ready")\n',
        '        server_thread.start()\n        _diag(f"BOOT HTTP listener started port={port}")\n        deferred.set_stage("listener-ready")\n',
        "listener logging",
    )
    text = replace_once(
        text,
        '            tool = build_headless_tool(legacy)\n            deferred.set_stage("installing-bridge")\n',
        '            _diag("HEADLESS constructing service object")\n            tool = build_headless_tool(legacy)\n            _diag("HEADLESS service object constructed")\n            deferred.set_stage("installing-bridge")\n',
        "headless construction logging",
    )
    text = replace_once(
        text,
        '            def scan_logs() -> None:\n                with contextlib.suppress(Exception):\n                    tool.repository.scan_logs()\n',
        '            def scan_logs() -> None:\n                _diag("REPOSITORY initial scan start")\n                try:\n                    result = tool.repository.scan_logs()\n                    _diag(f"REPOSITORY initial scan done result={result!r}")\n                except Exception:\n                    _diag("REPOSITORY initial scan exception\\n" + traceback.format_exc())\n',
        "repository scan logging",
    )
    text = replace_once(
        text,
        '            return 0\n        except Exception as exc:  # noqa: BLE001\n            detail = f"{type(exc).__name__}: {exc}"\n',
        '            _diag(f"BOOT loop exit deferred_shutdown={deferred._shutdown} bridge_shutdown={bridge._shutdown} destroyed={bool(getattr(tool, \'_headless_destroyed\', False))}")\n            return 0\n        except Exception as exc:  # noqa: BLE001\n            detail = f"{type(exc).__name__}: {exc}"\n            _diag("BOOT fatal exception " + detail + "\\n" + traceback.format_exc())\n',
        "headless fatal logging",
    )
    text = replace_once(
        text,
        '        finally:\n            if tool is not None:\n',
        '        finally:\n            _diag("BOOT backend cleanup begin")\n            if tool is not None:\n',
        "headless cleanup logging",
    )
    path.write_text(text, encoding="utf-8")


def patch_headless_core(path: pathlib.Path) -> None:
    text = path.read_text(encoding="utf-8")
    if "from JARNSEN_FRAMEWORK7_HEADLESS_BOOT import _diag" not in text:
        text = replace_once(
            text,
            'from typing import Any, Callable\n',
            'from typing import Any, Callable\n\nfrom JARNSEN_FRAMEWORK7_HEADLESS_BOOT import _diag\n',
            "headless core diag import",
        )
    text = replace_once(
        text,
        '                try:\n                    if not self.closed:\n                        callback(*args)\n                finally:\n',
        '                try:\n                    if not self.closed:\n                        callback(*args)\n                except BaseException:\n                    import traceback as _traceback\n                    _diag(f"SCHEDULER callback exception callback={getattr(callback, \'__name__\', repr(callback))}\\n{_traceback.format_exc()}")\n                    raise\n                finally:\n',
        "scheduler exception logging",
    )
    anchor = '''            self.status_text_var = HeadlessValue("Bereit")\n            self.status_var = self.status_text_var\n'''
    replacement = '''            self.status_text_var = HeadlessValue("Bereit")\n            self.status_var = self.status_text_var\n            # Legacy USB workers still touch these presentation controls. Keep\n            # them as pure-Python proxies in the Framework7 headless runtime.\n            self.start_button = HeadlessLabel("Start")\n            self.cancel_button = HeadlessLabel("Abbrechen")\n            self.auto_usb_log_var = HeadlessValue(True)\n            self.result_text = HeadlessText()\n'''
    if "self.auto_usb_log_var = HeadlessValue(True)" not in text:
        text = replace_once(text, anchor, replacement, "headless USB control proxies")
    if "def set_result(self, text: str)" not in text:
        text = replace_once(
            text,
            '    def set_status(self, text: str, level: str = "normal") -> None:\n        self.status_text_var.set(str(text or ""))\n        self.status_level = str(level or "normal")\n\n    def _build_ui(self) -> None:\n',
            '    def set_status(self, text: str, level: str = "normal") -> None:\n        self.status_text_var.set(str(text or ""))\n        self.status_level = str(level or "normal")\n\n    def set_result(self, text: str) -> None:\n        self.result_text.delete("1.0", "end")\n        self.result_text.insert("end", str(text or ""))\n        _diag(f"RESULT {str(text or \'\')[:800]}")\n\n    def _build_ui(self) -> None:\n',
            "headless set_result",
        )
    text = replace_once(
        text,
        '                text = str(payload or "")\n                if kind in {"status", "status_normal", "status_success", "status_warning", "status_error"}:\n',
        '                text = str(payload or "")\n                _diag(f"EVENT kind={kind} payload={text[:1000]}")\n                if kind in {"status", "status_normal", "status_success", "status_warning", "status_error"}:\n',
        "headless event logging",
    )
    path.write_text(text, encoding="utf-8")


def patch_legacy_compat(path: pathlib.Path) -> None:
    text = path.read_text(encoding="utf-8")
    if "from JARNSEN_FRAMEWORK7_HEADLESS_BOOT import _diag" not in text:
        text = replace_once(
            text,
            'from typing import Any\n',
            'from typing import Any\n\nfrom JARNSEN_FRAMEWORK7_HEADLESS_BOOT import _diag\n',
            "legacy compat diag import",
        )
    text = replace_once(
        text,
        '        candidates: list[Any] = []\n        with contextlib.suppress(Exception):\n            candidates = list(self.tool._auto_usb_log_candidates())\n',
        '        candidates: list[Any] = []\n        try:\n            candidates = list(self.tool._auto_usb_log_candidates())\n        except Exception as exc:\n            _diag(f"USB candidate scan exception {type(exc).__name__}: {exc}")\n            return []\n',
        "USB candidate exception logging",
    )
    text = replace_once(
        text,
        '        return result\n\n    def _current_usb_port(self: Any, node_id: str = "") -> str:\n',
        '        signature = tuple((str(item.get("device") or ""), str(item.get("identity") or ""), str(item.get("mapped_node_id") or "")) for item in result)\n        if self.__dict__.get("_diag_last_usb_signature") != signature:\n            self.__dict__["_diag_last_usb_signature"] = signature\n            _diag(f"USB targets changed count={len(result)} targets={result!r}")\n        return result\n\n    def _current_usb_port(self: Any, node_id: str = "") -> str:\n',
        "USB target timeline",
    )
    text = replace_once(
        text,
        '        value = self.call_ui(execute, timeout=30.0)\n        return {"ok": True, "result": value}\n',
        '        _diag(f"USB_LOG action requested node_id={node_id or \'--\'} payload={payload!r}")\n        try:\n            value = self.call_ui(execute, timeout=30.0)\n            _diag(f"USB_LOG action accepted result={value!r}")\n            return {"ok": True, "result": value}\n        except Exception as exc:\n            _diag(f"USB_LOG action exception {type(exc).__name__}: {exc}")\n            raise\n',
        "USB log action logging",
    )
    path.write_text(text, encoding="utf-8")


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: patch_framework7_full_diagnostics_v313.py <tools-dir>", file=sys.stderr)
        return 2
    root = pathlib.Path(sys.argv[1])
    patch_runtime(root / "JARNSEN_FRAMEWORK7_RUNTIME_FIXES_V312.py")
    patch_headless_boot(root / "JARNSEN_FRAMEWORK7_HEADLESS_BOOT.py")
    patch_headless_core(root / "JARNSEN_FRAMEWORK7_HEADLESS_CORE.py")
    patch_legacy_compat(root / "JARNSEN_FRAMEWORK7_LEGACY_COMPAT.py")
    print("Framework7 v3.13 full diagnostics and USB headless guards installed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
