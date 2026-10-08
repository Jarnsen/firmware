#include "jarnsen/core/service/JarnsenCrashTrace.h"

#include "jarnsen/core/build/JarnsenBuildInfo.h"
#include "jarnsen/core/service/JarnsenDiagnosticLog.h"

#if defined(ARCH_ESP32)

#include <Arduino.h>
#include <cstring>
#include <esp_attr.h>
#include <esp_heap_caps.h>
#include <esp_system.h>
#include <freertos/FreeRTOS.h>
#include <freertos/task.h>

namespace jarnsen
{
namespace
{
constexpr uint32_t TRACE_MAGIC = 0x4a435254U; // JCRT
constexpr uint16_t TRACE_VERSION = 1U;
constexpr uint8_t TRACE_CAPACITY = 20U;

struct TraceEntry {
    uint32_t uptimeMs;
    uint32_t freeHeap;
    uint32_t minFreeHeap;
    uint32_t largestBlock;
    uint16_t stackWatermark;
    uint16_t step;
    char name[28];
    char task[16];
};

struct TraceState {
    uint32_t magic;
    uint16_t version;
    uint8_t count;
    uint8_t head;
    uint8_t cleanShutdown;
    uint8_t reserved[3];
    uint32_t lastUptimeMs;
    TraceEntry entries[TRACE_CAPACITY];
    uint32_t crc;
};

RTC_NOINIT_ATTR TraceState rtcTrace;
TraceState previousTrace{};
bool previousTraceValid = false;
bool initialized = false;
uint32_t currentResetReason = 0U;

uint32_t crc32(const uint8_t *data, size_t length)
{
    uint32_t crc = 0xffffffffU;
    while (length--) {
        crc ^= *data++;
        for (uint8_t bit = 0; bit < 8U; ++bit)
            crc = (crc >> 1U) ^ (0xedb88320U & (0U - (crc & 1U)));
    }
    return crc ^ 0xffffffffU;
}

void sealTrace()
{
    rtcTrace.crc = crc32(reinterpret_cast<const uint8_t *>(&rtcTrace), offsetof(TraceState, crc));
}

bool validTrace(const TraceState &trace)
{
    if (trace.magic != TRACE_MAGIC || trace.version != TRACE_VERSION || trace.count > TRACE_CAPACITY ||
        trace.head >= TRACE_CAPACITY)
        return false;
    return trace.crc == crc32(reinterpret_cast<const uint8_t *>(&trace), offsetof(TraceState, crc));
}

void cleanShutdownHandler()
{
    if (rtcTrace.magic != TRACE_MAGIC || rtcTrace.version != TRACE_VERSION)
        return;
    rtcTrace.cleanShutdown = 1U;
    rtcTrace.lastUptimeMs = millis();
    sealTrace();
}

bool resetLooksLikeCrash(uint32_t reason)
{
    return reason == (uint32_t)ESP_RST_PANIC || reason == (uint32_t)ESP_RST_INT_WDT ||
           reason == (uint32_t)ESP_RST_TASK_WDT || reason == (uint32_t)ESP_RST_WDT;
}
} // namespace

const char *crashTraceResetReasonName(uint32_t reason)
{
    switch ((esp_reset_reason_t)reason) {
    case ESP_RST_POWERON:
        return "POWERON";
    case ESP_RST_EXT:
        return "EXT";
    case ESP_RST_SW:
        return "SW";
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
    default:
        return "OTHER";
    }
}

void crashTraceInit()
{
    if (initialized)
        return;

    currentResetReason = (uint32_t)esp_reset_reason();
    if (validTrace(rtcTrace)) {
        previousTrace = rtcTrace;
        previousTraceValid = true;
    }

    memset(&rtcTrace, 0, sizeof(rtcTrace));
    rtcTrace.magic = TRACE_MAGIC;
    rtcTrace.version = TRACE_VERSION;
    rtcTrace.cleanShutdown = 0U;
    rtcTrace.lastUptimeMs = millis();
    sealTrace();

    // Normal esp_restart() paths mark the previous boot clean. Panics/watchdogs
    // do not rely on this hook; their last breadcrumbs are already in RTC.
    (void)esp_register_shutdown_handler(cleanShutdownHandler);
    initialized = true;
}

void crashTraceBreadcrumb(uint16_t step, const char *name)
{
    if (!initialized)
        crashTraceInit();

    TraceEntry &entry = rtcTrace.entries[rtcTrace.head];
    memset(&entry, 0, sizeof(entry));
    entry.uptimeMs = millis();
    entry.freeHeap = heap_caps_get_free_size(MALLOC_CAP_8BIT);
    entry.minFreeHeap = heap_caps_get_minimum_free_size(MALLOC_CAP_8BIT);
    entry.largestBlock = heap_caps_get_largest_free_block(MALLOC_CAP_8BIT);
    entry.stackWatermark = (uint16_t)std::min<UBaseType_t>(uxTaskGetStackHighWaterMark(nullptr), UINT16_MAX);
    entry.step = step;
    snprintf(entry.name, sizeof(entry.name), "%s", name && name[0] ? name : "-");
    const char *task = pcTaskGetName(nullptr);
    snprintf(entry.task, sizeof(entry.task), "%s", task && task[0] ? task : "-");

    rtcTrace.lastUptimeMs = entry.uptimeMs;
    rtcTrace.head = (uint8_t)((rtcTrace.head + 1U) % TRACE_CAPACITY);
    if (rtcTrace.count < TRACE_CAPACITY)
        rtcTrace.count++;
    sealTrace();
}

void crashTraceTouch()
{
    if (!initialized)
        crashTraceInit();
    rtcTrace.lastUptimeMs = millis();
    sealTrace();
}

void crashTraceReport(uint32_t bootCount)
{
    if (!initialized)
        crashTraceInit();

    const uint32_t prevUptime = previousTraceValid ? previousTrace.lastUptimeMs / 1000U : 0U;
    const char *reasonName = crashTraceResetReasonName(currentResetReason);

    diagnosticLog("BOOT_BEGIN", "boot=%u reset=%s reset_code=%u build=%u sha=%s prev_uptime=%us",
                  (unsigned)bootCount, reasonName, (unsigned)currentResetReason, (unsigned)build::buildNumber,
                  build::gitSha, (unsigned)prevUptime);
    diagnosticLog("RESET_REASON", "name=%s code=%u prev_uptime=%us trace_valid=%u clean=%u rtc_bytes=%u",
                  reasonName, (unsigned)currentResetReason, (unsigned)prevUptime, previousTraceValid ? 1U : 0U,
                  previousTraceValid && previousTrace.cleanShutdown ? 1U : 0U, (unsigned)sizeof(TraceState));

    if (!previousTraceValid)
        return;

    if (!previousTrace.cleanShutdown && currentResetReason != (uint32_t)ESP_RST_POWERON) {
        diagnosticLog("UNCLEAN_SHUTDOWN", "reset=%s prev_uptime=%us breadcrumbs=%u",
                      reasonName, (unsigned)prevUptime, (unsigned)previousTrace.count);
    }

    if (!resetLooksLikeCrash(currentResetReason) && previousTrace.cleanShutdown)
        return;

    const uint8_t count = previousTrace.count;
    const uint8_t first =
        count < TRACE_CAPACITY ? 0U : previousTrace.head;
    for (uint8_t index = 0; index < count; ++index) {
        const uint8_t slot = (uint8_t)((first + index) % TRACE_CAPACITY);
        const TraceEntry &entry = previousTrace.entries[slot];
        diagnosticLog("LAST_LINES_BEFORE_RESET",
                      "idx=%u step=%u name=%s uptime_ms=%u heap=%u min=%u largest=%u stack=%u task=%s",
                      (unsigned)index, (unsigned)entry.step, entry.name, (unsigned)entry.uptimeMs,
                      (unsigned)entry.freeHeap, (unsigned)entry.minFreeHeap, (unsigned)entry.largestBlock,
                      (unsigned)entry.stackWatermark, entry.task);
    }
}

} // namespace jarnsen

#else

namespace jarnsen
{
void crashTraceInit() {}
void crashTraceReport(uint32_t) {}
void crashTraceBreadcrumb(uint16_t, const char *) {}
void crashTraceTouch() {}
const char *crashTraceResetReasonName(uint32_t)
{
    return "N/A";
}
} // namespace jarnsen

#endif
