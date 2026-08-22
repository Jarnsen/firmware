from pathlib import Path

COMMON = Path("src/vehicle/TrackerCommonPolicy.cpp")
STATUS = Path("src/vehicle/TrackerStatusModule.cpp")

common = COMMON.read_text()
status = STATUS.read_text()


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if new in text:
        print(f"{label}: already applied")
        return text
    if old not in text:
        raise SystemExit(f"{label}: anchor not found")
    print(f"{label}: applied")
    return text.replace(old, new, 1)


# Runtime integration: use Meshtastic's existing PowerStatus readings and feed
# the monitor only state that TrackerCommonPolicy already knows.
common = replace_once(
    common,
    '#include "TrackerStatusModule.h"\n',
    '#include "TrackerStatusModule.h"\n#include "vehicle/TrackerPowerMonitor.h"\n',
    'Tracker power monitor common include',
)

common = replace_once(
    common,
    '    trackerServiceSettingsInit();\n',
    '    trackerServiceSettingsInit();\n    trackerPowerMonitorInit();\n',
    'initialize Tracker power monitor',
)

old_send = '''    if (positionModule)\n        positionModule->sendOurPosition();\n'''
new_send = '''    if (positionModule) {\n        positionModule->sendOurPosition();\n        trackerPowerMonitorNotePositionTx();\n    }\n'''
count = common.count(old_send)
if count:
    common = common.replace(old_send, new_send)
    print(f'Tracker position TX counter: applied x{count}')
elif 'trackerPowerMonitorNotePositionTx();' in common:
    print('Tracker position TX counter: already applied')
else:
    raise SystemExit('Tracker position TX counter: sendOurPosition anchor not found')

common = replace_once(
    common,
    '''        updateLightSleepHeartbeat();\n        return bootHandoffComplete ? 10 : 20;\n''',
    '''        // GNSS is powered while moving/startup/final-fix work is active.\n        // Parked TAK keeps it down except during the heartbeat search window.\n        const bool gnssActiveForPower = !parked || motionActive || parkHeartbeatFixPending || finalPositionWaitStartedMs != 0;\n        trackerPowerMonitorTick(motionActive, parked, gnssActiveForPower, serviceActive,\n                                displayVisible && screen && screen->isScreenOn());\n\n        updateLightSleepHeartbeat();\n        return bootHandoffComplete ? 10 : 20;\n''',
    'feed Tracker runtime states to power monitor',
)

# UI integration.
status = replace_once(
    status,
    '#include "vehicle/TrackerDiagnosticLog.h"\n',
    '#include "vehicle/TrackerDiagnosticLog.h"\n#include "vehicle/TrackerPowerMonitor.h"\n',
    'Tracker power monitor UI include',
)

status = replace_once(
    status,
    '''    DIAGNOSTICS,\n};\n''',
    '''    DIAGNOSTICS,\n    POWER_STATS,\n};\n''',
    'Tracker power statistics menu state',
)

old_system = '''    case TrackerMenu::SYSTEM: {\n        static const char *opts[] = {"Back", "System Info", "Diagnostics"};\n        showTrackerOptions("System", opts, 3, initialSelection, [](int selected) {\n            if (selected == 0) queueTrackerMenu(TrackerMenu::ROOT, trackerRootSelection);\n            else if (selected == 1) queueTrackerMenu(TrackerMenu::SYSTEM_INFO, 0);\n            else if (selected == 2) queueTrackerMenu(TrackerMenu::DIAGNOSTICS, 0);\n        });\n        break;\n    }\n'''
new_system = '''    case TrackerMenu::SYSTEM: {\n        static const char *opts[] = {"Back", "System Info", "Diagnostics", "Power Statistics"};\n        showTrackerOptions("System", opts, 4, initialSelection, [](int selected) {\n            if (selected == 0) queueTrackerMenu(TrackerMenu::ROOT, trackerRootSelection);\n            else if (selected == 1) queueTrackerMenu(TrackerMenu::SYSTEM_INFO, 0);\n            else if (selected == 2) queueTrackerMenu(TrackerMenu::DIAGNOSTICS, 0);\n            else if (selected == 3) queueTrackerMenu(TrackerMenu::POWER_STATS, 0);\n        });\n        break;\n    }\n'''
status = replace_once(status, old_system, new_system, 'add Power Statistics to System menu')

