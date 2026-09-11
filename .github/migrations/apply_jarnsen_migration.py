#!/usr/bin/env python3
from pathlib import Path
import re


def rd(path):
    return Path(path).read_text(encoding="utf-8")


def wr(path, text):
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8", newline="\n")


def repl(path, old, new):
    text = rd(path)
    if old not in text:
        if new in text:
            return
        raise SystemExit(f"{path}: migration seam missing: {old[:120]!r}")
    if text.count(old) != 1:
        raise SystemExit(f"{path}: migration seam is not unique: {old[:120]!r}")
    wr(path, text.replace(old, new, 1))


SEC_H = r'''#pragma once

#include <stdint.h>

namespace jarnsen
{
constexpr uint32_t kJarnsenUserPin = 240180U;
constexpr const char kJarnsenWifiPassword[] = "24011980";

void serviceSecurityInit();
bool serviceSecurityLocked();
bool serviceSecurityVerifyPin(uint32_t pin);
bool serviceSecurityLock();
bool serviceSecurityUnlock(uint32_t pin);
void serviceSecurityPump();
bool serviceSecurityMeshAlertsEnabled();
void serviceSecuritySetMeshAlertsEnabled(bool enabled);
bool serviceSecurityWifiAllowed();
} // namespace jarnsen
'''

SEC_CPP = r'''#include "jarnsen/core/service/JarnsenServiceSecurity.h"

#include "NodeDB.h"
#include "configuration.h"
#include "gps/RTC.h"
#include "jarnsen/adapters/JarnsenLegacyStatusBridge.h"
#include "jarnsen/core/roles/JarnsenDeviceRole.h"
#include "jarnsen/core/status/JarnsenStatusProvider.h"
#include "modules/TextMessageModule.h"

#include <Arduino.h>
#include <cstdio>
#include <cstring>

#if defined(ARCH_ESP32)
#include <Preferences.h>
#endif

namespace jarnsen
{
namespace
{
enum class AlertKind : uint8_t { NONE = 0, LOCKED, UNLOCKED };
bool initialized = false;
bool lockedState = false;
bool meshAlerts = true;
AlertKind pendingAlert = AlertKind::NONE;
uint8_t pendingSendIndex = 0;
uint32_t nextSendMs = 0;

void loadState()
{
#if defined(ARCH_ESP32)
    Preferences prefs;
    if (prefs.begin("jarnSec", true)) {
        lockedState = prefs.getBool("locked", false);
        meshAlerts = prefs.getBool("alert", true);
        prefs.end();
    }
#endif
}

void persistBool(const char *key, bool value)
{
#if defined(ARCH_ESP32)
    Preferences prefs;
    if (prefs.begin("jarnSec", false)) {
        prefs.putBool(key, value);
        prefs.end();
    }
#else
    (void)key;
    (void)value;
#endif
}

void queueAlert(AlertKind kind)
{
    if (!meshAlerts)
        return;
    pendingAlert = kind;
    pendingSendIndex = 0;
    nextSendMs = millis();
}

bool timeReached(uint32_t now, uint32_t target)
{
    return (int32_t)(now - target) >= 0;
}

bool buildAlert(char *out, size_t capacity, AlertKind kind)
{
    if (!out || capacity < 32 || !nodeDB)
        return false;

    const NodeNum selfNum = nodeDB->getNodeNum();
    const meshtastic_NodeInfoLite *self = nodeDB->getMeshNode(selfNum);
    const char *name = self && self->long_name[0] ? self->long_name : "JARN-MESH";
    const uint32_t nowEpoch = getValidTime(RTCQuality::RTCQualityDevice, true);
    meshtastic_PositionLite position{};
    const bool havePosition = nodeDB->copyNodePosition(selfNum, position) &&
                              (position.latitude_i != 0 || position.longitude_i != 0);

    char positionText[72] = "pos=unknown";
    if (havePosition) {
        uint32_t age = 0;
        if (nowEpoch != 0 && position.time != 0 && nowEpoch >= position.time)
            age = nowEpoch - position.time;
        snprintf(positionText, sizeof(positionText), "pos=%.7f,%.7f age=%us", position.latitude_i * 1e-7,
                 position.longitude_i * 1e-7, (unsigned)age);
    }

    snprintf(out, capacity, "JARN %s name=%s id=!%08x time=%u %s",
             kind == AlertKind::LOCKED ? "LOCKED_FULL" : "UNLOCKED", name, (unsigned)selfNum,
             (unsigned)nowEpoch, positionText);
    return true;
}

bool transmitPendingAlert()
{
    if (!textMessageModule)
        return false;
    char message[196] = {};
    if (!buildAlert(message, sizeof(message), pendingAlert))
        return false;
    return textMessageModule->sendLocalBroadcast(message, 0);
}
} // namespace

void serviceSecurityInit()
{
    if (initialized)
        return;
    initialized = true;
    loadState();
}

bool serviceSecurityLocked()
{
    serviceSecurityInit();
    return lockedState;
}

bool serviceSecurityVerifyPin(uint32_t pin)
{
    return pin == kJarnsenUserPin;
}

bool serviceSecurityLock()
{
    serviceSecurityInit();
    if (lockedState)
        return false;
    lockedState = true;
    persistBool("locked", true);
    queueAlert(AlertKind::LOCKED);
    return true;
}

bool serviceSecurityUnlock(uint32_t pin)
{
    serviceSecurityInit();
    if (!serviceSecurityVerifyPin(pin) || !lockedState)
        return false;
    lockedState = false;
    persistBool("locked", false);
    queueAlert(AlertKind::UNLOCKED);
    return true;
}

void serviceSecurityPump()
{
    serviceSecurityInit();
    if (pendingAlert == AlertKind::NONE || !meshAlerts)
        return;
    const uint32_t now = millis();
    if (!timeReached(now, nextSendMs))
        return;
    if (!transmitPendingAlert()) {
        nextSendMs = now + 1000U;
        return;
    }
    pendingSendIndex++;
    if (pendingAlert == AlertKind::UNLOCKED || pendingSendIndex >= 3) {
        pendingAlert = AlertKind::NONE;
        pendingSendIndex = 0;
        nextSendMs = 0;
        return;
    }
    nextSendMs = now + (pendingSendIndex == 1 ? 3000U : 7000U);
}

bool serviceSecurityMeshAlertsEnabled()
{
    serviceSecurityInit();
    return meshAlerts;
}

void serviceSecuritySetMeshAlertsEnabled(bool enabled)
{
    serviceSecurityInit();
    meshAlerts = enabled;
    persistBool("alert", enabled);
    if (!enabled) {
        pendingAlert = AlertKind::NONE;
        pendingSendIndex = 0;
        nextSendMs = 0;
    }
}

bool serviceSecurityWifiAllowed()
{
    serviceSecurityInit();
    if (lockedState)
        return false;
    ensureLegacyStatusBridge();
    return !activeDeviceRoleIs(DeviceRole::DRONE_REPEATER);
}
} // namespace jarnsen
'''

