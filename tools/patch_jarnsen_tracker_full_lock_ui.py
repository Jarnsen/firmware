"""Apply the Tracker V1.1 Full-Lock operator UI to the Unified Core build tree.

Scope is intentionally Tracker V1.1 only:
- Full Lock owns the whole display and renders NODE / GESPERRT.
- Userbutton opens the existing six-digit JARNSEN PIN picker.
- Short press increments the selected digit, long press confirms/advances.
- The PIN is rendered as large seven-segment digits.
- Existing serviceSecurityLock/serviceSecurityUnlock state, persistence and mesh
  alerts are not reimplemented here.

The Unified Core build already uses deterministic source transforms for migrated
JARNSEN seams.  This transform is idempotent because build retries can execute it
more than once in the same checkout.
"""
from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected one anchor, got {count}")
    return text.replace(old, new, 1)


# ---------------------------------------------------------------------------
# Screen: Full Lock has absolute display ownership on Tracker V1.1.
# ---------------------------------------------------------------------------
SCREEN = Path("src/graphics/Screen.cpp")
screen = SCREEN.read_text(encoding="utf-8")

if "JARNSEN_TRACKER_FULL_LOCK_UI" not in screen:
    include_anchor = '#include "jarnsen/adapters/JarnsenDisplayRuntime.h"\n'
    include_replacement = include_anchor + '''#if defined(HELTEC_TRACKER_V1_1)\n#include "jarnsen/core/service/JarnsenServiceSecurity.h"\n#endif\n'''
    screen = replace_once(screen, include_anchor, include_replacement, "Screen security include")

    update_anchor = "static inline void updateUiFrame(OLEDDisplayUi *ui)\n{\n"
    helper = r'''#if defined(HELTEC_TRACKER_V1_1)
// JARNSEN_TRACKER_FULL_LOCK_UI
static bool jarnsenFullLockPinPickerActive()
{
    return NotificationRenderer::current_notification_type == notificationTypeEnum::number_picker &&
           NotificationRenderer::numDigits == 6U && strcmp(NotificationRenderer::alertBannerMessage, "PIN") == 0;
}

static void drawJarnsenFullLockScreenIntoBuffer(OLEDDisplay *display)
{
    if (!display)
        return;
    display->clear();
    const int w = display->getWidth();
    const int h = display->getHeight();
    display->setTextAlignment(TEXT_ALIGN_CENTER);
    display->setFont(FONT_LARGE);
    const int totalHeight = (2 * FONT_HEIGHT_LARGE) + 4;
    const int top = std::max(0, (h - totalHeight) / 2);
    display->drawString(w / 2, top, "NODE");
    display->drawString(w / 2, top + FONT_HEIGHT_LARGE + 4, "GESPERRT");
}

// Weak UI notification emitted by JarnsenServiceSecurity.  The security core
// remains display-agnostic; Tracker V1.1 uses the hook only to wake/redraw.
extern "C" void jarnsenFullLockUiStateChanged(bool locked)
{
    if (!screen)
        return;
    if (locked && !screen->isScreenOn())
        screen->setOn(true);
    screen->runNow();
}
#endif

'''
    screen = replace_once(screen, update_anchor, helper + update_anchor, "Screen Full Lock helper")

    update_body_anchor = "static inline void updateUiFrame(OLEDDisplayUi *ui)\n{\n"
    update_body_replacement = update_body_anchor + r'''#if defined(HELTEC_TRACKER_V1_1)
    if (jarnsen::serviceSecurityLocked() && screen != nullptr) {
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
#endif
'''
    screen = replace_once(screen, update_body_anchor, update_body_replacement, "Screen Full Lock render gate")

    set_on_anchor = "void Screen::setOn(bool on, FrameCallback einkScreensaver)\n{\n"
    set_on_replacement = set_on_anchor + r'''#if defined(HELTEC_TRACKER_V1_1)
    // Full Lock is an operator-visible state: idle display timeout must not
    // blank the lock screen.
    if (!on && jarnsen::serviceSecurityLocked())
        on = true;
#endif
'''
    screen = replace_once(screen, set_on_anchor, set_on_replacement, "Screen setOn Full Lock guard")

    handle_set_on_anchor = "void Screen::handleSetOn(bool on, FrameCallback einkScreensaver)\n{\n"
    handle_set_on_replacement = handle_set_on_anchor + r'''#if defined(HELTEC_TRACKER_V1_1)
    if (!on && jarnsen::serviceSecurityLocked())
        on = true;
#endif
'''
    screen = replace_once(screen, handle_set_on_anchor, handle_set_on_replacement, "Screen handleSetOn Full Lock guard")

    input_anchor = '''    if (!screenOn && !jarnsenLiveIsActive())\n        return 0;\n\n'''
    input_replacement = input_anchor + r'''#if defined(HELTEC_TRACKER_V1_1)
    // While Full Lock is active, no normal page/menu input is allowed through.
    // The physical Userbutton is the only entry into the local PIN prompt.
    if (jarnsen::serviceSecurityLocked() && !jarnsenFullLockPinPickerActive()) {
        if (NotificationRenderer::isOverlayBannerShowing())
            NotificationRenderer::resetBanner();

        const bool userButton = event->source && strcmp(event->source, "UserButton") == 0;
        if (userButton) {
            showNumberPicker("PIN", 0, 6, false, [](uint32_t pin) {
                (void)jarnsen::serviceSecurityUnlock(pin);
                if (screen)
                    screen->runNow();
            });
        } else {
            setFastFramerate();
            updateUiFrame(ui);
        }
        return 0;
    }
#endif

'''
    screen = replace_once(screen, input_anchor, input_replacement, "Screen Full Lock input gate")

