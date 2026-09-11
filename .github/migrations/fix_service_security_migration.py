#!/usr/bin/env python3
from pathlib import Path

path = Path('.github/migrations/apply_jarnsen_migration.py')
text = path.read_text(encoding='utf-8')
old = '''repl(tracker, ''' + "'''    trackerServiceMenuForceClose();\n    bluetoothOff();'''" + ''',\n     ''' + "'''    trackerServiceMenuForceClose();\n    jarnsenServiceWebStop();\n    bluetoothOff();'''" + ''')'''
new = '''repl(tracker, ''' + "'''    bleQueueHold.store(false);\n    serviceActive = false;\n    trackerServiceMenuForceClose();\n    bluetoothOff();\n    trackerDiagLog(\"BT_SERVICE\", \"closed/suspended\");'''" + ''',\n     ''' + "'''    bleQueueHold.store(false);\n    serviceActive = false;\n    trackerServiceMenuForceClose();\n    jarnsenServiceWebStop();\n    bluetoothOff();\n    trackerDiagLog(\"BT_SERVICE\", \"closed/suspended\");'''" + ''')'''
if text.count(old) != 1:
    raise SystemExit(f'expected exactly one stopService migration seam, found {text.count(old)}')
path.write_text(text.replace(old, new, 1), encoding='utf-8', newline='\n')
print('Hardened Tracker stopService migration seam')