wr("src/jarnsen/core/service/JarnsenServiceSecurity.h", SEC_H)
wr("src/jarnsen/core/service/JarnsenServiceSecurity.cpp", SEC_CPP)

# Mesh alert sender lives on the existing text-message SinglePortModule so the
# packet gets the normal TEXT_MESSAGE_APP port/channel encryption semantics.
repl("src/modules/TextMessageModule.h", "    bool recentlySeen(uint32_t id);\n",
     "    bool recentlySeen(uint32_t id);\n    bool sendLocalBroadcast(const char *message, uint8_t channel = 0);\n")
text = rd("src/modules/TextMessageModule.cpp")
if "bool TextMessageModule::sendLocalBroadcast" not in text:
    anchor = "\nbool TextMessageModule::wantPacket(const meshtastic_MeshPacket *p)\n"
    helper = r'''
bool TextMessageModule::sendLocalBroadcast(const char *message, uint8_t channel)
{
    if (!message || !message[0] || !service)
        return false;
    meshtastic_MeshPacket *packet = allocDataPacket();
    if (!packet)
        return false;
    packet->to = NODENUM_BROADCAST;
    packet->channel = channel;
    packet->want_ack = false;
    packet->decoded.dest = NODENUM_BROADCAST;
    size_t length = strlen(message);
    if (length > sizeof(packet->decoded.payload.bytes))
        length = sizeof(packet->decoded.payload.bytes);
    packet->decoded.payload.size = length;
    memcpy(packet->decoded.payload.bytes, message, length);
    service->sendToMesh(packet, RX_SRC_LOCAL, true);
    return true;
}
'''
    if anchor not in text:
        raise SystemExit("TextMessageModule send helper anchor missing")
    wr("src/modules/TextMessageModule.cpp", text.replace(anchor, "\n" + helper + anchor, 1))

# Fixed JARN Bluetooth PIN. Runtime policy only; do not save transient BLE state.
repl("src/nimble/NimbleBluetooth.cpp", '#include "JarnsenLiveDisplay.h"\n',
     '#include "JarnsenLiveDisplay.h"\n#include "jarnsen/core/service/JarnsenServiceSecurity.h"\n')
repl("src/nimble/NimbleBluetooth.cpp", "    BLESecurity security;\n",
     "    // JARN-MESH fixed service pairing policy; never log the PIN.\n"
     "    config.bluetooth.mode = meshtastic_Config_BluetoothConfig_PairingMode_FIXED_PIN;\n"
     "    config.bluetooth.fixed_pin = jarnsen::kJarnsenUserPin;\n\n"
     "    BLESecurity security;\n")

# ServiceWeb: compile through Unified-Core service/status seams and V4 metadata.
web = "src/mesh/http/JarnsenServiceWeb.cpp"
repl(web,
     '#if defined(ARCH_ESP32) && HAS_WIFI && (defined(_VARIANT_HELTEC_V3) || defined(HELTEC_TRACKER_V1_1))\n',
     '#if defined(ARCH_ESP32) && HAS_WIFI && (defined(_VARIANT_HELTEC_V3) || defined(_VARIANT_HELTEC_V4) || defined(HELTEC_TRACKER_V1_1))\n')
repl(web,
     '#include "mesh/wifi/WiFiAPClient.h"\n\n#if defined(_VARIANT_HELTEC_V3)\n#include "infrastructure/HeltecV3DiagnosticLog.h"\n#else\n#include "vehicle/TrackerDiagnosticLog.h"\n#endif\n',
     '#include "mesh/wifi/WiFiAPClient.h"\n#include "jarnsen/core/service/JarnsenServiceDiagnostics.h"\n'
     '#include "jarnsen/core/service/JarnsenServicePlatform.h"\n#include "jarnsen/core/service/JarnsenServiceSecurity.h"\n'
     '#include "jarnsen/core/status/JarnsenStatusProvider.h"\n')
repl(web, 'constexpr const char *SERVICE_PASSWORD = "24011980";\n',
     'constexpr const char *SERVICE_PASSWORD = jarnsen::kJarnsenWifiPassword;\n')
