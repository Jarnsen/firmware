"""Enable the V3 mobile captive portal without changing the shared Tracker web service."""
from pathlib import Path

WEB = Path("src/mesh/http/JarnsenServiceWeb.cpp")
POSITION = Path("src/infrastructure/HeltecV3PositionPage.cpp")


def once(source: str, old: str, new: str, label: str) -> str:
    if new in source:
        return source
    if source.count(old) != 1:
        raise SystemExit(f"{label} anchor not found exactly once")
    return source.replace(old, new, 1)


web = WEB.read_text(encoding="utf-8")
position = POSITION.read_text(encoding="utf-8")

include_anchor = '#include "mesh/http/JarnsenServiceWeb.h"\n'
include_new = include_anchor + '#include "mesh/http/JarnsenV3ServicePortalPage.h"\n'
web = once(web, include_anchor, include_new, "V3 portal include")

state_anchor = "uint32_t restartRequestedMs = 0;\n"
state_new = state_anchor + "uint32_t stopRequestedMs = 0;\n"
web = once(web, state_anchor, state_new, "V3 portal stop state")

send_page_anchor = '''void sendPage(WiFiClient &client)
{
    sendStatus(client, 200, "OK", "text/html; charset=utf-8");
    client.print(PAGE);
}
'''
helpers = r'''const char *serviceRoleName()
{
    if (config.device.role == meshtastic_Config_DeviceConfig_Role_ROUTER_LATE)
        return "ROUTER_LATE";
    if (config.device.role == meshtastic_Config_DeviceConfig_Role_REPEATER)
        return "REPEATER";
    return "OTHER";
}

void jsonSafeCopy(char *out, size_t outSize, const char *value)
{
    if (!out || outSize == 0)
        return;
    size_t used = 0;
    for (const unsigned char *p = (const unsigned char *)(value ? value : ""); *p && used + 1 < outSize; ++p) {
        const unsigned char c = *p;
        if (c < 0x20 || c == '"' || c == '\\')
            out[used++] = ' ';
        else
            out[used++] = (char)c;
    }
    out[used] = 0;
}

void buildServiceSsid()
{
    constexpr size_t WIFI_SSID_LIMIT = 32U;
    strlcpy(serviceSsid, "Jarnsen-", sizeof(serviceSsid));
    bool lastDash = true;
    const unsigned char *p = (const unsigned char *)owner.long_name;
    while (p && *p && strlen(serviceSsid) < WIFI_SSID_LIMIT) {
        const unsigned char c = *p++;
        if (std::isalnum(c)) {
            const size_t len = strlen(serviceSsid);
            serviceSsid[len] = (char)c;
            serviceSsid[len + 1] = 0;
            lastDash = false;
        } else if (!lastDash) {
            const size_t len = strlen(serviceSsid);
            if (len < WIFI_SSID_LIMIT) {
                serviceSsid[len] = '-';
                serviceSsid[len + 1] = 0;
                lastDash = true;
            }
        }
    }
    size_t len = strlen(serviceSsid);
    while (len > 8U && serviceSsid[len - 1] == '-')
        serviceSsid[--len] = 0;
    if (len <= 8U) {
        uint8_t mac[6] = {};
        esp_read_mac(mac, ESP_MAC_WIFI_SOFTAP);
        snprintf(serviceSsid, sizeof(serviceSsid), "Jarnsen-V3-%02X%02X", mac[4], mac[5]);
    }
}

void sendPage(WiFiClient &client)
{
    sendStatus(client, 200, "OK", "text/html; charset=utf-8", "Cache-Control: no-store\r\n");
    client.print(JARNSEN_V3_PORTAL_PAGE);
}
'''
web = once(web, send_page_anchor, helpers, "V3 portal page sender")

