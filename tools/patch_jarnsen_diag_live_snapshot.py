"""Add a fresh Tracker power snapshot to BLE and USB diagnostic exports."""
from pathlib import Path

TARGET = Path("src/vehicle/TrackerDiagnosticLog.cpp")
source = TARGET.read_text(encoding="utf-8")

include_anchor = '''#include "JarnsenDiagMetadataGenerated.h"
#include "NodeDB.h"
'''
if '#include "vehicle/TrackerPowerMonitor.h"' not in source:
    if source.count(include_anchor) != 1:
        raise SystemExit("Tracker power include anchor not found exactly once")
    source = source.replace(include_anchor, include_anchor + '#include "vehicle/TrackerPowerMonitor.h"\n', 1)

role_anchor = '''const char *trackerDiagRoleText()
{
    return config.device.role == meshtastic_Config_DeviceConfig_Role_TAK_TRACKER ? "TAK_TRACKER" : "TAK";
}
'''
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

source = source.replace("char bleHeader[768] = {};", "char bleHeader[1600] = {};", 1)

ble_context = '''    const char *longName = owner.long_name[0] ? owner.long_name : "--";
    const char *shortName = owner.short_name[0] ? owner.short_name : "--";
    bleHeaderLength = (size_t)snprintf(bleHeader, sizeof(bleHeader),
'''
if "formatTrackerLiveBattery(liveBattery" not in source:
    if source.count(ble_context) != 1:
        raise SystemExit("Tracker BLE header context not found exactly once")
    source = source.replace(
        ble_context,
        '''    const char *longName = owner.long_name[0] ? owner.long_name : "--";
    const char *shortName = owner.short_name[0] ? owner.short_name : "--";
    char liveBattery[768] = {};
    formatTrackerLiveBattery(liveBattery, sizeof(liveBattery));
    bleHeaderLength = (size_t)snprintf(bleHeader, sizeof(bleHeader),
''',
        1,
    )

ble_format = '''                                       "# feature=%s\\r\\n# log_format=%u\\r\\n# export=%s\\r\\n# transport=BLE\\r\\n# "
                                       "bytes=%u\\r\\n",
'''
if "# transport=BLE\\r\\n%s# bytes=%u" not in source:
    if source.count(ble_format) != 1:
        raise SystemExit("Tracker BLE format anchor not found exactly once")
    source = source.replace(
        ble_format,
        '''                                       "# feature=%s\\r\\n# log_format=%u\\r\\n# export=%s\\r\\n# transport=BLE\\r\\n%s# bytes=%u\\r\\n",
''',
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

usb_context = '''            const char *longName = owner.long_name[0] ? owner.long_name : "--";
            const char *shortName = owner.short_name[0] ? owner.short_name : "--";
            char header[768] = {};
'''
if "char usbLiveBattery[768]" not in source:
    if source.count(usb_context) != 1:
        raise SystemExit("Tracker USB header context not found exactly once")
    source = source.replace(
        usb_context,
        '''            const char *longName = owner.long_name[0] ? owner.long_name : "--";
            const char *shortName = owner.short_name[0] ? owner.short_name : "--";
            char usbLiveBattery[768] = {};
            formatTrackerLiveBattery(usbLiveBattery, sizeof(usbLiveBattery));
            char header[1600] = {};
''',
        1,
    )
    usb_format = '''                     "# log_format=%u\\r\\n# export=%s\\r\\n# bytes=%u\\r\\n",
'''
    if source.count(usb_format) != 1:
        raise SystemExit("Tracker USB format anchor not found exactly once")
    source = source.replace(
        usb_format,
        '''                     "# log_format=%u\\r\\n# export=%s\\r\\n%s# bytes=%u\\r\\n",
''',
        1,
    )
    usb_args = '''                     trackerDiagRoleText(), JARNSEN_DIAG_FEATURE_VERSION, (unsigned)JARNSEN_DIAG_LOG_FORMAT, exportTime,
                     (unsigned)exportTotalBytes);'''
    if source.count(usb_args) != 1:
        raise SystemExit("Tracker USB args anchor not found exactly once")
    source = source.replace(
        usb_args,
        '''                     trackerDiagRoleText(), JARNSEN_DIAG_FEATURE_VERSION, (unsigned)JARNSEN_DIAG_LOG_FORMAT, exportTime,
                     usbLiveBattery, (unsigned)exportTotalBytes);''',
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
    "char header[1600]",
):
    if marker not in source:
        raise SystemExit(f"missing Tracker live-snapshot marker: {marker}")

TARGET.write_text(source, encoding="utf-8")
print("Tracker diagnostic BLE/USB exports now include a fresh LIVE BATTERY snapshot")