repl(web, 'constexpr uint32_t IDLE_TIMEOUT_MS = 10UL * 60UL * 1000UL;\n',
     'constexpr uint32_t IDLE_TIMEOUT_MS = 10UL * 60UL * 1000UL;\nconstexpr uint32_t CAPTIVE_DNS_GRACE_MS = 20UL * 1000UL;\n')
old = '''#if defined(_VARIANT_HELTEC_V3)
constexpr const char *DEVICE_CODE = "HELTEC_V3_REPEATER";
constexpr const char *DEVICE_TITLE = "Heltec V3";
constexpr const char *SSID_PREFIX = "Jarnsen-V3";
constexpr const char *GITHUB_TAG = "jarnsen-v3-latest";
constexpr const char *FIRMWARE_ASSET = "heltec-v3-repeater-light-sleep.update.bin";
#else
constexpr const char *DEVICE_CODE = "HELTEC_TRACKER_V1.1";
constexpr const char *DEVICE_TITLE = "Tracker V1.1";
constexpr const char *SSID_PREFIX = "Jarnsen-Tracker";
constexpr const char *GITHUB_TAG = "jarnsen-tracker-latest";
constexpr const char *FIRMWARE_ASSET = "heltec-tracker-v11-vehicle-motion-wake.update.bin";
#endif'''
new = '''constexpr auto SERVICE_DESCRIPTOR = jarnsen::platformServiceDescriptor();
static_assert(SERVICE_DESCRIPTOR.profile.hardware.kind != jarnsen::HardwareKind::UNKNOWN,
              "Jarnsen ServiceWeb requires a known Unified Core hardware descriptor");
constexpr const char *DEVICE_CODE = SERVICE_DESCRIPTOR.protocolDeviceCode;
constexpr const char *DEVICE_TITLE = SERVICE_DESCRIPTOR.profile.hardware.displayName;
constexpr const char *SSID_PREFIX = SERVICE_DESCRIPTOR.serviceSsidPrefix;
constexpr const char *GITHUB_TAG = SERVICE_DESCRIPTOR.update.releaseTag;
constexpr const char *FIRMWARE_ASSET = SERVICE_DESCRIPTOR.update.assetName;'''
repl(web, old, new)
repl(web, "bool serviceActive = false;\nbool updateInProgress = false;\nbool hadStation = false;\nuint32_t lastActivityMs = 0;\n",
     "bool serviceActive = false;\nbool updateInProgress = false;\nbool portalAuthorized = false;\nbool captiveDnsActive = false;\n"
     "uint32_t captiveDnsStartedMs = 0;\nuint32_t lastActivityMs = 0;\n")

# Keep a PIN/password overlay in the static portal. Nothing sensitive is fetched before auth.
repl(web, '<body>\n<main class="app">',
     '<body>\n<div id="authGate" style="position:fixed;inset:0;z-index:1000;display:flex;align-items:center;justify-content:center;padding:20px;background:rgba(0,0,0,.58);backdrop-filter:blur(18px)"><div class="card" style="width:min(390px,100%);padding:22px"><div class="eyebrow">JARN-MESH SECURITY</div><h2>Service freigeben</h2><p class="muted">User-PIN für sensible Daten und Änderungen eingeben.</p><input id="userPin" type="password" inputmode="numeric" pattern="[0-9]*" maxlength="6" autocomplete="off" style="box-sizing:border-box;width:100%;height:48px;border-radius:14px;border:1px solid var(--line);background:var(--bg);color:var(--fg);padding:0 14px;font-size:20px;letter-spacing:.12em;margin:10px 0"><button class="btn" id="authBtn" type="button" style="width:100%">FREIGEBEN</button><div class="status" id="authStatus"></div></div></div>\n<main class="app">')
old_tail = "boot().then(()=>Promise.all([loadSituation(),loadTrack()])).then(()=>{if(selfPos)centerSelf();else fitAll()}).catch(e=>setStatus('mapStatus','Service nicht erreichbar: '+e.message,'err'));setInterval(loadSituation,10000);"
new_tail = "let serviceStarted=false;async function authorize(){const pin=$('userPin').value.trim();if(!/^\\d{6}$/.test(pin)){setStatus('authStatus','Bitte 6-stellige User-PIN eingeben.','err');return}setStatus('authStatus','PIN wird geprüft …');try{const r=await fetch('/auth',{method:'POST',headers:{'X-Jarnsen-Pin':pin},cache:'no-store'});if(!r.ok)throw Error('PIN nicht akzeptiert');$('userPin').value='';$('authGate').style.display='none';if(!serviceStarted){serviceStarted=true;await boot();await Promise.all([loadSituation(),loadTrack()]);if(selfPos)centerSelf();else fitAll();setInterval(loadLive,2000);setInterval(loadSituation,10000)}}catch(e){$('userPin').value='';setStatus('authStatus',e.message,'err')}}async function loadLive(){try{const r=await fetch('/live.json',{cache:'no-store'});if(!r.ok)return;const j=await r.json();if(j.position&&j.position.mgrs){$('positionValue').textContent=j.position.mgrs;$('positionSub').textContent='Eigener Standort'}$('networkValue').textContent=(j.online??0)+' online';$('networkSub').textContent=(j.nodes??0)+' bekannt'}catch(_){}}$('authBtn').addEventListener('click',authorize);$('userPin').addEventListener('keydown',e=>{if(e.key==='Enter')authorize()});setTimeout(()=>$('userPin').focus(),150);"
repl(web, old_tail, new_tail)

