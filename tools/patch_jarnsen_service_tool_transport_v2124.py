"""Transport fixes used by Service Tool v2.1.24.

- Let Windows establish/refresh the BLE bond automatically before encrypted
  diagnostic HOLD/START writes.
- Give native USB a short settle period before JARNSEN_TOOL_HELLO and resend the
  handshake while waiting, instead of relying on one write immediately after
  COM open.
"""
from __future__ import annotations

import sys
from pathlib import Path


def method_span(text: str, name: str) -> tuple[int, int]:
    normal = text.find(f"    def {name}(")
    asynchronous = text.find(f"    async def {name}(")
    starts = [value for value in (normal, asynchronous) if value >= 0]
    if not starts:
        raise SystemExit(f"transport v2.1.24 method {name} not found")
    start = min(starts)
    next_method = text.find("\n    def ", start + 1)
    next_async = text.find("\n    async def ", start + 1)
    next_decorator = text.find("\n    @", start + 1)
    candidates = [value for value in (next_method, next_async, next_decorator) if value >= 0]
    return start, min(candidates) if candidates else len(text)


def replace_method(text: str, name: str, updater) -> str:
    start, end = method_span(text, name)
    return text[:start] + updater(text[start:end]) + text[end:]


def patch(source: str) -> str:
    if "PATCH_TRANSPORT_V2124" in source:
        return source

    def pair_ble(method: str) -> str:
        old = '            pair=False,\n'
        if old not in method:
            if '            pair=True,\n' in method:
                return method
            raise SystemExit("transport v2.1.24 BLE pair anchor missing")
        return method.replace(old, '            pair=True,\n', 1)

    source = replace_method(source, "_set_ble_queue_hold_async", pair_ble)
    source = replace_method(source, "_ble_download_async", pair_ble)

    def patch_download(method: str) -> str:
        open_anchor = '''            ser.open()\n            sync_usb_identity = self._usb_identity_for_port_v2120(port)\n'''
        open_new = '''            ser.open()\n            if auto_mode:\n                # Native ESP32-S3 USB can enumerate before the command parser is\n                # fully ready. Do not fire HELLO in the same millisecond as open.\n                time.sleep(1.2)\n            sync_usb_identity = self._usb_identity_for_port_v2120(port)\n'''
        if "Native ESP32-S3 USB can enumerate" not in method:
            if method.count(open_anchor) != 1:
                raise SystemExit("transport v2.1.24 USB settle anchor missing")
            method = method.replace(open_anchor, open_new, 1)

        state_anchor = '''            sync_generation = 0\n            sync_cursor = 0\n            if auto_mode:\n'''
        state_new = '''            sync_generation = 0\n            sync_cursor = 0\n            handshake_last_send_v2124 = 0.0\n            handshake_retry_count_v2124 = 0\n            if auto_mode:\n'''
        if "handshake_retry_count_v2124" not in method:
            if method.count(state_anchor) != 1:
                raise SystemExit("transport v2.1.24 handshake-state anchor missing")
            method = method.replace(state_anchor, state_new, 1)

        log_anchor = '''                tool_log("USB_LOG_HANDSHAKE_V2120", port=port, usb_identity=sync_usb_identity, node_id=sync_managed_node_id or "--", generation=sync_generation, cursor=sync_cursor, full=force_full)\n'''
        log_new = log_anchor + '''                handshake_last_send_v2124 = time.monotonic()\n'''
        if "handshake_last_send_v2124 = time.monotonic()" not in method:
            if method.count(log_anchor) != 1:
                raise SystemExit("transport v2.1.24 handshake log anchor missing")
            method = method.replace(log_anchor, log_new, 1)

        loop_anchor = '''                chunk = ser.read(4096)\n                if chunk:\n                    scan.extend(chunk)\n'''
        loop_new = '''                chunk = ser.read(4096)\n                if (\n                    auto_mode\n                    and not chunk\n                    and not started\n                    and handshake_retry_count_v2124 < 6\n                    and time.monotonic() - handshake_last_send_v2124 >= 5.0\n                ):\n                    ser.write(command.encode("ascii"))\n                    ser.flush()\n                    handshake_last_send_v2124 = time.monotonic()\n                    handshake_retry_count_v2124 += 1\n                    tool_log(\n                        "USB_LOG_HANDSHAKE_RETRY_V2124",\n                        port=port,\n                        retry=handshake_retry_count_v2124,\n                        generation=sync_generation,\n                        cursor=sync_cursor,\n                        full=force_full,\n                    )\n                if chunk:\n                    scan.extend(chunk)\n'''
        if "USB_LOG_HANDSHAKE_RETRY_V2124" not in method:
            if method.count(loop_anchor) != 1:
                raise SystemExit("transport v2.1.24 read-loop anchor missing")
            method = method.replace(loop_anchor, loop_new, 1)

        method = method.replace(
            "            deadline = time.monotonic() + (100 if auto_mode else 300)\n",
            "            deadline = time.monotonic() + (120 if auto_mode else 300)\n",
            1,
        )
        return method

    source = replace_method(source, "_download_worker", patch_download)
    source += "\n# PATCH_TRANSPORT_V2124\n"

    required = (
        "pair=True,",
        "Native ESP32-S3 USB can enumerate",
        "USB_LOG_HANDSHAKE_RETRY_V2124",
        "handshake_retry_count_v2124",
        "(120 if auto_mode else 300)",
        "PATCH_TRANSPORT_V2124",
    )
    missing = [marker for marker in required if marker not in source]
    if missing:
        raise SystemExit("transport v2.1.24 validation failed: " + ", ".join(missing))
    return source


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: patch_jarnsen_service_tool_transport_v2124.py <source.py>")
    path = Path(sys.argv[1])
    path.write_text(patch(path.read_text(encoding="utf-8")), encoding="utf-8")
    print(f"Patched {path}: BLE pair + robust USB HELLO retry")


if __name__ == "__main__":
    main()
