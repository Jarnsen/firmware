#include "TrackerDiagnosticLog.h"
#include "JarnsenBuildGenerated.h"
#include "JarnsenDiagMetadataGenerated.h"
#include "NodeDB.h"
#include "vehicle/TrackerPowerMonitor.h"

#if defined(HELTEC_TRACKER_V1_1)

#include "FSCommon.h"
#include "NodeDB.h"
#include "configuration.h"
#include "gps/RTC.h"

#include <Arduino.h>
#include <Preferences.h>
#include <algorithm>
#include <atomic>
#include <cstdarg>
#include <cstdio>
#include <cstring>
#include <ctime>

namespace
{
constexpr const char *PREF_NAMESPACE = "trkV11Diag";
constexpr const char *CURRENT_LOG = "/tracker_diag.log";
constexpr const char *PREVIOUS_LOG = "/tracker_diag.prev.log";
constexpr size_t MAX_LOG_BYTES = 256U * 1024U;
constexpr size_t USB_FILE_CHUNK_BYTES = 1024U;
constexpr size_t USB_WRITE_CHUNK_BYTES = 512U;
constexpr uint32_t USB_SETTLE_MS = 1000UL;
constexpr uint32_t USB_DISCONNECT_GRACE_MS = 1000UL;
constexpr uint32_t USB_WRITE_TIMEOUT_MS = 5000UL;

const char *trackerDiagRoleText()
{
    return config.device.role == meshtastic_Config_DeviceConfig_Role_TAK_TRACKER ? "TAK_TRACKER" : "TAK";
}

void formatTrackerLiveBattery(char *out, size_t outSize)
{
    if (!out || outSize == 0)
        return;
    const TrackerPowerStats power = trackerPowerMonitorStats();
    char remaining[32] = "learning";
    if (power.estimateReady)
        trackerPowerFormatDuration(power.remainingSecs, remaining, sizeof(remaining));
    const char *inaState = !power.inaConfigured ? "OFF" : (!power.inaPresent ? "MISSING" : (power.inaValid ? "OK" : "WAIT"));
    const char *vbusState =
        !power.inaConfigured || !power.inaPresent ? "N/A" : (!power.inaValid ? "WAIT" : (power.vbusValid ? "OK" : "MISSING"));
    const int32_t current = power.currentMilliAmpsX10;
    const int32_t currentAbs = current < 0 ? -current : current;
    snprintf(out, outSize,
             "LIVE | BATTERY | %umV %u%% usb=%u charge=%u est=%s ina=%s vbus=%s current=%s%ld.%ldmA "
             "total=%u.%umAh sleepEst=%u.%umAh lightSleep=%us deepSleep=%us cap=%umAh left=%umAh conf=%u%% "
             "cycles=%u on=%us move=%us park=%us gps=%us ble=%us disp=%us tx=%u\r\n",
             (unsigned)power.voltageMv, (unsigned)power.batteryPercent, power.usbPowered ? 1U : 0U,
             power.charging ? 1U : 0U, remaining, inaState, vbusState, current < 0 ? "-" : "",
             (long)(currentAbs / 10), (long)(currentAbs % 10), (unsigned)(power.dischargedMahX10 / 10U),
             (unsigned)(power.dischargedMahX10 % 10U), (unsigned)(power.sleepEstimatedMahX10 / 10U),
             (unsigned)(power.sleepEstimatedMahX10 % 10U), (unsigned)power.lightSleepSecs, (unsigned)power.deepSleepSecs,
             (unsigned)power.learnedCapacityMah, (unsigned)power.remainingCapacityMah, (unsigned)power.capacityConfidence,
             (unsigned)power.capacityCycles, (unsigned)power.measuredSecs, (unsigned)power.movingSecs,
             (unsigned)power.parkedSecs, (unsigned)power.gnssSecs, (unsigned)power.bleSecs, (unsigned)power.displaySecs,
             (unsigned)power.positionTxCount);
}

enum class UsbExportState : uint8_t { IDLE = 0, PREPARE, SENDING, FINISH, COMPLETE, ERROR };
enum class UsbSnapshotPhase : uint8_t { NONE = 0, PREVIOUS, CURRENT };
enum class BleExportState : uint8_t { READY = 0, DOWNLOADING, COMPLETE, CANCELLED, ERROR };

bool initialized = false;
bool loggingEnabled = true;
bool exportRequested = false;
File exportFile;
UsbExportState exportState = UsbExportState::IDLE;
UsbSnapshotPhase exportSnapshotPhase = UsbSnapshotPhase::NONE;
uint32_t serialConnectedSinceMs = 0;
uint32_t serialLostSinceMs = 0;
size_t exportPreviousRemaining = 0;
size_t exportCurrentRemaining = 0;
size_t exportTotalBytes = 0;
size_t exportBytesSent = 0;
char usbHeader[1600] = {};
size_t usbHeaderLength = 0;
char usbFooter[160] = {};
size_t usbFooterLength = 0;
File bleExportFile;
uint8_t bleExportPhase = 0;
size_t blePreviousRemaining = 0;
size_t bleCurrentRemaining = 0;
size_t blePayloadSent = 0;
size_t bleTotalBytes = 0;
uint32_t bleCrc = 0xffffffffU;
char bleHeader[1600] = {};
size_t bleHeaderLength = 0;
size_t bleHeaderOffset = 0;
char bleFooter[160] = {};
size_t bleFooterLength = 0;
size_t bleFooterOffset = 0;
std::atomic<BleExportState> bleUiState{BleExportState::READY};
std::atomic<uint8_t> bleUiProgress{0};
std::atomic<uint32_t> bleUiSequence{0};

bool usbExportSessionActive()
{
    return exportState == UsbExportState::PREPARE || exportState == UsbExportState::SENDING ||
           exportState == UsbExportState::FINISH;
}

bool snapshotFilesLocked()
{
    return usbExportSessionActive() || bleUiState.load() == BleExportState::DOWNLOADING;
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
    // Keep the files backing an active snapshot stable. New diagnostic lines
    // may still append to CURRENT_LOG, but the fixed snapshot byte counts keep
    // them out of the in-flight export. Rotation resumes after the session.
    if (snapshotFilesLocked())
        return;

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

void clearUsbTransferRuntime()
{
    closeExportFile();
    exportSnapshotPhase = UsbSnapshotPhase::NONE;
    serialConnectedSinceMs = 0;
    serialLostSinceMs = 0;
}

void failUsbExport(const char *reason)
{
    const size_t sent = exportBytesSent;
    const size_t expected = exportTotalBytes;
    clearUsbTransferRuntime();
    exportRequested = false;
    exportState = UsbExportState::ERROR;
    trackerDiagLog("LOG_EXPORT", "usb error=%s sent=%u expected=%u", reason ? reason : "unknown", (unsigned)sent,
                   (unsigned)expected);
}

bool writeSerialAll(const uint8_t *data, size_t length, bool countPayload)
{
    size_t offset = 0;
    uint32_t lastProgressMs = millis();
    while (offset < length) {
        const size_t remaining = length - offset;
        const size_t chunk = std::min(remaining, USB_WRITE_CHUNK_BYTES);
        const size_t written = Serial.write(data + offset, chunk);
        if (written > 0) {
            offset += written;
            if (countPayload)
                exportBytesSent += written;
            lastProgressMs = millis();
            // Yield to the Meshtastic scheduler/watchdog without forcing a
            // blocking USB flush for every tiny fragment.
            yield();
        } else {
            if ((uint32_t)(millis() - lastProgressMs) >= USB_WRITE_TIMEOUT_MS)
                return false;
            delay(1);
            yield();
        }
    }
    return true;
}

bool writeSerialAll(const char *data, size_t length, bool countPayload)
{
    return writeSerialAll(reinterpret_cast<const uint8_t *>(data), length, countPayload);
}

bool writeSerialAll(const char *text)
{
    return writeSerialAll(text, strlen(text), false);
}

bool pumpFileChunk(size_t &remaining)
{
    if (remaining == 0)
        return true;
    if (!exportFile)
        return false;

    uint8_t buffer[USB_FILE_CHUNK_BYTES];
    const size_t want = std::min(remaining, sizeof(buffer));
    const size_t got = exportFile.read(buffer, want);
    if (got == 0)
        return false;
    if (!writeSerialAll(buffer, got, true))
        return false;
    remaining -= got;
    yield();
    return true;
}
} // namespace

extern "C" bool meshtasticTrackerDiagUsbSerialLockActive()
{
    return usbExportSessionActive();
}

void trackerDiagInit()
{
    if (initialized)
        return;

    Preferences prefs;
    if (prefs.begin(PREF_NAMESPACE, true)) {
        loggingEnabled = prefs.getBool("enabled", true);
        prefs.end();
    }
    initialized = true;

    if (loggingEnabled)
        trackerDiagLog("LOGGER", "initialized enabled=1 size=%u", (unsigned)trackerDiagLogSize());
}

bool trackerDiagEnabled()
{
    return loggingEnabled;
}

void trackerDiagSetEnabled(bool enabled)
{
    loggingEnabled = enabled;
    Preferences prefs;
    if (prefs.begin(PREF_NAMESPACE, false)) {
        prefs.putBool("enabled", enabled);
        prefs.end();
    }

    // Record the OFF transition before suppressing subsequent events. The ON
    // transition is naturally recorded after enabling.
    if (enabled)
        trackerDiagLog("LOGGER", "enabled=1");
    else {
        const bool saved = loggingEnabled;
        loggingEnabled = true;
        trackerDiagLog("LOGGER", "enabled=0");
        loggingEnabled = saved;
    }
}

size_t trackerDiagLogSize()
{
    return fileSize(PREVIOUS_LOG) + fileSize(CURRENT_LOG);
}

void trackerDiagClear()
{
    if (usbExportSessionActive() || bleUiState.load() == BleExportState::DOWNLOADING) {
        trackerDiagLog("LOGGER", "clear ignored while export active");
        return;
    }

    clearUsbTransferRuntime();
    exportRequested = false;
    exportState = UsbExportState::IDLE;
    exportPreviousRemaining = 0;
    exportCurrentRemaining = 0;
    exportTotalBytes = 0;
    exportBytesSent = 0;
    usbHeaderLength = 0;
    usbFooterLength = 0;
    if (FSCom.exists(CURRENT_LOG))
        FSCom.remove(CURRENT_LOG);
    if (FSCom.exists(PREVIOUS_LOG))
        FSCom.remove(PREVIOUS_LOG);
    if (loggingEnabled)
        trackerDiagLog("LOGGER", "log cleared");
}

void trackerDiagLog(const char *event, const char *fmt, ...)
{
    if (!initialized || !loggingEnabled || !event)
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

void trackerDiagLogPosition(const char *event, int32_t latitudeI, int32_t longitudeI, uint32_t ageSecs, uint8_t sats, bool fresh)
{
    trackerDiagLog(event, "lat=%.7f lon=%.7f age=%us sats=%u fresh=%u", latitudeI * 1e-7, longitudeI * 1e-7, (unsigned)ageSecs,
                   (unsigned)sats, fresh ? 1U : 0U);
}

void trackerDiagRequestUsbExport()
{
    // Button/service callbacks may fire more than once while a selection is
    // still held. Never reinitialize an active session or reset its offsets.
    if (exportRequested || usbExportSessionActive())
        return;

    clearUsbTransferRuntime();
    exportRequested = true;
    exportState = UsbExportState::PREPARE;
    exportBytesSent = 0;
    usbHeaderLength = 0;
    usbFooterLength = 0;

    trackerDiagLog("LOG_EXPORT", "requested usb=%u bytes=%u", (bool)Serial ? 1U : 0U, (unsigned)trackerDiagLogSize());

    // Freeze the snapshot boundaries exactly once. New lines may append while
    // the transfer runs, but these counters ensure they are not part of this
    // session and can never move the current export offset.
    exportPreviousRemaining = fileSize(PREVIOUS_LOG);
    exportCurrentRemaining = fileSize(CURRENT_LOG);
    exportTotalBytes = exportPreviousRemaining + exportCurrentRemaining;

    char exportTime[32] = {};
    makeTimestamp(exportTime, sizeof(exportTime));
    const uint32_t nodeNum = nodeDB ? nodeDB->getNodeNum() : 0;
    const char *longName = owner.long_name[0] ? owner.long_name : "--";
    const char *shortName = owner.short_name[0] ? owner.short_name : "--";
    char usbLiveBattery[768] = {};
    formatTrackerLiveBattery(usbLiveBattery, sizeof(usbLiveBattery));
    usbHeaderLength = (size_t)snprintf(usbHeader, sizeof(usbHeader),
                                       "\r\n===JARNSEN_DIAG_LOG_BEGIN===\r\n"
                                       "# device=HELTEC_TRACKER_V1.1\r\n# firmware=%s\r\n# build=%s\r\n"
                                       "# node_id=!%08x\r\n# long_name=%s\r\n# short_name=%s\r\n"
                                       "# build_time=%s %s\r\n# role=%s\r\n# feature=%s\r\n"
                                       "# log_format=%u\r\n# export=%s\r\n# transport=USB\r\n%s# bytes=%u\r\n",
                                       xstr(APP_VERSION), JARNSEN_BUILD_SHA, (unsigned)nodeNum, longName, shortName, __DATE__, __TIME__,
                                       trackerDiagRoleText(), JARNSEN_DIAG_FEATURE_VERSION, (unsigned)JARNSEN_DIAG_LOG_FORMAT, exportTime,
                                       usbLiveBattery, (unsigned)exportTotalBytes);
    usbFooterLength = (size_t)snprintf(usbFooter, sizeof(usbFooter),
                                       "\r\n# payload_sent=%u\r\n===JARNSEN_DIAG_LOG_END===\r\n",
                                       (unsigned)exportTotalBytes);
    if (usbHeaderLength >= sizeof(usbHeader) || usbFooterLength >= sizeof(usbFooter)) {
        failUsbExport("metadata overflow");
        return;
    }
}

bool trackerDiagUsbExportPending()
{
    return exportRequested || usbExportSessionActive();
}

const char *trackerDiagUsbExportStatusText()
{
    switch (exportState) {
    case UsbExportState::PREPARE:
        return (bool)Serial ? "PC erkannt - warte" : "PC/Downloader verbinden";
    case UsbExportState::SENDING:
        return "Uebertrage Log...";
    case UsbExportState::FINISH:
        return "Schliesse Export...";
    case UsbExportState::COMPLETE:
        return "Uebertragung fertig";
    case UsbExportState::ERROR:
        return "Uebertragung FEHLER";
    case UsbExportState::IDLE:
    default:
        return "Bereit";
    }
}

uint8_t trackerDiagUsbExportProgress()
{
    if (exportState == UsbExportState::COMPLETE)
        return 100;
    if ((exportState != UsbExportState::SENDING && exportState != UsbExportState::FINISH) || exportTotalBytes == 0)
        return 0;
    const size_t pct = (exportBytesSent * 100U) / exportTotalBytes;
    return (uint8_t)(pct > 99U ? 99U : pct);
}

void trackerDiagCancelBleExport()
{
    const bool wasActive = bleExportPhase != 0 && bleExportPhase != 5;
    resetBleExportTransfer();
    if (wasActive)
        setBleUiState(BleExportState::CANCELLED, 0);
}

bool trackerDiagBleExportActive()
{
    return bleUiState.load() == BleExportState::DOWNLOADING;
}

bool trackerDiagBleExportStatusVisible()
{
    return bleUiState.load() != BleExportState::READY;
}

const char *trackerDiagBleExportStatusText()
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

uint8_t trackerDiagBleExportProgress()
{
    return bleUiProgress.load();
}

uint32_t trackerDiagBleExportStatusSequence()
{
    return bleUiSequence.load();
}

bool trackerDiagStartBleExport()
{
    if (exportRequested || usbExportSessionActive()) {
        setBleUiState(BleExportState::ERROR, 0);
        return false;
    }
    resetBleExportTransfer();
    trackerDiagLog("LOG_EXPORT", "requested ble=1 bytes=%u", (unsigned)trackerDiagLogSize());
    blePreviousRemaining = fileSize(PREVIOUS_LOG);
    bleCurrentRemaining = fileSize(CURRENT_LOG);
    const size_t totalBytes = blePreviousRemaining + bleCurrentRemaining;
    bleTotalBytes = totalBytes;
    blePayloadSent = 0;
    bleCrc = 0xffffffffU;
    setBleUiState(BleExportState::DOWNLOADING, 0);

    char exportTime[32] = {};
    makeTimestamp(exportTime, sizeof(exportTime));
    const uint32_t nodeNum = nodeDB ? nodeDB->getNodeNum() : 0;
    const char *longName = owner.long_name[0] ? owner.long_name : "--";
    const char *shortName = owner.short_name[0] ? owner.short_name : "--";
    char liveBattery[768] = {};
    formatTrackerLiveBattery(liveBattery, sizeof(liveBattery));
    bleHeaderLength = (size_t)snprintf(bleHeader, sizeof(bleHeader),
                                       "===JARNSEN_DIAG_LOG_BEGIN===\r\n# device=HELTEC_TRACKER_V1.1\r\n# "
                                       "firmware=%s\r\n# build=%s\r\n"
                                       "# node_id=!%08x\r\n# long_name=%s\r\n# short_name=%s\r\n# build_time=%s "
                                       "%s\r\n# role=%s\r\n"
                                       "# feature=%s\r\n# log_format=%u\r\n# export=%s\r\n# transport=BLE\r\n%s# bytes=%u\r\n",
                                       xstr(APP_VERSION), JARNSEN_BUILD_SHA, (unsigned)nodeNum, longName, shortName, __DATE__,
                                       __TIME__, trackerDiagRoleText(), JARNSEN_DIAG_FEATURE_VERSION,
                                       (unsigned)JARNSEN_DIAG_LOG_FORMAT, exportTime, liveBattery, (unsigned)totalBytes);
    if (bleHeaderLength >= sizeof(bleHeader)) {
        resetBleExportTransfer();
        setBleUiState(BleExportState::ERROR, 0);
        return false;
    }
    bleHeaderOffset = 0;
    bleFooterLength = 0;
    bleFooterOffset = 0;
    bleExportPhase = 1;
    return true;
}

size_t trackerDiagReadBleExport(uint8_t *buffer, size_t capacity)
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
                trackerDiagLog("LOG_EXPORT", "ble complete sent=%u crc=%08x", (unsigned)blePayloadSent,
                               (unsigned)(bleCrc ^ 0xffffffffU));
            }
        }
    }
    return output;
}

