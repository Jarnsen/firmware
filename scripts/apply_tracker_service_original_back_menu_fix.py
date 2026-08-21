from pathlib import Path

PATH = Path("src/vehicle/TrackerStatusModule.cpp")
text = PATH.read_text()


def replace_once(old: str, new: str, label: str):
    global text
    if new in text:
        print(f"{label}: already applied")
        return
    if old not in text:
        raise SystemExit(f"{label}: anchor not found")
    text = text.replace(old, new, 1)
    print(f"{label}: applied")


# Match the original one-button menu model:
# - Point 0 is the passive Service overview.
# - Long opens the root menu.
# - Short moves to the next item.
# - Long activates the selected item.
# - Settings is a child menu and both levels have a real BACK item.
# - Long on a setting cycles/saves the value immediately, exactly like the
#   original V3-style service menu.
replace_once(
    '''enum TrackerServicePage : uint8_t {\n    TRACKER_SERVICE_OVERVIEW = 0,\n    TRACKER_SERVICE_DIAG,\n    TRACKER_SERVICE_VERSION,\n    TRACKER_SERVICE_MOTION,\n    TRACKER_SERVICE_DISTANCE,\n    TRACKER_SERVICE_INTERVAL,\n    TRACKER_SERVICE_PARK,\n    TRACKER_SERVICE_EXIT,\n    TRACKER_SERVICE_PAGE_COUNT,\n};\n\nbool trackerServiceMenuMode = false;\nuint8_t trackerServicePage = TRACKER_SERVICE_OVERVIEW;\n''',
    '''enum TrackerServicePage : uint8_t {\n    TRACKER_SERVICE_ROOT_STATUS = 0,\n    TRACKER_SERVICE_ROOT_DIAG,\n    TRACKER_SERVICE_ROOT_VERSION,\n    TRACKER_SERVICE_ROOT_SETTINGS,\n    TRACKER_SERVICE_ROOT_BACK,\n    TRACKER_SERVICE_SETTINGS_MOTION,\n    TRACKER_SERVICE_SETTINGS_DISTANCE,\n    TRACKER_SERVICE_SETTINGS_INTERVAL,\n    TRACKER_SERVICE_SETTINGS_PARK,\n    TRACKER_SERVICE_SETTINGS_BACK,\n};\n\nbool trackerServiceMenuMode = false;\nbool trackerServiceSettingsLevel = false;\nuint8_t trackerServicePage = TRACKER_SERVICE_ROOT_STATUS;\n''',
    "two-level original-style Tracker service menu state",
)

