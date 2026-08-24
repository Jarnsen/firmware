#include "infrastructure/HeltecV3DiagnosticLog.h"
#include "HeltecV3BuildGenerated.h"
#include "NodeDB.h"
#include "configuration.h"
#include "infrastructure/HeltecV3MeshMonitor.h"

#if defined(_VARIANT_HELTEC_V3)

#include "FSCommon.h"
#include "gps/RTC.h"

#include <Arduino.h>
#include <Preferences.h>
#include <cstdarg>
#include <cstdio>
#include <ctime>
#include <esp_system.h>

namespace
{
constexpr const char *PREF_NAMESPACE = "v3Diag";
constexpr const char *CURRENT_LOG = "/v3_diag.log";
constexpr const char *PREVIOUS_LOG = "/v3_diag.prev.log";
constexpr size_t MAX_LOG_BYTES = 64U * 1024U;
constexpr uint32_t USB_SETTLE_MS = 1000UL;
constexpr const char *DIAG_FEATURE_VERSION = "diag-meta-v1";
constexpr uint32_t DIAG_LOG_FORMAT = 2U;

const char *diagRoleText()
{
    switch (config.device.role) {
    case meshtastic_Config_DeviceConfig_Role_ROUTER_LATE:
        return "ROUTER_LATE";
    case meshtastic_Config_DeviceConfig_Role_REPEATER:
        return "REPEATER";
    default:
        return "OTHER";
    }
}

enum class UsbExportState : uint8_t { IDLE = 0, WAIT_USB, SENDING, COMPLETE, ERROR };

bool initialized = false;
HeltecV3DiagStats stats{};
esp_reset_reason_t bootResetReason = ESP_RST_UNKNOWN;

bool exportRequested = false;
uint8_t exportPhase = 0;
File exportFile;
UsbExportState exportState = UsbExportState::IDLE;
uint32_t serialConnectedSinceMs = 0;
size_t exportTotalBytes = 0;
size_t exportBytesSent = 0;

size_t fileSize(const char *path)
{
    File file = FSCom.open(path, FILE_O_READ);
    if (!file)
        return 0;
    const size_t size = file.size();
    file.close();
    return size;
}

void rotateIfNeeded(size_t incomingBytes)
{
    const size_t currentSize = fileSize(CURRENT_LOG);
    if (currentSize + incomingBytes <= MAX_LOG_BYTES)
        return;

    if (FSCom.exists(PREVIOUS_LOG))
        FSCom.remove(PREVIOUS_LOG);
    if (FSCom.exists(CURRENT_LOG))
        FSCom.rename(CURRENT_LOG, PREVIOUS_LOG);
}

void makeTimestamp(char *out, size_t outSize)
{
    if (!out || outSize == 0)
        return;

    const uint32_t epoch = getValidTime(RTCQualityDevice);
    if (epoch != 0) {
        time_t raw = (time_t)epoch;
        struct tm tmUtc = {};
        gmtime_r(&raw, &tmUtc);
        snprintf(out, outSize, "%04d-%02d-%02dT%02d:%02d:%02dZ", tmUtc.tm_year + 1900, tmUtc.tm_mon + 1, tmUtc.tm_mday,
                 tmUtc.tm_hour, tmUtc.tm_min, tmUtc.tm_sec);
    } else {
        snprintf(out, outSize, "UPTIME+%lus", (unsigned long)(millis() / 1000UL));
    }
}

void appendLine(const char *line)
{
    if (!line || !line[0])
        return;

    const size_t length = strlen(line);
    rotateIfNeeded(length + 1U);
    File file = FSCom.open(CURRENT_LOG, "a");
    if (!file)
        return;
    file.write((const uint8_t *)line, length);
    file.write((const uint8_t *)"\n", 1);
    file.flush();
    file.close();
}

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

void loadCounters()
{
    Preferences prefs;
    if (!prefs.begin(PREF_NAMESPACE, true))
        return;
    stats.bootCount = prefs.getULong("boot", 0);
    stats.crashResetCount = prefs.getULong("crash", 0);
    stats.serviceOpenCount = prefs.getULong("svc", 0);
    stats.bleConnectionCount = prefs.getULong("bleConn", 0);
    stats.bleRecoveryCount = prefs.getULong("bleRec", 0);
    stats.autoPositionSaveCount = prefs.getULong("posAuto", 0);
    stats.manualPositionSaveCount = prefs.getULong("posMan", 0);
    prefs.end();
}

void saveCounters()
{
    Preferences prefs;
    if (!prefs.begin(PREF_NAMESPACE, false))
        return;
    prefs.putULong("boot", stats.bootCount);
    prefs.putULong("crash", stats.crashResetCount);
    prefs.putULong("svc", stats.serviceOpenCount);
    prefs.putULong("bleConn", stats.bleConnectionCount);
    prefs.putULong("bleRec", stats.bleRecoveryCount);
    prefs.putULong("posAuto", stats.autoPositionSaveCount);
    prefs.putULong("posMan", stats.manualPositionSaveCount);
    prefs.end();
}

bool openExportFile(const char *path)
{
    if (exportFile)
        exportFile.close();
    exportFile = FSCom.open(path, FILE_O_READ);
    return (bool)exportFile;
}

void closeExportFile()
{
    if (exportFile)
        exportFile.close();
}

void resetTransferToWait()
{
    closeExportFile();
    exportPhase = 1;
    exportBytesSent = 0;
    serialConnectedSinceMs = 0;
    exportState = UsbExportState::WAIT_USB;
}

void pumpFileChunk()
{
    if (!exportFile)
        return;
    uint8_t buffer[384];
    const int available = exportFile.available();
    if (available <= 0)
        return;
    const size_t want = (size_t)available < sizeof(buffer) ? (size_t)available : sizeof(buffer);
    const size_t got = exportFile.read(buffer, want);
    if (got)
        exportBytesSent += Serial.write(buffer, got);
}
} // namespace