# Save the learned trend/counters immediately before the intentional USB export
# reboot so the estimate survives downloading the diagnostic log.
status = replace_once(
    status,
    'else if (selected == 3) { trackerDiagRequestUsbExport(); queueTrackerMenu(TrackerMenu::LOG_EXPORT, 0); }',
    'else if (selected == 3) { trackerPowerMonitorPersist(); trackerDiagRequestUsbExport(); queueTrackerMenu(TrackerMenu::LOG_EXPORT, 0); }',
    'persist power statistics before USB log export',
)

power_case = r'''    case TrackerMenu::POWER_STATS: {
        static char batteryLine[48], remainingLine[48], measuredLine[48], movingLine[48], parkedLine[48];
        static char gnssLine[48], bleLine[48], displayLine[48], txLine[48], trendLine[48];
        static const char *opts[] = {"Back", batteryLine, remainingLine, measuredLine, movingLine, parkedLine,
                                     gnssLine, bleLine, displayLine, txLine, trendLine};

        const TrackerPowerStats p = trackerPowerMonitorStats();
        if (p.batteryValid)
            snprintf(batteryLine, sizeof(batteryLine), "Battery: %u%%  %.2fV", (unsigned)p.batteryPercent,
                     p.voltageMv / 1000.0f);
        else
            snprintf(batteryLine, sizeof(batteryLine), "Battery: unavailable");

        char duration[32] = {};
        if (p.usbPowered || p.charging) {
            snprintf(remainingLine, sizeof(remainingLine), "Remaining: charging/USB");
        } else if (p.estimateReady) {
            trackerPowerFormatDuration(p.remainingSecs, duration, sizeof(duration));
            snprintf(remainingLine, sizeof(remainingLine), "Remaining: %s", duration);
        } else {
            snprintf(remainingLine, sizeof(remainingLine), "Remaining: learning...");
        }

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

        showTrackerOptions("Power Statistics", opts, 11, initialSelection, [](int selected) {
            if (selected == 0) queueTrackerMenu(TrackerMenu::SYSTEM, 3);
            else queueTrackerMenu(TrackerMenu::POWER_STATS, 0);
        });
        break;
    }

'''

start = status.find('void showTrackerMenu(TrackerMenu menu, int initialSelection)\n')
end = status.find('bool trackerServiceMenuActive()\n', start)
if start < 0 or end < 0:
    raise SystemExit('Tracker Power Statistics: showTrackerMenu boundary not found')
segment = status[start:end]
if 'case TrackerMenu::POWER_STATS:' not in segment:
    default_pos = segment.rfind('    default:\n')
    if default_pos < 0:
        raise SystemExit('Tracker Power Statistics: final menu default not found')
    absolute = start + default_pos
    status = status[:absolute] + power_case + status[absolute:]
    print('Tracker Power Statistics page: applied')
else:
    print('Tracker Power Statistics page: already applied')

for text, needle in [
    (common, 'trackerPowerMonitorTick('),
    (common, 'trackerPowerMonitorNotePositionTx();'),
    (status, 'case TrackerMenu::POWER_STATS:'),
    (status, 'Remaining: learning...'),
    (status, 'trackerPowerMonitorPersist(); trackerDiagRequestUsbExport();'),
    (status, 'Power Statistics'),
]:
    if needle not in text:
        raise SystemExit(f'Tracker power monitor verification failed: {needle}')

COMMON.write_text(common)
STATUS.write_text(status)
