"""v2.2.4: authenticate only when a protected GATT operation requires it.

The GATT-first v2.2.3 transport correctly avoids unnecessary Windows pairing,
but some JARN-MESH characteristics (queue HOLD/log control) require an
authenticated bond. In that case Windows returns Insufficient Authentication
and may display its own "Add device" toast. Handle that state explicitly:

1. Try the requested GATT operation without pairing.
2. On an authentication/security error, run the fixed-PIN Windows pairing flow
   for exactly that device using PIN 240180.
3. Retry the same GATT operation once after pairing.
4. Never loop pairing/retry indefinitely.
"""
from __future__ import annotations

from pathlib import Path
import sys

MARKER = "PATCH_V224_AUTH_ON_DEMAND_RETRY"


def method_span(text: str, name: str) -> tuple[int, int]:
    normal = text.find(f"    def {name}(")
    asynchronous = text.find(f"    async def {name}(")
    starts = [value for value in (normal, asynchronous) if value >= 0]
    if not starts:
        raise SystemExit(f"v2.2.4 method {name} not found")
    start = min(starts)
    candidates = [
        value for value in (
            text.find("\n    def ", start + 1),
            text.find("\n    async def ", start + 1),
            text.find("\n    @", start + 1),
        ) if value >= 0
    ]
    return start, min(candidates) if candidates else len(text)


def replace_method(text: str, name: str, replacement: str) -> str:
    start, end = method_span(text, name)
    return text[:start] + replacement.rstrip() + "\n" + text[end:]


def patch(source: str) -> str:
    if MARKER in source:
        return source

    helper_anchor = "    async def _set_ble_queue_hold_async("
    helper_pos = source.find(helper_anchor)
    if helper_pos < 0:
        raise SystemExit("v2.2.4 queue hold helper anchor not found")

    helper = r'''    # PATCH_V224_AUTH_ON_DEMAND_RETRY
    @staticmethod
    def _ble_auth_required_v224(exc: BaseException) -> bool:
        text = f"{type(exc).__name__}: {exc}".lower()
        return any(token in text for token in (
            "insufficient authentication",
            "insufficient encryption",
            "authentication",
            "not authorized",
            "access denied",
            "0x05",
            "0x0f",
        ))

    async def _pair_for_protected_gatt_v224(self, device: object, label: str) -> None:
        self._trace_v2133(f"{label}: geschützter GATT-Zugriff benötigt Authentifizierung")
        state = await self._windows_pair_fixed_pin_v2133(device, label)
        self._trace_v2133(f"{label}: Authentifizierung abgeschlossen · {state}")
        await asyncio.sleep(0.6)

'''
    source = source[:helper_pos] + helper + source[helper_pos:]

    queue_hold = r'''    async def _set_ble_queue_hold_async(self, ble_device: object, active: bool) -> None:
        label = str(getattr(ble_device, "name", "") or getattr(ble_device, "address", "") or "BLE-Node")

        async def attempt() -> None:
            async with BleakClient(
                ble_device,
                timeout=45.0,
                pair=False,
                winrt={"use_cached_services": False},
            ) as client:
                await self._write_ble_queue_hold(client, active)

        try:
            await attempt()
            return
        except Exception as exc:
            if not self._ble_auth_required_v224(exc):
                raise
            self._trace_v2133(f"{label}: HOLD benötigt Authentifizierung · {exc}")
            await self._pair_for_protected_gatt_v224(ble_device, label)
        await attempt()
'''
    source = replace_method(source, "_set_ble_queue_hold_async", queue_hold)

    start, end = method_span(source, "_ble_download_async")
    method = source[start:end]
    old_open = '''        async with BleakClient(\n            ble_device,\n            timeout=45.0,\n            pair=False,  # PATCH_V223_GATT_FIRST_NO_REPAIR: explicit preflight already decided pairing\n            winrt={"use_cached_services": False},\n        ) as client:\n'''
    if old_open not in method:
        old_open = '''        async with BleakClient(\n            ble_device,\n            timeout=45.0,\n            pair=False,\n            winrt={"use_cached_services": False},\n        ) as client:\n'''
    if old_open not in method:
        raise SystemExit("v2.2.4 BLE download connection anchor not found")

    # Wrap the existing body in a local one-shot transport function, then retry
    # only on authentication/security errors. Preserve the generated download
    # body verbatim to avoid changing protocol semantics.
    open_pos = method.find(old_open)
    body_start = open_pos + len(old_open)
    prefix = method[:open_pos]
    body = method[body_start:]
    body_lines = body.splitlines()
    # Existing body is indented 12 spaces under async-with. Move it to 16 spaces
    # under the local attempt() async-with.
    normalized = []
    for line in body_lines:
        if line.startswith("            "):
            normalized.append("    " + line)
        else:
            normalized.append(line)
    wrapped_body = "\n".join(normalized)
    replacement_tail = '''        async def _download_attempt_v224() -> None:\n            async with BleakClient(\n                ble_device,\n                timeout=45.0,\n                pair=False,\n                winrt={"use_cached_services": False},\n            ) as client:\n''' + wrapped_body + '''\n\n        try:\n            await _download_attempt_v224()\n        except Exception as exc:\n            if not self._ble_auth_required_v224(exc):\n                raise\n            self._trace_v2133(f"{label}: Logzugriff benötigt Authentifizierung · {exc}")\n            await self._pair_for_protected_gatt_v224(ble_device, label)\n            await _download_attempt_v224()\n'''
    method = prefix + replacement_tail
    source = source[:start] + method.rstrip() + "\n" + source[end:]

    # Replace misleading Windows HRESULT text when the OS cancels/withdraws a
    # pairing request without explicit user action.
    source = source.replace(
        "Der Vorgang wurde durch den Benutzer abgebrochen.",
        "Windows hat den Bluetooth-Vorgang beendet oder verworfen.",
    )

    required = (
        MARKER,
        "def _ble_auth_required_v224",
        "geschützter GATT-Zugriff benötigt Authentifizierung",
        "Logzugriff benötigt Authentifizierung",
        "Windows hat den Bluetooth-Vorgang beendet oder verworfen.",
    )
    missing = [item for item in required if item not in source]
    if missing:
        raise SystemExit("v2.2.4 auth retry validation failed: " + ", ".join(missing))
    return source


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: patch_jarnsen_service_tool_v224_auth_retry.py <source.py>")
    path = Path(sys.argv[1])
    path.write_text(patch(path.read_text(encoding="utf-8")), encoding="utf-8")
    print("Applied Service Tool v2.2.4: authenticated GATT retry with fixed PIN")


if __name__ == "__main__":
    main()
