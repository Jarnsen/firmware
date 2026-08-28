#include "drone/DroneSystemHealth.h"

#if defined(HELTEC_TRACKER_V1_1) && defined(JARNSEN_DRONE_REPEATER_BUILD)

#include "drone/DroneDiagnosticLog.h"

#include <Arduino.h>
#include <Preferences.h>
#include <esp_system.h>

namespace
{
constexpr const char *PREF_NAMESPACE = "droneHealth";
constexpr const char *BOOT_KEY = "boots";
constexpr const char *CRASH_KEY = "crashes";

bool initialized = false;
DroneSystemHealthStats stats{};
esp_reset_reason_t resetReason = ESP_RST_UNKNOWN;

bool isCrashReset(esp_reset_reason_t reason)
{
    return reason == ESP_RST_PANIC || reason == ESP_RST_INT_WDT || reason == ESP_RST_TASK_WDT || reason == ESP_RST_WDT;
}

void persistBootCounters()
{
    Preferences prefs;
    if (prefs.begin(PREF_NAMESPACE, false)) {
        prefs.putUInt(BOOT_KEY, stats.bootCount);
        prefs.putUInt(CRASH_KEY, stats.crashResetCount);
        prefs.end();
    }
}
}

void droneSystemHealthInit()
{
    if (initialized)
        return;

    Preferences prefs;
    if (prefs.begin(PREF_NAMESPACE, true)) {
        stats.bootCount = prefs.getUInt(BOOT_KEY, 0);
        stats.crashResetCount = prefs.getUInt(CRASH_KEY, 0);
        prefs.end();
    }

    resetReason = esp_reset_reason();
    stats.lastResetWasCrash = isCrashReset(resetReason);
    stats.bootCount++;
    if (stats.lastResetWasCrash)
        stats.crashResetCount++;
    stats.minFreeHeap = ESP.getFreeHeap();
    persistBootCounters();
    initialized = true;
}

void droneSystemHealthTick()
{
    if (!initialized)
        droneSystemHealthInit();
    const uint32_t freeHeap = ESP.getFreeHeap();
    if (stats.minFreeHeap == 0 || freeHeap < stats.minFreeHeap)
        stats.minFreeHeap = freeHeap;
}

void droneSystemHealthNoteGpsRecovery()
{
    if (!initialized)
        droneSystemHealthInit();
    stats.gpsRecoveryCount++;
    droneDiagLog("RECOVERY", "GPS count=%u", (unsigned)stats.gpsRecoveryCount);
}

void droneSystemHealthNoteBleRecovery()
{
    if (!initialized)
        droneSystemHealthInit();
    stats.bleRecoveryCount++;
    droneDiagLog("RECOVERY", "BLE count=%u", (unsigned)stats.bleRecoveryCount);
}

void droneSystemHealthNoteLoraRecovery()
{
    if (!initialized)
        droneSystemHealthInit();
    stats.loraRecoveryCount++;
    droneDiagLog("RECOVERY", "LORA count=%u", (unsigned)stats.loraRecoveryCount);
}

DroneSystemHealthStats droneSystemHealthStats()
{
    if (!initialized)
        droneSystemHealthInit();
    return stats;
}

const char *droneSystemHealthStatusText()
{
    if (!initialized)
        droneSystemHealthInit();
    if (stats.lastResetWasCrash || (stats.minFreeHeap != 0 && stats.minFreeHeap < 20000U))
        return "DEGRADED";
    return "OK";
}

const char *droneSystemHealthResetReasonText()
{
    if (!initialized)
        droneSystemHealthInit();
    switch (resetReason) {
    case ESP_RST_POWERON:
        return "POWERON";
    case ESP_RST_EXT:
        return "EXTERNAL";
    case ESP_RST_SW:
        return "SOFTWARE";
    case ESP_RST_PANIC:
        return "PANIC";
    case ESP_RST_INT_WDT:
        return "INT_WDT";
    case ESP_RST_TASK_WDT:
        return "TASK_WDT";
    case ESP_RST_WDT:
        return "WDT";
    case ESP_RST_DEEPSLEEP:
        return "DEEPSLEEP";
    case ESP_RST_BROWNOUT:
        return "BROWNOUT";
    case ESP_RST_SDIO:
        return "SDIO";
    default:
        return "UNKNOWN";
    }
}

#endif
