from pathlib import Path

STATUS = Path("src/vehicle/TrackerStatusModule.cpp")
text = STATUS.read_text()


def replace_once(old: str, new: str, label: str):
    global text
    if new in text:
        print(f"{label}: already applied")
        return
    if old not in text:
        raise SystemExit(f"{label}: anchor not found")
    text = text.replace(old, new, 1)
    print(f"{label}: applied")


# ---------------------------------------------------------------------------
# Service landing page: use the original Meshtastic device-focused renderer as
# the visual base. This preserves the same top status row, font sizes, spacing,
# node/GPS/channel presentation and general look as the stock page. Only the
# bottom line is replaced with the Service entry hint.
# ---------------------------------------------------------------------------
replace_once(
    '#include "graphics/ScreenFonts.h"\n#include "graphics/draw/NotificationRenderer.h"\n',
    '#include "graphics/ScreenFonts.h"\n#include "graphics/draw/NotificationRenderer.h"\n#include "graphics/draw/UIRenderer.h"\n',
    "Tracker Service stock UIRenderer include",
)

old_landing = '''        const int center = display->getWidth() / 2 + x;\n        display->setTextAlignment(TEXT_ALIGN_CENTER);\n        display->setFont(FONT_SMALL);\n\n        const char *role = config.device.role == meshtastic_Config_DeviceConfig_Role_TAK_TRACKER ? "TAK_TRACKER" : "TAK";\n        char line[72] = {};\n        snprintf(line, sizeof(line), "Mode: %s   Log:%s", role, trackerDiagEnabled() ? "ON" : "OFF");\n        display->drawString(center, 11 + y, line);\n        snprintf(line, sizeof(line), "Motion: %s", trackerMotionSensitivityName());\n        display->drawString(center, 24 + y, line);\n        snprintf(line, sizeof(line), "Smart: %um / %us", (unsigned)trackerSmartDistanceM(),\n                 (unsigned)trackerSmartIntervalSecs());\n        display->drawString(center, 37 + y, line);\n        char park[20] = {};\n        trackerFormatParkInterval(park, sizeof(park));\n        snprintf(line, sizeof(line), "Park: %s   GPS:%s", park,\n                 trackerLastFixAgeSecs() == UINT32_MAX ? "WAIT" : "FIX");\n        display->drawString(center, 50 + y, line);\n        display->drawString(center, 64 + y, "HOLD: SETTINGS");\n'''
new_landing = '''        // Reuse the exact stock home renderer so the Service page visually\n        // matches the original Meshtastic page (status bar, spacing and font).\n        graphics::UIRenderer::drawDeviceFocused(display, state, x, y);\n\n        // Replace only the lowest content line with the Service affordance.\n        // The rest of the stock page is left untouched.\n        const int center = display->getWidth() / 2 + x;\n        const int16_t footerTop = (int16_t)display->getHeight() - 13 + y;\n        display->setColor(BLACK);\n        display->fillRect(x, footerTop, display->getWidth(), 13);\n        display->setColor(WHITE);\n        display->setTextAlignment(TEXT_ALIGN_CENTER);\n        display->setFont(FONT_SMALL);\n        display->drawString(center, footerTop + 1, "SERVICE  HOLD: SETTINGS");\n'''
replace_once(old_landing, new_landing, "Tracker Service landing page matches stock Meshtastic UI")

# Dedicated export feedback page.
replace_once(
    '''    LOG_STATUS,\n    LOG_CLEAR,\n''',
    '''    LOG_STATUS,\n    LOG_EXPORT,\n    LOG_CLEAR,\n''',
    "Tracker log export menu state",
)

replace_once(
    '''volatile uint8_t trackerServiceFrameIndex = 255;\n\n''',
    '''volatile uint8_t trackerServiceFrameIndex = 255;\nchar trackerLogExportStatus[48] = "Status: Bereit";\nchar trackerLogExportProgress[40] = "Log: 0 KB";\nuint32_t trackerLogExportLastRefreshMs = 0;\n\n''',
    "Tracker log export live status buffers",
)

replace_once(
    '''void markOption(char *out, size_t outSize, bool selected, const char *label)\n{\n    snprintf(out, outSize, "[%c] %s", selected ? 'x' : ' ', label);\n}\n\n''',
    '''void markOption(char *out, size_t outSize, bool selected, const char *label)\n{\n    snprintf(out, outSize, "[%c] %s", selected ? 'x' : ' ', label);\n}\n\nvoid refreshTrackerLogExportText()\n{\n    snprintf(trackerLogExportStatus, sizeof(trackerLogExportStatus), "Status: %s", trackerDiagUsbExportStatusText());\n    const uint8_t progress = trackerDiagUsbExportProgress();\n    if (trackerDiagUsbExportPending() || progress > 0)\n        snprintf(trackerLogExportProgress, sizeof(trackerLogExportProgress), "Fortschritt: %u%%", (unsigned)progress);\n    else\n        snprintf(trackerLogExportProgress, sizeof(trackerLogExportProgress), "Log: %u KB",\n                 (unsigned)((trackerDiagLogSize() + 1023U) / 1024U));\n}\n\n''',
    "Tracker log export live text helper",
)

