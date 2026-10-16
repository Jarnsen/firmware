#!/usr/bin/env python3
"""HTTP-only Heltec V3 and zero-setup node-position safety contract."""
import re
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
    "nodeSelfPos=localNode&&localNode.has_position",
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
    "copyMeshtasticTcp",
    "JARNSEN_V3_HTTP_TCP_COPY_V1",
    "JARNSEN_V3_NODE_LIST_SELF_NO_GPS_V1",
    "allNodes=localNode?[localNode,...remote]:remote;",
    "badge.tcpConnected",
    "classList.toggle('tcpConnected',connected)",
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
    # Restore the actual Oct 8 native-SoftAP DHCP path; later custom DHCP
    # configuration caused iOS captive regressions.
    # WebUI must explain failed logs and never show offline status as green.
    "JARNSEN_INTERNET_BADGE_TRISTATE_V1",
    ".online.offline",
    "b.classList.toggle('offline',state==='offline')",
    "JARNSEN_WEB_LOG_HTTP_RETRY_AND_IOS_SAVE_V1",
    "JARNSEN_HTTP_LOG_CHUNK_PARTIAL_WRITE_V1",
    "id=\"saveLogBtn\"",
    "saveNodeLog",
    "LOG_EXPORT",
    "JARNSEN_CAPTIVE_KNOWN_GOOD_DHCP_RESTORE_V2",
    "JARNSEN_SHARED_IOS_HANDOFF_DNS_GRACE_V1",
    "known_good_native_softap_dhcp",
    "JARNSEN_V3_CAPTIVE_DNS_RELEASE_V1",
    "POST_AUTH_DNS_GRACE_MS",
    "portalAuthorizedAtMs = millis() ? millis() : 1U;",
    "released_after_pin; external_dns_no_longer_hijacked",
    # 2026-10-13 regression: iOS captive session cannot launch Safari by 302,
    # stored mesh coordinates must not become a fresh own-position arrow,
    # and newlib sscanf("%lf") cannot be trusted for tapped map points.
    "JARNSEN_IOS_DIRECT_HANDOFF_RESTORE_V1",
    'logEvent("CAPTIVE_DNS", "handoff_dns_grace_until_post_auth_timeout");',
    'logEvent("SERVICE_AUTH", "handoff direct to WebUI");',
    "JARNSEN_V3_POSITION_FRESHNESS_PARITY_V1",
    "POSITION_FRESH_SECONDS=300",
    "hasFreshPosition(nodeSelfPos)",
    "Keine aktuelle Pos.",
    "JARNSEN_V3_MGRS_QUERY_STRTOD_V1",
    "parseMgrsCoordinates(path, latitude, longitude)",
    "MGRS nicht verfügbar (",
    "Node-WLAN ist ein",
    # JARNSEN_WEBUI_MOBILE_AUTORETRY_V1 + displayed actual firmware identity.
    "JARNSEN_WEBUI_MOBILE_AUTORETRY_V1",
    "internetProbeRetryStep",
    "internetProbePromise",
    "scheduleInternetProbe(retryMs)",
    "tileCache.delete(key)",
    "JARNSEN_WEBUI_INSTALLED_FW_IDENTITY_V1",
    "jarnsen::build::version",
    "jarnsen::build::gitSha",
    "jarnsen::build::buildNumber",
    'id="fwIdentity"',
    'id="fwDetail"',
    "info.firmware_version",
    "info.firmware_build",
    "info.firmware_sha",
    # Four-page WebUI navigation retains current map, TCP, logs and OTA controls.
    "JARNSEN_WEBUI_SECTION_NAV_V1",
    'data-service-tab="map"',
    'data-service-tab="network"',
    'data-service-tab="diagnostics"',
    'data-service-tab="firmware"',
    "function showServiceTab(tab)",
    "if($('mapCard').classList.contains('viewHidden'))return;",
)
# UI refactor safety: do not remove existing API-linked buttons/sections.
for required_id in ("mapCard", "gpsAssistCard", "connectionCard",
                    "logCard", "firmwareCard", "internetBadge", "cellularBtn",
                    "analyseBtn", "saveLogBtn", "githubBtn", "uploadBtn",
                    "meshtasticTcpBadge", "nodePanel", "mapCanvas"):
    if f'id="{required_id}"' not in source:
        raise SystemExit("JARNSEN WebUI navigation FAIL: missing UI ID "+required_id)
if 'jarnsen::build::version' not in source or '"firmware_version"' not in source.replace(r'\"', '"'):
    raise SystemExit("JARNSEN WebUI firmware identity FAIL: no live firmware metadata")
if "setInterval(()=>scheduleInternetProbe(0),30000)" not in source:
    raise SystemExit("JARNSEN WebUI Internet FAIL: ongoing browser status checks lost")

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