# Board diagnostics are now behind Core facade (matches existing build-time refactor contract).
old_diag = '''bool startDiagExport()
{
#if defined(_VARIANT_HELTEC_V3)
    return heltecV3DiagStartBleExport();
#else
    return trackerDiagStartBleExport();
#endif
}

size_t readDiagExport(uint8_t *buffer, size_t capacity)
{
#if defined(_VARIANT_HELTEC_V3)
    return heltecV3DiagReadBleExport(buffer, capacity);
#else
    return trackerDiagReadBleExport(buffer, capacity);
#endif
}

void cancelDiagExport()
{
#if defined(_VARIANT_HELTEC_V3)
    heltecV3DiagCancelBleExport();
#else
    trackerDiagCancelBleExport();
#endif
}

void logEvent(const char *event, const char *detail)
{
#if defined(_VARIANT_HELTEC_V3)
    heltecV3DiagLog(event, "%s", detail);
#else
    trackerDiagLog(event, "%s", detail);
#endif
}'''
new_diag = '''bool startDiagExport()
{
    return jarnsen::serviceDiagStartExport();
}

size_t readDiagExport(uint8_t *buffer, size_t capacity)
{
    return jarnsen::serviceDiagReadExport(buffer, capacity);
}

void cancelDiagExport()
{
    jarnsen::serviceDiagCancelExport();
}

void logEvent(const char *event, const char *detail)
{
    jarnsen::serviceDiagLog(event, detail);
}'''
repl(web, old_diag, new_diag)
repl(web,
     'void sendJsonStatus(WiFiClient &client)\n{\n    sendStatus(client, 200, "OK", "application/json; charset=utf-8");\n    const meshtastic_NodeInfoLite *self = nodeDB ? nodeDB->getMeshNode(nodeDB->getNodeNum()) : nullptr;',
     'void sendJsonStatus(WiFiClient &client)\n{\n    sendStatus(client, 200, "OK", "application/json; charset=utf-8");\n    const jarnsen::NodeStatusSnapshot runtimeStatus = jarnsen::readNodeStatus(SERVICE_DESCRIPTOR.profile);\n    const meshtastic_NodeInfoLite *self = nodeDB ? nodeDB->getMeshNode(nodeDB->getNodeNum()) : nullptr;')
repl(web,
     '    client.print(",\\\"device\\\":");\n    sendJsonString(client, DEVICE_CODE);\n    client.print(",\\\"name\\\":");',
     '    client.print(",\\\"device\\\":");\n    sendJsonString(client, DEVICE_CODE);\n    client.print(",\\\"hardware\\\":");\n    sendJsonString(client, runtimeStatus.profile.hardware.code);\n    client.print(",\\\"hardware_name\\\":");\n    sendJsonString(client, runtimeStatus.profile.hardware.displayName);\n    client.print(",\\\"role\\\":");\n    sendJsonString(client, runtimeStatus.activeRoleKnown ? jarnsen::roleName(runtimeStatus.activeRole) : "UNKNOWN");\n    client.printf(",\\\"role_known\\\":%s,\\\"peripherals_known\\\":%s", runtimeStatus.activeRoleKnown ? "true" : "false", runtimeStatus.peripheralsKnown ? "true" : "false");\n    const auto &boardCaps = runtimeStatus.profile.hardware.capabilities;\n    client.printf(",\\\"board_capabilities\\\":{\\\"internal_gps\\\":%s,\\\"external_gps\\\":%s,\\\"bluetooth\\\":%s,\\\"wifi\\\":%s,\\\"battery\\\":%s,\\\"motion\\\":%s,\\\"ina226\\\":%s}", boardCaps.internalGps ? "true" : "false", boardCaps.supportsExternalGps ? "true" : "false", boardCaps.bluetooth ? "true" : "false", boardCaps.wifi ? "true" : "false", boardCaps.battery ? "true" : "false", boardCaps.supportsMotion ? "true" : "false", boardCaps.supportsIna226 ? "true" : "false");\n    const auto &caps = runtimeStatus.capabilities;\n    client.printf(",\\\"capabilities\\\":{\\\"gps\\\":%s,\\\"bluetooth\\\":%s,\\\"wifi\\\":%s,\\\"battery\\\":%s,\\\"usb_power\\\":%s,\\\"motion\\\":%s,\\\"ina226\\\":%s}", caps.gps ? "true" : "false", caps.bluetooth ? "true" : "false", caps.wifi ? "true" : "false", caps.battery ? "true" : "false", caps.usbPowerDetect ? "true" : "false", caps.motion ? "true" : "false", caps.ina226 ? "true" : "false");\n    const auto &roles = runtimeStatus.profile.roles;\n    client.printf(",\\\"supported_roles\\\":{\\\"tak\\\":%s,\\\"tak_tracker\\\":%s,\\\"tak_repeater\\\":%s,\\\"drone_repeater\\\":%s}", roles.tak ? "true" : "false", roles.takTracker ? "true" : "false", roles.takRepeater ? "true" : "false", roles.droneRepeater ? "true" : "false");\n    client.print(",\\\"name\\\":");')

