"""Harden Tracker V1.1 Full-Lock GPIO0 and display timing.

Desired operator flow:
- Full Lock shows NODE / GESPERRT for the normal 20 second display window.
- After 20 seconds the TFT turns off.
- First GPIO0 press while the TFT is off wakes only NODE / GESPERRT.
- The next press while that lock screen is visible opens the six-digit PIN UI.
- In PIN UI: short press increments the selected digit, long press confirms it.

The TAK role owns GPIO0 and the Tracker TFT directly, so this post-transform
adds explicit wake/PIN commands to Screen's queue and makes the TAK policy use
the same 20 second window without mutating UI state from the GPIO worker.
"""
from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected one anchor, got {count}")
    return text.replace(old, new, 1)


TAK = Path("src/vehicle/HeltecTrackerV11TakLeaderPolicy.cpp")
tak = TAK.read_text(encoding="utf-8")
if "JARNSEN_TRACKER_TAK_FULL_LOCK_BUTTON" not in tak:
    print("Tracker Full Lock TAK transform not present; follow-up skipped")
    raise SystemExit(0)
if "JARNSEN_TRACKER_TAK_LOCK_WAKE_V4" in tak:
    print("Tracker Full Lock 20s wake / second-press PIN policy already applied")
    raise SystemExit(0)

# ---------------------------------------------------------------------------
# Screen command queue: wake-only and open-PIN are separate commands.
# ---------------------------------------------------------------------------
COMMANDS = Path("src/commands.h")
commands = COMMANDS.read_text(encoding="utf-8")
if "JARNSEN_FULL_LOCK_WAKE_REQUEST" not in commands:
    commands = replace_once(
        commands,
        "    NOOP\n};",
        "    NOOP,\n    JARNSEN_FULL_LOCK_WAKE_REQUEST,\n    JARNSEN_FULL_LOCK_PIN_REQUEST\n};",
        "Screen Full Lock command enum",
    )
COMMANDS.write_text(commands, encoding="utf-8")

SCREEN_H = Path("src/graphics/Screen.h")
screen_h = SCREEN_H.read_text(encoding="utf-8")
if "requestJarnsenFullLockWake" not in screen_h:
    anchor = "    void showNumberPicker(const char *message, uint32_t durationMs, uint8_t digits, bool useBase16,\n                          std::function<void(uint32_t)> bannerCallback);\n"
    replacement = anchor + "#if defined(HELTEC_TRACKER_V1_1)\n    // Thread-safe requests used by the TAK GPIO0 worker while Full Lock is active.\n    void requestJarnsenFullLockWake();\n    void requestJarnsenFullLockPin();\n#endif\n"
    screen_h = replace_once(screen_h, anchor, replacement, "Screen Full Lock queue declarations")
SCREEN_H.write_text(screen_h, encoding="utf-8")

SCREEN_CPP = Path("src/graphics/Screen.cpp")
screen = SCREEN_CPP.read_text(encoding="utf-8")

# The first Full-Lock transform kept the display forced on. Remove those two
# guards so normal/TAK timeout policy can actually power the TFT down.
forced_set_on = r'''#if defined(HELTEC_TRACKER_V1_1)
    // Full Lock is an operator-visible state: idle display timeout must not
    // blank the lock screen.
    if (!on && jarnsen::serviceSecurityLocked())
        on = true;
#endif
'''
if forced_set_on in screen:
    screen = screen.replace(forced_set_on, "", 1)

forced_handle_on = r'''#if defined(HELTEC_TRACKER_V1_1)
    if (!on && jarnsen::serviceSecurityLocked())
        on = true;
#endif
'''
if forced_handle_on in screen:
    screen = screen.replace(forced_handle_on, "", 1)

