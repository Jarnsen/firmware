from pathlib import Path

PATH = Path("scripts/apply_tracker_clean_settings_menu_fix.py")
text = PATH.read_text()

# The clean-settings pass runs after the original UI/diagnostic/export passes.
# Normalize the patch script itself so it targets that current generated shape
# instead of an older intermediate version.

# 1) LOG_EXPORT already exists before the clean hierarchy pass. Preserve it in
# both the old enum anchor and the replacement enum.
old_enum_piece = "    LOG_STATUS,\\n    LOG_CLEAR,\\n"
new_enum_piece = "    LOG_STATUS,\\n    LOG_EXPORT,\\n    LOG_CLEAR,\\n"
count = text.count(old_enum_piece)
if count:
    text = text.replace(old_enum_piece, new_enum_piece, min(count, 2))
    print(f"Prepared clean settings enum for LOG_EXPORT x{min(count, 2)}")

# 2) The prior diagnostic pass can add statements around the service-window
# logic, so the exact two-line hardCap/idle anchor can be stale. Make the clean
# patch's replace_once helper tolerate that one known case by locating the two
# declarations directly in the generated TrackerCommon source.
old_helper = """    if old not in text:\n        raise SystemExit(f\"{label}: anchor not found\")\n    print(f\"{label}: applied\")\n    return text.replace(old, new, 1)\n"""
new_helper = """    if old not in text:\n        if label == 'dynamic BLE idle/hard timeout enforcement':\n            import re\n            pattern = re.compile(\n                r'^\\s{12}const bool hardCap = .*?;\\n\\s{12}const bool idle = .*?;\\n',\n                re.MULTILINE,\n            )\n            match = pattern.search(text)\n            if not match:\n                raise SystemExit(f\"{label}: runtime declarations not found\")\n            print(f\"{label}: applied via runtime declaration matcher\")\n            return text[:match.start()] + new + text[match.end():]\n        raise SystemExit(f\"{label}: anchor not found\")\n    print(f\"{label}: applied\")\n    return text.replace(old, new, 1)\n"""
if new_helper not in text:
    if old_helper not in text:
        raise SystemExit("prepare clean settings: replace_once helper anchor not found")
    text = text.replace(old_helper, new_helper, 1)
    print("Prepared clean settings BLE timeout fallback")

# 3) Keep the working live Log Download page in the new clean hierarchy.
old_export_action = "else if (selected == 3) { trackerDiagRequestUsbExport(); queueTrackerMenu(TrackerMenu::DIAG_LOG, 0); }"
new_export_action = "else if (selected == 3) { trackerDiagRequestUsbExport(); queueTrackerMenu(TrackerMenu::LOG_EXPORT, 0); }"
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
insert_anchor = "    case TrackerMenu::LOG_CLEAR: {\\n"
new_menu_start = text.find("new_menu = r'''void showTrackerMenu")
if new_menu_start < 0:
    raise SystemExit("prepare clean settings: new_menu start not found")
new_menu_end = text.find("'''\\nstatus = replace_span", new_menu_start)
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
    "LOG_STATUS,\\n    LOG_EXPORT,\\n    LOG_CLEAR,",
    'queueTrackerMenu(TrackerMenu::LOG_EXPORT, 0)',
    'case TrackerMenu::LOG_EXPORT:',
    'dynamic BLE idle/hard timeout enforcement',
]:
    if needle not in text:
        raise SystemExit(f"prepare clean settings verification failed: {needle}")

PATH.write_text(text)
