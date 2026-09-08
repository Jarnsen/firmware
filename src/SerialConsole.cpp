#include "SerialConsole.h"
#include "Default.h"
#include "NodeDB.h"
#include "PowerFSM.h"
#include "Throttle.h"
#include "concurrency/LockGuard.h"
#include "configuration.h"
#include "jarnsen/core/build/JarnsenBuildInfo.h"
#include "jarnsen/core/mesh/JarnsenRadioProfiles.h"
#include "jarnsen/core/service/JarnsenDiagnosticLog.h"
#include "main.h"
#include "time.h"

#if defined(ARDUINO_USB_CDC_ON_BOOT) && ARDUINO_USB_CDC_ON_BOOT
#define IS_USB_SERIAL
#ifdef SERIAL_HAS_ON_RECEIVE
#undef SERIAL_HAS_ON_RECEIVE
#endif
#include "HWCDC.h"
#endif

#ifdef RP2040_SLOW_CLOCK
#define Port Serial2
#else
#ifdef USER_DEBUG_PORT
#define Port USER_DEBUG_PORT
#else
#define Port Serial
#endif
#endif
#define SERIAL_CONNECTION_TIMEOUT (15 * 60) * 1000UL

SerialConsole *console;

#ifdef MESHTASTIC_PHONEAPI_ACCESS_CONTROL
static bool s_serialLinkUp = false;
#endif