if "JARNSEN_FULL_LOCK_WAKE_QUEUE_HANDLER" not in screen:
    function_anchor = "// Called to trigger an arcade-style initials picker (see showNumberPicker for\n"
    producers = r'''#if defined(HELTEC_TRACKER_V1_1)
void Screen::requestJarnsenFullLockWake()
{
    ScreenCmd cmd{};
    cmd.cmd = Cmd::JARNSEN_FULL_LOCK_WAKE_REQUEST;
    enqueueCmd(cmd);
}

void Screen::requestJarnsenFullLockPin()
{
    ScreenCmd cmd{};
    cmd.cmd = Cmd::JARNSEN_FULL_LOCK_PIN_REQUEST;
    enqueueCmd(cmd);
}
#endif

'''
    screen = replace_once(screen, function_anchor, producers + function_anchor, "Screen Full Lock queue producers")

    switch_anchor = "        case Cmd::NOOP:\n            break;\n"
    switch_replacement = r'''        case Cmd::JARNSEN_FULL_LOCK_WAKE_REQUEST:
#if defined(HELTEC_TRACKER_V1_1)
            // JARNSEN_FULL_LOCK_WAKE_QUEUE_HANDLER: wake-only always returns to
            // a fresh NODE GESPERRT frame. A stale PIN entry never survives an
            // off -> on cycle.
            if (jarnsen::serviceSecurityLocked()) {
                if (NotificationRenderer::isOverlayBannerShowing())
                    NotificationRenderer::resetBanner();
                handleSetOn(true);
                setFastFramerate();
            }
#endif
            break;
        case Cmd::JARNSEN_FULL_LOCK_PIN_REQUEST:
#if defined(HELTEC_TRACKER_V1_1)
            if (jarnsen::serviceSecurityLocked() && !jarnsenFullLockPinPickerActive()) {
                if (NotificationRenderer::isOverlayBannerShowing())
                    NotificationRenderer::resetBanner();
                showNumberPicker("PIN", 0, 6, false, [](uint32_t pin) {
                    (void)jarnsen::serviceSecurityUnlock(pin);
                    if (screen)
                        screen->runNow();
                });
                LOG_INFO("Full Lock: local PIN entry opened on second GPIO0 press");
            }
#endif
            break;
        case Cmd::NOOP:
            break;
'''
    screen = replace_once(screen, switch_anchor, switch_replacement, "Screen Full Lock queue consumers")

SCREEN_CPP.write_text(screen, encoding="utf-8")

# ---------------------------------------------------------------------------
# TAK display ownership: while locked, ON is always allowed, but OFF is blocked
# only for the active 20 second window. This replaces the old permanent-on rule.
# ---------------------------------------------------------------------------
old_wants = r'''static bool takLeaderWantsScreenOn()
{
    if (jarnsen::serviceSecurityLocked())
        return true;
    if (!leaderServiceActive || leaderDisplayStartedMs == 0)
'''
new_wants = r'''static bool takLeaderWantsScreenOn()
{
    if (!leaderServiceActive || leaderDisplayStartedMs == 0)
'''
tak = replace_once(tak, old_wants, new_wants, "TAK remove permanent locked-screen ownership")

old_power_gate = r'''bool takLeaderScreenPowerAllowed(bool on)
{
    if (!takLeaderEnabled() || !leaderBootHandoffComplete)
        return true;
    return on == takLeaderWantsScreenOn();
}
'''
new_power_gate = r'''bool takLeaderScreenPowerAllowed(bool on)
{
    if (!takLeaderEnabled() || !leaderBootHandoffComplete)
        return true;
    if (jarnsen::serviceSecurityLocked()) {
        const uint32_t current = millis();
        const bool lockWindowActive = leaderDisplayStartedMs != 0 &&
                                      (uint32_t)(current - leaderDisplayStartedMs) < leaderDisplayWindowMs;
        // Wake requests are always allowed. Power-off is allowed only after the
        // normal 20 second lock-screen window expires.
        return on || !lockWindowActive;
    }
    return on == takLeaderWantsScreenOn();
}
'''
tak = replace_once(tak, old_power_gate, new_power_gate, "TAK locked screen power gate")

# Track lock transitions so locking while the tracker is already awake starts a
# fresh 20 second window even if no GPIO press occurs.
state_anchor = "static bool leaderServiceFrameActive = false;\n"
if "leaderFullLockWasActive" not in tak:
    tak = replace_once(
        tak,
        state_anchor,
        state_anchor + "static bool leaderFullLockWasActive = false;\n",
        "TAK Full Lock transition state",
    )

# Do not let the normal TAK boot handoff blank a currently locked display.
boot_anchor = r'''            if (leaderServiceActive)
                renderTakLeaderServicePage();
            else if (screen && screen->isScreenOn())
                setTakLeaderScreenPower(false);
        }

        processTakLeaderMotion(now);
'''
boot_replacement = r'''            if (jarnsen::serviceSecurityLocked()) {
                // The lock transition block below owns wake/timing.
            } else if (leaderServiceActive) {
                renderTakLeaderServicePage();
            } else if (screen && screen->isScreenOn()) {
                setTakLeaderScreenPower(false);
            }
        }

        const bool fullLockActive = jarnsen::serviceSecurityLocked();
        if (fullLockActive != leaderFullLockWasActive) {
            leaderFullLockWasActive = fullLockActive;
            leaderButtonLatched = false;
            leaderOpenedServiceThisPress = false;
            leaderLongPressHandled = false;
            leaderButtonLowSinceMs = 0;
            leaderButtonHighSinceMs = 0;
            if (fullLockActive && leaderBootHandoffComplete && screen) {
                leaderDisplayStartedMs = now ? now : 1;
                leaderDisplayWindowMs = TAK_LEADER_DISPLAY_MS;
                screen->requestJarnsenFullLockWake();
                LOG_INFO("TAK Full Lock: NODE GESPERRT display window started (%us)",
                         (unsigned)(TAK_LEADER_DISPLAY_MS / 1000UL));
            }
        }

        processTakLeaderMotion(now);
'''
tak = replace_once(tak, boot_anchor, boot_replacement, "TAK Full Lock transition/wake")

