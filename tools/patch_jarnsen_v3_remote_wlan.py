"""Add a safe BLE -> WLAN service handover for the Heltec V3.

The Node Service Tool sends WLANSTART over the existing encrypted Jarnsen
control characteristic.  The GATT callback only queues an atomic request and
returns WLAN_ACK.  The V3 service task waits briefly for that acknowledgement
to leave the radio, parks BLE (including a clean client disconnect) and only
then starts the already-existing WLAN worker.  BLE advertising stays parked
while the service web AP is active and is restored by the existing V3 policy
after WLAN stops.
"""
from pathlib import Path

HEADER = Path("src/infrastructure/HeltecV3ServicePage.h")
PAGE = Path("src/infrastructure/HeltecV3ServicePage.cpp")
NIMBLE = Path("src/nimble/NimbleBluetooth.cpp")


def patch_header(source: str) -> str:
    marker = "bool heltecV3ServiceRequestWlanFromBle();"
    if marker not in source:
        anchor = "void heltecV3ServiceMenuClose();\n"
        if source.count(anchor) != 1:
            raise SystemExit("V3 service-page header anchor not found exactly once")
        source = source.replace(
            anchor,
            anchor
            + "\n// Queue a BLE -> WLAN handover. The caller may run in the NimBLE task;\n"
            + "// no Wi-Fi or BLE teardown is performed until heltecV3ServiceMenuPump().\n"
            + marker
            + "\n",
            1,
        )
    return source


def patch_page(source: str) -> str:
    if '#include "nimble/NimbleBluetooth.h"' not in source:
        anchor = '#include "mesh/http/JarnsenServiceWeb.h"\n'
        if source.count(anchor) != 1:
            raise SystemExit("V3 service-page JarnsenServiceWeb include anchor not found")
        source = source.replace(
            anchor,
            anchor
            + "\n#if defined(ARCH_ESP32) && !defined(CONFIG_IDF_TARGET_ESP32S2) && !MESHTASTIC_EXCLUDE_BLUETOOTH\n"
            + '#include "nimble/NimbleBluetooth.h"\n'
            + "extern NimbleBluetooth *nimbleBluetooth;\n"
            + "#endif\n",
            1,
        )
    elif "extern NimbleBluetooth *nimbleBluetooth;" not in source:
        anchor = '#include "nimble/NimbleBluetooth.h"\n'
        if source.count(anchor) != 1:
            raise SystemExit("V3 NimbleBluetooth include anchor not found exactly once")
        source = source.replace(anchor, anchor + "extern NimbleBluetooth *nimbleBluetooth;\n", 1)

    if "#include <atomic>" not in source:
        anchor = "#include <Arduino.h>\n"
        if source.count(anchor) != 1:
            raise SystemExit("V3 service-page Arduino include anchor not found")
        source = source.replace(anchor, anchor + "#include <atomic>\n", 1)

    state_marker = "std::atomic<bool> remoteWlanHandoverPending{false};"
    if state_marker not in source:
        anchor = "volatile V3WlanStartResult wlanStartResult = V3WlanStartResult::NONE;\n"
        if source.count(anchor) != 1:
            raise SystemExit("V3 WLAN worker state anchor not found")
        source = source.replace(
            anchor,
            anchor
            + "\n"
            + state_marker
            + "\n"
            + "std::atomic<uint32_t> remoteWlanHandoverRequestedMs{0};\n"
            + "bool remoteWlanBleParkIssued = false;\n",
            1,
        )

    if "void processRemoteWlanHandover()" not in source:
        anchor = "void handleWlanStartResult()\n{\n"
        if source.count(anchor) != 1:
            raise SystemExit("V3 WLAN result handler anchor not found")
        helper = r'''void processRemoteWlanHandover()
{
    if (!remoteWlanHandoverPending.load())
        return;

    const uint32_t requestedAt = remoteWlanHandoverRequestedMs.load();
    const uint32_t now = millis();
    const uint32_t ageMs = requestedAt ? (uint32_t)(now - requestedAt) : 0U;

    // Give the encrypted control characteristic enough time to return WLAN_ACK
    // before the service task disconnects the BLE client.
    if (ageMs < 450UL)
        return;

    if (jarnsenServiceWebActive()) {
        remoteWlanHandoverPending.store(false);
        remoteWlanBleParkIssued = false;
        return;
    }

    if (!remoteWlanBleParkIssued) {
#if defined(ARCH_ESP32) && !defined(CONFIG_IDF_TARGET_ESP32S2) && !MESHTASTIC_EXCLUDE_BLUETOOTH
        if (nimbleBluetooth && nimbleBluetooth->isActive())
            nimbleBluetooth->stopAdvertisingForService();
#endif
        remoteWlanBleParkIssued = true;
        heltecV3DiagLog("WIFI_REMOTE", "BLE park/disconnect requested before WLAN handover");
    }

    if (!bleConnectedForWlanStart()) {
        remoteWlanHandoverPending.store(false);
        remoteWlanBleParkIssued = false;
        heltecV3DiagLog("WIFI_REMOTE", "BLE disconnected; starting WLAN worker");
        requestWlanStart();
        return;
    }

    if (ageMs >= 4000UL) {
        remoteWlanHandoverPending.store(false);
        remoteWlanBleParkIssued = false;
        wlanStartResult = V3WlanStartResult::BLE_CONNECTED;
        heltecV3DiagLog("WIFI_FAIL", "remote WLAN handover timed out waiting for BLE disconnect");
    }
}

'''
        source = source.replace(anchor, helper + anchor, 1)

    request_marker = "bool heltecV3ServiceRequestWlanFromBle()"
    if request_marker not in source:
        anchor = "void heltecV3ServiceMenuPump()\n{\n"
        if source.count(anchor) != 1:
            raise SystemExit("V3 service-menu pump anchor not found")
        request = r'''bool heltecV3ServiceRequestWlanFromBle()
{
    if (!roleEnabled() || !heltecV3RuntimeServiceActive() || jarnsenServiceWebActive() || wlanStartPending || wlanStartRunning ||
        remoteWlanHandoverPending.load())
        return false;

    remoteWlanBleParkIssued = false;
    remoteWlanHandoverRequestedMs.store(millis() ? millis() : 1U);
    remoteWlanHandoverPending.store(true);
    return true;
}

'''
        source = source.replace(anchor, request + anchor, 1)

    pump_old = "void heltecV3ServiceMenuPump()\n{\n    handleWlanStartResult();\n"
    pump_new = "void heltecV3ServiceMenuPump()\n{\n    processRemoteWlanHandover();\n    handleWlanStartResult();\n"
    if pump_new not in source:
        if source.count(pump_old) != 1:
            raise SystemExit("V3 service-menu pump body anchor not found")
        source = source.replace(pump_old, pump_new, 1)

    stub = "bool heltecV3ServiceRequestWlanFromBle()\n{\n    return false;\n}\n"
    if source.count(request_marker) == 1:
        anchor = "void heltecV3ServiceMenuOpen() {}\n"
        if source.count(anchor) != 1:
            raise SystemExit("V3 service-page disabled stub anchor not found")
        source = source.replace(anchor, stub + anchor, 1)

    return source


