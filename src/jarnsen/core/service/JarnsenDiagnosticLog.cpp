#include "jarnsen/core/service/JarnsenDiagnosticLog.h"
#include "jarnsen/core/service/JarnsenDiagnosticPolicy.h"

#include "FSCommon.h"
#include "NodeDB.h"
#include "PowerStatus.h"
#include "configuration.h"
#include "jarnsen/core/build/JarnsenBuildInfo.h"
#include "jarnsen/core/power/JarnsenBatteryLearning.h"
#include "jarnsen/core/runtime/JarnsenTakRepeaterPolicy.h"

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
        if (vsnprintf(detail, sizeof(detail), fmt, args) >= (int)sizeof(detail))
            diagnosticNoteTruncation();
        va_end(args);
    }
    if (detail[0])
        trackerDiagLog(event, "%s", detail);
    else
        trackerDiagLog(event);
}

void diagnosticLogV(const char *level, const char *fmt, va_list args)
{
    if (!fmt || !diagnosticConsoleLevelEnabled(level))
        return;
    char detail[224] = {};
    va_list copy;
    va_copy(copy, args);
    if (vsnprintf(detail, sizeof(detail), fmt, copy) >= (int)sizeof(detail))
        diagnosticNoteTruncation();
    va_end(copy);
    trackerDiagLog(level, "%s", detail);
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

bool diagnosticLogEnabled()
{
    return trackerDiagEnabled();
}
void diagnosticLogSetEnabled(bool enabled)
{
    trackerDiagSetEnabled(enabled);
}
size_t diagnosticLogSize()
{
    return trackerDiagLogSize();
}
void diagnosticLogClear()
{
    trackerDiagClear();
}
const char *diagnosticLogUsbExportStatusText()
{
    return trackerDiagUsbExportStatusText();
}
uint8_t diagnosticLogUsbExportProgress()
{
    return trackerDiagUsbExportProgress();
}

#else

namespace
{
constexpr const char *CURRENT_LOG = "/jarnsen_diag.log";
constexpr const char *PREVIOUS_LOG = "/jarnsen_diag.prev.log";
constexpr const char *DISABLED_MARKER = "/prefs/jarnsen-diag-disabled-v1";
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
bool loggingEnabled = true;
bool snapshotLocked = false;
ExportState exportState = ExportState::IDLE;
Print *exportOutput = nullptr;
File exportFile;
size_t exportPreviousRemaining = 0;
size_t exportCurrentRemaining = 0;
size_t exportTotalBytes = 0;
size_t exportBytesSent = 0;
uint32_t exportCrc = 0xffffffffU;
uint32_t exportRequestedAtMs = 0;
char exportHeader[2304] = {};
size_t exportHeaderLength = 0;
char exportFooter[160] = {};
size_t exportFooterLength = 0;

// HTTP and USB share one bounded snapshot lock; no heap-sized copy of logs.
enum class WebExportPhase : uint8_t { IDLE, HEADER, PREVIOUS, CURRENT, FOOTER, DONE, FAILED };
WebExportPhase webPhase = WebExportPhase::IDLE;
File webFile;
size_t webPreviousRemaining = 0;
size_t webCurrentRemaining = 0;
size_t webHeaderOffset = 0;
size_t webHeaderLength = 0;
size_t webFooterOffset = 0;
size_t webFooterLength = 0;
char webHeader[1280] = {};
char webFooter[128] = {};
uint32_t webCrc = 0xffffffffU;
size_t webBytesSent = 0;

bool webExportRunning()
{
    return webPhase == WebExportPhase::HEADER || webPhase == WebExportPhase::PREVIOUS || webPhase == WebExportPhase::CURRENT ||
           webPhase == WebExportPhase::FOOTER;
}

void releaseWebExport(WebExportPhase next)
{
    if (webFile)
        webFile.close();
    webPhase = next;
    snapshotLocked = false;
}

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

    const auto learned = batteryLearningStats();
    if (learned.supported) {
        char remaining[32] = "learning";
        if (learned.usbPowered)
            snprintf(remaining, sizeof(remaining), "usb");
        else if (learned.charging)
            snprintf(remaining, sizeof(remaining), "charging");
        else if (learned.estimateReady)
            batteryLearningFormatDuration(learned.remainingSecs, remaining, sizeof(remaining));

        snprintf(out, outSize,
                 "LIVE | BATTERY | state=%s voltage=%s soc=%s usb=%s charge=%s learn=soc_time "
                 "rate=%u.%03u%%/h observations=%u\r\n"
                 "LIVE | POWER | source=%s current=unsupported power=unsupported discharged=unsupported "
                 "remaining=%s capacity_mah=unsupported ina226=off lightSleep=unsupported deepSleep=unsupported\r\n",
                 batteryStateText(battery), voltage, soc, optionalBoolText(usb), optionalBoolText(charging),
                 (unsigned)(learned.dischargeRateMilliPercentPerHour / 1000U),
                 (unsigned)(learned.dischargeRateMilliPercentPerHour % 1000U), (unsigned)learned.observations, powerSourceText(),
                 remaining);
    } else {
        snprintf(out, outSize,
                 "LIVE | BATTERY | state=%s voltage=%s soc=%s usb=%s charge=%s learn=unsupported\r\n"
                 "LIVE | POWER | source=%s current=unsupported power=unsupported discharged=unsupported "
                 "remaining=unsupported lightSleep=unsupported deepSleep=unsupported\r\n",
                 batteryStateText(battery), voltage, soc, optionalBoolText(usb), optionalBoolText(charging), powerSourceText());
    }

    if (takRepeaterRoleActive()) {
        const auto repeater = takRepeaterStats();
        const size_t used = strlen(out);
        if (used < outSize) {
            char radioAge[24] = "unknown";
            if (repeater.lastRadioAgeSecs != UINT32_MAX)
                snprintf(radioAge, sizeof(radioAge), "%us", (unsigned)repeater.lastRadioAgeSecs);
            snprintf(out + used, outSize - used,
                     "LIVE | TAK_REPEATER | mode=%s rx=%u tx=%u fwd=%u radio_age=%s cu=%u.%u%% airtx=%u.%u%% "
                     "pos_tx=%u gps=%u fix=%u service=%u wlan=%u ls=%u wakes=%u watchdog=%u boot=%u reset=%u\r\n",
                     takRepeaterPositionModeKey(repeater.positionMode), (unsigned)repeater.rxPackets,
                     (unsigned)repeater.txPackets, (unsigned)repeater.forwardedPackets, radioAge,
                     (unsigned)(repeater.channelUtilizationX10 / 10U), (unsigned)(repeater.channelUtilizationX10 % 10U),
                     (unsigned)(repeater.txAirUtilizationX10 / 10U), (unsigned)(repeater.txAirUtilizationX10 % 10U),
                     (unsigned)repeater.positionTxCount, repeater.gpsConnected ? 1U : 0U, repeater.gpsFix ? 1U : 0U,
                     repeater.serviceActive ? 1U : 0U, repeater.wifiServiceActive ? 1U : 0U, (unsigned)repeater.lightSleepEntries,
                     (unsigned)repeater.lightSleepWakes, (unsigned)repeater.watchdogStage, (unsigned)repeater.bootCount,
                     (unsigned)repeater.resetReason);
        }
    }
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
    const size_t discardedBytes = fileSize(PREVIOUS_LOG);
    if (FSCom.exists(PREVIOUS_LOG) && !FSCom.remove(PREVIOUS_LOG))
        diagnosticNoteWrite(false);
    if (FSCom.exists(CURRENT_LOG)) {
        // A logging caller may already own spiLock; renameFile() would take it again.
        // Use the filesystem API directly, like open/remove above.
        if (FSCom.rename(CURRENT_LOG, PREVIOUS_LOG))
            diagnosticNoteRotation(discardedBytes);
        else
            diagnosticNoteWrite(false);
    }
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
    if (!file) {
        diagnosticNoteWrite(false);
        return;
    }
    const bool bodyWritten = file.write(reinterpret_cast<const uint8_t *>(line), length) == length;
    const bool newlineWritten = file.write(reinterpret_cast<const uint8_t *>("\n"), 1U) == 1U;
    file.flush();
    file.close();
    diagnosticNoteWrite(bodyWritten && newlineWritten);
}

void appendEvent(const char *event, const char *detail)
{
    if (!initialized || !loggingEnabled || !event)
        return;
    DiagnosticWriteScope scope;
    if (!scope)
        return;
    char line[384] = {};
    if (diagnosticFormatLine(line, sizeof(line), event, detail))
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
            if (countPayload) {
                exportCrc = diagnosticCrc32(exportCrc, data + offset, written);
                exportBytesSent += written;
            }
            offset += written;
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
    snprintf(detail, sizeof(detail), "usb error=%s sent=%u expected=%u", reason ? reason : "unknown", (unsigned)exportBytesSent,
             (unsigned)exportTotalBytes);
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
    diagnosticPolicyInit();
    loggingEnabled = !FSCom.exists(DISABLED_MARKER);
    initialized = true;
    if (loggingEnabled)
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
        if (vsnprintf(detail, sizeof(detail), fmt, args) >= (int)sizeof(detail))
            diagnosticNoteTruncation();
        va_end(args);
    }
    appendEvent(event, detail);
}

