from pathlib import Path

POLICY = Path("src/infrastructure/HeltecV3RepeaterPolicy.cpp")
POSITION = Path("src/infrastructure/HeltecV3PositionPage.cpp")

policy = POLICY.read_text()
position = POSITION.read_text()


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if new in text:
        print(f"{label}: already applied")
        return text
    if old not in text:
        raise SystemExit(f"{label}: anchor not found")
    print(f"{label}: applied")
    return text.replace(old, new, 1)


def replace_span(text: str, start: str, end: str, replacement: str, label: str) -> str:
    a = text.find(start)
    if a < 0:
        raise SystemExit(f"{label}: start anchor not found")
    b = text.find(end, a)
    if b < 0:
        raise SystemExit(f"{label}: end anchor not found")
    b += len(end)
    print(f"{label}: applied")
    return text[:a] + replacement + text[b:]


# ---------------------------------------------------------------------------
# Position: use the exact same stock Meshtastic chrome as the other local V3
# pages. The MGRS/distance policy is unchanged; this is presentation only.
# ---------------------------------------------------------------------------
position = replace_once(
    position,
    '#include "graphics/ScreenFonts.h"\n',
    '#include "graphics/ScreenFonts.h"\n#include "graphics/SharedUIDisplay.h"\n#include "graphics/draw/UIRenderer.h"\n',
    "include stock Meshtastic UI helpers on V3 Position",
)
position = replace_once(
    position,
    '    void drawFrame(OLEDDisplay *display, OLEDDisplayUiState *, int16_t x, int16_t y) override\n',
    '    void drawFrame(OLEDDisplay *display, OLEDDisplayUiState *uiState, int16_t x, int16_t y) override\n',
    "name V3 Position UI state for stock navigation bar",
)

