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
    """Return only USB identities that are safe enough to pick a board.

    Espressif VID 303A and generic CP210x/CH34x adapters are deliberately not
    mapped to a Heltec model: Tracker V1.1 and V3 can share those transports.
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


def _normalize_identity(value: Any) -> str:
    return re.sub(r"\s+", "", str(value or "")).upper()


def _device_fingerprint(item: Any) -> str:
    """Return a session-stable physical identity for USB re-enumeration.

    Prefer a real serial number.  CP210x clones frequently use generic serials
    such as 0001, so for those we prefer the physical USB location instead.
    """
    if item is None:
        return ""
    vid = getattr(item, "vid", None)
    pid = getattr(item, "pid", None)
    serial_number = _normalize_identity(getattr(item, "serial_number", ""))
    location = _normalize_identity(getattr(item, "location", ""))
    hwid = str(getattr(item, "hwid", "") or "")

    if not serial_number:
        match = re.search(r"(?i)\bSER=([^\s]+)", hwid)
        if match:
            serial_number = _normalize_identity(match.group(1))
    if not location:
        match = re.search(r"(?i)\bLOCATION=([^\s]+)", hwid)
        if match:
            location = _normalize_identity(match.group(1))

    prefix = f"{(vid if vid is not None else -1):04X}:{(pid if pid is not None else -1):04X}"
    generic_serials = {"", "0000", "0001", "00000000", "NONE", "N/A"}
    if serial_number not in generic_serials:
        return f"{prefix}:SER:{serial_number}"
    if location:
        return f"{prefix}:LOC:{location}"
    description = _normalize_identity(getattr(item, "description", ""))
    return f"{prefix}:PORT:{_normalize_identity(getattr(item, 'device', ''))}:DESC:{description[:80]}"


def _transient_port_gone(text: str) -> bool:
    upper = (text or "").upper()
    return any(
        token in upper
        for token in (
            "FILENOTFOUNDERROR",
            "DAS SYSTEM KANN DIE ANGEGEBENE DATEI NICHT FINDEN",
            "THE SYSTEM CANNOT FIND THE FILE SPECIFIED",
            "NO SUCH FILE OR DIRECTORY",
            "DEVICE DISCONNECTED",
        )
    )


def _port_busy(text: str) -> bool:
    upper = (text or "").upper()
    return any(
        token in upper
        for token in (
            "PERMISSIONERROR",
            "ACCESS IS DENIED",
            "ZUGRIFF VERWEIGERT",
            "IN USE BY ANOTHER PROCESS",
            "MIGHT BE IN USE BY ANOTHER PROCESS",
        )
    )


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


_pnp_lock = threading.Lock()
_pnp_last_started = 0.0


def _background_pnp(reason: str) -> None:
    """Run expensive PnP diagnostics at most once every 30 seconds."""
    global _pnp_last_started
    now = time.monotonic()
    with _pnp_lock:
        if now - _pnp_last_started < 30.0:
            _emit(f"SERIAL PNP BACKGROUND SKIP reason={reason} rate_limited=1")
            return
        _pnp_last_started = now

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
    """Install a stable wired scanner with single-flight and re-enumeration tracking."""

    state_lock = threading.Lock()
    active_event: threading.Event | None = None
    active = False
    last_result: list[Any] = []
    last_completed = 0.0

    def enumerate_wired(*, log_meta: bool = False) -> tuple[dict[str, Any], set[str]]:
        try:
            ports = list(services.list_ports.comports())
        except Exception as exc:
            _emit(f"SERIAL ENUM ERROR type={type(exc).__name__} message={exc}")
            return {}, set()

        wired: dict[str, Any] = {}
        bluetooth: set[str] = set()
        for item in ports:
            port = str(getattr(item, "device", "") or "").upper()
            if not port:
                continue
            if _is_bluetooth(item):
                bluetooth.add(port)
                continue
            wired[port] = item
            if log_meta:
                hint, hint_reason = _usb_board_hint(item)
                _emit(
                    "SERIAL USB META "
                    f"port={port} fingerprint={_device_fingerprint(item)!r} "
                    f"vid={getattr(item, 'vid', None)!r} pid={getattr(item, 'pid', None)!r} "
                    f"serial={getattr(item, 'serial_number', None)!r} location={getattr(item, 'location', None)!r} "
                    f"manufacturer={getattr(item, 'manufacturer', None)!r} product={getattr(item, 'product', None)!r} "
                    f"description={getattr(item, 'description', None)!r} hwid={getattr(item, 'hwid', None)!r} "
                    f"board_hint={hint!r} reason={hint_reason!r}"
                )
        return wired, bluetooth

    def find_fingerprint(fingerprint: str) -> tuple[str, Any] | None:
        if not fingerprint:
            return None
        wired, _bluetooth = enumerate_wired(log_meta=False)
        for port, item in wired.items():
            if _device_fingerprint(item) == fingerprint:
                return port, item
        return None

    def stable_snapshot(watch_seconds: float = 4.0, interval: float = 0.35) -> tuple[dict[str, Any], set[str]]:
        deadline = time.monotonic() + watch_seconds
        last_signature: tuple[tuple[str, str], ...] | None = None
        stable_count = 0
        cycle = 0
        latest: dict[str, Any] = {}
        latest_bluetooth: set[str] = set()

        while True:
            cycle += 1
            latest, latest_bluetooth = enumerate_wired(log_meta=(cycle == 1))
            signature = tuple(sorted((port, _device_fingerprint(item)) for port, item in latest.items()))
            if signature and signature == last_signature:
                stable_count += 1
            elif signature:
                stable_count = 1
            else:
                stable_count = 0
            last_signature = signature
            _emit(
                f"SERIAL STABILITY cycle={cycle} wired={list(sorted(latest))} "
                f"stable_count={stable_count}/2 bluetooth={list(sorted(latest_bluetooth))}"
            )
            if signature and stable_count >= 2:
                return latest, latest_bluetooth
            if time.monotonic() >= deadline:
                return latest, latest_bluetooth
            time.sleep(interval)

    def probe_candidate(port: str, item: Any, probe_timeout: int) -> Any | None:
        original_port = port
        fingerprint = _device_fingerprint(item)
        description = str(getattr(item, "description", "") or "Serielles USB-Gerät")
        usb_hint, usb_reason = _usb_board_hint(item)
        _emit(
            f"SERIAL PROBE CANDIDATE port={port} fingerprint={fingerprint!r} "
            f"description={description!r} usb_hint={usb_hint!r} usb_reason={usb_reason!r}"
        )

        # Revalidate immediately before starting the helper.  A USB CDC device
        # can change COM number while Windows finishes enumeration.
        current = find_fingerprint(fingerprint)
        if current is None:
            _emit(f"SERIAL PROBE WAIT fingerprint={fingerprint!r} reason=not-present-before-probe")
            for _ in range(5):
                time.sleep(0.35)
                current = find_fingerprint(fingerprint)
                if current is not None:
                    break
        if current is None:
            _emit(
                f"SERIAL PROBE DROP port={original_port} fingerprint={fingerprint!r} "
                "reason=transient-port-disappeared-before-probe"
            )
            return None
        port, item = current
        if port != original_port:
            _emit(f"SERIAL PROBE REMAP old_port={original_port} new_port={port} fingerprint={fingerprint!r}")

        info_text = ""
        board_key = None
        busy_text = ""
        for attempt in range(1, 4):
            started = time.perf_counter()
            _emit(f"SERIAL PROBE START port={port} attempt={attempt}/3 fingerprint={fingerprint!r}")
            try:
                proc = services.meshtastic(port, "--info", timeout=probe_timeout, check=False)
                info_text = "\n".join(filter(None, (proc.stdout, proc.stderr)))
                _emit(
                    f"SERIAL PROBE MESHTASTIC END port={port} attempt={attempt} exit={proc.returncode} "
                    f"duration={time.perf_counter()-started:.3f}s chars={len(info_text)}"
                )
            except subprocess.TimeoutExpired as exc:
                stdout = _decode(exc.stdout)
                stderr = _decode(exc.stderr)
                info_text = "\n".join(filter(None, (stdout, stderr)))
                _emit(
                    f"SERIAL PROBE MESHTASTIC TIMEOUT port={port} attempt={attempt} "
                    f"duration={time.perf_counter()-started:.3f}s chars={len(info_text)} partial=1"
                )
            except Exception as exc:
                stdout = _decode(getattr(exc, "stdout", ""))
                stderr = _decode(getattr(exc, "stderr", ""))
                info_text = "\n".join(filter(None, (stdout, stderr)))
                _emit(
                    f"SERIAL PROBE MESHTASTIC ERROR port={port} attempt={attempt} "
                    f"duration={time.perf_counter()-started:.3f}s type={type(exc).__name__} "
                    f"message={exc} chars={len(info_text)}"
                )

            if info_text:
                board_key = services.detect_board_from_text(info_text)
                if board_key:
                    _emit(
                        f"SERIAL PROBE BOARD port={port} board={board_key!r} "
                        f"fingerprint={fingerprint!r} attempt={attempt}"
                    )
                    _emit_block(f"SERIAL ACTIVE INFO {port}", info_text)
                    break

            if _port_busy(info_text):
                busy_text = info_text
                _emit(f"SERIAL PROBE BUSY port={port} fingerprint={fingerprint!r}")
                break

            if _transient_port_gone(info_text):
                _emit(f"SERIAL PROBE TRANSIENT GONE port={port} attempt={attempt} fingerprint={fingerprint!r}")
                remapped = None
                for _ in range(6):
                    time.sleep(0.4)
                    remapped = find_fingerprint(fingerprint)
                    if remapped is not None:
                        break
                if remapped is None:
                    _emit(
                        f"SERIAL PROBE DROP port={port} fingerprint={fingerprint!r} "
                        "reason=port-did-not-return"
                    )
                    return None
                new_port, item = remapped
                if new_port != port:
                    _emit(f"SERIAL PROBE REMAP old_port={port} new_port={new_port} fingerprint={fingerprint!r}")
                port = new_port
                continue

            # Output without board metadata is a valid connection but not a
            # reason to retry the same expensive --info call repeatedly.
            if info_text:
                _emit_block(f"SERIAL ACTIVE INFO {port}", info_text)
            break

        if usb_hint and board_key != usb_hint:
            _emit(
                f"SERIAL BOARD USB OVERRIDE port={port} serial_board={board_key!r} "
                f"usb_board={usb_hint!r} reason={usb_reason!r}"
            )
            board_key = usb_hint

        # Never return a ghost port.  If it vanished after the probe, only keep
        # it when the helper explicitly reported a busy/locked port.
        present = find_fingerprint(fingerprint)
        if present is None and not busy_text:
            _emit(
                f"SERIAL PROBE DROP port={port} fingerprint={fingerprint!r} "
                "reason=not-present-after-probe"
            )
            return None
        if present is not None:
            current_port, current_item = present
            if current_port != port:
                _emit(f"SERIAL PROBE FINAL REMAP old_port={port} new_port={current_port} fingerprint={fingerprint!r}")
                port = current_port
                item = current_item

        if board_key is None:
            _emit(
                f"SERIAL BOARD UNKNOWN KEEP port={port} fingerprint={fingerprint!r} "
                f"busy={bool(busy_text)} manual-verification-required=1"
            )
        return services.DeviceInfo(port, description, board_key, info_text or busy_text)

    def do_scan(probe_timeout: int) -> list[Any]:
        scan_started = time.perf_counter()
        _emit(
            f"SERIAL STABLE SCAN START watch=4.0s interval=0.35s probe_timeout={probe_timeout}s "
            "single_flight=1 stable_sightings=2 follow_reenumeration=1"
        )
        wired, bluetooth = stable_snapshot()
        registry_ports = _registry_serial_ports()

        # Registry fallback is only useful for currently active non-Bluetooth
        # ports.  Do not resurrect ports that PySerial saw earlier but lost.
        candidates: dict[str, Any | None] = dict(wired)
        for port in registry_ports:
            if port in bluetooth or port in candidates:
                continue
            candidates[port] = None
            _emit(f"SERIAL REGISTRY-ONLY CANDIDATE port={port}")

        _background_pnp("wired-present" if candidates else "no-wired-after-watch")
        _emit(
            f"SERIAL STABLE CANDIDATES ports={list(sorted(candidates))} "
            f"elapsed={time.perf_counter()-scan_started:.3f}s"
        )

        devices: list[Any] = []
        for port in sorted(candidates):
            item = candidates[port]
            if item is None:
                # Re-query pyserial once.  If it still cannot provide the
                # device, keep the registry port selectable but do not guess a
                # board and do not start a long probe against a stale mapping.
                current_wired, _ = enumerate_wired(log_meta=True)
                item = current_wired.get(port)
                if item is None:
                    _emit(f"SERIAL REGISTRY-ONLY KEEP port={port} board=None probe_skipped=1")
                    devices.append(services.DeviceInfo(port, f"Windows Serial {port}", None, ""))
                    continue
            device = probe_candidate(port, item, probe_timeout)
            if device is not None:
                devices.append(device)

        _emit(
            f"SERIAL STABLE RESULT devices={[(d.port, d.board_key) for d in devices]} "
            f"elapsed={time.perf_counter()-scan_started:.3f}s"
        )
        return devices

    def scan_devices(probe_timeout: int = 8):
        nonlocal active, active_event, last_result, last_completed

        owner = False
        with state_lock:
            if active and active_event is not None:
                event = active_event
                _emit("SERIAL SINGLE-FLIGHT JOIN existing_scan=1")
            elif time.monotonic() - last_completed < 0.8:
                _emit("SERIAL SINGLE-FLIGHT CACHE age_lt=0.8s")
                return list(last_result)
            else:
                active = True
                active_event = threading.Event()
                event = active_event
                owner = True

        if not owner:
            event.wait(timeout=max(15.0, float(probe_timeout) + 8.0))
            with state_lock:
                _emit(f"SERIAL SINGLE-FLIGHT RETURN joined_devices={[(d.port, d.board_key) for d in last_result]}")
                return list(last_result)

        result: list[Any] = []
        try:
            result = do_scan(probe_timeout)
            return result
        finally:
            with state_lock:
                last_result = list(result)
                last_completed = time.monotonic()
                active = False
                if active_event is not None:
                    active_event.set()
                active_event = None

    services.scan_devices = scan_devices
    services.is_bluetooth_serial = _is_bluetooth
    services.serial_registry_ports = _registry_serial_ports
    services.usb_board_hint = _usb_board_hint
    services.serial_device_fingerprint = _device_fingerprint
    services.serial_transient_port_gone = _transient_port_gone
    _emit(
        "SERIAL STABLE SCANNER installed single-flight=1 stable-sightings=2 "
        "follow-reenumeration=1 ghost-drop=1 pnp-rate-limit=30s keep-unknown-wired=1"
    )
