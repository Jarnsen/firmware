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
    r"LILYGO|TTGO|T[\s_-]?BEAM|ESP32|ESPRESSIF|CH9102|CH343|CH34[01]|CP210|FTDI|"
    r"USB[\s_-]*JTAG|USB[\s_-]*SERIAL|USB[\s_-]*CDC|CDC[\s_-]*(?:ACM|SERIAL)",
    re.IGNORECASE,
)
_RELEVANT_VIDS = {"303A", "1A86", "10C4", "0403", "2886"}
_MAX_INVENTORY_LOG = 30


def _emit(message: str) -> None:
    try:
        import diagnostics
        diagnostics._emit(message)
    except Exception:
        pass


def _decode(value: Any) -> str:
    """Decode Windows command output without assuming redirected pnputil is UTF-8."""
    if value is None:
        return ""
    if not isinstance(value, bytes):
        return str(value).replace("\x00", "")

    data = bytes(value)
    if not data:
        return ""

    # Some Windows console tools emit UTF-16 when stdout is redirected. A plain
    # UTF-8 decode leaves NULs between every character and makes VID/COM regexes
    # silently miss the device. Prefer BOM-aware UTF-16 and use the NUL ratio as
    # a fallback signal when no BOM is present.
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        try:
            return data.decode("utf-16").replace("\x00", "")
        except Exception:
            pass

    nul_ratio = data.count(b"\x00") / max(1, len(data))
    if nul_ratio > 0.08:
        for encoding in ("utf-16-le", "utf-16-be"):
            try:
                text = data.decode(encoding)
            except Exception:
                continue
            upper = text.upper()
            if "VID_" in upper or "COM" in upper or "T-BEAM" in upper or "TBEAM" in upper:
                return text.replace("\x00", "")

    for encoding in ("utf-8", "mbcs", "cp850", "cp1252"):
        try:
            return data.decode(encoding).replace("\x00", "")
        except (LookupError, UnicodeDecodeError):
            continue
    return data.decode("utf-8", errors="replace").replace("\x00", "")


def _specific_board_hint(text: str) -> str | None:
    upper = str(text or "").upper().replace("_", " ").replace("-", " ")
    compact = re.sub(r"\s+", " ", upper).strip()
    if "T BEAM SUPREME" in compact or "TBEAM SUPREME" in compact or "TBEAM S3 CORE" in compact:
        return "tbeam_supreme"
    if "T BEAM" in compact or "TBEAM" in compact or "TTGO T BEAM" in compact:
        return "tbeam"
    return None


def _split_blocks(text: str) -> list[str]:
    normalized = str(text or "").replace("\x00", "").replace("\r\n", "\n").replace("\r", "\n")
    blocks = [block.strip() for block in re.split(r"\n\s*\n+", normalized) if block.strip()]
    if len(blocks) > 1:
        return blocks

    # Localized pnputil versions do not always preserve blank lines when stdout
    # is redirected. Build small line windows around every USB VID/PID marker as
    # well as the known serial markers. This also gives us a generic inventory
    # when a new USB bridge uses a VID we have never seen before.
    lines = [line.strip() for line in normalized.splitlines() if line.strip()]
    windows: list[str] = []
    seen: set[str] = set()
    for index, line in enumerate(lines):
        if not (_VID_PID_RE.search(line) or _COM_RE.search(line) or _RELEVANT_TEXT_RE.search(line)):
            continue
        start = max(0, index - 3)
        end = min(len(lines), index + 5)
        block = "\n".join(lines[start:end])
        key = block.upper()
        if key in seen:
            continue
        seen.add(key)
        windows.append(block)
    return windows or blocks


def _friendly_line(block: str, port: str | None) -> str:
    lines = [line.strip() for line in block.splitlines() if line.strip()]
    if port:
        for line in lines:
            if port.upper() in line.upper():
                return line.split(":", 1)[-1].strip() or line
    for line in lines:
        if _RELEVANT_TEXT_RE.search(line) and "VID_" not in line.upper():
            return line.split(":", 1)[-1].strip() or line
    for line in lines:
        if "VID_" in line.upper():
            return line.split(":", 1)[-1].strip() or line
    return "Windows USB-Gerät"


def _usb_inventory(text: str) -> list[dict[str, Any]]:
    """Return every connected USB VID/PID block, not only currently known boards."""
    inventory: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for block in _split_blocks(text):
        instance_match = _USB_INSTANCE_RE.search(block)
        vidpid_match = _VID_PID_RE.search(block)
        if not (instance_match or vidpid_match):
            continue

        vid = vidpid_match.group(1).upper() if vidpid_match else ""
        pid = vidpid_match.group(2).upper() if vidpid_match else ""
        com_match = _COM_RE.search(block)
        port = com_match.group(1).upper() if com_match else ""
        instance = instance_match.group(1).strip() if instance_match else ""
        board_hint = _specific_board_hint(block)
        description = _friendly_line(block, port or None)
        key = (instance.upper(), port, (vid + ":" + pid).upper())
        if key in seen:
            continue
        seen.add(key)
        inventory.append(
            {
                "port": port,
                "instance": instance,
                "vid": vid,
                "pid": pid,
                "description": description,
                "board_hint": board_hint,
                "raw": block,
            }
        )
    return inventory


