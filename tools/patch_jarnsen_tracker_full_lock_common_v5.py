"""Wire Tracker V1.1 Full-Lock UI to the active TrackerCommonPolicy.

Build 193 proved that wake-only works, but the second GPIO0 press appeared to do
nothing. The reason is that TrackerCommonPolicy owns GPIO0 for both TAK and
TAK_TRACKER, while the previous Full-Lock transforms concentrated on the older
TAK-specific policy. TrackerCommonPolicy was already incrementing its private
PIN digit on the second press, but the Full-Lock renderer intentionally covered
its legacy small banner with NODE GESPERRT.

This post-transform keeps the existing TrackerCommonPolicy security semantics:
- existing serviceSecurityLock/serviceSecurityUnlock implementation
- existing six-digit PIN state
- existing wrong-PIN 5 second block
- existing lock/unlock mesh alerts

It changes only the operator UI state:
- display off -> first GPIO0 press wakes NODE GESPERRT only
- next press while NODE GESPERRT is visible enters a dedicated PIN UI
- short press in PIN UI increments the selected digit
- long press confirms/advances the selected digit
- display timeout exits PIN UI, so the next wake starts at NODE GESPERRT again
- PIN digits are rendered large and readable on the Tracker 160x80 TFT
"""
from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected one anchor, got {count}")
    return text.replace(old, new, 1)


# ---------------------------------------------------------------------------
# TrackerCommonPolicy: make PIN entry an explicit UI mode.
# ---------------------------------------------------------------------------
COMMON = Path("src/vehicle/TrackerCommonPolicy.cpp")
common = COMMON.read_text(encoding="utf-8")

