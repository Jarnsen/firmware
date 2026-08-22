from pathlib import Path

POLICY = Path("src/infrastructure/HeltecV3RepeaterPolicy.cpp")
SCREEN = Path("src/graphics/Screen.cpp")
RADIO = Path("src/mesh/RadioLibInterface.cpp")
DIAG = Path("src/infrastructure/HeltecV3DiagnosticLog.cpp")

policy = POLICY.read_text()
screen = SCREEN.read_text()
radio = RADIO.read_text()
diag = DIAG.read_text()


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if new in text:
        print(f"{label}: already applied")
        return text
    if old not in text:
        raise SystemExit(f"{label}: anchor not found")
    print(f"{label}: applied")
    return text.replace(old, new, 1)


# ---------------------------------------------------------------------------
# Runtime policy wiring: diagnostics, service/mesh pages and USB maintenance.
# ---------------------------------------------------------------------------
policy = replace_once(
    policy,
    '#include "infrastructure/HeltecV3PositionPage.h"\n#include "main.h"\n',
    '#include "infrastructure/HeltecV3PositionPage.h"\n'
    '#include "infrastructure/HeltecV3DiagnosticLog.h"\n'
    '#include "infrastructure/HeltecV3MeshMonitor.h"\n'
    '#include "infrastructure/HeltecV3MeshPages.h"\n'
    '#include "infrastructure/HeltecV3Runtime.h"\n'
    '#include "infrastructure/HeltecV3ServicePage.h"\n'
    '#include "main.h"\n',
    "include V3 observability interfaces",
)

policy = replace_once(
    policy,
    'static uint32_t v3LastBleAdvertisingCheckMs = 0;\n',
    'static uint32_t v3LastBleAdvertisingCheckMs = 0;\n'
    'static bool v3UsbMaintenanceActive = false;\n',
    "add V3 USB maintenance state",
)

runtime_impl = r'''static bool v3NativeSerialConnected()
{
#if defined(ARDUINO_USB_CDC_ON_BOOT) && ARDUINO_USB_CDC_ON_BOOT
    return (bool)Serial;
#else
    return false;
#endif
}

static void v3UpdateUsbMaintenance()
{
    const bool connected = v3NativeSerialConnected();
    if (connected == v3UsbMaintenanceActive)
        return;
    v3UsbMaintenanceActive = connected;
    heltecV3DiagLog("USB_MAINT", "active=%u", connected ? 1U : 0U);
    LOG_INFO("Heltec V3 USB maintenance: %s", connected ? "active; light sleep vetoed" : "closed; normal light sleep restored");
}

bool heltecV3RuntimeRoleEnabled()
{
    return v3RepeaterRoleEnabled();
}

bool heltecV3RuntimeServiceActive()
{
    return v3RepeaterRoleEnabled() && v3ServiceActive;
}

bool heltecV3RuntimeUsbMaintenanceActive()
{
    return v3RepeaterRoleEnabled() && v3UsbMaintenanceActive;
}

const char *heltecV3RuntimeStateText()
{
    if (!v3RepeaterRoleEnabled())
        return "OFF";
    if (v3ServiceActive)
        return "SERVICE";
    if (v3UsbMaintenanceActive)
        return "MAINT";
    return "LISTEN";
}

const char *heltecV3RuntimeBleStateText()
{
    if (!v3RepeaterRoleEnabled())
        return "OFF";
    if (v3BleConnected())
        return "CONNECTED";
    if (v3BleAdvertisingActive())
        return "ADV";
    return "OFF";
}

uint32_t heltecV3RuntimeServiceRemainingSecs()
{
    if (!v3ServiceActive)
        return 0;
    const uint32_t now = millis();
    const uint32_t elapsed = (uint32_t)(now - v3ServiceLastActivityMs);
    return elapsed >= V3_SERVICE_IDLE_MS ? 0U : (V3_SERVICE_IDLE_MS - elapsed + 999U) / 1000U;
}

'''
policy = replace_once(
    policy,
    'static void v3BluetoothOnNow()\n',
    runtime_impl + 'static void v3BluetoothOnNow()\n',
    "implement V3 runtime health and USB maintenance helpers",
)

# Log the position action without changing any save/broadcast semantics.
policy = replace_once(
    policy,
    '''    // Native MeshModule page redraws from policy state; never switch to
    // an exclusive alert just because a position was saved.
    heltecV3PositionPageRefresh();
    return true;
''',
    '''    heltecV3DiagNotePositionSave(automatic, differenceM);
    // Native MeshModule page redraws from policy state; never switch to
    // an exclusive alert just because a position was saved.
    heltecV3PositionPageRefresh();
    return true;
''',
    "log V3 manual/automatic position saves",
)

policy = replace_once(
    policy,
    '''        v3BluetoothOnNow();
        v3LastBleAdvertisingCheckMs = now;
        v3BleTrafficLast = v3BleMeaningfulTrafficCount();
        LOG_INFO("Heltec V3 service: GPIO0 opened display/Bluetooth;''',
    '''        v3BluetoothOnNow();
        v3LastBleAdvertisingCheckMs = now;
        v3BleTrafficLast = v3BleMeaningfulTrafficCount();
        heltecV3DiagNoteServiceOpen();
        LOG_INFO("Heltec V3 service: GPIO0 opened display/Bluetooth;''',
    "count/log V3 service opens",
)

