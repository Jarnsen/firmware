#!/usr/bin/env python3
"""Preflight for V3 HTTPS handshake and connection memory exhaustion.

Build 421 starts HTTPS with 44 KiB but browser probes reduced RAM to 4 KiB.
The TLS library must keep running existing clients while refusing *new*
connections when memory is low. An outer heap guard around .loop() deadlocks.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "src/mesh/http/JarnsenServiceWeb.cpp"
OBSERVED_V3_HEAP_AFTER_TLS_START = 44064


def main() -> int:
    source = SOURCE.read_text(encoding="utf-8")
    match = re.search(r"constexpr uint32_t HTTPS_PUMP_MIN_FREE_HEAP\s*=\s*(\d+)U;", source)
    if not match:
        raise SystemExit("HTTPS preflight FAIL: missing named handshake heap guard")
    threshold = int(match.group(1))
    if threshold >= OBSERVED_V3_HEAP_AFTER_TLS_START or threshold < 24000:
        raise SystemExit("HTTPS preflight FAIL: bad new TLS connection threshold")
    if "HTTPS_PUMP_MIN_LARGEST_BLOCK = 16384U" not in source:
        raise SystemExit("HTTPS preflight FAIL: missing contiguous TLS block guard")
    if "heap_caps_get_largest_free_block(MALLOC_CAP_8BIT)" not in source:
        raise SystemExit("HTTPS preflight FAIL: TLS fragmentation not checked")
    if "ESP.getFreeHeap() >= 55000U" in source:
        raise SystemExit("HTTPS preflight FAIL: unreachable 55KiB guard restored")
    if "class JarnsenBudgetedHttpsServer final : public HTTPSServer" not in source:
        raise SystemExit("HTTPS preflight FAIL: no budgeted TLS server")
    if "HTTPSServer::loop();" not in source or "connection->loop();" not in source:
        raise SystemExit("HTTPS preflight FAIL: existing TLS sockets are not serviced")
    if "connection->closeConnection();" not in source or "delete connection;" not in source:
        raise SystemExit("HTTPS preflight FAIL: TLS socket cleanup missing")
    if "HTTPS_EMERGENCY_FREE_HEAP = 8192U" not in source:
        raise SystemExit("HTTPS preflight FAIL: emergency TLS cleanup guard missing")
    pump = source.split("void jarnsenServiceWebPump()", 1)[1]
    https = pump.index("serviceHttpsServer->loopWithMemoryBudget(")
    http = pump.index("httpServer.available();")
    if https >= http:
        raise SystemExit("HTTPS preflight FAIL: TLS must be pumped before captive HTTP")
    if "if (freeHeap >= HTTPS_PUMP_MIN_FREE_HEAP)" in pump:
        raise SystemExit("HTTPS preflight FAIL: conditional outer pump deadlock restored")
    for check, token in (
        ("iOS primary button points to mobileconfig", 'id="certDownloadBtn" href="http://192.168.4.1/jarnsen-root-ca.mobileconfig"'),
        ("legacy CER remains optional", 'id="certDerFallback" href="http://192.168.4.1/jarnsen-root-ca.cer"'),
        ("iOS profile correct MIME", 'sendStatus(client, 200, "OK", "application/x-apple-aspen-config"'),
        ("iOS profile valid filename", 'Content-Disposition: inline; filename=\\\"JARNSEN-MESH-Root-CA.mobileconfig\\\"'),
        ("Safari-only captive warning", "Captive-Portal-Fenster"),
        ("iOS direct HTTP route", 'sendRootCaMobileconfig(client);'),
        ("X509 CA DER route", 'sendRootCaCertificate(client);'),
    ):
        if token not in source:
            raise SystemExit(f"HTTPS preflight FAIL: {check}")
    if "pump_deferred_low_heap" in source or "setInterval(()=>checkHttpsTrust(),5000)" in source:
        raise SystemExit("HTTPS preflight FAIL: deadlocked pump or browser probe loop restored")
    for marker in (
        "new_tls_deferred_free=",
        'logEvent("WLAN_HTTPS", detail)',
        'jarnsen::crashTraceBreadcrumb(302U, "https_pump_begin")',
        "serviceHttpsServer && serviceHttpsActive",
    ):
        if marker not in source:
            raise SystemExit(f"HTTPS preflight FAIL: missing {marker}")
    for marker in (
        "JARNSEN_BROWSER_DIAG_V1",
        'window.addEventListener(\'unhandledrejection\'',
        'window.addEventListener(\'error\'',
        'reportWebDiagnostic(\'api_failure\'',
        'reportWebDiagnostic(\'gps_error\'',
        'reportWebDiagnostic(\'map_error\'',
        "X-Jarnsen-Detail",
        "bool clientDetailAllowed(",
        "void logClientDiagnostic(",
        "eventsInWindow >= 12U",
        "await loadSituation();await loadTrack();",
        "setInterval(()=>{if(!document.hidden)loadLive()},8000)",
    ):
        if marker not in source:
            raise SystemExit(f"Browser diagnostic preflight FAIL: missing {marker}")
    if "stopCaptiveDns();" in source.split("void jarnsenServiceWebPump()", 1)[1].split("bool jarnsenServiceWebActive()", 1)[0]:
        raise SystemExit("Captive preflight FAIL: DNS must remain active during WLAN service")
    if 'client.print(portalAuthorized ? "{\\\"captive\\\":false"' not in source:
        raise SystemExit("Captive preflight FAIL: authenticated iOS captive API not released")
    if 'sendCaptiveRedirect(client, strcmp(request.method, "HEAD") == 0);' not in source:
        raise SystemExit("Captive preflight FAIL: legacy iOS detection probes broken")
    print("HTTPS/captive preflight PASS: bounded TLS, fragmentation guard, stable iOS DNS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