for marker in (
    "JARNSEN_TRACKER_FULL_LOCK_UI",
    'display->drawString(w / 2, top, "NODE");',
    'display->drawString(w / 2, top + FONT_HEIGHT_LARGE + 4, "GESPERRT");',
    'showNumberPicker("PIN", 0, 6, false',
    "jarnsen::serviceSecurityUnlock(pin)",
):
    if marker not in screen:
        raise SystemExit(f"Screen Full Lock validation failed: {marker}")
SCREEN.write_text(screen, encoding="utf-8")


# ---------------------------------------------------------------------------
# Number picker: use most of the Tracker TFT for six readable PIN digits.
# ---------------------------------------------------------------------------
NOTIFY = Path("src/graphics/draw/NotificationRenderer.cpp")
notify = NOTIFY.read_text(encoding="utf-8")

if "JARNSEN_TRACKER_LARGE_PIN" not in notify:
    function_start = notify.find("void NotificationRenderer::drawNumberPicker(")
    function_end = notify.find("\nvoid NotificationRenderer::drawHexPicker(", function_start)
    if function_start < 0 or function_end < 0:
        raise SystemExit("drawNumberPicker boundaries not found")
    number_picker = notify[function_start:function_end]
    anchor = '''    if (alertBannerMessage[0] == '\\0')\n        return;\n\n    uint16_t totalLines = lineCount + 2;\n'''
    replacement = r'''    if (alertBannerMessage[0] == '\0')
        return;

#if defined(HELTEC_TRACKER_V1_1)
    // JARNSEN_TRACKER_LARGE_PIN: full-width local PIN entry for the 160x80
    // Tracker V1.1 TFT. Other number pickers and all other boards stay stock.
    if (numDigits == 6U && strcmp(alertBannerMessage, "PIN") == 0) {
        display->clear();
        const int16_t screenW = display->getWidth();
        const int16_t screenH = display->getHeight();
        const int16_t digitW = screenW >= 150 ? 20 : 16;
        const int16_t digitH = screenH >= 72 ? 42 : 30;
        const int16_t thickness = screenW >= 150 ? 4 : 3;
        const int16_t gap = 2;
        const int16_t groupGap = screenW >= 150 ? 6 : 4;
        const int16_t totalW = 6 * digitW + 5 * gap + groupGap;
        const int16_t top = screenH >= 72 ? 28 : 21;
        int16_t left = (screenW - totalW) / 2;

        display->setTextAlignment(TEXT_ALIGN_CENTER);
        display->setFont(FONT_SMALL);
        display->drawString(screenW / 2, 1, "PIN EINGABE");

        auto drawSegmentDigit = [display, digitW, digitH, thickness](uint8_t value, int16_t x0, int16_t y0) {
            static const uint8_t masks[10] = {0x3f, 0x06, 0x5b, 0x4f, 0x66, 0x6d, 0x7d, 0x07, 0x7f, 0x6f};
            if (value > 9U)
                return;
            const uint8_t mask = masks[value];
            const int16_t half = digitH / 2;
            auto segment = [display](int16_t sx, int16_t sy, int16_t sw, int16_t sh) { display->fillRect(sx, sy, sw, sh); };
            if (mask & 0x01) segment(x0 + thickness, y0, digitW - 2 * thickness, thickness);
            if (mask & 0x02) segment(x0 + digitW - thickness, y0 + thickness, thickness, half - thickness);
            if (mask & 0x04) segment(x0 + digitW - thickness, y0 + half, thickness, half - thickness);
            if (mask & 0x08) segment(x0 + thickness, y0 + digitH - thickness, digitW - 2 * thickness, thickness);
            if (mask & 0x10) segment(x0, y0 + half, thickness, half - thickness);
            if (mask & 0x20) segment(x0, y0 + thickness, thickness, half - thickness);
            if (mask & 0x40) segment(x0 + thickness, y0 + half - thickness / 2, digitW - 2 * thickness, thickness);
        };

        for (uint8_t digit = 0; digit < 6U; ++digit) {
            const uint8_t value = (currentNumber % pow_of_10(6U - digit)) / pow_of_10(5U - digit);
            drawSegmentDigit(value, left, top);
            if (curSelected == static_cast<int8_t>(digit)) {
                display->drawRect(left - 2, top - 2, digitW + 4, digitH + 4);
                display->setFont(FONT_SMALL);
                display->drawString(left + digitW / 2, screenH - FONT_HEIGHT_SMALL + 2, "^");
            }
            left += digitW;
            if (digit != 5U)
                left += gap;
            if (digit == 2U)
                left += groupGap;
        }
        return;
    }
#endif

    uint16_t totalLines = lineCount + 2;
'''
    count = number_picker.count(anchor)
    if count != 1:
        raise SystemExit(f"large PIN anchor expected once in drawNumberPicker, got {count}")
    number_picker = number_picker.replace(anchor, replacement, 1)
    notify = notify[:function_start] + number_picker + notify[function_end:]

