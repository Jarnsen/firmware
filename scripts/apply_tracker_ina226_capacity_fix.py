from pathlib import Path

COMMON = Path("src/vehicle/TrackerCommonPolicy.cpp")
STATUS = Path("src/vehicle/TrackerStatusModule.cpp")
POSITION = Path("src/modules/PositionModule.cpp")

common = COMMON.read_text()
status = STATUS.read_text()
position = POSITION.read_text()

def replace_once(text: str, old: str, new: str, label: str) -> str:
    if new in text:
        print(f"{label}: already applied")
        return text
    if old not in text:
        raise SystemExit(f"{label}: anchor not found")
    print(f"{label}: applied")
    return text.replace(old, new, 1)

old_counter = '''    if (positionModule) {
        positionModule->sendOurPosition();
        trackerPowerMonitorNotePositionTx();
    }
'''
count = common.count(old_counter)
if count:
    common = common.replace(old_counter, '''    if (positionModule)
        positionModule->sendOurPosition();
''')
    print(f"Tracker authoritative TX counter: removed common hooks x{count}")
elif "trackerPowerMonitorNotePositionTx();" in common:
    raise SystemExit("Tracker authoritative TX counter: unexpected common counter shape")

common = replace_once(common, '#include "NodeDB.h"\n', '#include "NodeDB.h"\n#include "GPSStatus.h"\n',
                      "Tracker post-wake GPS status include")

gps_helper = r'''bool gpsFixSince(uint32_t startedMs)
{
    if (!gpsStatus || !gpsStatus->getHasLock())
        return false;
    const uint32_t fixMs = gpsStatus->getLastFixMillis();
    return fixMs != 0 && (int32_t)(fixMs - startedMs) >= 0;
}

'''
if gps_helper not in common:
    marker = 'bool positionIsFresh()\n'
    pos = common.find(marker)
    if pos < 0:
        raise SystemExit("Tracker post-wake GPS helper: anchor not found")
    common = common[:pos] + gps_helper + common[pos:]
    print("Tracker post-wake GPS helper: applied")

common = replace_once(common,
    '''    if (sendFreshPosition(false)) {
        lastPositionHeartbeatEpoch = nowEpoch;
''',
    '''    if (gpsFixSince(parkHeartbeatFixStartedMs) && sendFreshPosition(false)) {
        lastPositionHeartbeatEpoch = nowEpoch;
''', "TAK heartbeat requires fix acquired after GNSS wake")

common = replace_once(common,
    '''        if (sendFreshPosition(true)) {
            timerPositionRequested = true;
''',
    '''        if (gpsFixSince(bootActivityMs) && sendFreshPosition(true)) {
            timerPositionRequested = true;
''', "TAK_TRACKER timer requires post-wake GNSS fix")

common = replace_once(common,
    '''        armDeepSleepMotionWake();

        const uint32_t sleepMs = trackerEffectiveParkIntervalSecs() * 1000UL;
''',
    '''        armDeepSleepMotionWake();
        trackerPowerMonitorPrepareForDeepSleep();

        const uint32_t sleepMs = trackerEffectiveParkIntervalSecs() * 1000UL;
''', "power down/persist INA226 before deep sleep")

position = replace_once(position,
    '''#include "vehicle/TrackerDiagnosticLog.h"
#endif
''',
    '''#include "vehicle/TrackerDiagnosticLog.h"
#include "vehicle/TrackerCommonPolicy.h"
#include "vehicle/TrackerPowerMonitor.h"
#endif
''', "PositionModule tracker power/common includes")

position = replace_once(position,
    '''    service->sendToMesh(p, RX_SRC_LOCAL, true);
''',
    '''    service->sendToMesh(p, RX_SRC_LOCAL, true);
#if defined(HELTEC_TRACKER_V1_1)
    if (config.device.role == meshtastic_Config_DeviceConfig_Role_TAK ||
        config.device.role == meshtastic_Config_DeviceConfig_Role_TAK_TRACKER)
        trackerPowerMonitorNotePositionTx();
#endif
''', "count actual Tracker position mesh sends")

position = replace_once(position,
    '''int32_t PositionModule::runOnce()
{
''',
    '''int32_t PositionModule::runOnce()
{
#if defined(HELTEC_TRACKER_V1_1)
    if ((config.device.role == meshtastic_Config_DeviceConfig_Role_TAK ||
         config.device.role == meshtastic_Config_DeviceConfig_Role_TAK_TRACKER) &&
        trackerCommonIsParked())
        return RUNONCE_INTERVAL;
#endif
''', "suppress generic PositionModule timer while parked")

