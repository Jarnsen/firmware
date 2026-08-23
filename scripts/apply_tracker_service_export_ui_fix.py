from pathlib import Path
import re

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

# The Power Statistics patch deliberately persists its counters immediately
# before an export. Move BOTH persistence and the export request to the second
# confirmation page so merely opening Export via USB has no side effect.
export_old_variants = [
    '''            else if (selected == 3) { trackerPowerMonitorPersist(); trackerDiagRequestUsbExport(); queueTrackerMenu(TrackerMenu::LOG_EXPORT, 0); }\n''',
    '''            else if (selected == 3) { trackerDiagRequestUsbExport(); queueTrackerMenu(TrackerMenu::LOG_EXPORT, 0); }\n''',
]
export_new = '''            else if (selected == 3) { queueTrackerMenu(TrackerMenu::LOG_EXPORT_CONFIRM, 0); }\n'''
if export_new in status:
    print("Tracker Export via USB opens confirmation instead of starting transfer: already applied")
else:
    for old in export_old_variants:
        if old in status:
            status = status.replace(old, export_new, 1)
            print("Tracker Export via USB opens confirmation instead of starting transfer: applied")
            break
    else:
        raise SystemExit("Tracker Export via USB opens confirmation instead of starting transfer: final export action not found")

confirm_case = '''    case TrackerMenu::LOG_EXPORT_CONFIRM: {\n        static const char *opts[] = {"Back", "HOLD: EXPORT NOW"};\n        showTrackerOptions("Export Diagnostic Log?", opts, 2, 0, [](int selected) {\n            if (selected == 0)\n                queueTrackerMenu(TrackerMenu::DIAG_LOG, trackerDiagSelection);\n            else if (selected == 1) {\n                trackerPowerMonitorPersist();\n                trackerDiagRequestUsbExport();\n                queueTrackerMenu(TrackerMenu::LOG_EXPORT, 0);\n            }\n        });\n        break;\n    }\n'''
status = replace_once(
    status,
    '''    case TrackerMenu::LOG_EXPORT: {\n''',
    confirm_case + '''    case TrackerMenu::LOG_EXPORT: {\n''',
    "Tracker explicit long-hold USB export confirmation page",
)

# The generic 20 s display timer is useful on normal pages, but powering the
# screen off underneath an active Service picker feels like a crash and can hide
# the export progress page. The final clean-settings patch can rewrite the BLE
# idle/hard-cap expressions, so match the stable surrounding timeout structure
# rather than one historical spelling of those two expressions.
if "const bool serviceUiActive = trackerServiceMenuActive();" in common:
    print("Tracker keep display alive while Service menu is active: already applied")
else:
    timeout_pattern = re.compile(
        r'''            const uint32_t serviceNow = millis\(\);\n'''
        r'''            const bool hardCap = [^\n]+;\n'''
        r'''            const bool idle = [^\n]+;\n'''
        r'''            if \(hardCap \|\| idle\) \{\n'''
        r'''                stopService\(\);\n'''
        r'''            \} else if \(displayVisible && displayStartedMs != 0 &&\n'''
        r'''                       \(uint32_t\)\(serviceNow - displayStartedMs\) >= displayWindowMs\) \{\n'''
        r'''                closeDisplay\(\);\n'''
        r'''                LOG_DEBUG\("Tracker service: display window closed; Bluetooth service continues"\);\n'''
        r'''            \}\n'''
    )
    match = timeout_pattern.search(common)
    if not match:
        raise SystemExit("Tracker keep display alive while Service menu is active: final timeout block not found")
    new_timeout = '''            const uint32_t serviceNow = millis();\n            const bool serviceUiActive = trackerServiceMenuActive();\n            if (serviceUiActive) {\n                // Do not let the generic page timer blank an active selection\n                // picker. If another Screen path switched it off, repair it.\n                displayVisible = true;\n                displayStartedMs = serviceNow ? serviceNow : 1;\n                if (bootHandoffComplete && screen && !screen->isScreenOn()) {\n                    screen->setOn(true);\n                    screen->runNow();\n                    LOG_WARN("Tracker service: restored screen while service menu active");\n                }\n            }\n            const bool hardCap = (uint32_t)(serviceNow - serviceStartedMs) >=\n                                 (uint32_t)trackerBleHardTimeoutSecs() * 1000UL;\n            const bool idle = (uint32_t)(serviceNow - serviceLastActivityMs) >=\n                              (uint32_t)trackerBleIdleTimeoutSecs() * 1000UL;\n            if (hardCap || idle) {\n                stopService();\n            } else if (!serviceUiActive && displayVisible && displayStartedMs != 0 &&\n                       (uint32_t)(serviceNow - displayStartedMs) >= displayWindowMs) {\n                closeDisplay();\n                LOG_DEBUG("Tracker service: display window closed; Bluetooth service continues");\n            }\n'''
    common = common[:match.start()] + new_timeout + common[match.end():]
    print("Tracker keep display alive while Service menu is active: applied")

for text, needle in [
    (status, "LOG_EXPORT_CONFIRM"),
    (status, '"HOLD: EXPORT NOW"'),
    (status, '"Export Diagnostic Log?"'),
    (status, "queueTrackerMenu(TrackerMenu::LOG_EXPORT_CONFIRM, 0)"),
    (status, "trackerPowerMonitorPersist();\n                trackerDiagRequestUsbExport();"),
    (common, "const bool serviceUiActive = trackerServiceMenuActive();"),
    (common, "restored screen while service menu active"),
    (common, "!serviceUiActive && displayVisible"),
]:
    if needle not in text:
        raise SystemExit(f"Tracker service/export verification failed: {needle}")

STATUS.write_text(status)
COMMON.write_text(common)
print("Tracker service UI ready: menu display held on + second long-hold confirmation before USB export")
