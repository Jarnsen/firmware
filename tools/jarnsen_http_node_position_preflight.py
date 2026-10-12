#!/usr/bin/env python3
"""HTTP-only Heltec V3 and zero-setup node-position safety contract."""
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
source = (ROOT / "src/mesh/http/JarnsenServiceWeb.cpp").read_text(encoding="utf-8")

required = (
    "JARNSEN_V3_HTTP_NODE_POSITION_NO_SETUP_V1",
    "constexpr bool SERVICE_HTTPS_ENABLED = false;",
    "constexpr bool SERVICE_HTTPS_ENABLED = true;",
    "const bool httpsReady = SERVICE_HTTPS_ENABLED ? startServiceHttps() : false;",
    'logEvent("WLAN_HTTPS", "disabled: V3 HTTP only, zero TLS allocation");',
    '"https_supported"',
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
)
for marker in required:
    if marker not in source:
        raise SystemExit(f"V3 HTTP-position preflight FAIL: missing {marker}")

page = source.split('const char PAGE[] PROGMEM = R"JARN(', 1)[1].split(')JARN";', 1)[0]
javascript = page.split("<script>", 1)[1].split("</script>", 1)[0]
result = subprocess.run(["node", "--check", "-"], input=javascript,
                        text=True, capture_output=True, check=False)
if result.returncode != 0:
    raise SystemExit("V3 HTTP-position preflight FAIL: browser JavaScript syntax: "
                     + result.stderr[-2000:])
print("JARNSEN V3 HTTP-only automatic node position preflight PASS")
