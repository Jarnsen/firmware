#!/usr/bin/env python3
"""HTTP-only Heltec V3 and zero-setup node-position safety contract."""
from pathlib import Path
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[1]
source = (ROOT / "src/mesh/http/JarnsenServiceWeb.cpp").read_text(encoding="utf-8")

required = (
    "JARNSEN_V3_HTTP_NODE_POSITION_NO_SETUP_V1",
    "constexpr bool SERVICE_HTTPS_ENABLED = false;",
    "constexpr bool SERVICE_HTTPS_ENABLED = true;",
    "const bool httpsReady = SERVICE_HTTPS_ENABLED ? startServiceHttps() : false;",
    'logEvent("WLAN_HTTPS", "disabled: V3 HTTP only, zero TLS allocation");',
    "https_supported",
    "JARNSEN_HTTP_AUTOMATIC_NODE_POSITION_V1",
    "nodeSelfPos=j.self&&j.self.has_position",
    "selfPos=ownCurrent?nodeSelfPos:null;",
    "httpNodeMode=info.https_supported===false;",
    "if(!httpNodeMode)setTimeout(async()=>{await checkHttpsTrust();startCertTrustWatch()}",
    "if(!httpNodeMode){if(window.isSecureContext)setTimeout(startPhoneGps,250)",
    "if(!document.hidden&&!httpNodeMode&&info?.tls_ready)",
    "Keine Node-Position vorhanden. Telefon-GPS ist im HTTP-Browser nicht verfügbar.",
    "Node-Position wird automatisch",
    "sendCaptiveApi(client);",
    "sendCaptiveRedirect(client,",
    "httpServer.begin();",
    "httpServer.available();",
    "const bool requestAuthorized = requestSessionValid(request.cookie, request.token);",
    "if (!requestAuthorized)",
    # JARNSEN TCP GPS integration: PIN gate must precede the TCP listener.
    "JARNSEN_MESHTASTIC_WIFI_TCP_V1",
    "JARNSEN_MESHTASTIC_TCP_AFTER_PIN_V1",
    "JARNSEN_MESHTASTIC_GPS_HELP_V1",
    "portalAuthorized && !serviceMeshtasticTcpActive",
    "initApiServer(); // Meshtastic PhoneAPI on TCP 4403.",
    "if (serviceMeshtasticTcpActive)",
    "deInitApiServer();",
    "isApiServerClientConnected()",
    "meshtastic_tcp_connected",
    "gpsAssistCard",
    "gpsGuideIosSteps",
    "gpsGuideAndroidSteps",
    "copyMeshtasticIp",
    "copyMeshtasticPort",
    "192.168.4.1",
    "4403",
    # JARNSEN_V3_SINGLE_SLOT_OTA_V2: guarded on-device OTA uses the inactive
    # partition and rejects unstable boot states or incompatible layouts.
    "JARNSEN_V3_SINGLE_SLOT_OTA_V2",
    "SERVICE_V3_APP_ONLY_UPDATE_ENABLED = true;",
    "esp_ota_get_state_partition(running, &runningState)",
    "runningState != ESP_OTA_IMG_VALID && runningState != ESP_OTA_IMG_UNDEFINED",
    "verifyServiceOtaLayout(size_t imageBytes, const char *&reason)",
    "esp_ota_get_running_partition()",
    "esp_ota_get_boot_partition()",
    "esp_ota_get_next_update_partition(nullptr)",
    "ESP_PARTITION_SUBTYPE_APP_OTA_0",
    "ESP_PARTITION_SUBTYPE_APP_OTA_1",
    "OTA-Slot oder aktive Bootpartition ist nicht sicher.",
    "ota_update_supported",
    'id="v3OtaBlocked"',
    "if (!verifyServiceOtaLayout(contentLength, otaError))",
    # Do not direct iOS users to Android-only settings.
    "Verfügbare Funkgeräte / Available Radios",
    "Manuell / Manual (+)",
    "192.168.4.1:4403",
    # JARNSEN_CAPTIVE_IOS_COMPLETE_AFTER_PIN_V1
    # A successful login must release iOS CNA instead of redirecting it
    # back to the PIN page; do not invent an upstream Internet connection.
    "JARNSEN_CAPTIVE_IOS_COMPLETE_AFTER_PIN_V1",
    'pathMatches(path, "/hotspot-detect.html")',
    "void sendCaptiveComplete(WiFiClient &client, const char *path, bool headOnly)",
    'client.print("<HTML><HEAD><TITLE>Success</TITLE></HEAD><BODY>Success</BODY></HTML>");',
    "if (isCaptiveProbe && portalAuthorized)",
    'logEvent("CAPTIVE_PROBE", "ios_complete_after_pin; local_only");',
    'logEvent("CAPTIVE_ROUTE", "foreign_host_after_pin_no_uplink");',
    "JARNSEN_SOFTAP_KEEP_ASSOCIATED_V1",
    "const bool stationAssociated = WiFi.softAPgetStationNum() > 0;",
    "!meshPhoneConnected && !stationAssociated",
    "JARNSEN_NO_FAKE_CELLULAR_ROUTE_V1",
    "INTERNET PRÜFEN",
    # Phone Internet must use mobile data without an AP-provided default route.
    "JARNSEN_V3_MOBILE_DATA_LOCAL_ROUTE_V1",
    "const bool localOnlyDhcp = configOk && configureServiceDhcp(false);",
    'v3_local_only_router_0',
    "JARNSEN_V3_CAPTIVE_DNS_RELEASE_V1",
    "POST_AUTH_DNS_GRACE_MS",
    "portalAuthorizedAtMs = millis() ? millis() : 1U;",
    "released_after_pin; external_dns_no_longer_hijacked",
    # 2026-10-13 regression: iOS captive session cannot launch Safari by 302,
    # stored mesh coordinates must not become a fresh own-position arrow,
    # and newlib sscanf("%lf") cannot be trusted for tapped map points.
    "JARNSEN_IOS_DIRECT_HANDOFF_RESTORE_V1",
    'logEvent("CAPTIVE_DNS", "released_at_authenticated_handoff");',
    'logEvent("SERVICE_AUTH", "handoff direct to WebUI");',
    "JARNSEN_V3_POSITION_FRESHNESS_PARITY_V1",
    "POSITION_FRESH_SECONDS=300",
    "hasFreshPosition(nodeSelfPos)",
    "Keine aktuelle Pos.",
    "JARNSEN_V3_MGRS_QUERY_STRTOD_V1",
    "parseMgrsCoordinates(path, latitude, longitude)",
    "MGRS nicht verfügbar (",
    "Node-WLAN ist ein",
)
# Meshtastic TCP is available only after the existing PIN gate.
# Meshtastic TCP is available only after the existing PIN gate.
tcp_header = (ROOT / "src/mesh/api/WiFiServerAPI.h").read_text(encoding="utf-8")
tcp_source = (ROOT / "src/mesh/api/WiFiServerAPI.cpp").read_text(encoding="utf-8")
server_header = (ROOT / "src/mesh/api/ServerAPI.h").read_text(encoding="utf-8")
if "isApiServerClientConnected()" not in tcp_header or "hasActiveClient()" not in tcp_source:
    raise SystemExit("V3 TCP GPS preflight FAIL: missing connected client accessor")