void trackerDiagPumpUsbExport()
{
    if (!exportRequested || !usbExportSessionActive())
        return;

    const uint32_t now = millis();

    if (exportState == UsbExportState::PREPARE) {
        // Wait for one stable CDC session before the single BEGIN marker. Once
        // BEGIN has been emitted this state is never entered again for the same
        // request.
        if (!(bool)Serial) {
            serialConnectedSinceMs = 0;
            return;
        }
        if (serialConnectedSinceMs == 0) {
            serialConnectedSinceMs = now ? now : 1;
            return;
        }
        if ((uint32_t)(now - serialConnectedSinceMs) < USB_SETTLE_MS)
            return;

        if (!writeSerialAll(usbHeader, usbHeaderLength, false)) {
            failUsbExport("header write timeout");
            return;
        }
        Serial.flush();
        exportSnapshotPhase = exportPreviousRemaining > 0 ? UsbSnapshotPhase::PREVIOUS : UsbSnapshotPhase::CURRENT;
        exportState = UsbExportState::SENDING;
        serialLostSinceMs = 0;
        return;
    }

    // A brief CDC status wobble may pause the same session, but it must never
    // rewind it. A real disconnect ends the session as ERROR rather than
    // emitting a second BEGIN and starting over.
    if (!(bool)Serial) {
        if (serialLostSinceMs == 0)
            serialLostSinceMs = now ? now : 1;
        if ((uint32_t)(now - serialLostSinceMs) >= USB_DISCONNECT_GRACE_MS)
            failUsbExport("serial disconnected");
        return;
    }
    serialLostSinceMs = 0;

    if (exportState == UsbExportState::SENDING) {
        if (exportSnapshotPhase == UsbSnapshotPhase::PREVIOUS) {
            if (exportPreviousRemaining == 0) {
                closeExportFile();
                exportSnapshotPhase = UsbSnapshotPhase::CURRENT;
                return;
            }
            if (!exportFile && !openExportFile(PREVIOUS_LOG)) {
                failUsbExport("previous snapshot unavailable");
                return;
            }
            if (!pumpFileChunk(exportPreviousRemaining)) {
                failUsbExport("previous snapshot read/write failed");
                return;
            }
            if (exportPreviousRemaining == 0) {
                closeExportFile();
                exportSnapshotPhase = UsbSnapshotPhase::CURRENT;
            }
            return;
        }

        if (exportSnapshotPhase == UsbSnapshotPhase::CURRENT) {
            if (exportCurrentRemaining == 0) {
                closeExportFile();
                exportSnapshotPhase = UsbSnapshotPhase::NONE;
                exportState = UsbExportState::FINISH;
                return;
            }
            if (!exportFile && !openExportFile(CURRENT_LOG)) {
                failUsbExport("current snapshot unavailable");
                return;
            }
            if (!pumpFileChunk(exportCurrentRemaining)) {
                failUsbExport("current snapshot read/write failed");
                return;
            }
            if (exportCurrentRemaining == 0) {
                closeExportFile();
                exportSnapshotPhase = UsbSnapshotPhase::NONE;
                exportState = UsbExportState::FINISH;
            }
            return;
        }

        failUsbExport("invalid snapshot phase");
        return;
    }

    if (exportState == UsbExportState::FINISH) {
        if (exportBytesSent != exportTotalBytes) {
            failUsbExport("payload length mismatch");
            return;
        }
        if (!writeSerialAll(usbFooter, usbFooterLength, false)) {
            failUsbExport("footer write timeout");
            return;
        }
        Serial.flush();

        const size_t sent = exportBytesSent;
        const size_t expected = exportTotalBytes;
        clearUsbTransferRuntime();
        exportRequested = false;
        exportState = UsbExportState::COMPLETE;
        trackerDiagLog("LOG_EXPORT", "complete sent=%u expected=%u", (unsigned)sent, (unsigned)expected);
        return;
    }
}

#endif // HELTEC_TRACKER_V1_1