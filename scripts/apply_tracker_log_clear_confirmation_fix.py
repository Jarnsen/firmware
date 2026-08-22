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


# Give the successful clear action its own small acknowledgement page. The
# diagnostic logger is cleared in-place; unlike USB export this must not reboot.
status = replace_once(
    status,
    '''    LOG_CLEAR,\n    SYSTEM,\n''',
    '''    LOG_CLEAR,\n    LOG_CLEARED,\n    SYSTEM,\n''',
    'Tracker log-cleared menu state',
)

status = replace_once(
    status,
    '''    case TrackerMenu::LOG_CLEAR: {\n        static const char *opts[] = {"Back", "CLEAR LOG NOW"};\n        showTrackerOptions("Clear Diagnostic Log?", opts, 2, initialSelection, [](int selected) {\n            if (selected == 0) queueTrackerMenu(TrackerMenu::DIAG_LOG, trackerDiagSelection);\n            else { trackerDiagClear(); queueTrackerMenu(TrackerMenu::LOG_CLEAR, 0); }\n        });\n        break;\n    }\n\n    case TrackerMenu::SYSTEM: {\n''',
    '''    case TrackerMenu::LOG_CLEAR: {\n        static const char *opts[] = {"Back", "CLEAR LOG NOW"};\n        showTrackerOptions("Clear Diagnostic Log?", opts, 2, initialSelection, [](int selected) {\n            if (selected == 0) {\n                queueTrackerMenu(TrackerMenu::DIAG_LOG, trackerDiagSelection);\n            } else {\n                trackerDiagClear();\n                queueTrackerMenu(TrackerMenu::LOG_CLEARED, 0);\n            }\n        });\n        break;\n    }\n\n    case TrackerMenu::LOG_CLEARED: {\n        static const char *opts[] = {"Back"};\n        showTrackerOptions("LOG CLEARED", opts, 1, 0, [](int) {\n            queueTrackerMenu(TrackerMenu::DIAG_LOG, trackerDiagSelection);\n        });\n        break;\n    }\n\n    case TrackerMenu::SYSTEM: {\n''',
    'Tracker clear-log acknowledgement page',
)

STATUS.write_text(status)
print('Tracker log clear confirmation patch complete')