position = replace_once(position,
    '''void PositionModule::handleNewPosition()
{
''',
    '''void PositionModule::handleNewPosition()
{
#if defined(HELTEC_TRACKER_V1_1)
    if ((config.device.role == meshtastic_Config_DeviceConfig_Role_TAK ||
         config.device.role == meshtastic_Config_DeviceConfig_Role_TAK_TRACKER) &&
        trackerCommonIsParked())
        return;
#endif
''', "suppress Smart Position callback while parked")

status = replace_once(status, '''    POWER_STATS,
};
''', '''    POWER_STATS,
    INA226_HW,
};
''', "INA226 menu state")

old_system = '''    case TrackerMenu::SYSTEM: {
        static const char *opts[] = {"Back", "System Info", "Diagnostics", "Power Statistics"};
        showTrackerOptions("System", opts, 4, initialSelection, [](int selected) {
            if (selected == 0) queueTrackerMenu(TrackerMenu::ROOT, trackerRootSelection);
            else if (selected == 1) queueTrackerMenu(TrackerMenu::SYSTEM_INFO, 0);
            else if (selected == 2) queueTrackerMenu(TrackerMenu::DIAGNOSTICS, 0);
            else if (selected == 3) queueTrackerMenu(TrackerMenu::POWER_STATS, 0);
        });
        break;
    }
'''
new_system = '''    case TrackerMenu::SYSTEM: {
        static const char *opts[] = {"Back", "System Info", "Diagnostics", "Power Statistics", "INA226 Hardware"};
        showTrackerOptions("System", opts, 5, initialSelection, [](int selected) {
            if (selected == 0) queueTrackerMenu(TrackerMenu::ROOT, trackerRootSelection);
            else if (selected == 1) queueTrackerMenu(TrackerMenu::SYSTEM_INFO, 0);
            else if (selected == 2) queueTrackerMenu(TrackerMenu::DIAGNOSTICS, 0);
            else if (selected == 3) queueTrackerMenu(TrackerMenu::POWER_STATS, 0);
            else if (selected == 4) queueTrackerMenu(TrackerMenu::INA226_HW, 0);
        });
        break;
    }
'''
status = replace_once(status, old_system, new_system, "add optional INA226 to System menu")

