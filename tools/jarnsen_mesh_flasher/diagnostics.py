from __future__ import annotations

import importlib.metadata
import os
import platform
import re
import shutil
import subprocess
import sys
import threading
import time
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any


_LOCK = threading.Lock()
_LOG_PATH: Path | None = None
_INSTALLED = False

_SENSITIVE = re.compile(
    r"(?i)(authorization|bearer|token|password|passwd|secret|private[_ -]?key|admin[_ -]?key|\bpsk\b)"
)


def _redact(text: Any) -> str:
    value = "" if text is None else str(text)
    lines: list[str] = []
    for line in value.splitlines() or [value]:
        if _SENSITIVE.search(line):
            if ":" in line:
                key = line.split(":", 1)[0]
                line = f"{key}: <redacted>"
            elif "=" in line:
                key = line.split("=", 1)[0]
                line = f"{key}=<redacted>"
            else:
                line = "<redacted sensitive line>"
        lines.append(line)
    return "\n".join(lines)


def _emit(message: str) -> None:
    if _LOG_PATH is None:
        return
    stamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
    thread = threading.current_thread().name
    line = f"[{stamp}] [DIAG:{thread}] {_redact(message)}"
    try:
        with _LOCK:
            with _LOG_PATH.open("a", encoding="utf-8") as handle:
                handle.write(line + "\n")
    except Exception:
        pass


def _emit_block(title: str, text: Any, *, max_chars: int = 60000) -> None:
    value = _redact(text)
    if not value.strip():
        _emit(f"{title}: <empty>")
        return
    if len(value) > max_chars:
        value = value[:max_chars] + f"\n... <truncated, total {len(value)} chars>"
    _emit(f"{title}: BEGIN")
    for line in value.splitlines():
        _emit(f"{title}> {line}")
    _emit(f"{title}: END")


def _format_command(cmd: list[str]) -> str:
    safe: list[str] = []
    hide_next = False
    for arg in cmd:
        if hide_next:
            safe.append("<redacted>")
            hide_next = False
            continue
        low = str(arg).lower()
        safe.append(str(arg))
        if low in {"--token", "--password", "--psk", "--private-key", "--admin-key"}:
            hide_next = True
    return subprocess.list2cmdline(safe)


def _decode_timeout_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def _run_diag_command(title: str, command: list[str], *, timeout: int = 15) -> None:
    _emit(f"SYSTEM CMD START title={title!r} timeout={timeout}s cmd={_format_command(command)}")
    started = time.perf_counter()
    try:
        proc = subprocess.run(
            command,
            text=True,
            capture_output=True,
            timeout=timeout,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
    except subprocess.TimeoutExpired as exc:
        _emit(f"SYSTEM CMD TIMEOUT title={title!r} duration={time.perf_counter()-started:.3f}s")
        _emit_block(f"{title} TIMEOUT STDOUT", _decode_timeout_value(exc.stdout))
        _emit_block(f"{title} TIMEOUT STDERR", _decode_timeout_value(exc.stderr))
        return
    except Exception as exc:
        _emit(
            f"SYSTEM CMD EXCEPTION title={title!r} duration={time.perf_counter()-started:.3f}s "
            f"type={type(exc).__name__} message={exc}"
        )
        return

    _emit(
        f"SYSTEM CMD END title={title!r} exit={proc.returncode} "
        f"duration={time.perf_counter()-started:.3f}s"
    )
    _emit_block(f"{title} STDOUT", proc.stdout)
    _emit_block(f"{title} STDERR", proc.stderr)


def _registry_serial_ports() -> list[tuple[str, str]]:
    if os.name != "nt":
        return []
    result: list[tuple[str, str]] = []
    try:
        import winreg

        key_path = r"HARDWARE\DEVICEMAP\SERIALCOMM"
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key_path) as key:
            index = 0
            while True:
                try:
                    name, value, _kind = winreg.EnumValue(key, index)
                except OSError:
                    break
                result.append((str(name), str(value)))
                index += 1
    except Exception as exc:
        _emit(f"SERIAL REGISTRY READ FAILURE type={type(exc).__name__} message={exc}")
    return result


