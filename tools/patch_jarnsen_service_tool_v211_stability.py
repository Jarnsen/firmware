"""v2.1.1 stability: persistent tool log, Tcl/Tk startup guard, BLE discovery fallback."""
from __future__ import annotations

import re
import sys
from pathlib import Path

APP_VERSION = "2.1.1"


def method_span(text: str, name: str) -> tuple[int, int]:
    start = text.find(f"    def {name}(")
    if start < 0:
        raise SystemExit(f"method {name} not found")
    match = re.search(r"\n    (?=@|def )", text[start + 1 :])
    end = start + 1 + match.start() if match else len(text)
    return start, end


def replace_method(text: str, name: str, updater) -> str:
    start, end = method_span(text, name)
    return text[:start] + updater(text[start:end]) + text[end:]


def function_span(text: str, name: str) -> tuple[int, int]:
    start = text.find(f"def {name}(")
    if start < 0:
        raise SystemExit(f"function {name} not found")
    match = re.search(r"\n(?=@|def |class )", text[start + 1 :])
    end = start + 1 + match.start() if match else len(text)
    return start, end


def replace_function(text: str, name: str, updater) -> str:
    start, end = function_span(text, name)
    return text[:start] + updater(text[start:end]) + text[end:]


def patch(source: str) -> str:
    source = re.sub(r'APP_VERSION = "[^"]+"', f'APP_VERSION = "{APP_VERSION}"', source, count=1)
    source = source.replace('APP_VERSION != "2.1.0"', 'APP_VERSION != "2.1.1"')
    source = source.replace("App-Version ist nicht v2.1.0", "App-Version ist nicht v2.1.1")

    if "import platform\n" not in source:
        source = source.replace("import os\n", "import os\nimport platform\n", 1)
    if "import traceback\n" not in source:
        source = source.replace("import threading\n", "import threading\nimport traceback\n", 1)

    anchor = "\ndef header_value(payload: bytes, name: bytes) -> str:\n"
    if "def init_tool_log()" not in source:
        diagnostics = r'''
_TOOL_LOG_LOCK = threading.Lock()
_TOOL_LOG_PATH: pathlib.Path | None = None


def tool_log_directory() -> pathlib.Path:
    target = output_directory() / "Tool-Logs"
    target.mkdir(parents=True, exist_ok=True)
    return target


def init_tool_log() -> pathlib.Path | None:
    global _TOOL_LOG_PATH
    if _TOOL_LOG_PATH is not None:
        return _TOOL_LOG_PATH
    try:
        directory = tool_log_directory()
        stamp = now_local().strftime("%Y-%m-%d_%H%M%S")
        _TOOL_LOG_PATH = directory / f"Jarnsen-Service-Tool_{stamp}_{os.getpid()}.log"
        _TOOL_LOG_PATH.touch(exist_ok=True)
        logs = sorted(
            directory.glob("Jarnsen-Service-Tool_*.log"),
            key=lambda item: item.stat().st_mtime,
            reverse=True,
        )
        for old in logs[20:]:
            with contextlib.suppress(OSError):
                old.unlink()
        return _TOOL_LOG_PATH
    except Exception:
        _TOOL_LOG_PATH = None
        return None


def _tool_log_value(value: object) -> str:
    text = str(value).replace("\r", "\\r").replace("\n", "\\n")
    return text[:1200]


def tool_log(event: str, **fields: object) -> None:
    path = init_tool_log()
    if path is None:
        return
    timestamp = now_local().isoformat(timespec="milliseconds")
    detail = " ".join(f"{key}={_tool_log_value(value)}" for key, value in fields.items())
    line = f"{timestamp} | {event}" + (f" | {detail}" if detail else "") + "\n"
    try:
        with _TOOL_LOG_LOCK:
            with path.open("a", encoding="utf-8") as handle:
                handle.write(line)
    except Exception:
        pass


def tool_log_exception(context: str, exc: BaseException) -> None:
    tool_log(
        "EXCEPTION",
        context=context,
        type=type(exc).__name__,
        message=exc,
        traceback="".join(traceback.format_exception(type(exc), exc, exc.__traceback__)),
    )


def configure_frozen_tcl_tk() -> None:
    frozen = bool(getattr(sys, "frozen", False))
    meipass = pathlib.Path(str(getattr(sys, "_MEIPASS", ""))) if frozen else None
    tool_log(
        "STARTUP_ENV",
        version=APP_VERSION,
        build=os.environ.get("APP_BUILD_SHA", "--"),
        executable=sys.executable,
        cwd=pathlib.Path.cwd(),
        python=sys.version.replace("\n", " "),
        platform=platform.platform(),
        frozen=frozen,
        meipass=meipass or "--",
        tcl_env=os.environ.get("TCL_LIBRARY", "--"),
        tk_env=os.environ.get("TK_LIBRARY", "--"),
    )
    if not frozen or not meipass or not meipass.exists():
        return
    tcl_candidates = [
        meipass / "_tcl_data",
        meipass / "tcl8.6",
        meipass / "lib" / "tcl8.6",
    ]
    tk_candidates = [
        meipass / "_tk_data",
        meipass / "tk8.6",
        meipass / "lib" / "tk8.6",
    ]
    with contextlib.suppress(Exception):
        for found in meipass.rglob("init.tcl"):
            tcl_candidates.append(found.parent)
    with contextlib.suppress(Exception):
        for found in meipass.rglob("tk.tcl"):
            tk_candidates.append(found.parent)
    tcl_dir = next((item for item in tcl_candidates if (item / "init.tcl").is_file()), None)
    tk_dir = next((item for item in tk_candidates if (item / "tk.tcl").is_file()), None)
    if tcl_dir:
        os.environ["TCL_LIBRARY"] = str(tcl_dir)
    if tk_dir:
        os.environ["TK_LIBRARY"] = str(tk_dir)
    tool_log(
        "TCL_TK_RESOLVE",
        tcl=tcl_dir or "NICHT_GEFUNDEN",
        tk=tk_dir or "NICHT_GEFUNDEN",
        tcl_candidates=";".join(str(item) for item in tcl_candidates[:12]),
        tk_candidates=";".join(str(item) for item in tk_candidates[:12]),
    )


def install_tool_exception_hooks() -> None:
    previous_sys_hook = sys.excepthook

    def sys_hook(exc_type, exc_value, exc_tb):
        if isinstance(exc_value, BaseException):
            tool_log_exception("sys.excepthook", exc_value)
        previous_sys_hook(exc_type, exc_value, exc_tb)

    sys.excepthook = sys_hook
    if hasattr(threading, "excepthook"):
        previous_thread_hook = threading.excepthook

        def thread_hook(args):
            if isinstance(args.exc_value, BaseException):
                tool_log_exception(f"thread:{getattr(args.thread, 'name', '--')}", args.exc_value)
            previous_thread_hook(args)

        threading.excepthook = thread_hook
'''
        if source.count(anchor) != 1:
            raise SystemExit("diagnostic helper anchor not found")
        source = source.replace(anchor, "\n" + diagnostics.strip() + "\n\n" + anchor.lstrip("\n"), 1)

    def patch_workflow_ui(method: str) -> str:
        if '"Tool-Log öffnen", self.open_tool_log' not in method:
            action_anchor = '            ("Service-WLAN öffnen", self.open_service_wlan, "TButton"),\n'
            if method.count(action_anchor) != 1:
                raise SystemExit("service Tool-Log action anchor not found")
            method = method.replace(
                action_anchor,
                action_anchor + '            ("Tool-Log öffnen", self.open_tool_log, "TButton"),\n',
                1,
            )
        return method

    source = replace_method(source, "_install_workflow_ui", patch_workflow_ui)

    if "    def open_tool_log(self)" not in source:
        open_log_method = r'''    def open_tool_log(self) -> None:
        path = init_tool_log()
        target = path if path and path.exists() else tool_log_directory()
        tool_log("TOOL_LOG_OPEN", target=target)
        try:
            if os.name == "nt":
                os.startfile(str(target))  # type: ignore[attr-defined]
            else:
                raise RuntimeError("Tool-Log kann auf diesem System nicht automatisch geöffnet werden")
        except Exception as exc:
            tool_log_exception("open_tool_log", exc)
            messagebox.showerror("Tool-Log", f"Tool-Log:\n{target}\n\n{exc}")

    def report_callback_exception(self, exc_type, exc_value, exc_traceback) -> None:
        if isinstance(exc_value, BaseException):
            tool_log_exception("tk_callback", exc_value)
        message = "".join(traceback.format_exception(exc_type, exc_value, exc_traceback))
        with contextlib.suppress(Exception):
            self.set_result("Tool-Fehler:\n" + message)
        with contextlib.suppress(Exception):
            messagebox.showerror(
                "Tool-Fehler",
                f"Ein interner Fehler wurde protokolliert.\n\nTool-Log:\n{init_tool_log()}",
            )
'''
        start, _ = method_span(source, "close_app")
        source = source[:start] + open_log_method.rstrip() + "\n\n" + source[start:]

    def patch_close_app(method: str) -> str:
        if 'tool_log("APP_SHUTDOWN"' not in method:
            first_line = method.find("\n") + 1
            method = method[:first_line] + '        tool_log("APP_SHUTDOWN", clean=True)\n' + method[first_line:]
        return method

    source = replace_method(source, "close_app", patch_close_app)

    def patch_scan_ble(method: str) -> str:
        return r'''    def _ble_scan_worker(self) -> None:
        started_at = time.monotonic()
        tool_log("BLE_SCAN_START", timeout_s=8.0)
        try:
            devices = asyncio.run(BleakScanner.discover(timeout=8.0, return_adv=True))
            verified: dict[str, object] = {}
            fallback: dict[str, object] = {}
            known_names: set[str] = set()
            with contextlib.suppress(Exception):
                for row in self.repository.list_nodes(True):
                    for value in (row["long_name"], row["short_name"]):
                        if value:
                            known_names.add(str(value).strip().lower())
            for device, advertisement in devices.values():
                advertised_name = str(getattr(advertisement, "local_name", "") or "").strip()
                device_name = str(getattr(device, "name", "") or "").strip()
                name = device_name or advertised_name or "Unbenanntes BLE-Gerät"
                address = str(getattr(device, "address", "--"))
                service_uuids = {
                    str(value).lower() for value in (getattr(advertisement, "service_uuids", None) or [])
                }
                tool_log(
                    "BLE_DEVICE",
                    name=name,
                    address=address,
                    advertised_name=advertised_name or "--",
                    services=",".join(sorted(service_uuids)) or "--",
                    rssi=getattr(advertisement, "rssi", "--"),
                )
                if OTABT_SERVICE_UUID in service_uuids:
                    verified[f"[OTA] {name} - {address}"] = device
                elif MESH_SERVICE_UUID in service_uuids:
                    verified[f"{name} - {address}"] = device
                elif name != "Unbenanntes BLE-Gerät":
                    lowered = name.lower()
                    likely = (
                        any(candidate and candidate in lowered for candidate in known_names)
                        or any(token in lowered for token in ("meshtastic", "heltec", "tracker", "jarnsen", "v3"))
                    )
                    prefix = "[?] " if likely else "[BLE] "
                    fallback[f"{prefix}{name} - {address}"] = device
            found = verified if verified else fallback
            tool_log(
                "BLE_SCAN_DONE",
                duration_s=f"{time.monotonic() - started_at:.2f}",
                total=len(devices),
                verified=len(verified),
                fallback=len(fallback),
                shown=len(found),
                mode="verified" if verified else "fallback",
            )
            self.events.put(("ble_devices", (found, len(devices))))
            if not verified and fallback:
                self.events.put((
                    "status_warning",
                    "Keine Service-UUID im Windows-Scan sichtbar · BLE-Geräte als Prüfkandidaten angezeigt",
                ))
        except Exception as exc:
            tool_log_exception("ble_scan", exc)
            self.events.put(("error", f"Bluetooth-Suche fehlgeschlagen: {exc}"))
        finally:
            self.events.put(("ble_scan_done", None))
'''

    source = replace_method(source, "_ble_scan_worker", patch_scan_ble)

    def patch_download_worker(method: str) -> str:
        if 'tool_log("SERIAL_OPEN"' in method:
            return method
        method = method.replace(
            '        ser: serial.Serial | None = None\n        try:\n',
            '        ser: serial.Serial | None = None\n        worker_started_at = time.monotonic()\n        transfer_started_at: float | None = None\n        serial_bytes_received = 0\n        try:\n',
            1,
        )
        method = method.replace(
            '            ser.open()\n',
            '            ser.open()\n            tool_log("SERIAL_OPEN", port=port, baud=ser.baudrate, timeout=ser.timeout)\n',
            1,
        )
        method = method.replace(
            '                if chunk:\n                    scan.extend(chunk)\n',
            '                if chunk:\n                    serial_bytes_received += len(chunk)\n                    scan.extend(chunk)\n',
            1,
        )
        method = method.replace(
            '                    started = True\n                    self.events.put(("status", "Transfer erkannt"))\n',
            '                    started = True\n                    transfer_started_at = time.monotonic()\n                    tool_log("SERIAL_TRANSFER_BEGIN", port=port, begin_marker=begin or b"HEADER_RECOVERY")\n                    self.events.put(("status", "Transfer erkannt"))\n',
            1,
        )
        method = method.replace(
            '                    self._finish_payload(bytes(captured), expected)\n                    return\n',
            '                    elapsed = max(0.001, time.monotonic() - (transfer_started_at or worker_started_at))\n                    rate_kib = serial_bytes_received / elapsed / 1024.0\n                    tool_log("SERIAL_TRANSFER_DONE", port=port, bytes=serial_bytes_received, expected=expected, duration_s=f"{elapsed:.2f}", rate_kib_s=f"{rate_kib:.2f}")\n                    self._finish_payload(bytes(captured), expected)\n                    return\n',
            1,
        )
        method = method.replace(
            '        except serial.SerialException as exc:\n',
            '        except serial.SerialException as exc:\n            tool_log_exception("serial_download", exc)\n',
            1,
        )
        method = method.replace(
            '        except Exception as exc:\n            self.events.put(("error", str(exc)))\n',
            '        except Exception as exc:\n            tool_log_exception("serial_download", exc)\n            self.events.put(("error", str(exc)))\n',
            1,
        )
        method = method.replace(
            '        finally:\n            if ser and ser.is_open:\n',
            '        finally:\n            total_elapsed = max(0.001, time.monotonic() - worker_started_at)\n            tool_log("SERIAL_WORKER_END", port=port, bytes=serial_bytes_received, duration_s=f"{total_elapsed:.2f}")\n            if ser and ser.is_open:\n',
            1,
        )
        return method

    source = replace_method(source, "_download_worker", patch_download_worker)

    def patch_finish_payload(method: str) -> str:
        if 'tool_log("NODE_LOG_SAVED"' in method:
            return method
        needle = '        output.write_bytes(payload)\n'
        if needle not in method:
            raise SystemExit("payload save anchor not found")
        method = method.replace(
            needle,
            needle + '        tool_log("NODE_LOG_SAVED", path=output, bytes=len(payload), device=device, node_id=node_id, long_name=long_name)\n',
            1,
        )
        return method

    source = replace_method(source, "_finish_payload", patch_finish_payload)

    def patch_self_test(function: str) -> str:
        if "Tk-Initialisierung" in function:
            return function
        marker = '        if not RECYCLE_AVAILABLE:\n            raise RuntimeError("send2trash ist nicht verfügbar")\n'
        if marker not in function:
            raise SystemExit("self-test tkinter anchor not found")
        tk_test = marker + '''        configure_frozen_tcl_tk()\n        root = None\n        try:\n            root = tk.Tk()\n            root.withdraw()\n            root.update_idletasks()\n            tool_log("SELF_TEST_TK", tcl=root.tk.call("info", "patchlevel"), library=root.tk.call("info", "library"))\n        except Exception as exc:\n            tool_log_exception("self_test_tk", exc)\n            raise RuntimeError(f"Tk-Initialisierung fehlgeschlagen: {exc}") from exc\n        finally:\n            if root is not None:\n                with contextlib.suppress(Exception):\n                    root.destroy()\n'''
        function = function.replace(marker, tk_test, 1)
        function = function.replace(
            '"OK: BLE, Papierkorb, Datenbank, Positionskarte und fünf Layouts\\n",',
            '"OK: Tk/Tcl, BLE, Papierkorb, Datenbank, Positionskarte und fünf Layouts\\n",',
            1,
        )
        return function

    source = replace_function(source, "packaged_self_test", patch_self_test)

    main_old = '''if __name__ == "__main__":\n    if "--self-test" in sys.argv:\n        raise SystemExit(packaged_self_test())\n    ServiceTool().mainloop()\n'''
    main_new = '''if __name__ == "__main__":\n    init_tool_log()\n    install_tool_exception_hooks()\n    configure_frozen_tcl_tk()\n    tool_log("APP_START", argv=" ".join(sys.argv))\n    try:\n        if "--self-test" in sys.argv:\n            raise SystemExit(packaged_self_test())\n        app = ServiceTool()\n        tool_log("GUI_READY")\n        app.mainloop()\n    except SystemExit:\n        raise\n    except BaseException as exc:\n        tool_log_exception("fatal_startup_or_mainloop", exc)\n        raise\n'''
    if main_new not in source:
        if source.count(main_old) != 1:
            raise SystemExit("main startup anchor not found")
        source = source.replace(main_old, main_new, 1)

    required = (
        'APP_VERSION = "2.1.1"',
        "def init_tool_log()",
        "def configure_frozen_tcl_tk()",
        "def tool_log_exception(",
        '"Tool-Log öffnen", self.open_tool_log',
        "def open_tool_log(self)",
        "def report_callback_exception(self",
        'tool_log("BLE_SCAN_START"',
        "BLE_DEVICE",
        "fallback",
        'tool_log("SERIAL_TRANSFER_DONE"',
        "rate_kib_s",
        "Tk-Initialisierung fehlgeschlagen",
        'tool_log("APP_START"',
        'tool_log("GUI_READY"',
    )
    for marker in required:
        if marker not in source:
            raise SystemExit(f"missing v2.1.1 marker: {marker}")
    return source


def main() -> None:
    target = Path(sys.argv[1] if len(sys.argv) > 1 else "tools/JARNSEN_NODE_SERVICE_TOOL.py")
    target.write_text(patch(target.read_text(encoding="utf-8")), encoding="utf-8")
    print("Service tool v2.1.1: tool diagnostics + Tcl/Tk startup + BLE fallback")


if __name__ == "__main__":
    main()