if "hasActiveClient() const" not in server_header:
    raise SystemExit("V3 TCP GPS preflight FAIL: server does not expose active socket status")

for marker in required:
    if marker not in source:
        raise SystemExit(f"V3 HTTP-position preflight FAIL: missing {marker}")

# Keep the DHCP configuration strictly before the AP accepts stations.
# DHCP restarts while an iPhone is associated caused instability on V3.
softap_start = source.split("bool startSoftApAttempt(uint8_t attempt)", 1)[1].split(
    "bool jarnsenServiceWebStart()", 1
)[0]
if softap_start.index("configureServiceDhcp(false)") < 0 or softap_start.index(
    "configureServiceDhcp(false)"
) >= softap_start.index("WiFi.softAP(serviceSsid"):
    raise SystemExit("V3 mobile-data preflight FAIL: DHCP not configured before AP association")

service_pump = source.split("void jarnsenServiceWebPump()", 1)[1].split(
    "bool jarnsenServiceWebActive()", 1
)[0]
if "configureServiceDhcp(" in service_pump:
    raise SystemExit("V3 mobile-data preflight FAIL: live DHCP restart")
if not ("portalAuthorized && portalAuthorizedAtMs != 0U" in service_pump
        and "stopCaptiveDns();" in service_pump):
    raise SystemExit("V3 mobile-data preflight FAIL: wildcard DNS not released after PIN")

# An authenticated captive handoff must go directly to '/'.
# Restore the old working route while keeping DHCP and Meshtastic TCP intact.
handoff = source.split("void sendPortalHandoff(WiFiClient &client, const char *path)", 1)[1].split(
    "void requestCellularInternet(WiFiClient &client)", 1
)[0]
if 'client.print("/\\r\\nConnection: close\\r\\n\\r\\n");' not in handoff:
    raise SystemExit("V3 iOS handoff FAIL: not redirecting directly to normal WebUI")
if "stopCaptiveDns();" not in handoff or handoff.index("stopCaptiveDns();") < handoff.index("strcmp(token, sessionToken)"):
    raise SystemExit("V3 iOS handoff FAIL: DNS release must follow successful PIN token check")
if "captive=1" in handoff or "safariHandoffHelp" in source:
    raise SystemExit("V3 iOS handoff FAIL: stale manual Safari interstitial")

display = (ROOT / "src/jarnsen/adapters/JarnsenDisplayRuntime.cpp").read_text(encoding="utf-8")
for token in ("JARNSEN_V3_DISPLAY_POSITION_PARITY_V1", "lastKnownOnly",
              "meshFresh", "getValidTime(RTCQualityDevice)", '"LETZTE"', '"POS ALT"'):
    if token not in display:
        raise SystemExit("V3 display-position parity FAIL: missing " + token)
if 'sscanf(path, "/mgrs?lat=%lf&lon=%lf"' in source:
    raise SystemExit("V3 MGRS preflight FAIL: stale floating-point sscanf parser")
if 'selfPos=nodeSelfPos;' in source:
    raise SystemExit("V3 position preflight FAIL: old mesh position rendered as live own GPS")

page = source.split('const char PAGE[] PROGMEM = R"JARN(', 1)[1].split(')JARN";', 1)[0]
javascript = page.split("<script>", 1)[1].split("</script>", 1)[0]
# A self-hosted GitHub runner can use its bundled Node.js 24 runtime for
# actions without exporting "node" into PATH. Try that bundled executable
# before skipping only the optional browser parse check.
node_executable = shutil.which("node")
if not node_executable:
    for bundled in ("node24", "node20"):
        candidate = Path.home() / "actions-runner" / "externals" / bundled / "bin" / "node"
        if candidate.is_file():
            node_executable = str(candidate)
            break
if node_executable:
    result = subprocess.run([node_executable, "--check", "-"], input=javascript,
                            text=True, capture_output=True, check=False)
    if result.returncode != 0:
        raise SystemExit("V3 HTTP-position preflight FAIL: browser JavaScript syntax: "
                         + result.stderr[-2000:])
else:
    print("JARNSEN V3 HTTP-position: Node.js CLI unavailable; browser parse check skipped")
print("JARNSEN V3 HTTP-only automatic node position preflight PASS")
