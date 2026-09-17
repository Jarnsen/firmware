#include "infrastructure/HeltecV3DiagnosticLog.h"
#include "HeltecV3BuildGenerated.h"
#include "NodeDB.h"
#include "Throttle.h"
#include "configuration.h"
#include "infrastructure/HeltecV3MeshMonitor.h"
#include "infrastructure/HeltecV3PowerMonitor.h"
#include "infrastructure/HeltecV3Runtime.h"

#if defined(_VARIANT_HELTEC_V3)

#include "FSCommon.h"
#include "gps/RTC.h"

#include <Arduino.h>
#include <Preferences.h>
#include <algorithm>
#include <atomic>
#include <cstdarg>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <ctime>
#include <esp_system.h>

namespace
{
constexpr const char *PREF_NAMESPACE = "v3Diag";
constexpr const char *CURRENT_LOG = "/v3_diag.log";
constexpr const char *PREVIOUS_LOG = "/v3_diag.prev.log";
constexpr size_t MAX_LOG_BYTES = 64U * 1024U;
constexpr uint32_t USB_SETTLE_MS = 1000UL;
constexpr uint32_t USB_WRITE_TIMEOUT_MS = 5000UL;
constexpr size_t USB_WRITE_CHUNK_BYTES = 512U;
constexpr size_t USB_FILE_BUFFER_BYTES = 1024U;
constexpr size_t USB_FLUSH_INTERVAL_BYTES = 8U * 1024U;
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
enum class BleExportState : uint8_t { READY = 0, DOWNLOADING, COMPLETE, CANCELLED, ERROR };

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
size_t exportPreviousRemaining = 0;
size_t exportCurrentRemaining = 0;
uint8_t *usbTransferBuffer = nullptr;
size_t usbBytesSinceFlush = 0;
std::atomic<bool> usbServiceHold{false};
std::atomic<bool> bleServiceHold{false};
File bleExportFile;
uint8_t bleExportPhase = 0;
size_t blePreviousRemaining = 0;
size_t bleCurrentRemaining = 0;
size_t blePayloadSent = 0;
size_t bleTotalBytes = 0;
uint32_t bleCrc = 0xffffffffU;
char bleHeader[1400] = {};
size_t bleHeaderLength = 0;
size_t bleHeaderOffset = 0;
char bleFooter[160] = {};
size_t bleFooterLength = 0;
size_t bleFooterOffset = 0;
std::atomic<BleExportState> bleUiState{BleExportState::READY};
std::atomic<uint8_t> bleUiProgress{0};
std::atomic<uint32_t> bleUiSequence{0};

void setRuntimeServiceHold(std::atomic<bool> &owned, bool active)
{
    if (active) {
        if (!owned.load() && heltecV3RuntimeSetBleQueueHold(true))
            owned.store(true);
    } else if (owned.exchange(false)) {
        heltecV3RuntimeSetBleQueueHold(false);
    }
}

bool ensureUsbTransferBuffer()
{
    if (usbTransferBuffer)
        return true;
    usbTransferBuffer = (uint8_t *)malloc(USB_FILE_BUFFER_BYTES);
    return usbTransferBuffer != nullptr;
}

void releaseUsbTransferBuffer()
{
    if (usbTransferBuffer) {
        free(usbTransferBuffer);
        usbTransferBuffer = nullptr;
    }
    usbBytesSinceFlush = 0;
}

uint32_t updateCrc32(uint32_t crc, const uint8_t *data, size_t length)
{
    while (length--) {
        crc ^= *data++;
        for (uint8_t bit = 0; bit < 8; bit++)
            crc = (crc >> 1U) ^ (0xedb88320U & (0U - (crc & 1U)));
    }
    return crc;
}

void closeBleExportFile()
{
    if (bleExportFile)
        bleExportFile.close();
}

void resetBleExportTransfer()
{
    closeBleExportFile();
    bleExportPhase = 0;
    bleHeaderOffset = 0;
    bleFooterOffset = 0;
}

void setBleUiState(BleExportState state, uint8_t progress)
{
    bleUiProgress.store(progress);
    bleUiState.store(state);
    bleUiSequence.fetch_add(1);
}

bool openBleExportFile(const char *path)
{
    closeBleExportFile();
    bleExportFile = FSCom.open(path, FILE_O_READ);
    return (bool)bleExportFile;
}

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
    usbBytesSinceFlush = 0;
}

