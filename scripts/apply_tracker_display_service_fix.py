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


# When the service/display are already open, advance the native page on the
# press edge itself. Waiting for release + debounce made page changes vulnerable
# to missed/long releases and provided no benefit because buttonWasPressed
# already suppresses repeats while the button remains held.
replace_once(
    '''                } else {\n                    serviceLastActivityMs = now;\n                    if (!displayWindowActive() || (screen && !screen->isScreenOn())) {\n                        showTrackerScreen();\n                        openedServiceThisPress = true;\n                    }\n                }\n''',
    '''                } else {\n                    serviceLastActivityMs = now;\n                    if (!displayWindowActive() || (screen && !screen->isScreenOn())) {\n                        showTrackerScreen();\n                        openedServiceThisPress = true;\n                    } else if (bootHandoffComplete && screen) {\n                        const uint32_t pressNow = millis();\n                        displayStartedMs = pressNow ? pressNow : 1;\n                        displayVisible = true;\n                        screen->showNextFrame();\n                        screen->runNow();\n                        openedServiceThisPress = true;\n                        LOG_DEBUG("Tracker service: GPIO0 press -> next Meshtastic page");\n                    }\n                }\n''',
    "tracker GPIO0 immediate page cycling",
)

replace_once(
    '''                if (serviceActive && !openedServiceThisPress) {\n                    serviceLastActivityMs = now;\n                    displayStartedMs = now ? now : 1;\n                    displayVisible = true;\n                    if (bootHandoffComplete && screen) {\n                        screen->showNextFrame();\n                        screen->runNow();\n                    }\n                }\n''',
    '''                if (serviceActive && !openedServiceThisPress) {\n                    const uint32_t releaseNow = millis();\n                    serviceLastActivityMs = releaseNow;\n                    displayStartedMs = releaseNow ? releaseNow : 1;\n                    displayVisible = true;\n                    if (bootHandoffComplete && screen) {\n                        screen->showNextFrame();\n                        screen->runNow();\n                        LOG_DEBUG("Tracker service: GPIO0 short press -> next Meshtastic page");\n                    }\n                }\n''',
    "tracker GPIO0 page cycling timestamp",
)

replace_once(
    '''        if (serviceActive) {\n            const bool hardCap = (uint32_t)(now - serviceStartedMs) >= TRACKER_COMMON_SERVICE_MAX_MS;\n            const bool idle = (uint32_t)(now - serviceLastActivityMs) >= TRACKER_COMMON_SERVICE_IDLE_MS;\n            if (hardCap || idle) {\n                stopService();\n            } else if (displayVisible && displayStartedMs != 0 &&\n                       (uint32_t)(now - displayStartedMs) >= displayWindowMs) {\n                closeDisplay();\n                LOG_DEBUG("Tracker service: display window closed; Bluetooth service continues");\n            }\n''',
    '''        if (serviceActive) {\n            // startService() can spend hundreds of milliseconds bringing NimBLE up.\n            // Do not compare displayStartedMs against the stale runOnce() timestamp\n            // captured before that work: unsigned subtraction would underflow and\n            // make a brand-new 20s display window look immediately expired.\n            const uint32_t serviceNow = millis();\n            const bool hardCap = (uint32_t)(serviceNow - serviceStartedMs) >= TRACKER_COMMON_SERVICE_MAX_MS;\n            const bool idle = (uint32_t)(serviceNow - serviceLastActivityMs) >= TRACKER_COMMON_SERVICE_IDLE_MS;\n            if (hardCap || idle) {\n                stopService();\n            } else if (displayVisible && displayStartedMs != 0 &&\n                       (uint32_t)(serviceNow - displayStartedMs) >= displayWindowMs) {\n                closeDisplay();\n                LOG_DEBUG("Tracker service: display window closed; Bluetooth service continues");\n            }\n''',
    "tracker display stale-time underflow fix",
)

for needle in [
    'const uint32_t serviceNow = millis();',
    '(uint32_t)(serviceNow - displayStartedMs) >= displayWindowMs',
    'const uint32_t releaseNow = millis();',
    'const uint32_t pressNow = millis();',
    'Tracker service: GPIO0 press -> next Meshtastic page',
    'Tracker service: GPIO0 short press -> next Meshtastic page',
]:
    if needle not in text:
        raise SystemExit(f"tracker display service verification failed: {needle}")

PATH.write_text(text)