for marker in (
    "JARNSEN_TRACKER_LARGE_PIN",
    'strcmp(alertBannerMessage, "PIN") == 0',
    'display->drawString(screenW / 2, 1, "PIN EINGABE");',
):
    if marker not in notify:
        raise SystemExit(f"large PIN validation failed: {marker}")
NOTIFY.write_text(notify, encoding="utf-8")


# ---------------------------------------------------------------------------
# Generic Tracker Userbutton: short increments digit, long confirms/advances.
# ---------------------------------------------------------------------------
BUTTON = Path("src/input/ButtonThread.cpp")
button = BUTTON.read_text(encoding="utf-8")

if "JARNSEN_TRACKER_LOCK_BUTTON" not in button:
    include_anchor = '#include "jarnsen/core/runtime/JarnsenRuntimePolicy.h"\n'
    include_replacement = include_anchor + '''#if defined(HELTEC_TRACKER_V1_1)\n#include "jarnsen/core/service/JarnsenServiceSecurity.h"\n#endif\n'''
    button = replace_once(button, include_anchor, include_replacement, "Button security include")

    short_anchor = '''            evt.inputEvent = _singlePress;\n'''
    short_replacement = r'''#if defined(HELTEC_TRACKER_V1_1)
            // JARNSEN_TRACKER_LOCK_BUTTON: while locked, short physical presses
            // increment the selected PIN digit instead of navigating pages.
            if (jarnsen::serviceSecurityLocked() && isJarnsenUserButton(_originName))
                evt.inputEvent = INPUT_BROKER_UP;
            else
#endif
                evt.inputEvent = _singlePress;
'''
    button = replace_once(button, short_anchor, short_replacement, "Button locked short press")

    long_anchor = '''                evt.inputEvent = _longPress;\n                this->notifyObservers(&evt);\n'''
    long_replacement = r'''#if defined(HELTEC_TRACKER_V1_1)
                if (jarnsen::serviceSecurityLocked() && isJarnsenUserButton(_originName))
                    evt.inputEvent = INPUT_BROKER_SELECT;
                else
#endif
                    evt.inputEvent = _longPress;
                this->notifyObservers(&evt);
'''
    button = replace_once(button, long_anchor, long_replacement, "Button locked long press")

for marker in (
    "JARNSEN_TRACKER_LOCK_BUTTON",
    "evt.inputEvent = INPUT_BROKER_UP;",
    "evt.inputEvent = INPUT_BROKER_SELECT;",
):
    if marker not in button:
        raise SystemExit(f"Button Full Lock validation failed: {marker}")
BUTTON.write_text(button, encoding="utf-8")


# ---------------------------------------------------------------------------
# Tracker TAK role: it owns GPIO0 directly and disables ButtonThread, so mirror
# the same short/long PIN controls without changing its normal unlocked policy.
# ---------------------------------------------------------------------------
TAK = Path("src/vehicle/HeltecTrackerV11TakLeaderPolicy.cpp")
tak = TAK.read_text(encoding="utf-8")