namespace
{
constexpr uint32_t JARNSEN_TOOL_LINE_TIMEOUT_MS = 5000U;
char s_jarnsenToolCommand[96] = {};
size_t s_jarnsenToolLength = 0;
bool s_jarnsenToolCollecting = false;
uint32_t s_jarnsenToolStartedMs = 0;

void resetJarnsenToolCommand()
{
    s_jarnsenToolLength = 0;
    s_jarnsenToolCollecting = false;
    s_jarnsenToolStartedMs = 0;
    s_jarnsenToolCommand[0] = '\0';
}

bool jarnsenToolCommandPending()
{
    return s_jarnsenToolCollecting;
}

void printRadioResult(bool ok, const char *action, const char *profile = nullptr)
{
    Port.print(ok ? "===JARNSEN_RADIO_OK=== action=" : "===JARNSEN_RADIO_ERROR=== action=");
    Port.print(action);
    if (profile && profile[0]) {
        Port.print(" profile=");
        Port.print(profile);
    }
    Port.print("\r\n");
    Port.flush();
}

bool consumeJarnsenToolCommand(bool allowDiagnosticExport)
{
    if (!s_jarnsenToolCollecting) {
        if (!Port.available() || Port.peek() != 'J')
            return false;
        s_jarnsenToolCollecting = true;
        s_jarnsenToolStartedMs = millis() ? millis() : 1;
        s_jarnsenToolLength = 0;
    }

    bool complete = false;
    while (Port.available() && s_jarnsenToolLength + 1 < sizeof(s_jarnsenToolCommand)) {
        const int value = Port.read();
        if (value < 0)
            break;
        const char c = (char)value;
        if (c == '\n') {
            complete = true;
            break;
        }
        if (c != '\r')
            s_jarnsenToolCommand[s_jarnsenToolLength++] = c;
    }
    s_jarnsenToolCommand[s_jarnsenToolLength] = '\0';

    if (!complete) {
        const bool full = s_jarnsenToolLength + 1 >= sizeof(s_jarnsenToolCommand);
        const bool expired = s_jarnsenToolStartedMs != 0 &&
                             (uint32_t)(millis() - s_jarnsenToolStartedMs) >= JARNSEN_TOOL_LINE_TIMEOUT_MS;
        if (full || expired)
            resetJarnsenToolCommand();
        return true;
    }

    char command[sizeof(s_jarnsenToolCommand)] = {};
    strlcpy(command, s_jarnsenToolCommand, sizeof(command));
    resetJarnsenToolCommand();

    const bool info = strncmp(command, "JARNSEN_TOOL_INFO ", 18) == 0 || strcmp(command, "JARNSEN_TOOL_INFO") == 0;
    const bool incremental = strncmp(command, "JARNSEN_TOOL_HELLO ", 19) == 0 || strcmp(command, "JARNSEN_TOOL_HELLO") == 0;
    const bool full = strncmp(command, "JARNSEN_TOOL_FULL ", 18) == 0 || strcmp(command, "JARNSEN_TOOL_FULL") == 0;

    if (info) {
        Port.print("===JARNSEN_INFO=== product=");
        Port.print(jarnsen::build::productName);
        Port.print(" version=");
        Port.print(jarnsen::build::version);
        Port.print(" build=");
        Port.print(jarnsen::build::buildNumber);
        Port.print(" hardware=");
        Port.print(jarnsen::build::hardwareName);
        Port.print(" sha=");
        Port.print(jarnsen::build::gitSha);
        Port.print(" radio_profiles=3 diag_log=1 service_version=2 power_diag=1\r\n");
        Port.flush();
        return true;
    }

    if (strcmp(command, "JARNSEN_TOOL_RADIO_INFO") == 0) {
        const auto active = jarnsen::radioProfileActive();
        Port.print("===JARNSEN_RADIO=== active=");
        Port.print(jarnsen::radioProfileKey(active));
        Port.print(" slots=3 standard=");
        Port.print(jarnsen::radioProfileSlotExists(jarnsen::RadioProfileSlot::STANDARD) ? 1 : 0);
        Port.print(" jarnsen1=");
        Port.print(jarnsen::radioProfileSlotExists(jarnsen::RadioProfileSlot::JARNSEN_1) ? 1 : 0);
        Port.print(" jarnsen2=");
        Port.print(jarnsen::radioProfileSlotExists(jarnsen::RadioProfileSlot::JARNSEN_2) ? 1 : 0);
        Port.print("\r\n");
        Port.flush();
        return true;
    }

    if (strcmp(command, "JARNSEN_TOOL_RADIO_CAPTURE_STANDARD") == 0) {
        printRadioResult(jarnsen::radioProfileCaptureStandard(), "capture", "standard");
        return true;
    }

    if (strncmp(command, "JARNSEN_TOOL_RADIO_SET ", 23) == 0) {
        char profileText[16] = {};
        char presetText[24] = {};
        float frequency = 0.0f;
        unsigned int hops = 0;
        const int parsed = sscanf(command, "JARNSEN_TOOL_RADIO_SET %15s %f %23s %u", profileText, &frequency, presetText, &hops);
        jarnsen::RadioProfileSlot profile = jarnsen::RadioProfileSlot::STANDARD;
        meshtastic_Config_LoRaConfig_ModemPreset preset = meshtastic_Config_LoRaConfig_ModemPreset_LONG_FAST;
        const bool valid = parsed == 4 && jarnsen::parseRadioProfile(profileText, profile) &&
                           jarnsen::parseRadioModemPreset(presetText, preset) && hops >= 1U && hops <= 20U;
        const bool ok = valid && jarnsen::radioProfileConfigureJarnsen(profile, frequency, preset, (uint8_t)hops);
        printRadioResult(ok, "set", valid ? jarnsen::radioProfileKey(profile) : profileText);
        return true;
    }

    if (strncmp(command, "JARNSEN_TOOL_RADIO_SELECT ", 26) == 0) {
        char profileText[16] = {};
        const int parsed = sscanf(command, "JARNSEN_TOOL_RADIO_SELECT %15s", profileText);
        jarnsen::RadioProfileSlot profile = jarnsen::RadioProfileSlot::STANDARD;
        const bool valid = parsed == 1 && jarnsen::parseRadioProfile(profileText, profile);
        const bool ok = valid && jarnsen::radioProfileSelect(profile, true);
        printRadioResult(ok, "select", valid ? jarnsen::radioProfileKey(profile) : profileText);
        return true;
    }

    if (allowDiagnosticExport && (incremental || full)) {
        jarnsen::diagnosticLogRequestUsbExport(Port);
        return true;
    }

    return true;
}
} // namespace

void consoleInit()
{
    if (console) {
        return;
    }
    auto sc = new SerialConsole();

#if defined(SERIAL_HAS_ON_RECEIVE)
    Port.onReceive([sc]() { sc->rxInt(); });
#else
    (void)sc;
#endif
    DEBUG_PORT.rpInit();
}

void consolePrintf(const char *format, ...)
{
    va_list arg;
    va_start(arg, format);
    console->vprintf(nullptr, format, arg);
    va_end(arg);
    console->flush();
}

SerialConsole::SerialConsole() : StreamAPI(&Port), RedirectablePrint(&Port), concurrency::OSThread("SerialConsole")
{
    api_type = TYPE_SERIAL;
    assert(!console);
    console = this;
    canWrite = false;

#ifdef RP2040_SLOW_CLOCK
    Port.setTX(SERIAL2_TX);
    Port.setRX(SERIAL2_RX);
#endif
    Port.begin(SERIAL_BAUD);
    setHostDraining(false);
    jarnsen::diagnosticLogInit();
    time_t timeout = millis();
    while (!Port) {
        if (Throttle::isWithinTimespanMs(timeout, FIVE_SECONDS_MS)) {
            delay(100);
        } else {
            break;
        }
    }
#if !ARCH_PORTDUINO
    emitRebooted();
#endif
}