if "JARNSEN_TRACKER_COMMON_FULL_LOCK_PIN_V5" not in common:
    state_anchor = "uint32_t lastSecurityBannerMs = 0;\n"
    state_replacement = state_anchor + "bool fullLockPinUiActive = false; // JARNSEN_TRACKER_COMMON_FULL_LOCK_PIN_V5\n"
    common = replace_once(common, state_anchor, state_replacement, "common PIN UI state")

    old_banner = r'''void showSecurityBanner(bool wakeScreen)
{
    if (!screen || !bootHandoffComplete)
        return;
    const uint32_t now = millis();
    char banner[72] = {};
    if (pinBlockedUntilMs != 0 && (int32_t)(pinBlockedUntilMs - now) > 0) {
        const uint32_t seconds = ((pinBlockedUntilMs - now) + 999U) / 1000U;
        snprintf(banner, sizeof(banner), "NODE GESPERRT\nPIN FALSCH - %us", (unsigned)seconds);
    } else {
        snprintf(banner, sizeof(banner), "NODE GESPERRT\nPIN %u/6  ZIFFER %u", (unsigned)(pinIndex + 1U),
                 (unsigned)pinDigit);
    }
    if (wakeScreen && !screen->isScreenOn())
        screen->setOn(true);
    screen->showSimpleBanner(banner, 5000U);
    lastSecurityBannerMs = now ? now : 1;
}
'''
    new_banner = r'''void showSecurityBanner(bool wakeScreen)
{
    if (!screen || !bootHandoffComplete)
        return;
    const uint32_t now = millis();
    // Full Lock display content is rendered centrally by Screen.cpp. Keep this
    // helper as the existing security refresh point, but do not install the old
    // small Meshtastic banner underneath the lock renderer.
    if (wakeScreen && !screen->isScreenOn())
        screen->setOn(true);
    screen->runNow();
    lastSecurityBannerMs = now ? now : 1;
}
'''
    common = replace_once(common, old_banner, new_banner, "common security banner ownership")

    common = replace_once(
        common,
        "    resetPinEntry();\n    pinBlockedUntilMs = 0;\n    resetLockSequence();\n",
        "    resetPinEntry();\n    fullLockPinUiActive = false;\n    pinBlockedUntilMs = 0;\n    resetLockSequence();\n",
        "enter Full Lock resets visible PIN UI",
    )

    common = replace_once(
        common,
        "    pinBlockedUntilMs = 0;\n    trackerDiagLog(\"SECURITY\", \"UNLOCKED\");\n",
        "    pinBlockedUntilMs = 0;\n    fullLockPinUiActive = false;\n    trackerDiagLog(\"SECURITY\", \"UNLOCKED\");\n",
        "successful unlock leaves PIN UI",
    )

    common = replace_once(
        common,
        "void closeDisplay()\n{\n    displayVisible = false;\n",
        "void closeDisplay()\n{\n    fullLockPinUiActive = false;\n    displayVisible = false;\n",
        "display timeout leaves PIN UI",
    )

    # Only redraw the PIN page periodically while PIN entry is actually active.
    old_periodic = r'''        if (jarnsen::serviceSecurityLocked() && serviceActive && displayVisible && screen && screen->isScreenOn() &&
            (lastSecurityBannerMs == 0 || (uint32_t)(now - lastSecurityBannerMs) >= 4000U))
            showSecurityBanner(false);
'''
    new_periodic = r'''        if (!jarnsen::serviceSecurityLocked())
            fullLockPinUiActive = false;
        if (jarnsen::serviceSecurityLocked() && fullLockPinUiActive && serviceActive && displayVisible && screen &&
            screen->isScreenOn() && (lastSecurityBannerMs == 0 || (uint32_t)(now - lastSecurityBannerMs) >= 1000U))
            showSecurityBanner(false);
'''
    common = replace_once(common, old_periodic, new_periodic, "common active PIN refresh")

    # Capture whether NODE GESPERRT was already visible before this physical
    # press resets the 20 second display deadline. On that second press, enter
    # PIN UI and consume the opening press completely.
    old_press_start = r'''            if (!buttonWasPressed) {
                buttonWasPressed = true;
                buttonPressedSinceMs = now ? now : 1;
                openedServiceThisPress = false;
                buttonLongHandled = false;
                lockGestureHandled = false;
                lockCountdownLast = 0;
                if (serviceActive) {
                    serviceLastActivityMs = now;
                    resetDisplayWindow(now);
                }
                if (!serviceActive) {
                    startService();
                    openedServiceThisPress = true;
                } else {
                    serviceLastActivityMs = now;
                    if (!displayWindowActive() || (screen && !screen->isScreenOn())) {
                        showTrackerScreen();
                        openedServiceThisPress = true;
                    }
                }
            }
'''
    new_press_start = r'''            if (!buttonWasPressed) {
                const bool lockedNow = jarnsen::serviceSecurityLocked();
                const bool lockScreenWasVisible = lockedNow && !fullLockPinUiActive && serviceActive && displayWindowActive() &&
                                                   screen && screen->isScreenOn();
                buttonWasPressed = true;
                buttonPressedSinceMs = now ? now : 1;
                openedServiceThisPress = false;
                buttonLongHandled = false;
                lockGestureHandled = false;
                lockCountdownLast = 0;
                if (serviceActive) {
                    serviceLastActivityMs = now;
                    resetDisplayWindow(now);
                }
                if (!serviceActive) {
                    startService();
                    openedServiceThisPress = true;
                } else {
                    serviceLastActivityMs = now;
                    if (!displayWindowActive() || (screen && !screen->isScreenOn())) {
                        // First press from display-off is wake-only. showTrackerScreen()
                        // returns to NODE GESPERRT while locked.
                        fullLockPinUiActive = false;
                        showTrackerScreen();
                        openedServiceThisPress = true;
                    }
                }
                if (lockScreenWasVisible && screen) {
                    // Second press while NODE GESPERRT is already visible enters
                    // PIN mode. Consume this physical press so it does not also
                    // increment or confirm a digit.
                    fullLockPinUiActive = true;
                    resetPinEntry();
                    pinBlockedUntilMs = 0;
                    openedServiceThisPress = true;
                    buttonLongHandled = true;
                    lastSecurityBannerMs = now ? now : 1;
                    screen->runNow();
                    trackerDiagLog("SECURITY", "PIN_UI_OPEN");
                    LOG_INFO("Tracker Full Lock: second GPIO0 press opened large PIN UI");
                }
            }
'''
    common = replace_once(common, old_press_start, new_press_start, "common two-stage lock press")

    common = replace_once(
        common,
        "                    if (jarnsen::serviceSecurityLocked())\n                        confirmPinDigit();\n",
        "                    if (jarnsen::serviceSecurityLocked() && fullLockPinUiActive)\n                        confirmPinDigit();\n",
        "common long press only confirms visible PIN",
    )

    common = replace_once(
        common,
        "                        if (jarnsen::serviceSecurityLocked())\n                            nextPinDigit();\n",
        "                        if (jarnsen::serviceSecurityLocked() && fullLockPinUiActive)\n                            nextPinDigit();\n",
        "common short press only increments visible PIN",
    )

    # Export a tiny read-only view for the central Full-Lock renderer.
    export_anchor = r'''bool trackerCommonScreenPowerAllowed(bool on)
{
'''
    exports = r'''bool trackerCommonFullLockPinUiActive()
{
    return trackerRoleEnabled() && jarnsen::serviceSecurityLocked() && fullLockPinUiActive;
}

uint8_t trackerCommonFullLockPinIndex()
{
    return pinIndex < 6U ? pinIndex : 5U;
}

uint8_t trackerCommonFullLockPinValue(uint8_t index)
{
    if (index >= 6U)
        return 0U;
    if (index < pinIndex)
        return pinDigits[index];
    if (index == pinIndex)
        return pinDigit;
    return 0U;
}

uint32_t trackerCommonFullLockPinBlockedRemainingMs()
{
    const uint32_t now = millis();
    if (pinBlockedUntilMs == 0 || (int32_t)(pinBlockedUntilMs - now) <= 0)
        return 0U;
    return pinBlockedUntilMs - now;
}

'''
    common = replace_once(common, export_anchor, exports + export_anchor, "common PIN renderer exports")

