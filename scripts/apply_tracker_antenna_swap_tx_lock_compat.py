from pathlib import Path
import runpy

STATUS = Path("src/vehicle/TrackerStatusModule.cpp")
status = STATUS.read_text()

# The antenna safety patch was intentionally written against the earlier
# Service-body signature. A later stock-frame patch moved the same row to
# textPos[4] and compacted its spacing. Normalize only that one row, run the
# safety patch unchanged, then restore the stock layout. This keeps the large
# safety patch stable while preserving the current visual design.
stock_row = '''        display->setTextAlignment(TEXT_ALIGN_LEFT);\n        snprintf(line, sizeof(line), "%sBT:%s  Log:%s", next,\n                 config.bluetooth.enabled ? "ON" : "OFF", trackerDiagEnabled() ? "ON" : "OFF");\n        display->drawString(left, textPos[4], line);\n'''
legacy_anchor = '''        snprintf(line, sizeof(line), "%s   BT:%s   Log:%s", next,\n                 config.bluetooth.enabled ? "ON" : "OFF", trackerDiagEnabled() ? "ON" : "OFF");\n        display->drawString(left, 64 + y, line);\n'''

if stock_row in status:
    status = status.replace(stock_row, legacy_anchor, 1)
    STATUS.write_text(status)
    print("Tracker antenna compat: normalized stock Service status row")
elif legacy_anchor in status:
    print("Tracker antenna compat: legacy anchor already present")
elif "TX:LOCK" in status:
    print("Tracker antenna compat: TX lock row already generated")
else:
    raise SystemExit("Tracker antenna compat: stock Service status row not found")

runpy.run_path("scripts/apply_tracker_antenna_swap_tx_lock_fix.py", run_name="__main__")

status = STATUS.read_text()
legacy_locked = '''        if (trackerAntennaTxLocked())\n            snprintf(line, sizeof(line), "%s   TX:LOCK   Log:%s", next, trackerDiagEnabled() ? "ON" : "OFF");\n        else\n            snprintf(line, sizeof(line), "%s   BT:%s   Log:%s", next,\n                     config.bluetooth.enabled ? "ON" : "OFF", trackerDiagEnabled() ? "ON" : "OFF");\n        display->drawString(left, 64 + y, line);\n'''
stock_locked = '''        display->setTextAlignment(TEXT_ALIGN_LEFT);\n        if (trackerAntennaTxLocked())\n            snprintf(line, sizeof(line), "%sTX:LOCK  Log:%s", next, trackerDiagEnabled() ? "ON" : "OFF");\n        else\n            snprintf(line, sizeof(line), "%sBT:%s  Log:%s", next,\n                     config.bluetooth.enabled ? "ON" : "OFF", trackerDiagEnabled() ? "ON" : "OFF");\n        display->drawString(left, textPos[4], line);\n'''

if legacy_locked in status:
    status = status.replace(legacy_locked, stock_locked, 1)
    STATUS.write_text(status)
    print("Tracker antenna compat: restored stock textPos[4] TX-lock row")
elif stock_locked in status:
    print("Tracker antenna compat: stock TX-lock row already restored")
else:
    raise SystemExit("Tracker antenna compat: generated TX-lock row not found")

for needle in [
    'trackerAntennaTxLocked()',
    '"%sTX:LOCK  Log:%s"',
    'display->drawString(left, textPos[4], line);',
    'case TrackerMenu::ANTENNA_TEST:',
    'ACTION: PREP SWAP / LOCK TX',
]:
    if needle not in status:
        raise SystemExit(f"Tracker antenna compat verification failed: {needle}")

print("Tracker antenna compatibility bridge complete")