policy = replace_once(
    policy,
    '''        if (bleConnected && !v3ServiceEverConnected) {
            v3ServiceEverConnected = true;
            LOG_INFO("Heltec V3 service: BLE connected; activity burst detector armed''',
    '''        if (bleConnected && !v3ServiceEverConnected) {
            v3ServiceEverConnected = true;
            heltecV3DiagNoteBleConnection();
            LOG_INFO("Heltec V3 service: BLE connected; activity burst detector armed''',
    "count/log first BLE connection in service window",
)

policy = replace_once(
    policy,
    '''            if (!v3BleAdvertisingActive()) {
                LOG_WARN("Heltec V3 service: GAP advertising inactive; restarting without BLE reinit");
''',
    '''            if (!v3BleAdvertisingActive()) {
                LOG_WARN("Heltec V3 service: GAP advertising inactive; restarting without BLE reinit");
                heltecV3DiagNoteBleRecovery();
''',
    "count/log V3 BLE GAP recovery",
)

policy = replace_once(
    policy,
    '''    v3ServiceActive = false;
    LOG_INFO("Heltec V3 service: window complete; Bluetooth/display off, repeater power policy restored");
''',
    '''    v3ServiceActive = false;
    heltecV3DiagLog("SERVICE_CLOSE", "BLE/display parked; repeater policy restored");
    LOG_INFO("Heltec V3 service: window complete; Bluetooth/display off, repeater power policy restored");
''',
    "log V3 service close",
)

# Long press remains context-sensitive: position=save, service=USB log export,
# antenna page=test state machine. Mesh Health itself stays read-only.
policy = replace_once(
    policy,
    '''            if (heltecV3PositionPageRecentlyVisible()) {
                heltecV3ManualSaveLatestPosition();
                heltecV3PositionPageRefresh();
            }
            v3LongPressHandled = true;
            // 20 s of display inactivity are counted from the last accepted
''',
    '''            if (heltecV3PositionPageRecentlyVisible()) {
                heltecV3ManualSaveLatestPosition();
                heltecV3PositionPageRefresh();
            } else if (heltecV3ServicePageRecentlyVisible()) {
                heltecV3DiagRequestUsbExport();
                heltecV3ServicePageRefresh();
            } else if (heltecV3AntennaPageRecentlyVisible()) {
                heltecV3AntennaHandleLongPress();
                heltecV3MeshPagesRefresh();
            }
            v3LongPressHandled = true;
            // 20 s of display inactivity are counted from the last accepted
''',
    "route V3 long press by native page context",
)

# USB maintenance is a true serial-session veto, not a USB-power veto. Keep LoRa
# and normal role behavior intact; only prevent Light Sleep while CDC is open.
policy = replace_once(
    policy,
    '''        if (v3ServiceActive)
            return 1;
        v3ForceIdlePeripheralsOff();
''',
    '''        if (v3ServiceActive || v3NativeSerialConnected())
            return 1;
        v3ForceIdlePeripheralsOff();
''',
    "veto V3 light sleep only for service or open native serial",
)

# Pump low-cost monitors before the service-active early return. There is no
# per-packet flash logging; MeshMonitor emits only hourly summaries/warnings.
policy = replace_once(
    policy,
    '''        const uint32_t now = millis();

#ifdef BUTTON_PIN
''',
    '''        const uint32_t now = millis();
        v3UpdateUsbMaintenance();
        heltecV3DiagPumpUsbExport();
        heltecV3MeshMonitorTick();

#ifdef BUTTON_PIN
''',
    "pump V3 USB export and mesh health outside service windows",
)

# Initialize diagnostics before the service task begins. The existing BLE boot
# pre-initialization/parking remains unchanged.
policy = replace_once(
    policy,
    '''    if (screen)
        screen->setOn(false);
    setupV3ServiceButton();

    LOG_INFO("Heltec V3 %s duty:''',
    '''    if (screen)
        screen->setOn(false);
    heltecV3DiagInit();
    heltecV3MeshMonitorTick();
    setupV3ServiceButton();

    LOG_INFO("Heltec V3 %s duty:''',
    "initialize V3 diagnostics and mesh monitor",
)