# Replace the first-press behavior. If the screen/window was inactive, the press
# only wakes NODE GESPERRT. Only a subsequent press opens PIN. Every press starts
# a fresh 20 second window, matching the rest of the JARNSEN UI.
old_latch = r'''                    if (!leaderButtonLatched) {
                        leaderButtonLatched = true;
                        leaderButtonLowSinceMs = now ? now : 1;
                        leaderOpenedServiceThisPress = false;
                        leaderLongPressHandled = false;
                        if (!pinActive && screen) {
                            screen->showNumberPicker("PIN", 0, 6, false, [](uint32_t pin) {
                                (void)jarnsen::serviceSecurityUnlock(pin);
                                if (screen)
                                    screen->runNow();
                            });
                            leaderOpenedServiceThisPress = true;
                        }
                    }
'''
new_latch = r'''                    if (!leaderButtonLatched) {
                        // JARNSEN_TRACKER_TAK_LOCK_WAKE_V4
                        const bool displayWasActive = screen && screen->isScreenOn() && leaderDisplayStartedMs != 0 &&
                                                      (uint32_t)(now - leaderDisplayStartedMs) < leaderDisplayWindowMs;
                        leaderButtonLatched = true;
                        leaderButtonLowSinceMs = now ? now : 1;
                        leaderOpenedServiceThisPress = false;
                        leaderLongPressHandled = false;
                        leaderDisplayStartedMs = now ? now : 1;
                        leaderDisplayWindowMs = TAK_LEADER_DISPLAY_MS;

                        if (!displayWasActive && screen) {
                            // First press from display-off is wake-only.
                            screen->requestJarnsenFullLockWake();
                            leaderOpenedServiceThisPress = true;
                            LOG_DEBUG("TAK Full Lock: GPIO0 wake-only press");
                        } else if (!pinActive && screen) {
                            // Only the next press while NODE GESPERRT is visible
                            // opens the PIN entry.
                            screen->requestJarnsenFullLockPin();
                            leaderOpenedServiceThisPress = true;
                        }
                    }
'''
tak = replace_once(tak, old_latch, new_latch, "TAK Full Lock two-stage button flow")

# While locked, Full Lock owns only the display content/timer. Do not let the
# normal TAK service page force the panel off before the 20 second window ends.
service_anchor = r'''        if (leaderServiceActive) {
            if (!takLeaderServiceStillActive(now)) {
'''
service_replacement = r'''        if (fullLockActive) {
            if (leaderBootHandoffComplete && screen && !takLeaderDisplayWindowActive(now) && screen->isScreenOn()) {
                setTakLeaderScreenPower(false);
                LOG_DEBUG("TAK Full Lock: 20s display window expired -> TFT off");
            }
        } else if (leaderServiceActive) {
            if (!takLeaderServiceStillActive(now)) {
'''
tak = replace_once(tak, service_anchor, service_replacement, "TAK Full Lock display timeout ownership")

TAK.write_text(tak, encoding="utf-8")

for path, markers in (
    (COMMANDS, ("JARNSEN_FULL_LOCK_WAKE_REQUEST", "JARNSEN_FULL_LOCK_PIN_REQUEST")),
    (SCREEN_H, ("requestJarnsenFullLockWake", "requestJarnsenFullLockPin")),
    (SCREEN_CPP, ("JARNSEN_FULL_LOCK_WAKE_QUEUE_HANDLER", "second GPIO0 press")),
    (TAK, ("JARNSEN_TRACKER_TAK_LOCK_WAKE_V4", "20s display window expired")),
):
    content = path.read_text(encoding="utf-8")
    for marker in markers:
        if marker not in content:
            raise SystemExit(f"Full Lock 20s/two-stage validation failed in {path}: {marker}")

print("Tracker V1.1 Full Lock: 20s display, wake-only first press, PIN second press applied")
