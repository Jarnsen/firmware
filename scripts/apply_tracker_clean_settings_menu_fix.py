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


def replace_all(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count == 0:
        if new in text:
            print(f"{label}: already applied")
            return text
        raise SystemExit(f"{label}: anchor not found")
    print(f"{label}: applied x{count}")
    return text.replace(old, new)


def replace_span(text: str, start_marker: str, end_marker: str, replacement: str, label: str) -> str:
    start = text.find(start_marker)
    if start < 0:
        raise SystemExit(f"{label}: start marker not found")
    end = text.find(end_marker, start)
    if end < 0:
        raise SystemExit(f"{label}: end marker not found")
    print(f"{label}: applied")
    return text[:start] + replacement + text[end:]


# ---------------------------------------------------------------------------
# Runtime policy: use the persisted service settings rather than hard-coded
# moving-GNSS / parked-GPS / BLE window constants. 10s is the new default for
# moving GNSS, but users can choose 5/10/15/30s from the menu.
# ---------------------------------------------------------------------------
common = replace_all(
    common,
    'config.position.gps_update_interval = TRACKER_COMMON_MOVING_GPS_UPDATE_SECS;',
    'config.position.gps_update_interval = trackerMovingGnssSecs();',
    'configurable moving GNSS interval',
)

common = replace_all(
    common,
    'TRACKER_COMMON_PARK_GPS_WAIT_MS',
    '((uint32_t)trackerParkGpsSearchSecs() * 1000UL)',
    'configurable parked GPS search time',
)

common = replace_once(
    common,
    '''    LOG_INFO("Tracker service: GPIO0 opened native Meshtastic UI + Bluetooth; idle=%us, activity=%u/%us, hard-cap=%us",\n             (unsigned)(TRACKER_COMMON_SERVICE_IDLE_MS / 1000UL), (unsigned)TRACKER_COMMON_BLE_ACTIVITY_THRESHOLD,\n             (unsigned)(TRACKER_COMMON_BLE_ACTIVITY_WINDOW_MS / 1000UL),\n             (unsigned)(TRACKER_COMMON_SERVICE_MAX_MS / 1000UL));\n''',
    '''    LOG_INFO("Tracker service: GPIO0 opened native Meshtastic UI + Bluetooth; idle=%us, activity=%u/%us, hard-cap=%us",\n             (unsigned)trackerBleIdleTimeoutSecs(), (unsigned)TRACKER_COMMON_BLE_ACTIVITY_THRESHOLD,\n             (unsigned)(TRACKER_COMMON_BLE_ACTIVITY_WINDOW_MS / 1000UL),\n             (unsigned)trackerBleHardTimeoutSecs());\n''',
    'dynamic BLE service-window log',
)

common = replace_once(
    common,
    '        LOG_DEBUG("Tracker service: active BLE burst detected; 120s idle timer reset");\n',
    '        LOG_DEBUG("Tracker service: active BLE burst detected; %us idle timer reset", (unsigned)trackerBleIdleTimeoutSecs());\n',
    'dynamic BLE idle-reset log',
)

common = replace_once(
    common,
    '''            const bool hardCap = (uint32_t)(now - serviceStartedMs) >= TRACKER_COMMON_SERVICE_MAX_MS;\n            const bool idle = (uint32_t)(now - serviceLastActivityMs) >= TRACKER_COMMON_SERVICE_IDLE_MS;\n''',
    '''            const bool hardCap = (uint32_t)(now - serviceStartedMs) >= (uint32_t)trackerBleHardTimeoutSecs() * 1000UL;\n            const bool idle = (uint32_t)(now - serviceLastActivityMs) >= (uint32_t)trackerBleIdleTimeoutSecs() * 1000UL;\n''',
    'dynamic BLE idle/hard timeout enforcement',
)

# TAK_TRACKER timer-cycle GPS search should obey the same selected parked GPS
# search time as TAK. The adaptive result recorder remains useful in the log,
# but the user's menu value is now the authoritative wait window.
common = replace_all(
    common,
    'vehicleAdaptiveTimerGpsWaitMs()',
    '((uint32_t)trackerParkGpsSearchSecs() * 1000UL)',
    'park GPS search applies to deep-sleep timer wakes',
)

# On service close, immediately re-apply the correct GNSS runtime policy. This
# makes a freshly changed Moving GNSS value effective without rebooting while
# still keeping parked TAK GNSS asleep.
common = replace_once(
    common,
    '''    closeDisplay();\n    trackerApplyPositionSettings();\n    LOG_INFO("Tracker service: native UI/Bluetooth window complete");\n''',
    '''    closeDisplay();\n    trackerApplyPositionSettings();\n    if (parked)\n        useParkedGnssPolicy();\n    else\n        useMovingGnssPolicy();\n    LOG_INFO("Tracker service: native UI/Bluetooth window complete");\n''',
    'apply selected GNSS policy after service menu closes',
)

# ---------------------------------------------------------------------------
# Menu state: settings only in Settings; runtime/status information moves to
# Diagnostics. This keeps the one-button menu short and predictable.
# ---------------------------------------------------------------------------
old_enum = '''enum class TrackerMenu : uint8_t {\n    NONE = 0,\n    ROOT,\n    POSITION,\n    DISTANCE,\n    INTERVAL,\n    MOTION,\n    MOTION_SENS,\n    PARK_POWER,\n    PARK_INTERVAL,\n    BLUETOOTH,\n    DIAG_LOG,\n    LOGGING,\n    LOG_STATUS,\n    LOG_CLEAR,\n    SYSTEM_INFO,\n};\n'''
new_enum = '''enum class TrackerMenu : uint8_t {\n    NONE = 0,\n    ROOT,\n    POSITION,\n    DISTANCE,\n    INTERVAL,\n    MOVING_GNSS,\n    MOTION,\n    MOTION_SENS,\n    PARK_POWER,\n    PARK_INTERVAL,\n    PARK_GPS_SEARCH,\n    BLUETOOTH,\n    BLE_IDLE,\n    BLE_HARD,\n    DIAG_LOG,\n    LOGGING,\n    LOG_STATUS,\n    LOG_CLEAR,\n    SYSTEM,\n    SYSTEM_INFO,\n    DIAGNOSTICS,\n};\n'''
status = replace_once(status, old_enum, new_enum, 'expanded clean Tracker menu state')

# Add helper selectors directly before showTrackerMenu().
helpers = r'''int movingGnssSelection()
{
    switch (trackerMovingGnssSecs()) {
    case 5: return 1;
    case 10: return 2;
    case 15: return 3;
    case 30: return 4;
    default: return 2;
    }
}

int parkGpsSearchSelection()
{
    switch (trackerParkGpsSearchSecs()) {
    case 15: return 1;
    case 30: return 2;
    case 45: return 3;
    case 60: return 4;
    default: return 2;
    }
}

int bleIdleSelection()
{
    switch (trackerBleIdleTimeoutSecs()) {
    case 60: return 1;
    case 120: return 2;
    case 180: return 3;
    case 300: return 4;
    default: return 2;
    }
}

int bleHardSelection()
{
    switch (trackerBleHardTimeoutSecs()) {
    case 300: return 1;
    case 600: return 2;
    case 900: return 3;
    case 1800: return 4;
    default: return 3;
    }
}

'''
if helpers not in status:
    anchor = 'void showTrackerMenu(TrackerMenu menu, int initialSelection)\n'
    if anchor not in status:
        raise SystemExit('Tracker clean menu helpers: showTrackerMenu anchor not found')
    status = status.replace(anchor, helpers + anchor, 1)
    print('Tracker clean menu selectors: applied')

new_menu = r'''void showTrackerMenu(TrackerMenu menu, int initialSelection)
{
    trackerMenuCurrent = menu;
    trackerMenuPending = TrackerMenu::NONE;

    switch (menu) {
    case TrackerMenu::ROOT: {
        static const char *opts[] = {"Back", "Position", "Motion", "Parking", "Bluetooth", "Diagnostic Log", "System"};
        showTrackerOptions("Service Settings", opts, 7, initialSelection, [](int selected) {
            trackerRootSelection = selected;
            switch (selected) {
            case 0:
                trackerServiceMenuMode = false;
                trackerMenuCurrent = TrackerMenu::NONE;
                trackerServiceModule.requestServiceFocus();
                if (screen) { screen->setFrames(graphics::Screen::FOCUS_MODULE); screen->runNow(); }
                break;
            case 1: queueTrackerMenu(TrackerMenu::POSITION, 0); break;
            case 2: queueTrackerMenu(TrackerMenu::MOTION, 0); break;
            case 3: queueTrackerMenu(TrackerMenu::PARK_POWER, 0); break;
            case 4: queueTrackerMenu(TrackerMenu::BLUETOOTH, 0); break;
            case 5: queueTrackerMenu(TrackerMenu::DIAG_LOG, 0); break;
            case 6: queueTrackerMenu(TrackerMenu::SYSTEM, 0); break;
            }
        });
        break;
    }

    case TrackerMenu::POSITION: {
        static const char *opts[] = {"Back", "Smart Distance", "Min TX Interval", "Moving GNSS"};
        showTrackerOptions("Position", opts, 4, initialSelection, [](int selected) {
            trackerPositionSelection = selected;
            if (selected == 0) queueTrackerMenu(TrackerMenu::ROOT, trackerRootSelection);
            else if (selected == 1) queueTrackerMenu(TrackerMenu::DISTANCE, 0);
            else if (selected == 2) queueTrackerMenu(TrackerMenu::INTERVAL, 0);
            else if (selected == 3) queueTrackerMenu(TrackerMenu::MOVING_GNSS, 0);
        });
        break;
    }

    case TrackerMenu::DISTANCE: {
        static char labels[5][24];
        static const char *opts[5] = {labels[0], labels[1], labels[2], labels[3], labels[4]};
        snprintf(labels[0], sizeof(labels[0]), "Back");
        const uint16_t vals[] = {50, 75, 100, 150};
        for (int i = 0; i < 4; ++i) {
            char raw[12]; snprintf(raw, sizeof(raw), "%u m", (unsigned)vals[i]);
            markOption(labels[i + 1], sizeof(labels[i + 1]), trackerSmartDistanceM() == vals[i], raw);
        }
        showTrackerOptions("Smart Distance", opts, 5, initialSelection, [](int selected) {
            if (selected == 0) queueTrackerMenu(TrackerMenu::POSITION, trackerPositionSelection);
            else { const uint16_t vals[] = {50, 75, 100, 150}; trackerSetSmartDistanceM(vals[selected - 1]); queueTrackerMenu(TrackerMenu::DISTANCE, 0); }
        });
        break;
    }

    case TrackerMenu::INTERVAL: {
        static char labels[5][24];
        static const char *opts[5] = {labels[0], labels[1], labels[2], labels[3], labels[4]};
        snprintf(labels[0], sizeof(labels[0]), "Back");
        const uint16_t vals[] = {30, 45, 60, 90};
        for (int i = 0; i < 4; ++i) {
            char raw[12]; snprintf(raw, sizeof(raw), "%u s", (unsigned)vals[i]);
            markOption(labels[i + 1], sizeof(labels[i + 1]), trackerSmartIntervalSecs() == vals[i], raw);
        }
        showTrackerOptions("Min TX Interval", opts, 5, initialSelection, [](int selected) {
            if (selected == 0) queueTrackerMenu(TrackerMenu::POSITION, trackerPositionSelection);
            else { const uint16_t vals[] = {30, 45, 60, 90}; trackerSetSmartIntervalSecs(vals[selected - 1]); queueTrackerMenu(TrackerMenu::INTERVAL, 0); }
        });
        break;
    }

    case TrackerMenu::MOVING_GNSS: {
        static char labels[5][24];
        static const char *opts[5] = {labels[0], labels[1], labels[2], labels[3], labels[4]};
        snprintf(labels[0], sizeof(labels[0]), "Back");
        const uint16_t vals[] = {5, 10, 15, 30};
        for (int i = 0; i < 4; ++i) {
            char raw[12]; snprintf(raw, sizeof(raw), "%u s", (unsigned)vals[i]);
            markOption(labels[i + 1], sizeof(labels[i + 1]), trackerMovingGnssSecs() == vals[i], raw);
        }
        showTrackerOptions("Moving GNSS", opts, 5, initialSelection, [](int selected) {
            if (selected == 0) queueTrackerMenu(TrackerMenu::POSITION, trackerPositionSelection);
            else { const uint16_t vals[] = {5, 10, 15, 30}; trackerSetMovingGnssSecs(vals[selected - 1]); queueTrackerMenu(TrackerMenu::MOVING_GNSS, 0); }
        });
        break;
    }

    case TrackerMenu::MOTION: {
        static const char *opts[] = {"Back", "Sensitivity"};
        showTrackerOptions("Motion", opts, 2, initialSelection, [](int selected) {
            trackerMotionSelection = selected;
            if (selected == 0) queueTrackerMenu(TrackerMenu::ROOT, trackerRootSelection);
            else if (selected == 1) queueTrackerMenu(TrackerMenu::MOTION_SENS, 0);
        });
        break;
    }

    case TrackerMenu::MOTION_SENS: {
        static char labels[5][28];
        static const char *opts[5] = {labels[0], labels[1], labels[2], labels[3], labels[4]};
        snprintf(labels[0], sizeof(labels[0]), "Back");
        const char *names[] = {"VERY SENS", "SENSITIVE", "NORMAL", "ROBUST"};
        for (int i = 0; i < 4; ++i)
            markOption(labels[i + 1], sizeof(labels[i + 1]), trackerMotionSensitivityIndex() == i, names[i]);
        showTrackerOptions("Sensitivity", opts, 5, initialSelection, [](int selected) {
            if (selected == 0) queueTrackerMenu(TrackerMenu::MOTION, trackerMotionSelection);
            else { trackerSetMotionSensitivityIndex((uint8_t)(selected - 1)); queueTrackerMenu(TrackerMenu::MOTION_SENS, 0); }
        });
        break;
    }

    case TrackerMenu::PARK_POWER: {
        static const char *opts[] = {"Back", "Park Interval", "GPS Search Time"};
        showTrackerOptions("Parking", opts, 3, initialSelection, [](int selected) {
            trackerParkSelection = selected;
            if (selected == 0) queueTrackerMenu(TrackerMenu::ROOT, trackerRootSelection);
            else if (selected == 1) queueTrackerMenu(TrackerMenu::PARK_INTERVAL, 0);
            else if (selected == 2) queueTrackerMenu(TrackerMenu::PARK_GPS_SEARCH, 0);
        });
        break;
    }

    case TrackerMenu::PARK_INTERVAL: {
        static char labels[9][24];
        static const char *opts[9] = {labels[0], labels[1], labels[2], labels[3], labels[4], labels[5], labels[6], labels[7], labels[8]};
        const uint16_t vals[] = {20, 30, 60, 120, 240, 360, 540, 720};
        const char *names[] = {"20 min", "30 min", "60 min", "2 h", "4 h", "6 h", "9 h", "12 h"};
        snprintf(labels[0], sizeof(labels[0]), "Back");
        for (int i = 0; i < 8; ++i)
            markOption(labels[i + 1], sizeof(labels[i + 1]), trackerParkIntervalMinutes() == vals[i], names[i]);
        showTrackerOptions("Park Interval", opts, 9, initialSelection, [](int selected) {
            if (selected == 0) queueTrackerMenu(TrackerMenu::PARK_POWER, trackerParkSelection);
            else { const uint16_t vals[] = {20, 30, 60, 120, 240, 360, 540, 720}; trackerSetParkIntervalMinutes(vals[selected - 1]); queueTrackerMenu(TrackerMenu::PARK_INTERVAL, 0); }
        });
        break;
    }

    case TrackerMenu::PARK_GPS_SEARCH: {
        static char labels[5][24];
        static const char *opts[5] = {labels[0], labels[1], labels[2], labels[3], labels[4]};
        snprintf(labels[0], sizeof(labels[0]), "Back");
        const uint16_t vals[] = {15, 30, 45, 60};
        for (int i = 0; i < 4; ++i) {
            char raw[12]; snprintf(raw, sizeof(raw), "%u s", (unsigned)vals[i]);
            markOption(labels[i + 1], sizeof(labels[i + 1]), trackerParkGpsSearchSecs() == vals[i], raw);
        }
        showTrackerOptions("GPS Search Time", opts, 5, initialSelection, [](int selected) {
            if (selected == 0) queueTrackerMenu(TrackerMenu::PARK_POWER, trackerParkSelection);
            else { const uint16_t vals[] = {15, 30, 45, 60}; trackerSetParkGpsSearchSecs(vals[selected - 1]); queueTrackerMenu(TrackerMenu::PARK_GPS_SEARCH, 0); }
        });
        break;
    }

    case TrackerMenu::BLUETOOTH: {
        static const char *opts[] = {"Back", "Idle Timeout", "Hard Timeout"};
        showTrackerOptions("Bluetooth", opts, 3, initialSelection, [](int selected) {
            trackerBluetoothSelection = selected;
            if (selected == 0) queueTrackerMenu(TrackerMenu::ROOT, trackerRootSelection);
            else if (selected == 1) queueTrackerMenu(TrackerMenu::BLE_IDLE, 0);
            else if (selected == 2) queueTrackerMenu(TrackerMenu::BLE_HARD, 0);
        });
        break;
    }

    case TrackerMenu::BLE_IDLE: {
        static char labels[5][24];
        static const char *opts[5] = {labels[0], labels[1], labels[2], labels[3], labels[4]};
        snprintf(labels[0], sizeof(labels[0]), "Back");
        const uint16_t vals[] = {60, 120, 180, 300};
        const char *names[] = {"60 s", "120 s", "180 s", "300 s"};
        for (int i = 0; i < 4; ++i) markOption(labels[i + 1], sizeof(labels[i + 1]), trackerBleIdleTimeoutSecs() == vals[i], names[i]);
        showTrackerOptions("Idle Timeout", opts, 5, initialSelection, [](int selected) {
            if (selected == 0) queueTrackerMenu(TrackerMenu::BLUETOOTH, trackerBluetoothSelection);
            else { const uint16_t vals[] = {60, 120, 180, 300}; trackerSetBleIdleTimeoutSecs(vals[selected - 1]); queueTrackerMenu(TrackerMenu::BLE_IDLE, 0); }
        });
        break;
    }

    case TrackerMenu::BLE_HARD: {
        static char labels[5][24];
        static const char *opts[5] = {labels[0], labels[1], labels[2], labels[3], labels[4]};
        snprintf(labels[0], sizeof(labels[0]), "Back");
        const uint16_t vals[] = {300, 600, 900, 1800};
        const char *names[] = {"5 min", "10 min", "15 min", "30 min"};
        for (int i = 0; i < 4; ++i) markOption(labels[i + 1], sizeof(labels[i + 1]), trackerBleHardTimeoutSecs() == vals[i], names[i]);
        showTrackerOptions("Hard Timeout", opts, 5, initialSelection, [](int selected) {
            if (selected == 0) queueTrackerMenu(TrackerMenu::BLUETOOTH, trackerBluetoothSelection);
            else { const uint16_t vals[] = {300, 600, 900, 1800}; trackerSetBleHardTimeoutSecs(vals[selected - 1]); queueTrackerMenu(TrackerMenu::BLE_HARD, 0); }
        });
        break;
    }

    case TrackerMenu::DIAG_LOG: {
        static const char *opts[] = {"Back", "Logging", "Log Status", "Export via USB", "Clear Log"};
        showTrackerOptions("Diagnostic Log", opts, 5, initialSelection, [](int selected) {
            trackerDiagSelection = selected;
            if (selected == 0) queueTrackerMenu(TrackerMenu::ROOT, trackerRootSelection);
            else if (selected == 1) queueTrackerMenu(TrackerMenu::LOGGING, 0);
            else if (selected == 2) queueTrackerMenu(TrackerMenu::LOG_STATUS, 0);
            else if (selected == 3) { trackerDiagRequestUsbExport(); queueTrackerMenu(TrackerMenu::DIAG_LOG, 0); }
            else if (selected == 4) queueTrackerMenu(TrackerMenu::LOG_CLEAR, 0);
        });
        break;
    }

    case TrackerMenu::LOGGING: {
        static char off[24], on[24];
        static const char *opts[] = {"Back", off, on};
        markOption(off, sizeof(off), !trackerDiagEnabled(), "Off");
        markOption(on, sizeof(on), trackerDiagEnabled(), "On");
        showTrackerOptions("Diagnostic Logging", opts, 3, initialSelection, [](int selected) {
            if (selected == 0) queueTrackerMenu(TrackerMenu::DIAG_LOG, trackerDiagSelection);
            else { trackerDiagSetEnabled(selected == 2); queueTrackerMenu(TrackerMenu::LOGGING, 0); }
        });
        break;
    }

    case TrackerMenu::LOG_STATUS: {
        static char sizeLine[40], exportLine[40];
        static const char *opts[] = {"Back", sizeLine, exportLine};
        snprintf(sizeLine, sizeof(sizeLine), "Size: %u KB", (unsigned)((trackerDiagLogSize() + 1023U) / 1024U));
        snprintf(exportLine, sizeof(exportLine), "USB export: %s", trackerDiagUsbExportPending() ? "WAIT/RUN" : "READY");
        showTrackerOptions("Log Status", opts, 3, initialSelection, [](int selected) {
            if (selected == 0) queueTrackerMenu(TrackerMenu::DIAG_LOG, trackerDiagSelection);
            else queueTrackerMenu(TrackerMenu::LOG_STATUS, 0);
        });
        break;
    }

    case TrackerMenu::LOG_CLEAR: {
        static const char *opts[] = {"Back", "CLEAR LOG NOW"};
        showTrackerOptions("Clear Diagnostic Log?", opts, 2, initialSelection, [](int selected) {
            if (selected == 0) queueTrackerMenu(TrackerMenu::DIAG_LOG, trackerDiagSelection);
            else { trackerDiagClear(); queueTrackerMenu(TrackerMenu::LOG_CLEAR, 0); }
        });
        break;
    }

    case TrackerMenu::SYSTEM: {
        static const char *opts[] = {"Back", "System Info", "Diagnostics"};
        showTrackerOptions("System", opts, 3, initialSelection, [](int selected) {
            if (selected == 0) queueTrackerMenu(TrackerMenu::ROOT, trackerRootSelection);
            else if (selected == 1) queueTrackerMenu(TrackerMenu::SYSTEM_INFO, 0);
            else if (selected == 2) queueTrackerMenu(TrackerMenu::DIAGNOSTICS, 0);
        });
        break;
    }

    case TrackerMenu::SYSTEM_INFO: {
        static char version[48], build[40], role[40];
        static const char *opts[] = {"Back", version, build, role};
        snprintf(version, sizeof(version), "FW: %s", JARNSEN_FIRMWARE_VERSION);
        snprintf(build, sizeof(build), "Build: %.8s", JARNSEN_BUILD_SHA);
        snprintf(role, sizeof(role), "Role: %s", config.device.role == meshtastic_Config_DeviceConfig_Role_TAK_TRACKER ? "TAK_TRACKER" : "TAK");
        showTrackerOptions("System Info", opts, 4, initialSelection, [](int selected) {
            if (selected == 0) queueTrackerMenu(TrackerMenu::SYSTEM, 1);
            else queueTrackerMenu(TrackerMenu::SYSTEM_INFO, 0);
        });
        break;
    }

    case TrackerMenu::DIAGNOSTICS: {
        static char state[40], gpsAge[40], sensor[40], wake[48], mode[40];
        static const char *opts[] = {"Back", state, gpsAge, sensor, wake, mode};
        snprintf(state, sizeof(state), "State: %s", trackerCommonRuntimeState());
        const uint32_t age = trackerLastFixAgeSecs();
        if (age == UINT32_MAX) snprintf(gpsAge, sizeof(gpsAge), "GPS age: ?");
        else snprintf(gpsAge, sizeof(gpsAge), "GPS age: %us", (unsigned)age);
        snprintf(sensor, sizeof(sensor), "Sensor: %s", trackerMotionSensorStatus());
        snprintf(wake, sizeof(wake), "Wake: %s", trackerBootWakeReason());
        snprintf(mode, sizeof(mode), "Sleep: %s", config.device.role == meshtastic_Config_DeviceConfig_Role_TAK_TRACKER ? "Deep" : "Light");
        showTrackerOptions("Diagnostics", opts, 6, initialSelection, [](int selected) {
            if (selected == 0) queueTrackerMenu(TrackerMenu::SYSTEM, 2);
            else queueTrackerMenu(TrackerMenu::DIAGNOSTICS, 0);
        });
        break;
    }

    default:
        break;
    }
}

'''
status = replace_span(
    status,
    'void showTrackerMenu(TrackerMenu menu, int initialSelection)\n',
    'bool trackerServiceMenuActive()\n',
    new_menu,
    'clean Tracker settings/status menu hierarchy',
)

for needle in [
    'trackerMovingGnssSecs()',
    'trackerParkGpsSearchSecs()',
    'trackerBleIdleTimeoutSecs()',
    'trackerBleHardTimeoutSecs()',
    'case TrackerMenu::MOVING_GNSS:',
    'case TrackerMenu::PARK_GPS_SEARCH:',
    'case TrackerMenu::BLE_IDLE:',
    'case TrackerMenu::BLE_HARD:',
    'case TrackerMenu::DIAGNOSTICS:',
    'static const char *opts[] = {"Back", "Sensitivity"};',
    'static const char *opts[] = {"Back", "Park Interval", "GPS Search Time"};',
]:
    if needle not in common and needle not in status:
        raise SystemExit(f"Tracker clean settings-menu verification failed: {needle}")

if 'Local GNSS: 5 s' in status or 'Sensor: %s", trackerMotionSensorStatus()' in status[status.find('case TrackerMenu::MOTION:'):status.find('case TrackerMenu::MOTION_SENS:')]:
    raise SystemExit('Tracker clean settings-menu verification failed: stale status rows remain in Settings')

COMMON.write_text(common)
STATUS.write_text(status)
