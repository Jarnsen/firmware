from __future__ import annotations

import os
import re
import subprocess
import time
from typing import Any

_INSTALLED = False
_COM_RE = re.compile(r"\b(COM\d+)\b", re.IGNORECASE)
_USB_INSTANCE_RE = re.compile(r"(USB\\VID_[0-9A-F]{4}&PID_[0-9A-F]{4}[^\r\n]*)", re.IGNORECASE)
_VID_PID_RE = re.compile(r"\bVID_([0-9A-F]{4})&PID_([0-9A-F]{4})\b", re.IGNORECASE)
_RELEVANT_TEXT_RE = re.compile(
    r"LILYGO|T[\s_-]?BEAM|ESP32|ESPRESSIF|CH9102|CH343|CH34[01]|CP210|USB[\s_-]*JTAG|USB[\s_-]*SERIAL|CDC",
    re.IGNORECASE,
)
_RELEVANT_VIDS = {"303A", "1A86", "10C4", "0403", "2886"}


def _emit(message: str) -> None:
    try:
        import diagnostics
        diagnostics._emit(message)
    except Exception:
        pass


def _decode(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def _specific_board_hint(text: str) -> str | None:
    upper = str(text or "").upper().replace("_", " ").replace("-", " ")
    compact = re.sub(r"\s+", " ", upper).strip()
    if "T BEAM SUPREME" in compact or "TBEAM SUPREME" in compact or "TBEAM S3 CORE" in compact:
        return "tbeam_supreme"
    if "T BEAM" in compact or "TBEAM" in compact:
        return "tbeam"
    return None


def _split_blocks(text: str) -> list[str]:
    normalized = str(text or "").replace("\r\n", "\n").replace("\r", "\n")
    return [block.strip() for block in re.split(r"\n\s*\n+", normalized) if block.strip()]


def _friendly_line(block: str, port: str | None) -> str:
    lines = [line.strip() for line in block.splitlines() if line.strip()]
    if port:
        for line in lines:
            if port.upper() in line.upper():
                return line.split(":", 1)[-1].strip() or line
    for line in lines:
        if _RELEVANT_TEXT_RE.search(line) and "VID_" not in line.upper():
            return line.split(":", 1)[-1].strip() or line
    return "Windows USB-Gerät"


def _pnputil_usb_snapshot(timeout: float = 4.0) -> list[dict[str, Any]]:
    if os.name != "nt":
        return []
    cmd = ["pnputil", "/enum-devices", "/connected"]
    started = time.perf_counter()
    _emit(f"WINDOWS USB FALLBACK CMD {' '.join(cmd)} timeout={timeout:.1f}s")
    try:
        proc = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
    except Exception as exc:
        _emit(
            f"WINDOWS USB FALLBACK EXCEPTION duration={time.perf_counter()-started:.3f}s "
            f"type={type(exc).__name__} message={exc}"
        )
        return []
    stdout, stderr = _decode(proc.stdout), _decode(proc.stderr)
    _emit(
        f"WINDOWS USB FALLBACK END exit={proc.returncode} duration={time.perf_counter()-started:.3f}s "
        f"stdout_chars={len(stdout)} stderr_chars={len(stderr)}"
    )
    if proc.returncode != 0 and stderr.strip():
        _emit(f"WINDOWS USB FALLBACK STDERR {stderr.strip()[:1200]!r}")

    devices: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for block in _split_blocks(stdout):
        instance_match = _USB_INSTANCE_RE.search(block)
        vidpid_match = _VID_PID_RE.search(block)
        vid = vidpid_match.group(1).upper() if vidpid_match else ""
        pid = vidpid_match.group(2).upper() if vidpid_match else ""
        if not ((instance_match and vid in _RELEVANT_VIDS) or _RELEVANT_TEXT_RE.search(block)):
            continue
        com_match = _COM_RE.search(block)
        port = com_match.group(1).upper() if com_match else ""
        instance = instance_match.group(1).strip() if instance_match else ""
        description = _friendly_line(block, port or None)
        board_hint = _specific_board_hint(block)
        key = (instance.upper(), port)
        if key in seen:
            continue
        seen.add(key)
        item = {
            "port": port,
            "instance": instance,
            "vid": vid,
            "pid": pid,
            "description": description,
            "board_hint": board_hint,
            "raw": block,
        }
        devices.append(item)
        _emit(
            "WINDOWS USB FALLBACK DEVICE "
            f"port={port or None!r} vidpid={(vid + ':' + pid) if vid else None!r} "
            f"board_hint={board_hint!r} description={description!r} instance={instance!r}"
        )
    _emit(f"WINDOWS USB FALLBACK DEVICE COUNT={len(devices)}")
    return devices


def _probe_recovered_port(services: Any, item: dict[str, Any], probe_timeout: int) -> Any:
    port = str(item.get("port") or "").upper()
    description = str(item.get("description") or f"Windows USB {port}")
    info_text = ""
    board_key = item.get("board_hint")
    started = time.perf_counter()
    _emit(f"WINDOWS USB RECOVERED COM PROBE port={port} board_hint={board_key!r}")
    try:
        proc = services.meshtastic(port, "--info", timeout=probe_timeout, check=False)
        info_text = "\n".join(filter(None, (proc.stdout, proc.stderr)))
        _emit(
            f"WINDOWS USB RECOVERED COM PROBE END port={port} exit={proc.returncode} "
            f"duration={time.perf_counter()-started:.3f}s chars={len(info_text)}"
        )
    except subprocess.TimeoutExpired as exc:
        info_text = "\n".join(filter(None, (_decode(exc.stdout), _decode(exc.stderr))))
        _emit(
            f"WINDOWS USB RECOVERED COM PROBE TIMEOUT port={port} "
            f"duration={time.perf_counter()-started:.3f}s chars={len(info_text)}"
        )
    except Exception as exc:
        info_text = "\n".join(
            filter(None, (_decode(getattr(exc, "stdout", "")), _decode(getattr(exc, "stderr", ""))))
        )
        _emit(
            f"WINDOWS USB RECOVERED COM PROBE ERROR port={port} "
            f"type={type(exc).__name__} message={exc} chars={len(info_text)}"
        )
    if info_text:
        detected = services.detect_board_from_text(info_text)
        if detected:
            board_key = detected
    _emit(f"WINDOWS USB RECOVERED COM KEEP port={port} board={board_key!r}")
    return services.DeviceInfo(port, description, board_key, info_text)


def _no_com_message(devices: list[dict[str, Any]]) -> str:
    if not devices:
        return ""
    best = next((item for item in devices if item.get("board_hint")), devices[0])
    description = str(best.get("description") or "USB-Gerät")
    vid, pid = str(best.get("vid") or ""), str(best.get("pid") or "")
    vidpid = f" · {vid}:{pid}" if vid and pid else ""
    board_key = best.get("board_hint")
    prefix = (
        "T-Beam Supreme per USB erkannt"
        if board_key == "tbeam_supreme"
        else "T-Beam per USB erkannt"
        if board_key == "tbeam"
        else "USB-Gerät erkannt"
    )
    return f"{prefix}, aber Windows hat keinen COM-Port angelegt · {description}{vidpid}"


def install() -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True
    if os.name != "nt":
        return
    try:
        import services
    except Exception as exc:
        _emit(f"WINDOWS USB FALLBACK install failed type={type(exc).__name__} message={exc}")
        return

    previous_scan = services.scan_devices
    services.serial_usb_no_com = []
    services.serial_usb_no_com_message = ""

    def scan_devices(probe_timeout: int = 8):
        services.serial_usb_no_com = []
        services.serial_usb_no_com_message = ""
        devices = previous_scan(probe_timeout)
        if devices:
            return devices

        snapshot = _pnputil_usb_snapshot(timeout=4.0)
        if not snapshot:
            return devices

        recovered: list[Any] = []
        seen_ports: set[str] = set()
        for item in snapshot:
            port = str(item.get("port") or "").upper()
            if not port or port in seen_ports:
                continue
            seen_ports.add(port)
            recovered.append(_probe_recovered_port(services, item, probe_timeout))

        if recovered:
            _emit(f"WINDOWS USB FALLBACK RECOVERED ports={[device.port for device in recovered]}")
            return recovered

        no_com = [item for item in snapshot if not item.get("port")]
        services.serial_usb_no_com = no_com
        services.serial_usb_no_com_message = _no_com_message(no_com)
        if no_com:
            _emit(
                f"WINDOWS USB NO-COM count={len(no_com)} "
                f"message={services.serial_usb_no_com_message!r}"
            )
        return devices

    services.scan_devices = scan_devices

    try:
        import customtkinter as ctk
        previous_ctk_init = ctk.CTk.__init__

        def ctk_init(self, *args, **kwargs):
            previous_ctk_init(self, *args, **kwargs)
            current_set_status = getattr(self, "_set_status", None)
            if current_set_status is None or getattr(self, "_jarnsen_usb_status_wrapped", False):
                return

            def set_status(text: str, _base=current_set_status):
                replacement = str(text)
                if replacement == "Kein serielles Gerät gefunden":
                    message = str(getattr(services, "serial_usb_no_com_message", "") or "")
                    if message:
                        replacement = message
                return _base(replacement)

            self._set_status = set_status
            self._jarnsen_usb_status_wrapped = True

        ctk.CTk.__init__ = ctk_init
    except Exception as exc:
        _emit(f"WINDOWS USB FALLBACK status patch failed type={type(exc).__name__} message={exc}")

    _emit(
        "WINDOWS USB FALLBACK installed pnputil-connected=1 recover-com=1 "
        "usb-without-com-status=1 relevant-vids=303A,1A86,10C4,0403,2886"
    )
