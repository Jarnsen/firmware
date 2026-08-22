from pathlib import Path

PATH = Path("scripts/apply_tracker_clean_settings_menu_fix.py")
text = PATH.read_text()

# The clean-settings pass runs after the original UI/diagnostic/export passes.
# Normalize the patch script itself so it targets that current generated shape
# instead of an older intermediate version.

# 1) LOG_EXPORT already exists before the clean hierarchy pass. Preserve it in
# both the old enum anchor and the replacement enum.
old_enum_piece = r'''    LOG_STATUS,\n    LOG_CLEAR,\n'''
new_enum_piece = r'''    LOG_STATUS,\n    LOG_EXPORT,\n    LOG_CLEAR,\n'''
count = text.count(old_enum_piece)
if count:
    text = text.replace(old_enum_piece, new_enum_piece, min(count, 2))
    print(f"Prepared clean settings enum for LOG_EXPORT x{min(count, 2)}")

# 2) The prior diagnostic pass can add statements around the service-window
# logic, so matching two exact adjacent source lines is unnecessarily brittle.
# Replace that one patch operation with a small regex that rewrites the two
# declarations wherever they currently sit in TrackerCommon::runOnce().
start_marker = '''common = replace_once(\n    common,\n    '''            const bool hardCap = (uint32_t)(now - serviceStartedMs) >= TRACKER_COMMON_SERVICE_MAX_MS;\\n            const bool idle = (uint32_t)(now - serviceLastActivityMs) >= TRACKER_COMMON_SERVICE_IDLE_MS;\\n''',\n'''
end_marker = '''    'dynamic BLE idle/hard timeout enforcement',\n)\n'''
start = text.find(start_marker)
if start >= 0:
    end = text.find(end_marker, start)
    if end < 0:
        raise SystemExit("prepare clean settings: BLE timeout patch end not found")
    end += len(end_marker)
    replacement = r'''new_timeout_block = '''            const bool hardCap = (uint32_t)(now - serviceStartedMs) >= (uint32_t)trackerBleHardTimeoutSecs() * 1000UL;\n            const bool idle = (uint32_t)(now - serviceLastActivityMs) >= (uint32_t)trackerBleIdleTimeoutSecs() * 1000UL;\n'''
if new_timeout_block in common:
    print("dynamic BLE idle/hard timeout enforcement: already applied")
else:
    import re
    pattern = re.compile(
        r'^\s{12}const bool hardCap = .*?;\n\s{12}const bool idle = .*?;\n',
        re.MULTILINE,
    )
    match = pattern.search(common)
    if not match:
        raise SystemExit("dynamic BLE idle/hard timeout enforcement: runtime declarations not found")
    common = common[:match.start()] + new_timeout_block + common[match.end():]
    print("dynamic BLE idle/hard timeout enforcement: applied")
'''
    text = text[:start] + replacement + text[end:]
    print("Prepared clean settings BLE timeout matcher")

# 3) Keep the working live Log Download page in the new clean hierarchy.
old_export_action = '''else if (selected == 3) { trackerDiagRequestUsbExport(); queueTrackerMenu(TrackerMenu::DIAG_LOG, 0); }'''
new_export_action = '''else if (selected == 3) { trackerDiagRequestUsbExport(); queueTrackerMenu(TrackerMenu::LOG_EXPORT, 0); }'''
if old_export_action in text:
    text = text.replace(old_export_action, new_export_action, 1)
    print("Prepared clean settings USB export action")

export_case = r'''
    case TrackerMenu::LOG_EXPORT: {
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
insert_anchor = '''    case TrackerMenu::LOG_CLEAR: {\n'''
# Insert inside the raw new_menu string only if the clean script doesn't already
# carry a LOG_EXPORT case there.
new_menu_start = text.find("new_menu = r'''void showTrackerMenu")
if new_menu_start < 0:
    raise SystemExit("prepare clean settings: new_menu start not found")
new_menu_end = text.find("'''\nstatus = replace_span", new_menu_start)
if new_menu_end < 0:
    raise SystemExit("prepare clean settings: new_menu end not found")
new_menu_text = text[new_menu_start:new_menu_end]
if 'case TrackerMenu::LOG_EXPORT:' not in new_menu_text:
    anchor_pos = text.find(insert_anchor, new_menu_start, new_menu_end)
    if anchor_pos < 0:
        raise SystemExit("prepare clean settings: LOG_CLEAR insertion anchor not found")
    text = text[:anchor_pos] + export_case + text[anchor_pos:]
    print("Prepared clean settings live LOG_EXPORT page")

# Verification: current UI/export state must survive the clean hierarchy pass.
for needle in [
    r'LOG_STATUS,\n    LOG_EXPORT,\n    LOG_CLEAR,',
    'queueTrackerMenu(TrackerMenu::LOG_EXPORT, 0)',
    'case TrackerMenu::LOG_EXPORT:',
    'new_timeout_block',
]:
    if needle not in text:
        raise SystemExit(f"prepare clean settings verification failed: {needle}")

PATH.write_text(text)
