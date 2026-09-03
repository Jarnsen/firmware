from __future__ import annotations

import json
import os
import re
import subprocess
import threading
import time
from typing import Any


def _emit(message: str) -> None:
    try:
        import diagnostics
        diagnostics._emit(message)
    except Exception:
        pass


def _emit_block(title: str, text: str) -> None:
    try:
        import diagnostics
        diagnostics._emit_block(title, text, max_chars=50000)
    except Exception:
        pass


def _decode(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def _is_bluetooth(item: Any) -> bool:
    text = " ".join(
        str(value or "")
        for value in (
            getattr(item, "description", ""),
            getattr(item, "hwid", ""),
            getattr(item, "manufacturer", ""),
            getattr(item, "product", ""),
        )
    ).upper()
    return any(token in text for token in ("BTHENUM", "BLUETOOTH", "BTHMODEM", "RFCOMM"))


def _usb_text(item: Any) -> str:
    return " ".join(
        str(value or "")
        for value in (
            getattr(item, "description", ""),
            getattr(item, "hwid", ""),
            getattr(item, "manufacturer", ""),
            getattr(item, "product", ""),
            getattr(item, "interface", ""),
        )
    )


def _usb_board_hint(item: Any) -> tuple[str | None, str]:
    """Return only hardware-safe USB hints.

    Heltec Tracker V1.1 and V3 both use Espressif USB and cannot safely be
    distinguished by VID alone.  Seeed Wio Tracker L1, however, is the only
    supported Seeed/VID_2886 board in this flasher, so that identity can safely
    prevent a generic tracker-text false positive.
    """
    if item is None:
        return None, "no pyserial metadata"
    text = _usb_text(item).upper()
    vid = getattr(item, "vid", None)
    pid = getattr(item, "pid", None)
    if "WIO TRACKER" in text or "SEEED WIO" in text:
        return "wio", f"usb text={text[:220]!r}"
    if vid == 0x2886 and any(token in text for token in ("SEEED", "WIO", "XIAO", "NRF")):
        return "wio", f"Seeed VID/PID={vid:04X}:{(pid or 0):04X} text={text[:180]!r}"
    return None, f"VID/PID={(vid if vid is not None else -1):04X}:{(pid if pid is not None else -1):04X}"


def _registry_serial_ports() -> list[str]:
    """Read active Windows SERIALCOMM mappings without spawning PowerShell."""
    if os.name != "nt":
        return []
    try:
        import winreg

        key = winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            r"HARDWARE\DEVICEMAP\SERIALCOMM",
            0,
            winreg.KEY_READ,
        )
    except Exception as exc:
        _emit(f"SERIAL REGISTRY OPEN FAILED type={type(exc).__name__} message={exc}")
        return []

    ports: list[str] = []
    index = 0
    try:
        while True:
            try:
                name, value, _kind = winreg.EnumValue(key, index)
            except OSError:
                break
            index += 1
            port = str(value or "").strip().upper()
            if re.fullmatch(r"COM\d+", port):
                ports.append(port)
                _emit(f"SERIAL REGISTRY MAP name={name!r} port={port}")
    finally:
        try:
            winreg.CloseKey(key)
        except Exception:
            pass

    result = sorted(set(ports), key=lambda value: int(value[3:]))
    _emit(f"SERIAL REGISTRY PORTS {result}")
    return result


def _powershell_json(script: str, timeout: int = 5) -> Any:
    prefix = (
        "$OutputEncoding=[Console]::OutputEncoding="
        "[System.Text.UTF8Encoding]::new($false);"
        "$ErrorActionPreference='Continue';"
    )
    cmd = ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", prefix + script]
    _emit(f"SERIAL PNP CMD {subprocess.list2cmdline(cmd)}")
    started = time.perf_counter()
    try:
        proc = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
    except Exception as exc:
        _emit(
            f"SERIAL PNP EXCEPTION duration={time.perf_counter()-started:.3f}s "
            f"type={type(exc).__name__} message={exc}"
        )
        return []

    stdout = proc.stdout.decode("utf-8", errors="replace")
    stderr = proc.stderr.decode("utf-8", errors="replace")
    _emit(
        f"SERIAL PNP END exit={proc.returncode} duration={time.perf_counter()-started:.3f}s "
        f"stdout_bytes={len(proc.stdout)} stderr_bytes={len(proc.stderr)}"
    )
    if stderr.strip():
        _emit_block("SERIAL PNP STDERR", stderr)
    if not stdout.strip():
        _emit("SERIAL PNP JSON empty")
        return []
    try:
        data = json.loads(stdout)
    except Exception as exc:
        _emit(f"SERIAL PNP JSON ERROR type={type(exc).__name__} message={exc}")
        _emit_block("SERIAL PNP RAW", stdout)
        return []
    if data is None:
        return []
    return data if isinstance(data, list) else [data]