# Session/cookie helpers inserted immediately before sendJsonString.
text = rd(web)
if "bool requestSessionValid" not in text:
    anchor = "void sendJsonString(WiFiClient &client, const char *text)\n{"
    helpers = r'''bool requestSessionValid(const char *cookie, const char *token)
{
    if (!portalAuthorized || !sessionToken[0])
        return false;
    if (token && token[0] && strcmp(token, sessionToken) == 0)
        return true;
    if (!cookie || !cookie[0])
        return false;
    char expected[48] = {};
    snprintf(expected, sizeof(expected), "JARN_SESSION=%s", sessionToken);
    return strstr(cookie, expected) != nullptr;
}

void sendAuthRequired(WiFiClient &client)
{
    sendStatus(client, 401, "Unauthorized", "application/json; charset=utf-8");
    client.print("{\"error\":\"user_pin_required\"}");
}

void sendPortalAuth(WiFiClient &client, const char *pinText)
{
    if (!pinText || strlen(pinText) != 6) {
        sendStatus(client, 400, "Bad Request", "application/json; charset=utf-8");
        client.print("{\"ok\":false}");
        return;
    }
    char *end = nullptr;
    const unsigned long pin = strtoul(pinText, &end, 10);
    if (!end || *end != 0 || !jarnsen::serviceSecurityVerifyPin((uint32_t)pin)) {
        sendStatus(client, 403, "Forbidden", "application/json; charset=utf-8");
        client.print("{\"ok\":false}");
        logEvent("SERVICE_AUTH", "rejected");
        return;
    }
    portalAuthorized = true;
    client.print("HTTP/1.1 200 OK\r\nContent-Type: application/json; charset=utf-8\r\nCache-Control: no-store\r\n");
    client.printf("Set-Cookie: JARN_SESSION=%s; Path=/; HttpOnly; SameSite=Strict\r\n", sessionToken);
    client.print("Connection: close\r\n\r\n{\"ok\":true}");
    logEvent("SERVICE_AUTH", "accepted");
}

void stopCaptiveDns()
{
    if (!captiveDnsActive)
        return;
    dnsServer.stop();
    captiveDnsActive = false;
    captiveDnsStartedMs = 0;
}

'''
    if anchor not in text:
        raise SystemExit("ServiceWeb auth helper anchor missing")
    wr(web, text.replace(anchor, helpers + anchor, 1))

repl(web, "    char device[40] = {};\n    char hash[65] = {};\n    char token[32] = {};",
     "    char device[40] = {};\n    char hash[65] = {};\n    char token[32] = {};\n    char pin[16] = {};\n    char cookie[160] = {};")
repl(web, '        else if (strcasecmp(line, "X-Jarnsen-Token") == 0)\n            strlcpy(token, value, sizeof(token));',
     '        else if (strcasecmp(line, "X-Jarnsen-Token") == 0)\n            strlcpy(token, value, sizeof(token));\n        else if (strcasecmp(line, "X-Jarnsen-Pin") == 0)\n            strlcpy(pin, value, sizeof(pin));\n        else if (strcasecmp(line, "Cookie") == 0)\n            strlcpy(cookie, value, sizeof(cookie));')
old_routes = '''    lastActivityMs = millis() ? millis() : 1;
    if (strcmp(method, "GET") == 0 && strcmp(path, "/status") == 0)
        sendJsonStatus(client);
    else if (strcmp(method, "GET") == 0 && strcmp(path, "/nodes.json") == 0)
        sendNodesJson(client);
    else if (strcmp(method, "GET") == 0 && strncmp(path, "/mgrs?", 6) == 0)
        sendMgrs(client, path);
    else if (strcmp(method, "GET") == 0 && strcmp(path, "/log") == 0)
        sendLog(client);
    else if (strcmp(method, "GET") == 0 && strcmp(path, "/track.geojson") == 0)
        sendTrack(client);
    else if (strcmp(method, "POST") == 0 && strcmp(path, "/track/clear") == 0)
        clearTrack(client, token);
    else if (strcmp(method, "POST") == 0 && strcmp(path, "/update") == 0)
        receiveUpdate(client, contentLength, device, hash, token);
    else if (strcmp(method, "GET") == 0)
        sendPage(client);
    else {
        sendStatus(client, 404, "Not Found", "text/plain; charset=utf-8");
        client.print("Nicht gefunden.");
    }'''
new_routes = '''    lastActivityMs = millis() ? millis() : 1;
    if (strcmp(method, "POST") == 0 && strcmp(path, "/auth") == 0) {
        sendPortalAuth(client, pin);
        return;
    }
    const bool pageRequest = strcmp(method, "GET") == 0 &&
                             (strcmp(path, "/") == 0 || strcmp(path, "/generate_204") == 0 ||
                              strcmp(path, "/hotspot-detect.html") == 0 || strcmp(path, "/connecttest.txt") == 0 ||
                              strcmp(path, "/ncsi.txt") == 0);
    if (pageRequest) {
        sendPage(client);
        return;
    }
    if (!requestSessionValid(cookie, token)) {
        sendAuthRequired(client);
        return;
    }
    if (strcmp(method, "GET") == 0 && (strcmp(path, "/status") == 0 || strcmp(path, "/live.json") == 0))
        sendJsonStatus(client);
    else if (strcmp(method, "GET") == 0 && strcmp(path, "/nodes.json") == 0)
        sendNodesJson(client);
    else if (strcmp(method, "GET") == 0 && strncmp(path, "/mgrs?", 6) == 0)
        sendMgrs(client, path);
    else if (strcmp(method, "GET") == 0 && strcmp(path, "/log") == 0)
        sendLog(client);
    else if (strcmp(method, "GET") == 0 && strcmp(path, "/track.geojson") == 0)
        sendTrack(client);
    else if (strcmp(method, "POST") == 0 && strcmp(path, "/track/clear") == 0)
        clearTrack(client, token);
    else if (strcmp(method, "POST") == 0 && strcmp(path, "/update") == 0)
        receiveUpdate(client, contentLength, device, hash, token);
    else if (strcmp(method, "GET") == 0)
        sendPage(client);
    else {
        sendStatus(client, 404, "Not Found", "text/plain; charset=utf-8");
        client.print("Nicht gefunden.");
    }'''
