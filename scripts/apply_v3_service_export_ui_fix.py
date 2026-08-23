from pathlib import Path

SERVICE = Path("src/infrastructure/HeltecV3ServicePage.cpp")
service = SERVICE.read_text()


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if new in text:
        print(f"{label}: already applied")
        return text
    if old not in text:
        raise SystemExit(f"{label}: anchor not found")
    print(f"{label}: applied")
    return text.replace(old, new, 1)


# Selecting "Export via USB" must not immediately start a transfer. The user
# deliberately confirms it with a second long press. This patch intentionally
# does NOT change the established display policy: the OLED still turns off
# 20 seconds after the last accepted button action, including while a menu is
# open. Waking it later restores the existing page/menu state.
service = replace_once(
    service,
    "DIAG_LOG, CLEAR_CONFIRM",
    "DIAG_LOG, EXPORT_CONFIRM, CLEAR_CONFIRM",
    "V3 export confirmation menu state",
)

service = replace_once(
    service,
    '''            else if (selected == 1)\n                queueAction(V3MenuAction::EXPORT_LOG);\n''',
    '''            else if (selected == 1)\n                queueMenu(V3ServiceMenu::EXPORT_CONFIRM);\n''',
    "V3 Export via USB opens confirmation instead of starting transfer",
)

confirm_case = '''    case V3ServiceMenu::EXPORT_CONFIRM: {\n        static const char *options[] = {"Back", "HOLD: EXPORT NOW"};\n        showOptions("Export Diagnostic Log?", options, 2, [](int selected) {\n            if (selected == 0)\n                queueMenu(V3ServiceMenu::DIAG_LOG);\n            else if (selected == 1)\n                queueAction(V3MenuAction::EXPORT_LOG);\n        });\n        break;\n    }\n'''
service = replace_once(
    service,
    '''    case V3ServiceMenu::CLEAR_CONFIRM: {\n''',
    confirm_case + '''    case V3ServiceMenu::CLEAR_CONFIRM: {\n''',
    "V3 explicit long-hold export confirmation page",
)

for needle in [
    "EXPORT_CONFIRM",
    '"HOLD: EXPORT NOW"',
    '"Export Diagnostic Log?"',
    "queueMenu(V3ServiceMenu::EXPORT_CONFIRM)",
]:
    if needle not in service:
        raise SystemExit(f"V3 service/export verification failed: {needle}")

SERVICE.write_text(service)
print("V3 export confirmation ready; existing 20s-after-last-button display timeout preserved")
