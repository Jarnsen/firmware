"""Framework7 v3 desktop shell for the Jarnsen Node Service Tool.

The existing Tk service tool remains the proven device/service backend.  This
launcher runs that backend hidden in a child process, exposes a loopback-only JSON
bridge, and renders the visible UI with Framework7 in a Windows WebView.
"""
from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import inspect
import json
import os
import queue
import secrets
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable

APP_VERSION = "3.0.0"


def _resource_path(relative: str) -> Path:
    if getattr(sys, "frozen", False):
        root = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    else:
        root = Path(__file__).resolve().parent
    return root / relative


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (dt.datetime, dt.date)):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(item) for item in value]
    try:
        return dict(value)
    except Exception:
        return str(value)


class LegacyBridge:
    def __init__(self, tool: Any):
        self.tool = tool
        self.tk_host = self._resolve_tk_host(tool)
        self._shutdown = False
        self.activity: list[str] = []
        if not isinstance(getattr(tool, "mac_activity_events_v220", None), list):
            tool.mac_activity_events_v220 = self.activity
        else:
            self.activity = tool.mac_activity_events_v220

    @staticmethod
    def _resolve_tk_host(tool: Any) -> Any:
        root = getattr(tool, "root", tool)
        with contextlib.suppress(Exception):
            return root.winfo_toplevel()
        return root

    def call_ui(self, callback: Callable[[], Any], timeout: float = 90.0) -> Any:
        result: queue.Queue[tuple[bool, Any]] = queue.Queue(maxsize=1)

        def runner() -> None:
            try:
                result.put((True, callback()))
            except Exception as exc:  # noqa: BLE001
                result.put((False, exc))

        self.tk_host.after(0, runner)
        ok, value = result.get(timeout=timeout)
        if not ok:
            raise value
        return value

    @staticmethod
    def _parse_when(value: object) -> dt.datetime | None:
        text = str(value or "").strip()
        if not text:
            return None
        try:
            parsed = dt.datetime.fromisoformat(text.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=dt.datetime.now().astimezone().tzinfo)
            return parsed.astimezone()
        except Exception:
            return None

    def _ble_reachable(self, status: dict[str, Any] | None) -> bool:
        if not status:
            return False
        seen = self._parse_when(status.get("last_seen"))
        if seen is None:
            return False
        return (dt.datetime.now().astimezone() - seen).total_seconds() <= 90

    def _node_snapshot(self, row: Any) -> dict[str, Any]:
        data = dict(row)
        node_id = str(data.get("node_id") or "")
        latest = self.tool.repository.latest_log(node_id)
        metrics = dict((latest or {}).get("metrics") or {})
        device = str(data.get("device") or metrics.get("device") or "")
        build = str((latest or {}).get("build") or metrics.get("build") or "")
        firmware = str((latest or {}).get("firmware") or metrics.get("firmware") or "--")
        ble_status = None
        if hasattr(self.tool.repository, "ble_status_for_node_v2132"):
            ble_status = self.tool.repository.ble_status_for_node_v2132(node_id)
        reachable = self._ble_reachable(dict(ble_status) if ble_status else None)
        due = True
        if hasattr(self.tool, "_node_is_due_v2133"):
            with contextlib.suppress(Exception):
                due = bool(self.tool._node_is_due_v2133(node_id))
        update = False
        update_text = ""
        update_level = ""
        if hasattr(self.tool, "firmware_state"):
            with contextlib.suppress(Exception):
                state, detail, level = self.tool.firmware_state(device, build)
                update_text = str(state or detail or "")
                update_level = str(level or "")
                update = update_level == "warning" or "update" in update_text.lower()
        battery_raw = metrics.get("battery_pct")
        try:
            battery = float(battery_raw) if battery_raw not in (None, "") else None
        except Exception:
            battery = None
        warning_count = int(metrics.get("warning_count") or 0)
        sync_state = str(getattr(self.tool, "node_sync_state_v2132", {}).get(node_id) or "")
        captured_at = str((latest or {}).get("captured_at") or data.get("last_seen") or "")
        return {
            "node_id": node_id,
            "long_name": str(metrics.get("long_name") or data.get("long_name") or node_id),
            "short_name": str(metrics.get("short_name") or data.get("short_name") or ""),
            "device": device,
            "device_label": "Tracker V1.1" if device == "HELTEC_TRACKER_V1.1" else ("Heltec V3" if device == "HELTEC_V3_REPEATER" else device or "Unbekannt"),
            "battery": battery,
            "firmware": firmware,
            "build": build,
            "captured_at": captured_at,
            "ble_reachable": reachable,
            "ble": dict(ble_status) if ble_status else None,
            "log_due": due,
            "update": update,
            "update_text": update_text,
            "update_level": update_level,
            "warning_count": warning_count,
            "attention": bool(warning_count or (battery is not None and battery <= 20)),
            "sync_state": sync_state,
            "archived": bool(data.get("archived") or False),
            "metrics": metrics,
        }

    def state(self) -> dict[str, Any]:
        def collect() -> dict[str, Any]:
            try:
                rows = self.tool.repository.list_nodes(False)
            except TypeError:
                rows = self.tool.repository.list_nodes()
            nodes = [self._node_snapshot(row) for row in rows]
            nodes.sort(key=lambda item: (not item["attention"], not item["update"], not item["ble_reachable"], item["long_name"].lower()))
            ble_count = sum(1 for item in nodes if item["ble_reachable"])
            due_count = sum(1 for item in nodes if item["log_due"])
            updates = sum(1 for item in nodes if item["update"])
            warnings = sum(1 for item in nodes if item["attention"])
            status = "Bereit"
            for attr in ("status_var", "status_text_var"):
                variable = getattr(self.tool, attr, None)
                if variable is not None:
                    with contextlib.suppress(Exception):
                        text = str(variable.get() or "").strip()
                        if text:
                            status = text
                            break
            return {
                "version": APP_VERSION,
                "backend_version": str(getattr(sys.modules.get("JARNSEN_NODE_SERVICE_TOOL"), "APP_VERSION", "")),
                "status": status,
                "busy": bool(getattr(self.tool, "worker_running", False)),
                "nodes": nodes,
                "summary": {
                    "nodes": len(nodes),
                    "ble": ble_count,
                    "logs_due": due_count,
                    "updates": updates,
                    "warnings": warnings,
                },
                "activity": list(self.activity[-100:]),
                "settings": {
                    "auto_ble": True,
                    "ble_scan_seconds": 30,
                    "log_freshness_minutes": 15,
                    "pin": "240180",
                    "transport_priority": "USB → BLE",
                },
            }

        return _json_safe(self.call_ui(collect, timeout=15.0))

    def node_logs(self, node_id: str) -> list[dict[str, Any]]:
        def collect() -> list[dict[str, Any]]:
            rows = self.tool.repository.logs_for_node(node_id)
            return [_json_safe(dict(row)) for row in rows]

        return self.call_ui(collect, timeout=15.0)

    def _select_nodes(self, node_ids: list[str]) -> None:
        states = getattr(self.tool, "node_selection_v2133", None)
        if not isinstance(states, dict):
            return
        normalized = {str(value or "").strip().lower() for value in node_ids}
        for key, variable in states.items():
            with contextlib.suppress(Exception):
                variable.set(str(key).strip().lower() in normalized)

    def _invoke_batch(self, name: str, node_ids: list[str]) -> Any:
        function = getattr(self.tool, name)
        self._select_nodes(node_ids)
        try:
            signature = inspect.signature(function)
            if len(signature.parameters) >= 1:
                return function(node_ids)
        except Exception:
            pass
        return function()

    def action(self, payload: dict[str, Any]) -> dict[str, Any]:
        command = str(payload.get("command") or "").strip()
        node_ids = [str(item) for item in payload.get("node_ids") or [] if str(item).strip()]
        node_id = str(payload.get("node_id") or "").strip()
        if node_id and node_id not in node_ids:
            node_ids.append(node_id)

        def execute() -> Any:
            if command == "refresh":
                return self.tool.refresh_all_nodes_overview()
            if command == "scan_ble":
                return self.tool.auto_ble_refresh_v2132(False)
            if command == "download_log":
                return self._invoke_batch("batch_log_download_v2133", node_ids)
            if command == "wake":
                return self._invoke_batch("batch_wake_v2133", node_ids)
            if command == "ota":
                return self._invoke_batch("batch_ota_v2133", node_ids)
            if command == "live":
                return self._invoke_batch("batch_live_v2133", node_ids)
            if command == "delete":
                return self.tool._delete_node_ids_v2131(node_ids)
            if command == "firmware_check":
                function = getattr(self.tool, "check_github_update", None) or getattr(self.tool, "check_for_updates", None)
                if function is None:
                    raise RuntimeError("Firmwareprüfung ist in diesem Build nicht verfügbar")
                return function()
            if command == "shutdown":
                self._shutdown = True
                self.tk_host.after(50, self.tk_host.destroy)
                return True
            raise ValueError(f"Unbekannter Befehl: {command}")

        value = self.call_ui(execute, timeout=120.0)
        return {"ok": True, "result": _json_safe(value)}