def _is_bluetooth_port(*values: Any) -> bool:
    text = " ".join(str(value or "") for value in values).upper()
    return any(token in text for token in ("BTHENUM", "BLUETOOTH", "BTHMODEM", "RFCOMM"))


def _windows_snapshot(stage: str) -> None:
    if os.name != "nt":
        return
    _emit(f"WINDOWS DEVICE SNAPSHOT START stage={stage}")

    registry = _registry_serial_ports()
    _emit(f"SERIAL REGISTRY count={len(registry)}")
    for name, port in registry:
        _emit(
            f"SERIAL REGISTRY ENTRY device_name={name!r} port={port!r} "
            f"bluetooth={_is_bluetooth_port(name)}"
        )

    commands: list[tuple[str, list[str], int]] = [
        (
            "REG SERIALCOMM",
            ["reg", "query", r"HKLM\HARDWARE\DEVICEMAP\SERIALCOMM"],
            10,
        ),
        (
            "PNPUTIL PORTS",
            ["pnputil", "/enum-devices", "/connected", "/class", "Ports"],
            15,
        ),
        (
            "POWERSHELL Win32_SerialPort",
            [
                "powershell.exe",
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                "$ErrorActionPreference='Continue'; "
                "Get-CimInstance Win32_SerialPort | "
                "Select-Object DeviceID,Name,Description,PNPDeviceID,ProviderType,Status,ConfigManagerErrorCode | "
                "Format-List | Out-String -Width 4096",
            ],
            20,
        ),
        (
            "POWERSHELL Present Ports",
            [
                "powershell.exe",
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                "$ErrorActionPreference='Continue'; "
                "Get-PnpDevice -PresentOnly -Class Ports | "
                "Select-Object Status,Class,FriendlyName,InstanceId,Problem,ProblemStatus | "
                "Format-List | Out-String -Width 4096",
            ],
            20,
        ),
        (
            "POWERSHELL ESP USB candidates",
            [
                "powershell.exe",
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                "$ErrorActionPreference='Continue'; "
                "Get-PnpDevice -PresentOnly | Where-Object { "
                "$_.FriendlyName -match 'COM|ESP32|ESPRESSIF|HELTEC|CP210|CH340|CH341|USB JTAG|USB Serial|CDC' "
                "-or $_.InstanceId -match 'VID_303A|VID_10C4|VID_1A86|USB\\VID_' } | "
                "Select-Object Status,Class,FriendlyName,InstanceId,Problem,ProblemStatus | "
                "Format-List | Out-String -Width 4096",
            ],
            25,
        ),
    ]

    for title, command, timeout in commands:
        _run_diag_command(title, command, timeout=timeout)

    handle = shutil.which("handle.exe") or shutil.which("handle64.exe")
    _emit(f"SYSINTERNALS HANDLE available={bool(handle)} path={handle or '-'}")
    _emit(f"WINDOWS DEVICE SNAPSHOT END stage={stage}")


def _start_windows_snapshot(stage: str) -> None:
    if os.name != "nt":
        return
    threading.Thread(
        target=_windows_snapshot,
        args=(stage,),
        name=f"diag-windows-{stage}",
        daemon=True,
    ).start()


def _log_runtime_versions() -> None:
    for package in (
        "pyserial",
        "meshtastic",
        "esptool",
        "requests",
        "customtkinter",
        "cryptography",
        "protobuf",
        "pyinstaller",
    ):
        try:
            version = importlib.metadata.version(package)
        except Exception as exc:
            version = f"unavailable ({type(exc).__name__})"
        _emit(f"PACKAGE {package}={version}")


