#include "vehicle/TrackerServiceUpgrade.h"
#include "configuration.h"

#if defined(HELTEC_TRACKER_V1_1)

#include "mesh/http/JarnsenServiceWeb.h"
#include "vehicle/TrackerCommonPolicy.h"
#include "vehicle/TrackerDiagnosticLog.h"

#if HAS_SCREEN
#include "graphics/Screen.h"
#endif

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
constexpr uint32_t WLAN_BLE_DISCONNECT_TIMEOUT_MS = 4000UL;

TrackerServiceHealthStats stats{};
esp_reset_reason_t bootResetReason = ESP_RST_UNKNOWN;
bool initialized = false;
bool lastBleConnected = false;
bool lastWebActive = false;
bool wlanBleParkIssued = false;
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

void showWlanStartedBanner()
{
#if HAS_SCREEN
    if (!screen)
        return;
    if (!screen->isScreenOn())
        screen->setOn(true);
    char banner[144] = {};
    snprintf(banner, sizeof(banner), "WLAN AKTIV\n%s\nPW:%s\n%s", jarnsenServiceWebSsid(), jarnsenServiceWebPassword(),
             jarnsenServiceWebAddress());
    screen->showSimpleBanner(banner, 7000);
#endif
}

void showWlanFailureBanner(const char *reason)
{
#if HAS_SCREEN
    if (!screen)
        return;
    if (!screen->isScreenOn())
        screen->setOn(true);
    char banner[144] = {};
    snprintf(banner, sizeof(banner), "WLAN START FEHLER\n%.112s", reason && reason[0] ? reason : "Unbekannter Fehler");
    screen->showSimpleBanner(banner, 5000);
#else
    (void)reason;
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

void failWlanHandover(const char *reason)
{
    wlanPending.store(false);
    wlanRequestedMs.store(0);
    wlanBleParkIssued = false;
    stats.wlanFailureCount++;
    saveStats();
    trackerDiagLog("WIFI_FAIL", "count=%u reason=%s", (unsigned)stats.wlanFailureCount, reason ? reason : "unknown");
    showWlanFailureBanner(reason);
    restoreBleAfterFailedOrClosedWlan();
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

    wlanBleParkIssued = false;
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
    const uint32_t ageMs = requested ? (uint32_t)(now - requested) : 0U;
    if (ageMs < WLAN_ACK_GRACE_MS)
        return;

    if (!trackerCommonServiceActive() || jarnsenServiceWebActive()) {
        wlanPending.store(false);
        wlanRequestedMs.store(0);
        wlanBleParkIssued = false;
        return;
    }

    // WLANSTART can arrive from an actively connected Node Service Tool. Give
    // WLAN_ACK time to leave the GATT characteristic, then explicitly tear down
    // NimBLE. Wi-Fi is not touched until the physical BLE link is confirmed gone.
    if (!wlanBleParkIssued) {
#if defined(ARCH_ESP32) && !defined(CONFIG_IDF_TARGET_ESP32S2) && !MESHTASTIC_EXCLUDE_BLUETOOTH
        if (nimbleBluetooth && nimbleBluetooth->isActive()) {
            trackerDiagLog("WIFI_BLE", "deinit/disconnect requested before SoftAP connected=%u", bleConnected() ? 1U : 0U);
            nimbleBluetooth->deinit();
        }
#endif
        wlanBleParkIssued = true;
        return;
    }

    if (bleConnected()) {
        if (ageMs < WLAN_BLE_DISCONNECT_TIMEOUT_MS)
            return;
        failWlanHandover("BLE Verbindung konnte nicht getrennt werden");
        return;
    }

    wlanPending.store(false);
    wlanRequestedMs.store(0);
    wlanBleParkIssued = false;
    trackerDiagLog("WIFI_BLE", "BLE disconnected; starting service WLAN");
    trackerDiagLog("WIFI_CALL", "starting service web after verified BLE handover");
    const bool started = jarnsenServiceWebStart();
    if (started) {
        stats.wlanStartCount++;
        saveStats();
        lastWebActive = true;
        trackerDiagLog("WIFI_OK", "count=%u ssid=%s", (unsigned)stats.wlanStartCount, jarnsenServiceWebSsid());
        showWlanStartedBanner();
    } else {
        const char *reason = jarnsenServiceWebLastError();
        failWlanHandover(reason && reason[0] ? reason : "Access Point konnte nicht gestartet werden");
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
