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


# Export must require an explicit second long-press confirmation. Selecting
# "Export via USB" only opens a confirmation picker; no serial transfer starts.
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

# A selection picker is an active user interaction. Do not let the generic
# 20-second page timer power the OLED off underneath an open Service/Diagnostic/
# Power menu. The 120-second service inactivity and 15-minute hard cap still
# remain in force, so this cannot keep the service session alive forever.
old_timeout = '''        const uint32_t displayNow = millis();\n        if (v3DisplayVisible &&\n            (uint32_t)(displayNow - v3DisplayStartedMs) >= (uint32_t)V3_SERVICE_DISPLAY_MS) {\n            v3DisplayVisible = false;\n            if (screen && screen->isScreenOn())\n                screen->setOn(false);\n            LOG_DEBUG("Heltec V3 service: display window closed");\n        }\n'''
new_timeout = '''        const uint32_t displayNow = millis();\n        const bool serviceUiActive = heltecV3ServiceMenuActive();\n        if (serviceUiActive) {\n            // A menu disappearing looks exactly like a crash on the one-button\n            // device. Keep it visible and repair any unrelated screen-off while\n            // the picker is active. User button activity still drives the normal\n            // 120 s service-idle timer.\n            v3DisplayVisible = true;\n            v3DisplayStartedMs = displayNow ? displayNow : 1;\n            if (screen && !screen->isScreenOn()) {\n                screen->setOn(true);\n                screen->runNow();\n                LOG_WARN("Heltec V3 service: restored screen while service menu active");\n            }\n        } else if (v3DisplayVisible &&\n                   (uint32_t)(displayNow - v3DisplayStartedMs) >= (uint32_t)V3_SERVICE_DISPLAY_MS) {\n            v3DisplayVisible = false;\n            if (screen && screen->isScreenOn())\n                screen->setOn(false);\n            LOG_DEBUG("Heltec V3 service: display window closed");\n        }\n'''
policy = replace_once(policy, old_timeout, new_timeout, "V3 keep display alive while Service menu is active")

for text, needle in [
    (service, "EXPORT_CONFIRM"),
    (service, '"HOLD: EXPORT NOW"'),
    (service, '"Export Diagnostic Log?"'),
    (service, "queueMenu(V3ServiceMenu::EXPORT_CONFIRM)"),
    (policy, "const bool serviceUiActive = heltecV3ServiceMenuActive();"),
    (policy, "restored screen while service menu active"),
]:
    if needle not in text:
        raise SystemExit(f"V3 service/export verification failed: {needle}")

SERVICE.write_text(service)
POLICY.write_text(policy)
print("V3 service UI ready: menu display held on + second long-hold confirmation before USB export")
