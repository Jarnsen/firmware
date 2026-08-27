#include "vehicle/TrackerServiceUpgrade.h"
#include "configuration.h"

#if defined(HELTEC_TRACKER_V1_1)

#include "mesh/http/JarnsenServiceWeb.h"
#include "vehicle/TrackerCommonPolicy.h"
#include "vehicle/TrackerDiagnosticLog.h"

#if defined(ARCH_ESP32) && !defined(CONFIG_IDF_TARGET_ESP32S2) && !MESHTASTIC_EXCLUDE_BLUETOOTH
#include "nimble/NimbleBluetooth.h"
extern NimbleBluetooth *nimbleBluetooth;
#endif

#include <Arduino.h>
#include <Preferences.h>
#include <atomic>
#include <esp_system.h>

namespace
{
constexpr const char *PREF_NAMESPACE = "trkSvcHealth";
constexpr uint32_t WLAN_ACK_GRACE_MS = 450UL;

TrackerServiceHealthStats stats{};
esp_reset_reason_t bootResetReason = ESP_RST_UNKNOWN;
bool initialized = false;
bool lastBleConnected = false;
bool lastWebActive = false;
std::atomic<bool> wlanPending{false};
std::atomic<uint32_t> wlanRequestedMs{0};

bool resetLooksLikeCrash(esp_reset_reason_t reason)
{
    switch (reason) {
    case ESP_RST_PANIC:
    case ESP_RST_INT_WDT:
    case ESP_RST_TASK_WDT:
    case ESP_RST_WDT:
    case ESP_RST_BROWNOUT:
        return true;
    default:
        return false;
    }
}

void loadStats()
{
    Preferences prefs;
    if (!prefs.begin(PREF_NAMESPACE, true))
        return;
    stats.bootCount = prefs.getULong("boot", 0);
    stats.crashResetCount = prefs.getULong("crash", 0);
    stats.serviceOpenCount = prefs.getULong("service", 0);
    stats.bleConnectionCount = prefs.getULong("ble", 0);
    stats.wlanStartCount = prefs.getULong("wlan", 0);
    stats.wlanFailureCount = prefs.getULong("wlanFail", 0);
    prefs.end();
}

void saveStats()
{
    Preferences prefs;
    if (!prefs.begin(PREF_NAMESPACE, false))
        return;
    prefs.putULong("boot", stats.bootCount);
    prefs.putULong("crash", stats.crashResetCount);
    prefs.putULong("service", stats.serviceOpenCount);
    prefs.putULong("ble", stats.bleConnectionCount);
    prefs.putULong("wlan", stats.wlanStartCount);
    prefs.putULong("wlanFail", stats.wlanFailureCount);
    prefs.end();
}

bool bleConnected()
{
#if defined(ARCH_ESP32) && !defined(CONFIG_IDF_TARGET_ESP32S2) && !MESHTASTIC_EXCLUDE_BLUETOOTH
    return nimbleBluetooth && nimbleBluetooth->isConnected();
#else
    return false;
#endif
}

void restoreBleAfterFailedOrClosedWlan()
{
#if defined(ARCH_ESP32) && !defined(CONFIG_IDF_TARGET_ESP32S2) && !MESHTASTIC_EXCLUDE_BLUETOOTH
    if (!trackerCommonServiceActive())
        return;
    if (!nimbleBluetooth || !nimbleBluetooth->isActive()) {
        trackerDiagLog("WIFI_BLE", "restoring BLE after WLAN handover");
        setBluetoothEnable(true);
    }
#endif
}
} // namespace

void trackerServiceUpgradeInit()
{
    if (initialized)
        return;
    loadStats();
    bootResetReason = esp_reset_reason();
    stats.bootCount++;
    if (resetLooksLikeCrash(bootResetReason))
        stats.crashResetCount++;
    saveStats();
    initialized = true;
    lastBleConnected = bleConnected();
    lastWebActive = jarnsenServiceWebActive();
    trackerDiagLog("HEALTH_BOOT", "boots=%u crashes=%u reset=%s", (unsigned)stats.bootCount,
                   (unsigned)stats.crashResetCount, trackerServiceUpgradeResetReasonText());
}