# Native log endpoint failure must remain distinguishable from a Safari
# download error and a partial WiFi write must not truncate HTTP chunk framing.
if "Logdownload fehlgeschlagen." in source:
    raise SystemExit("JARNSEN WebUI logging FAIL: old uninformative error still present")
if "http_rejected_backend_busy_or_unavailable" not in source:
    raise SystemExit("JARNSEN WebUI logging FAIL: missing backend 409 diagnostic")
if "sent < length && client.connected()" not in source:
    raise SystemExit("JARNSEN WebUI logging FAIL: missing partial-write retry loop")

# JARNSEN_V3_DIAG_HTTP_409_BACKEND_FIX_V1: V3 uses HELTEC_V3, not just
# _VARIANT_HELTEC_V3. The web backend must not silently choose no-op.
backend = (ROOT / "src/jarnsen/hardware/JarnsenDiagnosticBackend.cpp").read_text(encoding="utf-8")
generic_log = (ROOT / "src/jarnsen/core/service/JarnsenDiagnosticLog.cpp").read_text(encoding="utf-8")
for item in ("JARNSEN_V3_DIAG_HTTP_409_BACKEND_FIX_V1",
             "diagnosticLogStartWebExport", "diagnosticLogReadWebExport",
             "diagnosticLogCancelWebExport", "defined(HELTEC_V3)",
             "defined(HELTEC_TRACKER_V1_1)"):
    if item not in backend:
        raise SystemExit("V3 HTTP 409 backend FAIL: missing " + item)
if "HeltecV3DiagnosticLog.h" in backend or "heltecV3DiagStartBleExport" in backend:
    raise SystemExit("V3 HTTP 409 backend FAIL: references unavailable V3 BLE implementation")
for item in ("JARNSEN_SHARED_HTTP_LOG_SNAPSHOT_V1", "snapshotLocked = true;",
             "diagnosticLogUsbExportPending()", "releaseWebExport(WebExportPhase::DONE)",
             "webPreviousRemaining", "webCurrentRemaining", "FSCom.open(path, FILE_O_READ)"):
    if item not in generic_log:
        raise SystemExit("Shared HTTP diagnostic stream FAIL: missing " + item)
if "JARNSEN_CAPTIVE_DNS_LOW_TTL_CELLULAR_V1" not in source or "dnsServer.setTTL(1)" not in source:
    raise SystemExit("Captive cellular low-TTL FAIL: wildcard DNS TTL not bounded")
if "===JARNSEN_DIAG_LOG_END===" not in source:
    raise SystemExit("HTTP log completeness FAIL: Safari client does not verify export footer")

# JARNSEN_V3_CAPTIVE_SEPARATE_LANDING_V1
# Captive probe routes to /captive, normal root (/) is always WebUI.
redirect = source.split("void sendCaptiveRedirect(WiFiClient &client, bool headOnly)", 1)[1].split(
    "// JARNSEN_CAPTIVE_IOS_COMPLETE_AFTER_PIN_V1", 1
)[0]
if 'SERVICE_V3_AUTO_PINLESS ? "/captive" : "/"' not in redirect:
    raise SystemExit("V3 captive FAIL: CNA must use /captive on V3 only")
if redirect.count("client.print(targetPath);") != 4:
    raise SystemExit("V3 captive FAIL: inconsistent HTTP 302 and HTML fallback")
if "JARNSEN_V3_CAPTIVE_GATEWAY_STATUS_V1" not in source:
    raise SystemExit("V3 captive FAIL: local-only gateway must not report mobile Internet")
softap_start = source.split("bool startSoftApAttempt(uint8_t attempt)", 1)[1].split(
    "bool jarnsenServiceWebStart()", 1
)[0]
service_pump = source.split("void jarnsenServiceWebPump()", 1)[1].split(
    "bool jarnsenServiceWebActive()", 1
)[0]
for marker in (
    "JARNSEN_V3_AUTO_PORTAL_PINLESS_V1",
    "JARNSEN_LOCAL_ONLY_DHCP_V1",
    "JARNSEN_V3_NO_LIVE_DHCP_RESTART_V1",
    "JARNSEN_V3_CAPTIVE_SEPARATE_LANDING_V1",
    "JARNSEN_V3_CAPTIVE_PLAIN_HTTP_LINK_V1",
    'v3_authorization_preserved; no_dhcp_restart',
    "JARNSEN_V3_STATION_EDGE_TELEMETRY_V1",
    "JARNSEN_V3_CAPTIVE_TRACE_V1",
    "stage=http302 target=192.168.4.1/captive landing=plain_http_link",
    "stage=associated router=0 dns=%u auth=%u",
    "stage=checkpoint age_s=%lu probes=%u foreign=%u webui=%u auth=%u dns=%u",
    "stage=webui_open path=root",
    "configureLocalServiceDhcp()",
    "uint8_t routerOffer = 0U;",
    "uint8_t dnsOffer = 0U;",
    "ESP_NETIF_DOMAIN_NAME_SERVER",
    "if (!SERVICE_LOCAL_ONLY)",
    "stage=ready router=0 dns=0 http=80 tls=off target=root",
    "uint32_t leaseMinutes = 120U;",
    'logEvent("SERVICE_AUTH", "v3_pinless_http_ip_open; no_pin_requested")',
    'logEvent("WLAN_STATION", detail)',
):
    if marker not in source:
        raise SystemExit("V3 captive FAIL: missing "+marker)