repl(web, old_routes, new_routes)

repl(web, '''bool softApReady()
{
    const wifi_mode_t mode = WiFi.getMode();
    return (mode == WIFI_AP || mode == WIFI_AP_STA) && WiFi.softAPIP() == IPAddress(192, 168, 4, 1);
}''',
     '''bool softApReady()
{
    return WiFi.getMode() == WIFI_AP && WiFi.softAPIP() == IPAddress(192, 168, 4, 1);
}''')
repl(web, '''bool startSoftApAttempt(uint8_t attempt)
{
    WiFi.softAPdisconnect(false);
    if (!hadStation) {
        WiFi.disconnect(true, false);
        WiFi.mode(WIFI_OFF);
        delay(100);
    }

    const wifi_mode_t wantedMode = hadStation ? WIFI_AP_STA : WIFI_AP;
    const bool modeOk = WiFi.mode(wantedMode);
    delay(120);''',
     '''bool startSoftApAttempt(uint8_t attempt)
{
    WiFi.softAPdisconnect(false);
    WiFi.disconnect(true, false);
    WiFi.mode(WIFI_OFF);
    delay(100);
    const bool modeOk = WiFi.mode(WIFI_AP);
    delay(120);''')
repl(web, '''    hadStation = WiFi.status() == WL_CONNECTED;
    WiFi.persistent(false);
    serviceError[0] = 0;''',
     '''    jarnsen::serviceSecurityInit();
    if (!jarnsen::serviceSecurityWifiAllowed()) {
        snprintf(serviceError, sizeof(serviceError), "%s",
                 jarnsen::serviceSecurityLocked() ? "Node ist voll gesperrt" : "WLAN für diese Rolle gesperrt");
        logEvent("WLAN_SERVICE_REJECT", serviceError);
        return false;
    }
    WiFi.persistent(false);
    portalAuthorized = false;
    stopCaptiveDns();
    serviceError[0] = 0;''')
repl(web, '        WiFi.softAPdisconnect(false);\n        WiFi.mode(hadStation ? WIFI_STA : WIFI_OFF);',
     '        WiFi.softAPdisconnect(false);\n        WiFi.disconnect(true, false);\n        WiFi.mode(WIFI_OFF);')
repl(web, '    dnsServer.start(53, "*", IPAddress(192, 168, 4, 1));\n    httpServer.begin();',
     '    dnsServer.start(53, "*", IPAddress(192, 168, 4, 1));\n    captiveDnsActive = true;\n    captiveDnsStartedMs = millis() ? millis() : 1;\n    httpServer.begin();')
repl(web, '''    dnsServer.stop();
    httpServer.end();
    WiFi.softAPdisconnect(false);
    WiFi.mode(hadStation ? WIFI_STA : WIFI_OFF);
    serviceActive = false;''',
     '''    stopCaptiveDns();
    httpServer.end();
    WiFi.softAPdisconnect(false);
    WiFi.disconnect(true, false);
    WiFi.mode(WIFI_OFF);
    portalAuthorized = false;
    serviceActive = false;''')
repl(web, '''    dnsServer.processNextRequest();
    WiFiClient client = httpServer.available();
    if (client) {
        handleClient(client);
        client.flush();
        client.stop();
    }
    if (!updateInProgress && !Throttle::isWithinTimespanMs(lastActivityMs, IDLE_TIMEOUT_MS))
        jarnsenServiceWebStop();''',
     '''    if (!updateInProgress && jarnsen::serviceSecurityLocked()) {
        jarnsenServiceWebStop();
        return;
    }
    if (captiveDnsActive) {
        dnsServer.processNextRequest();
        if (!Throttle::isWithinTimespanMs(captiveDnsStartedMs, CAPTIVE_DNS_GRACE_MS))
            stopCaptiveDns();
    }
    WiFiClient client = httpServer.available();
    if (client) {
        stopCaptiveDns();
        handleClient(client);
        client.flush();
        client.stop();
    }
    if (!updateInProgress && !Throttle::isWithinTimespanMs(lastActivityMs, IDLE_TIMEOUT_MS))
        jarnsenServiceWebStop();''')

repl("src/mesh/http/JarnsenServiceWeb.h",
     '#if defined(ARCH_ESP32) && HAS_WIFI && (defined(_VARIANT_HELTEC_V3) || defined(HELTEC_TRACKER_V1_1))\n',
     '#if defined(ARCH_ESP32) && HAS_WIFI && (defined(_VARIANT_HELTEC_V3) || defined(_VARIANT_HELTEC_V4) || defined(HELTEC_TRACKER_V1_1))\n')

# Tracker: preserve existing 1.2 s service long press, add short-short-third-hold 3 s full lock.
tracker = "src/vehicle/TrackerCommonPolicy.cpp"
repl(tracker, '#include "jarnsen/core/power/JarnsenPowerPolicy.h"\n',
     '#include "jarnsen/core/power/JarnsenPowerPolicy.h"\n#include "jarnsen/core/service/JarnsenServiceSecurity.h"\n')
repl(tracker, '#ifndef TRACKER_COMMON_BUTTON_LONG_MS\n#define TRACKER_COMMON_BUTTON_LONG_MS 1200UL\n#endif',
     '#ifndef TRACKER_COMMON_BUTTON_LONG_MS\n#define TRACKER_COMMON_BUTTON_LONG_MS 1200UL\n#endif\n'
     '#define TRACKER_COMMON_LOCK_HOLD_MS 3000UL\n#define TRACKER_COMMON_LOCK_SEQUENCE_GAP_MS 900UL\n#define TRACKER_COMMON_PIN_BLOCK_MS 5000UL')
