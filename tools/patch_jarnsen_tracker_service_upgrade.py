"""Wire the Tracker V1.1 service upgrades into the consolidated Meshtastic sources.

This build-scoped patch keeps the Tracker's existing motion/GNSS/deep-sleep,
A/B antenna test, MGRS and power-monitor code unchanged. It only adds:
- queued BLE/UI -> WLAN handover,
- WLANSTART on the encrypted Jarnsen control characteristic,
- passive mesh-health observation,
- the Tracker captive service portal and protected service actions,
- persistent service/boot health counters.
"""
from pathlib import Path

COMMON = Path("src/vehicle/TrackerCommonPolicy.cpp")
STATUS = Path("src/vehicle/TrackerStatusModule.cpp")
NIMBLE = Path("src/nimble/NimbleBluetooth.cpp")
RADIO = Path("src/mesh/RadioLibInterface.cpp")
WEB = Path("src/mesh/http/JarnsenServiceWeb.cpp")


def once(source: str, old: str, new: str, label: str) -> str:
    if new in source:
        return source
    if source.count(old) != 1:
        raise SystemExit(f"{label} anchor not found exactly once")
    return source.replace(old, new, 1)


def patch_common(source: str) -> str:
    include = '#include "vehicle/TrackerPowerMonitor.h"\n'
    source = once(
        source,
        include,
        include + '#include "vehicle/TrackerServiceUpgrade.h"\n',
        "TrackerCommon service-upgrade include",
    )
    source = once(
        source,
        '    trackerDiagLog("BT_SERVICE", "opened/resumed");\n',
        '    trackerDiagLog("BT_SERVICE", "opened/resumed");\n    trackerServiceUpgradeNoteServiceOpen();\n',
        "Tracker service-open counter",
    )
    source = once(
        source,
        '        processBleExportFeedback(now);\n        trackerServiceMenuPump();\n',
        '        processBleExportFeedback(now);\n        trackerServiceUpgradeTick();\n        trackerServiceMenuPump();\n',
        "Tracker service-upgrade pump",
    )
    source = once(
        source,
        '    trackerDiagInit();\n    trackerAntennaTestInit();\n',
        '    trackerDiagInit();\n    trackerServiceUpgradeInit();\n    trackerAntennaTestInit();\n',
        "Tracker service-upgrade init",
    )
    return source


def patch_status(source: str) -> str:
    include = '#include "vehicle/TrackerStatusModule.h"\n'
    source = once(
        source,
        include,
        include + '#include "vehicle/TrackerServiceUpgrade.h"\n',
        "TrackerStatus service-upgrade include",
    )
    source = once(
        source,
        '                if (jarnsenServiceWebActive())\n                    jarnsenServiceWebStop();\n                else\n                    jarnsenServiceWebStart();\n',
        '                if (jarnsenServiceWebActive())\n                    jarnsenServiceWebStop();\n                else\n                    trackerServiceUpgradeRequestWlan();\n',
        "Tracker WLAN menu handover",
    )
    return source


def patch_nimble(source: str) -> str:
    include = '#include "vehicle/TrackerStatusModule.h"\n'
    source = once(
        source,
        include,
        include + '#include "vehicle/TrackerServiceUpgrade.h"\n',
        "NimBLE Tracker service-upgrade include",
    )
    marker = 'memcmp(data, "WLANSTART", 9)'
    if marker not in source:
        anchor = '''        } else if (length == 7 && memcmp(data, "RELEASE", 7) == 0) {
            jarnsenOtaQueueHold = false;
            setJarnsenBleQueueHold(false);
            characteristic->setValue((const uint8_t *)"IDLE", 4);
'''
        if source.count(anchor) != 1:
            raise SystemExit("Tracker WLANSTART control anchor not found exactly once")
        replacement = anchor + '''#if defined(HELTEC_TRACKER_V1_1)
        } else if (length == 9 && memcmp(data, "WLANSTART", 9) == 0) {
            const bool queued = trackerServiceUpgradeRequestWlan();
            const char *status = queued ? "WLAN_ACK" : "LOCKED";
            characteristic->setValue((const uint8_t *)status, strlen(status));
#endif
'''
        source = source.replace(anchor, replacement, 1)
    return source


def patch_radio(source: str) -> str:
    if '#include "vehicle/TrackerMeshHealth.h"' not in source:
        anchors = (
            '#include "vehicle/TrackerAntennaTest.h"\n',
            '#include "vehicle/TrackerCommonPolicy.h"\n',
        )
        for anchor in anchors:
            if source.count(anchor) == 1:
                source = source.replace(anchor, anchor + '#include "vehicle/TrackerMeshHealth.h"\n', 1)
                break
        else:
            raise SystemExit("RadioLib Tracker include anchor not found")
    call = 'trackerMeshHealthOnRadioPacket(*mp);'
    if call not in source:
        anchor = 'trackerAntennaOnRadioPacket(*mp);'
        if source.count(anchor) != 1:
            raise SystemExit("Tracker antenna receive callback anchor not found exactly once")
        source = source.replace(anchor, call + '\n        ' + anchor, 1)
    return source


