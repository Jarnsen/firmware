#include "jarnsen/core/service/JarnsenDiagnosticLog.h"

#include "FSCommon.h"
#include "NodeDB.h"
#include "PowerStatus.h"
#include "configuration.h"
#include "jarnsen/core/build/JarnsenBuildInfo.h"

#if defined(HELTEC_TRACKER_V1_1)
#include "vehicle/TrackerDiagnosticLog.h"
#endif

#include <algorithm>
#include <cstdarg>
#include <cstdio>
#include <cstring>

namespace jarnsen
{

#if defined(HELTEC_TRACKER_V1_1)

void diagnosticLogInit()
{
    trackerDiagInit();
}

void diagnosticLog(const char *event, const char *fmt, ...)
{
    if (!event)
        return;
    char detail[224] = {};
    if (fmt && fmt[0]) {
        va_list args;
        va_start(args, fmt);
        vsnprintf(detail, sizeof(detail), fmt, args);
        va_end(args);
    }
    if (detail[0])
        trackerDiagLog(event, "%s", detail);
    else
        trackerDiagLog(event);
}

void diagnosticLogV(const char *, const char *, va_list)
{
    // Tracker V1.1 already records its richer purpose-built diagnostics.
}

void diagnosticLogRequestUsbExport(Print &)
{
    trackerDiagRequestUsbExport();
}

void diagnosticLogPumpUsbExport()
{
    trackerDiagPumpUsbExport();
}

bool diagnosticLogUsbExportPending()
{
    return trackerDiagUsbExportPending();
}

#else

namespace
{
constexpr const char *CURRENT_LOG = "/jarnsen_diag.log";
constexpr const char *PREVIOUS_LOG = "/jarnsen_diag.prev.log";
constexpr size_t MAX_LOG_BYTES = 256U * 1024U;
constexpr size_t FILE_CHUNK_BYTES = 1024U;
constexpr size_t WRITE_CHUNK_BYTES = 512U;
constexpr uint32_t EXPORT_SETTLE_MS = 750U;
constexpr uint32_t WRITE_TIMEOUT_MS = 5000U;

enum class ExportState : uint8_t {
    IDLE = 0,
    PREPARE,
    HEADER,
    PREVIOUS,
    CURRENT,
    FOOTER,
    COMPLETE,
    ERROR,
};

bool initialized = false;
bool snapshotLocked = false;
ExportState exportState = ExportState::IDLE;
Print *exportOutput = nullptr;
File exportFile;
size_t exportPreviousRemaining = 0;
size_t exportCurrentRemaining = 0;
size_t exportTotalBytes = 0;
size_t exportBytesSent = 0;
uint32_t exportRequestedAtMs = 0;
char exportHeader[1280] = {};
size_t exportHeaderLength = 0;
char exportFooter[160] = {};
size_t exportFooterLength = 0;

const char *optionalBoolText(meshtastic::OptionalBool value)
{
    switch (value) {
    case meshtastic::OptFalse:
        return "0";
    case meshtastic::OptTrue:
        return "1";
    case meshtastic::OptUnknown:
    default:
        return "unknown";
    }
}

const char *batteryStateText(meshtastic::OptionalBool value)
{
    switch (value) {
    case meshtastic::OptFalse:
        return "absent";
    case meshtastic::OptTrue:
        return "present";
    case meshtastic::OptUnknown:
    default:
        return "unknown";
    }
}

const char *powerSourceText()
{
#if defined(HAS_PMU)
    return "pmu";
#elif defined(BATTERY_PIN)
    return "adc";
#else
    return "power-status";
#endif
}

void formatGenericLivePower(char *out, size_t outSize)
{
    if (!out || outSize == 0)
        return;

    meshtastic::OptionalBool battery = meshtastic::OptUnknown;
    meshtastic::OptionalBool usb = meshtastic::OptUnknown;
    meshtastic::OptionalBool charging = meshtastic::OptUnknown;
    char voltage[24] = "unknown";
    char soc[16] = "unknown";

    if (powerStatus && powerStatus->isInitialized()) {
        battery = powerStatus->getHasBatteryState();
        usb = powerStatus->getHasUSBState();
        charging = powerStatus->getIsChargingState();

        if (battery == meshtastic::OptTrue) {
            snprintf(voltage, sizeof(voltage), "%dmV", powerStatus->getBatteryVoltageMv());
            snprintf(soc, sizeof(soc), "%u%%", (unsigned)powerStatus->getBatteryChargePercent());
        } else if (battery == meshtastic::OptFalse) {
            snprintf(voltage, sizeof(voltage), "unsupported");
            snprintf(soc, sizeof(soc), "unsupported");
        }
    }

    snprintf(out, outSize,
             "LIVE | BATTERY | state=%s voltage=%s soc=%s usb=%s charge=%s learn=unsupported\r\n"
             "LIVE | POWER | source=%s current=unsupported power=unsupported discharged=unsupported "
             "remaining=unsupported lightSleep=unsupported deepSleep=unsupported\r\n",
             batteryStateText(battery), voltage, soc, optionalBoolText(usb), optionalBoolText(charging), powerSourceText());
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

void closeExportFile()
{
    if (exportFile)
        exportFile.close();
}

void rotateIfNeeded(size_t incomingBytes)
{
    if (snapshotLocked)
        return;
    const size_t current = fileSize(CURRENT_LOG);
    if (current + incomingBytes <= MAX_LOG_BYTES)
        return;
    if (FSCom.exists(PREVIOUS_LOG))
        FSCom.remove(PREVIOUS_LOG);
    if (FSCom.exists(CURRENT_LOG))
        renameFile(CURRENT_LOG, PREVIOUS_LOG);
}

void appendLine(const char *line)
{
    if (!line || !line[0])
        return;
    const size_t length = strlen(line);
    rotateIfNeeded(length + 1U);
#if defined(ARCH_NRF52) || defined(ARCH_NRF54L15)
    // Adafruit LittleFS uses FILE_O_WRITE as append/create and seeks to EOF on open.
    File file = FSCom.open(CURRENT_LOG, FILE_O_WRITE);
#else
    File file = FSCom.open(CURRENT_LOG, "a");
#endif
    if (!file)
        return;
    file.write(reinterpret_cast<const uint8_t *>(line), length);
    file.write(reinterpret_cast<const uint8_t *>("\n"), 1U);
    file.flush();
    file.close();
}

void appendEvent(const char *event, const char *detail)
{
    if (!initialized || !event)
        return;
    char line[384] = {};
    const unsigned long uptime = millis() / 1000UL;
    if (detail && detail[0])
        snprintf(line, sizeof(line), "UPTIME+%lus | %-14s | %s", uptime, event, detail);
    else
        snprintf(line, sizeof(line), "UPTIME+%lus | %s", uptime, event);
    appendLine(line);
}

bool writeAll(const uint8_t *data, size_t length, bool countPayload)
{
    if (!exportOutput)
        return false;
    size_t offset = 0;
    uint32_t lastProgress = millis();
    while (offset < length) {
        const size_t chunk = std::min(WRITE_CHUNK_BYTES, length - offset);
        const size_t written = exportOutput->write(data + offset, chunk);
        if (written > 0) {
            offset += written;
            if (countPayload)
                exportBytesSent += written;
            lastProgress = millis();
            yield();
        } else {
            if ((uint32_t)(millis() - lastProgress) >= WRITE_TIMEOUT_MS)
                return false;
            delay(1);
            yield();
        }
    }
    return true;
}

bool writeAll(const char *text, size_t length, bool countPayload = false)
{
    return writeAll(reinterpret_cast<const uint8_t *>(text), length, countPayload);
}

bool openExportFile(const char *path)
{
    closeExportFile();
    exportFile = FSCom.open(path, FILE_O_READ);
    return (bool)exportFile;
}

void finishWithError(const char *reason)
{
    closeExportFile();
    snapshotLocked = false;
    exportState = ExportState::ERROR;
    char detail[160] = {};
    snprintf(detail, sizeof(detail), "usb error=%s sent=%u expected=%u", reason ? reason : "unknown",
             (unsigned)exportBytesSent, (unsigned)exportTotalBytes);
    appendEvent("LOG_EXPORT", detail);
}

bool pumpFile(const char *path, size_t &remaining)
{
    if (remaining == 0)
        return true;
    if (!exportFile && !openExportFile(path))
        return false;
    uint8_t buffer[FILE_CHUNK_BYTES];
    const size_t want = std::min(sizeof(buffer), remaining);
    const size_t got = exportFile.read(buffer, want);
    if (got == 0)
        return false;
    if (!writeAll(buffer, got, true))
        return false;
    remaining -= got;
    if (remaining == 0)
        closeExportFile();
    return true;
}

} // namespace

void diagnosticLogInit()
{
    if (initialized)
        return;
    initialized = true;
    diagnosticLog("LOGGER", "initialized board=%s version=%s build=%u", build::hardwareName, build::version,
                  (unsigned)build::buildNumber);
}

void diagnosticLog(const char *event, const char *fmt, ...)
{
    if (!initialized || !event)
        return;
    char detail[256] = {};
    if (fmt && fmt[0]) {
        va_list args;
        va_start(args, fmt);
        vsnprintf(detail, sizeof(detail), fmt, args);
        va_end(args);
    }
    appendEvent(event, detail);
}

void diagnosticLogV(const char *level, const char *fmt, va_list args)
{
    if (!initialized || !fmt)
        return;
    char detail[256] = {};
    va_list copy;
    va_copy(copy, args);
    vsnprintf(detail, sizeof(detail), fmt, copy);
    va_end(copy);
    appendEvent(level && level[0] ? level : "LOG", detail);
}

void diagnosticLogRequestUsbExport(Print &output)
{
    diagnosticLogInit();
    if (exportState == ExportState::PREPARE || exportState == ExportState::HEADER ||
        exportState == ExportState::PREVIOUS || exportState == ExportState::CURRENT || exportState == ExportState::FOOTER)
        return;

    closeExportFile();
    exportOutput = &output;
    exportBytesSent = 0;
    exportPreviousRemaining = fileSize(PREVIOUS_LOG);
    exportCurrentRemaining = fileSize(CURRENT_LOG);
    exportTotalBytes = exportPreviousRemaining + exportCurrentRemaining;
    snapshotLocked = true;
    exportRequestedAtMs = millis();

    const uint32_t nodeNum = nodeDB ? nodeDB->getNodeNum() : 0U;
    const char *longName = owner.long_name[0] ? owner.long_name : "--";
    const char *shortName = owner.short_name[0] ? owner.short_name : "--";
    const unsigned role = config.has_device ? (unsigned)config.device.role : 0U;
    const unsigned region = config.has_lora ? (unsigned)config.lora.region : 0U;
    const unsigned hops = config.has_lora ? (unsigned)config.lora.hop_limit : 0U;
    const double frequency = config.has_lora ? (double)config.lora.override_frequency : 0.0;
    char livePower[512] = {};
    formatGenericLivePower(livePower, sizeof(livePower));

    exportHeaderLength = (size_t)snprintf(
        exportHeader, sizeof(exportHeader),
        "\r\n===JARNSEN_DIAG_LOG_BEGIN===\r\n"
        "# device=%s\r\n# firmware=%s\r\n# build=%u\r\n# sha=%s\r\n"
        "# node_id=!%08x\r\n# long_name=%s\r\n# short_name=%s\r\n"
        "# role=%u\r\n# lora_region=%u\r\n# lora_frequency=%.3f\r\n# lora_hops=%u\r\n"
        "# transport=USB\r\n# log_format=2\r\n# power_diag=1\r\n%s# bytes=%u\r\n",
        build::hardwareName, build::version, (unsigned)build::buildNumber, build::gitSha, (unsigned)nodeNum, longName,
        shortName, role, region, frequency, hops, livePower, (unsigned)exportTotalBytes);
    exportFooterLength = (size_t)snprintf(exportFooter, sizeof(exportFooter),
                                           "\r\n# payload_sent=%u\r\n===JARNSEN_DIAG_LOG_END===\r\n",
                                           (unsigned)exportTotalBytes);
    if (exportHeaderLength >= sizeof(exportHeader) || exportFooterLength >= sizeof(exportFooter)) {
        finishWithError("metadata overflow");
        return;
    }

    exportState = ExportState::PREPARE;
    diagnosticLog("LOG_EXPORT", "requested bytes=%u", (unsigned)exportTotalBytes);
}

bool diagnosticLogUsbExportPending()
{
    return exportState == ExportState::PREPARE || exportState == ExportState::HEADER ||
           exportState == ExportState::PREVIOUS || exportState == ExportState::CURRENT || exportState == ExportState::FOOTER;
}

void diagnosticLogPumpUsbExport()
{
    if (!diagnosticLogUsbExportPending())
        return;

    if (exportState == ExportState::PREPARE) {
        if ((uint32_t)(millis() - exportRequestedAtMs) < EXPORT_SETTLE_MS)
            return;
        exportState = ExportState::HEADER;
    }

    if (exportState == ExportState::HEADER) {
        if (!writeAll(exportHeader, exportHeaderLength)) {
            finishWithError("header write timeout");
            return;
        }
        exportState = exportPreviousRemaining > 0 ? ExportState::PREVIOUS : ExportState::CURRENT;
        return;
    }

    if (exportState == ExportState::PREVIOUS) {
        if (!pumpFile(PREVIOUS_LOG, exportPreviousRemaining)) {
            finishWithError("previous log read/write");
            return;
        }
        if (exportPreviousRemaining == 0)
            exportState = ExportState::CURRENT;
        return;
    }

    if (exportState == ExportState::CURRENT) {
        if (!pumpFile(CURRENT_LOG, exportCurrentRemaining)) {
            finishWithError("current log read/write");
            return;
        }
        if (exportCurrentRemaining == 0)
            exportState = ExportState::FOOTER;
        return;
    }

    if (exportState == ExportState::FOOTER) {
        if (!writeAll(exportFooter, exportFooterLength)) {
            finishWithError("footer write timeout");
            return;
        }
        closeExportFile();
        snapshotLocked = false;
        exportState = ExportState::COMPLETE;
        exportOutput = nullptr;
        diagnosticLog("LOG_EXPORT", "usb complete sent=%u", (unsigned)exportBytesSent);
    }
}

#endif

} // namespace jarnsen