COMMON.write_text(common, encoding="utf-8")


# Public declarations for Screen.cpp.
COMMON_H = Path("src/vehicle/TrackerCommonPolicy.h")
common_h = COMMON_H.read_text(encoding="utf-8")
if "trackerCommonFullLockPinUiActive" not in common_h:
    common_h += "\n// Read-only Full-Lock PIN UI state consumed by the Tracker display renderer.\n"
    common_h += "bool trackerCommonFullLockPinUiActive();\n"
    common_h += "uint8_t trackerCommonFullLockPinIndex();\n"
    common_h += "uint8_t trackerCommonFullLockPinValue(uint8_t index);\n"
    common_h += "uint32_t trackerCommonFullLockPinBlockedRemainingMs();\n"
COMMON_H.write_text(common_h, encoding="utf-8")


# ---------------------------------------------------------------------------
# Screen: render TrackerCommonPolicy's existing PIN state as large digits.
# ---------------------------------------------------------------------------
SCREEN = Path("src/graphics/Screen.cpp")
screen = SCREEN.read_text(encoding="utf-8")

if "JARNSEN_TRACKER_COMMON_PIN_RENDER_V5" not in screen:
    include_anchor = '#include "jarnsen/core/service/JarnsenServiceSecurity.h"\n'
    include_replacement = (
        include_anchor
        + '#include "vehicle/TrackerCommonPolicy.h"\n'
        + '#include "jarnsen/core/display/JarnsenPinRenderer.h"\n'
    )
    screen = replace_once(screen, include_anchor, include_replacement, "Screen common policy include")

    helper_anchor = "// Weak UI notification emitted by JarnsenServiceSecurity.  The security core\n"
    helper = r'''// JARNSEN_TRACKER_COMMON_PIN_RENDER_V5
static void drawJarnsenTrackerCommonPinScreen(OLEDDisplay *display)
{
    if (!display)
        return;

    uint8_t values[6] = {};
    for (uint8_t digit = 0; digit < 6U; ++digit)
        values[digit] = trackerCommonFullLockPinValue(digit);

    jarnsen::drawReferenceSixDigitPin(display, 0, 0, values, trackerCommonFullLockPinIndex(),
                                     trackerCommonFullLockPinBlockedRemainingMs(), "PIN EINGABE");
}

'''
    screen = replace_once(screen, helper_anchor, helper + helper_anchor, "Screen common PIN renderer helper")

    old_gate = r'''    if (jarnsen::serviceSecurityLocked() && screen != nullptr) {
        OLEDDisplay *display = screen->getDisplayDevice();
        if (jarnsenFullLockPinPickerActive()) {
            display->clear();
            NotificationRenderer::drawBannercallback(display, ui->getUiState());
        } else {
            if (NotificationRenderer::isOverlayBannerShowing())
                NotificationRenderer::resetBanner();
            drawJarnsenFullLockScreenIntoBuffer(display);
        }
        display->display();
        return;
    }
'''
    new_gate = r'''    if (jarnsen::serviceSecurityLocked() && screen != nullptr) {
        OLEDDisplay *display = screen->getDisplayDevice();
        if (trackerCommonFullLockPinUiActive()) {
            if (NotificationRenderer::isOverlayBannerShowing())
                NotificationRenderer::resetBanner();
            drawJarnsenTrackerCommonPinScreen(display);
        } else if (jarnsenFullLockPinPickerActive()) {
            display->clear();
            NotificationRenderer::drawBannercallback(display, ui->getUiState());
        } else {
            if (NotificationRenderer::isOverlayBannerShowing())
                NotificationRenderer::resetBanner();
            drawJarnsenFullLockScreenIntoBuffer(display);
        }
        display->display();
        return;
    }
'''
    screen = replace_once(screen, old_gate, new_gate, "Screen Full Lock common PIN gate")

SCREEN.write_text(screen, encoding="utf-8")


for path, markers in (
    (COMMON, ("JARNSEN_TRACKER_COMMON_FULL_LOCK_PIN_V5", "PIN_UI_OPEN", "fullLockPinUiActive")),
    (COMMON_H, ("trackerCommonFullLockPinUiActive", "trackerCommonFullLockPinValue")),
    (SCREEN, ("JARNSEN_TRACKER_COMMON_PIN_RENDER_V5", "drawJarnsenTrackerCommonPinScreen")),
):
    content = path.read_text(encoding="utf-8")
    for marker in markers:
        if marker not in content:
            raise SystemExit(f"Tracker Common Full Lock v5 validation failed in {path}: {marker}")

print("Tracker V1.1 active Common Full Lock PIN UI v5 applied")