# After changing a value, reopen the same picker with BACK highlighted. This is
# faster with one physical button: long selects the value, then the next long
# immediately returns one level instead of requiring a full cycle first.
for old, new, label in [
    ('trackerSetSmartDistanceM(vals[selected - 1]); queueTrackerMenu(TrackerMenu::DISTANCE, selected);',
     'trackerSetSmartDistanceM(vals[selected - 1]); queueTrackerMenu(TrackerMenu::DISTANCE, 0);',
     'Smart Distance returns cursor to Back'),
    ('trackerSetSmartIntervalSecs(vals[selected - 1]); queueTrackerMenu(TrackerMenu::INTERVAL, selected);',
     'trackerSetSmartIntervalSecs(vals[selected - 1]); queueTrackerMenu(TrackerMenu::INTERVAL, 0);',
     'Smart Interval returns cursor to Back'),
    ('trackerSetMotionSensitivityIndex((uint8_t)(selected - 1)); queueTrackerMenu(TrackerMenu::MOTION_SENS, selected);',
     'trackerSetMotionSensitivityIndex((uint8_t)(selected - 1)); queueTrackerMenu(TrackerMenu::MOTION_SENS, 0);',
     'Motion sensitivity returns cursor to Back'),
    ('trackerSetParkIntervalMinutes(vals[selected - 1]); queueTrackerMenu(TrackerMenu::PARK_INTERVAL, selected);',
     'trackerSetParkIntervalMinutes(vals[selected - 1]); queueTrackerMenu(TrackerMenu::PARK_INTERVAL, 0);',
     'Park interval returns cursor to Back'),
    ('trackerDiagSetEnabled(selected == 2); queueTrackerMenu(TrackerMenu::LOGGING, selected);',
     'trackerDiagSetEnabled(selected == 2); queueTrackerMenu(TrackerMenu::LOGGING, 0);',
     'Logging selection returns cursor to Back'),
    ('trackerDiagClear(); queueTrackerMenu(TrackerMenu::LOG_CLEAR, selected);',
     'trackerDiagClear(); queueTrackerMenu(TrackerMenu::LOG_CLEAR, 0);',
     'Clear-log confirmation returns cursor to Back'),
]:
    replace_once(old, new, label)

# Export now moves to a dedicated live status screen instead of silently
# returning to the Diagnostic Log list.
replace_once(
    '''            else if (selected == 3) { trackerDiagRequestUsbExport(); queueTrackerMenu(TrackerMenu::DIAG_LOG, selected); }\n''',
    '''            else if (selected == 3) { trackerDiagRequestUsbExport(); queueTrackerMenu(TrackerMenu::LOG_EXPORT, 0); }\n''',
    "open Tracker USB export status page",
)

export_case = '''    case TrackerMenu::LOG_EXPORT: {\n        static const char *opts[] = {"Back", trackerLogExportStatus, trackerLogExportProgress};\n        refreshTrackerLogExportText();\n        showTrackerOptions("Log Download", opts, 3, 0, [](int selected) {\n            if (selected == 0)\n                queueTrackerMenu(TrackerMenu::DIAG_LOG, 0);\n            else\n                queueTrackerMenu(TrackerMenu::LOG_EXPORT, 0);\n        });\n        break;\n    }\n'''
replace_once(
    '''    case TrackerMenu::LOG_CLEAR: {\n''',
    export_case + '''    case TrackerMenu::LOG_CLEAR: {\n''',
    "Tracker USB export live status page",
)

# While the export page is visible, refresh the two status strings four times a
# second. The original selection picker stays active and Back remains selected.
replace_once(
    '''void trackerServiceMenuPump()\n{\n    if (!trackerServiceMenuMode || trackerMenuPending == TrackerMenu::NONE)\n        return;\n    const TrackerMenu menu = trackerMenuPending;\n    const int selection = trackerMenuPendingSelection;\n    showTrackerMenu(menu, selection);\n}\n''',
    '''void trackerServiceMenuPump()\n{\n    if (!trackerServiceMenuMode)\n        return;\n\n    if (trackerMenuCurrent == TrackerMenu::LOG_EXPORT) {\n        const uint32_t now = millis();\n        if (trackerLogExportLastRefreshMs == 0 || (uint32_t)(now - trackerLogExportLastRefreshMs) >= 250U) {\n            trackerLogExportLastRefreshMs = now ? now : 1;\n            refreshTrackerLogExportText();\n            if (screen)\n                screen->runNow();\n        }\n    }\n\n    if (trackerMenuPending == TrackerMenu::NONE)\n        return;\n    const TrackerMenu menu = trackerMenuPending;\n    const int selection = trackerMenuPendingSelection;\n    showTrackerMenu(menu, selection);\n}\n''',
    "refresh Tracker USB export status while transferring",
)

for needle in [
    'graphics::UIRenderer::drawDeviceFocused(display, state, x, y);',
    'SERVICE  HOLD: SETTINGS',
    'LOG_EXPORT',
    'Status: %s',
    'Fortschritt: %u%%',
    'queueTrackerMenu(TrackerMenu::PARK_INTERVAL, 0)',
    'queueTrackerMenu(TrackerMenu::MOTION_SENS, 0)',
    'showTrackerOptions("Log Download"',
    'trackerLogExportLastRefreshMs',
]:
    if needle not in text:
        raise SystemExit(f"Tracker visual/export verification failed: {needle}")

STATUS.write_text(text)
