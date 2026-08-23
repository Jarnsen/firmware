from pathlib import Path

SERVICE = Path("src/infrastructure/HeltecV3ServicePage.cpp")
POLICY = Path("src/infrastructure/HeltecV3RepeaterPolicy.cpp")
service = SERVICE.read_text()
policy = POLICY.read_text()


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if new in text:
        print(f"{label}: already applied")
        return text
    if old not in text:
        raise SystemExit(f"{label}: anchor not found")
    print(f"{label}: applied")
    return text.replace(old, new, 1)


# Selecting "Export via USB" must not immediately start a transfer. The user
# deliberately confirms it with a second long press. The established display
# policy remains unchanged: 20 seconds from the last accepted button action.
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

# Keep the menu-state probe available for runtime/CI diagnostics, but do not
# use it to hold the OLED on. This preserves the agreed 20-second inactivity
# timeout even while a service picker is open.
old_timeout = '''        const uint32_t displayNow = millis();\n        if (v3DisplayVisible &&\n            (uint32_t)(displayNow - v3DisplayStartedMs) >= (uint32_t)V3_SERVICE_DISPLAY_MS) {\n'''
new_timeout = '''        const uint32_t displayNow = millis();\n        const bool serviceUiActive = heltecV3ServiceMenuActive();\n        (void)serviceUiActive;\n        if (v3DisplayVisible &&\n            (uint32_t)(displayNow - v3DisplayStartedMs) >= (uint32_t)V3_SERVICE_DISPLAY_MS) {\n'''
policy = replace_once(policy, old_timeout, new_timeout, "V3 preserve 20s timeout with service UI state probe")

for text, needle in [
    (service, "EXPORT_CONFIRM"),
    (service, '"HOLD: EXPORT NOW"'),
    (service, '"Export Diagnostic Log?"'),
    (service, "queueMenu(V3ServiceMenu::EXPORT_CONFIRM)"),
    (policy, "const bool serviceUiActive = heltecV3ServiceMenuActive();"),
    (policy, "(void)serviceUiActive;"),
]:
    if needle not in text:
        raise SystemExit(f"V3 service/export verification failed: {needle}")

SERVICE.write_text(service)
POLICY.write_text(policy)
print("V3 export confirmation ready; 20s-after-last-button display timeout preserved")