pretty_start = '''        char line[64] = {};\n        const int16_t center = display->getWidth() / 2 + x;\n'''
pretty_end = '''        drawCenteredLine(display, x, 54 + y, line);\n'''
stock_position = r'''        char line[64] = {};
        const int16_t center = display->getWidth() / 2 + x;
        const int left = x + 2;
        const int right = x + display->getWidth() - 2;

        auto splitMgrs = [](const char *mgrs, char *prefix, size_t prefixSize, char *digits, size_t digitsSize) {
            char zoneBand[8] = {};
            char grid[4] = {};
            char east[8] = {};
            char north[8] = {};
            if (!mgrs || sscanf(mgrs, "%7s %3s %7s %7s", zoneBand, grid, east, north) != 4) {
                snprintf(prefix, prefixSize, "---");
                snprintf(digits, digitsSize, "---");
                return false;
            }
            snprintf(prefix, prefixSize, "%s %s", zoneBand, grid);
            snprintf(digits, digitsSize, "%s %s", east, north);
            return true;
        };

        char oldPrefix[16] = "---";
        char oldDigits[20] = "---";
        char newPrefix[16] = "---";
        char newDigits[20] = "---";
        const bool oldMgrsValid = state.haveSavedPosition &&
                                  splitMgrs(oldMgrs, oldPrefix, sizeof(oldPrefix), oldDigits, sizeof(oldDigits));
        const bool newMgrsValid = state.havePhonePosition &&
                                  splitMgrs(newMgrs, newPrefix, sizeof(newPrefix), newDigits, sizeof(newDigits));
        const bool goodPhone = state.havePhonePosition && state.phoneFresh && state.phoneAccurate && newMgrsValid;
        const unsigned accM = (unsigned)(state.accuracyMm / 1000UL);

        display->clear();
        graphics::drawCommonHeader(display, x, y, "Position");
        display->setColor(WHITE);
        const int *textPos = graphics::getTextPositions(display);

        auto finishPage = [&]() {
            graphics::drawCommonFooter(display, x, y);
            if (uiState)
                graphics::UIRenderer::drawNavigationBar(display, uiState);
        };
        auto drawPair = [&](int yy, const char *a, const char *b) {
            display->setFont(FONT_SMALL);
            display->setTextAlignment(TEXT_ALIGN_LEFT);
            display->drawString(left, yy, a ? a : "");
            display->setTextAlignment(TEXT_ALIGN_RIGHT);
            display->drawString(right, yy, b ? b : "");
        };

        if (state.lastSaveValid && state.lastSaveAgeMs <= 3000U && oldMgrsValid) {
            drawPair(textPos[1], "POSITION SAVED", state.lastSaveAutomatic ? "AUTO" : "MANUAL");
            display->setTextAlignment(TEXT_ALIGN_CENTER);
            display->setFont(FONT_SMALL);
            display->drawString(center, textPos[2], oldPrefix);
            display->setFont(FONT_MEDIUM);
            display->drawString(center, textPos[3], oldDigits);
            snprintf(line, sizeof(line), "DIFF %um%s", (unsigned)state.lastSavedDifferenceM,
                     state.lastSaveMeshSent ? "  SENT" : "");
            display->setFont(FONT_SMALL);
            display->drawString(center, textPos[4], line);
            finishPage();
            return;
        }

        const bool compareMode = goodPhone && oldMgrsValid && state.differenceM > state.ignoreDistanceM;
        if (compareMode) {
            snprintf(line, sizeof(line), "OLD %s %s", oldPrefix, oldDigits);
            display->setTextAlignment(TEXT_ALIGN_CENTER);
            display->setFont(FONT_SMALL);
            display->drawString(center, textPos[1], line);
            snprintf(line, sizeof(line), "NEW %s %s", newPrefix, newDigits);
            display->drawString(center, textPos[2], line);
            char l[28] = {};
            char r[28] = {};
            snprintf(l, sizeof(l), "DIFF:%um", (unsigned)state.differenceM);
            snprintf(r, sizeof(r), "ACC:%um", accM);
            drawPair(textPos[3], l, r);
            if (state.differenceM > state.autoDistanceM)
                snprintf(line, sizeof(line), "AUTO %u/%u   HOLD:SAVE", (unsigned)state.autoConfirmCount,
                         (unsigned)state.autoConfirmRequired);
            else
                snprintf(line, sizeof(line), "POSITION CHECK   HOLD:SAVE");
            display->setTextAlignment(TEXT_ALIGN_CENTER);
            display->drawString(center, textPos[4], line);
            finishPage();
            return;
        }

        if (!oldMgrsValid && goodPhone) {
            display->setTextAlignment(TEXT_ALIGN_CENTER);
            display->setFont(FONT_SMALL);
            display->drawString(center, textPos[1], "NEW POSITION");
            display->drawString(center, textPos[2], newPrefix);
            display->setFont(FONT_MEDIUM);
            display->drawString(center, textPos[3], newDigits);
            snprintf(line, sizeof(line), "ACC %um   HOLD:SAVE", accM);
            display->setFont(FONT_SMALL);
            display->drawString(center, textPos[4], line);
            finishPage();
            return;
        }

        if (!oldMgrsValid) {
            display->setTextAlignment(TEXT_ALIGN_CENTER);
            display->setFont(FONT_MEDIUM);
            display->drawString(center, textPos[2], "NO POSITION");
            display->setFont(FONT_SMALL);
            display->drawString(center, textPos[4], state.havePhonePosition ? "PHONE GPS WAIT" : "WAIT FOR PHONE GPS");
            finishPage();
            return;
        }

        display->setTextAlignment(TEXT_ALIGN_CENTER);
        display->setFont(FONT_SMALL);
        display->drawString(center, textPos[1], oldPrefix);
        display->setFont(FONT_MEDIUM);
        display->drawString(center, textPos[2], oldDigits);
        display->setFont(FONT_SMALL);

        if (!state.havePhonePosition) {
            snprintf(line, sizeof(line), "FIXED POSITION");
        } else if (!state.phoneFresh) {
            snprintf(line, sizeof(line), "GPS AGE %us", state.phoneAgeSecs == UINT32_MAX ? 9999U : (unsigned)state.phoneAgeSecs);
        } else if (!state.phoneAccurate) {
            snprintf(line, sizeof(line), "GPS ACC %um - WAIT", accM);
        } else {
            snprintf(line, sizeof(line), "POSITION OK  %um  ACC %um", (unsigned)state.differenceM, accM);
        }
        display->drawString(center, textPos[4], line);
        finishPage();
'''
position = replace_span(position, pretty_start, pretty_end, stock_position, "render V3 Position with stock page chrome")