void diagnosticLogV(const char *level, const char *fmt, va_list args)
{
    if (!initialized || !fmt || !diagnosticConsoleLevelEnabled(level))
        return;
    char detail[256] = {};
    va_list copy;
    va_copy(copy, args);
    if (vsnprintf(detail, sizeof(detail), fmt, copy) >= (int)sizeof(detail))
        diagnosticNoteTruncation();
    va_end(copy);
    appendEvent(level && level[0] ? level : "LOG", detail);
}

void diagnosticLogRequestUsbExport(Print &output)
{
    diagnosticLogInit();
    if (webExportRunning())
        return;
    if (exportState == ExportState::PREPARE || exportState == ExportState::HEADER || exportState == ExportState::PREVIOUS ||
        exportState == ExportState::CURRENT || exportState == ExportState::FOOTER)
        return;

    closeExportFile();
    exportOutput = &output;
    exportBytesSent = 0;
    exportCrc = 0xffffffffU;
    exportPreviousRemaining = fileSize(PREVIOUS_LOG);
    exportCurrentRemaining = fileSize(CURRENT_LOG);
    exportTotalBytes = exportPreviousRemaining + exportCurrentRemaining;
    snapshotLocked = true;
    exportRequestedAtMs = millis();
    char snapshot[640] = {};
    if (!diagnosticSnapshotMetadata(snapshot, sizeof(snapshot), PREVIOUS_LOG, exportPreviousRemaining, CURRENT_LOG,
                                    exportCurrentRemaining)) {
        finishWithError("snapshot metadata overflow");
        return;
    }

    const uint32_t nodeNum = nodeDB ? nodeDB->getNodeNum() : 0U;
    const char *longName = owner.long_name[0] ? owner.long_name : "--";
    const char *shortName = owner.short_name[0] ? owner.short_name : "--";
    const unsigned region = config.has_lora ? (unsigned)config.lora.region : 0U;
    const unsigned hops = config.has_lora ? (unsigned)config.lora.hop_limit : 0U;
    const double frequency = config.has_lora ? (double)config.lora.override_frequency : 0.0;
    char livePower[768] = {};
    formatGenericLivePower(livePower, sizeof(livePower));

    exportHeaderLength = (size_t)snprintf(exportHeader, sizeof(exportHeader),
                                          "\r\n===JARNSEN_DIAG_LOG_BEGIN===\r\n"
                                          "# device=%s\r\n# firmware=%s\r\n# build=%u\r\n# sha=%s\r\n"
                                          "# node_id=!%08x\r\n# long_name=%s\r\n# short_name=%s\r\n"
                                          "# role=%s\r\n# lora_region=%u\r\n# lora_frequency=%.3f\r\n# lora_hops=%u\r\n"
                                          "# transport=USB\r\n# log_format=3\r\n# power_diag=1\r\n%s%s# bytes=%u\r\n",
                                          build::hardwareName, build::version, (unsigned)build::buildNumber, build::gitSha,
                                          (unsigned)nodeNum, longName, shortName, diagnosticRoleKey(), region, frequency, hops,
                                          livePower, snapshot, (unsigned)exportTotalBytes);
    exportFooterLength = (size_t)snprintf(exportFooter, sizeof(exportFooter),
                                          "\r\n# payload_sent=%u\r\n===JARNSEN_DIAG_LOG_END===\r\n", (unsigned)exportTotalBytes);
    if (exportHeaderLength >= sizeof(exportHeader) || exportFooterLength >= sizeof(exportFooter)) {
        finishWithError("metadata overflow");
        return;
    }

    exportState = ExportState::PREPARE;
    diagnosticLog("LOG_EXPORT", "requested bytes=%u", (unsigned)exportTotalBytes);
}

