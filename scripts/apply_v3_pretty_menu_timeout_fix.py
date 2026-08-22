from pathlib import Path

POLICY_PATH = Path("src/infrastructure/HeltecV3RepeaterPolicy.cpp")
PAGE_PATH = Path("src/infrastructure/HeltecV3PositionPage.cpp")

policy = POLICY_PATH.read_text()
page = PAGE_PATH.read_text()


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if new in text:
        print(f"{label}: already applied")
        return text
    if old not in text:
        raise SystemExit(f"{label}: anchor not found")
    print(f"{label}: applied")
    return text.replace(old, new, 1)


# ---------------------------------------------------------------------------
# V3 OLED presentation
# ---------------------------------------------------------------------------
# Heltec WiFi LoRa 32 V3 uses a monochrome OLED. Do not imitate the Tracker
# TFT's color regions: keep the page white-on-black, but copy the useful visual
# hierarchy from the Tracker page (strong title, OLD/NEW data rows, status row,
# persistent action hint). This keeps all position logic unchanged.
old_draw = '''        char line[64] = {};\n        drawCenteredLine(display, x, 11 + y, "POSITION / MGRS");\n\n        snprintf(line, sizeof(line), "OLD %s", oldMgrs);\n        drawCenteredLine(display, x, 23 + y, line);\n\n        if (!state.havePhonePosition) {\n            drawCenteredLine(display, x, 35 + y, "NEW PHONE GPS WAIT");\n            drawCenteredLine(display, x, 49 + y, "BT: Handyposition senden");\n            return;\n        }\n\n        snprintf(line, sizeof(line), "NEW %s", newMgrs);\n        drawCenteredLine(display, x, 35 + y, line);\n\n        if (!state.phoneFresh) {\n            snprintf(line, sizeof(line), "GPS ALT %us - NICHT SPEICHERN",\n                     state.phoneAgeSecs == UINT32_MAX ? 9999U : (unsigned)state.phoneAgeSecs);\n            drawCenteredLine(display, x, 49 + y, line);\n            return;\n        }\n\n        if (!state.phoneAccurate) {\n            snprintf(line, sizeof(line), "ACC %um SCHLECHT - WARTEN", (unsigned)(state.accuracyMm / 1000UL));\n            drawCenteredLine(display, x, 49 + y, line);\n            return;\n        }\n\n        if (state.lastSaveValid && state.lastSaveAgeMs <= 5000U) {\n            snprintf(line, sizeof(line), "SAVED %s %um%s", state.lastSaveAutomatic ? "AUTO" : "MANUAL",\n                     (unsigned)state.lastSavedDifferenceM, state.lastSaveMeshSent ? " SENT" : "");\n            drawCenteredLine(display, x, 49 + y, line);\n            return;\n        }\n\n        const unsigned accM = (unsigned)(state.accuracyMm / 1000UL);\n        if (!state.haveSavedPosition) {\n            snprintf(line, sizeof(line), "ACC %um  LONG: SAVE", accM);\n        } else if (state.differenceM <= state.ignoreDistanceM) {\n            snprintf(line, sizeof(line), "DIFF %um ACC %um  OK", (unsigned)state.differenceM, accM);\n        } else if (state.differenceM <= state.autoDistanceM) {\n            snprintf(line, sizeof(line), "DIFF %um ACC %um LONG:SAVE", (unsigned)state.differenceM, accM);\n        } else {\n            snprintf(line, sizeof(line), "DIFF %um AUTO %u/%u LONG:SAVE", (unsigned)state.differenceM,\n                     (unsigned)state.autoConfirmCount, (unsigned)state.autoConfirmRequired);\n        }\n        drawCenteredLine(display, x, 49 + y, line);\n'''

