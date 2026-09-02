from __future__ import annotations

import json
import os
import re
import subprocess
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
    return "BTHENUM" in text or "BLUETOOTH" in text or "BTHMODEM" in text


def _powershell_json(script: str, timeout: int = 12) -> Any:
    # Force UTF-8 explicitly.  The previous diagnostics used the inherited
    # Windows ANSI codepage and could lose PnP output on German Windows.
    prefix = (
        "$OutputEncoding=[Console]::OutputEncoding="
        "[System.Text.UTF8Encoding]::new($false);"
        "$ErrorActionPreference='Continue';"
    )
    cmd = [
        "powershell.exe",
        "-NoProfile",
        "-NonInteractive",
        "-Command",
        prefix + script,
    ]
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


def _pnp_snapshot() -> list[dict[str, Any]]:
    script = r"""
$items = Get-PnpDevice -PresentOnly | Where-Object {
    ($_.Class -eq 'Ports') -or
    ($_.FriendlyName -match 'COM|ESP32|ESPRESSIF|HELTEC|CP210|CH340|CH341|USB JTAG|USB Serial|CDC') -or
    ($_.InstanceId -match 'VID_303A|VID_10C4|VID_1A86|USB\\VID_')
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
    raw = _powershell_json(script)
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


def _extract_com(item: dict[str, Any]) -> str:
    for value in (item.get("PortName"), item.get("FriendlyName")):
        text = str(value or "")
        match = re.search(r"\b(COM\d+)\b", text, re.IGNORECASE)
        if match:
            return match.group(1).upper()
    return ""


def _looks_like_esp(item: dict[str, Any]) -> bool:
    text = " ".join(
        str(item.get(key) or "")
        for key in ("FriendlyName", "InstanceId", "Class")
    ).upper()
    return any(
        token in text
        for token in (
            "ESP32",
            "ESPRESSIF",
            "HELTEC",
            "VID_303A",
            "USB JTAG",
            "USB SERIAL",
            "CDC",
            "CP210",
            "CH340",
            "CH341",
            "VID_10C4",
            "VID_1A86",
        )
    )


def install(services: Any) -> None:
    """Install the active wired-serial scanner before app.py imports scan_devices."""

    def scan_devices(probe_timeout: int = 8):
        scan_started = time.perf_counter()
        watch_seconds = 5.0
        interval = 0.5
        _emit(
            f"SERIAL ACTIVE SCAN START watch={watch_seconds:.1f}s interval={interval:.1f}s "
            f"probe_timeout={probe_timeout}s"
        )

        observed: dict[str, Any] = {}
        previous: set[str] = set()
        cycle = 0
        deadline = time.perf_counter() + watch_seconds
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
                else:
                    wired.append(port)

            added = sorted(current - previous)
            removed = sorted(previous - current)
            _emit(
                f"SERIAL ACTIVE CYCLE={cycle} all={sorted(current)} wired={sorted(wired)} "
                f"bluetooth={sorted(bluetooth)} added={added} removed={removed}"
            )
            previous = current

            # A real wired COM is enough; do not make the user wait the full five seconds.
            if wired:
                _emit(f"SERIAL ACTIVE WIRED FOUND cycle={cycle} ports={sorted(wired)}")
                break
            if time.perf_counter() >= deadline:
                break
            time.sleep(interval)

        # PnP is intentionally synchronous here.  Build 21 previously returned
        # "no device" while the useful Windows diagnostics were still running.
        pnp = _pnp_snapshot()
        pnp_com: dict[str, dict[str, Any]] = {}
        esp_without_com: list[dict[str, Any]] = []
        for item in pnp:
            port = _extract_com(item)
            if port:
                pnp_com[port] = item
            elif _looks_like_esp(item):
                esp_without_com.append(item)

        for item in esp_without_com:
            _emit(
                "SERIAL USB DETECTED WITHOUT COM "
                f"name={item.get('FriendlyName')!r} instance={item.get('InstanceId')!r} "
                f"status={item.get('Status')!r} problem={item.get('Problem')!r} "
                f"problem_status={item.get('ProblemStatus')!r}"
            )

        candidates: dict[str, tuple[str, str]] = {}
        for port, item in observed.items():
            if not _is_bluetooth(item):
                candidates[port] = (
                    str(getattr(item, "description", "") or "Serielles USB-Gerät"),
                    "pyserial",
                )
        for port, item in pnp_com.items():
            instance = str(item.get("InstanceId") or "").upper()
            name = str(item.get("FriendlyName") or f"Windows PnP {port}")
            if "BTHENUM" in instance or "BLUETOOTH" in name.upper():
                continue
            candidates.setdefault(port, (name, "windows-pnp"))

        _emit(
            f"SERIAL ACTIVE CANDIDATES wired={sorted(candidates)} "
            f"esp_without_com={len(esp_without_com)} elapsed={time.perf_counter()-scan_started:.3f}s"
        )

        devices = []
        for port in sorted(candidates):
            description, source = candidates[port]
            _emit(f"SERIAL ACTIVE PROBE START port={port} source={source} description={description!r}")
            info_text = ""
            board_key = None
            started = time.perf_counter()
            try:
                proc = services.meshtastic(port, "--info", timeout=probe_timeout, check=False)
                info_text = "\n".join(filter(None, (proc.stdout, proc.stderr)))
                board_key = services.detect_board_from_text(info_text)
                _emit(
                    f"SERIAL ACTIVE MESHTASTIC END port={port} exit={proc.returncode} "
                    f"duration={time.perf_counter()-started:.3f}s chars={len(info_text)} board={board_key!r}"
                )
            except Exception as exc:
                _emit(
                    f"SERIAL ACTIVE MESHTASTIC ERROR port={port} duration={time.perf_counter()-started:.3f}s "
                    f"type={type(exc).__name__} message={exc}"
                )

            # Keep a wired COM selectable even when Meshtastic identification fails.
            devices.append(services.DeviceInfo(port, description, board_key, info_text))

        if not devices:
            if esp_without_com:
                _emit(
                    "SERIAL ACTIVE RESULT: ESP/Heltec-like USB hardware is present but Windows exposes no COM port. "
                    "The flasher cannot open a serial transport until Windows assigns a COM interface."
                )
            else:
                _emit(
                    "SERIAL ACTIVE RESULT: no wired serial or ESP/Heltec USB device became visible during scan window."
                )
        else:
            _emit(
                f"SERIAL ACTIVE RESULT devices={[(d.port, d.board_key) for d in devices]} "
                f"elapsed={time.perf_counter()-scan_started:.3f}s"
            )
        return devices

    services.scan_devices = scan_devices
    _emit("SERIAL ACTIVE SCANNER installed")