def _pnp_snapshot(timeout: int = 5) -> list[dict[str, Any]]:
    script = r"""
$items = Get-PnpDevice -PresentOnly | Where-Object {
    ($_.Class -eq 'Ports') -or
    ($_.FriendlyName -match 'COM|ESP32|ESPRESSIF|HELTEC|WIO|SEEED|CP210|CH340|CH341|USB JTAG|USB Serial|CDC') -or
    ($_.InstanceId -match 'VID_(303A|10C4|1A86|2886)') -or
    ($_.InstanceId -like 'USB\VID_*')
} | ForEach-Object {
    $p = $_
    $port = $null
    try {
        $port = (Get-PnpDeviceProperty -InstanceId $p.InstanceId -KeyName 'DEVPKEY_Device_PortName' -ErrorAction SilentlyContinue).Data
    } catch {}
    [PSCustomObject]@{
        Status = [string]$p.Status
        Class = [string]$p.Class
        FriendlyName = [string]$p.FriendlyName
        InstanceId = [string]$p.InstanceId
        Problem = [string]$p.Problem
        ProblemStatus = [string]$p.ProblemStatus
        PortName = [string]$port
    }
}
@($items) | ConvertTo-Json -Depth 4 -Compress
"""
    raw = _powershell_json(script, timeout=timeout)
    result: list[dict[str, Any]] = []
    for item in raw:
        if isinstance(item, dict):
            result.append(item)
            _emit(
                "SERIAL PNP DEVICE "
                f"status={item.get('Status')!r} class={item.get('Class')!r} "
                f"name={item.get('FriendlyName')!r} instance={item.get('InstanceId')!r} "
                f"problem={item.get('Problem')!r} problem_status={item.get('ProblemStatus')!r} "
                f"port={item.get('PortName')!r}"
            )
    _emit(f"SERIAL PNP DEVICE COUNT={len(result)}")
    return result


def _background_pnp(reason: str) -> None:
    def worker() -> None:
        _emit(f"SERIAL PNP BACKGROUND START reason={reason}")
        started = time.perf_counter()
        result = _pnp_snapshot(timeout=5)
        _emit(
            f"SERIAL PNP BACKGROUND END reason={reason} devices={len(result)} "
            f"duration={time.perf_counter()-started:.3f}s"
        )

    threading.Thread(target=worker, name="serial-pnp-diagnostics", daemon=True).start()


