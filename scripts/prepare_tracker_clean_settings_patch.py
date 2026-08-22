from pathlib import Path

PATH = Path("scripts/apply_tracker_clean_settings_menu_fix.py")
text = PATH.read_text()

# This helper runs after the original UI/export patches. Keep it deliberately
# simple: patch only a few unique source fragments in the clean-settings script
# so it matches the already-generated Tracker UI shape.

# 1) LOG_EXPORT already exists when the clean hierarchy runs. Preserve it in
# both the old enum anchor and the replacement enum.
old_enum_piece = "    LOG_STATUS,\\n    LOG_CLEAR,\\n"
new_enum_piece = "    LOG_STATUS,\\n    LOG_EXPORT,\\n    LOG_CLEAR,\\n"
count = text.count(old_enum_piece)
if count:
    text = text.replace(old_enum_piece, new_enum_piece)
    print(f"Prepared clean settings enum for LOG_EXPORT x{count}")

# 2) Replace the brittle exact two-line BLE timeout patch operation in the
# clean-settings script with a runtime regex matcher. Find the operation by its
# unique label, not by nested triple-quoted source text.
label = "    'dynamic BLE idle/hard timeout enforcement',\n)\n"
label_pos = text.find(label)
if label_pos >= 0:
    start = text.rfind("common = replace_once(\n", 0, label_pos)
    if start < 0:
        raise SystemExit("prepare clean settings: BLE timeout operation start not found")
    end = label_pos + len(label)
    replacement = '''new_timeout_block = (\n    "            const bool hardCap = (uint32_t)(now - serviceStartedMs) >= (uint32_t)trackerBleHardTimeoutSecs() * 1000UL;\\n"\n    "            const bool idle = (uint32_t)(now - serviceLastActivityMs) >= (uint32_t)trackerBleIdleTimeoutSecs() * 1000UL;\\n"\n)\nif new_timeout_block in common:\n    print("dynamic BLE idle/hard timeout enforcement: already applied")\nelse:\n    import re\n    pattern = re.compile(\n        r"^\\s{12}const bool hardCap = .*?;\\n\\s{12}const bool idle = .*?;\\n",\n        re.MULTILINE,\n    )\n    match = pattern.search(common)\n    if not match:\n        raise SystemExit("dynamic BLE idle/hard timeout enforcement: runtime declarations not found")\n    common = common[:match.start()] + new_timeout_block + common[match.end():]\n    print("dynamic BLE idle/hard timeout enforcement: applied")\n\n'''
    text = text[:start] + replacement + text[end:]
    print("Prepared clean settings BLE timeout matcher")
elif 'new_timeout_block = (' in text:
    print("Prepared clean settings BLE timeout matcher: already applied")
else:
    raise SystemExit("prepare clean settings: BLE timeout patch label not found")

# 3) Keep the working live Log Download page instead of returning silently to
# the Diagnostic Log list.
old_export_action = 'else if (selected == 3) { trackerDiagRequestUsbExport(); queueTrackerMenu(TrackerMenu::DIAG_LOG, 0); }'
new_export_action = 'else if (selected == 3) { trackerDiagRequestUsbExport(); queueTrackerMenu(TrackerMenu::LOG_EXPORT, 0); }'
if old_export_action in text:
    text = text.replace(old_export_action, new_export_action, 1)
    print("Prepared clean settings USB export action")

# 4) Insert the live export page directly before LOG_CLEAR in the new menu.
# There is only one C++ LOG_CLEAR case in this patch script.
if 'case TrackerMenu::LOG_EXPORT:' not in text:
    anchor = '    case TrackerMenu::LOG_CLEAR: {\n'
    pos = text.find(anchor)
    if pos < 0:
        raise SystemExit("prepare clean settings: LOG_CLEAR insertion anchor not found")
    export_case = r'''    case TrackerMenu::LOG_EXPORT: {
        static const char *opts[] = {"Back", trackerLogExportStatus, trackerLogExportProgress};
        refreshTrackerLogExportText();
        showTrackerOptions("Log Download", opts, 3, 0, [](int selected) {
            if (selected == 0)
                queueTrackerMenu(TrackerMenu::DIAG_LOG, trackerDiagSelection);
            else
                queueTrackerMenu(TrackerMenu::LOG_EXPORT, 0);
        });
        break;
    }

'''
    text = text[:pos] + export_case + text[pos:]
    print("Prepared clean settings live LOG_EXPORT page")
else:
    print("Prepared clean settings live LOG_EXPORT page: already present")

for needle in [
    "LOG_EXPORT,\\n    LOG_CLEAR,",
    "queueTrackerMenu(TrackerMenu::LOG_EXPORT, 0)",
    "case TrackerMenu::LOG_EXPORT:",
    "new_timeout_block = (",
]:
    if needle not in text:
        raise SystemExit(f"prepare clean settings verification failed: {needle}")

PATH.write_text(text)