old_switch = '''        switch ((TrackerServicePage)trackerServicePage) {\n        case TRACKER_SERVICE_OVERVIEW:\n            snprintf(line, sizeof(line), "Motion %s | Smart %um/%us", trackerMotionSensitivityName(),\n                     (unsigned)trackerSmartDistanceM(), (unsigned)trackerSmartIntervalSecs());\n            display->drawString(center, 32 + y, line);\n            snprintf(line, sizeof(line), "Park %umin (eff %us)", (unsigned)trackerParkIntervalMinutes(),\n                     (unsigned)trackerEffectiveParkIntervalSecs());\n            display->drawString(center, 47 + y, line);\n            display->drawString(center, 62 + y, trackerServiceMenuMode ? "SHORT: NEXT" : "HOLD GPIO0: MENU");\n            break;\n        case TRACKER_SERVICE_DIAG:\n            snprintf(line, sizeof(line), "GPS age %us | %s", trackerLastFixAgeSecs() == UINT32_MAX ? 9999U :\n                         (unsigned)trackerLastFixAgeSecs(), trackerMotionSensorStatus());\n            display->drawString(center, 32 + y, line);\n            snprintf(line, sizeof(line), "miss %u | wake %s", (unsigned)trackerMotionSensorMissedMovementEvents(),\n                     trackerBootWakeReason());\n            display->drawString(center, 48 + y, line);\n            break;\n        case TRACKER_SERVICE_VERSION:\n            snprintf(line, sizeof(line), "%s", JARNSEN_FIRMWARE_VERSION);\n            display->drawString(center, 32 + y, line);\n            snprintf(line, sizeof(line), "build %.8s | up %umin", JARNSEN_BUILD_SHA, (unsigned)(millis() / 60000UL));\n            display->drawString(center, 48 + y, line);\n            break;\n        case TRACKER_SERVICE_MOTION:\n            snprintf(line, sizeof(line), "Motion: %s", trackerMotionSensitivityName());\n            display->drawString(center, 30 + y, line);\n            snprintf(line, sizeof(line), "%u pulses / %us", (unsigned)trackerMotionConfirmCount(),\n                     (unsigned)(trackerMotionConfirmWindowMs() / 1000UL));\n            display->drawString(center, 46 + y, line);\n            display->drawString(center, 62 + y, "HOLD: CHANGE");\n            break;\n        case TRACKER_SERVICE_DISTANCE:\n            snprintf(line, sizeof(line), "Min distance: %u m", (unsigned)trackerSmartDistanceM());\n            display->drawString(center, 36 + y, line);\n            display->drawString(center, 57 + y, "HOLD: CHANGE");\n            break;\n        case TRACKER_SERVICE_INTERVAL:\n            snprintf(line, sizeof(line), "Min interval: %u s", (unsigned)trackerSmartIntervalSecs());\n            display->drawString(center, 36 + y, line);\n            display->drawString(center, 57 + y, "HOLD: CHANGE");\n            break;\n        case TRACKER_SERVICE_PARK:\n            snprintf(line, sizeof(line), "Park: %u min", (unsigned)trackerParkIntervalMinutes());\n            display->drawString(center, 32 + y, line);\n            snprintf(line, sizeof(line), "effective: %u s", (unsigned)trackerEffectiveParkIntervalSecs());\n            display->drawString(center, 48 + y, line);\n            display->drawString(center, 64 + y, "HOLD: CHANGE");\n            break;\n        case TRACKER_SERVICE_EXIT:\n            display->drawString(center, 37 + y, "SERVICE MENU EXIT");\n            display->drawString(center, 57 + y, "HOLD: EXIT");\n            break;\n        default:\n            trackerServicePage = TRACKER_SERVICE_OVERVIEW;\n            break;\n        }\n'''
new_switch = '''        // Point 0: passive Service overview outside the menu hierarchy.\n        if (!trackerServiceMenuMode) {\n            snprintf(line, sizeof(line), "Motion %s  %um/%us", trackerMotionSensitivityName(),\n                     (unsigned)trackerSmartDistanceM(), (unsigned)trackerSmartIntervalSecs());\n            display->drawString(center, 31 + y, line);\n            snprintf(line, sizeof(line), "Park %umin  eff %us", (unsigned)trackerParkIntervalMinutes(),\n                     (unsigned)trackerEffectiveParkIntervalSecs());\n            display->drawString(center, 47 + y, line);\n            display->drawString(center, 63 + y, "HOLD: MENU");\n            return;\n        }\n\n        switch ((TrackerServicePage)trackerServicePage) {\n        case TRACKER_SERVICE_ROOT_STATUS:\n            snprintf(line, sizeof(line), "STATUS  GPS %s", trackerLastFixAgeSecs() == UINT32_MAX ? "WAIT" : "FIX");\n            display->drawString(center, 30 + y, line);\n            snprintf(line, sizeof(line), "Motion %s  Park %umin", trackerMotionSensitivityName(),\n                     (unsigned)trackerParkIntervalMinutes());\n            display->drawString(center, 46 + y, line);\n            display->drawString(center, 62 + y, "SHORT: NEXT");\n            break;\n        case TRACKER_SERVICE_ROOT_DIAG:\n            snprintf(line, sizeof(line), "DIAG  GPS AGE %us", trackerLastFixAgeSecs() == UINT32_MAX ? 9999U :\n                         (unsigned)trackerLastFixAgeSecs());\n            display->drawString(center, 30 + y, line);\n            snprintf(line, sizeof(line), "%s  MISS %u", trackerMotionSensorStatus(),\n                     (unsigned)trackerMotionSensorMissedMovementEvents());\n            display->drawString(center, 46 + y, line);\n            display->drawString(center, 62 + y, "SHORT: NEXT");\n            break;\n        case TRACKER_SERVICE_ROOT_VERSION:\n            snprintf(line, sizeof(line), "%s", JARNSEN_FIRMWARE_VERSION);\n            display->drawString(center, 30 + y, line);\n            snprintf(line, sizeof(line), "BUILD %.8s  UP %umin", JARNSEN_BUILD_SHA, (unsigned)(millis() / 60000UL));\n            display->drawString(center, 46 + y, line);\n            display->drawString(center, 62 + y, "SHORT: NEXT");\n            break;\n        case TRACKER_SERVICE_ROOT_SETTINGS:\n            display->drawString(center, 34 + y, "EINSTELLUNGEN");\n            display->drawString(center, 54 + y, "LONG: OPEN");\n            break;\n        case TRACKER_SERVICE_ROOT_BACK:\n            display->drawString(center, 34 + y, "ZURUECK");\n            display->drawString(center, 54 + y, "LONG: BACK -> PUNKT 0");\n            break;\n        case TRACKER_SERVICE_SETTINGS_MOTION:\n            snprintf(line, sizeof(line), "MOTION %s", trackerMotionSensitivityName());\n            display->drawString(center, 30 + y, line);\n            snprintf(line, sizeof(line), "%u PULSES / %us", (unsigned)trackerMotionConfirmCount(),\n                     (unsigned)(trackerMotionConfirmWindowMs() / 1000UL));\n            display->drawString(center, 46 + y, line);\n            display->drawString(center, 62 + y, "LONG: CHANGE");\n            break;\n        case TRACKER_SERVICE_SETTINGS_DISTANCE:\n            snprintf(line, sizeof(line), "MIN DISTANCE  %u m", (unsigned)trackerSmartDistanceM());\n            display->drawString(center, 37 + y, line);\n            display->drawString(center, 57 + y, "LONG: CHANGE");\n            break;\n        case TRACKER_SERVICE_SETTINGS_INTERVAL:\n            snprintf(line, sizeof(line), "MIN INTERVAL  %u s", (unsigned)trackerSmartIntervalSecs());\n            display->drawString(center, 37 + y, line);\n            display->drawString(center, 57 + y, "LONG: CHANGE");\n            break;\n        case TRACKER_SERVICE_SETTINGS_PARK:\n            snprintf(line, sizeof(line), "PARK UPDATE  %u min", (unsigned)trackerParkIntervalMinutes());\n            display->drawString(center, 31 + y, line);\n            snprintf(line, sizeof(line), "effective %u s", (unsigned)trackerEffectiveParkIntervalSecs());\n            display->drawString(center, 47 + y, line);\n            display->drawString(center, 63 + y, "LONG: CHANGE");\n            break;\n        case TRACKER_SERVICE_SETTINGS_BACK:\n            display->drawString(center, 34 + y, "ZURUECK");\n            display->drawString(center, 54 + y, "LONG: BACK");\n            break;\n        default:\n            trackerServiceSettingsLevel = false;\n            trackerServicePage = TRACKER_SERVICE_ROOT_STATUS;\n            break;\n        }\n'''
replace_once(old_switch, new_switch, "original-style Tracker service pages and BACK entries")

