"""Tracker V1.1: keep sleep awake only for an active native-USB session.

The old policy treated bool(Serial) as an active session. On ESP32-S3 native
USB CDC that stays true while a PC merely has the COM port open, so TAK_TRACKER
could repeatedly veto deep sleep and emit PARK_SLEEP spam many times per second.

This patch, applied after mesh-sync/access patching, changes the contract to:
- any received native-serial byte refreshes a 15 s activity window,
- a diagnostic USB export keeps the lock for its complete transfer,
- a connected but idle COM port no longer blocks autonomous deep sleep,
- PARK_SLEEP veto diagnostics are emitted on transition and at most every 30 s.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HEADER = ROOT / "src/vehicle/TrackerDiagnosticLog.h"
DIAG = ROOT / "src/vehicle/TrackerDiagnosticLog.cpp"
COMMON = ROOT / "src/vehicle/TrackerCommonPolicy.cpp"
POWER = ROOT / "src/PowerFSM.cpp"
STREAM = ROOT / "src/mesh/StreamAPI.cpp"


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected one anchor, got {count}")
    return text.replace(old, new, 1)


# Public activity helpers live with the diagnostic/tool serial parser.
header = HEADER.read_text(encoding="utf-8")
if "trackerDiagNativeSerialSessionActive" not in header:
    header = replace_once(
        header,
        "bool trackerDiagHandleToolSerialByte(uint8_t value);\n",
        "bool trackerDiagHandleToolSerialByte(uint8_t value);\n"
        "void trackerDiagMarkNativeSerialActivity();\n"
        "bool trackerDiagNativeSerialSessionActive();\n",
        "diagnostic header serial activity",
    )
HEADER.write_text(header, encoding="utf-8")

# Track serial RX activity and expose one sleep-lock decision. Export state is
# authoritative, while ordinary Meshtastic serial traffic gets a bounded grace.
diag = DIAG.read_text(encoding="utf-8")
if "lastNativeSerialActivityMs" not in diag:
    diag = replace_once(
        diag,
        "size_t toolCommandLength = 0;\n",
        "size_t toolCommandLength = 0;\nuint32_t lastNativeSerialActivityMs = 0;\n",
        "diagnostic activity variable",
    )

if "void trackerDiagMarkNativeSerialActivity()" not in diag:
    anchor = '''extern "C" bool meshtasticTrackerDiagUsbSerialLockActive()\n{\n    return usbExportSessionActive();\n}\n'''
    addition = anchor + '''\nvoid trackerDiagMarkNativeSerialActivity()\n{\n    const uint32_t now = millis();\n    lastNativeSerialActivityMs = now ? now : 1U;\n}\n\nbool trackerDiagNativeSerialSessionActive()\n{\n    if (exportRequested || usbExportSessionActive())\n        return true;\n    const uint32_t last = lastNativeSerialActivityMs;\n    return last != 0U && (uint32_t)(millis() - last) < 15000UL;\n}\n'''
    diag = replace_once(diag, anchor, addition, "diagnostic activity helpers")
DIAG.write_text(diag, encoding="utf-8")

# Mark every serial byte before the Jarnsen tool parser gets first refusal. This
# also covers normal Meshtastic serial configuration traffic instead of only
# JARNSEN_TOOL_* commands.
stream = STREAM.read_text(encoding="utf-8")
old_hook = '''        uint8_t c = (uint8_t)cInt;\n#if defined(HELTEC_TRACKER_V1_1)\n        if (trackerDiagHandleToolSerialByte(c))\n            continue;\n#endif\n'''
new_hook = '''        uint8_t c = (uint8_t)cInt;\n#if defined(HELTEC_TRACKER_V1_1)\n        trackerDiagMarkNativeSerialActivity();\n        if (trackerDiagHandleToolSerialByte(c))\n            continue;\n#endif\n'''
if "trackerDiagMarkNativeSerialActivity();" not in stream:
    count = stream.count(old_hook)
    if count < 1:
        raise SystemExit("StreamAPI Tracker serial hook anchor missing")
    stream = stream.replace(old_hook, new_hook)
STREAM.write_text(stream, encoding="utf-8")

# Replace raw USB-connect presence with the bounded active-session decision and
# rate-limit the diagnostic event.
common = COMMON.read_text(encoding="utf-8")
if "serialSleepVetoActive" not in common:
    common = replace_once(
        common,
        "bool pairingDisplayActive = false;\n",
        "bool pairingDisplayActive = false;\n"
        "bool serialSleepVetoActive = false;\n"
        "uint32_t lastSerialSleepVetoLogMs = 0;\n",
        "common serial veto state",
    )

old_veto = '''    if (trackerUsesDeepSleep()) {\n#if defined(ARDUINO_USB_CDC_ON_BOOT) && ARDUINO_USB_CDC_ON_BOOT\n        if ((bool)Serial) {\n            trackerDiagLog("PARK_SLEEP", "deep sleep veto: native serial connected");\n            return;\n        }\n#endif\n\n        rememberCurrentPosition();\n'''
new_veto = '''    if (trackerUsesDeepSleep()) {\n        if (trackerDiagNativeSerialSessionActive()) {\n            const uint32_t now = millis();\n            if (!serialSleepVetoActive || (uint32_t)(now - lastSerialSleepVetoLogMs) >= 30000UL) {\n                trackerDiagLog("PARK_SLEEP", "deep sleep veto: active native serial session");\n                lastSerialSleepVetoLogMs = now ? now : 1U;\n            }\n            serialSleepVetoActive = true;\n            return;\n        }\n        if (serialSleepVetoActive) {\n            trackerDiagLog("PARK_SLEEP", "native serial session idle; deep sleep allowed");\n            serialSleepVetoActive = false;\n            lastSerialSleepVetoLogMs = 0;\n        }\n\n        rememberCurrentPosition();\n'''
if "deep sleep veto: active native serial session" not in common:
    common = replace_once(common, old_veto, new_veto, "common deep-sleep serial veto")
COMMON.write_text(common, encoding="utf-8")

# Generic PowerFSM light-sleep gating must follow the same session definition so
# an idle USB cable cannot keep the CPU fully awake forever.
power = POWER.read_text(encoding="utf-8")
if '#include "vehicle/TrackerDiagnosticLog.h"' not in power:
    power = replace_once(
        power,
        '#include "target_specific.h"\n',
        '#include "target_specific.h"\n#if defined(HELTEC_TRACKER_V1_1)\n#include "vehicle/TrackerDiagnosticLog.h"\n#endif\n',
        "PowerFSM diagnostic include",
    )
old_power = '''static bool trackerUsbKeepsCpuAwake()\n{\n#if defined(HELTEC_TRACKER_V1_1)\n    bool nativeSerialConnected = false;\n#if defined(ARDUINO_USB_CDC_ON_BOOT) && ARDUINO_USB_CDC_ON_BOOT\n    nativeSerialConnected = (bool)Serial;\n#endif\n    return trackerOwnsInteractiveOutputs() && nativeSerialConnected;\n#else\n    return false;\n#endif\n}\n'''
new_power = '''static bool trackerUsbKeepsCpuAwake()\n{\n#if defined(HELTEC_TRACKER_V1_1)\n    return trackerOwnsInteractiveOutputs() && trackerDiagNativeSerialSessionActive();\n#else\n    return false;\n#endif\n}\n'''
if "trackerDiagNativeSerialSessionActive();" not in power:
    power = replace_once(power, old_power, new_power, "PowerFSM active serial gating")
POWER.write_text(power, encoding="utf-8")

for path, markers in (
    (HEADER, ("trackerDiagMarkNativeSerialActivity", "trackerDiagNativeSerialSessionActive")),
    (DIAG, ("lastNativeSerialActivityMs", "15000UL", "trackerDiagNativeSerialSessionActive")),
    (STREAM, ("trackerDiagMarkNativeSerialActivity();",)),
    (COMMON, ("serialSleepVetoActive", "30000UL", "deep sleep veto: active native serial session")),
    (POWER, ('#include "vehicle/TrackerDiagnosticLog.h"', "trackerDiagNativeSerialSessionActive();")),
):
    text = path.read_text(encoding="utf-8")
    for marker in markers:
        if marker not in text:
            raise SystemExit(f"missing Tracker serial-session marker in {path}: {marker}")

print("Tracker native-serial sleep veto now uses active-session timeout; PARK_SLEEP logging rate-limited")
