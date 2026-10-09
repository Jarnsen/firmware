#!/usr/bin/env python3
"""Regression contract for the Heltec V3 HTTPS-loop starvation found in Build 420.

Build 420 started HTTPSServer(443) with 44,064 bytes free, but skipped its
loop until 55,000 bytes were free; HTTPS therefore never accepted clients.
This static contract is deliberately not a substitute for device TLS tests.
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
    if threshold >= OBSERVED_V3_HEAP_AFTER_TLS_START or threshold < 28000:
        raise SystemExit("HTTPS preflight FAIL: heap threshold would starve V3 or be unsafe")
    if "ESP.getFreeHeap() >= 55000U" in source:
        raise SystemExit("HTTPS preflight FAIL: unreachable 55KiB guard restored")
    pump = source.split("void jarnsenServiceWebPump()", 1)[1]
    https = pump.index("serviceHttpsServer->loop();")
    http = pump.index("httpServer.available();")
    if https >= http:
        raise SystemExit("HTTPS preflight FAIL: TLS must be pumped before HTTP captive clients")
    for marker in (
        "pump_deferred_low_heap",
        "HTTPS_LOW_HEAP_WARN_INTERVAL_MS",
        'logEvent("WLAN_HTTPS", detail)',
        "jarnsen::crashTraceBreadcrumb(302U, \"https_pump_begin\")",
        "serviceHttpsServer && serviceHttpsActive",
    ):
        if marker not in source:
            raise SystemExit(f"HTTPS preflight FAIL: missing {marker}")
    print(f"V3 HTTPS pump preflight PASS: threshold={threshold} < 44064-byte observed baseline")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