replace_once(
    '''    trackerServiceMenuMode = true;\n    trackerServicePage = TRACKER_SERVICE_OVERVIEW;\n''',
    '''    trackerServiceMenuMode = true;\n    trackerServiceSettingsLevel = false;\n    trackerServicePage = TRACKER_SERVICE_ROOT_STATUS;\n''',
    "open Tracker service root menu",
)

replace_once(
    '''    trackerServicePage = (uint8_t)((trackerServicePage + 1U) % TRACKER_SERVICE_PAGE_COUNT);\n    if (screen)\n        screen->runNow();\n''',
    '''    if (trackerServiceSettingsLevel) {\n        trackerServicePage++;\n        if (trackerServicePage > TRACKER_SERVICE_SETTINGS_BACK || trackerServicePage < TRACKER_SERVICE_SETTINGS_MOTION)\n            trackerServicePage = TRACKER_SERVICE_SETTINGS_MOTION;\n    } else {\n        trackerServicePage++;\n        if (trackerServicePage > TRACKER_SERVICE_ROOT_BACK)\n            trackerServicePage = TRACKER_SERVICE_ROOT_STATUS;\n    }\n    if (screen)\n        screen->runNow();\n''',
    "short press cycles only current Tracker service level",
)

replace_once(
    '''    trackerServiceMenuMode = false;\n    trackerServicePage = TRACKER_SERVICE_OVERVIEW;\n    trackerStatusRequestFocus();\n''',
    '''    trackerServiceMenuMode = false;\n    trackerServiceSettingsLevel = false;\n    trackerServicePage = TRACKER_SERVICE_ROOT_STATUS;\n    trackerServiceModule.requestServiceFocus();\n    if (screen) {\n        screen->setFrames(graphics::Screen::FOCUS_MODULE);\n        screen->runNow();\n    }\n''',
    "root BACK returns to Service point 0",
)