def _install_exception_hooks() -> None:
    original_sys_hook = sys.excepthook

    def sys_hook(exc_type, exc_value, exc_traceback):
        _emit_block(
            "UNCAUGHT MAIN EXCEPTION",
            "".join(traceback.format_exception(exc_type, exc_value, exc_traceback)),
        )
        original_sys_hook(exc_type, exc_value, exc_traceback)

    sys.excepthook = sys_hook

    if hasattr(threading, "excepthook"):
        original_thread_hook = threading.excepthook

        def thread_hook(args):
            _emit_block(
                f"UNCAUGHT THREAD EXCEPTION {getattr(args.thread, 'name', '-')}",
                "".join(traceback.format_exception(args.exc_type, args.exc_value, args.exc_traceback)),
            )
            original_thread_hook(args)

        threading.excepthook = thread_hook


def install(services: Any, log_dir: Path) -> Path:
    global _INSTALLED, _LOG_PATH
    if _INSTALLED and _LOG_PATH is not None:
        return _LOG_PATH

    log_dir.mkdir(parents=True, exist_ok=True)
    _LOG_PATH = log_dir / f"flasher-{datetime.now().strftime('%Y%m%d-%H%M%S')}.log"
    _INSTALLED = True

    # Force the GUI and the low-level diagnostics to use exactly the same file.
    services.PATHS.logs = log_dir
    services.make_log_file = lambda: _LOG_PATH

    _install_exception_hooks()

    def detailed_run_helper(
        tool: str,
        args: Any,
        *,
        timeout: int = 60,
        check: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        cmd = services.helper_command() + [tool, *[str(a) for a in args]]
        command_text = _format_command(cmd)
        _emit(f"PROCESS START tool={tool} timeout={timeout}s check={check}")
        _emit(f"PROCESS CMD {command_text}")
        started = time.perf_counter()
        try:
            proc = subprocess.run(
                cmd,
                text=True,
                capture_output=True,
                timeout=timeout,
                startupinfo=services._startupinfo(),
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
        except subprocess.TimeoutExpired as exc:
            elapsed = time.perf_counter() - started
            _emit(f"PROCESS TIMEOUT tool={tool} after={elapsed:.3f}s configured_timeout={timeout}s")
            _emit_block("TIMEOUT STDOUT", _decode_timeout_value(exc.stdout))
            _emit_block("TIMEOUT STDERR", _decode_timeout_value(exc.stderr))
            raise
        except Exception as exc:
            elapsed = time.perf_counter() - started
            _emit(f"PROCESS EXCEPTION tool={tool} after={elapsed:.3f}s type={type(exc).__name__} message={exc}")
            _emit_block("PROCESS EXCEPTION TRACEBACK", traceback.format_exc())
            raise

        elapsed = time.perf_counter() - started
        _emit(f"PROCESS END tool={tool} exit={proc.returncode} duration={elapsed:.3f}s")
        _emit_block("STDOUT", proc.stdout)
        _emit_block("STDERR", proc.stderr)
        if check and proc.returncode != 0:
            details = (proc.stderr or proc.stdout or "").strip()
            _emit(f"PROCESS FAILURE tool={tool} exit={proc.returncode}")
            raise services.FlasherError(details or f"{tool} fehlgeschlagen (Exit {proc.returncode})")
        return proc

    services.run_helper = detailed_run_helper

    def detailed_detect_board_from_text(text: str):
        upper = (text or "").upper()
        detected = None
        matched_token = None
        for key, profile_data in services.BOARD_PROFILES.items():
            for token in profile_data["match"]:
                if str(token).upper() in upper:
                    detected = key
                    matched_token = token
                    break
            if detected:
                break
        _emit(
            f"BOARD DETECT input_chars={len(text or '')} result={detected!r} "
            f"matched_token={matched_token!r}"
        )
        return detected

    services.detect_board_from_text = detailed_detect_board_from_text

    def _port_dict(item: Any) -> dict[str, Any]:
        return {
            "device": str(getattr(item, "device", "") or ""),
            "description": str(getattr(item, "description", "") or ""),
            "hwid": str(getattr(item, "hwid", "") or ""),
            "vid": getattr(item, "vid", None),
            "pid": getattr(item, "pid", None),
            "serial_number": getattr(item, "serial_number", None),
            "manufacturer": getattr(item, "manufacturer", None),
            "product": getattr(item, "product", None),
            "interface": getattr(item, "interface", None),
            "location": getattr(item, "location", None),
            "registry_name": "",
            "source": "pyserial",
        }

    def detailed_scan_devices(probe_timeout: int = 8):
        _emit(f"SERIAL SCAN START probe_timeout={probe_timeout}s")
        _start_windows_snapshot(f"scan-{datetime.now().strftime('%H%M%S')}")
        started_scan = time.perf_counter()

        try:
            pyserial_ports = list(services.list_ports.comports())
        except Exception as exc:
            _emit(f"SERIAL ENUMERATION ERROR type={type(exc).__name__} message={exc}")
            _emit_block("SERIAL ENUMERATION TRACEBACK", traceback.format_exc())
            pyserial_ports = []

        _emit(f"SERIAL PYSERIAL ENUMERATION count={len(pyserial_ports)}")
        records: list[dict[str, Any]] = []
        seen: set[str] = set()

        for index, item in enumerate(pyserial_ports, start=1):
            record = _port_dict(item)
            device_upper = record["device"].upper()
            if device_upper:
                seen.add(device_upper)
            bluetooth = _is_bluetooth_port(
                record["description"],
                record["hwid"],
                record["manufacturer"],
                record["product"],
            )
            record["bluetooth"] = bluetooth
            records.append(record)
            vid = f"0x{record['vid']:04X}" if record["vid"] is not None else "-"
            pid = f"0x{record['pid']:04X}" if record["pid"] is not None else "-"
            try:
                usb_info = item.usb_info() if hasattr(item, "usb_info") else ""
            except Exception as exc:
                usb_info = f"<usb_info error {type(exc).__name__}: {exc}>"
            _emit(
                "SERIAL PORT "
                f"#{index} source=pyserial device={record['device']} "
                f"description={record['description']!r} hwid={record['hwid']!r} "
                f"VID={vid} PID={pid} serial={record['serial_number']!r} "
                f"manufacturer={record['manufacturer']!r} product={record['product']!r} "
                f"interface={record['interface']!r} location={record['location']!r} "
                f"bluetooth={bluetooth} str={str(item)!r} usb_info={usb_info!r}"
            )

        registry_entries = _registry_serial_ports()
        _emit(f"SERIAL REGISTRY MERGE count={len(registry_entries)}")
        for registry_name, port in registry_entries:
            port_upper = port.upper()
            bluetooth = _is_bluetooth_port(registry_name, port)
            _emit(
                f"SERIAL REGISTRY MERGE ENTRY name={registry_name!r} port={port!r} "
                f"already_in_pyserial={port_upper in seen} bluetooth={bluetooth}"
            )
            if port_upper in seen:
                continue
            records.append(
                {
                    "device": port,
                    "description": f"Windows Registry Serial Port ({registry_name})",
                    "hwid": registry_name,
                    "vid": None,
                    "pid": None,
                    "serial_number": None,
                    "manufacturer": None,
                    "product": None,
                    "interface": None,
                    "location": None,
                    "registry_name": registry_name,
                    "source": "registry",
                    "bluetooth": bluetooth,
                }
            )
            seen.add(port_upper)

        non_bluetooth = [record for record in records if not record.get("bluetooth")]
        bluetooth_records = [record for record in records if record.get("bluetooth")]
        _emit(
            f"SERIAL CANDIDATES total={len(records)} usb_or_wired={len(non_bluetooth)} "
            f"bluetooth_skipped={len(bluetooth_records)}"
        )
        for record in bluetooth_records:
            _emit(
                f"SERIAL SKIP BLUETOOTH port={record['device']} description={record['description']!r} "
                f"hwid={record['hwid']!r}; reason=USB flasher does not probe RFCOMM/Bluetooth SPP"
            )

        def candidate_score(record: dict[str, Any]) -> tuple[int, str]:
            text = " ".join(
                str(record.get(key) or "")
                for key in ("description", "hwid", "manufacturer", "product", "interface", "registry_name")
            ).upper()
            preferred = any(
                token in text
                for token in (
                    "VID_303A",
                    "ESPRESSIF",
                    "ESP32",
                    "HELTEC",
                    "USB JTAG",
                    "USB SERIAL",
                    "CDC",
                    "CP210",
                    "SILICON LABS",
                    "CH340",
                    "CH341",
                    "VID_10C4",
                    "VID_1A86",
                    "USB",
                )
            )
            return (0 if preferred else 1, str(record.get("device") or ""))

        non_bluetooth.sort(key=candidate_score)
        devices = []

        if not non_bluetooth:
            _emit(
                "SERIAL NO WIRED CANDIDATES: Windows/pyserial currently expose no non-Bluetooth COM port. "
                "Check the parallel Windows PnP/registry snapshot for a missing driver, missing COM assignment, "
                "USB cable/power-only cable, or device enumeration failure."
            )

        for record in non_bluetooth:
            port = str(record["device"])
            description = str(record["description"] or "Serielles Gerät")
            _emit(
                f"SERIAL PROBE START port={port} source={record.get('source')} "
                f"description={description!r}"
            )
            probe_started = time.perf_counter()
            info_text = ""
            board_key = None
            meshtastic_error = ""

            try:
                result = services.meshtastic(port, "--info", timeout=probe_timeout, check=False)
                info_text = "\n".join(filter(None, (result.stdout, result.stderr)))
                board_key = services.detect_board_from_text(info_text)
                _emit(
                    f"SERIAL MESHTASTIC PROBE port={port} exit={result.returncode} "
                    f"chars={len(info_text)} board_key={board_key!r}"
                )
            except subprocess.TimeoutExpired as exc:
                meshtastic_error = f"TimeoutExpired after {probe_timeout}s"
                info_text = "\n".join(
                    filter(
                        None,
                        (_decode_timeout_value(exc.stdout), _decode_timeout_value(exc.stderr)),
                    )
                )
                _emit(
                    f"SERIAL MESHTASTIC TIMEOUT port={port} configured_timeout={probe_timeout}s "
                    f"captured_chars={len(info_text)}"
                )
            except Exception as exc:
                meshtastic_error = f"{type(exc).__name__}: {exc}"
                _emit(f"SERIAL MESHTASTIC EXCEPTION port={port} error={meshtastic_error}")
                _emit_block(f"SERIAL MESHTASTIC TRACEBACK {port}", traceback.format_exc())

            if board_key is None:
                # Only use esptool after the normal Meshtastic probe failed to identify
                # the node. This gives us a second independent serial stack and catches
                # devices that are already in ROM bootloader mode.
                _emit(f"SERIAL ESPTOOL FALLBACK START port={port}")
                try:
                    esp = services.esptool(port, "--chip", "auto", "chip_id", timeout=15, check=False)
                    esp_text = "\n".join(filter(None, (esp.stdout, esp.stderr)))
                    _emit(
                        f"SERIAL ESPTOOL FALLBACK END port={port} exit={esp.returncode} chars={len(esp_text)}"
                    )
                    if esp_text:
                        _emit_block(f"SERIAL ESPTOOL {port}", esp_text, max_chars=20000)
                        if info_text:
                            info_text += "\n\n--- ESPTOOL FALLBACK ---\n" + esp_text
                        else:
                            info_text = esp_text
                except subprocess.TimeoutExpired as exc:
                    _emit(f"SERIAL ESPTOOL FALLBACK TIMEOUT port={port}")
                    _emit_block(f"SERIAL ESPTOOL TIMEOUT STDOUT {port}", _decode_timeout_value(exc.stdout))
                    _emit_block(f"SERIAL ESPTOOL TIMEOUT STDERR {port}", _decode_timeout_value(exc.stderr))
                except Exception as exc:
                    _emit(
                        f"SERIAL ESPTOOL FALLBACK EXCEPTION port={port} "
                        f"type={type(exc).__name__} message={exc}"
                    )

            # If both stacks fail, perform one raw pyserial open/close test at the
            # very end. This is deliberately last because opening a USB serial port
            # may toggle DTR/RTS and reset an ESP32 board.
            if board_key is None and not info_text.strip():
                try:
                    import serial

                    _emit(f"SERIAL RAW OPEN TEST START port={port} baud=115200")
                    raw_started = time.perf_counter()
                    ser = serial.Serial(
                        port=port,
                        baudrate=115200,
                        timeout=0.2,
                        write_timeout=0.2,
                        rtscts=False,
                        dsrdtr=False,
                    )
                    try:
                        waiting = getattr(ser, "in_waiting", -1)
                        _emit(
                            f"SERIAL RAW OPEN TEST SUCCESS port={port} duration={time.perf_counter()-raw_started:.3f}s "
                            f"is_open={ser.is_open} in_waiting={waiting}"
                        )
                    finally:
                        ser.close()
                        _emit(f"SERIAL RAW OPEN TEST CLOSED port={port}")
                except Exception as exc:
                    _emit(
                        f"SERIAL RAW OPEN TEST FAILURE port={port} type={type(exc).__name__} message={exc}"
                    )
                    handle = shutil.which("handle.exe") or shutil.which("handle64.exe")
                    if handle:
                        _run_diag_command(f"HANDLE {port}", [handle, "-accepteula", port], timeout=10)

            devices.append(services.DeviceInfo(port, description, board_key, info_text))
            _emit(
                f"SERIAL PROBE END port={port} duration={time.perf_counter()-probe_started:.3f}s "
                f"board_key={board_key!r} model_text_chars={len(info_text)} "
                f"meshtastic_error={meshtastic_error!r}"
            )
            if info_text:
                _emit_block(f"SERIAL INFO {port}", info_text, max_chars=30000)

        _emit(
            f"SERIAL SCAN END duration={time.perf_counter()-started_scan:.3f}s "
            f"returned_devices={len(devices)} detected_boards={sum(1 for item in devices if item.board_key)}"
        )
        return devices

    services.scan_devices = detailed_scan_devices

    original_wait_for_serial = services.wait_for_serial

    def detailed_wait_for_serial(port: str, timeout: int = 90) -> None:
        _emit(f"SERIAL WAIT START port={port} timeout={timeout}s")
        started = time.perf_counter()
        last_ports: tuple[str, ...] = ()
        try:
            deadline = time.time() + timeout
            while time.time() < deadline:
                current = tuple(sorted(str(p.device) for p in services.list_ports.comports()))
                if current != last_ports:
                    _emit(f"SERIAL WAIT PORT SET port={port} visible_ports={current}")
                    last_ports = current
                if any(value.upper() == port.upper() for value in current):
                    time.sleep(3)
                    _emit(f"SERIAL WAIT END port={port} duration={time.perf_counter()-started:.3f}s")
                    return
                time.sleep(1)
            raise services.FlasherError(f"{port} ist nach dem Flash nicht wieder erschienen.")
        except Exception as exc:
            _emit(
                f"SERIAL WAIT FAILURE port={port} duration={time.perf_counter()-started:.3f}s "
                f"type={type(exc).__name__} message={exc}"
            )
            _start_windows_snapshot(f"wait-failure-{port}")
            raise

    services.wait_for_serial = detailed_wait_for_serial

    client_cls = services.GitHubFirmwareClient
    original_init = client_cls.__init__
    original_resolve = client_cls.resolve_latest
    original_download = client_cls._download_zip

    def detailed_init(self) -> None:
        started = time.perf_counter()
        original_init(self)
        gh_path = shutil.which("gh")
        _emit(
            f"GITHUB CLIENT init duration={time.perf_counter()-started:.3f}s "
            f"auth={'available' if bool(self.token) else 'missing'} gh_cli={gh_path or '-'} repo={services.REPOSITORY}"
        )

    def detailed_get_json(self, url: str, **params) -> dict:
        safe_params = {key: value for key, value in params.items() if not _SENSITIVE.search(str(key))}
        _emit(f"GITHUB GET url={url} params={safe_params}")
        started = time.perf_counter()
        try:
            response = self.session.get(url, params=params, timeout=30)
        except Exception as exc:
            _emit(
                f"GITHUB GET EXCEPTION duration={time.perf_counter()-started:.3f}s "
                f"type={type(exc).__name__} message={exc}"
            )
            _emit_block("GITHUB EXCEPTION TRACEBACK", traceback.format_exc())
            raise
        elapsed = time.perf_counter() - started
        _emit(
            f"GITHUB RESPONSE status={response.status_code} duration={elapsed:.3f}s "
            f"final_url={response.url} bytes={len(response.content)}"
        )
        if response.status_code >= 400:
            _emit_block("GITHUB ERROR BODY", response.text[:8000])
            raise services.FlasherError(
                f"GitHub API: HTTP {response.status_code} · {response.text[:220]}"
            )
        data = response.json()
        if isinstance(data, dict) and "workflow_runs" in data:
            runs = data.get("workflow_runs") or []
            _emit(f"GITHUB WORKFLOW_RUNS count={len(runs)} total_count={data.get('total_count')}")
            for run in runs[:100]:
                _emit(
                    "GITHUB RUN "
                    f"id={run.get('id')} number={run.get('run_number')} "
                    f"name={run.get('name')!r} branch={run.get('head_branch')!r} "
                    f"sha={run.get('head_sha')!r} status={run.get('status')!r} "
                    f"conclusion={run.get('conclusion')!r} event={run.get('event')!r} "
                    f"path={run.get('path')!r} created={run.get('created_at')!r} updated={run.get('updated_at')!r}"
                )
        elif isinstance(data, dict) and "artifacts" in data:
            artifacts = data.get("artifacts") or []
            _emit(f"GITHUB ARTIFACTS count={len(artifacts)} total_count={data.get('total_count')}")
            for artifact in artifacts[:200]:
                _emit(
                    "GITHUB ARTIFACT "
                    f"id={artifact.get('id')} name={artifact.get('name')!r} "
                    f"expired={artifact.get('expired')} size={artifact.get('size_in_bytes')} "
                    f"digest={artifact.get('digest')!r} created={artifact.get('created_at')!r} "
                    f"expires={artifact.get('expires_at')!r}"
                )
        else:
            keys = list(data.keys()) if isinstance(data, dict) else []
            _emit(f"GITHUB JSON type={type(data).__name__} keys={keys[:50]}")
        return data

    def detailed_resolve_latest(self, board_key: str):
        profile_data = services.BOARD_PROFILES.get(board_key, {})
        _emit(
            f"FIRMWARE RESOLVE START board_key={board_key!r} label={profile_data.get('label')!r} "
            f"branch={profile_data.get('branch')!r} pio_env={profile_data.get('pio_env')!r} "
            f"workflow_path={profile_data.get('workflow_path')!r} "
            f"expected_artifact_prefix={profile_data.get('artifact_prefix')!r}"
        )
        started = time.perf_counter()
        try:
            bundle = original_resolve(self, board_key)
        except Exception as exc:
            _emit(
                f"FIRMWARE RESOLVE FAILURE duration={time.perf_counter()-started:.3f}s "
                f"type={type(exc).__name__} message={exc}"
            )
            _emit_block("FIRMWARE RESOLVE TRACEBACK", traceback.format_exc())
            raise
        _emit(
            f"FIRMWARE RESOLVE END duration={time.perf_counter()-started:.3f}s "
            f"run_id={bundle.run_id} run_number={bundle.run_number} artifact_id={bundle.artifact_id} "
            f"artifact_name={bundle.artifact_name!r} product={getattr(bundle, 'product', '')!r} "
            f"version={getattr(bundle, 'version', '')!r} root={bundle.root}"
        )
        for label, path in (
            ("factory", bundle.factory),
            ("metadata", bundle.metadata),
            ("ota", bundle.ota),
            ("update", getattr(bundle, "update", None)),
            ("webflasher", getattr(bundle, "webflasher", None)),
        ):
            if path is None:
                _emit(f"FIRMWARE FILE {label}=<none>")
                continue
            path = Path(path)
            _emit(
                f"FIRMWARE FILE {label}={path} exists={path.exists()} "
                f"size={path.stat().st_size if path.exists() else -1}"
            )
        return bundle

    def detailed_download(self, artifact_id: int, destination: Path) -> None:
        _emit(f"ARTIFACT DOWNLOAD START id={artifact_id} destination={destination}")
        started = time.perf_counter()
        try:
            result = original_download(self, artifact_id, destination)
        except Exception as exc:
            _emit(
                f"ARTIFACT DOWNLOAD FAILURE id={artifact_id} duration={time.perf_counter()-started:.3f}s "
                f"type={type(exc).__name__} message={exc}"
            )
            _emit_block("ARTIFACT DOWNLOAD TRACEBACK", traceback.format_exc())
            raise
        size = destination.stat().st_size if destination.exists() else -1
        _emit(f"ARTIFACT DOWNLOAD END id={artifact_id} duration={time.perf_counter()-started:.3f}s size={size}")
        return result

    client_cls.__init__ = detailed_init
    client_cls._get_json = detailed_get_json
    client_cls.resolve_latest = detailed_resolve_latest
    client_cls._download_zip = detailed_download

    _emit("=" * 88)
    _emit("JARNSEN-MESH-FLASHER maximum diagnostics enabled")
    _emit(f"log_path={_LOG_PATH}")
    _emit(f"pid={os.getpid()} parent_pid={os.getppid() if hasattr(os, 'getppid') else '-'}")
    _emit(f"app_frozen={getattr(sys, 'frozen', False)} executable={sys.executable}")
    _emit(f"python={sys.version.replace(chr(10), ' ')}")
    _emit(
        f"platform={sys.platform} os_name={os.name} release={platform.release()} "
        f"version={platform.version()} machine={platform.machine()} processor={platform.processor()!r}"
    )
    _emit(f"cwd={Path.cwd()} home={Path.home()} temp={os.environ.get('TEMP', '-')}")
    _emit(f"localappdata={os.environ.get('LOCALAPPDATA', '-')} appdata={os.environ.get('APPDATA', '-')}")
    _emit(f"helper_command={_format_command(services.helper_command())}")
    _emit(f"PATH={os.environ.get('PATH', '')}")
    _emit(f"sys_path={sys.path!r}")
    _emit(f"pyinstaller_meipass={getattr(sys, '_MEIPASS', '-')}")
    _log_runtime_versions()
    _emit("Sensitive values (tokens/passwords/PSKs/private keys) are redacted.")
    _emit("Bluetooth RFCOMM COM ports are logged but skipped by the USB flasher scan.")
    _emit("If Meshtastic identification fails on a wired COM port, esptool is tried as a fallback.")
    _emit("=" * 88)

    _start_windows_snapshot("startup")
    return _LOG_PATH