class ApiHandler(BaseHTTPRequestHandler):
    bridge: LegacyBridge
    token: str

    def log_message(self, *_args: Any) -> None:
        return

    def _cors(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Jarnsen-Token")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Cache-Control", "no-store")

    def _authorized(self) -> bool:
        return self.headers.get("X-Jarnsen-Token", "") == self.token

    def _send(self, status: int, data: Any) -> None:
        body = json.dumps(_json_safe(data), ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self._cors()
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self) -> None:  # noqa: N802
        self.send_response(204)
        self._cors()
        self.end_headers()

    def do_GET(self) -> None:  # noqa: N802
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/health":
            self._send(200, {"ok": True, "version": APP_VERSION})
            return
        if not self._authorized():
            self._send(403, {"ok": False, "error": "forbidden"})
            return
        try:
            if parsed.path == "/api/state":
                self._send(200, self.bridge.state())
                return
            if parsed.path.startswith("/api/node/") and parsed.path.endswith("/logs"):
                node_id = urllib.parse.unquote(parsed.path[len("/api/node/") : -len("/logs")]).strip("/")
                self._send(200, {"logs": self.bridge.node_logs(node_id)})
                return
            self._send(404, {"ok": False, "error": "not-found"})
        except Exception as exc:  # noqa: BLE001
            self._send(500, {"ok": False, "error": str(exc), "type": type(exc).__name__})

    def do_POST(self) -> None:  # noqa: N802
        if not self._authorized():
            self._send(403, {"ok": False, "error": "forbidden"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0") or 0)
            payload = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
            if self.path == "/api/action":
                self._send(200, self.bridge.action(payload))
                return
            self._send(404, {"ok": False, "error": "not-found"})
        except Exception as exc:  # noqa: BLE001
            self._send(500, {"ok": False, "error": str(exc), "type": type(exc).__name__})


def _backend(port: int, token: str) -> int:
    import JARNSEN_NODE_SERVICE_TOOL as legacy

    # The old UI is intentionally kept only as an implementation backend.
    if hasattr(legacy.ServiceTool, "_install_mac_shell_v220"):
        legacy.ServiceTool._install_mac_shell_v220 = lambda self: None
    tool = legacy.ServiceTool()
    host = LegacyBridge._resolve_tk_host(tool)
    with contextlib.suppress(Exception):
        host.withdraw()
    bridge = LegacyBridge(tool)

    handler = type("JarnsenApiHandler", (ApiHandler,), {"bridge": bridge, "token": token})
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


def _wait_for_backend(base_url: str, timeout: float = 30.0) -> None:
    deadline = time.monotonic() + timeout
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(f"{base_url}/health", timeout=1.0) as response:
                if response.status == 200:
                    return
        except Exception as exc:  # noqa: BLE001
            last_error = exc
        time.sleep(0.15)
    raise RuntimeError(f"Service-Backend konnte nicht gestartet werden: {last_error}")


def _frontend(debug: bool = False) -> int:
    import webview

    port = _free_port()
    token = secrets.token_urlsafe(24)
    base_url = f"http://127.0.0.1:{port}"
    if getattr(sys, "frozen", False):
        command = [sys.executable, "--f7-backend", "--port", str(port), "--token", token]
    else:
        command = [sys.executable, str(Path(__file__).resolve()), "--f7-backend", "--port", str(port), "--token", token]
    flags = 0
    if os.name == "nt":
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    backend = subprocess.Popen(command, creationflags=flags)
    try:
        _wait_for_backend(base_url)
        index = _resource_path("service_tool_web/index.html")
        if not index.exists():
            raise FileNotFoundError(f"Framework7 UI fehlt: {index}")
        query = urllib.parse.urlencode({"api": base_url, "token": token, "version": APP_VERSION})
        url = index.resolve().as_uri() + "?" + query
        window = webview.create_window(
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


def _self_test() -> int:
    required = [
        _resource_path("service_tool_web/index.html"),
        _resource_path("service_tool_web/app.css"),
        _resource_path("service_tool_web/app.js"),
        _resource_path("service_tool_web/vendor/framework7-bundle.min.css"),
        _resource_path("service_tool_web/vendor/framework7-bundle.min.js"),
    ]
    missing = [str(path) for path in required if not path.exists()]
    output = Path.cwd() / "Jarnsen-Node-Service-Tool-self-test.txt"
    if missing:
        output.write_text("Framework7 self-test FAILED\nMissing:\n" + "\n".join(missing), encoding="utf-8")
        return 2
    output.write_text(
        "Framework7 self-test OK\n"
        f"version={APP_VERSION}\n"
        "shell=Framework7 9.1.3 / iOS theme\n"
        "backend=legacy Python service core\n",
        encoding="utf-8",
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(add_help=True)
    parser.add_argument("--f7-backend", action="store_true")
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--token", default="")
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--debug-webview", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        return _self_test()
    if args.f7_backend:
        if not args.port or not args.token:
            raise SystemExit("--f7-backend benötigt --port und --token")
        return _backend(args.port, args.token)
    return _frontend(args.debug_webview)


if __name__ == "__main__":
    raise SystemExit(main())
