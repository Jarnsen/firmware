"""Extend JARNSEN Full Lock display/input ownership to every Unified Core board.

Tracker V1.1 keeps its richer TrackerCommonPolicy implementation. This transform
adds the same hard local-UI lock gate to the five shared-display targets:
Heltec V3, Heltec V4, Seeed Wio Tracker L1, T-Beam and T-Beam Supreme.

While serviceSecurityLocked() is true:
- normal pages, stock Meshtastic UI and menu navigation are never rendered;
- the display shows NODE / GESPERRT;
- display timeout remains the normal JARNSEN 20 s policy;
- a wake press is consumed by normal screen wake handling;
- the next intentional input opens the existing six-digit PIN picker;
- Userbutton short press increments the current digit and long press confirms;
- successful PIN uses serviceSecurityUnlock(), preserving existing persistence
  and mesh alert behavior.

This does not add a new remote/AdminModule policy. It only makes the existing
persistent Full Lock state own the local UI consistently on all supported boards.
"""

from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected one anchor, got {count}")
    return text.replace(old, new, 1)


# ---------------------------------------------------------------------------
# Screen: absolute local UI ownership for the five shared-display boards.
# Tracker is excluded because its existing Full Lock transform/Common policy is
# richer and already owns that board.
# ---------------------------------------------------------------------------
SCREEN = Path("src/graphics/Screen.cpp")
screen = SCREEN.read_text(encoding="utf-8")
MARKER = "JARNSEN_UNIFIED_NONTRACKER_FULL_LOCK_UI"

if MARKER not in screen:
    include_anchor = '#include "jarnsen/adapters/JarnsenDisplayRuntime.h"\n'
    if '#include "jarnsen/core/service/JarnsenServiceSecurity.h"' not in screen:
        screen = replace_once(
            screen,
            include_anchor,
            include_anchor + '#include "jarnsen/core/service/JarnsenServiceSecurity.h"\n',
            "Screen shared security include",
        )

    update_anchor = "static inline void updateUiFrame(OLEDDisplayUi *ui)\n{\n"
    helper = r'''#if !defined(HELTEC_TRACKER_V1_1) && \
    (defined(HELTEC_V3) || defined(_VARIANT_HELTEC_V3) || defined(HELTEC_V4) || defined(_VARIANT_HELTEC_V4) || \
     defined(SEEED_WIO_TRACKER_L1) || defined(TBEAM_V10) || defined(LILYGO_TBEAM_S3_CORE))
#define JARNSEN_UNIFIED_NONTRACKER_FULL_LOCK 1
#else
#define JARNSEN_UNIFIED_NONTRACKER_FULL_LOCK 0
#endif

#if JARNSEN_UNIFIED_NONTRACKER_FULL_LOCK
// JARNSEN_UNIFIED_NONTRACKER_FULL_LOCK_UI
static bool jarnsenUnifiedFullLockPinPickerActive()
{
    return NotificationRenderer::current_notification_type == notificationTypeEnum::number_picker &&
           NotificationRenderer::numDigits == 6U && strcmp(NotificationRenderer::alertBannerMessage, "PIN") == 0;
}

static void drawJarnsenUnifiedFullLockScreenIntoBuffer(OLEDDisplay *display)
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

// Security-core presentation hook for shared-display boards. Locking wakes and
// reclaims the JARNSEN display module, but does not defeat the normal 20 s
// display timeout. Unlocking simply redraws the normal JARNSEN UI.
extern "C" void jarnsenFullLockUiStateChanged(bool locked)
{
    if (!screen)
        return;
    if (locked) {
        jarnsenDisplayRequestFocus();
        if (!screen->isScreenOn())
            screen->setOn(true);
    }
    screen->runNow();
}
#endif

'''
    screen = replace_once(screen, update_anchor, helper + update_anchor, "Screen common Full Lock helper")

    update_body = update_anchor + r'''#if JARNSEN_UNIFIED_NONTRACKER_FULL_LOCK
    if (jarnsen::serviceSecurityLocked() && screen != nullptr) {
        OLEDDisplay *display = screen->getDisplayDevice();
        if (jarnsenUnifiedFullLockPinPickerActive()) {
            display->clear();
            NotificationRenderer::drawBannercallback(display, ui->getUiState());
        } else {
            if (NotificationRenderer::isOverlayBannerShowing())
                NotificationRenderer::resetBanner();
            drawJarnsenUnifiedFullLockScreenIntoBuffer(display);
        }
        display->display();
        return;
    }
#endif
'''
    screen = replace_once(screen, update_anchor, update_body, "Screen common Full Lock render gate")

    input_anchor = '''    if (!screenOn && !jarnsenLiveIsActive())\n        return 0;\n\n'''
    input_gate = input_anchor + r'''#if JARNSEN_UNIFIED_NONTRACKER_FULL_LOCK
    // Full Lock consumes every normal UI event. When the display is already
    // awake, the next intentional operator input opens the local PIN picker.
    if (jarnsen::serviceSecurityLocked() && !jarnsenUnifiedFullLockPinPickerActive()) {
        if (NotificationRenderer::isOverlayBannerShowing())
            NotificationRenderer::resetBanner();

        const bool requestPin = event->inputEvent == INPUT_BROKER_UP || event->inputEvent == INPUT_BROKER_DOWN ||
                                event->inputEvent == INPUT_BROKER_LEFT || event->inputEvent == INPUT_BROKER_RIGHT ||
                                event->inputEvent == INPUT_BROKER_SELECT || event->inputEvent == INPUT_BROKER_USER_PRESS ||
                                event->inputEvent == INPUT_BROKER_ALT_PRESS;
        if (requestPin) {
            showNumberPicker("PIN", 0, 6, false, [](uint32_t pin) {
                const bool unlocked = jarnsen::serviceSecurityUnlock(pin);
                if (unlocked)
                    jarnsenDisplayRequestFocus();
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
    screen = replace_once(screen, input_anchor, input_gate, "Screen common Full Lock input gate")

for required in (
    MARKER,
    "JARNSEN_UNIFIED_NONTRACKER_FULL_LOCK",
    "drawJarnsenUnifiedFullLockScreenIntoBuffer",
    'showNumberPicker("PIN", 0, 6, false',
    "jarnsen::serviceSecurityUnlock(pin)",
):
    if required not in screen:
        raise SystemExit(f"Unified Full Lock Screen validation failed: {required}")
SCREEN.write_text(screen, encoding="utf-8")


# ---------------------------------------------------------------------------
# Generic Userbutton: use the same PIN controls on every JARNSEN button target.
# The active Tracker Common policy owns/disables ButtonThread, so widening the
# compile guard does not steal Tracker GPIO ownership.
# ---------------------------------------------------------------------------
BUTTON = Path("src/input/ButtonThread.cpp")
button = BUTTON.read_text(encoding="utf-8")
BUTTON_MARKER = "JARNSEN_UNIFIED_FULL_LOCK_BUTTON"

if BUTTON_MARKER not in button:
    include_anchor = '#include "jarnsen/core/service/JarnsenDiagnosticLog.h"\n'
    if '#include "jarnsen/core/service/JarnsenServiceSecurity.h"' not in button:
        button = replace_once(
            button,
            include_anchor,
            include_anchor + '#include "jarnsen/core/service/JarnsenServiceSecurity.h"\n',
            "Button shared security include",
        )

    tracker_short = r'''#if defined(HELTEC_TRACKER_V1_1)
            // JARNSEN_TRACKER_LOCK_BUTTON: while locked, short physical presses
            // increment the selected PIN digit instead of navigating pages.
            if (jarnsen::serviceSecurityLocked() && isJarnsenUserButton(_originName))
                evt.inputEvent = INPUT_BROKER_UP;
            else
