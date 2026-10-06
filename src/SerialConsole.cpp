#include "SerialConsole.h"
#include "Default.h"
#include "MeshService.h"
#include "NodeDB.h"
#include "PowerFSM.h"
#include "Throttle.h"
#include "concurrency/LockGuard.h"
#include "configuration.h"
#include "jarnsen/adapters/JarnsenLegacyStatusBridge.h"
#include "jarnsen/core/build/JarnsenBuildInfo.h"
#include "jarnsen/core/mesh/JarnsenRadioProfiles.h"
#include "jarnsen/core/roles/JarnsenRolePersistence.h"
#include "jarnsen/core/runtime/JarnsenDroneRepeaterPolicy.h"
#include "jarnsen/core/service/JarnsenDiagnosticLog.h"
#include "jarnsen/core/service/JarnsenHardwareIdentity.h"
#include "jarnsen/core/service/JarnsenTlsProvisioning.h"
#include "jarnsen/core/status/JarnsenStatusProvider.h"
#include "jarnsen/hardware/JarnsenHardwareProfiles.h"
#include "main.h"
#include "time.h"

#include <cctype>
#include <cstdlib>

#if defined(HELTEC_TRACKER_V1_1) && defined(CONFIG_IDF_TARGET_ESP32S3)
#include "platform/esp32/JarnsenRomBoot.h"
#endif

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
char s_jarnsenToolCommand[160] = {};
size_t s_jarnsenToolLength = 0;
bool s_jarnsenToolCollecting = false;
bool s_jarnsenServiceTakeover = false;
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

void drainJarnsenServiceInput()
{
    while (Port.available())
        (void)Port.read();
}

int hexNibble(char value)
{
    if (value >= '0' && value <= '9')
        return value - '0';
    if (value >= 'a' && value <= 'f')
        return value - 'a' + 10;
    if (value >= 'A' && value <= 'F')
        return value - 'A' + 10;
    return -1;
}

bool decodeOwnerHex(const char *text, size_t length, char *out, size_t outSize)
{
    if (!text || !out || outSize < 2 || length == 0 || (length & 1U) != 0 || length / 2 >= outSize)
        return false;

    const size_t decodedLength = length / 2;
    for (size_t i = 0; i < decodedLength; ++i) {
        const int high = hexNibble(text[i * 2]);
        const int low = hexNibble(text[i * 2 + 1]);
        if (high < 0 || low < 0)
            return false;
        const char value = static_cast<char>((high << 4) | low);
        if (value == '\0')
            return false;
        out[i] = value;
    }
    out[decodedLength] = '\0';
    return true;
}

