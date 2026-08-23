from pathlib import Path

STATUS = Path("src/vehicle/TrackerStatusModule.cpp")
status = STATUS.read_text()


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if new in text:
        print(f"{label}: already applied")
        return text
    if old not in text:
        raise SystemExit(f"{label}: anchor not found")
    print(f"{label}: applied")
    return text.replace(old, new, 1)


# Selecting Export via USB only opens a confirmation picker. The actual export
# starts on a deliberate second long press. This patch intentionally leaves the
# established display policy untouched: 20 seconds after the last accepted
# button action the display may turn off, even inside a menu; the current menu
# state is preserved and restored when the display is woken again.
status = replace_once(
    status,
    '''    LOG_STATUS,\n    LOG_EXPORT,\n''',
    '''    LOG_STATUS,\n    LOG_EXPORT_CONFIRM,\n    LOG_EXPORT,\n''',
    "Tracker export confirmation menu state",
)

# Power Statistics persists immediately before a real export. Move both the
# persistence and export request behind the confirmation gesture.
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

for needle in [
    "LOG_EXPORT_CONFIRM",
    '"HOLD: EXPORT NOW"',
    '"Export Diagnostic Log?"',
    "queueTrackerMenu(TrackerMenu::LOG_EXPORT_CONFIRM, 0)",
    "trackerPowerMonitorPersist();\n                trackerDiagRequestUsbExport();",
]:
    if needle not in status:
        raise SystemExit(f"Tracker service/export verification failed: {needle}")

STATUS.write_text(status)
print("Tracker export confirmation ready; existing 20s-after-last-button display timeout preserved")