bool writeSerialAll(const uint8_t *data, size_t length, bool countPayload)
{
    size_t offset = 0;
    uint32_t lastProgressMs = millis() ? millis() : 1;
    while (offset < length) {
        if (!(bool)Serial)
            return false;
        const size_t remaining = length - offset;
        const size_t chunk = std::min(remaining, USB_WRITE_CHUNK_BYTES);
        const size_t written = Serial.write(data + offset, chunk);
        if (written > 0) {
            offset += written;
            if (countPayload)
                exportBytesSent += written;
            lastProgressMs = millis() ? millis() : 1;
            usbBytesSinceFlush += written;
            if (usbBytesSinceFlush >= USB_FLUSH_INTERVAL_BYTES) {
                Serial.flush();
                usbBytesSinceFlush = 0;
            }
        } else {
            if (!Throttle::isWithinTimespanMs(lastProgressMs, USB_WRITE_TIMEOUT_MS))
                return false;
            delay(1);
        }
    }
    return true;
}

bool writeSerialAll(const char *text)
{
    return writeSerialAll((const uint8_t *)text, strlen(text), false);
}

bool pumpFileChunk(size_t &remaining)
{
    if (!exportFile || remaining == 0)
        return true;
    if (!ensureUsbTransferBuffer())
        return false;
    const int available = exportFile.available();
    if (available <= 0)
        return false;
    const size_t availableNow = (size_t)available;
    const size_t want = std::min(remaining, std::min(availableNow, USB_FILE_BUFFER_BYTES));
    const size_t got = exportFile.read(usbTransferBuffer, want);
    if (got == 0 || !writeSerialAll(usbTransferBuffer, got, true))
        return false;
    remaining -= got;
    return true;
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
    setRuntimeServiceHold(usbServiceHold, false);
    releaseUsbTransferBuffer();
    if (FSCom.exists(CURRENT_LOG))
        FSCom.remove(CURRENT_LOG);
    if (FSCom.exists(PREVIOUS_LOG))
        FSCom.remove(PREVIOUS_LOG);
    heltecV3DiagLog("LOGGER", "log cleared");
}

