#include "TrackerDiagnosticLog.h"

#if defined(HELTEC_TRACKER_V1_1)

#include "FSCommon.h"
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

bool initialized = false;
bool loggingEnabled = true;
bool exportRequested = false;
uint8_t exportPhase = 0; // 0 idle, 1 begin, 2 previous, 3 current, 4 end
File exportFile;

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
        snprintf(out, outSize, "%04d-%02d-%02dT%02d:%02d:%02dZ", tmUtc.tm_year + 1900, tmUtc.tm_mon + 1,
                 tmUtc.tm_mday, tmUtc.tm_hour, tmUtc.tm_min, tmUtc.tm_sec);
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
        Serial.write(buffer, got);
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
    if (exportFile)
        exportFile.close();
    exportRequested = false;
    exportPhase = 0;
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

void trackerDiagLogPosition(const char *event, int32_t latitudeI, int32_t longitudeI, uint32_t ageSecs, uint8_t sats,
                            bool fresh)
{
    trackerDiagLog(event, "lat=%.7f lon=%.7f age=%us sats=%u fresh=%u", latitudeI * 1e-7, longitudeI * 1e-7,
                   (unsigned)ageSecs, (unsigned)sats, fresh ? 1U : 0U);
}

void trackerDiagRequestUsbExport()
{
    exportRequested = true;
    exportPhase = 1;
    if (exportFile)
        exportFile.close();
    trackerDiagLog("LOG_EXPORT", "requested usb=%u bytes=%u", (bool)Serial ? 1U : 0U, (unsigned)trackerDiagLogSize());
}

bool trackerDiagUsbExportPending()
{
    return exportRequested;
}

void trackerDiagPumpUsbExport()
{
    if (!exportRequested || !(bool)Serial)
        return;

    switch (exportPhase) {
    case 1:
        Serial.println("===TRACKER_LOG_BEGIN===");
        Serial.printf("# bytes=%u\n", (unsigned)trackerDiagLogSize());
        exportPhase = 2;
        if (!openExportFile(PREVIOUS_LOG))
            exportPhase = 3;
        break;

    case 2:
        if (exportFile && exportFile.available() > 0) {
            pumpFileChunk();
        } else {
            if (exportFile)
                exportFile.close();
            exportPhase = 3;
        }
        break;

    case 3:
        if (!exportFile && !openExportFile(CURRENT_LOG)) {
            exportPhase = 4;
            break;
        }
        if (exportFile.available() > 0) {
            pumpFileChunk();
        } else {
            exportFile.close();
            exportPhase = 4;
        }
        break;

    case 4:
        Serial.println("===TRACKER_LOG_END===");
        Serial.flush();
        exportRequested = false;
        exportPhase = 0;
        if (exportFile)
            exportFile.close();
        trackerDiagLog("LOG_EXPORT", "complete");
        break;

    default:
        exportRequested = false;
        exportPhase = 0;
        if (exportFile)
            exportFile.close();
        break;
    }
}

#endif // HELTEC_TRACKER_V1_1
