"""v2.1.25: resilient auto USB log retries and JARN-MESH semantic version labels."""
from __future__ import annotations

import re
import sys
from pathlib import Path

APP_VERSION = "2.1.25"


def method_span(text: str, name: str) -> tuple[int, int]:
    normal = text.find(f"    def {name}(")
    asynchronous = text.find(f"    async def {name}(")
    starts = [value for value in (normal, asynchronous) if value >= 0]
    if not starts:
        raise SystemExit(f"v2.1.25 method {name} not found")
    start = min(starts)
    next_method = text.find("\n    def ", start + 1)
    next_async = text.find("\n    async def ", start + 1)
    next_decorator = text.find("\n    @", start + 1)
    candidates = [value for value in (next_method, next_async, next_decorator) if value >= 0]
    return start, min(candidates) if candidates else len(text)


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"v2.1.25 {label} anchor missing or ambiguous ({count})")
    return text.replace(old, new, 1)


def patch(source: str) -> str:
    if "PATCH_V2125_AUTO_USB_SEMVER" in source:
        return source

    source = re.sub(r'APP_VERSION = "[^"]+"', f'APP_VERSION = "{APP_VERSION}"', source, count=1)
    source = source.replace('APP_VERSION != "2.1.24"', 'APP_VERSION != "2.1.25"')
    source = source.replace("App-Version ist nicht v2.1.24", "App-Version ist nicht v2.1.25")

    # Diagnostics now carry a dedicated JARN-MESH semantic version.  Keep the
    # Meshtastic/internal APP_VERSION separately so exact troubleshooting data is
    # never lost, but all normal UI firmware labels use the product version.
    helper_anchor = '''def log_metrics(payload: bytes) -> dict[str, str]:\n'''
    helper = r'''def jarnsen_firmware_label(payload: bytes) -> str:
    semantic = header_value(payload, b"jarnsen_version").strip()
    if semantic:
        if semantic.lower().startswith("jarn-mesh"):
            return semantic
        if not semantic.lower().startswith("v"):
            semantic = "v" + semantic
        return f"JARN-MESH {semantic}"
    return header_value(payload, b"firmware")


def log_metrics(payload: bytes) -> dict[str, str]:
'''
    source = replace_once(source, helper_anchor, helper, "semantic-version helper")
    source = replace_once(
        source,
        '''        "firmware": header_value(payload, b"firmware"),\n        "build": header_value(payload, b"build"),\n''',
        '''        "firmware": jarnsen_firmware_label(payload),\n        "meshtastic_firmware": header_value(payload, b"firmware"),\n        "jarnsen_version": header_value(payload, b"jarnsen_version"),\n        "build": header_value(payload, b"build"),\n''',
        "metrics firmware label",
    )

    # Replace the one-shot serial worker with a bounded retry state machine for
    # automatic USB attach.  Windows ESP32-S3 CDC can transiently throw
    # ClearCommError/Access denied or re-enumerate after wake/reset.  Manual
    # downloads remain a single long attempt; auto mode re-finds the physical USB
    # device, reopens it and re-sends HELLO up to four times.
    start, end = method_span(source, "_download_worker")
    replacement = r'''    def _download_worker(
        self,
        port: str,
        auto_mode: bool = False,
        force_full: bool = False,
        retry_attempt: int = 1,
        physical_identity: dict[str, object] | None = None,
    ) -> None:
        ser: serial.Serial | None = None
        delegated_retry = False
        bytes_seen = 0
        attempt_started = time.monotonic()
        if auto_mode and physical_identity is None:
            with contextlib.suppress(Exception):
                physical_identity = self._serial_port_identity(port)
        try:
            if auto_mode:
                # Give a freshly enumerated ESP32-S3 CDC endpoint a short grace
                # period before the first open.  Subsequent attempts already wait
                # while re-finding the physical device.
                if retry_attempt == 1:
                    time.sleep(1.5)
                tool_log(
                    "AUTO_USB_ATTEMPT_V2125",
                    port=port,
                    attempt=retry_attempt,
                    identity=self._serial_identity_key(physical_identity or {}) or "--",
                )
            self.events.put(("status", f"Öffne {port} ohne DTR/RTS-Reset ..."))
            self.events.put(("progress_detail", (None, "Port öffnen", True)))
            ser = serial.Serial()
            ser.port = port
            ser.baudrate = 115200
            ser.timeout = 0.10
            ser.write_timeout = 1.0
            ser.rtscts = False
            ser.dsrdtr = False
            ser.dtr = False
            ser.rts = False
            ser.open()

            sync_usb_identity = self._usb_identity_for_port_v2120(port)
            sync_managed_node_id = ""
            sync_generation = 0
            sync_cursor = 0
            if auto_mode:
                if sync_usb_identity:
                    sync_managed_node_id, sync_generation, sync_cursor = self.repository.log_sync_for_usb(sync_usb_identity)
                command = (
                    "JARNSEN_TOOL_FULL 1\n"
                    if force_full
                    else f"JARNSEN_TOOL_HELLO 1 {int(sync_generation)} {int(sync_cursor)}\n"
                )
                ser.write(command.encode("ascii"))
                ser.flush()
                tool_log(
                    "USB_LOG_HANDSHAKE_V2120",
                    port=port,
                    usb_identity=sync_usb_identity,
                    node_id=sync_managed_node_id or "--",
                    generation=sync_generation,
                    cursor=sync_cursor,
                    full=force_full,
                )
            self.events.put(("status", f"{port} offen - warte auf Diagnostikexport" if auto_mode else f"{port} offen - jetzt Export am Gerät bestätigen"))
            self.events.put(("progress_detail", (None, "Warte auf Export", True)))

            scan = bytearray()
            captured = bytearray()
            end_marker = b""
            started = False
            expected = 0
            # Four ~35 s windows cover the observed 70-80 s post-wake delay while
            # also recovering by reopening/re-handshaking instead of waiting on a
            # dead Windows CDC handle for the full timeout.
            deadline = time.monotonic() + (35 if auto_mode else 300)
            while not self.stop_event.is_set() and time.monotonic() < deadline:
                chunk = ser.read(4096)
                if chunk:
                    bytes_seen += len(chunk)
                    scan.extend(chunk)
                if not started:
                    found = None
                    for begin, end_marker_candidate in PROTOCOLS:
                        pos = scan.find(begin)
                        if pos >= 0:
                            found = (pos, begin, end_marker_candidate)
                            break
                    if not found:
                        pos = scan.find(b"# device=HELTEC_")
                        if pos >= 0:
                            found = (pos, b"", PROTOCOLS[0][1])
                    if not found:
                        if len(scan) > 1024:
                            del scan[:-1024]
                        continue
                    pos, begin, end_marker = found
                    after = bytes(scan[pos + len(begin) :]).lstrip(b"\r\n")
                    scan.clear()
                    scan.extend(after)
                    started = True
                    tool_log("SERIAL_TRANSFER_BEGIN", port=port, begin_marker=begin or b"header-recovery")
                    self.events.put(("status", "Transfer erkannt"))
                    self.events.put(("progress_detail", (None, "Log vorbereiten", True)))

                header = bytes(captured[-2048:]) + bytes(scan[:4096])
                match = re.search(rb"(?m)^# bytes=(\d+)\r?$", header)
                if match:
                    expected = int(match.group(1))
                end_pos = scan.find(end_marker)
                if end_pos >= 0:
                    captured.extend(scan[:end_pos].rstrip(b"\r\n"))
                    self._delta_sync_context_v2120 = {
                        "port": port,
                        "usb_identity": sync_usb_identity,
                        "managed_node_id": sync_managed_node_id,
                    } if auto_mode else None
                    self._finish_payload(bytes(captured), expected)
                    if auto_mode:
                        tool_log(
                            "AUTO_USB_SUCCESS_V2125",
                            port=port,
                            attempt=retry_attempt,
                            bytes=bytes_seen,
                            duration_s=f"{time.monotonic() - attempt_started:.2f}",
                        )
                    return
                keep = max(1, len(end_marker) - 1)
                if len(scan) > keep:
                    take = len(scan) - keep
                    captured.extend(scan[:take])
                    del scan[:take]
                if expected:
                    progress_bytes = bytes(captured) + bytes(scan)
                    bytes_header = re.search(rb"(?m)^# bytes=(\d+)\r?$", progress_bytes[:4096])
                    data_start = bytes_header.end() if bytes_header else len(progress_bytes)
                    while data_start < len(progress_bytes) and progress_bytes[data_start] in b"\r\n":
                        data_start += 1
                    transferred = min(expected, max(0, len(progress_bytes) - data_start))
                    self.events.put((
                        "progress_detail",
                        (
                            min(99, int(transferred * 100 / expected)),
                            f"Übertragen {transferred:,}/{expected:,} Bytes".replace(",", "."),
                            False,
                        ),
                    ))

            if started:
                captured.extend(scan)
                partial = output_directory() / f"Jarnsen_Node_Log_PARTIAL_{now_local():%Y-%m-%d_%H%M%S}.txt"
                partial.write_bytes(bytes(captured))
                raise RuntimeError(f"Transfer abgebrochen. Teil-Datei: {partial}")
            if auto_mode and retry_attempt < 4 and not self.stop_event.is_set():
                delegated_retry = True
                tool_log("AUTO_USB_RETRY_V2125", port=port, attempt=retry_attempt, reason="no-marker", bytes=bytes_seen)
                if ser and ser.is_open:
                    ser.close()
                time.sleep(2.0)
                retry_port = port
                if physical_identity:
                    retry_port = self._wait_for_matching_serial_port(physical_identity, port, timeout=15.0)
                    tool_log("AUTO_USB_REFIND_V2125", old_port=port, new_port=retry_port, attempt=retry_attempt + 1)
                return self._download_worker(retry_port, True, force_full, retry_attempt + 1, physical_identity)
            if auto_mode:
                tool_log("AUTO_USB_GIVEUP_V2125", port=port, attempt=retry_attempt, reason="no-marker", bytes=bytes_seen)
                self.events.put(("auto_log_no_export", port))
                return
            raise RuntimeError("Kein Exportmarker empfangen. Export am Gerät erneut bestätigen.")
        except serial.SerialException as exc:
            if auto_mode and retry_attempt < 4 and not self.stop_event.is_set():
                delegated_retry = True
                tool_log("AUTO_USB_RETRY_V2125", port=port, attempt=retry_attempt, reason=type(exc).__name__, error=exc, bytes=bytes_seen)
                with contextlib.suppress(Exception):
                    if ser and ser.is_open:
                        ser.close()
                time.sleep(2.0)
                try:
                    retry_port = self._wait_for_matching_serial_port(physical_identity or {}, port, timeout=15.0) if physical_identity else port
                except Exception as refind_exc:
                    tool_log("AUTO_USB_REFIND_V2125", old_port=port, new_port="--", attempt=retry_attempt + 1, error=refind_exc)
                    retry_port = port
                else:
                    tool_log("AUTO_USB_REFIND_V2125", old_port=port, new_port=retry_port, attempt=retry_attempt + 1)
                return self._download_worker(retry_port, True, force_full, retry_attempt + 1, physical_identity)
            raise_text = f"Port {port} konnte nicht geöffnet/gelesen werden: {exc}\nAlle Serial-Monitore schließen oder Blockersuche verwenden."
            self.events.put(("status_warning" if auto_mode else "error", raise_text))
            if auto_mode:
                tool_log("AUTO_USB_GIVEUP_V2125", port=port, attempt=retry_attempt, reason=type(exc).__name__, error=exc, bytes=bytes_seen)
        except Exception as exc:
            if auto_mode and retry_attempt < 4 and not self.stop_event.is_set():
                delegated_retry = True
                tool_log("AUTO_USB_RETRY_V2125", port=port, attempt=retry_attempt, reason=type(exc).__name__, error=exc, bytes=bytes_seen)
                with contextlib.suppress(Exception):
                    if ser and ser.is_open:
                        ser.close()
                time.sleep(2.0)
                retry_port = port
                with contextlib.suppress(Exception):
                    if physical_identity:
                        retry_port = self._wait_for_matching_serial_port(physical_identity, port, timeout=15.0)
                return self._download_worker(retry_port, True, force_full, retry_attempt + 1, physical_identity)
            self.events.put(("status_warning" if auto_mode else "error", str(exc)))
            if auto_mode:
                tool_log("AUTO_USB_GIVEUP_V2125", port=port, attempt=retry_attempt, reason=type(exc).__name__, error=exc, bytes=bytes_seen)
        finally:
            with contextlib.suppress(Exception):
                if ser and ser.is_open:
                    ser.close()
            tool_log("SERIAL_WORKER_END", port=port, bytes=bytes_seen, duration_s=f"{time.monotonic() - attempt_started:.2f}")
            if not delegated_retry:
                self.events.put(("done", None))
'''
    source = source[:start] + replacement.rstrip() + "\n" + source[end:]

    source += "\n# PATCH_V2125_AUTO_USB_SEMVER\n"
    required = (
        'APP_VERSION = "2.1.25"',
        'def jarnsen_firmware_label(payload: bytes)',
        'b"jarnsen_version"',
        '"meshtastic_firmware": header_value(payload, b"firmware")',
        'AUTO_USB_ATTEMPT_V2125',
        'AUTO_USB_RETRY_V2125',
        'AUTO_USB_REFIND_V2125',
        'AUTO_USB_SUCCESS_V2125',
        'AUTO_USB_GIVEUP_V2125',
        'retry_attempt: int = 1',
        'time.monotonic() + (35 if auto_mode else 300)',
        'PATCH_V2125_AUTO_USB_SEMVER',
    )
    missing = [marker for marker in required if marker not in source]
    if missing:
        raise SystemExit("v2.1.25 validation failed: " + ", ".join(missing))
    return source


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: patch_jarnsen_service_tool_v2125.py <source.py>")
    path = Path(sys.argv[1])
    path.write_text(patch(path.read_text(encoding="utf-8")), encoding="utf-8")
    print(f"Patched {path} to v{APP_VERSION}: resilient auto USB log + JARN-MESH semantic versions")


if __name__ == "__main__":
    main()