new_draw = '''        char line[64] = {};\n        const int16_t center = display->getWidth() / 2 + x;\n\n        // Monochrome V3 OLED: use typography/spacing instead of fake colors.\n        display->setTextAlignment(TEXT_ALIGN_CENTER);\n        display->setFont(FONT_MEDIUM);\n        display->drawString(center, 0 + y, "POSITION  MGRS");\n\n        snprintf(line, sizeof(line), "OLD %s", oldMgrs);\n        drawCenteredLine(display, x, 18 + y, line);\n\n        if (!state.havePhonePosition) {\n            drawCenteredLine(display, x, 29 + y, "NEW PHONE GPS WAIT");\n            drawCenteredLine(display, x, 40 + y, "BT: POSITION SENDEN");\n            drawCenteredLine(display, x, 52 + y, "SHORT:NEXT LONG:SAVE");\n            return;\n        }\n\n        snprintf(line, sizeof(line), "NEW %s", newMgrs);\n        drawCenteredLine(display, x, 29 + y, line);\n\n        if (!state.phoneFresh) {\n            snprintf(line, sizeof(line), "GPS ALT %us - WARTEN",\n                     state.phoneAgeSecs == UINT32_MAX ? 9999U : (unsigned)state.phoneAgeSecs);\n        } else if (!state.phoneAccurate) {\n            snprintf(line, sizeof(line), "ACC %um - WARTEN", (unsigned)(state.accuracyMm / 1000UL));\n        } else if (state.lastSaveValid && state.lastSaveAgeMs <= 5000U) {\n            snprintf(line, sizeof(line), "SAVED %s %um%s", state.lastSaveAutomatic ? "AUTO" : "MANUAL",\n                     (unsigned)state.lastSavedDifferenceM, state.lastSaveMeshSent ? " SENT" : "");\n        } else {\n            const unsigned accM = (unsigned)(state.accuracyMm / 1000UL);\n            if (!state.haveSavedPosition) {\n                snprintf(line, sizeof(line), "ACC %um  READY", accM);\n            } else if (state.differenceM <= state.ignoreDistanceM) {\n                snprintf(line, sizeof(line), "DIFF %um ACC %um  OK", (unsigned)state.differenceM, accM);\n            } else if (state.differenceM <= state.autoDistanceM) {\n                snprintf(line, sizeof(line), "DIFF %um ACC %um CHECK", (unsigned)state.differenceM, accM);\n            } else {\n                snprintf(line, sizeof(line), "DIFF %um AUTO %u/%u", (unsigned)state.differenceM,\n                         (unsigned)state.autoConfirmCount, (unsigned)state.autoConfirmRequired);\n            }\n        }\n        drawCenteredLine(display, x, 40 + y, line);\n        drawCenteredLine(display, x, 52 + y, "SHORT:NEXT LONG:SAVE");\n'''
page = replace_once(page, old_draw, new_draw, "apply clean monochrome V3 position menu layout")


# ---------------------------------------------------------------------------
# Display timeout semantics
# ---------------------------------------------------------------------------
# The 20-second window is an inactivity timeout, not a fixed lifetime from the
# moment the menu was opened. Short taps already reset v3DisplayStartedMs in the
# one-tap guard and a wake press resets it in the native-page patch. Long press
# must do the same so the screen cannot switch off while the user is operating
# the position page.
old_long = '''            if (heltecV3PositionPageRecentlyVisible()) {\n                heltecV3ManualSaveLatestPosition();\n                heltecV3PositionPageRefresh();\n            }\n            v3LongPressHandled = true;\n            v3ServiceLastActivityMs = now;\n'''
new_long = '''            if (heltecV3PositionPageRecentlyVisible()) {\n                heltecV3ManualSaveLatestPosition();\n                heltecV3PositionPageRefresh();\n            }\n            v3LongPressHandled = true;\n            // 20 s of display inactivity are counted from the last accepted\n            // user action. BLE/GPS traffic deliberately does not extend it.\n            v3DisplayStartedMs = now;\n            v3DisplayVisible = true;\n            v3ServiceLastActivityMs = now;\n'''
policy = replace_once(policy, old_long, new_long, "reset V3 20s display inactivity timer on long press")

# Guardrails: this script must preserve the already-agreed menu timeout and the
# short-tap reset installed by apply_v3_ble_visibility_button_guard_fix.py.
for needle in [
    "#define V3_SERVICE_DISPLAY_MS (20UL * 1000UL)",
    "v3DisplayStartedMs = now;",
    "SHORT:NEXT LONG:SAVE",
    "POSITION  MGRS",
]:
    if needle not in (policy + page):
        raise SystemExit(f"V3 pretty-menu verification failed: {needle}")

POLICY_PATH.write_text(policy)
PAGE_PATH.write_text(page)
print("V3 menu ready: monochrome V1.1-style hierarchy + 20s inactivity after last accepted button action")