def patch_web(source: str) -> str:
    include_anchor = '#include "vehicle/TrackerDiagnosticLog.h"\n'
    include_new = (
        include_anchor
        + '#include "vehicle/TrackerMeshHealth.h"\n'
        + '#include "vehicle/TrackerServiceUpgrade.h"\n'
        + '#include "mesh/http/JarnsenTrackerServicePortalPage.h"\n'
    )
    source = once(source, include_anchor, include_new, "Tracker web service includes")

    source = once(
        source,
        'uint32_t restartRequestedMs = 0;\n',
        'uint32_t restartRequestedMs = 0;\nuint32_t stopRequestedMs = 0;\n',
        "Tracker portal stop state",
    )

    send_page_old = '''void sendPage(WiFiClient &client)
{
    sendStatus(client, 200, "OK", "text/html; charset=utf-8");
    client.print(PAGE);
}
'''
    send_page_new = '''void sendPage(WiFiClient &client)
{
    sendStatus(client, 200, "OK", "text/html; charset=utf-8", "Cache-Control: no-store\\r\\n");
#if defined(HELTEC_TRACKER_V1_1)
    client.print(JARNSEN_TRACKER_PORTAL_PAGE);
#else
    client.print(PAGE);
#endif
}
'''
    source = once(source, send_page_old, send_page_new, "Tracker portal page sender")

    status_old = '''void sendJsonStatus(WiFiClient &client)
{
    sendStatus(client, 200, "OK", "application/json; charset=utf-8");
    client.printf(
        "{\\\"title\\\":\\\"%s\\\",\\\"device\\\":\\\"%s\\\",\\\"ssid\\\":\\\"%s\\\",\\\"token\\\":\\\"%s\\\",\\\"tag\\\":\\\"%s\\\",\\\"asset\\\":\\\"%s\\\",\\\"track_count\\\":%u}",
        DEVICE_TITLE, DEVICE_CODE, serviceSsid, sessionToken, GITHUB_TAG, FIRMWARE_ASSET,
        (unsigned)jarnsenPositionTrackCount());
}
'''
    status_new = r'''const char *trackerServiceRoleName()
{
#if defined(HELTEC_TRACKER_V1_1)
    return config.device.role == meshtastic_Config_DeviceConfig_Role_TAK_TRACKER ? "TAK_TRACKER" : "TAK";
#else
    return "OTHER";
#endif
}

void trackerJsonSafeCopy(char *out, size_t outSize, const char *value)
{
    if (!out || outSize == 0)
        return;
    size_t used = 0;
    for (const unsigned char *p = (const unsigned char *)(value ? value : ""); *p && used + 1 < outSize; ++p) {
        const unsigned char c = *p;
        out[used++] = (c < 0x20 || c == '"' || c == '\\') ? ' ' : (char)c;
    }
    out[used] = 0;
}

void sendJsonStatus(WiFiClient &client)
{
#if defined(HELTEC_TRACKER_V1_1)
    char longName[48] = {};
    char shortName[16] = {};
    char lastNode[12] = {};
    trackerJsonSafeCopy(longName, sizeof(longName), owner.long_name);
    trackerJsonSafeCopy(shortName, sizeof(shortName), owner.short_name);
    const uint32_t nodeNum = nodeDB ? nodeDB->getNodeNum() : 0U;
    const TrackerServiceHealthStats health = trackerServiceUpgradeHealth();
    const TrackerMeshHealthSummary mesh = trackerMeshHealthSummary();
    if (mesh.lastDirectNode)
        snprintf(lastNode, sizeof(lastNode), "!%08x", (unsigned)mesh.lastDirectNode);
    sendStatus(client, 200, "OK", "application/json; charset=utf-8", "Cache-Control: no-store\r\n");
    client.printf(
        "{\"title\":\"%s\",\"device\":\"%s\",\"ssid\":\"%s\",\"token\":\"%s\",\"tag\":\"%s\",\"asset\":\"%s\","
        "\"track_count\":%u,\"long_name\":\"%s\",\"short_name\":\"%s\",\"node_id\":\"!%08x\",\"role\":\"%s\","
        "\"health\":{\"boots\":%u,\"crashes\":%u,\"service\":%u,\"ble\":%u,\"wlan\":%u,\"wlan_fail\":%u,\"reset\":\"%s\"},"
        "\"mesh\":{\"observed\":%u,\"active15\":%u,\"active1h\":%u,\"active24\":%u,\"direct15\":%u,\"rx1h\":%u,"
        "\"total_rx\":%u,\"last_node\":\"%s\",\"last_rssi\":%d,\"last_snr_q4\":%d,\"last_age\":%u}}",
        DEVICE_TITLE, DEVICE_CODE, serviceSsid, sessionToken, GITHUB_TAG, FIRMWARE_ASSET,
        (unsigned)jarnsenPositionTrackCount(), longName, shortName, (unsigned)nodeNum, trackerServiceRoleName(),
        (unsigned)health.bootCount, (unsigned)health.crashResetCount, (unsigned)health.serviceOpenCount,
        (unsigned)health.bleConnectionCount, (unsigned)health.wlanStartCount, (unsigned)health.wlanFailureCount,
        trackerServiceUpgradeResetReasonText(), (unsigned)mesh.observedNodes, (unsigned)mesh.active15m, (unsigned)mesh.active1h,
        (unsigned)mesh.active24h, (unsigned)mesh.direct15m, (unsigned)mesh.rx1h, (unsigned)mesh.totalRx, lastNode,
        (int)mesh.lastDirectRssiDbm, (int)mesh.lastDirectSnrQ4, (unsigned)mesh.lastDirectAgeSecs);
#else
    sendStatus(client, 200, "OK", "application/json; charset=utf-8");
    client.printf(
        "{\"title\":\"%s\",\"device\":\"%s\",\"ssid\":\"%s\",\"token\":\"%s\",\"tag\":\"%s\",\"asset\":\"%s\",\"track_count\":%u}",
        DEVICE_TITLE, DEVICE_CODE, serviceSsid, sessionToken, GITHUB_TAG, FIRMWARE_ASSET,
        (unsigned)jarnsenPositionTrackCount());
#endif
}
'''
    source = once(source, status_old, status_new, "Tracker portal JSON status")

    clear_anchor = '''void clearTrack(WiFiClient &client, const char *token)
{
'''
    helpers = r'''void clearDiagnosticLog(WiFiClient &client, const char *token)
{
    if (strcmp(token, sessionToken) != 0) {
        sendStatus(client, 403, "Forbidden", "text/plain; charset=utf-8");
        client.print("Ungültige Servicesitzung.");
        return;
    }
#if defined(_VARIANT_HELTEC_V3)
    heltecV3DiagClear();
#else
    trackerDiagClear();
#endif
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
    client.print("<html><body>Jarnsen Tracker Service</body></html>");
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
    source = once(source, clear_anchor, helpers, "Tracker portal protected actions")

    route_old = '''    if (strcmp(method, "GET") == 0 && strcmp(path, "/status") == 0)
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
    source = once(source, route_old, route_new, "Tracker portal routes")

    source = once(
        source,
        '''    serviceActive = true;
    lastActivityMs = millis() ? millis() : 1;
    restartRequestedMs = 0;
''',
        '''    serviceActive = true;
    lastActivityMs = millis() ? millis() : 1;
    restartRequestedMs = 0;
    stopRequestedMs = 0;
''',
        "Tracker portal start state",
    )
    source = once(
        source,
        '''    serviceActive = false;
    restartRequestedMs = 0;
    logEvent("WLAN_SERVICE", "stopped");
''',
        '''    serviceActive = false;
    restartRequestedMs = 0;
    stopRequestedMs = 0;
    logEvent("WLAN_SERVICE", "stopped");
''',
        "Tracker portal stop state",
    )
    source = once(
        source,
        '''    if (restartRequestedMs != 0 && !Throttle::isWithinTimespanMs(restartRequestedMs, 1500UL)) {
        delay(50);
        ESP.restart();
    }
    dnsServer.processNextRequest();
''',
        '''    if (restartRequestedMs != 0 && !Throttle::isWithinTimespanMs(restartRequestedMs, 1500UL)) {
        delay(50);
        ESP.restart();
    }
    if (stopRequestedMs != 0 && !Throttle::isWithinTimespanMs(stopRequestedMs, 350UL)) {
        jarnsenServiceWebStop();
        return;
    }
    dnsServer.processNextRequest();
''',
        "Tracker portal delayed shutdown",
    )
    return source