if softap_start.index("configureLocalServiceDhcp()") > softap_start.index("WiFi.softAP(serviceSsid"):
    raise SystemExit("V3 captive FAIL: DHCP initial config after association")
for forbidden in ("configureLocalServiceDhcp()", "esp_netif_dhcps_start(", "esp_netif_dhcps_stop("):
    if forbidden in service_pump:
        raise SystemExit("V3 captive FAIL: DHCP restart after association")
if "offerV3RouterlessDhcpAfterSafari" in source:
    raise SystemExit("V3 captive FAIL: unsafe post-Safari DHCP restart")
if not ("portalAuthorized && portalAuthorizedAtMs != 0U" in service_pump and "stopCaptiveDns();" in service_pump):
    raise SystemExit("V3 captive FAIL: post-login DNS release lost")

# V3: no PIN overlay, but captive HTTP redirect and old-board PIN remain.
for required in ('display:none;align-items:center', "if (SERVICE_V3_AUTO_PINLESS)",
                 'if (!SERVICE_V3_AUTO_PINLESS && strcmp(request.method, "POST")',
                 'strcmp(request.token, sessionToken) != 0',
                 "if (portalAuthorized && !serviceMeshtasticTcpActive)"):
    if required not in source:
        raise SystemExit("V3 no-PIN preflight FAIL: missing " + required)
if 'sendCaptiveRedirect(client, strcmp(request.method, "HEAD") == 0)' not in source:
    raise SystemExit("V3 automatic captive opening lost")
# Initial /captive should show exactly one plain IP link without authorizing.
# Root and /webui serve WebUI directly and must be distinct from /captive.
landing = source.split("void sendV3SafariLinkLanding(WiFiClient &client)", 1)[1].split(
    "void sendPage(WiFiClient &client)", 1
)[0]
for needed in ("JARNSEN-MESH", "http://192.168.4.1/",
               "v3_plain_http_link target=root awaiting_tap auth=0"):
    if needed not in landing:
        raise SystemExit("V3 plain IP link FAIL: missing "+needed)
if landing.count("<a ") != 1 or "href=" not in landing:
    raise SystemExit("V3 plain IP link FAIL: one real HTML link required")
if "http://192.168.4.1/webui" in landing or "WEBUI IN SAFARI ÖFFNEN" in landing:
    raise SystemExit("V3 plain IP link FAIL: old button or /webui destination")
for unsafe in ("setTimeout(", "location.replace(", "window.open(", "background:#007aff"):
    if unsafe in landing:
        raise SystemExit("V3 plain IP link FAIL: script or button styling remains")
handler = source.split("const bool requestAuthorized = requestSessionValid", 1)[1].split(
    'if (strcmp(request.method, "GET") == 0 && strcmp(request.path, "/jarnsen-root-ca.cer")', 1
)[0]
captive_branch = handler.index('strcmp(request.path, "/captive") == 0')
landing_call = handler.index("sendV3SafariLinkLanding(client);", captive_branch)
root_branch = handler.index('(strcmp(request.path, "/") == 0 || strcmp(request.path, "/webui") == 0)', landing_call)
root_auth = handler.index("portalAuthorized = true;", root_branch)
root_page = handler.index("sendPage(client);", root_auth)
if not (captive_branch < landing_call < root_branch < root_auth < root_page):
    raise SystemExit("V3 separate landing FAIL: root must enter WebUI, not return to CNA")
if "portalAuthorized = true;" in handler[captive_branch:root_branch]:
    raise SystemExit("V3 separate landing FAIL: /captive must not authorize")
if 'scheduleCellularRoute("v3-ip-root-opened");' not in handler:
    raise SystemExit("V3 separate landing FAIL: WebUI route does not schedule DNS handoff")