def install(services: Any) -> None:
    """Install a fast wired scanner with hardware-safe board identity."""

    def scan_devices(probe_timeout: int = 8):
        scan_started = time.perf_counter()
        watch_seconds = 5.0
        interval = 0.5
        _emit(
            f"SERIAL ACTIVE SCAN START watch={watch_seconds:.1f}s interval={interval:.1f}s "
            f"probe_timeout={probe_timeout}s pnp_blocking=0"
        )

        observed: dict[str, Any] = {}
        previous: set[str] = set()
        bluetooth_seen: set[str] = set()
        cycle = 0
        deadline = time.perf_counter() + watch_seconds
        wired_now: list[str] = []
        while True:
            cycle += 1
            try:
                ports = list(services.list_ports.comports())
            except Exception as exc:
                _emit(f"SERIAL ACTIVE ENUM ERROR cycle={cycle} type={type(exc).__name__} message={exc}")
                ports = []

            current: set[str] = set()
            wired: list[str] = []
            bluetooth: list[str] = []
            for item in ports:
                port = str(getattr(item, "device", "") or "").upper()
                if not port:
                    continue
                current.add(port)
                observed[port] = item
                if _is_bluetooth(item):
                    bluetooth.append(port)
                    bluetooth_seen.add(port)
                else:
                    wired.append(port)
                    hint, hint_reason = _usb_board_hint(item)
                    _emit(
                        "SERIAL USB META "
                        f"port={port} vid={getattr(item, 'vid', None)!r} pid={getattr(item, 'pid', None)!r} "
                        f"manufacturer={getattr(item, 'manufacturer', None)!r} product={getattr(item, 'product', None)!r} "
                        f"description={getattr(item, 'description', None)!r} hwid={getattr(item, 'hwid', None)!r} "
                        f"board_hint={hint!r} reason={hint_reason!r}"
                    )

            wired_now = wired
            _emit(
                f"SERIAL ACTIVE CYCLE={cycle} all={sorted(current)} wired={sorted(wired)} "
                f"bluetooth={sorted(bluetooth)} added={sorted(current-previous)} "
                f"removed={sorted(previous-current)}"
            )
            previous = current
            if wired or time.perf_counter() >= deadline:
                break
            time.sleep(interval)

        registry_ports = _registry_serial_ports()
        candidates: dict[str, tuple[str, str, Any | None]] = {}
        for port, item in observed.items():
            if not _is_bluetooth(item):
                candidates[port] = (
                    str(getattr(item, "description", "") or "Serielles USB-Gerät"),
                    "pyserial",
                    item,
                )

        for port in registry_ports:
            if port in bluetooth_seen:
                continue
            if port not in candidates:
                candidates[port] = (f"Windows Serial {port}", "registry", None)
                _emit(f"SERIAL REGISTRY CANDIDATE port={port}")

        _background_pnp("wired-present" if wired_now else "no-wired-after-watch")

        _emit(
            f"SERIAL ACTIVE CANDIDATES wired={sorted(candidates)} "
            f"elapsed={time.perf_counter()-scan_started:.3f}s"
        )

        devices = []
        for port in sorted(candidates):
            description, source, port_item = candidates[port]
            usb_hint, usb_reason = _usb_board_hint(port_item)
            _emit(
                f"SERIAL ACTIVE PROBE START port={port} source={source} description={description!r} "
                f"usb_hint={usb_hint!r} usb_reason={usb_reason!r}"
            )
            info_text = ""
            board_key = None
            started = time.perf_counter()
            try:
                proc = services.meshtastic(port, "--info", timeout=probe_timeout, check=False)
                info_text = "\n".join(filter(None, (proc.stdout, proc.stderr)))
                _emit(
                    f"SERIAL ACTIVE MESHTASTIC END port={port} exit={proc.returncode} "
                    f"duration={time.perf_counter()-started:.3f}s chars={len(info_text)}"
                )
            except subprocess.TimeoutExpired as exc:
                stdout = _decode(exc.stdout)
                stderr = _decode(exc.stderr)
                info_text = "\n".join(filter(None, (stdout, stderr)))
                _emit(
                    f"SERIAL ACTIVE MESHTASTIC TIMEOUT port={port} "
                    f"duration={time.perf_counter()-started:.3f}s chars={len(info_text)} "
                    "using_partial_output=True"
                )
            except Exception as exc:
                stdout = _decode(getattr(exc, "stdout", ""))
                stderr = _decode(getattr(exc, "stderr", ""))
                info_text = "\n".join(filter(None, (stdout, stderr)))
                _emit(
                    f"SERIAL ACTIVE MESHTASTIC ERROR port={port} duration={time.perf_counter()-started:.3f}s "
                    f"type={type(exc).__name__} message={exc} partial_chars={len(info_text)}"
                )

            if info_text:
                board_key = services.detect_board_from_text(info_text)
                _emit(f"SERIAL ACTIVE BOARD port={port} serial_board={board_key!r} chars={len(info_text)}")
                _emit_block(f"SERIAL ACTIVE INFO {port}", info_text)

            # Physical USB identity outranks generic serial prose.  This is the
            # explicit guard for the original-Meshtastic Wio false positive.
            if usb_hint and board_key != usb_hint:
                _emit(
                    f"SERIAL BOARD USB OVERRIDE port={port} serial_board={board_key!r} "
                    f"usb_board={usb_hint!r} reason={usb_reason!r}"
                )
                board_key = usb_hint

            # A real wired port remains selectable even when JARNSEN-MESH 2.0.0
            # is booting/light-sleeping and --info returns no usable metadata.
            if board_key is None:
                _emit(
                    f"SERIAL BOARD UNKNOWN KEEP port={port} source={source} "
                    "device remains selectable; manual board verification required before flash"
                )

            devices.append(services.DeviceInfo(port, description, board_key, info_text))

        if not devices:
            _emit("SERIAL ACTIVE RESULT: no wired serial device visible; PnP diagnostics continue in background")
        else:
            _emit(
                f"SERIAL ACTIVE RESULT devices={[(d.port, d.board_key) for d in devices]} "
                f"elapsed={time.perf_counter()-scan_started:.3f}s"
            )
        return devices

    services.scan_devices = scan_devices
    services.is_bluetooth_serial = _is_bluetooth
    services.serial_registry_ports = _registry_serial_ports
    services.usb_board_hint = _usb_board_hint
    _emit(
        "SERIAL ACTIVE SCANNER installed partial-timeout-detection=1 pnp-blocking=0 "
        "registry-fallback=1 usb-board-guard=1 keep-unknown-wired=1"
    )
