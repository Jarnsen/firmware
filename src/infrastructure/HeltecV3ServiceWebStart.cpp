#include "configuration.h"

#if defined(_VARIANT_HELTEC_V3) && HAS_WIFI

#include "infrastructure/HeltecV3DiagnosticLog.h"
#include "infrastructure/HeltecV3Runtime.h"
#include "main.h"
#include "mesh/http/JarnsenServiceWeb.h"

#if defined(ARCH_ESP32) && !defined(CONFIG_IDF_TARGET_ESP32S2) && !MESHTASTIC_EXCLUDE_BLUETOOTH
#include "nimble/NimbleBluetooth.h"
#endif

#include <Arduino.h>
#include <atomic>

namespace
{
std::atomic<bool> bleParkedForWifi{false};

bool bleConnected()
{
#if defined(ARCH_ESP32) && !defined(CONFIG_IDF_TARGET_ESP32S2) && !MESHTASTIC_EXCLUDE_BLUETOOTH
    return nimbleBluetooth && nimbleBluetooth->isConnected();
#else
    return false;
#endif
}

void parkBleAdvertisingForWifi()
{
#if defined(ARCH_ESP32) && !defined(CONFIG_IDF_TARGET_ESP32S2) && !MESHTASTIC_EXCLUDE_BLUETOOTH
    if (!nimbleBluetooth || !nimbleBluetooth->isActive() || nimbleBluetooth->isConnected())
        return;
    if (!nimbleBluetooth->isAdvertisingSuppressed())
        nimbleBluetooth->stopAdvertisingForService();
    bleParkedForWifi.store(true);
    heltecV3DiagLog("WIFI_BLE", "advertising parked before WLAN start");
#endif
}

void resumeBleAdvertisingAfterWifi(const char *reason)
{
    if (!bleParkedForWifi.exchange(false))
        return;
#if defined(ARCH_ESP32) && !defined(CONFIG_IDF_TARGET_ESP32S2) && !MESHTASTIC_EXCLUDE_BLUETOOTH
    if (heltecV3RuntimeServiceActive() && nimbleBluetooth && nimbleBluetooth->isActive() && !nimbleBluetooth->isConnected()) {
        nimbleBluetooth->startAdvertising();
        heltecV3DiagLog("WIFI_BLE", "advertising resumed reason=%s", reason ? reason : "wifi-stop");
    } else {
        heltecV3DiagLog("WIFI_BLE", "resume skipped reason=%s service=%u", reason ? reason : "wifi-stop",
                        heltecV3RuntimeServiceActive() ? 1U : 0U);
    }
#endif
}
} // namespace

bool jarnsenServiceWebRequestStart()
{
    if (jarnsenServiceWebActive())
        return true;

    if (bleConnected()) {
        heltecV3DiagLog("WIFI_FAIL", "BLE client connected; WLAN start rejected");
        return false;
    }

    // HeltecV3ServicePage already moved this call onto its dedicated worker.
    // Do not defer a second time: return only after AP + DNS + HTTP really started.
    heltecV3DiagLog("WIFI_REQ", "single worker start");
    parkBleAdvertisingForWifi();
    heltecV3DiagLog("WIFI_INIT", "worker-context=1 heap=%u", (unsigned)ESP.getFreeHeap());
    heltecV3DiagLog("AP_START", "begin");

    const bool started = jarnsenServiceWebStart();
    if (started) {
        heltecV3DiagLog("AP_OK", "ssid=%s ip=%s", jarnsenServiceWebSsid(), jarnsenServiceWebAddress());
        heltecV3DiagLog("WEB_OK", "http=80 heap=%u", (unsigned)ESP.getFreeHeap());
    } else {
        heltecV3DiagLog("WIFI_FAIL", "%s", jarnsenServiceWebLastError()[0] ? jarnsenServiceWebLastError() : "start failed");
        resumeBleAdvertisingAfterWifi("start-failed");
    }
    return started;
}

extern "C" void jarnsenServiceWebPlatformOnStopped()
{
    resumeBleAdvertisingAfterWifi("stopped");
}

extern "C" void jarnsenServiceWebPlatformOnFailed()
{
    resumeBleAdvertisingAfterWifi("failed");
}

#endif