void heltecV3DiagInit()
{
    if (initialized)
        return;

    loadCounters();
    bootResetReason = esp_reset_reason();
    stats.bootCount++;
    if (resetLooksLikeCrash(bootResetReason))
        stats.crashResetCount++;
    saveCounters();
    initialized = true;

    heltecV3DiagLog("BOOT",
                    "count=%u reset=%s crashCount=%u role=%s firmware=%s "
                    "build=%s built=%s %s feature=%s logFormat=%u",
                    (unsigned)stats.bootCount, heltecV3DiagResetReasonText(), (unsigned)stats.crashResetCount, diagRoleText(),
                    xstr(APP_VERSION), JARNSEN_V3_BUILD_SHA, __DATE__, __TIME__, DIAG_FEATURE_VERSION, (unsigned)DIAG_LOG_FORMAT);
}

void heltecV3DiagLog(const char *event, const char *fmt, ...)
{
    if (!initialized || !event)
        return;

    char timestamp[32] = {};
    makeTimestamp(timestamp, sizeof(timestamp));

    char detail[224] = {};
    if (fmt && fmt[0]) {
        va_list args;
        va_start(args, fmt);
        vsnprintf(detail, sizeof(detail), fmt, args);
        va_end(args);
    }

    char line[320] = {};
    if (detail[0])
        snprintf(line, sizeof(line), "%s | %-14s | %s", timestamp, event, detail);
    else
        snprintf(line, sizeof(line), "%s | %s", timestamp, event);
    appendLine(line);
}

void heltecV3DiagNoteServiceOpen()
{
    stats.serviceOpenCount++;
    if ((stats.serviceOpenCount & 7U) == 0U)
        saveCounters();
    heltecV3DiagLog("SERVICE_OPEN", "count=%u", (unsigned)stats.serviceOpenCount);
}

void heltecV3DiagNoteBleConnection()
{
    stats.bleConnectionCount++;
    if ((stats.bleConnectionCount & 7U) == 0U)
        saveCounters();
    heltecV3DiagLog("BLE_CONNECT", "count=%u", (unsigned)stats.bleConnectionCount);
}

void heltecV3DiagNoteBleRecovery()
{
    stats.bleRecoveryCount++;
    saveCounters();
    heltecV3DiagLog("BLE_RECOVERY", "count=%u", (unsigned)stats.bleRecoveryCount);
}

void heltecV3DiagNotePositionSave(bool automatic, uint32_t differenceM)
{
    if (automatic)
        stats.autoPositionSaveCount++;
    else
        stats.manualPositionSaveCount++;
    saveCounters();
    heltecV3DiagLog(automatic ? "POSITION_AUTO" : "POSITION_MAN", "diff=%um auto=%u manual=%u", (unsigned)differenceM,
                    (unsigned)stats.autoPositionSaveCount, (unsigned)stats.manualPositionSaveCount);
}

HeltecV3DiagStats heltecV3DiagStats()
{
    return stats;
}

const char *heltecV3DiagResetReasonText()
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
    case ESP_RST_SDIO:
        return "SDIO";
    default:
        return "OTHER";
    }
}

size_t heltecV3DiagLogSize()
{
    return fileSize(PREVIOUS_LOG) + fileSize(CURRENT_LOG);
}

void heltecV3DiagClear()
{
    closeExportFile();
    exportRequested = false;
    exportPhase = 0;
    exportState = UsbExportState::IDLE;
    serialConnectedSinceMs = 0;
    exportTotalBytes = 0;
    exportBytesSent = 0;
    if (FSCom.exists(CURRENT_LOG))
        FSCom.remove(CURRENT_LOG);
    if (FSCom.exists(PREVIOUS_LOG))
        FSCom.remove(PREVIOUS_LOG);
    heltecV3DiagLog("LOGGER", "log cleared");
}

void heltecV3DiagRequestUsbExport()
{
    closeExportFile();
    saveCounters();
    exportRequested = true;
    exportPhase = 1;
    exportState = UsbExportState::WAIT_USB;
    serialConnectedSinceMs = 0;
    exportBytesSent = 0;
    heltecV3DiagLog("LOG_EXPORT", "requested serial=%u bytes=%u", (bool)Serial ? 1U : 0U, (unsigned)heltecV3DiagLogSize());
    exportTotalBytes = heltecV3DiagLogSize();
}

