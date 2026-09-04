"""v2.2.2: make Windows fixed-PIN BLE pairing resilient to generic WinRT FAILED results.

The v2.1.33 path only retried when Windows returned
PROTECTION_LEVEL_COULD_NOT_BE_MET. Real Windows 11 installations can return the
more generic FAILED result for the first minimum-protection attempt even though
the same Meshtastic device pairs successfully with a less strict protection
level. Retry deliberately, keep the fixed PIN automated, and finally prove
whether direct GATT access already works before declaring the node unavailable.
"""
from __future__ import annotations

import sys
from pathlib import Path

APP_VERSION = "2.2.2"
MARKER = "PATCH_V222_WINDOWS_BLE_PAIRING_FALLBACK"


def method_span(text: str, name: str) -> tuple[int, int]:
    normal = text.find(f"    def {name}(")
    asynchronous = text.find(f"    async def {name}(")
    starts = [value for value in (normal, asynchronous) if value >= 0]
    if not starts:
        raise SystemExit(f"v2.2.2 method {name} not found")
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


def patch(source: str) -> str:
    if MARKER in source:
        return source

    replacement = r'''    async def _windows_pair_fixed_pin_v2133(self, device: object, label: str = "") -> str:
        # PATCH_V222_WINDOWS_BLE_PAIRING_FALLBACK
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
                    "PIN/Auth",
                    DevicePairingKinds.PROVIDE_PIN | DevicePairingKinds.CONFIRM_ONLY,
                    DevicePairingProtectionLevel.ENCRYPTION_AND_AUTHENTICATION,
                ),
                (
                    "PIN/Encryption",
                    DevicePairingKinds.PROVIDE_PIN | DevicePairingKinds.CONFIRM_ONLY,
                    DevicePairingProtectionLevel.ENCRYPTION,
                ),
                (
                    "Alle/Encryption",
                    DevicePairingKinds.CONFIRM_ONLY
                    | DevicePairingKinds.PROVIDE_PIN
                    | DevicePairingKinds.DISPLAY_PIN
                    | DevicePairingKinds.CONFIRM_PIN_MATCH,
                    DevicePairingProtectionLevel.ENCRYPTION,
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

            # Some Windows BLE stacks can establish the encrypted GATT session even
            # though DeviceInformationCustomPairing reports generic FAILED. Prove
            # actual service access before rejecting the node.
            try:
                async with BleakClient(
                    device,
                    timeout=15.0,
                    pair=False,
                    winrt={"use_cached_services": False},
                ) as client:
                    if client.is_connected:
                        self._trace_v2133(f"{label}: GATT direkt erreichbar trotz WinRT-Pairingstatus")
                        return "GATT direkt erreichbar; Windows-Pairingstatus ignoriert"
            except Exception as exc:
                statuses.append(f"GATT={type(exc).__name__}:{exc}")
                self._trace_v2133(f"{label}: GATT-Direktprobe fehlgeschlagen · {exc}")

            raise RuntimeError("Windows-Kopplung fehlgeschlagen: " + " | ".join(statuses))
        finally:
            requester.close()
'''

    source = replace_method(source, "_windows_pair_fixed_pin_v2133", replacement)

    required = (
        MARKER,
        'DevicePairingProtectionLevel.NONE',
        'PIN/Auth',
        'PIN/Encryption',
        'Alle/Encryption',
        'GATT direkt erreichbar',
        'Windows PairingRequested',
    )
    missing = [item for item in required if item not in source]
    if missing:
        raise SystemExit("v2.2.2 BLE pairing validation failed: " + ", ".join(missing))
    return source


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: patch_jarnsen_service_tool_v222_ble_pairing.py <source.py>")
    path = Path(sys.argv[1])
    source = path.read_text(encoding="utf-8")
    path.write_text(patch(source), encoding="utf-8")
    print(f"Patched {path} to v{APP_VERSION}: resilient Windows fixed-PIN BLE pairing")


if __name__ == "__main__":
    main()
