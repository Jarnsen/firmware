from pathlib import Path

PATH = Path("src/vehicle/TrackerStatusModule.cpp")
text = PATH.read_text()


def replace_all(old: str, new: str, label: str):
    global text
    count = text.count(old)
    if count == 0:
        if new in text:
            print(f"{label}: already applied")
            return
        raise SystemExit(f"{label}: anchor not found")
    text = text.replace(old, new)
    print(f"{label}: applied x{count}")


# One-button rule requested by the user: once an item has been selected, the
# destination/reopened menu always starts on Back. The current value remains
# visible through [x], so cursor position no longer doubles as value state.
replacements = [
    ('queueTrackerMenu(TrackerMenu::POSITION, trackerPositionSelection);', 'queueTrackerMenu(TrackerMenu::POSITION, 0);'),
    ('queueTrackerMenu(TrackerMenu::MOTION, trackerMotionSelection);', 'queueTrackerMenu(TrackerMenu::MOTION, 0);'),
    ('queueTrackerMenu(TrackerMenu::PARK_POWER, trackerParkSelection);', 'queueTrackerMenu(TrackerMenu::PARK_POWER, 0);'),
    ('queueTrackerMenu(TrackerMenu::BLUETOOTH, trackerBluetoothSelection);', 'queueTrackerMenu(TrackerMenu::BLUETOOTH, 0);'),
    ('queueTrackerMenu(TrackerMenu::DIAG_LOG, trackerDiagSelection);', 'queueTrackerMenu(TrackerMenu::DIAG_LOG, 0);'),
    ('queueTrackerMenu(TrackerMenu::DISTANCE, distanceSelection());', 'queueTrackerMenu(TrackerMenu::DISTANCE, 0);'),
    ('queueTrackerMenu(TrackerMenu::INTERVAL, intervalSelection());', 'queueTrackerMenu(TrackerMenu::INTERVAL, 0);'),
    ('queueTrackerMenu(TrackerMenu::MOTION_SENS, trackerMotionSensitivityIndex() + 1);', 'queueTrackerMenu(TrackerMenu::MOTION_SENS, 0);'),
    ('queueTrackerMenu(TrackerMenu::PARK_INTERVAL, parkIntervalSelection());', 'queueTrackerMenu(TrackerMenu::PARK_INTERVAL, 0);'),
    ('queueTrackerMenu(TrackerMenu::LOGGING, trackerDiagEnabled() ? 2 : 1);', 'queueTrackerMenu(TrackerMenu::LOGGING, 0);'),
]

for idx, (old, new) in enumerate(replacements, 1):
    replace_all(old, new, f"Back cursor rule {idx}")

# Read-only rows also return the cursor to Back after long-select.
replace_all('queueTrackerMenu(TrackerMenu::POSITION, selected);', 'queueTrackerMenu(TrackerMenu::POSITION, 0);',
            'Position read-only row returns to Back')
replace_all('queueTrackerMenu(TrackerMenu::MOTION, selected);', 'queueTrackerMenu(TrackerMenu::MOTION, 0);',
            'Motion read-only row returns to Back')
replace_all('queueTrackerMenu(TrackerMenu::PARK_POWER, selected);', 'queueTrackerMenu(TrackerMenu::PARK_POWER, 0);',
            'Park read-only row returns to Back')
replace_all('queueTrackerMenu(TrackerMenu::BLUETOOTH, selected);', 'queueTrackerMenu(TrackerMenu::BLUETOOTH, 0);',
            'Bluetooth read-only row returns to Back')
replace_all('queueTrackerMenu(TrackerMenu::LOG_STATUS, selected);', 'queueTrackerMenu(TrackerMenu::LOG_STATUS, 0);',
            'Log status row returns to Back')
replace_all('queueTrackerMenu(TrackerMenu::SYSTEM_INFO, selected);', 'queueTrackerMenu(TrackerMenu::SYSTEM_INFO, 0);',
            'System info row returns to Back')

for needle in [
    'queueTrackerMenu(TrackerMenu::POSITION, 0);',
    'queueTrackerMenu(TrackerMenu::MOTION, 0);',
    'queueTrackerMenu(TrackerMenu::PARK_POWER, 0);',
    'queueTrackerMenu(TrackerMenu::DIAG_LOG, 0);',
    'queueTrackerMenu(TrackerMenu::PARK_INTERVAL, 0);',
    'queueTrackerMenu(TrackerMenu::LOGGING, 0);',
]:
    if needle not in text:
        raise SystemExit(f"Tracker Back cursor verification failed: {needle}")

PATH.write_text(text)
