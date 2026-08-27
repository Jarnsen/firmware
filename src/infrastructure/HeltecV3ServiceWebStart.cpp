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
#include <esp_heap_caps.h>

namespace
{
std::atomic<bool> bleReleasedForWifi{false};
std::atomic<bool> wifiTransitionActive{false};

bool bleConnected()
{
#if defined(ARCH_ESP32) && !defined(CONFIG_IDF_TARGET_ESP32S2) && !MESHTASTIC_EXCLUDE_BLUETOOTH
    return nimbleBluetooth && nimbleBluetooth->isConnected();
#else
    return false;
#endif
}

uint32_t largest8BitBlock()
{
#if defined(ARCH_ESP32)
    return (uint32_t)heap_caps_get_largest_free_block(MALLOC_CAP_8BIT);
#else
    return 0U;
#endif
}

bool releaseBleStackForWifi()
{
#if defined(ARCH_ESP32) && !defined(CONFIG_IDF_TARGET_ESP32S2) && !MESHTASTIC_EXCLUDE_BLUETOOTH
    if (!nimbleBluetooth || !nimbleBluetooth->isActive()) {
        heltecV3DiagLog("WIFI_BLE", "stack already inactive heap=%u largest=%u", (unsigned)ESP.getFreeHeap(),
                        (unsigned)largest8BitBlock());
        return true;
    }
    if (nimbleBluetooth->isConnected())
        return false;

    const uint32_t heapBefore = ESP.getFreeHeap();
    const uint32_t largestBefore = largest8BitBlock();
    heltecV3DiagLog("WIFI_BLE", "deinit begin heap=%u largest=%u", (unsigned)heapBefore, (unsigned)largestBefore);

    // WLAN and NimBLE together leave too little contiguous RAM on the V3. Fully
    // release NimBLE for the WLAN maintenance window. We deliberately reboot
    // after WLAN closes instead of reinitializing both radio stacks in one boot.
    nimbleBluetooth->deinit();
    delay(120);

    const bool released = !nimbleBluetooth->isActive();
    heltecV3DiagLog("WIFI_BLE", "deinit %s heap=%u largest=%u gain=%ld", released ? "ok" : "failed",
                    (unsigned)ESP.getFreeHeap(), (unsigned)largest8BitBlock(), (long)ESP.getFreeHeap() - (long)heapBefore);
    if (released)
        bleReleasedForWifi.store(true);
    return released;
#else
    return true;
#endif
}

void scheduleRadioRestoreReboot(const char *reason)
{
    if (!bleReleasedForWifi.exchange(false)) {
        wifiTransitionActive.store(false);
        return;
    }
    wifiTransitionActive.store(true);
    heltecV3DiagLog("WIFI_REBOOT", "reason=%s delay=2s", reason ? reason : "wifi-stop");
    rebootAtMsec = millis() + 2000UL;
}
} // namespace

bool heltecV3RuntimeWifiTransitionActive()
{
    return wifiTransitionActive.load();
}

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
    wifiTransitionActive.store(true);
    heltecV3DiagLog("WIFI_REQ", "single worker start");
    if (!releaseBleStackForWifi()) {
        wifiTransitionActive.store(false);
        heltecV3DiagLog("WIFI_FAIL", "NimBLE could not be released for WLAN");
        return false;
    }

    heltecV3DiagLog("WIFI_INIT", "worker-context=1 heap=%u largest=%u", (unsigned)ESP.getFreeHeap(),
                    (unsigned)largest8BitBlock());
    heltecV3DiagLog("AP_START", "begin");

    const bool started = jarnsenServiceWebStart();
    if (started) {
        wifiTransitionActive.store(false);
        heltecV3DiagLog("AP_OK", "ssid=%s ip=%s", jarnsenServiceWebSsid(), jarnsenServiceWebAddress());
        heltecV3DiagLog("WEB_OK", "http=80 heap=%u largest=%u", (unsigned)ESP.getFreeHeap(), (unsigned)largest8BitBlock());
    } else {
        heltecV3DiagLog("WIFI_FAIL", "%s", jarnsenServiceWebLastError()[0] ? jarnsenServiceWebLastError() : "start failed");
        scheduleRadioRestoreReboot("start-failed");
    }
    return started;
}

extern "C" void jarnsenServiceWebPlatformOnStopped()
{
    scheduleRadioRestoreReboot("stopped");
}

extern "C" void jarnsenServiceWebPlatformOnFailed()
{
    scheduleRadioRestoreReboot("failed");
}

#endif