bool diagnosticLogUsbExportPending()
{
    return exportState == ExportState::PREPARE || exportState == ExportState::HEADER || exportState == ExportState::PREVIOUS ||
           exportState == ExportState::CURRENT || exportState == ExportState::FOOTER;
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
        if (exportBytesSent != exportTotalBytes) {
            finishWithError("payload length mismatch");
            return;
        }
        exportFooterLength =
            (size_t)snprintf(exportFooter, sizeof(exportFooter),
                             "\r\n# payload_sent=%u\r\n# crc32=%08x\r\n# transfer_complete=1\r\n===JARNSEN_DIAG_LOG_END===\r\n",
                             (unsigned)exportBytesSent, (unsigned)(exportCrc ^ 0xffffffffU));
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

bool diagnosticLogEnabled()
{
    diagnosticLogInit();
    return loggingEnabled;
}

void diagnosticLogSetEnabled(bool enabled)
{
    diagnosticLogInit();
    if (loggingEnabled == enabled)
        return;
    loggingEnabled = enabled;
    if (enabled) {
        if (FSCom.exists(DISABLED_MARKER))
            FSCom.remove(DISABLED_MARKER);
        appendEvent("LOGGER", "enabled");
    } else {
        File marker = FSCom.open(DISABLED_MARKER, FILE_O_WRITE);
        if (marker) {
            const uint8_t value = 1U;
            marker.write(&value, 1U);
            marker.flush();
            marker.close();
        }
    }
}

size_t diagnosticLogSize()
{
    return fileSize(PREVIOUS_LOG) + fileSize(CURRENT_LOG);
}

void diagnosticLogClear()
{
    if (webExportRunning())
        return;
    closeExportFile();
    snapshotLocked = false;
    exportState = ExportState::IDLE;
    exportOutput = nullptr;
    if (FSCom.exists(PREVIOUS_LOG))
        FSCom.remove(PREVIOUS_LOG);
    if (FSCom.exists(CURRENT_LOG))
        FSCom.remove(CURRENT_LOG);
    if (loggingEnabled)
        appendEvent("LOGGER", "cleared");
}

// JARNSEN_SHARED_HTTP_LOG_SNAPSHOT_V1
// HTTP reads exactly the bytes present when export began. File rotation is
// paused, concurrent USB export is rejected and memory stays bounded.
bool diagnosticLogStartWebExport()
{
    diagnosticLogInit();
    if (webExportRunning() || diagnosticLogUsbExportPending())
        return false;
    releaseWebExport(WebExportPhase::IDLE);
    webPreviousRemaining = fileSize(PREVIOUS_LOG);
    webCurrentRemaining = fileSize(CURRENT_LOG);
    webHeaderOffset = 0;
    webFooterOffset = 0;
    const size_t total = webPreviousRemaining + webCurrentRemaining;
    snapshotLocked = true;
    webCrc = 0xffffffffU;
    webBytesSent = 0;
    char snapshot[640] = {};
    if (!diagnosticSnapshotMetadata(snapshot, sizeof(snapshot), PREVIOUS_LOG, webPreviousRemaining, CURRENT_LOG,
                                    webCurrentRemaining)) {
        releaseWebExport(WebExportPhase::FAILED);
        return false;
    }
    const uint32_t nodeId = nodeDB ? nodeDB->getNodeNum() : 0U;
    const int headLength = snprintf(webHeader, sizeof(webHeader),
                                    "===JARNSEN_DIAG_LOG_BEGIN===\r\n"
                                    "# device=%s\r\n# firmware=%s\r\n# build=%u\r\n# sha=%s\r\n"
                                    "# node_id=!%08x\r\n# transport=HTTP\r\n# log_format=3\r\n%s# bytes=%u\r\n",
                                    build::hardwareName, build::version, (unsigned)build::buildNumber, build::gitSha,
                                    (unsigned)nodeId, snapshot, (unsigned)total);
    const int footLength =
        snprintf(webFooter, sizeof(webFooter), "\r\n# payload_sent=%u\r\n===JARNSEN_DIAG_LOG_END===\r\n", (unsigned)total);
    if (headLength < 0 || footLength < 0 || (size_t)headLength >= sizeof(webHeader) || (size_t)footLength >= sizeof(webFooter)) {
        releaseWebExport(WebExportPhase::FAILED);
        return false;
    }
    webHeaderLength = (size_t)headLength;
    webFooterLength = (size_t)footLength;
    snapshotLocked = true;
    webPhase = WebExportPhase::HEADER;
    return true;
}

size_t diagnosticLogReadWebExport(uint8_t *buffer, size_t capacity)
{
    if (!buffer || !capacity || !webExportRunning())
        return 0;
    size_t produced = 0;
    while (produced < capacity && webExportRunning()) {
        if (webPhase == WebExportPhase::HEADER || webPhase == WebExportPhase::FOOTER) {
            const bool header = webPhase == WebExportPhase::HEADER;
            const char *source = header ? webHeader : webFooter;
            size_t &offset = header ? webHeaderOffset : webFooterOffset;
            const size_t length = header ? webHeaderLength : webFooterLength;
            const size_t bytes = std::min(length - offset, capacity - produced);
            memcpy(buffer + produced, source + offset, bytes);
            produced += bytes;
            offset += bytes;
            if (offset == length) {
                if (header)
                    webPhase = webPreviousRemaining ? WebExportPhase::PREVIOUS : WebExportPhase::CURRENT;
                else
                    releaseWebExport(WebExportPhase::DONE);
            }
            continue;
        }
        const bool previous = webPhase == WebExportPhase::PREVIOUS;
        size_t &remaining = previous ? webPreviousRemaining : webCurrentRemaining;
        const char *path = previous ? PREVIOUS_LOG : CURRENT_LOG;
        if (!remaining) {
            if (webFile)
                webFile.close();
            if (!previous) {
                webFooterLength = (size_t)snprintf(
                    webFooter, sizeof(webFooter),
                    "\r\n# payload_sent=%u\r\n# crc32=%08x\r\n# transfer_complete=1\r\n===JARNSEN_DIAG_LOG_END===\r\n",
                    (unsigned)webBytesSent, (unsigned)(webCrc ^ 0xffffffffU));
            }
            webPhase = previous ? WebExportPhase::CURRENT : WebExportPhase::FOOTER;
            continue;
        }
        if (!webFile)
            webFile = FSCom.open(path, FILE_O_READ);
        if (!webFile) {
            releaseWebExport(WebExportPhase::FAILED);
            break;
        }
        const size_t wanted = std::min(remaining, capacity - produced);
        const size_t count = webFile.read(buffer + produced, wanted);
        if (!count) {
            releaseWebExport(WebExportPhase::FAILED);
            break;
        }
        webCrc = diagnosticCrc32(webCrc, buffer + produced, count);
        webBytesSent += count;
        produced += count;
        remaining -= count;
    }
    return produced;
}

void diagnosticLogCancelWebExport()
{
    if (webExportRunning())
        releaseWebExport(WebExportPhase::IDLE);
}

const char *diagnosticLogUsbExportStatusText()
{
    switch (exportState) {
    case ExportState::PREPARE:
        return "WARTET";
    case ExportState::HEADER:
    case ExportState::PREVIOUS:
    case ExportState::CURRENT:
    case ExportState::FOOTER:
        return "EXPORT";
    case ExportState::COMPLETE:
        return "FERTIG";
    case ExportState::ERROR:
        return "FEHLER";
    case ExportState::IDLE:
    default:
        return "BEREIT";
    }
}

uint8_t diagnosticLogUsbExportProgress()
{
    if (exportState == ExportState::COMPLETE)
        return 100U;
    if (exportTotalBytes == 0)
        return diagnosticLogUsbExportPending() ? 0U : 100U;
    const size_t percent = (exportBytesSent * 100U) / exportTotalBytes;
    return (uint8_t)std::min<size_t>(100U, percent);
}

#endif

} // namespace jarnsen