files = {
    COMMON: patch_common,
    STATUS: patch_status,
    NIMBLE: patch_nimble,
    RADIO: patch_radio,
    WEB: patch_web,
}
for path, patcher in files.items():
    source = path.read_text(encoding="utf-8")
    patched = patcher(source)
    path.write_text(patched, encoding="utf-8")

required = {
    COMMON: ("trackerServiceUpgradeInit();", "trackerServiceUpgradeTick();", "trackerServiceUpgradeNoteServiceOpen();"),
    STATUS: ("trackerServiceUpgradeRequestWlan();",),
    NIMBLE: ('memcmp(data, "WLANSTART", 9)', '"WLAN_ACK"'),
    RADIO: ("trackerMeshHealthOnRadioPacket(*mp);",),
    WEB: ("JARNSEN_TRACKER_PORTAL_PAGE", 'strcmp(path, "/shutdown")', 'strcmp(path, "/log/clear")', "trackerMeshHealthSummary()"),
}
for path, markers in required.items():
    text = path.read_text(encoding="utf-8")
    for marker in markers:
        if marker not in text:
            raise SystemExit(f"missing Tracker service-upgrade marker in {path}: {marker}")

print("Tracker V1.1 service upgrade wired: WLAN handover, captive portal, mesh health, persistent counters")
