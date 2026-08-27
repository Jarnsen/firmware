"""Complete V3 LIVE BATTERY data for BLE and add it to USB exports."""
from pathlib import Path

TARGET = Path("src/infrastructure/HeltecV3DiagnosticLog.cpp")
source = TARGET.read_text(encoding="utf-8")

# BLE already has a fresh snapshot. Complete it with the four learned average currents.
ble_format_anchor = '''                         "confidence=%u%% cycles=%u on=%us listen=%us service=%us ble=%us disp=%us tx=%u "
                         "auto=%u manual=%u\\r\\n"
'''
if "avgListen=%ldmA avgService=%ldmA avgBle=%ldmA avgDisplay=%ldmA" not in source:
    if source.count(ble_format_anchor) != 1:
        raise SystemExit("V3 BLE live-battery format anchor not found exactly once")
    source = source.replace(
        ble_format_anchor,
        '''                         "confidence=%u%% cycles=%u avgListen=%ldmA avgService=%ldmA avgBle=%ldmA avgDisplay=%ldmA "
                         "on=%us listen=%us service=%us ble=%us disp=%us tx=%u auto=%u manual=%u\\r\\n"
''',
        1,
    )
    ble_args_anchor = '''                         (unsigned)power.remainingCapacityMah, (unsigned)power.capacityConfidence,
                         (unsigned)power.capacityCycles, (unsigned)power.measuredSecs, (unsigned)power.listenSecs,
'''
    if source.count(ble_args_anchor) != 1:
        raise SystemExit("V3 BLE live-battery args anchor not found exactly once")
    source = source.replace(
        ble_args_anchor,
        '''                         (unsigned)power.remainingCapacityMah, (unsigned)power.capacityConfidence,
                         (unsigned)power.capacityCycles, (long)power.listenAvgMa, (long)power.serviceAvgMa,
                         (long)power.bleAvgMa, (long)power.displayAvgMa, (unsigned)power.measuredSecs, (unsigned)power.listenSecs,
''',
        1,
    )

# USB export previously contained only metadata + stored log. Add the same fresh snapshot.
usb_context = '''        const char *longName = owner.long_name[0] ? owner.long_name : "--";
        const char *shortName = owner.short_name[0] ? owner.short_name : "--";
        char header[768] = {};
'''
if "char usbLiveBattery[1050]" not in source:
    if source.count(usb_context) != 1:
        raise SystemExit("V3 USB header context not found exactly once")
    usb_insert = '''        const char *longName = owner.long_name[0] ? owner.long_name : "--";
        const char *shortName = owner.short_name[0] ? owner.short_name : "--";
        const HeltecV3PowerStats power = heltecV3PowerMonitorStats();
        const HeltecV3DiagStats diagnostic = heltecV3DiagStats();
        char remaining[32] = "learning";
        if (power.estimateReady)
            heltecV3PowerFormatDuration(power.remainingSecs, remaining, sizeof(remaining));
        char usbLiveBattery[1050] = {};
        snprintf(usbLiveBattery, sizeof(usbLiveBattery),
                 "LIVE | BATTERY | src=%s ina=%s vbus=%s %umV %u%% usb=%u charge=%u est=%s "
                 "current=%ldmA power=%umW used=%umAh/%umWh capacity=%umAh left=%umAh confidence=%u%% cycles=%u "
                 "avgListen=%ldmA avgService=%ldmA avgBle=%ldmA avgDisplay=%ldmA on=%us listen=%us service=%us "
                 "ble=%us disp=%us tx=%u auto=%u manual=%u\\r\\n",
                 heltecV3PowerMonitorSourceText(), power.inaPresent ? "ACTIVE" : "OFF",
                 power.vbusValid ? "OK" : (power.inaPresent ? "MISSING" : "N/A"), (unsigned)power.voltageMv,
                 (unsigned)power.batteryPercent, power.usbPowered ? 1U : 0U, power.charging ? 1U : 0U, remaining,
                 (long)(power.currentValid ? power.currentMa : 0), (unsigned)(power.currentValid ? power.powerMw : 0),
                 (unsigned)power.consumedMah, (unsigned)power.consumedMwh, (unsigned)power.learnedCapacityMah,
                 (unsigned)power.remainingCapacityMah, (unsigned)power.capacityConfidence, (unsigned)power.capacityCycles,
                 (long)power.listenAvgMa, (long)power.serviceAvgMa, (long)power.bleAvgMa, (long)power.displayAvgMa,
                 (unsigned)power.measuredSecs, (unsigned)power.listenSecs, (unsigned)power.serviceSecs,
                 (unsigned)power.bleSecs, (unsigned)power.displaySecs, (unsigned)power.positionTxCount,
                 (unsigned)diagnostic.autoPositionSaveCount, (unsigned)diagnostic.manualPositionSaveCount);
        char header[1800] = {};
'''
    source = source.replace(usb_context, usb_insert, 1)

    usb_format = '''                 "# log_format=%u\\r\\n# export=%s\\r\\n# bytes=%u\\r\\n",
'''
    if source.count(usb_format) != 1:
        raise SystemExit("V3 USB format anchor not found exactly once")
    source = source.replace(
        usb_format,
        '''                 "# log_format=%u\\r\\n# export=%s\\r\\n%s# bytes=%u\\r\\n",
''',
        1,
    )
    usb_args = '''                 diagRoleText(), DIAG_FEATURE_VERSION, (unsigned)DIAG_LOG_FORMAT, exportTime, (unsigned)exportTotalBytes);'''
    if source.count(usb_args) != 1:
        raise SystemExit("V3 USB args anchor not found exactly once")
    source = source.replace(
        usb_args,
        '''                 diagRoleText(), DIAG_FEATURE_VERSION, (unsigned)DIAG_LOG_FORMAT, exportTime, usbLiveBattery,
                 (unsigned)exportTotalBytes);''',
        1,
    )

for marker in (
    "avgListen=%ldmA avgService=%ldmA avgBle=%ldmA avgDisplay=%ldmA",
    "(long)power.listenAvgMa",
    "char usbLiveBattery[1050]",
    "char header[1800]",
    "usbLiveBattery,",
):
    if marker not in source:
        raise SystemExit(f"missing V3 live-snapshot marker: {marker}")

TARGET.write_text(source, encoding="utf-8")
print("V3 diagnostic BLE LIVE snapshot completed; USB now includes fresh LIVE BATTERY data")