def patch_nimble(source: str) -> str:
    marker = 'memcmp(data, "WLANSTART", 9)'
    if marker not in source:
        anchor = '''        } else if (length == 7 && memcmp(data, "RELEASE", 7) == 0) {
            jarnsenOtaQueueHold = false;
            setJarnsenBleQueueHold(false);
            characteristic->setValue((const uint8_t *)"IDLE", 4);
'''
        if source.count(anchor) != 1:
            raise SystemExit("Jarnsen RELEASE control anchor not found")
        replacement = anchor + '''#if defined(_VARIANT_HELTEC_V3)
        } else if (length == 9 && memcmp(data, "WLANSTART", 9) == 0) {
            const bool queued = heltecV3ServiceRequestWlanFromBle();
            const char *status = queued ? "WLAN_ACK" : "LOCKED";
            characteristic->setValue((const uint8_t *)status, strlen(status));
#endif
'''
        source = source.replace(anchor, replacement, 1)
    return source


header = patch_header(HEADER.read_text(encoding="utf-8"))
page = patch_page(PAGE.read_text(encoding="utf-8"))
nimble = patch_nimble(NIMBLE.read_text(encoding="utf-8"))

required_header = ("heltecV3ServiceRequestWlanFromBle", "BLE -> WLAN handover")
required_page = (
    "extern NimbleBluetooth *nimbleBluetooth;",
    "remoteWlanHandoverPending",
    "processRemoteWlanHandover",
    "stopAdvertisingForService",
    "ageMs < 450UL",
    "ageMs >= 4000UL",
    "BLE disconnected; starting WLAN worker",
)
required_nimble = ('memcmp(data, "WLANSTART", 9)', '"WLAN_ACK"', '"LOCKED"')
for marker in required_header:
    if marker not in header:
        raise SystemExit(f"missing V3 remote-WLAN header marker: {marker}")
for marker in required_page:
    if marker not in page:
        raise SystemExit(f"missing V3 remote-WLAN page marker: {marker}")
for marker in required_nimble:
    if marker not in nimble:
        raise SystemExit(f"missing V3 remote-WLAN NimBLE marker: {marker}")

HEADER.write_text(header, encoding="utf-8")
PAGE.write_text(page, encoding="utf-8")
NIMBLE.write_text(nimble, encoding="utf-8")
print("Heltec V3: encrypted WLANSTART queues safe BLE -> WLAN service handover")