# ---------------------------------------------------------------------------
# One-button menu routing. Outside the menu short release still advances the
# stock carousel. On Service, long opens the stock selection picker. Inside the
# picker short = next selection and long = SELECT. Position and Antenna retain
# their page-specific long actions; Mesh Health is deliberately read-only.
# ---------------------------------------------------------------------------
policy = replace_once(
    policy,
    '''        v3UpdateUsbMaintenance();\n        heltecV3DiagPumpUsbExport();\n        heltecV3MeshMonitorTick();\n\n#ifdef BUTTON_PIN\n''',
    '''        v3UpdateUsbMaintenance();\n        heltecV3DiagPumpUsbExport();\n        heltecV3MeshMonitorTick();\n        heltecV3ServiceMenuPump();\n\n#ifdef BUTTON_PIN\n''',
    "pump V3 stock service menu",
)

old_long = '''        if (v3ButtonWasPressed && pressed && !v3OpenedServiceThisPress && !v3LongPressHandled &&\n            (uint32_t)(now - v3ButtonPressedSinceMs) >= V3_SERVICE_LONG_PRESS_MS) {\n            if (heltecV3PositionPageRecentlyVisible()) {\n                heltecV3ManualSaveLatestPosition();\n                heltecV3PositionPageRefresh();\n            } else if (heltecV3ServicePageRecentlyVisible()) {\n                heltecV3DiagRequestUsbExport();\n                heltecV3ServicePageRefresh();\n            } else if (heltecV3AntennaPageRecentlyVisible()) {\n                heltecV3AntennaHandleLongPress();\n                heltecV3MeshPagesRefresh();\n            }\n            v3LongPressHandled = true;\n            // 20 s of display inactivity are counted from the last accepted\n            // user action. BLE/GPS traffic deliberately does not extend it.\n            v3DisplayStartedMs = now;\n            v3DisplayVisible = true;\n            v3ServiceLastActivityMs = now;\n        }\n'''
new_long = '''        if (v3ButtonWasPressed && pressed && !v3OpenedServiceThisPress && !v3LongPressHandled &&\n            (uint32_t)(now - v3ButtonPressedSinceMs) >= V3_SERVICE_LONG_PRESS_MS) {\n            if (heltecV3ServiceMenuActive()) {\n                heltecV3ServiceMenuSelect();\n            } else if (heltecV3PositionPageRecentlyVisible()) {\n                heltecV3ManualSaveLatestPosition();\n                heltecV3PositionPageRefresh();\n            } else if (heltecV3ServicePageRecentlyVisible()) {\n                heltecV3ServiceMenuOpen();\n            } else if (heltecV3AntennaPageRecentlyVisible()) {\n                heltecV3AntennaHandleLongPress();\n                heltecV3MeshPagesRefresh();\n            }\n            // Mesh Health and stock Meshtastic pages are read-only on long press.\n            // The gesture is still consumed so release cannot become a short tap.\n            v3LongPressHandled = true;\n            v3DisplayStartedMs = now;\n            v3DisplayVisible = true;\n            v3ServiceLastActivityMs = now;\n        }\n'''
policy = replace_once(policy, old_long, new_long, "route V3 long press through real stock menu")

