#include "drone/DronePowerMonitor.h"

#if defined(HELTEC_TRACKER_V1_1) && defined(JARNSEN_DRONE_REPEATER_BUILD)

#include "NodeDB.h"
#include "PowerStatus.h"
#include "configuration.h"
#include "drone/DroneDiagnosticLog.h"

#include <Arduino.h>
#include <Preferences.h>

namespace
{
constexpr const char *PREF_NAMESPACE = "dronePower";
constexpr const char *USB_DROP_KEY = "usbDrop";
constexpr const char *USB_RESTORE_KEY = "usbRestore";
constexpr uint32_t USB_DISPLAY_TIMEOUT_SECS = 20U;
constexpr uint32_t BATTERY_DISPLAY_TIMEOUT_SECS = 10U;

bool initialized = false;
bool previousUsbKnown = false;
bool previousUsb = false;
uint32_t lastTickMs = 0;
uint64_t gpsMs = 0;
uint64_t bleMs = 0;
uint64_t displayMs = 0;
uint32_t positionTxCount = 0;
uint32_t loraRxCount = 0;
uint32_t loraTxCount = 0;
uint32_t relayTxCount = 0;
uint32_t usbDropCount = 0;
uint32_t usbRestoreCount = 0;

void persistTransitions()
{
    Preferences prefs;
    if (prefs.begin(PREF_NAMESPACE, false)) {
        prefs.putUInt(USB_DROP_KEY, usbDropCount);
        prefs.putUInt(USB_RESTORE_KEY, usbRestoreCount);
        prefs.end();
    }
}

bool currentUsb()
{
    return powerStatus && powerStatus->getHasUSB();
}

void applySideConsumerPriority(bool usb)
{
    // Mission functions (LoRa RX/relay + GNSS) are intentionally never reduced.
    // Only the display idle window becomes stricter on battery. BLE remains
    // button-only and Wi-Fi remains disabled by the drone policy in both modes.
    const uint32_t desiredDisplaySecs = usb ? USB_DISPLAY_TIMEOUT_SECS : BATTERY_DISPLAY_TIMEOUT_SECS;
    if (config.display.screen_on_secs != desiredDisplaySecs) {
        config.display.screen_on_secs = desiredDisplaySecs;
        droneDiagLog("POWER_POLICY", "%s display_timeout=%us lora=FULL gps=FULL ble=SERVICE wifi=OFF",
                     usb ? "USB" : "BATTERY", (unsigned)desiredDisplaySecs);
    }
}
}

void dronePowerMonitorInit()
{
    if (initialized)
        return;

    Preferences prefs;
    if (prefs.begin(PREF_NAMESPACE, true)) {
        usbDropCount = prefs.getUInt(USB_DROP_KEY, 0);
        usbRestoreCount = prefs.getUInt(USB_RESTORE_KEY, 0);
        prefs.end();
    }

    previousUsb = currentUsb();
    previousUsbKnown = true;
    lastTickMs = millis();
    initialized = true;
    applySideConsumerPriority(previousUsb);
}

void dronePowerMonitorTick(bool gpsActive, bool bleActive, bool displayActive)
{
    if (!initialized)
        dronePowerMonitorInit();

    const uint32_t now = millis();
    const uint32_t delta = lastTickMs == 0 ? 0 : now - lastTickMs;
    lastTickMs = now;

    // Ignore implausibly large gaps so a debugger/clock anomaly cannot corrupt
    // the runtime accounting.
    if (delta <= 10UL * 60UL * 1000UL) {
        if (gpsActive)
            gpsMs += delta;
        if (bleActive)
            bleMs += delta;
        if (displayActive)
            displayMs += delta;
    }

    const bool usb = currentUsb();
    if (!previousUsbKnown) {
        previousUsb = usb;
        previousUsbKnown = true;
        applySideConsumerPriority(usb);
    } else if (usb != previousUsb) {
        if (usb) {
            usbRestoreCount++;
            droneDiagLog("POWER_SOURCE", "USB_RESTORED battery=%u%%", powerStatus && powerStatus->getHasBattery()
                                                                      ? (unsigned)powerStatus->getBatteryChargePercent()
                                                                      : 0U);
        } else {
            usbDropCount++;
            droneDiagLog("POWER_SOURCE", "USB_LOST -> BATTERY battery=%u%%", powerStatus && powerStatus->getHasBattery()
                                                                           ? (unsigned)powerStatus->getBatteryChargePercent()
                                                                           : 0U);
        }
        previousUsb = usb;
        persistTransitions();
        applySideConsumerPriority(usb);
    }
}

void dronePowerMonitorNotePositionTx()
{
    if (!initialized)
        dronePowerMonitorInit();
    positionTxCount++;
}

void dronePowerMonitorNoteRadioRx()
{
    if (!initialized)
        dronePowerMonitorInit();
    loraRxCount++;
}

void dronePowerMonitorNoteRadioTx(bool relay)
{
    if (!initialized)
        dronePowerMonitorInit();
    loraTxCount++;
    if (relay)
        relayTxCount++;
}

DronePowerStats dronePowerMonitorStats()
{
    if (!initialized)
        dronePowerMonitorInit();

    DronePowerStats out{};
    out.uptimeSecs = millis() / 1000UL;
    out.usbDropCount = usbDropCount;
    out.usbRestoreCount = usbRestoreCount;
    out.gpsSecs = (uint32_t)(gpsMs / 1000ULL);
    out.bleSecs = (uint32_t)(bleMs / 1000ULL);
    out.displaySecs = (uint32_t)(displayMs / 1000ULL);
    out.positionTxCount = positionTxCount;
    out.loraRxCount = loraRxCount;
    out.loraTxCount = loraTxCount;
    out.relayTxCount = relayTxCount;

    if (powerStatus) {
        out.hasBattery = powerStatus->getHasBattery();
        out.usbPowered = powerStatus->getHasUSB();
        out.charging = powerStatus->getIsCharging();
        if (out.hasBattery) {
            const int voltage = powerStatus->getBatteryVoltageMv();
            if (voltage > 0 && voltage < 65536)
                out.voltageMv = (uint16_t)voltage;
            out.batteryPercent = powerStatus->getBatteryChargePercent();
        }
    }
    return out;
}

const char *dronePowerSourceText()
{
    const DronePowerStats stats = dronePowerMonitorStats();
    if (stats.usbPowered)
        return stats.hasBattery ? "USB+BAT" : "USB";
    if (stats.hasBattery)
        return "BATTERY";
    return "UNKNOWN";
}

#endif
