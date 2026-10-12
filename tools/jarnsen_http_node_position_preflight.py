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
    "selfPos=nodeSelfPos;",
    "httpNodeMode=info.https_supported===false;",
    "if(!httpNodeMode)setTimeout(async()=>{await checkHttpsTrust();startCertTrustWatch()}",
    "if(!httpNodeMode){if(window.isSecureContext)setTimeout(startPhoneGps,250)",
    "if(!document.hidden&&!httpNodeMode&&info?.tls_ready)",
    "Kein GPS-Fix vorhanden. Safari kann Telefon-GPS über HTTP nicht auslesen.",
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
    # JARNSEN_V3_UPDATE_SAFETY_GATE_V1: no destructive OTA while
    # the app-only bootloop is unexplained. Both HTTP and HTTPS are gated.
    "JARNSEN_V3_UPDATE_SAFETY_GATE_V1",
    "SERVICE_V3_APP_ONLY_UPDATE_VALIDATED = false;",
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
)
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