if "JARNSEN_TRACKER_TAK_FULL_LOCK_BUTTON" not in tak:
    include_anchor = '#include "jarnsen/core/status/JarnsenStatusProvider.h"\n'
    include_replacement = include_anchor + '#include "jarnsen/core/service/JarnsenServiceSecurity.h"\n'
    tak = replace_once(tak, include_anchor, include_replacement, "TAK security include")

    wants_anchor = '''static bool takLeaderWantsScreenOn()\n{\n    if (!leaderServiceActive || leaderDisplayStartedMs == 0)\n'''
    wants_replacement = '''static bool takLeaderWantsScreenOn()\n{\n    if (jarnsen::serviceSecurityLocked())\n        return true;\n    if (!leaderServiceActive || leaderDisplayStartedMs == 0)\n'''
    tak = replace_once(tak, wants_anchor, wants_replacement, "TAK locked screen power")

    block_start_marker = "        const gpio_num_t button = takLeaderButtonPin();\n"
    block_end_marker = "\n        // Same policy as the V3 service: only a burst of meaningful GATT\n"
    block_start = tak.find(block_start_marker)
    block_end = tak.find(block_end_marker, block_start)
    if block_start < 0 or block_end < 0:
        raise SystemExit("TAK button block boundaries not found")
    original = tak[block_start:block_end]
    indented_original = "\n".join("    " + line if line else line for line in original.split("\n"))

    locked_block = r'''        if (jarnsen::serviceSecurityLocked()) {
            // JARNSEN_TRACKER_TAK_FULL_LOCK_BUTTON: TAK owns GPIO0 directly.
            // Keep its normal unlocked service behavior intact, but while Full
            // Lock is set use short=increment and long=confirm for the PIN.
            const gpio_num_t button = takLeaderButtonPin();
            if (button != GPIO_NUM_NC) {
                const bool pressed = digitalRead(button) == LOW;
                const bool pinActive = graphics::NotificationRenderer::current_notification_type ==
                                           graphics::notificationTypeEnum::number_picker &&
                                       graphics::NotificationRenderer::numDigits == 6U &&
                                       strcmp(graphics::NotificationRenderer::alertBannerMessage, "PIN") == 0;
                if (pressed) {
                    leaderButtonHighSinceMs = 0;
                    if (!leaderButtonLatched) {
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

                    if (leaderButtonLatched && !leaderOpenedServiceThisPress && !leaderLongPressHandled && pinActive &&
                        (uint32_t)(now - leaderButtonLowSinceMs) >= (uint32_t)TAK_LEADER_MENU_LONG_PRESS_MS) {
                        graphics::NotificationRenderer::inEvent.inputEvent = INPUT_BROKER_SELECT;
                        graphics::NotificationRenderer::inEvent.source = "UserButton";
                        graphics::NotificationRenderer::inEvent.kbchar = 0;
                        if (screen)
                            screen->runNow();
                        leaderLongPressHandled = true;
                    }
                } else if (leaderButtonLatched) {
                    if (leaderButtonHighSinceMs == 0)
                        leaderButtonHighSinceMs = now ? now : 1;
                    if ((uint32_t)(now - leaderButtonHighSinceMs) >= 25U) {
                        if (pinActive && !leaderOpenedServiceThisPress && !leaderLongPressHandled) {
                            graphics::NotificationRenderer::inEvent.inputEvent = INPUT_BROKER_UP;
                            graphics::NotificationRenderer::inEvent.source = "UserButton";
                            graphics::NotificationRenderer::inEvent.kbchar = 0;
                            if (screen)
                                screen->runNow();
                        }
                        leaderButtonLatched = false;
                        leaderOpenedServiceThisPress = false;
                        leaderLongPressHandled = false;
                        leaderButtonLowSinceMs = 0;
                        leaderButtonHighSinceMs = 0;
                    }
                } else {
                    leaderButtonHighSinceMs = 0;
                }
            }
        } else {
'''
    tak = tak[:block_start] + locked_block + indented_original + "\n        }" + tak[block_end:]

for marker in (
    "JARNSEN_TRACKER_TAK_FULL_LOCK_BUTTON",
    "if (jarnsen::serviceSecurityLocked())\n        return true;",
    'screen->showNumberPicker("PIN", 0, 6, false',
):
    if marker not in tak:
        raise SystemExit(f"TAK Full Lock validation failed: {marker}")
TAK.write_text(tak, encoding="utf-8")

print("Tracker V1.1 Full Lock display, PIN renderer and Userbutton controls applied")