void trackerServiceUpgradeNoteServiceOpen()
{
    if (!initialized)
        trackerServiceUpgradeInit();
    stats.serviceOpenCount++;
    saveStats();
    trackerDiagLog("SERVICE_OPEN", "count=%u", (unsigned)stats.serviceOpenCount);
}

bool trackerServiceUpgradeRequestWlan()
{
    if (!initialized)
        trackerServiceUpgradeInit();
    if (!trackerCommonServiceActive() || jarnsenServiceWebActive() || wlanPending.load())
        return false;

    wlanRequestedMs.store(millis() ? millis() : 1U);
    wlanPending.store(true);
    trackerDiagLog("WIFI_REQ", "safe BLE->WLAN handover queued");
    return true;
}

void trackerServiceUpgradeTick()
{
    if (!initialized)
        trackerServiceUpgradeInit();

    const bool connected = bleConnected();
    if (connected && !lastBleConnected) {
        stats.bleConnectionCount++;
        saveStats();
        trackerDiagLog("BLE_CONNECT", "persistent count=%u", (unsigned)stats.bleConnectionCount);
    }
    lastBleConnected = connected;

    const bool webActive = jarnsenServiceWebActive();
    if (lastWebActive && !webActive && !wlanPending.load())
        restoreBleAfterFailedOrClosedWlan();
    lastWebActive = webActive;

    if (!wlanPending.load())
        return;

    const uint32_t requested = wlanRequestedMs.load();
    const uint32_t now = millis();
    if (requested != 0 && (uint32_t)(now - requested) < WLAN_ACK_GRACE_MS)
        return;

    wlanPending.store(false);
    wlanRequestedMs.store(0);
    if (!trackerCommonServiceActive() || jarnsenServiceWebActive())
        return;

#if defined(ARCH_ESP32) && !defined(CONFIG_IDF_TARGET_ESP32S2) && !MESHTASTIC_EXCLUDE_BLUETOOTH
    if (nimbleBluetooth && nimbleBluetooth->isActive()) {
        trackerDiagLog("WIFI_BLE", "deinit BLE before SoftAP connected=%u", bleConnected() ? 1U : 0U);
        nimbleBluetooth->deinit();
        delay(120);
    }
#endif

    trackerDiagLog("WIFI_CALL", "starting service web after BLE handover");
    const bool started = jarnsenServiceWebStart();
    if (started) {
        stats.wlanStartCount++;
        saveStats();
        lastWebActive = true;
        trackerDiagLog("WIFI_OK", "count=%u ssid=%s", (unsigned)stats.wlanStartCount, jarnsenServiceWebSsid());
    } else {
        stats.wlanFailureCount++;
        saveStats();
        trackerDiagLog("WIFI_FAIL", "count=%u reason=%s", (unsigned)stats.wlanFailureCount, jarnsenServiceWebLastError());
        restoreBleAfterFailedOrClosedWlan();
    }
}

TrackerServiceHealthStats trackerServiceUpgradeHealth()
{
    return stats;
}

const char *trackerServiceUpgradeResetReasonText()
{
    switch (bootResetReason) {
    case ESP_RST_POWERON:
        return "POWER";
    case ESP_RST_SW:
        return "SOFT";
    case ESP_RST_PANIC:
        return "PANIC";
    case ESP_RST_INT_WDT:
        return "INT-WDT";
    case ESP_RST_TASK_WDT:
        return "TASK-WDT";
    case ESP_RST_WDT:
        return "WDT";
    case ESP_RST_DEEPSLEEP:
        return "DEEPSLEEP";
    case ESP_RST_BROWNOUT:
        return "BROWNOUT";
    default:
        return "OTHER";
    }
}

#endif