def _pnputil_usb_snapshot(timeout: float = 4.0) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if os.name != "nt":
        return [], []
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
        return [], []
    stdout, stderr = _decode(proc.stdout), _decode(proc.stderr)
    _emit(
        f"WINDOWS USB FALLBACK END exit={proc.returncode} duration={time.perf_counter()-started:.3f}s "
        f"stdout_chars={len(stdout)} stderr_chars={len(stderr)}"
    )
    if proc.returncode != 0 and stderr.strip():
        _emit(f"WINDOWS USB FALLBACK STDERR {stderr.strip()[:1200]!r}")

    inventory = _usb_inventory(stdout)
    _emit(f"WINDOWS USB INVENTORY COUNT={len(inventory)}")
    for index, item in enumerate(inventory[:_MAX_INVENTORY_LOG], start=1):
        vid, pid = str(item.get("vid") or ""), str(item.get("pid") or "")
        _emit(
            "WINDOWS USB INVENTORY "
            f"item={index}/{len(inventory)} port={item.get('port') or None!r} "
            f"vidpid={(vid + ':' + pid) if vid else None!r} "
            f"board_hint={item.get('board_hint')!r} "
            f"description={item.get('description')!r} instance={item.get('instance')!r}"
        )
    if len(inventory) > _MAX_INVENTORY_LOG:
        _emit(f"WINDOWS USB INVENTORY truncated={len(inventory)-_MAX_INVENTORY_LOG}")

    devices: list[dict[str, Any]] = []
    for item in inventory:
        vid = str(item.get("vid") or "").upper()
        block = str(item.get("raw") or "")
        port = str(item.get("port") or "").upper()
        board_hint = item.get("board_hint")
        relevant_vid = bool(vid and vid in _RELEVANT_VIDS)
        relevant_text = bool(_RELEVANT_TEXT_RE.search(block))

        # Any genuine USB device that already owns a COM port is safe to keep as
        # a candidate even with an unknown VID. Bluetooth COM ports never enter
        # this inventory because they have no USB\\VID_xxxx&PID_xxxx instance.
        if not (board_hint or relevant_vid or relevant_text or port):
            continue
        devices.append(item)
        _emit(
            "WINDOWS USB FALLBACK DEVICE "
            f"port={port or None!r} "
            f"vidpid={(item.get('vid') + ':' + item.get('pid')) if item.get('vid') else None!r} "
            f"board_hint={board_hint!r} description={item.get('description')!r} "
            f"instance={item.get('instance')!r}"
        )
    _emit(f"WINDOWS USB FALLBACK DEVICE COUNT={len(devices)}")
    return devices, inventory


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


def _manual_board_recovery_message(app: Any) -> str:
    try:
        selected = str(app.board_var.get() or "")
    except Exception:
        selected = ""
    if "T-Beam Supreme" in selected:
        return (
            "T-Beam Supreme: kein USB/COM sichtbar · BOOT gedrückt halten → RESET kurz drücken → "
            "RESET loslassen → BOOT loslassen → danach Neu suchen"
        )
    if "T-Beam" in selected:
        return (
            "T-Beam: kein USB/COM sichtbar · BOOT gedrückt halten → RESET kurz drücken → "
            "RESET loslassen → BOOT loslassen → danach Neu suchen"
        )
    return ""


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
    services.serial_usb_inventory = []

    def scan_devices(probe_timeout: int = 8):
        services.serial_usb_no_com = []
        services.serial_usb_no_com_message = ""
        services.serial_usb_inventory = []
        devices = previous_scan(probe_timeout)
        if devices:
            return devices

        snapshot, inventory = _pnputil_usb_snapshot(timeout=4.0)
        services.serial_usb_inventory = inventory
        if not snapshot:
            _emit(
                "WINDOWS USB FALLBACK NO-CANDIDATE "
                f"inventory={len(inventory)} wired-com=0"
            )
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
                    recovery = _manual_board_recovery_message(self)
                    if message and recovery:
                        replacement = f"{message} · {recovery}"
                    elif message:
                        replacement = message
                    elif recovery:
                        replacement = recovery
                return _base(replacement)

            self._set_status = set_status
            self._jarnsen_usb_status_wrapped = True

        ctk.CTk.__init__ = ctk_init
    except Exception as exc:
        _emit(f"WINDOWS USB FALLBACK status patch failed type={type(exc).__name__} message={exc}")

    _emit(
        "WINDOWS USB FALLBACK installed pnputil-connected=1 recover-com=1 "
        "usb-without-com-status=1 robust-decode=1 strict-cdc=1 usb-inventory=all-vidpid "
        "unknown-usb-com=keep tbeam-recovery-hint=1 relevant-vids=303A,1A86,10C4,0403,2886"
    )