repl(tracker, '''bool buttonWasPressed = false;
bool openedServiceThisPress = false;
uint32_t buttonPressedSinceMs = 0;
uint32_t buttonHighSinceMs = 0;
bool buttonLongHandled = false;''',
     '''bool buttonWasPressed = false;
bool openedServiceThisPress = false;
uint32_t buttonPressedSinceMs = 0;
uint32_t buttonHighSinceMs = 0;
bool buttonLongHandled = false;
uint8_t lockTapCount = 0;
uint32_t lockSequenceDeadlineMs = 0;
bool lockGestureArmed = false;
bool lockGestureHandled = false;
uint8_t pinDigits[6] = {};
uint8_t pinIndex = 0;
uint8_t pinDigit = 0;
uint32_t pinBlockedUntilMs = 0;
uint32_t lastSecurityBannerMs = 0;''')

text = rd(tracker)
if "void resetLockSequence()" not in text:
    anchor = "void bluetoothOn()\n{"
    helpers = r'''void bluetoothOn();
void bluetoothOff();
void showTrackerScreen();

void resetLockSequence()
{
    lockTapCount = 0;
    lockSequenceDeadlineMs = 0;
    lockGestureArmed = false;
    lockGestureHandled = false;
}

void recordLockTap(uint32_t now)
{
    if (jarnsen::serviceSecurityLocked()) {
        resetLockSequence();
        return;
    }
    if (lockTapCount == 0 || lockSequenceDeadlineMs == 0 || (int32_t)(now - lockSequenceDeadlineMs) > 0)
        lockTapCount = 1;
    else if (lockTapCount < 2)
        lockTapCount++;
    lockSequenceDeadlineMs = now + TRACKER_COMMON_LOCK_SEQUENCE_GAP_MS;
}

void resetPinEntry()
{
    memset(pinDigits, 0, sizeof(pinDigits));
    pinIndex = 0;
    pinDigit = 0;
}

void showSecurityBanner(bool wakeScreen)
{
    if (!screen || !bootHandoffComplete)
        return;
    const uint32_t now = millis();
    char banner[72] = {};
    if (pinBlockedUntilMs != 0 && (int32_t)(pinBlockedUntilMs - now) > 0) {
        const uint32_t seconds = ((pinBlockedUntilMs - now) + 999U) / 1000U;
        snprintf(banner, sizeof(banner), "NODE GESPERRT\nPIN FALSCH - %us", (unsigned)seconds);
    } else {
        snprintf(banner, sizeof(banner), "NODE GESPERRT\nPIN %u/6  ZIFFER %u", (unsigned)(pinIndex + 1U),
                 (unsigned)pinDigit);
    }
    if (wakeScreen && !screen->isScreenOn())
        screen->setOn(true);
    screen->showSimpleBanner(banner, 5000U);
    lastSecurityBannerMs = now ? now : 1;
}

void enterFullLock()
{
    if (!jarnsen::serviceSecurityLock())
        return;
    jarnsenServiceWebStop();
    trackerServiceMenuForceClose();
    bluetoothOff();
    resetPinEntry();
    pinBlockedUntilMs = 0;
    resetLockSequence();
    lockGestureHandled = true;
    trackerDiagLog("SECURITY", "LOCKED_FULL");
    showSecurityBanner(true);
}

void nextPinDigit()
{
    const uint32_t now = millis();
    if (pinBlockedUntilMs != 0 && (int32_t)(pinBlockedUntilMs - now) > 0) {
        showSecurityBanner(true);
        return;
    }
    pinBlockedUntilMs = 0;
    pinDigit = (uint8_t)((pinDigit + 1U) % 10U);
    showSecurityBanner(true);
}

void confirmPinDigit()
{
    const uint32_t now = millis();
    if (pinBlockedUntilMs != 0 && (int32_t)(pinBlockedUntilMs - now) > 0) {
        showSecurityBanner(true);
        return;
    }
    pinBlockedUntilMs = 0;
    pinDigits[pinIndex++] = pinDigit;
    pinDigit = 0;
    if (pinIndex < 6) {
        showSecurityBanner(true);
        return;
    }
    uint32_t entered = 0;
    for (uint8_t i = 0; i < 6; i++)
        entered = entered * 10U + pinDigits[i];
    resetPinEntry();
    if (!jarnsen::serviceSecurityUnlock(entered)) {
        pinBlockedUntilMs = now + TRACKER_COMMON_PIN_BLOCK_MS;
        trackerDiagLog("SECURITY", "PIN_REJECT");
        showSecurityBanner(true);
        return;
    }
    pinBlockedUntilMs = 0;
    trackerDiagLog("SECURITY", "UNLOCKED");
    bluetoothOn();
    showTrackerScreen();
}

'''
    if anchor not in text:
        raise SystemExit("Tracker helper anchor missing")
    wr(tracker, text.replace(anchor, helpers + anchor, 1))

repl(tracker, '''    if (screen) {
        screen->setOn(true);
        if (!trackerServiceMenuActive())
            trackerStatusRequestFocus();
        screen->runNow();
    }''',
     '''    if (screen) {
        screen->setOn(true);
        if (jarnsen::serviceSecurityLocked()) {
            trackerServiceMenuForceClose();
            showSecurityBanner(false);
            return;
        }
        if (!trackerServiceMenuActive())
            trackerStatusRequestFocus();
        screen->runNow();
    }''')
