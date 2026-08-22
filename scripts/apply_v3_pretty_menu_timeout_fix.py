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
# The Heltec WiFi LoRa 32 V3 has a monochrome OLED. Keep the native Meshtastic
# look: one calm primary position view, large MGRS digits, and only enter a
# denser OLD/NEW comparison view when a good phone fix actually differs by more
# than the 25 m ignore threshold. Navigation help is not permanently printed;
# LONG:SAVE is shown only when a position can meaningfully be accepted.
old_draw = '''        char line[64] = {};\n        drawCenteredLine(display, x, 11 + y, "POSITION / MGRS");\n\n        snprintf(line, sizeof(line), "OLD %s", oldMgrs);\n        drawCenteredLine(display, x, 23 + y, line);\n\n        if (!state.havePhonePosition) {\n            drawCenteredLine(display, x, 35 + y, "NEW PHONE GPS WAIT");\n            drawCenteredLine(display, x, 49 + y, "BT: Handyposition senden");\n            return;\n        }\n\n        snprintf(line, sizeof(line), "NEW %s", newMgrs);\n        drawCenteredLine(display, x, 35 + y, line);\n\n        if (!state.phoneFresh) {\n            snprintf(line, sizeof(line), "GPS ALT %us - NICHT SPEICHERN",\n                     state.phoneAgeSecs == UINT32_MAX ? 9999U : (unsigned)state.phoneAgeSecs);\n            drawCenteredLine(display, x, 49 + y, line);\n            return;\n        }\n\n        if (!state.phoneAccurate) {\n            snprintf(line, sizeof(line), "ACC %um SCHLECHT - WARTEN", (unsigned)(state.accuracyMm / 1000UL));\n            drawCenteredLine(display, x, 49 + y, line);\n            return;\n        }\n\n        if (state.lastSaveValid && state.lastSaveAgeMs <= 5000U) {\n            snprintf(line, sizeof(line), "SAVED %s %um%s", state.lastSaveAutomatic ? "AUTO" : "MANUAL",\n                     (unsigned)state.lastSavedDifferenceM, state.lastSaveMeshSent ? " SENT" : "");\n            drawCenteredLine(display, x, 49 + y, line);\n            return;\n        }\n\n        const unsigned accM = (unsigned)(state.accuracyMm / 1000UL);\n        if (!state.haveSavedPosition) {\n            snprintf(line, sizeof(line), "ACC %um  LONG: SAVE", accM);\n        } else if (state.differenceM <= state.ignoreDistanceM) {\n            snprintf(line, sizeof(line), "DIFF %um ACC %um  OK", (unsigned)state.differenceM, accM);\n        } else if (state.differenceM <= state.autoDistanceM) {\n            snprintf(line, sizeof(line), "DIFF %um ACC %um LONG:SAVE", (unsigned)state.differenceM, accM);\n        } else {\n            snprintf(line, sizeof(line), "DIFF %um AUTO %u/%u LONG:SAVE", (unsigned)state.differenceM,\n                     (unsigned)state.autoConfirmCount, (unsigned)state.autoConfirmRequired);\n        }\n        drawCenteredLine(display, x, 49 + y, line);\n'''