bool heltecV3DiagUsbExportPending()
{
    return exportRequested;
}

const char *heltecV3DiagUsbExportStatusText()
{
    switch (exportState) {
    case UsbExportState::WAIT_USB:
        return (bool)Serial ? "USB READY" : "CONNECT PC";
    case UsbExportState::SENDING:
        return "LOG EXPORT";
    case UsbExportState::COMPLETE:
        return "LOG DONE";
    case UsbExportState::ERROR:
        return "LOG ERROR";
    case UsbExportState::IDLE:
    default:
        return "LOG READY";
    }
}

uint8_t heltecV3DiagUsbExportProgress()
{
    if (exportState == UsbExportState::COMPLETE)
        return 100;
    if (exportState != UsbExportState::SENDING || exportTotalBytes == 0)
        return 0;
    const size_t pct = (exportBytesSent * 100U) / exportTotalBytes;
    return (uint8_t)(pct > 99U ? 99U : pct);
}

void heltecV3DiagPumpUsbExport()
{
    if (!exportRequested)
        return;

    if (!(bool)Serial) {
        if (exportState == UsbExportState::SENDING)
            resetTransferToWait();
        else {
            exportState = UsbExportState::WAIT_USB;
            serialConnectedSinceMs = 0;
        }
        return;
    }

    if (exportState == UsbExportState::WAIT_USB) {
        const uint32_t now = millis();
        if (serialConnectedSinceMs == 0) {
            serialConnectedSinceMs = now ? now : 1;
            return;
        }
        if ((uint32_t)(now - serialConnectedSinceMs) < USB_SETTLE_MS)
            return;
        exportState = UsbExportState::SENDING;
    }

    switch (exportPhase) {
    case 1:
        Serial.print("\r\n===JARNSEN_DIAG_LOG_BEGIN===\r\n");
        {
            char exportTime[32] = {};
            makeTimestamp(exportTime, sizeof(exportTime));
            Serial.print("# device=HELTEC_V3_REPEATER\r\n");
            Serial.printf("# firmware=%s\r\n", xstr(APP_VERSION));
            Serial.printf("# build=%s\r\n", JARNSEN_V3_BUILD_SHA);
            Serial.printf("# build_time=%s %s\r\n", __DATE__, __TIME__);
            Serial.printf("# role=%s\r\n", diagRoleText());
            Serial.printf("# feature=%s\r\n", DIAG_FEATURE_VERSION);
            Serial.printf("# log_format=%u\r\n", (unsigned)DIAG_LOG_FORMAT);
            Serial.printf("# export=%s\r\n", exportTime);
        }
        Serial.printf("# bytes=%u\r\n", (unsigned)exportTotalBytes);
        Serial.flush();
        exportPhase = 2;
        if (!openExportFile(PREVIOUS_LOG))
            exportPhase = 3;
        break;
    case 2:
        if (exportFile && exportFile.available() > 0)
            pumpFileChunk();
        else {
            closeExportFile();
            exportPhase = 3;
        }
        break;
    case 3:
        if (!exportFile && !openExportFile(CURRENT_LOG)) {
            exportPhase = 4;
            break;
        }
        if (exportFile.available() > 0)
            pumpFileChunk();
        else {
            closeExportFile();
            exportPhase = 4;
        }
        break;
    case 4:
        heltecV3MeshMonitorPrintSnapshot(Serial);
        Serial.print("\r\n===JARNSEN_DIAG_LOG_END===\r\n");
        Serial.flush();
        exportRequested = false;
        exportPhase = 0;
        exportState = UsbExportState::COMPLETE;
        closeExportFile();
        heltecV3DiagLog("LOG_EXPORT", "complete sent=%u", (unsigned)exportBytesSent);
        break;
    default:
        closeExportFile();
        exportRequested = false;
        exportPhase = 0;
        exportState = UsbExportState::ERROR;
        heltecV3DiagLog("LOG_EXPORT", "invalid phase");
        break;
    }
}

#else

void heltecV3DiagInit() {}
void heltecV3DiagLog(const char *, const char *, ...) {}
void heltecV3DiagNoteServiceOpen() {}
void heltecV3DiagNoteBleConnection() {}
void heltecV3DiagNoteBleRecovery() {}
void heltecV3DiagNotePositionSave(bool, uint32_t) {}
HeltecV3DiagStats heltecV3DiagStats()
{
    return {};
}
const char *heltecV3DiagResetReasonText()
{
    return "N/A";
}
size_t heltecV3DiagLogSize()
{
    return 0;
}
void heltecV3DiagClear() {}
void heltecV3DiagRequestUsbExport() {}
bool heltecV3DiagUsbExportPending()
{
    return false;
}
const char *heltecV3DiagUsbExportStatusText()
{
    return "N/A";
}
uint8_t heltecV3DiagUsbExportProgress()
{
    return 0;
}
void heltecV3DiagPumpUsbExport() {}

#endif
