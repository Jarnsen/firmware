"""Add/verify a fresh Tracker power snapshot in BLE and USB diagnostic exports.

The current Tracker source already carries the atomic USB export state machine.
This patch stays backward compatible with the previous local-header layout so the
build chain can validate either form without rewriting the new session logic.
"""
from pathlib import Path

TARGET = Path("src/vehicle/TrackerDiagnosticLog.cpp")
source = TARGET.read_text(encoding="utf-8")

include_anchor = '''#include "JarnsenDiagMetadataGenerated.h"\n#include "NodeDB.h"\n'''
if '#include "vehicle/TrackerPowerMonitor.h"' not in source:
    if source.count(include_anchor) != 1:
        raise SystemExit("Tracker power include anchor not found exactly once")
    source = source.replace(include_anchor, include_anchor + '#include "vehicle/TrackerPowerMonitor.h"\n', 1)

role_anchor = '''const char *trackerDiagRoleText()\n{\n    return config.device.role == meshtastic_Config_DeviceConfig_Role_TAK_TRACKER ? "TAK_TRACKER" : "TAK";\n}\n'''
helper = role_anchor + r'''

void formatTrackerLiveBattery(char *out, size_t outSize)
{
    if (!out || outSize == 0)
        return;
    const TrackerPowerStats power = trackerPowerMonitorStats();
    char remaining[32] = "learning";
    if (power.estimateReady)
        trackerPowerFormatDuration(power.remainingSecs, remaining, sizeof(remaining));
    const char *inaState = !power.inaConfigured ? "OFF" : (!power.inaPresent ? "MISSING" : (power.inaValid ? "OK" : "WAIT"));
    const char *vbusState =
        !power.inaConfigured || !power.inaPresent ? "N/A" : (!power.inaValid ? "WAIT" : (power.vbusValid ? "OK" : "MISSING"));
    const int32_t current = power.currentMilliAmpsX10;
    const int32_t currentAbs = current < 0 ? -current : current;
    snprintf(out, outSize,
             "LIVE | BATTERY | %umV %u%% usb=%u charge=%u est=%s ina=%s vbus=%s current=%s%ld.%ldmA "
             "total=%u.%umAh sleepEst=%u.%umAh lightSleep=%us deepSleep=%us cap=%umAh left=%umAh conf=%u%% "
             "cycles=%u on=%us move=%us park=%us gps=%us ble=%us disp=%us tx=%u\r\n",
             (unsigned)power.voltageMv, (unsigned)power.batteryPercent, power.usbPowered ? 1U : 0U,
             power.charging ? 1U : 0U, remaining, inaState, vbusState, current < 0 ? "-" : "",
             (long)(currentAbs / 10), (long)(currentAbs % 10), (unsigned)(power.dischargedMahX10 / 10U),
             (unsigned)(power.dischargedMahX10 % 10U), (unsigned)(power.sleepEstimatedMahX10 / 10U),
             (unsigned)(power.sleepEstimatedMahX10 % 10U), (unsigned)power.lightSleepSecs, (unsigned)power.deepSleepSecs,
             (unsigned)power.learnedCapacityMah, (unsigned)power.remainingCapacityMah, (unsigned)power.capacityConfidence,
             (unsigned)power.capacityCycles, (unsigned)power.measuredSecs, (unsigned)power.movingSecs,
             (unsigned)power.parkedSecs, (unsigned)power.gnssSecs, (unsigned)power.bleSecs, (unsigned)power.displaySecs,
             (unsigned)power.positionTxCount);
}
'''
if "void formatTrackerLiveBattery(" not in source:
    if source.count(role_anchor) != 1:
        raise SystemExit("Tracker role helper anchor not found exactly once")
    source = source.replace(role_anchor, helper, 1)

if "char bleHeader[1600]" not in source:
    source = source.replace("char bleHeader[768] = {};", "char bleHeader[1600] = {};", 1)

ble_context = '''    const char *longName = owner.long_name[0] ? owner.long_name : "--";\n    const char *shortName = owner.short_name[0] ? owner.short_name : "--";\n    bleHeaderLength = (size_t)snprintf(bleHeader, sizeof(bleHeader),\n'''
if "formatTrackerLiveBattery(liveBattery" not in source:
    if source.count(ble_context) != 1:
        raise SystemExit("Tracker BLE header context not found exactly once")
    source = source.replace(
        ble_context,
        '''    const char *longName = owner.long_name[0] ? owner.long_name : "--";\n    const char *shortName = owner.short_name[0] ? owner.short_name : "--";\n    char liveBattery[768] = {};\n    formatTrackerLiveBattery(liveBattery, sizeof(liveBattery));\n    bleHeaderLength = (size_t)snprintf(bleHeader, sizeof(bleHeader),\n''',
        1,
    )