#endif
                evt.inputEvent = _singlePress;
'''
    unified_short = r'''#if JARNSEN_BUTTON_TARGET
            // JARNSEN_UNIFIED_FULL_LOCK_BUTTON: while locked, short physical
            // presses increment the selected PIN digit instead of navigating.
            if (jarnsen::serviceSecurityLocked() && isJarnsenUserButton(_originName))
                evt.inputEvent = INPUT_BROKER_UP;
            else
#endif
                evt.inputEvent = _singlePress;
'''
    if tracker_short in button:
        button = replace_once(button, tracker_short, unified_short, "Widen Full Lock short press")
    else:
        raw_short = "            evt.inputEvent = _singlePress;\n"
        button = replace_once(button, raw_short, unified_short, "Add Full Lock short press")

    tracker_long = r'''#if defined(HELTEC_TRACKER_V1_1)
                if (jarnsen::serviceSecurityLocked() && isJarnsenUserButton(_originName))
                    evt.inputEvent = INPUT_BROKER_SELECT;
                else
#endif
                    evt.inputEvent = _longPress;
                this->notifyObservers(&evt);
'''
    unified_long = r'''#if JARNSEN_BUTTON_TARGET
                if (jarnsen::serviceSecurityLocked() && isJarnsenUserButton(_originName))
                    evt.inputEvent = INPUT_BROKER_SELECT;
                else
#endif
                    evt.inputEvent = _longPress;
                this->notifyObservers(&evt);
'''
    if tracker_long in button:
        button = replace_once(button, tracker_long, unified_long, "Widen Full Lock long press")
    else:
        raw_long = '''                evt.inputEvent = _longPress;\n                this->notifyObservers(&evt);\n'''
        button = replace_once(button, raw_long, unified_long, "Add Full Lock long press")

for required in (BUTTON_MARKER, "#if JARNSEN_BUTTON_TARGET", "evt.inputEvent = INPUT_BROKER_UP;", "evt.inputEvent = INPUT_BROKER_SELECT;"):
    if required not in button:
        raise SystemExit(f"Unified Full Lock Button validation failed: {required}")
BUTTON.write_text(button, encoding="utf-8")