old_short = '''            if (!v3OpenedServiceThisPress && !v3LongPressHandled && validTap && actionGuardExpired) {\n                if (screen) {\n                    screen->showNextFrame();\n                    screen->runNow();\n                }\n                v3LastPageAdvanceMs = now ? now : 1;\n                v3DisplayStartedMs = now;\n                v3DisplayVisible = true;\n                v3ServiceLastActivityMs = now;\n                LOG_DEBUG("Heltec V3 button: one tap -> one next frame (held=%ums)", (unsigned)heldMs);\n'''
new_short = '''            if (!v3OpenedServiceThisPress && !v3LongPressHandled && validTap && actionGuardExpired) {\n                if (heltecV3ServiceMenuActive()) {\n                    heltecV3ServiceMenuNext();\n                    LOG_DEBUG("Heltec V3 button: one tap -> next service-menu item (held=%ums)", (unsigned)heldMs);\n                } else if (screen) {\n                    screen->showNextFrame();\n                    screen->runNow();\n                    LOG_DEBUG("Heltec V3 button: one tap -> one next frame (held=%ums)", (unsigned)heldMs);\n                }\n                v3LastPageAdvanceMs = now ? now : 1;\n                v3DisplayStartedMs = now;\n                v3DisplayVisible = true;\n                v3ServiceLastActivityMs = now;\n'''
policy = replace_once(policy, old_short, new_short, "short release drives menu cursor or stock carousel")

# After a 20-second display timeout the first press must only restore whatever
# the user was looking at. It must not jump back to Position and must not also
# advance on release. This mirrors the Tracker V1.1 interaction model.
old_wake = '''            if (!v3DisplayVisible || (screen && !screen->isScreenOn())) {\n                v3DisplayStartedMs = now;\n                v3DisplayVisible = true;\n                if (screen && !screen->isScreenOn())\n                    screen->setOn(true);\n                heltecV3PositionPageRequestFocus();\n                v3OpenedServiceThisPress = true;\n            }\n'''
new_wake = '''            if (!v3DisplayVisible || (screen && !screen->isScreenOn())) {\n                v3DisplayStartedMs = now;\n                v3DisplayVisible = true;\n                if (screen && !screen->isScreenOn())\n                    screen->setOn(true);\n                // Preserve current page/menu. This wake press is consumed; its\n                // release must not navigate. Initial service open still focuses Position.\n                if (screen)\n                    screen->runNow();\n                v3OpenedServiceThisPress = true;\n            }\n'''
policy = replace_once(policy, old_wake, new_wake, "restore current V3 page after display timeout")

# A service window may expire while a picker is open. Always clear only our
# selection picker before parking the display/BLE, so the next GPIO0 session
# starts from a clean native page.
policy = replace_once(
    policy,
    '''static void stopV3ServiceMode()\n{\n    if (!v3ServiceActive)\n        return;\n    v3BluetoothOffNow();\n''',
    '''static void stopV3ServiceMode()\n{\n    if (!v3ServiceActive)\n        return;\n    heltecV3ServiceMenuClose();\n    v3BluetoothOffNow();\n''',
    "close V3 service picker when service window ends",
)

for text, needle in [
    (position, 'graphics::drawCommonHeader(display, x, y, "Position")'),
    (position, 'graphics::drawCommonFooter(display, x, y)'),
    (position, 'graphics::UIRenderer::drawNavigationBar(display, uiState)'),
    (policy, 'heltecV3ServiceMenuPump();'),
    (policy, 'heltecV3ServiceMenuSelect();'),
    (policy, 'heltecV3ServiceMenuOpen();'),
    (policy, 'heltecV3ServiceMenuNext();'),
    (policy, 'Preserve current page/menu'),
]:
    if needle not in text:
        raise SystemExit(f"V3 stock UI/menu verification failed: {needle}")

if 'heltecV3DiagRequestUsbExport();\n                heltecV3ServicePageRefresh();' in policy:
    raise SystemExit("V3 stock UI/menu verification failed: Service long press still exports log directly")

POLICY.write_text(policy)
POSITION.write_text(position)
print("V3 stock UI ready: native page chrome + Tracker-style one-button selection menu + current-page wake restore")

# Power Statistics is layered last because it extends the final Tracker-style
# Service picker and runtime state produced above.
power_patch = Path("scripts/apply_v3_power_monitor_fix.py")
if not power_patch.exists():
    raise SystemExit("V3 power integration script missing")
exec(compile(power_patch.read_text(), str(power_patch), "exec"), {"__name__": "__main__"})
