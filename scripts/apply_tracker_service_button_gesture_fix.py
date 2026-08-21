from pathlib import Path

PATH = Path("src/vehicle/TrackerCommonPolicy.cpp")
text = PATH.read_text()


def replace_once(old: str, new: str, label: str):
    global text
    if new in text:
        print(f"{label}: already applied")
        return
    if old not in text:
        raise SystemExit(f"{label}: anchor not found")
    text = text.replace(old, new, 1)
    print(f"{label}: applied")


# A long press can only be recognized after the button has been held for the
# threshold. The previous code advanced the normal Meshtastic carousel on the
# press edge immediately, so every intended long press first selected the next
# page. Defer ALL normal page navigation until a confirmed short release.
replace_once(
    '''                    if (!displayWindowActive() || (screen && !screen->isScreenOn())) {\n                        showTrackerScreen();\n                        openedServiceThisPress = true;\n                    } else if (!trackerServiceMenuActive() && bootHandoffComplete && screen) {\n                        const uint32_t pressNow = millis();\n                        displayStartedMs = pressNow ? pressNow : 1;\n                        displayVisible = true;\n                        screen->showNextFrame();\n                        screen->runNow();\n                        openedServiceThisPress = true;\n                        LOG_DEBUG("Tracker service: GPIO0 press -> next Meshtastic page");\n                    }\n''',
    '''                    if (!displayWindowActive() || (screen && !screen->isScreenOn())) {\n                        showTrackerScreen();\n                        openedServiceThisPress = true;\n                    }\n''',
    "defer Tracker native page navigation until short release",
)

# On release, decide the gesture only after we know it was not a long press.
# Outside the service menu a short release advances the normal carousel. Inside
# the service menu it advances only the service sub-page. A long press has
# buttonLongHandled/openedServiceThisPress set and therefore never falls through
# into either short-press action.
replace_once(
    '''                if (serviceActive && !openedServiceThisPress && !buttonLongHandled && trackerServiceMenuActive()) {\n                    const uint32_t releaseNow = millis();\n                    serviceLastActivityMs = releaseNow;\n                    displayStartedMs = releaseNow ? releaseNow : 1;\n                    displayVisible = true;\n                    trackerServiceMenuNext();\n                    LOG_DEBUG("Tracker service: GPIO0 short press -> next service sub-page");\n                }\n''',
    '''                if (serviceActive && !openedServiceThisPress && !buttonLongHandled) {\n                    const uint32_t releaseNow = millis();\n                    serviceLastActivityMs = releaseNow;\n                    displayStartedMs = releaseNow ? releaseNow : 1;\n                    displayVisible = true;\n                    if (trackerServiceMenuActive()) {\n                        trackerServiceMenuNext();\n                        LOG_DEBUG("Tracker service: GPIO0 short release -> next service sub-page");\n                    } else if (bootHandoffComplete && screen) {\n                        screen->showNextFrame();\n                        screen->runNow();\n                        LOG_DEBUG("Tracker service: GPIO0 short release -> next Meshtastic page");\n                    }\n                }\n''',
    "separate Tracker short-release navigation from long-press menu action",
)

for needle in [
    'Tracker service: GPIO0 short release -> next Meshtastic page',
    'Tracker service: GPIO0 short release -> next service sub-page',
    'Tracker service: GPIO0 long press -> service menu action',
    'if (trackerServiceMenuActive())',
]:
    if needle not in text:
        raise SystemExit(f"Tracker service gesture verification failed: {needle}")

if 'Tracker service: GPIO0 press -> next Meshtastic page' in text:
    raise SystemExit("Tracker service gesture verification failed: immediate page advance still present")

PATH.write_text(text)