ina_and_power_cases = r'''    case TrackerMenu::INA226_HW: {
        static char offLine[24], onLine[24];
        static const char *opts[] = {"Back", offLine, onLine};
        const bool enabled = trackerIna226Enabled();
        markOption(offLine, sizeof(offLine), !enabled, "Off");
        markOption(onLine, sizeof(onLine), enabled, "On");
        showTrackerOptions("INA226 Hardware", opts, 3, initialSelection, [](int selected) {
            if (selected == 0) queueTrackerMenu(TrackerMenu::SYSTEM, 4);
            else {
                trackerSetIna226Enabled(selected == 2);
                queueTrackerMenu(TrackerMenu::INA226_HW, 0);
            }
        });
        break;
    }

    case TrackerMenu::POWER_STATS: {
        static char batteryLine[48], remainingLine[48], inaLine[48], currentLine[48], powerLine[48];
        static char usedLine[48], capacityLine[48], confidenceLine[48], measuredLine[48], movingLine[48];
        static char parkedLine[48], gnssLine[48], bleLine[48], displayLine[48], txLine[48], trendLine[48];
        static const char *opts[] = {"Back", batteryLine, remainingLine, inaLine, currentLine, powerLine, usedLine,
                                     capacityLine, confidenceLine, measuredLine, movingLine, parkedLine, gnssLine,
                                     bleLine, displayLine, txLine, trendLine};
        const TrackerPowerStats p = trackerPowerMonitorStats();
        if (p.batteryValid)
            snprintf(batteryLine, sizeof(batteryLine), "Battery: %u%%  %u.%03uV", (unsigned)p.batteryPercent,
                     (unsigned)(p.voltageMv / 1000U), (unsigned)(p.voltageMv % 1000U));
        else
            snprintf(batteryLine, sizeof(batteryLine), "Battery: unavailable");

        char duration[32] = {};
        if (p.usbPowered || p.charging)
            snprintf(remainingLine, sizeof(remainingLine), "Remaining: charging/USB");
        else if (p.estimateReady) {
            trackerPowerFormatDuration(p.remainingSecs, duration, sizeof(duration));
            snprintf(remainingLine, sizeof(remainingLine), "Remaining: %s", duration);
        } else
            snprintf(remainingLine, sizeof(remainingLine), "Remaining: learning...");

        if (!p.inaConfigured) snprintf(inaLine, sizeof(inaLine), "INA226: OFF");
        else if (!p.inaPresent) snprintf(inaLine, sizeof(inaLine), "INA226: MISSING");
        else if (!p.inaValid) snprintf(inaLine, sizeof(inaLine), "INA226: WAIT");
        else snprintf(inaLine, sizeof(inaLine), "INA226: ACTIVE  %umV", (unsigned)p.inaBusVoltageMv);

        if (p.inaValid) {
            const int32_t c = p.currentMilliAmpsX10;
            const int32_t ac = c < 0 ? -c : c;
            snprintf(currentLine, sizeof(currentLine), "Current: %s%ld.%ld mA", c < 0 ? "-" : "",
                     (long)(ac / 10), (long)(ac % 10));
            const int32_t w = p.powerMilliWattsX10;
            const int32_t aw = w < 0 ? -w : w;
            snprintf(powerLine, sizeof(powerLine), "Power: %s%ld.%ld mW", w < 0 ? "-" : "",
                     (long)(aw / 10), (long)(aw % 10));
        } else {
            snprintf(currentLine, sizeof(currentLine), "Current: --");
            snprintf(powerLine, sizeof(powerLine), "Power: --");
        }

        snprintf(usedLine, sizeof(usedLine), "Used: %u.%u mAh / %u.%u mWh",
                 (unsigned)(p.dischargedMahX10 / 10U), (unsigned)(p.dischargedMahX10 % 10U),
                 (unsigned)(p.dischargedMwhX10 / 10U), (unsigned)(p.dischargedMwhX10 % 10U));
        if (p.capacityReady)
            snprintf(capacityLine, sizeof(capacityLine), "Capacity: %u mAh", (unsigned)p.learnedCapacityMah);
        else
            snprintf(capacityLine, sizeof(capacityLine), "Capacity: learning...");
        snprintf(confidenceLine, sizeof(confidenceLine), "Confidence: %u%%  Cycles:%u",
                 (unsigned)p.capacityConfidence, (unsigned)p.capacityCycles);

        trackerPowerFormatDuration(p.measuredSecs, duration, sizeof(duration));
        snprintf(measuredLine, sizeof(measuredLine), "Measured: %s", duration);
        trackerPowerFormatDuration(p.movingSecs, duration, sizeof(duration));
        snprintf(movingLine, sizeof(movingLine), "Moving: %s", duration);
        trackerPowerFormatDuration(p.parkedSecs, duration, sizeof(duration));
        snprintf(parkedLine, sizeof(parkedLine), "Parked: %s", duration);
        trackerPowerFormatDuration(p.gnssSecs, duration, sizeof(duration));
        snprintf(gnssLine, sizeof(gnssLine), "GNSS: %s", duration);
        trackerPowerFormatDuration(p.bleSecs, duration, sizeof(duration));
        snprintf(bleLine, sizeof(bleLine), "BLE: %s", duration);
        trackerPowerFormatDuration(p.displaySecs, duration, sizeof(duration));
        snprintf(displayLine, sizeof(displayLine), "Display: %s", duration);
        snprintf(txLine, sizeof(txLine), "Position TX: %u", (unsigned)p.positionTxCount);
        if (p.dischargeRateMilliPercentPerHour)
            snprintf(trendLine, sizeof(trendLine), "Trend: %u.%03u%%/h",
                     (unsigned)(p.dischargeRateMilliPercentPerHour / 1000U),
                     (unsigned)(p.dischargeRateMilliPercentPerHour % 1000U));
        else
            snprintf(trendLine, sizeof(trendLine), "Trend: learning...");

        showTrackerOptions("Power Statistics", opts, 17, initialSelection, [](int selected) {
            if (selected == 0) queueTrackerMenu(TrackerMenu::SYSTEM, 3);
            else queueTrackerMenu(TrackerMenu::POWER_STATS, 0);
        });
        break;
    }

'''
start = status.find('    case TrackerMenu::POWER_STATS: {\n')
end = status.find('    default:\n', start)
if start < 0 or end < 0:
    raise SystemExit("INA226 Power Statistics replacement boundary not found")
status = status[:start] + ina_and_power_cases + status[end:]
print("INA226/Power Statistics pages: applied")

checks = [
    (common, "gpsFixSince(parkHeartbeatFixStartedMs)"),
    (common, "trackerPowerMonitorPrepareForDeepSleep();"),
    (position, "trackerPowerMonitorNotePositionTx();"),
    (position, "trackerCommonIsParked()"),
    (status, 'case TrackerMenu::INA226_HW:'),
    (status, '"INA226: MISSING"'),
    (status, '"Capacity: learning..."'),
    (status, "trackerSetIna226Enabled(selected == 2);"),
]
for text, needle in checks:
    if needle not in text:
        raise SystemExit(f"Tracker INA226/capacity verification failed: {needle}")

COMMON.write_text(common)
STATUS.write_text(status)
POSITION.write_text(position)
