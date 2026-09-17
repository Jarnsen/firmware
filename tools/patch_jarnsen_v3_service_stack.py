"""Give the Heltec V3 service task enough stack for captive-portal HTTP handling.

The V3 service task also owns display/menu/diagnostic work.  Wi-Fi is normally
inactive, but once the service AP is running the first OS captive-portal probe
is handled from this task through jarnsenServiceWebPump().  The previous 6144
byte stack was too small for the nested WiFiClient/HTTP path and could panic
immediately after WEB_OK.  Keep this change V3-only and build-scoped.
"""
from pathlib import Path

TARGET = Path("src/infrastructure/HeltecV3RepeaterPolicy.cpp")
source = TARGET.read_text(encoding="utf-8")

old = 'xTaskCreate(v3ServiceTask, "V3Service", 6144, nullptr, 1, &v3ServiceTaskHandle);'
new = 'xTaskCreate(v3ServiceTask, "V3Service", 12288, nullptr, 1, &v3ServiceTaskHandle);'

if new not in source:
    if source.count(old) != 1:
        raise SystemExit("V3Service 6144-byte stack anchor not found exactly once")
    source = source.replace(old, new, 1)

if source.count(new) != 1:
    raise SystemExit("V3Service 12288-byte stack marker not found exactly once")

TARGET.write_text(source, encoding="utf-8")
print("Heltec V3 service task stack raised to 12288 bytes for captive-portal HTTP handling")