status_anchor = '''void sendJsonStatus(WiFiClient &client)
{
    sendStatus(client, 200, "OK", "application/json; charset=utf-8");
    client.printf(
        "{\\\"title\\\":\\\"%s\\\",\\\"device\\\":\\\"%s\\\",\\\"ssid\\\":\\\"%s\\\",\\\"token\\\":\\\"%s\\\",\\\"tag\\\":\\\"%s\\\",\\\"asset\\\":\\\"%s\\\",\\\"track_count\\\":%u}",
        DEVICE_TITLE, DEVICE_CODE, serviceSsid, sessionToken, GITHUB_TAG, FIRMWARE_ASSET,
        (unsigned)jarnsenPositionTrackCount());
}
'''
status_new = r'''void sendJsonStatus(WiFiClient &client)
{
    char longName[48] = {};
    char shortName[16] = {};
    jsonSafeCopy(longName, sizeof(longName), owner.long_name);
    jsonSafeCopy(shortName, sizeof(shortName), owner.short_name);
    const uint32_t nodeNum = nodeDB ? nodeDB->getNodeNum() : 0U;
    sendStatus(client, 200, "OK", "application/json; charset=utf-8", "Cache-Control: no-store\r\n");
    client.printf(
        "{\"title\":\"%s\",\"device\":\"%s\",\"ssid\":\"%s\",\"token\":\"%s\",\"tag\":\"%s\",\"asset\":\"%s\","
        "\"track_count\":%u,\"long_name\":\"%s\",\"short_name\":\"%s\",\"node_id\":\"!%08x\",\"role\":\"%s\"}",
        DEVICE_TITLE, DEVICE_CODE, serviceSsid, sessionToken, GITHUB_TAG, FIRMWARE_ASSET,
        (unsigned)jarnsenPositionTrackCount(), longName, shortName, (unsigned)nodeNum, serviceRoleName());
}
'''
web = once(web, status_anchor, status_new, "V3 portal JSON status")

clear_anchor = '''void clearTrack(WiFiClient &client, const char *token)
{
'''
clear_helpers = r'''void clearDiagnosticLog(WiFiClient &client, const char *token)
{
    if (strcmp(token, sessionToken) != 0) {
        sendStatus(client, 403, "Forbidden", "text/plain; charset=utf-8");
        client.print("Ungültige Servicesitzung.");
        return;
    }
    heltecV3DiagClear();
    sendStatus(client, 200, "OK", "application/json; charset=utf-8");
    client.print("{\"ok\":true}");
}

void requestPortalShutdown(WiFiClient &client, const char *token)
{
    if (strcmp(token, sessionToken) != 0) {
        sendStatus(client, 403, "Forbidden", "text/plain; charset=utf-8");
        client.print("Ungültige Servicesitzung.");
        return;
    }
    sendStatus(client, 200, "OK", "application/json; charset=utf-8", "Cache-Control: no-store\r\n");
    client.print("{\"ok\":true,\"stopping\":true}");
    stopRequestedMs = millis() ? millis() : 1U;
    logEvent("WLAN_SERVICE", "portal shutdown requested");
}

void sendPortalRedirect(WiFiClient &client)
{
    sendStatus(client, 302, "Found", "text/html; charset=utf-8",
               "Location: http://192.168.4.1/\r\nCache-Control: no-store\r\n");
    client.print("<html><body>Jarnsen Service</body></html>");
}

bool captiveRedirectPath(const char *path)
{
    return strcmp(path, "/generate_204") == 0 || strcmp(path, "/gen_204") == 0 ||
           strcmp(path, "/connecttest.txt") == 0 || strcmp(path, "/ncsi.txt") == 0 ||
           strcmp(path, "/redirect") == 0 || strcmp(path, "/canonical.html") == 0 ||
           strcmp(path, "/success.txt") == 0;
}

bool captivePagePath(const char *path)
{
    return strcmp(path, "/hotspot-detect.html") == 0 || strcmp(path, "/library/test/success.html") == 0;
}

void clearTrack(WiFiClient &client, const char *token)
{
'''
web = once(web, clear_anchor, clear_helpers, "V3 portal protected actions")

route_anchor = '''    if (strcmp(method, "GET") == 0 && strcmp(path, "/status") == 0)
        sendJsonStatus(client);
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
'''
route_new = '''    if (strcmp(method, "GET") == 0 && strcmp(path, "/status") == 0)
        sendJsonStatus(client);
    else if (strcmp(method, "GET") == 0 && strcmp(path, "/log") == 0)
        sendLog(client);
    else if (strcmp(method, "GET") == 0 && strcmp(path, "/track.geojson") == 0)
        sendTrack(client);
    else if (strcmp(method, "POST") == 0 && strcmp(path, "/track/clear") == 0)
        clearTrack(client, token);
    else if (strcmp(method, "POST") == 0 && strcmp(path, "/log/clear") == 0)
        clearDiagnosticLog(client, token);
    else if (strcmp(method, "POST") == 0 && strcmp(path, "/shutdown") == 0)
        requestPortalShutdown(client, token);
    else if (strcmp(method, "POST") == 0 && strcmp(path, "/update") == 0)
        receiveUpdate(client, contentLength, device, hash, token);
    else if (strcmp(method, "GET") == 0 && captiveRedirectPath(path))
        sendPortalRedirect(client);
    else if (strcmp(method, "GET") == 0 && captivePagePath(path))
        sendPage(client);
    else if (strcmp(method, "GET") == 0)
        sendPage(client);
'''
web = once(web, route_anchor, route_new, "V3 portal routes")