# An authenticated captive handoff must go directly to '/'.
# Restore the old working route while keeping DHCP and Meshtastic TCP intact.
handoff = source.split("void sendPortalHandoff(WiFiClient &client, const char *path)", 1)[1].split(
    "void requestCellularInternet(WiFiClient &client)", 1
)[0]
if 'client.print("/\\r\\nConnection: close\\r\\n\\r\\n");' not in handoff:
    raise SystemExit("V3 iOS handoff FAIL: not redirecting directly to normal WebUI")
if "stopCaptiveDns();" in handoff:
    raise SystemExit("JARNSEN shared WiFi preflight FAIL: handoff must retain DNS for iOS success probe")
if "handoff_dns_grace_until_post_auth_timeout" not in handoff:
    raise SystemExit("JARNSEN shared WiFi preflight FAIL: post-PIN DNS grace not logged")
if 'client.print("/?captive=1' in handoff or "safariHandoffHelp" in source:
    raise SystemExit("V3 iOS handoff FAIL: stale manual Safari interstitial")

# Verify the no-GPS local node is emitted in self JSON and shown in the
# node list; otherwise UI incorrectly displays 0 nodes despite a working TCP.
json_code = source.split("void writeNodesJson(Print &client)", 1)[1].split(
    "void sendNodesJson(WiFiClient &client)", 1
)[0]
if "sendNodeJson(client, *self, nullptr)" not in json_code:
    raise SystemExit("V3 node-list preflight FAIL: local node missing without GPS")
if "192.168.4.1:4403" not in source:
    raise SystemExit("V3 TCP copy preflight FAIL: full address not available")

# OLED MGRS-10: zone/band/grid square above ALL ten digits in one row,
# with a measured font choice. No E/N prefixes and no silent truncation.
display_source = (ROOT / "src/jarnsen/adapters/JarnsenDisplayRuntime.cpp").read_text(encoding="utf-8")
mgrs_draw = display_source.split("void drawMgrs(OLEDDisplay *display, int16_t x, int16_t y)", 1)[1].split(
    "void drawNode(OLEDDisplay *display, int16_t x, int16_t y)", 1
)[0]
for token in (
    "JARNSEN_MGRS_SINGLE_ROW_FIT_128_V2",
    "drawHeader(display, x, y, zoneGrid);",
    "display->getStringWidth(digits) <= w - 8",
    "display->setFont(mediumFits ? FONT_MEDIUM : FONT_SMALL)",
    "drawV3MgrsUniformDigits(display, x, y, w, bands, digits)",
    "display->drawString(x + w / 2, rowY, digits);",
):
    if token not in mgrs_draw:
        raise SystemExit("V3 MGRS one-row layout FAIL: " + token)
if '"E %.5s"' in mgrs_draw or '"N %.5s"' in mgrs_draw:
    raise SystemExit("V3 MGRS one-row layout FAIL: unwanted E/N prefixes")
if "JARNSEN_MGRS_TWO_LINE_128_V1" in mgrs_draw:
    raise SystemExit("V3 MGRS one-row layout FAIL: obsolete separate digit rows")

for marker in ("JARNSEN_V3_MGRS_UNIFORM_2X_GLYPHS_V1",
               "V3_MGRS_SCALE, V3_MGRS_SCALE", "V3_MGRS_TOTAL_WIDTH == 117",
               "V3_MGRS_GLYPH_HEIGHT == 18"):
    if marker not in display_source:
        raise SystemExit("V3 MGRS uniform scaling FAIL: missing " + marker)

# The Heltec V3 must use real proportional raster scaling, never the
# extra y-1/y+1 drawString passes that stretched Build 514 vertically.
if "JARNSEN_V3_MGRS_VISUAL_PLUS_2PX_V1" in display_source:
    raise SystemExit("V3 MGRS uniform scaling FAIL: distorted 514 overdraw still present")
font_block = display_source.split("constexpr uint8_t V3_MGRS_ROWS[10][9] = {", 1)[1].split("};", 1)[0]
rows = re.findall(r"[{]([^{}]+)[}]", font_block)
if len(rows) != 10 or any(len(re.findall(r"0x[0-9a-fA-F]+", item)) != 9 for item in rows):
    raise SystemExit("V3 MGRS uniform scaling FAIL: need ten complete 5x9 glyphs")
if "static_assert(V3_MGRS_TOTAL_WIDTH == 117" not in display_source:
    raise SystemExit("V3 MGRS uniform scaling FAIL: missing 117px width bound")
if "static_assert(V3_MGRS_GLYPH_HEIGHT == 18" not in display_source:
    raise SystemExit("V3 MGRS uniform scaling FAIL: missing 18px height bound")
if "if (!rendered)" not in mgrs_draw:
    raise SystemExit("V3 MGRS uniform scaling FAIL: fallback renderer removed")

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
