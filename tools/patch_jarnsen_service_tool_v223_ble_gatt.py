"""v2.2.3: avoid repeated Windows pairing when direct Meshtastic GATT already works.

Windows 11 can reject the custom fixed-PIN pairing ceremony with
REJECTED_BY_HANDLER even while the same node is directly reachable over GATT.
The v2.2.2 fallback proved that state only after several pairing attempts, and
the actual log/HOLD connection was then opened again with pair=True. That caused
a second Windows pairing failure and could repeatedly disturb/restart the node
when automatic log maintenance retried.

This patch makes the transport fail-soft and non-invasive:
1. Probe direct GATT first with pair=False.
2. Only run Windows fixed-PIN pairing if that direct connection is unavailable.
3. After the explicit preflight, log download and queue HOLD never request a
   second implicit Windows pairing.
"""
from __future__ import annotations

import sys
from pathlib import Path

MARKER = "PATCH_V223_GATT_FIRST_NO_REPAIR"


def method_span(text: str, name: str) -> tuple[int, int]:
    normal = text.find(f"    def {name}(")
    asynchronous = text.find(f"    async def {name}(")
    starts = [value for value in (normal, asynchronous) if value >= 0]
    if not starts:
        raise SystemExit(f"v2.2.3 method {name} not found")
    start = min(starts)
    candidates = [
        value
        for value in (
            text.find("\n    def ", start + 1),
            text.find("\n    async def ", start + 1),
            text.find("\n    @", start + 1),
        )
        if value >= 0
    ]
    return start, min(candidates) if candidates else len(text)


def replace_method(text: str, name: str, replacement: str) -> str:
    start, end = method_span(text, name)
    return text[:start] + replacement.rstrip() + "\n" + text[end:]


def disable_implicit_pairing(text: str, name: str) -> str:
    start, end = method_span(text, name)
    method = text[start:end]
    if "pair=True," not in method:
        raise SystemExit(f"v2.2.3 {name} expected pair=True")
    method = method.replace(
        "pair=True,",
        "pair=False,  # PATCH_V223_GATT_FIRST_NO_REPAIR: explicit preflight already decided pairing",
        1,
    )
    return text[:start] + method + text[end:]


