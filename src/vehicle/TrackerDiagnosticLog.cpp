#include "TrackerDiagnosticLog.h"
#include "JarnsenBuildGenerated.h"
#include "JarnsenDiagMetadataGenerated.h"
#include "NodeDB.h"

#if defined(HELTEC_TRACKER_V1_1)

#include "FSCommon.h"
#include "NodeDB.h"
#include "configuration.h"
#include "gps/RTC.h"

#include <Arduino.h>
#include <Preferences.h>
#include <cstdarg>
#include <cstdio>
#include <ctime>

namespace
{
constexpr const char *PREF_NAMESPACE = "trkV11Diag";
constexpr const char *CURRENT_LOG = "/tracker_diag.log";
constexpr const char *PREVIOUS_LOG = "/tracker_diag.prev.log";
constexpr size_t MAX_LOG_BYTES = 256U * 1024U;
constexpr uint32_t USB_SETTLE_MS = 1000UL;
constexpr uint32_t USB_WRITE_TIMEOUT_MS = 5000UL;

const char *trackerDiagRoleText()
{
    return config.device.role == meshtastic_Config_DeviceConfig_Role_TAK_TRACKER ? "TAK_TRACKER" : "TAK";
}

enum class UsbExportState : uint8_t { IDLE = 0, WAIT_USB, SENDING, COMPLETE, ERROR };

bool initialized = false;
bool loggingEnabled = true;
bool exportRequested = false;
uint8_t exportPhase = 0; // 0 idle, 1 begin, 2 previous, 3 current, 4 end
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

bool writeSerialAll(const uint8_t *data, size_t length, bool countPayload)
{
    size_t offset = 0;
    uint32_t lastProgressMs = millis();
    while (offset < length) {
        if (!(bool)Serial)
            return false;
        const size_t written = Serial.write(data + offset, length - offset);
        if (written > 0) {
            offset += written;
            if (countPayload)
                exportBytesSent += written;
            lastProgressMs = millis();
        } else {
            if ((uint32_t)(millis() - lastProgressMs) >= USB_WRITE_TIMEOUT_MS)
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

bool pumpFileChunk()
{
    if (!exportFile)
        return true;

    uint8_t buffer[128];
    const int available = exportFile.available();
    if (available <= 0)
        return true;
    const size_t want = (size_t)available < sizeof(buffer) ? (size_t)available : sizeof(buffer);
    const size_t got = exportFile.read(buffer, want);
    return got == 0 || writeSerialAll(buffer, got, true);
}
} // namespace

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
    closeExportFile();
    exportRequested = true;
    exportPhase = 1;
    exportState = UsbExportState::WAIT_USB;
    serialConnectedSinceMs = 0;
    exportBytesSent = 0;

    trackerDiagLog("LOG_EXPORT", "requested usb=%u bytes=%u", (bool)Serial ? 1U : 0U, (unsigned)trackerDiagLogSize());
    // Snapshot after recording the request, so the size shown to the user and
    // the downloader includes the request breadcrumb itself.
    exportTotalBytes = trackerDiagLogSize();
}

bool trackerDiagUsbExportPending()
{
    return exportRequested;
}

const char *trackerDiagUsbExportStatusText()
{
    switch (exportState) {
    case UsbExportState::WAIT_USB:
        return (bool)Serial ? "PC erkannt - warte" : "PC/Downloader verbinden";
    case UsbExportState::SENDING:
        return "Uebertrage Log...";
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
    if (exportState != UsbExportState::SENDING || exportTotalBytes == 0)
        return 0;
    const size_t pct = (exportBytesSent * 100U) / exportTotalBytes;
    return (uint8_t)(pct > 99U ? 99U : pct);
}

void trackerDiagPumpUsbExport()
{
    if (!exportRequested)
        return;

    // If Windows/USB disappears during a transfer, do not silently finish a
    // truncated file. Return to WAIT_USB and restart from byte zero on the
    // next stable connection.
    if (!(bool)Serial) {
        if (exportState == UsbExportState::SENDING)
            resetTransferToWait();
        else {
            exportState = UsbExportState::WAIT_USB;
            serialConnectedSinceMs = 0;
        }
        return;
    }

    // Give pyserial/Windows enough time to finish opening the native CDC port.
    // The previous implementation could emit the begin marker immediately and
    // the PC downloader then cleared it from the input buffer as it started.
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
        // Start on a fresh line even if normal serial logging was in progress.
        {
            char exportTime[32] = {};
            makeTimestamp(exportTime, sizeof(exportTime));
            const uint32_t nodeNum = nodeDB ? nodeDB->getNodeNum() : 0;
            const meshtastic_NodeInfoLite *self = nodeDB ? nodeDB->getMeshNode(nodeNum) : nullptr;
            const char *longName = self && self->long_name[0] ? self->long_name : "--";
            const char *shortName = self && self->short_name[0] ? self->short_name : "--";
            char header[768] = {};
            snprintf(header, sizeof(header),
                     "\r\n===JARNSEN_DIAG_LOG_BEGIN===\r\n"
                     "# device=HELTEC_TRACKER_V1.1\r\n# firmware=%s\r\n# build=%s\r\n"
                     "# node_id=!%08x\r\n# long_name=%s\r\n# short_name=%s\r\n"
                     "# build_time=%s %s\r\n# role=%s\r\n# feature=%s\r\n"
                     "# log_format=%u\r\n# export=%s\r\n# bytes=%u\r\n",
                     xstr(APP_VERSION), JARNSEN_BUILD_SHA, (unsigned)nodeNum, longName, shortName, __DATE__, __TIME__,
                     trackerDiagRoleText(), JARNSEN_DIAG_FEATURE_VERSION, (unsigned)JARNSEN_DIAG_LOG_FORMAT, exportTime,
                     (unsigned)exportTotalBytes);
            if (!writeSerialAll(header)) {
                resetTransferToWait();
                break;
            }
        }
        Serial.flush();
        exportPhase = 2;
        if (!openExportFile(PREVIOUS_LOG))
            exportPhase = 3;
        break;

    case 2:
        if (exportFile && exportFile.available() > 0) {
            if (!pumpFileChunk())
                resetTransferToWait();
        } else {
            closeExportFile();
            exportPhase = 3;
        }
        break;

    case 3:
        if (!exportFile && !openExportFile(CURRENT_LOG)) {
            exportPhase = 4;
            break;
        }
        if (exportFile.available() > 0) {
            if (!pumpFileChunk())
                resetTransferToWait();
        } else {
            closeExportFile();
            exportPhase = 4;
        }
        break;

    case 4:
        {
            char footer[112] = {};
            snprintf(footer, sizeof(footer), "\r\n# payload_sent=%u\r\n\r\n===JARNSEN_DIAG_LOG_END===\r\n",
                     (unsigned)exportBytesSent);
            if (!writeSerialAll(footer)) {
                resetTransferToWait();
                break;
            }
        }
        Serial.flush();
        exportRequested = false;
        exportPhase = 0;
        exportState = exportBytesSent >= exportTotalBytes ? UsbExportState::COMPLETE : UsbExportState::ERROR;
        closeExportFile();
        trackerDiagLog("LOG_EXPORT", "%s sent=%u expected=%u",
                       exportState == UsbExportState::COMPLETE ? "complete" : "incomplete", (unsigned)exportBytesSent,
                       (unsigned)exportTotalBytes);
        break;

    default:
        closeExportFile();
        exportRequested = false;
        exportPhase = 0;
        exportState = UsbExportState::ERROR;
        trackerDiagLog("LOG_EXPORT", "invalid phase");
        break;
    }
}

#endif // HELTEC_TRACKER_V1_1
