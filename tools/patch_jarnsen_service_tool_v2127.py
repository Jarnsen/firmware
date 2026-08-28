"""v2.1.27: keep automatic USB log sessions alive until success or explicit cancel.

Observed on Windows/ESP32-S3 after provisioning:
- first HELLO may hit ClearCommError while the CDC endpoint re-enumerates,
- a later attempt can receive ordinary bytes but no export marker,
- the generic stop_event can remain/set transiently and prematurely terminate
  the current auto cycle even though the user did not press Cancel,
- the same node then succeeds on the next watcher cycle a few seconds later.

For auto USB logging we therefore distinguish an explicit user/app cancel from
an incidental stop_event, extend the bounded retry window, and keep one logical
session alive instead of surfacing a false failure between watcher cycles.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

APP_VERSION = "2.1.27"


def method_span(text: str, name: str) -> tuple[int, int]:
    normal = text.find(f"    def {name}(")
    asynchronous = text.find(f"    async def {name}(")
    starts = [value for value in (normal, asynchronous) if value >= 0]
    if not starts:
        raise SystemExit(f"v2.1.27 method {name} not found")
    start = min(starts)
    next_method = text.find("\n    def ", start + 1)
    next_async = text.find("\n    async def ", start + 1)
    next_decorator = text.find("\n    @", start + 1)
    candidates = [value for value in (next_method, next_async, next_decorator) if value >= 0]
    return start, min(candidates) if candidates else len(text)


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"v2.1.27 {label}: expected one anchor, got {count}")
    return text.replace(old, new, 1)


def replace_method(text: str, name: str, updater) -> str:
    start, end = method_span(text, name)
    return text[:start] + updater(text[start:end]) + text[end:]


def patch(source: str) -> str:
    if "PATCH_V2127_STICKY_AUTO_USB" in source:
        return source

    source = re.sub(r'APP_VERSION = "[^"]+"', f'APP_VERSION = "{APP_VERSION}"', source, count=1)
    source = source.replace('APP_VERSION != "2.1.26"', 'APP_VERSION != "2.1.27"')
    source = source.replace("App-Version ist nicht v2.1.26", "App-Version ist nicht v2.1.27")

    def add_explicit_cancel_flag(method: str, label: str) -> str:
        marker = '        self.stop_event.set()\n'
        if '        self._user_cancel_requested_v2127 = True\n' in method:
            return method
        count = method.count(marker)
        if count != 1:
            raise SystemExit(f"v2.1.27 {label} stop-event anchor count={count}")
        return method.replace(
            marker,
            '        self._user_cancel_requested_v2127 = True\n' + marker,
            1,
        )

    source = replace_method(source, "cancel", lambda method: add_explicit_cancel_flag(method, "cancel"))
    source = replace_method(source, "close_app", lambda method: add_explicit_cancel_flag(method, "close"))

    def patch_auto_start(method: str) -> str:
        anchor = 'self._select_serial_port_in_ui(port); self.stop_event.clear();'
        replacement = 'self._select_serial_port_in_ui(port); self._user_cancel_requested_v2127 = False; self.stop_event.clear();'
        if replacement in method:
            return method
        if method.count(anchor) != 1:
            raise SystemExit(f"v2.1.27 auto-start anchor count={method.count(anchor)}")
        return method.replace(anchor, replacement, 1)

    source = replace_method(source, "_start_auto_usb_download", patch_auto_start)

    def patch_download(method: str) -> str:
        state_anchor = '''        bytes_seen = 0\n        ack_seen_v2126 = False\n        ack_text_v2126 = ""\n        attempt_started = time.monotonic()\n'''
        state_new = '''        bytes_seen = 0\n        ack_seen_v2126 = False\n        ack_text_v2126 = ""\n        attempt_started = time.monotonic()\n        explicit_cancel_v2127 = lambda: bool(\n            self.stop_event.is_set() and getattr(self, "_user_cancel_requested_v2127", False)\n        )\n        if auto_mode and self.stop_event.is_set() and not explicit_cancel_v2127():\n            tool_log("AUTO_USB_STALE_STOP_V2127", port=port, attempt=retry_attempt)\n            self.stop_event.clear()\n'''
        method = replace_once(method, state_anchor, state_new, "download cancel state")

        method = replace_once(
            method,
            '            deadline = time.monotonic() + (35 if auto_mode else 300)\n',
            '            deadline = time.monotonic() + (45 if auto_mode else 300)\n',
            "attempt deadline",
        )
        method = replace_once(
            method,
            '            while not self.stop_event.is_set() and time.monotonic() < deadline:\n',
            '            while not explicit_cancel_v2127() and time.monotonic() < deadline:\n',
            "loop cancel condition",
        )

        old_condition = 'if auto_mode and retry_attempt < 4 and not self.stop_event.is_set():'
        count = method.count(old_condition)
        if count != 3:
            raise SystemExit(f"v2.1.27 retry-condition count={count}")
        method = method.replace(old_condition, 'if auto_mode and retry_attempt < 8 and not explicit_cancel_v2127():')

        recursive_call = 'return self._download_worker(retry_port, True, force_full, retry_attempt + 1, physical_identity)'
        count = method.count(recursive_call)
        if count != 3:
            raise SystemExit(f"v2.1.27 recursive retry call count={count}")
        method = method.replace(
            recursive_call,
            'self.stop_event.clear()\n                ' + recursive_call,
        )

        marker = '''            if started:\n                captured.extend(scan)\n'''
        cancel_block = '''            if explicit_cancel_v2127():\n                tool_log("AUTO_USB_CANCELLED_V2127", port=port, attempt=retry_attempt, bytes=bytes_seen)\n                return\n            if started:\n                captured.extend(scan)\n'''
        method = replace_once(method, marker, cancel_block, "explicit cancel result")
        return method

    source = replace_method(source, "_download_worker", patch_download)
    source += "\n# PATCH_V2127_STICKY_AUTO_USB\n"

    required = (
        'APP_VERSION = "2.1.27"',
        '_user_cancel_requested_v2127 = True',
        '_user_cancel_requested_v2127 = False',
        'AUTO_USB_STALE_STOP_V2127',
        'AUTO_USB_CANCELLED_V2127',
        'retry_attempt < 8',
        '(45 if auto_mode else 300)',
        'while not explicit_cancel_v2127()',
        'PATCH_V2127_STICKY_AUTO_USB',
    )
    missing = [marker for marker in required if marker not in source]
    if missing:
        raise SystemExit("v2.1.27 validation failed: " + ", ".join(missing))
    return source


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: patch_jarnsen_service_tool_v2127.py <source.py>")
    path = Path(sys.argv[1])
    path.write_text(patch(path.read_text(encoding="utf-8")), encoding="utf-8")
    print(f"Patched {path} to v{APP_VERSION}: sticky automatic USB log session")


if __name__ == "__main__":
    main()