bool ownerNameHasVisibleText(const char *text)
{
    if (!text)
        return false;
    while (*text) {
        if (!std::isspace(static_cast<unsigned char>(*text)))
            return true;
        ++text;
    }
    return false;
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
        Port.print(" radio_profiles=3 diag_log=1 service_version=2 radio_standard_set=1 power_diag=1 usb_takeover=1 role_api=1 owner_api=1 hw_identity=1 tls_provision=1");
#if defined(HELTEC_TRACKER_V1_1) && defined(CONFIG_IDF_TARGET_ESP32S3)
        Port.print(" rom_boot=1");
#endif
        Port.print("\r\n");
        Port.flush();
        return true;
    }

    if (strcmp(command, "JARNSEN_TOOL_HW_INFO") == 0) {
        char response[256] = {};
        if (jarnsen::hardwareIdentityFormat(response, sizeof(response))) {
            Port.print(response);
            Port.print("\r\n");
        } else {
            Port.print("JARNSEN_HW_INFO schema=1 board=unknown chip=0000000000000000 state=storage_error "
                       "firmware_target=unknown mismatch=0 provisioned=0\r\n");
        }
        Port.flush();
        return true;
    }

    if (strcmp(command, "JARNSEN_TOOL_TLS_INFO") == 0) {
        jarnsen::TlsProvisioningInfo tls{};
        const bool readable = jarnsen::tlsProvisioningInfo(tls);
        Port.print("===JARNSEN_TLS=== ready=");
        Port.print(readable && tls.ready ? 1 : 0);
        Port.print(" cert=");
        Port.print((unsigned)tls.certLength);
        Port.print(" key=");
        Port.print((unsigned)tls.keyLength);
        Port.print(" root=");
        Port.print((unsigned)tls.rootLength);
        Port.print("\r\n");
        Port.flush();
        return true;
    }

    if (strncmp(command, "JARNSEN_TOOL_TLS_BEGIN ", 23) == 0) {
        unsigned long certLength = 0;
        unsigned long keyLength = 0;
        unsigned long rootLength = 0;
        const int parsed =
            sscanf(command, "JARNSEN_TOOL_TLS_BEGIN %lu %lu %lu", &certLength, &keyLength, &rootLength);
        const bool ok = parsed == 3 && jarnsen::tlsProvisionBegin((size_t)certLength, (size_t)keyLength, (size_t)rootLength);
        Port.print(ok ? "===JARNSEN_TLS_OK=== action=begin\r\n"
                      : "===JARNSEN_TLS_ERROR=== action=begin\r\n");
        Port.flush();
        return true;
    }

    if (strncmp(command, "JARNSEN_TOOL_TLS_CHUNK ", 23) == 0) {
        char kindText = 0;
        unsigned long offset = 0;
        char payload[113] = {};
        const int parsed = sscanf(command, "JARNSEN_TOOL_TLS_CHUNK %c %lu %112s", &kindText, &offset, payload);
        jarnsen::TlsBlobKind kind = jarnsen::TlsBlobKind::CERT;
        bool kindOk = true;
        if (kindText == 'C')
            kind = jarnsen::TlsBlobKind::CERT;
        else if (kindText == 'K')
            kind = jarnsen::TlsBlobKind::PRIVATE_KEY;
        else if (kindText == 'R')
            kind = jarnsen::TlsBlobKind::ROOT_CA;
        else
            kindOk = false;
        const bool ok = parsed == 3 && kindOk && jarnsen::tlsProvisionChunk(kind, (size_t)offset, payload);
        Port.print(ok ? "===JARNSEN_TLS_OK=== action=chunk\r\n"
                      : "===JARNSEN_TLS_ERROR=== action=chunk\r\n");
        Port.flush();
        return true;
    }

    if (strcmp(command, "JARNSEN_TOOL_TLS_COMMIT") == 0) {
        const bool ok = jarnsen::tlsProvisionCommit();
        Port.print(ok ? "===JARNSEN_TLS_OK=== action=commit\r\n"
                      : "===JARNSEN_TLS_ERROR=== action=commit\r\n");
        Port.flush();
        return true;
    }

    if (strcmp(command, "JARNSEN_TOOL_TLS_ABORT") == 0) {
        jarnsen::tlsProvisionAbort();
        Port.print("===JARNSEN_TLS_OK=== action=abort\r\n");
        Port.flush();
        return true;
    }

    if (strcmp(command, "JARNSEN_TOOL_ROLE_INFO") == 0) {
        jarnsen::ensureLegacyStatusBridge();
        jarnsen::DeviceRole active = jarnsen::DeviceRole::UNCONFIGURED;
        const bool known = jarnsen::readActiveDeviceRole(active);
        jarnsen::DeviceRole persisted = jarnsen::DeviceRole::UNCONFIGURED;
        const bool persistedKnown = jarnsen::readPersistedDeviceRole(persisted);
        const auto profile = jarnsen::currentHardwareRoleProfile();
        const auto status = jarnsen::readNodeStatus(profile);

        Port.print("===JARNSEN_ROLE=== role=");
        Port.print(jarnsen::roleKey(known ? active : jarnsen::DeviceRole::UNCONFIGURED));
        Port.print(" known=");
        Port.print(known ? 1 : 0);
        Port.print(" persisted=");
        Port.print(persistedKnown ? 1 : 0);
        Port.print(" allowed=");
        Port.print(known && jarnsen::roleAllowed(active, profile.roles) ? 1 : 0);
        Port.print(" gps_ready=");
        Port.print(status.capabilities.gps ? 1 : 0);
        Port.print(" external_gps_required=");
        Port.print((!profile.hardware.capabilities.internalGps && profile.hardware.capabilities.supportsExternalGps) ? 1 : 0);
        Port.print(" role_api=1\r\n");
        Port.flush();
        return true;
    }

    static constexpr char OWNER_SET_PREFIX[] = "JARNSEN_TOOL_OWNER_SET ";
    if (strncmp(command, OWNER_SET_PREFIX, sizeof(OWNER_SET_PREFIX) - 1) == 0) {
        const char *payload = command + sizeof(OWNER_SET_PREFIX) - 1;
        const char *separator = strchr(payload, ' ');
        char longName[sizeof(owner.long_name)] = {};
        char shortName[sizeof(owner.short_name)] = {};

        bool valid = separator && separator != payload;
        const char *shortHex = valid ? separator + 1 : nullptr;
        while (shortHex && *shortHex == ' ')
            ++shortHex;
        if (!shortHex || !*shortHex || strchr(shortHex, ' '))
            valid = false;

        if (valid) {
            const size_t longHexLength = static_cast<size_t>(separator - payload);
            const size_t shortHexLength = strlen(shortHex);
            valid = decodeOwnerHex(payload, longHexLength, longName, sizeof(longName)) &&
                    decodeOwnerHex(shortHex, shortHexLength, shortName, sizeof(shortName)) &&
                    ownerNameHasVisibleText(longName) && ownerNameHasVisibleText(shortName);
        }

        bool stored = false;
        bool verified = false;
        if (valid && nodeDB && service) {
            strlcpy(owner.long_name, longName, sizeof(owner.long_name));
            strlcpy(owner.short_name, shortName, sizeof(owner.short_name));
            snprintf(owner.id, sizeof(owner.id), "!%08x", nodeDB->getNodeNum());

            // Keep the live self-node and the persisted DeviceState/NodeDB in
            // lock-step. This bypasses the phone Admin transaction state that
            // made Meshtastic CLI --set-owner report success while silently
            // leaving the old owner on a freshly provisioned V3.
            service->reloadOwner(false);
            stored = nodeDB->saveToDisk(SEGMENT_DEVICESTATE | SEGMENT_NODEDATABASE);
            verified = stored && strcmp(owner.long_name, longName) == 0 && strcmp(owner.short_name, shortName) == 0;
        }

        jarnsen::diagnosticLog("OWNER_SET", "result=%s long=%s short=%s persisted=%d",
                               verified ? "ok" : "error", valid ? longName : "<invalid>",
                               valid ? shortName : "<invalid>", stored ? 1 : 0);
        Port.print(verified ? "===JARNSEN_OWNER_OK=== action=set persisted=1\r\n"
                            : "===JARNSEN_OWNER_ERROR=== action=set persisted=0\r\n");
        Port.flush();
        return true;
    }

    if (strncmp(command, "JARNSEN_TOOL_ROLE_SET ", 22) == 0) {
        char roleText[32] = {};
        const int parsed = sscanf(command, "JARNSEN_TOOL_ROLE_SET %31s", roleText);
        jarnsen::DeviceRole requested = jarnsen::DeviceRole::UNCONFIGURED;
        const bool valid = parsed == 1 && jarnsen::parseDeviceRoleKey(roleText, requested);
        const bool allowed = valid && jarnsen::deviceRoleAllowedOnCurrentHardware(requested);

        bool configOk = allowed;
        if (configOk && requested == jarnsen::DeviceRole::DRONE_REPEATER)
            configOk = jarnsen::droneRepeaterApplyBaseConfig(true);

        const bool stored = configOk && jarnsen::writePersistedDeviceRole(requested);
        jarnsen::DeviceRole verify = jarnsen::DeviceRole::UNCONFIGURED;
        const bool verified = stored && jarnsen::readPersistedDeviceRole(verify) && verify == requested;

        if (verified) {
            jarnsen::diagnosticLog("ROLE_SET", "role=%s result=ok", jarnsen::roleKey(requested));
            Port.print("===JARNSEN_ROLE_OK=== role=");
            Port.print(jarnsen::roleKey(requested));
            Port.print(" verified=1 reboot_required=1\r\n");
        } else {
            const char *reason = !valid ? "invalid_role" : (!allowed ? "unsupported_board" : (!configOk ? "profile_persist" : "store_verify"));
            jarnsen::diagnosticLog("ROLE_SET", "role=%s result=error reason=%s", valid ? jarnsen::roleKey(requested) : roleText, reason);
            Port.print("===JARNSEN_ROLE_ERROR=== role=");
            Port.print(valid ? jarnsen::roleKey(requested) : roleText);
            Port.print(" reason=");
            Port.print(reason);
            Port.print("\r\n");
        }
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
        char frequencyText[24] = {};
        char presetText[24] = {};
        char hopsText[12] = {};
        // Keep the wire parser integer/string-only. ESP32/newlib nano builds do
        // not reliably enable scanf floating-point support; using %f here made
        // a syntactically valid STANDARD command fail before it reached the
        // profile persistence code. STANDARD does not need the frequency token
        // at all, while JARNSEN profiles parse it explicitly with strtof below.
        const int parsed = sscanf(command, "JARNSEN_TOOL_RADIO_SET %15s %23s %23s %11s", profileText, frequencyText,
                                  presetText, hopsText);
        jarnsen::RadioProfileSlot profile = jarnsen::RadioProfileSlot::STANDARD;
        meshtastic_Config_LoRaConfig_ModemPreset preset = meshtastic_Config_LoRaConfig_ModemPreset_LONG_FAST;

        char *hopsEnd = nullptr;
        const unsigned long hopsValue = strtoul(hopsText, &hopsEnd, 10);
        const bool hopsValid = hopsText[0] != '\0' && hopsEnd && *hopsEnd == '\0' && hopsValue >= 1UL && hopsValue <= 20UL;
        const bool profileValid = parsed == 4 && jarnsen::parseRadioProfile(profileText, profile);
        const bool presetValid = parsed == 4 && jarnsen::parseRadioModemPreset(presetText, preset);

        float frequency = 0.0f;
        bool frequencyValid = profileValid && profile == jarnsen::RadioProfileSlot::STANDARD;
        if (profileValid && profile != jarnsen::RadioProfileSlot::STANDARD) {
            char *frequencyEnd = nullptr;
            frequency = strtof(frequencyText, &frequencyEnd);
            frequencyValid = frequencyText[0] != '\0' && frequencyEnd && *frequencyEnd == '\0';
        }

        const bool valid = profileValid && presetValid && hopsValid && frequencyValid;
        bool ok = false;
        if (valid) {
            ok = profile == jarnsen::RadioProfileSlot::STANDARD
                     ? jarnsen::radioProfileConfigureStandard((uint8_t)hopsValue)
                     : jarnsen::radioProfileConfigureJarnsen(profile, frequency, preset, (uint8_t)hopsValue);
        }

        if (!valid) {
            jarnsen::diagnosticLog("RADIO_SET",
                                   "profile=%s result=error reason=parse parsed=%d frequency=%s preset=%s hops=%s",
                                   profileText, parsed, frequencyText, presetText, hopsText);
        } else if (!ok) {
            jarnsen::diagnosticLog("RADIO_SET", "profile=%s result=error reason=persist hops=%lu",
                                   jarnsen::radioProfileKey(profile), hopsValue);
        } else {
            jarnsen::diagnosticLog("RADIO_SET", "profile=%s result=ok hops=%lu", jarnsen::radioProfileKey(profile),
                                   hopsValue);
        }
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

#if defined(HELTEC_TRACKER_V1_1) && defined(CONFIG_IDF_TARGET_ESP32S3)
    if (strcmp(command, "JARNSEN_TOOL_ROM_BOOT") == 0) {
        jarnsen::diagnosticLog("ROM_BOOT", "requested=1 transport=usb chip=esp32s3");
        Port.print("===JARNSEN_ROM_BOOT=== accepted=1 chip=esp32s3\r\n");
        Port.flush();
        delay(50);
        JarnsenRomBoot::enterEsp32S3DownloadMode();
        return true;
    }
#endif

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
    if (jarnsen::diagnosticLogUsbExportPending()) {
        // The textual diagnostic snapshot owns the serial wire until END. Do
        // not let framed FromRadio bytes or host retries splice into it.
        drainJarnsenServiceInput();
        return 5;
    }
#ifdef MESHTASTIC_PHONEAPI_ACCESS_CONTROL
    const bool linkUp = static_cast<bool>(Port);
    if (s_serialLinkUp && !linkUp)
        close();
    s_serialLinkUp = linkUp;
#endif

#ifdef IS_USB_SERIAL
    if (!HWCDC::isPlugged()) {
        resetJarnsenToolCommand();
        s_jarnsenServiceTakeover = false;
        usingProtobufs = false;
        canWrite = false;
        setHostDraining(false);
        resetStreamRxState();
        concurrency::LockGuard guard(&streamLock);
        frameWriter.reset();
    }
#endif

#ifdef HELTEC_MESH_SOLAR
    if (moduleConfig.serial.enabled && moduleConfig.serial.override_console_serial_port &&
        moduleConfig.serial.mode == meshtastic_ModuleConfig_SerialConfig_Serial_Mode_MS_CONFIG) {
        return 250;
    }
#endif

    // A literal JARNSEN_TOOL_* line is an explicit local-service request. It
    // can take ownership even after a Meshtastic protobuf session. Disable API
    // TX and discard partial framed state; the next valid ToRadio frame resumes
    // the normal Meshtastic serial API without a reboot.
    if (jarnsenToolCommandPending() || (Port.available() && Port.peek() == 'J')) {
        if (!s_jarnsenServiceTakeover)
            jarnsen::diagnosticLog("USB_SERVICE", "takeover previous=%s", usingProtobufs ? "protobuf" : "console");
        s_jarnsenServiceTakeover = true;
        usingProtobufs = false;
        canWrite = false;
        resetStreamRxState();
#ifdef IS_USB_SERIAL
        {
            concurrency::LockGuard guard(&streamLock);
            frameWriter.reset();
        }
#endif
        setHostDraining(true);
        if (consumeJarnsenToolCommand(true))
            return Port.available() ? 0 : 5;
    }

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
    if (usingProtobufs || s_jarnsenServiceTakeover)
        return;

    Port.flush();
}

size_t SerialConsole::write(uint8_t c)
{
    if (usingProtobufs || s_jarnsenServiceTakeover)
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
        if (s_jarnsenServiceTakeover) {
            jarnsen::diagnosticLog("USB_SERVICE", "resume=protobuf");
            s_jarnsenServiceTakeover = false;
        }
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
    if (s_jarnsenServiceTakeover || jarnsen::diagnosticLogUsbExportPending())
        return;
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