old_long = '''    switch ((TrackerServicePage)trackerServicePage) {\n    case TRACKER_SERVICE_MOTION:\n        trackerCycleMotionSensitivity();\n        break;\n    case TRACKER_SERVICE_DISTANCE:\n        trackerCycleSmartDistance();\n        break;\n    case TRACKER_SERVICE_INTERVAL:\n        trackerCycleSmartInterval();\n        break;\n    case TRACKER_SERVICE_PARK:\n        trackerCycleParkInterval();\n        break;\n    case TRACKER_SERVICE_EXIT:\n        trackerServiceMenuClose();\n        return;\n    default:\n        return;\n    }\n    if (screen)\n        screen->runNow();\n'''
new_long = '''    switch ((TrackerServicePage)trackerServicePage) {\n    case TRACKER_SERVICE_ROOT_SETTINGS:\n        trackerServiceSettingsLevel = true;\n        trackerServicePage = TRACKER_SERVICE_SETTINGS_MOTION;\n        break;\n    case TRACKER_SERVICE_ROOT_BACK:\n        trackerServiceMenuClose();\n        return;\n    case TRACKER_SERVICE_SETTINGS_MOTION:\n        trackerCycleMotionSensitivity();\n        break;\n    case TRACKER_SERVICE_SETTINGS_DISTANCE:\n        trackerCycleSmartDistance();\n        break;\n    case TRACKER_SERVICE_SETTINGS_INTERVAL:\n        trackerCycleSmartInterval();\n        break;\n    case TRACKER_SERVICE_SETTINGS_PARK:\n        trackerCycleParkInterval();\n        break;\n    case TRACKER_SERVICE_SETTINGS_BACK:\n        trackerServiceSettingsLevel = false;\n        trackerServicePage = TRACKER_SERVICE_ROOT_SETTINGS;\n        break;\n    default:\n        // STATUS/DIAG/VERSION are read-only pages; long press deliberately\n        // has no side effect, matching the original service-menu concept.\n        return;\n    }\n    if (screen)\n        screen->runNow();\n'''
replace_once(old_long, new_long, "original-style Tracker long-press select/change/back behavior")

for needle in [
    'TRACKER_SERVICE_ROOT_BACK',
    'TRACKER_SERVICE_SETTINGS_BACK',
    'LONG: BACK -> PUNKT 0',
    'trackerServiceSettingsLevel = true;',
    'trackerServicePage = TRACKER_SERVICE_ROOT_SETTINGS;',
    'trackerServiceModule.requestServiceFocus();',
]:
    if needle not in text:
        raise SystemExit(f"Tracker original BACK-menu verification failed: {needle}")

if 'TRACKER_SERVICE_EXIT' in text or 'HOLD: EXIT' in text or 'SERVICE MENU EXIT' in text:
    raise SystemExit("Tracker original BACK-menu verification failed: legacy EXIT page remains")

PATH.write_text(text)