int32_t SerialConsole::runOnce()
{
    jarnsen::diagnosticLogPumpUsbExport();
#ifdef MESHTASTIC_PHONEAPI_ACCESS_CONTROL
    const bool linkUp = static_cast<bool>(Port);
    if (s_serialLinkUp && !linkUp)
        close();
    s_serialLinkUp = linkUp;
#endif

#ifdef IS_USB_SERIAL
    if (!HWCDC::isPlugged())
        resetJarnsenToolCommand();
#endif

#ifdef HELTEC_MESH_SOLAR
    if (moduleConfig.serial.enabled && moduleConfig.serial.override_console_serial_port &&
        moduleConfig.serial.mode == meshtastic_ModuleConfig_SerialConfig_Serial_Mode_MS_CONFIG) {
        return 250;
    }
#endif

    // A literal JARNSEN_TOOL_* line is an explicit local-service request.  The
    // diagnostic exporter writes directly to Port, so do not silently discard
    // JARNSEN_TOOL_FULL/HELLO merely because an earlier Meshtastic session left
    // the console latched in protobuf mode.
    if ((jarnsenToolCommandPending() || (Port.available() && Port.peek() == 'J')) &&
        consumeJarnsenToolCommand(true))
        return Port.available() ? 0 : 5;

    int32_t delay = runOncePart();
#if defined(SERIAL_HAS_ON_RECEIVE) || defined(CONFIG_IDF_TARGET_ESP32S2)
    return Port.available() ? delay : INT32_MAX;
#elif defined(IS_USB_SERIAL)
    return HWCDC::isPlugged() ? delay : (1000 * 20);
#else
    return delay;
#endif
}

void SerialConsole::flush()
{
    if (usingProtobufs)
        return;

    Port.flush();
}

size_t SerialConsole::write(uint8_t c)
{
    if (usingProtobufs)
        return 1;

    if (c == '\n')
        RedirectablePrint::write('\r');
    return RedirectablePrint::write(c);
}

void SerialConsole::onNowHasData(uint32_t fromRadioNum)
{
    setIntervalFromNow(0);
}

void SerialConsole::rxInt()
{
    setIntervalFromNow(0);
}

bool SerialConsole::checkIsConnected()
{
    return Throttle::isWithinTimespanMs(lastContactMsec, SERIAL_CONNECTION_TIMEOUT);
}

void SerialConsole::setHostDraining(bool draining)
{
#ifdef IS_USB_SERIAL
    Port.setTxTimeoutMs(draining ? 100 : 0);
#else
    (void)draining;
#endif
}

void SerialConsole::onConnectionChanged(bool connected)
{
    if (!connected) {
        setHostDraining(false);
    }
    StreamAPI::onConnectionChanged(connected);
    if (connected)
        setHostDraining(true);
}

bool SerialConsole::finishPendingFrame()
{
#ifdef IS_USB_SERIAL
    concurrency::LockGuard guard(&streamLock);
    return frameWriter.finishPendingFrame(Port);
#else
    return true;
#endif
}

bool SerialConsole::canEncodeLogRecord()
{
#ifdef IS_USB_SERIAL
    concurrency::LockGuard guard(&streamLock);
    return frameWriter.isIdle();
#else
    return true;
#endif
}

bool SerialConsole::writeFrame(uint8_t *buf, size_t len, bool bestEffort)
{
#ifdef IS_USB_SERIAL
    if (len == 0 || !canWrite)
        return false;

    const size_t totalLen = buildFrameHeader(buf, len);

    concurrency::LockGuard guard(&streamLock);
    return frameWriter.writeFrame(Port, buf, totalLen, bestEffort);
#else
    return StreamAPI::writeFrame(buf, len, bestEffort);
#endif
}

bool SerialConsole::handleToRadio(const uint8_t *buf, size_t len)
{
    if (config.has_lora && config.security.serial_enabled) {
        setHostDraining(true);
        usingProtobufs = true;
        canWrite = true;

        return StreamAPI::handleToRadio(buf, len);
    } else {
        return false;
    }
}

void SerialConsole::log_to_serial(const char *logLevel, const char *format, va_list arg)
{
    jarnsen::diagnosticLogV(logLevel, format, arg);
    if (usingProtobufs) {
        if (config.security.debug_log_api_enabled && !pauseBluetoothLogging) {
            meshtastic_LogRecord_Level ll = RedirectablePrint::getLogLevel(logLevel);
            auto thread = concurrency::OSThread::currentThread;
            emitLogRecord(ll, thread ? thread->ThreadName.c_str() : "", format, arg);
        }
        return;
    }

    RedirectablePrint::log_to_serial(logLevel, format, arg);
}