new_draw = '''        char line[64] = {};\n        const int16_t center = display->getWidth() / 2 + x;\n\n        auto splitMgrs = [](const char *mgrs, char *prefix, size_t prefixSize, char *digits, size_t digitsSize) {\n            char zoneBand[8] = {};\n            char grid[4] = {};\n            char east[8] = {};\n            char north[8] = {};\n            if (!mgrs || sscanf(mgrs, "%7s %3s %7s %7s", zoneBand, grid, east, north) != 4) {\n                snprintf(prefix, prefixSize, "---");\n                snprintf(digits, digitsSize, "---");\n                return false;\n            }\n            snprintf(prefix, prefixSize, "%s %s", zoneBand, grid);\n            snprintf(digits, digitsSize, "%s %s", east, north);\n            return true;\n        };\n\n        char oldPrefix[16] = "---";\n        char oldDigits[20] = "---";\n        char newPrefix[16] = "---";\n        char newDigits[20] = "---";\n        const bool oldMgrsValid = state.haveSavedPosition &&\n                                  splitMgrs(oldMgrs, oldPrefix, sizeof(oldPrefix), oldDigits, sizeof(oldDigits));\n        const bool newMgrsValid = state.havePhonePosition &&\n                                  splitMgrs(newMgrs, newPrefix, sizeof(newPrefix), newDigits, sizeof(newDigits));\n        const bool goodPhone = state.havePhonePosition && state.phoneFresh && state.phoneAccurate && newMgrsValid;\n        const unsigned accM = (unsigned)(state.accuracyMm / 1000UL);\n\n        display->setTextAlignment(TEXT_ALIGN_CENTER);\n\n        // Saved feedback is intentionally brief. After ~3 s the normal native\n        // position view takes over again without consuming a permanent row.\n        if (state.lastSaveValid && state.lastSaveAgeMs <= 3000U && oldMgrsValid) {\n            display->setFont(FONT_MEDIUM);\n            display->drawString(center, 11 + y, "POSITION SAVED");\n            display->setFont(FONT_SMALL);\n            display->drawString(center, 28 + y, state.lastSaveAutomatic ? "AUTO" : "MANUAL");\n            display->drawString(center, 39 + y, oldPrefix);\n            display->setFont(FONT_MEDIUM);\n            display->drawString(center, 49 + y, oldDigits);\n            return;\n        }\n\n        // Comparison mode only when a trustworthy phone position really differs\n        // from the stored fixed position. This keeps the normal page uncluttered.\n        const bool compareMode = goodPhone && oldMgrsValid && state.differenceM > state.ignoreDistanceM;\n        if (compareMode) {\n            display->setFont(FONT_MEDIUM);\n            display->drawString(center, 10 + y, state.differenceM > state.autoDistanceM ? "AUTO POSITION" : "POSITION CHECK");\n\n            char oldCompact[40] = {};\n            char newCompact[40] = {};\n            snprintf(oldCompact, sizeof(oldCompact), "OLD %s %s", oldPrefix, oldDigits);\n            snprintf(newCompact, sizeof(newCompact), "NEW %s %s", newPrefix, newDigits);\n            drawCenteredLine(display, x, 27 + y, oldCompact);\n            drawCenteredLine(display, x, 38 + y, newCompact);\n\n            snprintf(line, sizeof(line), "DIFF %um  ACC %um", (unsigned)state.differenceM, accM);\n            drawCenteredLine(display, x, 49 + y, line);\n            if (state.differenceM > state.autoDistanceM)\n                snprintf(line, sizeof(line), "AUTO %u/%u  LONG:SAVE", (unsigned)state.autoConfirmCount,\n                         (unsigned)state.autoConfirmRequired);\n            else\n                snprintf(line, sizeof(line), "LONG:SAVE");\n            drawCenteredLine(display, x, 59 + y, line);\n            return;\n        }\n\n        // No stored fixed position yet: a good phone fix becomes the candidate\n        // primary view and explicitly offers manual acceptance.\n        if (!oldMgrsValid && goodPhone) {\n            display->setFont(FONT_SMALL);\n            display->drawString(center, 12 + y, "NEUE POSITION");\n            display->drawString(center, 23 + y, newPrefix);\n            display->setFont(FONT_LARGE);\n            display->drawString(center, 31 + y, newDigits);\n            snprintf(line, sizeof(line), "ACC %um  LONG:SAVE", accM);\n            drawCenteredLine(display, x, 54 + y, line);\n            return;\n        }\n\n        if (!oldMgrsValid) {\n            display->setFont(FONT_MEDIUM);\n            display->drawString(center, 20 + y, "KEINE POSITION");\n            display->setFont(FONT_SMALL);\n            display->drawString(center, 43 + y, state.havePhonePosition ? "PHONE GPS WARTEN" : "PHONE GPS WAIT");\n            return;\n        }\n\n        // Normal native-style position page: the fixed MGRS position is the\n        // visual focus. OLD/NEW labels stay hidden unless comparison is useful.\n        display->setFont(FONT_SMALL);\n        display->drawString(center, 12 + y, "POSITION");\n        display->drawString(center, 23 + y, oldPrefix);\n        display->setFont(FONT_LARGE);\n        display->drawString(center, 31 + y, oldDigits);\n\n        if (!state.havePhonePosition) {\n            snprintf(line, sizeof(line), "FIXED POSITION");\n        } else if (!state.phoneFresh) {\n            snprintf(line, sizeof(line), "GPS ALT %us",\n                     state.phoneAgeSecs == UINT32_MAX ? 9999U : (unsigned)state.phoneAgeSecs);\n        } else if (!state.phoneAccurate) {\n            snprintf(line, sizeof(line), "GPS ACC %um - WARTEN", accM);\n        } else {\n            snprintf(line, sizeof(line), "POSITION OK  %um  ACC %um", (unsigned)state.differenceM, accM);\n        }\n        drawCenteredLine(display, x, 54 + y, line);\n'''
page = replace_once(page, old_draw, new_draw, "apply native-style V3 position and comparison views")


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

# Guardrails: preserve the agreed 20 s inactivity semantics and ensure the
# cleaner native page does not regress to a permanently verbose help screen.
for needle in [
    "#define V3_SERVICE_DISPLAY_MS (20UL * 1000UL)",
    "v3DisplayStartedMs = now;",
    "POSITION SAVED",
    "POSITION CHECK",
    "AUTO POSITION",
    "POSITION OK",
    "FONT_LARGE",
]:
    if needle not in (policy + page):
        raise SystemExit(f"V3 pretty-menu verification failed: {needle}")

if 'SHORT:NEXT LONG:SAVE' in page:
    raise SystemExit("V3 pretty-menu verification failed: permanent navigation help still present")

POLICY_PATH.write_text(policy)
PAGE_PATH.write_text(page)
print("V3 position page ready: native primary MGRS view + conditional OLD/NEW comparison + 20s inactivity")