ble_format = '''                                       "# feature=%s\\r\\n# log_format=%u\\r\\n# export=%s\\r\\n# transport=BLE\\r\\n# "\n                                       "bytes=%u\\r\\n",\n'''
if "# transport=BLE\\r\\n%s# bytes=%u" not in source:
    if source.count(ble_format) != 1:
        raise SystemExit("Tracker BLE format anchor not found exactly once")
    source = source.replace(
        ble_format,
        '''                                       "# feature=%s\\r\\n# log_format=%u\\r\\n# export=%s\\r\\n# transport=BLE\\r\\n%s# bytes=%u\\r\\n",\n''',
        1,
    )
    args_anchor = '''                                       (unsigned)JARNSEN_DIAG_LOG_FORMAT, exportTime, (unsigned)totalBytes);'''
    if source.count(args_anchor) != 1:
        raise SystemExit("Tracker BLE args anchor not found exactly once")
    source = source.replace(
        args_anchor,
        '''                                       (unsigned)JARNSEN_DIAG_LOG_FORMAT, exportTime, liveBattery, (unsigned)totalBytes);''',
        1,
    )

# Atomic USB source: the header is persistent and built once when the snapshot is
# frozen. Do not rewrite it into the legacy per-pump local-header form.
atomic_usb = all(
    marker in source
    for marker in (
        "char usbHeader[1600]",
        "char usbLiveBattery[768]",
        "formatTrackerLiveBattery(usbLiveBattery",
        "# transport=USB\\r\\n%s# bytes=%u",
    )
)

if not atomic_usb:
    usb_context = '''            const char *longName = owner.long_name[0] ? owner.long_name : "--";\n            const char *shortName = owner.short_name[0] ? owner.short_name : "--";\n            char header[768] = {};\n'''
    if "char usbLiveBattery[768]" not in source:
        if source.count(usb_context) != 1:
            raise SystemExit("Tracker USB header context not found exactly once")
        source = source.replace(
            usb_context,
            '''            const char *longName = owner.long_name[0] ? owner.long_name : "--";\n            const char *shortName = owner.short_name[0] ? owner.short_name : "--";\n            char usbLiveBattery[768] = {};\n            formatTrackerLiveBattery(usbLiveBattery, sizeof(usbLiveBattery));\n            char header[1600] = {};\n''',
            1,
        )
        usb_format = '''                     "# log_format=%u\\r\\n# export=%s\\r\\n# bytes=%u\\r\\n",\n'''
        if source.count(usb_format) != 1:
            raise SystemExit("Tracker USB format anchor not found exactly once")
        source = source.replace(
            usb_format,
            '''                     "# log_format=%u\\r\\n# export=%s\\r\\n%s# bytes=%u\\r\\n",\n''',
            1,
        )
        usb_args = '''                     trackerDiagRoleText(), JARNSEN_DIAG_FEATURE_VERSION, (unsigned)JARNSEN_DIAG_LOG_FORMAT, exportTime,\n                     (unsigned)exportTotalBytes);'''
        if source.count(usb_args) != 1:
            raise SystemExit("Tracker USB args anchor not found exactly once")
        source = source.replace(
            usb_args,
            '''                     trackerDiagRoleText(), JARNSEN_DIAG_FEATURE_VERSION, (unsigned)JARNSEN_DIAG_LOG_FORMAT, exportTime,\n                     usbLiveBattery, (unsigned)exportTotalBytes);''',
            1,
        )

for marker in (
    '#include "vehicle/TrackerPowerMonitor.h"',
    "void formatTrackerLiveBattery(",
    "left=%umAh",
    "cycles=%u",
    "formatTrackerLiveBattery(liveBattery",
    "formatTrackerLiveBattery(usbLiveBattery",
    "char bleHeader[1600]",
):
    if marker not in source:
        raise SystemExit(f"missing Tracker live-snapshot marker: {marker}")

if "char usbHeader[1600]" not in source and "char header[1600]" not in source:
    raise SystemExit("missing Tracker USB live-snapshot header buffer")

TARGET.write_text(source, encoding="utf-8")
print("Tracker diagnostic BLE/USB exports include a fresh LIVE BATTERY snapshot")
