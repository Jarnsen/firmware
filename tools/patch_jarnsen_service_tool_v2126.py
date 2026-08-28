"""Post-v2.1.25 patch: make native USB auto-log handshake observable.

New Tracker/V3 firmware replies with JARNSEN_TOOL_ACK before starting a diagnostic
export. Record that acknowledgement explicitly so a screenshot/tool log can
separate these states:
  PC opened COM -> HELLO sent -> node ACK received -> export marker received.
The ACK remains ordinary preamble data and is not written into the diagnostic
payload itself. This is a transport revision of the current v2.1.25 package, so
its public app version remains unchanged while the build SHA identifies it.
"""
from __future__ import annotations

import sys
from pathlib import Path


def method_span(text: str, name: str) -> tuple[int, int]:
    normal = text.find(f"    def {name}(")
    asynchronous = text.find(f"    async def {name}(")
    starts = [value for value in (normal, asynchronous) if value >= 0]
    if not starts:
        raise SystemExit(f"v2.1.25 ACK patch method {name} not found")
    start = min(starts)
    next_method = text.find("\n    def ", start + 1)
    next_async = text.find("\n    async def ", start + 1)
    next_decorator = text.find("\n    @", start + 1)
    candidates = [value for value in (next_method, next_async, next_decorator) if value >= 0]
    return start, min(candidates) if candidates else len(text)


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"v2.1.25 ACK {label}: expected one anchor, got {count}")
    return text.replace(old, new, 1)


def patch(source: str) -> str:
    if "PATCH_V2126_USB_NODE_ACK" in source:
        return source

    start, end = method_span(source, "_download_worker")
    method = source[start:end]

    state_old = '''        bytes_seen = 0\n        attempt_started = time.monotonic()\n'''
    state_new = '''        bytes_seen = 0\n        ack_seen_v2126 = False\n        ack_text_v2126 = ""\n        attempt_started = time.monotonic()\n'''
    method = replace_once(method, state_old, state_new, "ACK state")

    scan_old = '''                if chunk:\n                    bytes_seen += len(chunk)\n                    scan.extend(chunk)\n                if not started:\n'''
    scan_new = '''                if chunk:\n                    bytes_seen += len(chunk)\n                    scan.extend(chunk)\n                    if auto_mode and not ack_seen_v2126:\n                        ack_match_v2126 = re.search(\n                            rb"JARNSEN_TOOL_ACK 1 (?:HELLO \\d+ \\d+|FULL)\\r?\\n",\n                            scan,\n                        )\n                        if ack_match_v2126:\n                            ack_seen_v2126 = True\n                            ack_text_v2126 = ack_match_v2126.group(0).decode("ascii", "replace").strip()\n                            tool_log(\n                                "USB_LOG_ACK_V2126",\n                                port=port,\n                                attempt=retry_attempt,\n                                ack=ack_text_v2126,\n                            )\n                            self.events.put(("status", "Node bestätigt USB-Loganfrage - Export startet"))\n                            self.events.put(("progress_detail", (None, "Node bestätigt Anfrage", True)))\n                if not started:\n'''
    method = replace_once(method, scan_old, scan_new, "ACK scanner")

    retry_old = '''                tool_log("AUTO_USB_RETRY_V2125", port=port, attempt=retry_attempt, reason="no-marker", bytes=bytes_seen)\n'''
    retry_new = '''                retry_reason_v2126 = "ack-without-export" if ack_seen_v2126 else "no-node-ack"\n                tool_log(\n                    "AUTO_USB_RETRY_V2125",\n                    port=port,\n                    attempt=retry_attempt,\n                    reason=retry_reason_v2126,\n                    bytes=bytes_seen,\n                    ack=ack_text_v2126 or "--",\n                )\n'''
    method = replace_once(method, retry_old, retry_new, "retry reason")

    giveup_old = '''                tool_log("AUTO_USB_GIVEUP_V2125", port=port, attempt=retry_attempt, reason="no-marker", bytes=bytes_seen)\n                self.events.put(("auto_log_no_export", port))\n'''
    giveup_new = '''                giveup_reason_v2126 = "ack-without-export" if ack_seen_v2126 else "no-node-ack"\n                tool_log(\n                    "AUTO_USB_GIVEUP_V2125",\n                    port=port,\n                    attempt=retry_attempt,\n                    reason=giveup_reason_v2126,\n                    bytes=bytes_seen,\n                    ack=ack_text_v2126 or "--",\n                )\n                if ack_seen_v2126:\n                    self.events.put(("status_warning", "Node hat die USB-Anfrage bestätigt, aber keinen Exportmarker geliefert."))\n                else:\n                    self.events.put(("status_warning", "Keine USB-Bestätigung der Node empfangen; COM/Node-Empfang prüfen."))\n                self.events.put(("auto_log_no_export", port))\n'''
    method = replace_once(method, giveup_old, giveup_new, "giveup reason")

    source = source[:start] + method + source[end:]
    source += "\n# PATCH_V2126_USB_NODE_ACK\n"

    required = (
        'APP_VERSION = "2.1.25"',
        "USB_LOG_ACK_V2126",
        "Node bestätigt USB-Loganfrage - Export startet",
        "ack-without-export",
        "no-node-ack",
        "PATCH_V2126_USB_NODE_ACK",
    )
    missing = [marker for marker in required if marker not in source]
    if missing:
        raise SystemExit("v2.1.25 ACK validation failed: " + ", ".join(missing))
    return source


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: patch_jarnsen_service_tool_v2126.py <source.py>")
    path = Path(sys.argv[1])
    path.write_text(patch(path.read_text(encoding="utf-8")), encoding="utf-8")
    print(f"Patched {path}: explicit node USB ACK telemetry")


if __name__ == "__main__":
    main()
