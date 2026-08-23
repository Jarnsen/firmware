from pathlib import Path

STATUS = Path("src/vehicle/TrackerStatusModule.cpp")
COMMON = Path("src/vehicle/TrackerCommonPolicy.cpp")

status = STATUS.read_text()
common = COMMON.read_text()


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if new in text:
        print(f"{label}: already applied")
        return text
    if old not in text:
        raise SystemExit(f"{label}: anchor not found")
    print(f"{label}: applied")
    return text.replace(old, new, 1)


# Selecting Export via USB must not immediately start the transfer. Add a
# dedicated second picker; moving to HOLD: EXPORT NOW and long-selecting it is
# the deliberate confirmation gesture.
status = replace_once(
    status,
    '''    LOG_STATUS,\n    LOG_EXPORT,\n''',
    '''    LOG_STATUS,\n    LOG_EXPORT_CONFIRM,\n    LOG_EXPORT,\n''',
    "Tracker export confirmation menu state",
)

status = replace_once(
    status,
    '''            else if (selected == 3) { trackerDiagRequestUsbExport(); queueTrackerMenu(TrackerMenu::LOG_EXPORT, 0); }\n''',
    '''            else if (selected == 3) { queueTrackerMenu(TrackerMenu::LOG_EXPORT_CONFIRM, 0); }\n''',
    "Tracker Export via USB opens confirmation instead of starting transfer",
)

confirm_case = '''    case TrackerMenu::LOG_EXPORT_CONFIRM: {\n        static const char *opts[] = {"Back", "HOLD: EXPORT NOW"};\n        showTrackerOptions("Export Diagnostic Log?", opts, 2, 0, [](int selected) {\n            if (selected == 0)\n                queueTrackerMenu(TrackerMenu::DIAG_LOG, 0);\n            else if (selected == 1) {\n                trackerDiagRequestUsbExport();\n                queueTrackerMenu(TrackerMenu::LOG_EXPORT, 0);\n            }\n        });\n        break;\n    }\n'''
status = replace_once(
    status,
    '''    case TrackerMenu::LOG_EXPORT: {\n''',
    confirm_case + '''    case TrackerMenu::LOG_EXPORT: {\n''',
    "Tracker explicit long-hold USB export confirmation page",
)

# The generic 20 s display timer is useful on normal pages, but powering the
# screen off underneath an active Service picker feels like a crash and can hide
# the export progress page. While any Tracker Service menu is active, hold the
# screen on. The existing 120 s service-idle timer and 15 min hard cap remain.
old_timeout = '''            const uint32_t serviceNow = millis();\n            const bool hardCap = (uint32_t)(serviceNow - serviceStartedMs) >= TRACKER_COMMON_SERVICE_MAX_MS;\n            const bool idle = (uint32_t)(serviceNow - serviceLastActivityMs) >= TRACKER_COMMON_SERVICE_IDLE_MS;\n            if (hardCap || idle) {\n                stopService();\n            } else if (displayVisible && displayStartedMs != 0 &&\n                       (uint32_t)(serviceNow - displayStartedMs) >= displayWindowMs) {\n                closeDisplay();\n                LOG_DEBUG("Tracker service: display window closed; Bluetooth service continues");\n            }\n'''
new_timeout = '''            const uint32_t serviceNow = millis();\n            const bool serviceUiActive = trackerServiceMenuActive();\n            if (serviceUiActive) {\n                displayVisible = true;\n                displayStartedMs = serviceNow ? serviceNow : 1;\n                if (bootHandoffComplete && screen && !screen->isScreenOn()) {\n                    screen->setOn(true);\n                    screen->runNow();\n                    LOG_WARN("Tracker service: restored screen while service menu active");\n                }\n            }\n            const bool hardCap = (uint32_t)(serviceNow - serviceStartedMs) >= TRACKER_COMMON_SERVICE_MAX_MS;\n            const bool idle = (uint32_t)(serviceNow - serviceLastActivityMs) >= TRACKER_COMMON_SERVICE_IDLE_MS;\n            if (hardCap || idle) {\n                stopService();\n            } else if (!serviceUiActive && displayVisible && displayStartedMs != 0 &&\n                       (uint32_t)(serviceNow - displayStartedMs) >= displayWindowMs) {\n                closeDisplay();\n                LOG_DEBUG("Tracker service: display window closed; Bluetooth service continues");\n            }\n'''
common = replace_once(common, old_timeout, new_timeout, "Tracker keep display alive while Service menu is active")

for text, needle in [
    (status, "LOG_EXPORT_CONFIRM"),
    (status, '"HOLD: EXPORT NOW"'),
    (status, '"Export Diagnostic Log?"'),
    (status, "queueTrackerMenu(TrackerMenu::LOG_EXPORT_CONFIRM, 0)"),
    (common, "const bool serviceUiActive = trackerServiceMenuActive();"),
    (common, "restored screen while service menu active"),
]:
    if needle not in text:
        raise SystemExit(f"Tracker service/export verification failed: {needle}")

STATUS.write_text(status)
COMMON.write_text(common)
print("Tracker service UI ready: menu display held on + second long-hold confirmation before USB export")