def patch(source: str) -> str:
    if MARKER in source:
        return source

    replacement = r'''    async def _windows_pair_fixed_pin_v2133(self, device: object, label: str = "") -> str:
        # PATCH_V223_GATT_FIRST_NO_REPAIR
        if sys.platform != "win32":
            return "nicht-Windows"
        from winrt.windows.devices.bluetooth import BluetoothLEDevice
        from winrt.windows.devices.enumeration import (
            DeviceInformation,
            DevicePairingKinds,
            DevicePairingProtectionLevel,
            DevicePairingResultStatus,
        )

        requester = await BluetoothLEDevice.from_bluetooth_address_async(
            self._ble_address_int_v2133(device)
        )
        if requester is None:
            raise RuntimeError("Windows konnte das BLE-Gerät nicht öffnen")
        try:
            info = await DeviceInformation.create_from_id_async(requester.device_information.id)
            if info.pairing.is_paired:
                return "bereits gekoppelt"

            # Important: Windows can reject the custom pairing ceremony even
            # though the Meshtastic GATT server is already usable. Prove the
            # least-invasive path first and do not touch the Windows bond state
            # when it is unnecessary.
            try:
                async with BleakClient(
                    device,
                    timeout=15.0,
                    pair=False,
                    winrt={"use_cached_services": False},
                ) as client:
                    if client.is_connected:
                        self._trace_v2133(
                            f"{label}: GATT direkt erreichbar · Windows-Kopplung wird übersprungen"
                        )
                        return "GATT direkt erreichbar; Windows-Kopplung nicht nötig"
            except Exception as exc:
                self._trace_v2133(
                    f"{label}: GATT-Vorprobe nicht ausreichend · {type(exc).__name__}: {exc}"
                )

            if not info.pairing.can_pair:
                raise RuntimeError("Windows meldet das Gerät als nicht koppelbar")

            custom = info.pairing.custom
            request_kinds: list[str] = []

            def requested(_sender: object, args: object) -> None:
                kind = args.pairing_kind
                kind_name = str(getattr(kind, "name", kind))
                request_kinds.append(kind_name)
                self._trace_v2133(f"{label}: Windows PairingRequested · {kind_name}")
                if kind == DevicePairingKinds.PROVIDE_PIN:
                    args.accept(DEFAULT_BT_PIN_V2133)
                else:
                    args.accept()

            token = custom.add_pairing_requested(requested)
            attempts: list[tuple[str, object, object]] = [
                (
                    "PIN/Encryption",
                    DevicePairingKinds.PROVIDE_PIN | DevicePairingKinds.CONFIRM_ONLY,
                    DevicePairingProtectionLevel.ENCRYPTION,
                ),
                (
                    "PIN/Auth",
                    DevicePairingKinds.PROVIDE_PIN | DevicePairingKinds.CONFIRM_ONLY,
                    DevicePairingProtectionLevel.ENCRYPTION_AND_AUTHENTICATION,
                ),
                (
                    "PIN/None",
                    DevicePairingKinds.PROVIDE_PIN | DevicePairingKinds.CONFIRM_ONLY,
                    DevicePairingProtectionLevel.NONE,
                ),
            ]
            statuses: list[str] = []
            try:
                for attempt_name, ceremonies, protection in attempts:
                    request_kinds.clear()
                    try:
                        result = await custom.pair_with_protection_level_async(ceremonies, protection)
                        status_name = str(getattr(result.status, "name", result.status))
                        detail = f"{attempt_name}={status_name}"
                        if request_kinds:
                            detail += f" ({'/'.join(request_kinds)})"
                        statuses.append(detail)
                        self._trace_v2133(f"{label}: Windows-Kopplung · {detail}")
                        if result.status in (
                            DevicePairingResultStatus.PAIRED,
                            DevicePairingResultStatus.ALREADY_PAIRED,
                        ):
                            return f"mit PIN {DEFAULT_BT_PIN_V2133} gekoppelt · {attempt_name}"
                    except Exception as exc:
                        detail = f"{attempt_name}=EXC:{type(exc).__name__}:{exc}"
                        statuses.append(detail)
                        self._trace_v2133(f"{label}: Windows-Kopplung · {detail}")
                    await asyncio.sleep(0.35)
            finally:
                custom.remove_pairing_requested(token)

            raise RuntimeError("Windows-Kopplung fehlgeschlagen: " + " | ".join(statuses))
        finally:
            requester.close()
'''

    source = replace_method(source, "_windows_pair_fixed_pin_v2133", replacement)

    # v2.1.32 deliberately changed these transports to pair=True. That was
    # useful before an explicit pairing preflight existed, but is now exactly
    # the unwanted second pairing seen on Windows 11.
    source = disable_implicit_pairing(source, "_ble_download_async")
    source = disable_implicit_pairing(source, "_set_ble_queue_hold_async")

    required = (
        MARKER,
        "GATT direkt erreichbar · Windows-Kopplung wird übersprungen",
        "GATT direkt erreichbar; Windows-Kopplung nicht nötig",
        "def _ble_download_async",
        "def _set_ble_queue_hold_async",
    )
    missing = [item for item in required if item not in source]
    if missing:
        raise SystemExit("v2.2.3 BLE GATT-first validation failed: " + ", ".join(missing))

    # Both downstream transports must now be non-pairing.
    for name in ("_ble_download_async", "_set_ble_queue_hold_async"):
        start, end = method_span(source, name)
        method = source[start:end]
        if "pair=True," in method or "pair=False" not in method:
            raise SystemExit(f"v2.2.3 {name} still requests implicit pairing")
    return source


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: patch_jarnsen_service_tool_v223_ble_gatt.py <source.py>")
    path = Path(sys.argv[1])
    path.write_text(patch(path.read_text(encoding="utf-8")), encoding="utf-8")
    print("Applied Service Tool v2.2.3: GATT-first BLE without duplicate Windows pairing")


if __name__ == "__main__":
    main()