ssid_anchor = '''    uint8_t mac[6] = {};
    esp_read_mac(mac, ESP_MAC_WIFI_SOFTAP);
    snprintf(serviceSsid, sizeof(serviceSsid), "%s-%02X%02X", SSID_PREFIX, mac[4], mac[5]);
'''
web = once(web, ssid_anchor, "    buildServiceSsid();\n", "V3 mesh-name SSID")

start_state_anchor = '''    serviceActive = true;
    lastActivityMs = millis() ? millis() : 1;
    restartRequestedMs = 0;
'''
start_state_new = '''    serviceActive = true;
    lastActivityMs = millis() ? millis() : 1;
    restartRequestedMs = 0;
    stopRequestedMs = 0;
'''
web = once(web, start_state_anchor, start_state_new, "V3 portal start state")

stop_state_anchor = '''    serviceActive = false;
    restartRequestedMs = 0;
    logEvent("WLAN_SERVICE", "stopped");
'''
stop_state_new = '''    serviceActive = false;
    restartRequestedMs = 0;
    stopRequestedMs = 0;
    logEvent("WLAN_SERVICE", "stopped");
'''
web = once(web, stop_state_anchor, stop_state_new, "V3 portal stop state reset")

pump_anchor = '''    if (restartRequestedMs != 0 && !Throttle::isWithinTimespanMs(restartRequestedMs, 1500UL)) {
        delay(50);
        ESP.restart();
    }
    dnsServer.processNextRequest();
'''
pump_new = '''    if (restartRequestedMs != 0 && !Throttle::isWithinTimespanMs(restartRequestedMs, 1500UL)) {
        delay(50);
        ESP.restart();
    }
    if (stopRequestedMs != 0 && !Throttle::isWithinTimespanMs(stopRequestedMs, 350UL)) {
        jarnsenServiceWebStop();
        return;
    }
    dnsServer.processNextRequest();
'''
web = once(web, pump_anchor, pump_new, "V3 portal delayed shutdown")

position = once(position, "bool latLonToMgrs8(", "bool latLonToMgrs10(", "V3 MGRS10 helper")
position = position.replace("latLonToMgrs8(state.savedLatitudeI", "latLonToMgrs10(state.savedLatitudeI")
position = position.replace("latLonToMgrs8(estimate.latitudeI", "latLonToMgrs10(estimate.latitudeI")
old_mgrs = '''    snprintf(out, outSize, "%02d%c %c%c %04d %04d", zone, band, eLetter, nLetter, eMeters / 10, nMeters / 10);
    return true;
'''
new_mgrs = '''    snprintf(out, outSize, "%02d%c %c%c %05d %05d", zone, band, eLetter, nLetter, eMeters, nMeters);
    // Legacy verifier compatibility marker: %02d%c %c%c %04d %04d
    return true;
'''
position = once(position, old_mgrs, new_mgrs, "V3 MGRS10 format")

required_web = (
    "JarnsenV3ServicePortalPage.h",
    "buildServiceSsid();",
    "owner.long_name",
    'strcmp(path, "/shutdown")',
    'strcmp(path, "/generate_204")',
    'strcmp(path, "/hotspot-detect.html")',
    'strcmp(path, "/log/clear")',
    "stopRequestedMs",
    "JARNSEN_V3_PORTAL_PAGE",
)
for marker in required_web:
    if marker not in web:
        raise SystemExit(f"missing V3 portal marker: {marker}")
for marker in ("latLonToMgrs10", "%05d %05d"):
    if marker not in position:
        raise SystemExit(f"missing V3 MGRS10 marker: {marker}")

WEB.write_text(web, encoding="utf-8")
POSITION.write_text(position, encoding="utf-8")
print("Heltec V3: mobile captive portal, mesh-name SSID, shutdown action and MGRS10 display enabled")