repl(tracker, '''    bluetoothOn();
    trackerDiagLog("BT_SERVICE", "opened/resumed");
    showTrackerScreen();''',
     '''    jarnsen::serviceSecurityInit();
    if (jarnsen::serviceSecurityLocked()) {
        bluetoothOff();
        resetPinEntry();
    } else {
        bluetoothOn();
    }
    trackerDiagLog("BT_SERVICE", jarnsen::serviceSecurityLocked() ? "locked/local-pin" : "opened/resumed");
    showTrackerScreen();''')
repl(tracker, '''    trackerServiceMenuForceClose();
    bluetoothOff();''',
     '''    trackerServiceMenuForceClose();
    jarnsenServiceWebStop();
    bluetoothOff();''')
repl(tracker, '''        jarnsenServiceWebPump();
        rememberCurrentPosition();''',
     '''        jarnsenServiceWebPump();
        jarnsen::serviceSecurityPump();
        rememberCurrentPosition();
        if (jarnsen::serviceSecurityLocked() && serviceActive && displayVisible && screen && screen->isScreenOn() &&
            (lastSecurityBannerMs == 0 || (uint32_t)(now - lastSecurityBannerMs) >= 4000U))
            showSecurityBanner(false);''')
repl(tracker, '''                openedServiceThisPress = false;
                buttonLongHandled = false;
                if (serviceActive) {''',
     '''                openedServiceThisPress = false;
                buttonLongHandled = false;
                lockGestureHandled = false;
                lockGestureArmed = !jarnsen::serviceSecurityLocked() && lockTapCount == 2 && lockSequenceDeadlineMs != 0 &&
                                   (int32_t)(lockSequenceDeadlineMs - now) >= 0;
                if (serviceActive) {''')
old_long = '''            if (serviceActive && !buttonLongHandled && buttonPressedSinceMs != 0 &&
                (uint32_t)(now - buttonPressedSinceMs) >= TRACKER_COMMON_BUTTON_LONG_MS) {
                serviceLastActivityMs = now;
                resetDisplayWindow(now);
                if (trackerServiceMenuActive())
                    trackerServiceMenuSelect();
                else if (trackerServicePageVisible())
                    trackerServiceMenuOpen();
                buttonLongHandled = true;
                openedServiceThisPress = true;
            }'''
new_long = '''            if (serviceActive && !buttonLongHandled && buttonPressedSinceMs != 0) {
                const uint32_t heldMs = (uint32_t)(now - buttonPressedSinceMs);
                if (lockGestureArmed && heldMs >= TRACKER_COMMON_LOCK_HOLD_MS) {
                    serviceLastActivityMs = now;
                    resetDisplayWindow(now);
                    enterFullLock();
                    buttonLongHandled = true;
                    openedServiceThisPress = true;
                    lockGestureHandled = true;
                } else if (!lockGestureArmed && heldMs >= TRACKER_COMMON_BUTTON_LONG_MS) {
                    serviceLastActivityMs = now;
                    resetDisplayWindow(now);
                    if (jarnsen::serviceSecurityLocked())
                        confirmPinDigit();
                    else if (trackerServiceMenuActive())
                        trackerServiceMenuSelect();
                    else if (trackerServicePageVisible())
                        trackerServiceMenuOpen();
                    buttonLongHandled = true;
                    openedServiceThisPress = true;
                }
            }'''
repl(tracker, old_long, new_long)
old_short = '''                    if (!openedServiceThisPress && !buttonLongHandled) {
                        if (trackerServiceMenuActive())
                            trackerServiceMenuShortPress();
                        else if (bootHandoffComplete && screen) {
                            screen->showNextFrame();
                            screen->runNow();
                        }
                    }
                }
                buttonWasPressed = false;
                openedServiceThisPress = false;
                buttonPressedSinceMs = 0;
                buttonHighSinceMs = 0;
                buttonLongHandled = false;'''
new_short = '''                    if (!openedServiceThisPress && !buttonLongHandled) {
                        if (jarnsen::serviceSecurityLocked())
                            nextPinDigit();
                        else if (trackerServiceMenuActive())
                            trackerServiceMenuShortPress();
                        else if (bootHandoffComplete && screen) {
                            screen->showNextFrame();
                            screen->runNow();
                        }
                    }
                    if (!buttonLongHandled && !jarnsen::serviceSecurityLocked()) {
                        if (lockGestureArmed)
                            resetLockSequence();
                        recordLockTap(releaseNow);
                    } else if (lockGestureHandled || jarnsen::serviceSecurityLocked()) {
                        resetLockSequence();
                    }
                }
                buttonWasPressed = false;
                openedServiceThisPress = false;
                buttonPressedSinceMs = 0;
                buttonHighSinceMs = 0;
                buttonLongHandled = false;
                lockGestureArmed = false;
                lockGestureHandled = false;'''
repl(tracker, old_short, new_short)

for path, needles in {
    web: ["/live.json", "CAPTIVE_DNS_GRACE_MS", "X-Jarnsen-Pin", "JARN_SESSION", "WiFi.mode(WIFI_AP)", "serviceSecurityWifiAllowed"],
    tracker: ["TRACKER_COMMON_LOCK_HOLD_MS 3000UL", "enterFullLock", "confirmPinDigit", "serviceSecurityPump"],
    "src/nimble/NimbleBluetooth.cpp": ["PairingMode_FIXED_PIN", "jarnsen::kJarnsenUserPin"],
}.items():
    data = rd(path)
    for needle in needles:
        if needle not in data:
            raise SystemExit(f"{path}: final check missing {needle}")

print("Applied JARN captive portal/WLAN/User-PIN/full-lock/Bluetooth-PIN migration")