# ---------------------------------------------------------------------------
# Native page order: Position -> Service -> Mesh Health -> Antenna Test -> stock
# Meshtastic pages. All pages are observers only; none changes routing.
# ---------------------------------------------------------------------------
screen = replace_once(
    screen,
    '''#if defined(_VARIANT_HELTEC_V3)
bool heltecV3PositionPageEnabled();
void heltecV3PositionPageDrawFrame(OLEDDisplay *display, OLEDDisplayUiState *state, int16_t x, int16_t y);
#endif
''',
    '''#if defined(_VARIANT_HELTEC_V3)
bool heltecV3PositionPageEnabled();
void heltecV3PositionPageDrawFrame(OLEDDisplay *display, OLEDDisplayUiState *state, int16_t x, int16_t y);
bool heltecV3ServicePageEnabled();
void heltecV3ServicePageDrawFrame(OLEDDisplay *display, OLEDDisplayUiState *state, int16_t x, int16_t y);
bool heltecV3MeshHealthPageEnabled();
void heltecV3MeshHealthPageDrawFrame(OLEDDisplay *display, OLEDDisplayUiState *state, int16_t x, int16_t y);
bool heltecV3AntennaPageEnabled();
void heltecV3AntennaPageDrawFrame(OLEDDisplay *display, OLEDDisplayUiState *state, int16_t x, int16_t y);
#endif
''',
    "declare V3 health pages in Screen",
)

screen = replace_once(
    screen,
    '''#if defined(_VARIANT_HELTEC_V3)
    // The repeater's MGRS/service position page is deliberately the first
    // normal page. Critical faults still take precedence when present.
    if (heltecV3PositionPageEnabled()) {
        fsi.positions.deviceFocused = numframes;
        normalFrames[numframes++] = heltecV3PositionPageDrawFrame;
        indicatorIcons.push_back(icon_module);
    }
#endif
''',
    '''#if defined(_VARIANT_HELTEC_V3)
    // V3 local observability pages come first, then the stock Meshtastic
    // carousel. Critical-fault frames still precede all of them.
    if (heltecV3PositionPageEnabled()) {
        fsi.positions.deviceFocused = numframes;
        normalFrames[numframes++] = heltecV3PositionPageDrawFrame;
        indicatorIcons.push_back(icon_module);
    }
    if (heltecV3ServicePageEnabled()) {
        normalFrames[numframes++] = heltecV3ServicePageDrawFrame;
        indicatorIcons.push_back(icon_module);
    }
    if (heltecV3MeshHealthPageEnabled()) {
        normalFrames[numframes++] = heltecV3MeshHealthPageDrawFrame;
        indicatorIcons.push_back(icon_module);
    }
    if (heltecV3AntennaPageEnabled()) {
        normalFrames[numframes++] = heltecV3AntennaPageDrawFrame;
        indicatorIcons.push_back(icon_module);
    }
#endif
''',
    "insert V3 Service Mesh Health and Antenna pages after Position",
)


# ---------------------------------------------------------------------------
# Physical LoRa RX tap. RSSI/SNR metadata is measured here before Router mutates
# hops. The monitor is passive and cannot change/drop/rebroadcast packets.
# ---------------------------------------------------------------------------
radio = replace_once(
    radio,
    '#include "mesh-pb-constants.h"\n',
    '#include "mesh-pb-constants.h"\n#ifdef _VARIANT_HELTEC_V3\n#include "infrastructure/HeltecV3MeshMonitor.h"\n#endif\n',
    "include V3 mesh monitor at radio RX boundary",
)

radio = replace_once(
    radio,
    '''            addReceiveMetadata(mp);

            mp->which_payload_variant =
''',
    '''            addReceiveMetadata(mp);
#ifdef _VARIANT_HELTEC_V3
            heltecV3MeshMonitorOnRadioPacket(*mp);
#endif

            mp->which_payload_variant =
''',
    "observe V3 physical LoRa packets after RSSI/SNR metadata",
)


# ---------------------------------------------------------------------------
# USB export appends a live Mesh/Antenna snapshot after the persistent log.
# ---------------------------------------------------------------------------
diag = replace_once(
    diag,
    '#include "infrastructure/HeltecV3DiagnosticLog.h"\n',
    '#include "infrastructure/HeltecV3DiagnosticLog.h"\n#include "infrastructure/HeltecV3MeshMonitor.h"\n',
    "include mesh snapshot in V3 diagnostic export",
)

diag = replace_once(
    diag,
    '''    case 4:
        Serial.print("\\r\\n===V3_LOG_END===\\r\\n");
''',
    '''    case 4:
        heltecV3MeshMonitorPrintSnapshot(Serial);
        Serial.print("\\r\\n===V3_LOG_END===\\r\\n");
''',
    "append V3 mesh/antenna snapshot to USB log export",
)

for text, needle in [
    (policy, 'heltecV3DiagInit();'),
    (policy, 'heltecV3DiagNoteBleRecovery();'),
    (policy, 'v3NativeSerialConnected()'),
    (policy, 'heltecV3AntennaHandleLongPress();'),
    (screen, 'heltecV3MeshHealthPageDrawFrame'),
    (screen, 'heltecV3AntennaPageDrawFrame'),
    (radio, 'heltecV3MeshMonitorOnRadioPacket(*mp);'),
    (diag, 'heltecV3MeshMonitorPrintSnapshot(Serial);'),
]:
    if needle not in text:
        raise SystemExit(f"V3 observability integration verification failed: {needle}")

POLICY.write_text(policy)
SCREEN.write_text(screen)
RADIO.write_text(radio)
DIAG.write_text(diag)
print("V3 observability ready: persistent diag + Service + USB maintenance + Mesh Health + safe RX antenna A/B test")
