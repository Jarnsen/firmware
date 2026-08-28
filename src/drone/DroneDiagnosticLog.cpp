#include "drone/DroneDiagnosticLog.h"

#if defined(HELTEC_TRACKER_V1_1) && defined(JARNSEN_DRONE_REPEATER_BUILD)

#include "FSCommon.h"
#include "drone/DroneMeshHealth.h"
#include "drone/DronePowerMonitor.h"
#include "drone/DroneSystemHealth.h"
#include "gps/RTC.h"
#include "vehicle/JarnsenBuildInfo.h"

#include <Arduino.h>
#include <algorithm>
#include <cstdarg>
#include <cstdio>
#include <cstring>
#include <ctime>

namespace
{
constexpr const char *CURRENT_LOG = "/drone_diag.log";
constexpr const char *PREVIOUS_LOG = "/drone_diag.prev.log";
constexpr size_t MAX_LOG_BYTES = 128U * 1024U;
constexpr size_t IO_CHUNK = 384U;

bool initialized = false;

enum class UsbState : uint8_t { IDLE = 0, PREPARE, HEADER, PREVIOUS, CURRENT, FOOTER, DONE, ERROR };
UsbState usbState = UsbState::IDLE;
File usbFile;
size_t usbPreviousBytes = 0;
size_t usbCurrentBytes = 0;
size_t usbExpectedBytes = 0;
size_t usbPayloadSent = 0;
size_t usbHeaderOffset = 0;
size_t usbFooterOffset = 0;
char usbHeader[1024] = {};
size_t usbHeaderLength = 0;
char usbFooter[192] = {};
size_t usbFooterLength = 0;

bool bleActive = false;
File bleFile;
uint8_t blePhase = 0;
size_t blePreviousBytes = 0;
size_t bleCurrentBytes = 0;
size_t blePreviousSent = 0;
size_t bleCurrentSent = 0;
size_t bleHeaderOffset = 0;
size_t bleFooterOffset = 0;
char bleHeader[1024] = {};
size_t bleHeaderLength = 0;
char bleFooter[192] = {};
size_t bleFooterLength = 0;

size_t fileSize(const char *path)
{
    File file = FSCom.open(path, FILE_O_READ);
    if (!file)
        return 0;
    const size_t size = file.size();
    file.close();
    return size;
}

bool snapshotLocked()
{
    return usbState != UsbState::IDLE && usbState != UsbState::DONE && usbState != UsbState::ERROR || bleActive;
}

void rotateIfNeeded(size_t incoming)
{
    if (snapshotLocked())
        return;
    if (fileSize(CURRENT_LOG) + incoming <= MAX_LOG_BYTES)
        return;
    if (FSCom.exists(PREVIOUS_LOG))
        FSCom.remove(PREVIOUS_LOG);
    if (FSCom.exists(CURRENT_LOG))
        FSCom.rename(CURRENT_LOG, PREVIOUS_LOG);
}

void makeTimestamp(char *out, size_t outSize)
{
    const uint32_t epoch = getValidTime(RTCQualityDevice);
    if (epoch != 0) {
        time_t raw = (time_t)epoch;
        struct tm utc = {};
        gmtime_r(&raw, &utc);
        snprintf(out, outSize, "%04d-%02d-%02dT%02d:%02d:%02dZ", utc.tm_year + 1900, utc.tm_mon + 1, utc.tm_mday,
                 utc.tm_hour, utc.tm_min, utc.tm_sec);
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

size_t buildHeader(char *out, size_t outSize, size_t payloadBytes)
{
    const DronePowerStats power = dronePowerMonitorStats();
    const DroneMeshHealthSummary mesh = droneMeshHealthSummary();
    const DroneSystemHealthStats health = droneSystemHealthStats();
    return (size_t)snprintf(
        out, outSize,
        "===JARNSEN_DIAG_LOG_BEGIN===\r\n"
        "# device=HELTEC_TRACKER_V1.1\r\n"
        "# profile=DRONE_REPEATER\r\n"
        "# build=%.8s\r\n"
        "# bytes=%u\r\n"
        "# power=%s usb=%u battery=%u percent=%u voltage_mv=%u usb_drops=%u usb_restores=%u\r\n"
        "# mesh_nodes=%u active15m=%u direct15m=%u rx1h=%u rx_total=%u\r\n"
        "# health=%s reset=%s boots=%u crashes=%u min_heap=%u gps_recovery=%u ble_recovery=%u lora_recovery=%u\r\n"
        "# counters pos_tx=%u lora_rx=%u lora_tx=%u relay_tx=%u gps_s=%u ble_s=%u display_s=%u\r\n",
        JARNSEN_BUILD_SHA, (unsigned)payloadBytes, dronePowerSourceText(), power.usbPowered ? 1U : 0U,
        power.hasBattery ? 1U : 0U, (unsigned)power.batteryPercent, (unsigned)power.voltageMv,
        (unsigned)power.usbDropCount, (unsigned)power.usbRestoreCount, (unsigned)mesh.observedNodes,
        (unsigned)mesh.active15m, (unsigned)mesh.direct15m, (unsigned)mesh.rx1h, (unsigned)mesh.totalRx,
        droneSystemHealthStatusText(), droneSystemHealthResetReasonText(), (unsigned)health.bootCount,
        (unsigned)health.crashResetCount, (unsigned)health.minFreeHeap, (unsigned)health.gpsRecoveryCount,
        (unsigned)health.bleRecoveryCount, (unsigned)health.loraRecoveryCount, (unsigned)power.positionTxCount,
        (unsigned)power.loraRxCount, (unsigned)power.loraTxCount, (unsigned)power.relayTxCount,
        (unsigned)power.gpsSecs, (unsigned)power.bleSecs, (unsigned)power.displaySecs);
}

size_t buildFooter(char *out, size_t outSize, size_t payloadSent)
{
    return (size_t)snprintf(out, outSize, "\r\n# payload_sent=%u\r\n===JARNSEN_DIAG_LOG_END===\r\n", (unsigned)payloadSent);
}

void closeUsbFile()
{
    if (usbFile)
        usbFile.close();
}

bool openUsbFile(const char *path)
{
    closeUsbFile();
    usbFile = FSCom.open(path, FILE_O_READ);
    return (bool)usbFile;
}

void failUsb()
{
    closeUsbFile();
    usbState = UsbState::ERROR;
}

size_t serialWriteChunk(const uint8_t *data, size_t length)
{
    if (!data || length == 0)
        return 0;
    const size_t chunk = std::min(length, IO_CHUNK);
    return Serial.write(data, chunk);
}

void closeBleFile()
{
    if (bleFile)
        bleFile.close();
}

bool openBleFile(const char *path)
{
    closeBleFile();
    bleFile = FSCom.open(path, FILE_O_READ);
    return (bool)bleFile;
}
}

void droneDiagInit()
{
    if (initialized)
        return;
    initialized = true;
    droneDiagLog("BOOT", "build=%.8s profile=DRONE_REPEATER power=%s reset=%s", JARNSEN_BUILD_SHA, dronePowerSourceText(),
                 droneSystemHealthResetReasonText());
}

void droneDiagTick()
{
    if (!initialized)
        droneDiagInit();

    if (usbState == UsbState::IDLE || usbState == UsbState::DONE || usbState == UsbState::ERROR)
        return;
    if (!Serial)
        return;

    switch (usbState) {
    case UsbState::PREPARE:
        usbPreviousBytes = fileSize(PREVIOUS_LOG);
        usbCurrentBytes = fileSize(CURRENT_LOG);
        usbExpectedBytes = usbPreviousBytes + usbCurrentBytes;
        usbPayloadSent = 0;
        usbHeaderOffset = 0;
        usbFooterOffset = 0;
        usbHeaderLength = buildHeader(usbHeader, sizeof(usbHeader), usbExpectedBytes);
        if (usbHeaderLength >= sizeof(usbHeader)) {
            failUsb();
            break;
        }
        usbState = UsbState::HEADER;
        break;

    case UsbState::HEADER: {
        const size_t written = serialWriteChunk((const uint8_t *)usbHeader + usbHeaderOffset, usbHeaderLength - usbHeaderOffset);
        usbHeaderOffset += written;
        if (usbHeaderOffset >= usbHeaderLength) {
            if (usbPreviousBytes != 0 && openUsbFile(PREVIOUS_LOG))
                usbState = UsbState::PREVIOUS;
            else if (usbCurrentBytes != 0 && openUsbFile(CURRENT_LOG))
                usbState = UsbState::CURRENT;
            else
                usbState = UsbState::FOOTER;
        }
        break;
    }

    case UsbState::PREVIOUS:
    case UsbState::CURRENT: {
        uint8_t buffer[IO_CHUNK] = {};
        const size_t expected = usbState == UsbState::PREVIOUS ? usbPreviousBytes : usbCurrentBytes;
        const size_t phaseSent = usbState == UsbState::PREVIOUS ? usbPayloadSent : usbPayloadSent - usbPreviousBytes;
        const size_t remaining = expected > phaseSent ? expected - phaseSent : 0;
        if (remaining == 0) {
            closeUsbFile();
            if (usbState == UsbState::PREVIOUS && usbCurrentBytes != 0 && openUsbFile(CURRENT_LOG))
                usbState = UsbState::CURRENT;
            else
                usbState = UsbState::FOOTER;
            break;
        }
        const size_t got = usbFile.read(buffer, std::min(sizeof(buffer), remaining));
        if (got == 0) {
            failUsb();
            break;
        }
        const size_t written = serialWriteChunk(buffer, got);
        if (written != got) {
            failUsb();
            break;
        }
        usbPayloadSent += written;
        break;
    }

    case UsbState::FOOTER: {
        if (usbFooterLength == 0) {
            usbFooterLength = buildFooter(usbFooter, sizeof(usbFooter), usbPayloadSent);
            if (usbFooterLength >= sizeof(usbFooter)) {
                failUsb();
                break;
            }
        }
        const size_t written = serialWriteChunk((const uint8_t *)usbFooter + usbFooterOffset, usbFooterLength - usbFooterOffset);
        usbFooterOffset += written;
        if (usbFooterOffset >= usbFooterLength) {
            Serial.flush();
            usbState = UsbState::DONE;
        }
        break;
    }

    default:
        break;
    }
}

void droneDiagLog(const char *event, const char *fmt, ...)
{
    char timestamp[32] = {};
    makeTimestamp(timestamp, sizeof(timestamp));
    char detail[320] = {};
    if (fmt && fmt[0]) {
        va_list args;
        va_start(args, fmt);
        vsnprintf(detail, sizeof(detail), fmt, args);
        va_end(args);
    }
    char line[420] = {};
    snprintf(line, sizeof(line), "%s | %-16s | %s", timestamp, event ? event : "EVENT", detail);
    appendLine(line);
}

size_t droneDiagLogSize()
{
    return fileSize(PREVIOUS_LOG) + fileSize(CURRENT_LOG);
}

void droneDiagClear()
{
    if (snapshotLocked())
        return;
    if (FSCom.exists(PREVIOUS_LOG))
        FSCom.remove(PREVIOUS_LOG);
    if (FSCom.exists(CURRENT_LOG))
        FSCom.remove(CURRENT_LOG);
    droneDiagLog("LOG", "cleared");
}

void droneDiagRequestUsbExport()
{
    if (!initialized)
        droneDiagInit();
    closeUsbFile();
    usbHeaderLength = 0;
    usbFooterLength = 0;
    usbState = UsbState::PREPARE;
}

bool droneDiagUsbExportPending()
{
    return usbState != UsbState::IDLE && usbState != UsbState::DONE && usbState != UsbState::ERROR;
}

uint8_t droneDiagUsbExportProgress()
{
    if (usbState == UsbState::DONE)
        return 100;
    if (usbExpectedBytes == 0)
        return usbState == UsbState::FOOTER ? 95 : 0;
    const uint32_t progress = (uint32_t)((uint64_t)usbPayloadSent * 90ULL / usbExpectedBytes);
    return (uint8_t)(progress > 90U ? 90U : progress);
}

const char *droneDiagUsbExportStatusText()
{
    switch (usbState) {
    case UsbState::IDLE:
        return "READY";
    case UsbState::PREPARE:
        return "PREPARE";
    case UsbState::HEADER:
    case UsbState::PREVIOUS:
    case UsbState::CURRENT:
    case UsbState::FOOTER:
        return "EXPORTING";
    case UsbState::DONE:
        return "DONE";
    case UsbState::ERROR:
        return "ERROR";
    }
    return "UNKNOWN";
}

bool droneDiagStartBleExport()
{
    if (!initialized)
        droneDiagInit();
    if (bleActive)
        return false;

    blePreviousBytes = fileSize(PREVIOUS_LOG);
    bleCurrentBytes = fileSize(CURRENT_LOG);
    blePreviousSent = 0;
    bleCurrentSent = 0;
    bleHeaderOffset = 0;
    bleFooterOffset = 0;
    bleHeaderLength = buildHeader(bleHeader, sizeof(bleHeader), blePreviousBytes + bleCurrentBytes);
    bleFooterLength = 0;
    blePhase = 0;
    bleActive = bleHeaderLength < sizeof(bleHeader);
    return bleActive;
}

size_t droneDiagReadBleExport(uint8_t *buffer, size_t capacity)
{
    if (!bleActive || !buffer || capacity == 0)
        return 0;

    if (blePhase == 0) {
        const size_t remaining = bleHeaderLength - bleHeaderOffset;
        const size_t take = std::min(remaining, capacity);
        memcpy(buffer, bleHeader + bleHeaderOffset, take);
        bleHeaderOffset += take;
        if (bleHeaderOffset >= bleHeaderLength) {
            if (blePreviousBytes != 0 && openBleFile(PREVIOUS_LOG))
                blePhase = 1;
            else if (bleCurrentBytes != 0 && openBleFile(CURRENT_LOG))
                blePhase = 2;
            else
                blePhase = 3;
        }
        return take;
    }

    if (blePhase == 1 || blePhase == 2) {
        size_t &sent = blePhase == 1 ? blePreviousSent : bleCurrentSent;
        const size_t expected = blePhase == 1 ? blePreviousBytes : bleCurrentBytes;
        const size_t remaining = expected > sent ? expected - sent : 0;
        if (remaining == 0) {
            closeBleFile();
            if (blePhase == 1 && bleCurrentBytes != 0 && openBleFile(CURRENT_LOG))
                blePhase = 2;
            else
                blePhase = 3;
            return droneDiagReadBleExport(buffer, capacity);
        }
        const size_t got = bleFile.read(buffer, std::min(capacity, remaining));
        if (got == 0) {
            droneDiagCancelBleExport();
            return 0;
        }
        sent += got;
        return got;
    }

    if (blePhase == 3) {
        if (bleFooterLength == 0)
            bleFooterLength = buildFooter(bleFooter, sizeof(bleFooter), blePreviousSent + bleCurrentSent);
        const size_t remaining = bleFooterLength - bleFooterOffset;
        const size_t take = std::min(remaining, capacity);
        memcpy(buffer, bleFooter + bleFooterOffset, take);
        bleFooterOffset += take;
        if (bleFooterOffset >= bleFooterLength) {
            closeBleFile();
            bleActive = false;
            blePhase = 4;
        }
        return take;
    }

    return 0;
}

void droneDiagCancelBleExport()
{
    closeBleFile();
    bleActive = false;
    blePhase = 0;
}

bool droneDiagBleExportActive()
{
    return bleActive;
}

#endif