void heltecV3DiagRequestUsbExport()
{
    if (bleUiState.load() == BleExportState::DOWNLOADING) {
        exportState = UsbExportState::ERROR;
        heltecV3DiagLog("LOG_EXPORT", "usb rejected: BLE export active");
        return;
    }
    if (!ensureUsbTransferBuffer()) {
        exportRequested = false;
        exportPhase = 0;
        exportState = UsbExportState::ERROR;
        heltecV3DiagLog("LOG_EXPORT", "usb rejected: transfer buffer allocation failed");
        return;
    }

    closeExportFile();
    saveCounters();
    exportRequested = true;
    exportPhase = 1;
    exportState = UsbExportState::WAIT_USB;
    serialConnectedSinceMs = 0;
    exportBytesSent = 0;
    usbBytesSinceFlush = 0;
    setRuntimeServiceHold(usbServiceHold, true);
    heltecV3DiagLog("LOG_EXPORT", "requested serial=%u bytes=%u buf=%u chunk=%u", (bool)Serial ? 1U : 0U,
                    (unsigned)heltecV3DiagLogSize(), (unsigned)USB_FILE_BUFFER_BYTES, (unsigned)USB_WRITE_CHUNK_BYTES);
    exportPreviousRemaining = fileSize(PREVIOUS_LOG);
    exportCurrentRemaining = fileSize(CURRENT_LOG);
    exportTotalBytes = exportPreviousRemaining + exportCurrentRemaining;
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

void heltecV3DiagCancelBleExport()
{
    const bool wasActive = bleExportPhase != 0 && bleExportPhase != 5;
    resetBleExportTransfer();
    setRuntimeServiceHold(bleServiceHold, false);
    if (wasActive)
        setBleUiState(BleExportState::CANCELLED, 0);
}

bool heltecV3DiagBleExportActive()
{
    return bleUiState.load() == BleExportState::DOWNLOADING;
}

bool heltecV3DiagBleExportStatusVisible()
{
    return bleUiState.load() != BleExportState::READY;
}

const char *heltecV3DiagBleExportStatusText()
{
    switch (bleUiState.load()) {
    case BleExportState::DOWNLOADING:
        return "BT LOG DOWNLOAD";
    case BleExportState::COMPLETE:
        return "BT LOG DONE";
    case BleExportState::CANCELLED:
        return "BT LOG CANCEL";
    case BleExportState::ERROR:
        return "BT LOG ERROR";
    case BleExportState::READY:
    default:
        return "BT LOG READY";
    }
}

uint8_t heltecV3DiagBleExportProgress()
{
    return bleUiProgress.load();
}

uint32_t heltecV3DiagBleExportStatusSequence()
{
    return bleUiSequence.load();
}

bool heltecV3DiagStartBleExport()
{
    if (exportRequested) {
        setBleUiState(BleExportState::ERROR, 0);
        return false;
    }
    resetBleExportTransfer();
    heltecV3DiagLog("LOG_EXPORT", "requested ble=1 bytes=%u", (unsigned)heltecV3DiagLogSize());
    blePreviousRemaining = fileSize(PREVIOUS_LOG);
    bleCurrentRemaining = fileSize(CURRENT_LOG);
    const size_t totalBytes = blePreviousRemaining + bleCurrentRemaining;
    bleTotalBytes = totalBytes;
    blePayloadSent = 0;
    bleCrc = 0xffffffffU;
    setBleUiState(BleExportState::DOWNLOADING, 0);
    setRuntimeServiceHold(bleServiceHold, true);

    char exportTime[32] = {};
    makeTimestamp(exportTime, sizeof(exportTime));
    const uint32_t nodeNum = nodeDB ? nodeDB->getNodeNum() : 0;
    const char *longName = owner.long_name[0] ? owner.long_name : "--";
    const char *shortName = owner.short_name[0] ? owner.short_name : "--";
    const HeltecV3PowerStats power = heltecV3PowerMonitorStats();
    const HeltecV3DiagStats diagnostic = heltecV3DiagStats();
    char remaining[32] = "learning";
    if (power.estimateReady)
        heltecV3PowerFormatDuration(power.remainingSecs, remaining, sizeof(remaining));
    bleHeaderLength =
        (size_t)snprintf(bleHeader, sizeof(bleHeader),
                         "===JARNSEN_DIAG_LOG_BEGIN===\r\n# device=HELTEC_V3_REPEATER\r\n# "
                         "firmware=%s\r\n# build=%s\r\n"
                         "# node_id=!%08x\r\n# long_name=%s\r\n# short_name=%s\r\n# build_time=%s "
                         "%s\r\n# role=%s\r\n"
                         "# feature=%s\r\n# log_format=%u\r\n# export=%s\r\n# transport=BLE\r\n"
                         "LIVE | BATTERY | src=%s ina=%s vbus=%s %umV %u%% usb=%u charge=%u est=%s "
                         "current=%ldmA power=%umW used=%umAh/%umWh capacity=%umAh left=%umAh "
                         "confidence=%u%% cycles=%u on=%us listen=%us service=%us ble=%us disp=%us tx=%u "
                         "auto=%u manual=%u\r\n"
                         "# bytes=%u\r\n",
                         xstr(APP_VERSION), JARNSEN_V3_BUILD_SHA, (unsigned)nodeNum, longName, shortName, __DATE__, __TIME__,
                         diagRoleText(), DIAG_FEATURE_VERSION, (unsigned)DIAG_LOG_FORMAT, exportTime,
                         heltecV3PowerMonitorSourceText(), power.inaPresent ? "ACTIVE" : "OFF",
                         power.vbusValid ? "OK" : (power.inaPresent ? "MISSING" : "N/A"), (unsigned)power.voltageMv,
                         (unsigned)power.batteryPercent, power.usbPowered ? 1U : 0U, power.charging ? 1U : 0U, remaining,
                         (long)(power.currentValid ? power.currentMa : 0), (unsigned)(power.currentValid ? power.powerMw : 0),
                         (unsigned)power.consumedMah, (unsigned)power.consumedMwh, (unsigned)power.learnedCapacityMah,
                         (unsigned)power.remainingCapacityMah, (unsigned)power.capacityConfidence,
                         (unsigned)power.capacityCycles, (unsigned)power.measuredSecs, (unsigned)power.listenSecs,
                         (unsigned)power.serviceSecs, (unsigned)power.bleSecs, (unsigned)power.displaySecs,
                         (unsigned)power.positionTxCount, (unsigned)diagnostic.autoPositionSaveCount,
                         (unsigned)diagnostic.manualPositionSaveCount, (unsigned)totalBytes);
    if (bleHeaderLength >= sizeof(bleHeader)) {
        resetBleExportTransfer();
        setBleUiState(BleExportState::ERROR, 0);
        setRuntimeServiceHold(bleServiceHold, false);
        return false;
    }
    bleHeaderOffset = 0;
    bleFooterLength = 0;
    bleFooterOffset = 0;
    bleExportPhase = 1;
    return true;
}

size_t heltecV3DiagReadBleExport(uint8_t *buffer, size_t capacity)
{
    if (!buffer || capacity == 0 || bleExportPhase == 0 || bleExportPhase == 5)
        return 0;
    size_t output = 0;
    while (output < capacity && bleExportPhase != 5) {
        if (bleExportPhase == 1) {
            const size_t remaining = bleHeaderLength - bleHeaderOffset;
            const size_t count = std::min(remaining, capacity - output);
            memcpy(buffer + output, bleHeader + bleHeaderOffset, count);
            bleHeaderOffset += count;
            output += count;
            if (bleHeaderOffset == bleHeaderLength)
                bleExportPhase = 2;
        } else if (bleExportPhase == 2 || bleExportPhase == 3) {
            size_t &remaining = bleExportPhase == 2 ? blePreviousRemaining : bleCurrentRemaining;
            const char *path = bleExportPhase == 2 ? PREVIOUS_LOG : CURRENT_LOG;
            if (remaining == 0) {
                closeBleExportFile();
                bleExportPhase++;
                continue;
            }
            if (!bleExportFile && !openBleExportFile(path)) {
                remaining = 0;
                continue;
            }
            const size_t count = std::min(remaining, capacity - output);
            const size_t got = bleExportFile.read(buffer + output, count);
            if (got == 0) {
                resetBleExportTransfer();
                setBleUiState(BleExportState::ERROR, 0);
                setRuntimeServiceHold(bleServiceHold, false);
                return 0;
            }
            bleCrc = updateCrc32(bleCrc, buffer + output, got);
            remaining -= got;
            blePayloadSent += got;
            output += got;
            if (bleTotalBytes != 0) {
                const uint8_t progress = (uint8_t)std::min<size_t>(99U, (blePayloadSent * 100U) / bleTotalBytes);
                const uint8_t reported = (uint8_t)((progress / 10U) * 10U);
                if (reported > bleUiProgress.load())
                    setBleUiState(BleExportState::DOWNLOADING, reported);
            }
        } else if (bleExportPhase == 4) {
            if (bleFooterLength == 0) {
                bleFooterLength = (size_t)snprintf(bleFooter, sizeof(bleFooter),
                                                   "\r\n# payload_sent=%u\r\n# crc32=%08x\r\n"
                                                   "===JARNSEN_DIAG_LOG_END===\r\n",
                                                   (unsigned)blePayloadSent, (unsigned)(bleCrc ^ 0xffffffffU));
            }
            const size_t remaining = bleFooterLength - bleFooterOffset;
            const size_t count = std::min(remaining, capacity - output);
            memcpy(buffer + output, bleFooter + bleFooterOffset, count);
            bleFooterOffset += count;
            output += count;
            if (bleFooterOffset == bleFooterLength) {
                bleExportPhase = 5;
                closeBleExportFile();
                setBleUiState(BleExportState::COMPLETE, 100);
                setRuntimeServiceHold(bleServiceHold, false);
                heltecV3DiagLog("LOG_EXPORT", "ble complete sent=%u crc=%08x", (unsigned)blePayloadSent,
                                (unsigned)(bleCrc ^ 0xffffffffU));
            }
        }
    }
    return output;
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
        if (Throttle::isWithinTimespanMs(serialConnectedSinceMs, USB_SETTLE_MS))
            return;
        exportState = UsbExportState::SENDING;
    }

    if (!ensureUsbTransferBuffer()) {
        exportRequested = false;
        exportPhase = 0;
        exportState = UsbExportState::ERROR;
        setRuntimeServiceHold(usbServiceHold, false);
        heltecV3DiagLog("LOG_EXPORT", "usb failed: transfer buffer unavailable");
        return;
    }

    switch (exportPhase) {
    case 1: {
        // Capture a stable byte range only when the PC is actually ready. The
        // active log may have grown while the export waited for USB. The large
        // formatted header lives on the heap, not on the V3Service task stack.
        exportPreviousRemaining = fileSize(PREVIOUS_LOG);
        exportCurrentRemaining = fileSize(CURRENT_LOG);
        exportTotalBytes = exportPreviousRemaining + exportCurrentRemaining;
        exportBytesSent = 0;
        char exportTime[32] = {};
        makeTimestamp(exportTime, sizeof(exportTime));
        const uint32_t nodeNum = nodeDB ? nodeDB->getNodeNum() : 0;
        const char *longName = owner.long_name[0] ? owner.long_name : "--";
        const char *shortName = owner.short_name[0] ? owner.short_name : "--";
        const int headerLength = snprintf((char *)usbTransferBuffer, USB_FILE_BUFFER_BYTES,
                                          "\r\n===JARNSEN_DIAG_LOG_BEGIN===\r\n"
                                          "# device=HELTEC_V3_REPEATER\r\n# firmware=%s\r\n# build=%s\r\n"
                                          "# node_id=!%08x\r\n# long_name=%s\r\n# short_name=%s\r\n"
                                          "# build_time=%s %s\r\n# role=%s\r\n# feature=%s\r\n"
                                          "# log_format=%u\r\n# export=%s\r\n# bytes=%u\r\n",
                                          xstr(APP_VERSION), JARNSEN_V3_BUILD_SHA, (unsigned)nodeNum, longName, shortName,
                                          __DATE__, __TIME__, diagRoleText(), DIAG_FEATURE_VERSION, (unsigned)DIAG_LOG_FORMAT,
                                          exportTime, (unsigned)exportTotalBytes);
        if (headerLength <= 0 || (size_t)headerLength >= USB_FILE_BUFFER_BYTES ||
            !writeSerialAll(usbTransferBuffer, (size_t)headerLength, false)) {
            resetTransferToWait();
            break;
        }
        Serial.flush();
        usbBytesSinceFlush = 0;
        exportPhase = 2;
        if (!openExportFile(PREVIOUS_LOG))
            exportPhase = 3;
        break;
    }
    case 2:
        if (exportPreviousRemaining > 0 && exportFile) {
            if (!pumpFileChunk(exportPreviousRemaining))
                resetTransferToWait();
        } else {
            closeExportFile();
            exportPhase = 3;
        }
        break;
    case 3:
        if (exportCurrentRemaining == 0) {
            closeExportFile();
            exportPhase = 4;
            break;
        }
        if (!exportFile && !openExportFile(CURRENT_LOG)) {
            exportPhase = 4;
            break;
        }
        if (exportCurrentRemaining > 0) {
            if (!pumpFileChunk(exportCurrentRemaining))
                resetTransferToWait();
        } else {
            closeExportFile();
            exportPhase = 4;
        }
        break;
    case 4: {
        heltecV3MeshMonitorPrintSnapshot(Serial);
        const int footerLength = snprintf((char *)usbTransferBuffer, USB_FILE_BUFFER_BYTES,
                                          "\r\n# payload_sent=%u\r\n\r\n===JARNSEN_DIAG_LOG_END===\r\n",
                                          (unsigned)exportBytesSent);
        if (footerLength <= 0 || (size_t)footerLength >= USB_FILE_BUFFER_BYTES ||
            !writeSerialAll(usbTransferBuffer, (size_t)footerLength, false)) {
            resetTransferToWait();
            break;
        }
        // The end marker is only considered complete after USB CDC has drained.
        Serial.flush();
        usbBytesSinceFlush = 0;
        exportRequested = false;
        exportPhase = 0;
        exportState = exportBytesSent >= exportTotalBytes ? UsbExportState::COMPLETE : UsbExportState::ERROR;
        closeExportFile();
        setRuntimeServiceHold(usbServiceHold, false);
        releaseUsbTransferBuffer();
        heltecV3DiagLog("LOG_EXPORT", "%s sent=%u expected=%u",
                        exportState == UsbExportState::COMPLETE ? "complete" : "incomplete", (unsigned)exportBytesSent,
                        (unsigned)exportTotalBytes);
        break;
    }
    default:
        closeExportFile();
        exportRequested = false;
        exportPhase = 0;
        exportState = UsbExportState::ERROR;
        setRuntimeServiceHold(usbServiceHold, false);
        releaseUsbTransferBuffer();
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
bool heltecV3DiagStartBleExport()
{
    return false;
}
size_t heltecV3DiagReadBleExport(uint8_t *, size_t)
{
    return 0;
}
void heltecV3DiagCancelBleExport() {}
bool heltecV3DiagBleExportActive()
{
    return false;
}
bool heltecV3DiagBleExportStatusVisible()
{
    return false;
}
const char *heltecV3DiagBleExportStatusText()
{
    return "BT LOG READY";
}
uint8_t heltecV3DiagBleExportProgress()
{
    return 0;
}
uint32_t heltecV3DiagBleExportStatusSequence()
{
    return 0;
}

#endif
