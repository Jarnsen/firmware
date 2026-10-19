#include "jarnsen/core/service/JarnsenDiagnosticPolicy.h"

#include "BluetoothStatus.h"
#include "FSCommon.h"
#include "GPSStatus.h"
#include "PowerStatus.h"
#include "RadioLibInterface.h"
#include "configuration.h"
#include "gps/RTC.h"
#include "jarnsen/core/build/JarnsenBuildInfo.h"
#include "jarnsen/core/mesh/JarnsenNodeStateCache.h"
#include "jarnsen/core/service/JarnsenCrashTrace.h"
#include "jarnsen/core/service/JarnsenDiagnosticLog.h"
#include "jarnsen/core/status/JarnsenStatusProvider.h"
#include "memGet.h"
#include "mesh/http/JarnsenServiceWeb.h"
#if defined(HELTEC_TRACKER_V1_1)
#include "vehicle/TrackerPowerMonitor.h"
#endif

#include <Arduino.h>
#include <algorithm>
#include <atomic>
#include <cstdarg>
#include <cstdio>

#ifdef ARCH_ESP32
#include <esp_sleep.h>
#include <esp_system.h>
#endif

namespace jarnsen
{
namespace
{
std::atomic_flag writeBusy = ATOMIC_FLAG_INIT;
std::atomic_flag queueBusy = ATOMIC_FLAG_INIT;
std::atomic<bool> ready{false}, detailOn{false};
std::atomic<uint32_t> detailSince{0}, written{0}, suppressed{0}, dropped{0}, ioErrors{0}, truncated{0};
std::atomic<uint32_t> filtered{0};
std::atomic<uint32_t> rotations{0}, discarded{0}, cacheAdds{0}, cacheUpdates{0}, cacheRejects{0}, cacheExpires{0},
    cacheReplaces{0};
std::atomic<uint32_t> sleeps{0}, wakes{0};
std::atomic<uint32_t> timerWakes{0}, gpioWakes{0}, otherWakes{0}, rejectedStarts{0};
std::atomic<uint32_t> packetKinds[static_cast<size_t>(DiagnosticPacketKind::COUNT)]{};
std::atomic<uint32_t> packetSkipped{0}, cacheSkipped{0};
uint32_t bootId = 0, healthAt = 0, summaryAt = 0;
uint32_t lastConfig = UINT32_MAX;
bool contextSent = false, bootReported = false;
DiagnosticRepeatGate repeatGate;

struct PendingEvent {
    uint32_t capturedMs = 0;
    char event[24]{};
    char detail[200]{};
};
PendingEvent pending[8]{};
size_t queueHead = 0, queueCount = 0;

struct DeepIntent {
    uint32_t magic = 0;
    uint32_t boot = 0;
    uint32_t epoch = 0;
    uint32_t plannedMs = 0;
};
#ifdef ARCH_ESP32
RTC_DATA_ATTR DeepIntent deepIntent;
#else
DeepIntent deepIntent;
#endif
constexpr uint32_t DEEP_INTENT_MAGIC = 0x4a444750U;

bool inInterrupt()
{
#if defined(ARCH_ESP32) || defined(ARCH_NRF52)
    return xPortInIsrContext() == pdTRUE;
#else
    return false;
#endif
}

const char *wakeName(int cause)
{
#ifdef ARCH_ESP32
    switch (static_cast<esp_sleep_wakeup_cause_t>(cause)) {
    case ESP_SLEEP_WAKEUP_TIMER:
        return "timer";
    case ESP_SLEEP_WAKEUP_EXT0:
        return "ext0";
    case ESP_SLEEP_WAKEUP_EXT1:
        return "ext1";
    case ESP_SLEEP_WAKEUP_GPIO:
        return "gpio_unresolved";
    case ESP_SLEEP_WAKEUP_TOUCHPAD:
        return "touch";
    case ESP_SLEEP_WAKEUP_UNDEFINED:
        return "cold_or_reset";
    default:
        return "other";
    }
#else
    (void)cause;
    return "platform_unknown";
#endif
}

void drainQueue()
{
    for (unsigned i = 0; i < 2U; ++i) {
        PendingEvent entry;
        if (queueBusy.test_and_set())
            return;
        if (!queueCount) {
            queueBusy.clear();
            return;
        }
        entry = pending[queueHead];
        queueHead = (queueHead + 1U) % 8U;
        --queueCount;
        queueBusy.clear();
        diagnosticLog(entry.event, "at_ms=%u %s", (unsigned)entry.capturedMs, entry.detail);
    }
}

void fileBoundary(char *out, size_t capacity, const char *path, size_t bytes, bool last)
{
    snprintf(out, capacity, "empty");
#ifdef FSCom
    if (!bytes)
        return;
    File file = FSCom.open(path, FILE_O_READ);
    if (!file) {
        snprintf(out, capacity, "unavailable");
        return;
    }
    char tail[512]{};
    const size_t offset = last && bytes > sizeof(tail) - 1U ? bytes - (sizeof(tail) - 1U) : 0U;
    if (offset && !file.seek(offset)) {
        snprintf(out, capacity, "seek_failed");
        file.close();
        return;
    }
    const size_t got = file.read(reinterpret_cast<uint8_t *>(tail), std::min(bytes - offset, sizeof(tail) - 1U));
    file.close();
    tail[got] = '\0';
    char *line = tail;
    if (last) {
        for (size_t i = 0; i < got; ++i)
            if (tail[i] == '\n' && i + 1U < got)
                line = tail + i + 1U;
    }
    char *end = std::strstr(line, " |");
    char *metadata = std::strstr(line, " | utc=");
    if (end && metadata) {
        char *stop = std::strstr(metadata, " repeat=");
        if (stop)
            *stop = '\0';
        snprintf(out, capacity, "%.*s %s", (int)(end - line), line, metadata + 3);
        return;
    }
    if (!end)
        end = std::strpbrk(line, "\r\n");
    if (end)
        *end = '\0';
    snprintf(out, capacity, "%s", line);
#else
    (void)path;
    (void)bytes;
    (void)last;
#endif
}
} // namespace

void diagnosticPolicyInit()
{
    if (ready.load())
        return;
#ifdef ARCH_ESP32
    bootId = esp_random();
#else
    bootId = static_cast<uint32_t>(random(1L, 0x7fffffffL));
#endif
    ready.store(true);
}

bool diagnosticDetailEnabled()
{
    return detailOn.load() && Throttle::isWithinTimespanMs(detailSince.load(), DIAGNOSTIC_DETAIL_MS);
}

const char *diagnosticRoleKey()
{
    return roleKey(activeDeviceRoleOr());
}

void diagnosticSetDetailEnabled(bool enabled)
{
    detailSince.store(millis());
    detailOn.store(enabled);
    diagnosticLog("LOG_MODE", "mode=%s duration_s=%u", enabled ? "detail" : "normal", enabled ? 600U : 0U);
}

bool diagnosticConsoleLevelEnabled(const char *level)
{
    const bool enabled = level && (diagnosticDetailEnabled() || !std::strcmp(level, "WARN ") || !std::strcmp(level, "ERROR") ||
                                   !std::strcmp(level, "CRIT "));
    if (!enabled && ready.load())
        ++filtered;
    return enabled;
}

bool diagnosticTryWrite()
{
    if (!ready.load() || inInterrupt()) {
        ++dropped;
        return false;
    }
    if (writeBusy.test_and_set()) {
        ++dropped;
        return false;
    }
    return true;
}

void diagnosticEndWrite()
{
    writeBusy.clear();
}

bool diagnosticFormatLine(char *out, size_t capacity, const char *event, const char *detail)
{
    const uint32_t now = millis();
    uint32_t repeats = 0;
    if (!repeatGate.accept(event, detail, now, diagnosticDetailEnabled(), repeats)) {
        ++suppressed;
        return false;
    }
    const int length =
        snprintf(out, capacity, "UPTIME+%lus | %-14s | utc=%u boot=%08x repeat=%u %s", (unsigned long)(now / 1000U), event,
                 (unsigned)getValidTime(RTCQualityDevice), (unsigned)bootId, (unsigned)repeats, detail ? detail : "");
    if (length < 0 || static_cast<size_t>(length) >= capacity)
        ++truncated;
    for (char *p = out; length >= 0 && *p; ++p)
        if (*p == '\r' || *p == '\n')
            *p = ' ';
    return length >= 0;
}

void diagnosticNoteWrite(bool success)
{
    if (success)
        ++written;
    else
        ++ioErrors;
}

void diagnosticNoteTruncation()
{
    ++truncated;
}

void diagnosticNoteRotation(size_t discardedBytes)
{
    ++rotations;
    discarded.fetch_add(static_cast<uint32_t>(discardedBytes));
}

void diagnosticQueueEvent(const char *event, const char *fmt, ...)
{
    if (!ready.load() || !event || inInterrupt() || queueBusy.test_and_set()) {
        ++dropped;
        return;
    }
    if (queueCount == 8U) {
        queueBusy.clear();
        ++dropped;
        return;
    }
    auto &entry = pending[(queueHead + queueCount) % 8U];
    entry.capturedMs = millis();
    snprintf(entry.event, sizeof(entry.event), "%s", event);
    va_list args;
    va_start(args, fmt);
    const int length = vsnprintf(entry.detail, sizeof(entry.detail), fmt ? fmt : "", args);
    va_end(args);
    if (length < 0 || static_cast<size_t>(length) >= sizeof(entry.detail))
        ++truncated;
    ++queueCount;
    queueBusy.clear();
}

void diagnosticCacheEvent(const char *action, const NodeStateRecord &record, const char *reason)
{
    if (!std::strcmp(action, "insert"))
        ++cacheAdds;
    else if (!std::strcmp(action, "update"))
        ++cacheUpdates;
    else if (!std::strcmp(action, "reject"))
        ++cacheRejects;
    else if (!std::strcmp(action, "expire"))
        ++cacheExpires;
    else if (!std::strcmp(action, "replace"))
        ++cacheReplaces;
    diagnosticQueueEvent("CACHE", "action=%s node=%08x packet=%08x source=%u expires=%u role=%s origin=%u reason=%s", action,
                         (unsigned)record.nodeNum, (unsigned)record.packetId, (unsigned)record.sourceEpoch,
                         (unsigned)record.expiresEpoch, roleKey(record.role), (unsigned)record.origin, reason ? reason : "none");
}

void diagnosticNotePacket(DiagnosticPacketKind kind, uint32_t node, uint32_t packet, uint32_t port, bool modulesAllowed)
{
    const size_t index = static_cast<size_t>(kind);
    if (index >= static_cast<size_t>(DiagnosticPacketKind::COUNT))
        return;
    ++packetKinds[index];
    if (!modulesAllowed)
        ++packetSkipped;
    if (diagnosticDetailEnabled())
        diagnosticQueueEvent("RX_PACKET", "node=0x%08x packet=0x%08x port=%u decoded=%u modules=%u", (unsigned)node,
                             (unsigned)packet, (unsigned)port, kind != DiagnosticPacketKind::UNDECODED ? 1U : 0U,
                             modulesAllowed ? 1U : 0U);
}

void diagnosticCacheSkip(uint32_t node, uint32_t packet, const char *reason)
{
    ++cacheSkipped;
    diagnosticQueueEvent("CACHE_SKIP", "node=0x%08x packet=0x%08x reason=%s", (unsigned)node, (unsigned)packet,
                         reason ? reason : "unknown");
}

void diagnosticSleepEnter(bool deep, uint32_t plannedMs)
{
    ++sleeps;
    if (deep) {
        deepIntent = {DEEP_INTENT_MAGIC, bootId, getValidTime(RTCQualityDevice), plannedMs};
        diagnosticLog("SLEEP_ENTER", "mode=deep role=%s planned_ms=%u result=pending", roleKey(activeDeviceRoleOr()),
                      (unsigned)plannedMs);
    } else {
        diagnosticQueueEvent("SLEEP_ENTER", "mode=light role=%s planned_ms=%u result=pending", roleKey(activeDeviceRoleOr()),
                             (unsigned)plannedMs);
    }
}

void diagnosticSleepWake(uint32_t plannedMs, uint32_t actualMs, int result, int cause, int buttonLevel, int radioLevel,
                         int motionLevel)
{
    ++wakes;
#ifdef ARCH_ESP32
    if (result != 0)
        ++rejectedStarts;
    else if (cause == ESP_SLEEP_WAKEUP_TIMER)
        ++timerWakes;
    else if (cause == ESP_SLEEP_WAKEUP_GPIO)
        ++gpioWakes;
    else
        ++otherWakes;
#endif
    diagnosticQueueEvent(
        "SLEEP_WAKE",
        "mode=light role=%s planned_ms=%u actual_ms=%u result=%d cause=%s raw=%d button=%d radio=%d motion=%d levels_are_hints=1",
        roleKey(activeDeviceRoleOr()), (unsigned)plannedMs, (unsigned)actualMs, result,
        result == 0 ? wakeName(cause) : "start_rejected", cause, buttonLevel, radioLevel, motionLevel);
}

void diagnosticRuntimeTick()
{
    if (!ready.load())
        return;
    if (detailOn.load() && !diagnosticDetailEnabled()) {
        detailOn.store(false);
        diagnosticLog("LOG_MODE", "mode=normal reason=detail_timeout");
    }
    if (!diagnosticLogEnabled())
        return;
    const DeviceRole role = activeDeviceRoleOr();
    const uint32_t signature =
        static_cast<uint32_t>(role) ^ (config.power.is_power_saving ? 0x100U : 0U) ^ (config.power.ls_secs << 9U);
    if (!contextSent || signature != lastConfig) {
        contextSent = true;
        lastConfig = signature;
        diagnosticLog("LOG_CONTEXT", "format=%u board=%s build=%u role=%s power_save=%u configured_ls_s=%u mode=%s",
                      (unsigned)DIAGNOSTIC_LOG_FORMAT, build::hardwareName, (unsigned)build::buildNumber, roleKey(role),
                      config.power.is_power_saving ? 1U : 0U, (unsigned)config.power.ls_secs,
                      diagnosticDetailEnabled() ? "detail" : "normal");
        if (!bootReported) {
            bootReported = true;
#ifdef ARCH_ESP32
            const uint64_t mask = esp_sleep_get_ext1_wakeup_status();
            diagnosticLog("BOOT_STATE", "reset_raw=%u cause=%s wake_raw=%d ext1_mask=%08x%08x", (unsigned)esp_reset_reason(),
                          wakeName(esp_sleep_get_wakeup_cause()), (int)esp_sleep_get_wakeup_cause(), (unsigned)(mask >> 32U),
                          (unsigned)mask);
#elif defined(ARCH_NRF52)
            diagnosticLog("BOOT_STATE", "reset_raw=%08x cause=platform_unknown", (unsigned)readResetReason());
#else
            diagnosticLog("BOOT_STATE", "reset_known=0 cause=platform_unknown");
#endif
        }
#ifdef ARCH_ESP32
        if (deepIntent.magic == DEEP_INTENT_MAGIC) {
            const uint32_t epoch = getValidTime(RTCQualityDevice);
            const bool validDuration = epoch && deepIntent.epoch && epoch >= deepIntent.epoch;
            const bool resumed = esp_reset_reason() == ESP_RST_DEEPSLEEP;
            diagnosticLog("SLEEP_RESUME",
                          "mode=deep previous_boot=%08x planned_ms=%u actual_s=%u duration_source=rtc_delta duration_known=%u "
                          "resumed=%u reset=%u cause=%s raw=%d",
                          (unsigned)deepIntent.boot, (unsigned)deepIntent.plannedMs,
                          validDuration ? (unsigned)(epoch - deepIntent.epoch) : 0U, validDuration ? 1U : 0U, resumed ? 1U : 0U,
                          (unsigned)esp_reset_reason(), wakeName(esp_sleep_get_wakeup_cause()),
                          (int)esp_sleep_get_wakeup_cause());
            deepIntent = {};
        }
#endif
    }
    drainQueue();
    char repeatedEvent[24]{}, repeatedContext[64]{};
    uint32_t repeatCount = 0;
    bool summaryAvailable = false;
    if ((!summaryAt || !Throttle::isWithinTimespanMs(summaryAt, 1000U)) && !writeBusy.test_and_set()) {
        summaryAt = millis() ? millis() : 1U;
        summaryAvailable =
            repeatGate.takeSummary(repeatedEvent, sizeof(repeatedEvent), repeatedContext, sizeof(repeatedContext), repeatCount);
        writeBusy.clear();
    }
    if (summaryAvailable)
        diagnosticLog("LOG_REPEAT", "event=%s count=%u context=%s", repeatedEvent, (unsigned)repeatCount, repeatedContext);
    if (healthAt && Throttle::isWithinTimespanMs(healthAt, 60000U))
        return;
    healthAt = millis() ? millis() : 1U;
    crashTraceTouch();
    const uint32_t heap = memGet.getFreeHeap();
    diagnosticLog(
        "HEALTH",
        "role=%s power_save=%u usb=%d bat_mv=%d bat_pct=%d ble=%u wifi=%u gps=%d fix=%d heap=%u cache=%u/%u sleep_attempt=%u "
        "sleep_return=%u",
        roleKey(role), config.power.is_power_saving ? 1U : 0U, powerStatus ? (int)powerStatus->getHasUSBState() : 2,
        powerStatus ? powerStatus->getBatteryVoltageMv() : -1, powerStatus ? powerStatus->getBatteryChargePercent() : -1,
        bluetoothStatus ? (unsigned)bluetoothStatus->getConnectionState() : UINT32_MAX, jarnsenServiceWebActive() ? 1U : 0U,
        gpsStatus ? (int)gpsStatus->getIsConnected() : -1, gpsStatus ? (int)gpsStatus->getHasLock() : -1, (unsigned)heap,
        (unsigned)nodeStateCache().count(getValidTime(RTCQualityDevice)), (unsigned)JARNSEN_NODE_STATE_CACHE_CAPACITY,
        (unsigned)sleeps.load(), (unsigned)wakes.load());
    const auto *radio = RadioLibInterface::instance;
    diagnosticLog("HEALTH_SLEEP", "scope=this_boot timer=%u gpio_unresolved=%u other=%u start_rejected=%u",
                  (unsigned)timerWakes.load(), (unsigned)gpioWakes.load(), (unsigned)otherWakes.load(),
                  (unsigned)rejectedStarts.load());
    if (powerStatus)
        diagnosticLog("POWER_SOURCE", "voltage_source=%s has_battery=%d usb=%d charging=%d ina_battery_addr=0x%x",
                      powerStatus->getBatteryVoltageSource(), (int)powerStatus->getHasBatteryState(),
                      (int)powerStatus->getHasUSBState(), (int)powerStatus->getIsChargingState(),
                      (unsigned)config.power.device_battery_ina_address);
#if defined(HELTEC_TRACKER_V1_1)
    const auto powerStats = trackerPowerMonitorStats();
    diagnosticLog("POWER_INA",
                  "configured=%u present=%u sample_valid=%u bus_valid=%u bus_mv=%u current_x10_ma=%ld "
                  "awake_x10_mah=%u sleep_est_x10_mah=%u capacity_ready=%u capacity_mah=%u confidence=%u",
                  powerStats.inaConfigured ? 1U : 0U, powerStats.inaPresent ? 1U : 0U, powerStats.inaValid ? 1U : 0U,
                  powerStats.vbusValid ? 1U : 0U, (unsigned)powerStats.inaBusVoltageMv, (long)powerStats.currentMilliAmpsX10,
                  (unsigned)powerStats.awakeMeasuredMahX10, (unsigned)powerStats.sleepEstimatedMahX10,
                  powerStats.capacityReady ? 1U : 0U, (unsigned)powerStats.learnedCapacityMah,
                  (unsigned)powerStats.capacityConfidence);
    diagnosticLog("POWER_INA_SAMPLE", "state=%s calibration=%u status=0x%x current_ua=%ld light_counted=%us deep_counted=%us",
                  trackerPowerInaState(powerStats), (unsigned)powerStats.inaCalibration, (unsigned)powerStats.inaStatus,
                  (long)powerStats.currentMicroAmps, (unsigned)powerStats.lightSleepSecs, (unsigned)powerStats.deepSleepSecs);
#endif
    diagnosticLog("HEALTH_FLOW", "radio_known=%u rx=%u tx=%u fwd=%u cache_add=%u update=%u reject=%u expire=%u replace=%u",
                  radio ? 1U : 0U, radio ? (unsigned)radio->rxGood : 0U, radio ? (unsigned)radio->txGood : 0U,
                  radio ? (unsigned)radio->txRelay : 0U, (unsigned)cacheAdds.load(), (unsigned)cacheUpdates.load(),
                  (unsigned)cacheRejects.load(), (unsigned)cacheExpires.load(), (unsigned)cacheReplaces.load());
    diagnosticLog("HEALTH_RX",
                  "scope=this_boot source=radio position=%u atak=%u nodeinfo=%u telemetry=%u routing=%u private=%u other=%u "
                  "undecoded=%u module_skip=%u cache_skip=%u",
                  (unsigned)packetKinds[0].load(), (unsigned)packetKinds[1].load(), (unsigned)packetKinds[2].load(),
                  (unsigned)packetKinds[3].load(), (unsigned)packetKinds[4].load(), (unsigned)packetKinds[5].load(),
                  (unsigned)packetKinds[6].load(), (unsigned)packetKinds[7].load(), (unsigned)packetSkipped.load(),
                  (unsigned)cacheSkipped.load());
    diagnosticLog("HEALTH_LOG", "written=%u suppressed=%u filtered=%u dropped=%u io_error=%u truncated=%u",
                  (unsigned)written.load(), (unsigned)suppressed.load(), (unsigned)filtered.load(), (unsigned)dropped.load(),
                  (unsigned)ioErrors.load(), (unsigned)truncated.load());
}

bool diagnosticSnapshotMetadata(char *out, size_t capacity, const char *previousPath, size_t previousBytes,
                                const char *currentPath, size_t currentBytes)
{
    char first[80]{}, last[80]{};
    fileBoundary(first, sizeof(first), previousBytes ? previousPath : currentPath, previousBytes ? previousBytes : currentBytes,
                 false);
    fileBoundary(last, sizeof(last), currentBytes ? currentPath : previousPath, currentBytes ? currentBytes : previousBytes,
                 true);
    const int length =
        snprintf(out, capacity,
                 "# schema=unified-role-v1\r\n# build_number=%u\r\n# role_key=%s\r\n# boot_id=%08x\r\n"
                 "# log_mode=%s\r\n# stats_scope=this_boot_at_export_start\r\n"
                 "# written=%u suppressed=%u filtered=%u dropped=%u io_errors=%u truncated=%u\r\n"
                 "# rotations=%u discarded_bytes=%u\r\n# history=rotating_files\r\n"
                 "# history_first=%s\r\n# history_last=%s\r\n",
                 (unsigned)build::buildNumber, roleKey(activeDeviceRoleOr()), (unsigned)bootId,
                 diagnosticDetailEnabled() ? "detail" : "normal", (unsigned)written.load(), (unsigned)suppressed.load(),
                 (unsigned)filtered.load(), (unsigned)dropped.load(), (unsigned)ioErrors.load(), (unsigned)truncated.load(),
                 (unsigned)rotations.load(), (unsigned)discarded.load(), first, last);
    return length >= 0 && static_cast<size_t>(length) < capacity;
}
} // namespace jarnsen
