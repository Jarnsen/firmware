"""Apply the JARNSEN local-menu PIN policy to every supported display adapter.

The security policy itself lives in jarnsen/core/service/JarnsenMenuAuthorization:
- one existing six-digit JARNSEN user PIN
- five-minute RAM-only authorization shared by protected menu actions
- three wrong attempts -> 30-second local input block
- Full Lock/reboot clear authorization
- no Full-Lock state mutation and no mesh lock/unlock alerts

This transform only wires board UI adapters to that shared policy. The Tracker
keeps its richer menu renderer; the common JARNSEN display adapter covers
Heltec V3/V4, Wio Tracker L1, T-Beam and T-Beam Supreme.
"""

from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected one anchor, got {count}")
    return text.replace(old, new, 1)


# ---------------------------------------------------------------------------
# Tracker V1.1: keep its existing PIN UI, but bind grant/validation to the
# shared Unified-Core menu authorization service.
# ---------------------------------------------------------------------------
TRACKER = Path("src/vehicle/TrackerStatusModule.cpp")
tracker = TRACKER.read_text(encoding="utf-8")

if "JARNSEN_TRACKER_MENU_PIN_SHARED_CORE" not in tracker:
    if "JARNSEN_TRACKER_MENU_PIN_AUTH_V1" not in tracker:
        raise SystemExit("Tracker menu PIN transform must run before shared menu security transform")

    include_anchor = '#include "jarnsen/core/service/JarnsenServiceSecurity.h"\n'
    tracker = replace_once(
        tracker,
        include_anchor,
        include_anchor + '#include "jarnsen/core/service/JarnsenMenuAuthorization.h"\n',
        "Tracker shared menu auth include",
    )

    tracker = replace_once(
        tracker,
        "void clearMenuAuthorization()\n{\n    trackerMenuAuthUntilMs = 0;\n",
        "void clearMenuAuthorization()\n{\n    jarnsen::menuAuthorizationClear(); // JARNSEN_TRACKER_MENU_PIN_SHARED_CORE\n    trackerMenuAuthUntilMs = 0;\n",
        "Tracker clear shared authorization",
    )

    tracker = replace_once(
        tracker,
        "    if (menuDeadlineActive(trackerMenuAuthUntilMs, now))\n        return true;\n",
        "    if (menuDeadlineActive(trackerMenuAuthUntilMs, now))\n        return jarnsen::menuAuthorizationValid();\n",
        "Tracker validate shared authorization",
    )

    tracker = replace_once(
        tracker,
        "    if (jarnsen::serviceSecurityVerifyPin(entered))\n        finishMenuPinSuccess();\n    else\n        rejectMenuPin();\n",
        "    const auto authResult = jarnsen::menuAuthorizationSubmitPin(entered);\n"
        "    if (authResult == jarnsen::MenuAuthorizationResult::GRANTED)\n"
        "        finishMenuPinSuccess();\n"
        "    else\n"
        "        rejectMenuPin();\n",
        "Tracker submit PIN through shared authorization",
    )

TRACKER.write_text(tracker, encoding="utf-8")


# ---------------------------------------------------------------------------
# Shared display adapter: V3/V4/Wio/T-Beam/T-Beam Supreme.
# Current shared menu exposes PROFILE mutations and read-only SYSTEM/MESHTASTIC;
# protect PROFILE at entry and again at mutation if the 5-minute session expired.
# Future protected mutations in this adapter can call requireMenuAuthorization().
# ---------------------------------------------------------------------------
COMMON = Path("src/jarnsen/adapters/JarnsenDisplayRuntime.cpp")
common = COMMON.read_text(encoding="utf-8")
MARKER = "JARNSEN_SHARED_MENU_PIN_AUTH_V1"

if MARKER not in common:
    include_anchor = '#include "jarnsen/core/position/JarnsenPositionCore.h"\n'
    common = replace_once(
        common,
        include_anchor,
        include_anchor + '#include "jarnsen/core/service/JarnsenMenuAuthorization.h"\n',
        "Shared display menu auth include",
    )

    state_anchor = "const char *profileError = nullptr;\n"
    state_block = r'''const char *profileError = nullptr;

// JARNSEN_SHARED_MENU_PIN_AUTH_V1
constexpr uint32_t MENU_PIN_ERROR_MS = 1500UL;
bool menuPinMode = false;
MenuView menuPinPendingView = MenuView::NONE;
uint8_t menuPinPendingSelection = 0;
uint8_t menuPinDigits[6] = {};
uint8_t menuPinIndex = 0;
uint8_t menuPinDigit = 0;
uint32_t menuPinErrorUntilMs = 0;

void redraw();

bool localDeadlineActive(uint32_t deadline, uint32_t now)
{
    return deadline != 0U && (int32_t)(deadline - now) > 0;
}

void resetMenuPinDigits()
{
    std::memset(menuPinDigits, 0, sizeof(menuPinDigits));
    menuPinIndex = 0;
    menuPinDigit = 0;
}

void cancelMenuPinRequest()
{
    menuPinMode = false;
    menuPinErrorUntilMs = 0;
    resetMenuPinDigits();
}

void beginMenuPinRequest()
{
    menuPinPendingView = menuView;
    menuPinPendingSelection = menuSelection;
    menuPinMode = true;
    menuPinErrorUntilMs = 0;
    resetMenuPinDigits();
    redraw();
}

bool requireMenuAuthorization()
{
    if (jarnsen::menuAuthorizationValid())
        return true;
    beginMenuPinRequest();
    return false;
}

void finishMenuPinSuccess()
{
    const MenuView pendingView = menuPinPendingView;
    const uint8_t pendingSelection = menuPinPendingSelection;
    cancelMenuPinRequest();
    menuView = pendingView;
    menuSelection = pendingSelection;
    // Re-run exactly the protected selection that requested authorization.
    // The shared five-minute session is now valid, so this cannot recurse back
    // into PIN entry.
    jarnsenDisplayHandleSelect();
}

void menuPinStep(bool next)
{
    if (jarnsen::menuAuthorizationBlockRemainingMs() != 0U) {
        redraw();
        return;
    }
    menuPinErrorUntilMs = 0;
    if (next)
        menuPinDigit = (uint8_t)((menuPinDigit + 1U) % 10U);
    else
        menuPinDigit = (uint8_t)((menuPinDigit + 9U) % 10U);
    redraw();
}

void menuPinSelect()
{
    const uint32_t now = millis();
    if (jarnsen::menuAuthorizationBlockRemainingMs() != 0U) {
        redraw();
        return;
    }

    menuPinErrorUntilMs = 0;
    if (menuPinIndex >= 6U)
        resetMenuPinDigits();
    menuPinDigits[menuPinIndex++] = menuPinDigit;
    menuPinDigit = 0;

    if (menuPinIndex < 6U) {
        redraw();
        return;
    }

    uint32_t entered = 0;
    for (uint8_t i = 0; i < 6U; ++i)
        entered = entered * 10U + menuPinDigits[i];

    const auto result = jarnsen::menuAuthorizationSubmitPin(entered);
    resetMenuPinDigits();
    if (result == jarnsen::MenuAuthorizationResult::GRANTED) {
        finishMenuPinSuccess();
        return;
    }

    if (result == jarnsen::MenuAuthorizationResult::REJECTED)
        menuPinErrorUntilMs = now + MENU_PIN_ERROR_MS;
    redraw();
}

void drawMenuPin(OLEDDisplay *display, int16_t x, int16_t y)
{
    if (!display)
        return;

    const int w = display->getWidth();
    const int h = display->getHeight();
    const uint32_t now = millis();
    const uint32_t blockedMs = jarnsen::menuAuthorizationBlockRemainingMs();

    display->setTextAlignment(TEXT_ALIGN_CENTER);
    if (blockedMs != 0U) {
        display->setFont(FONT_MEDIUM);
        display->drawString(x + w / 2, y + 8, "PIN GESPERRT");
        char waitText[24] = {};
        std::snprintf(waitText, sizeof(waitText), "NOCH %lus", (unsigned long)((blockedMs + 999U) / 1000U));
        display->setFont(FONT_SMALL);
        display->drawString(x + w / 2, y + 32, waitText);
        return;
    }

    display->setFont(FONT_SMALL);
    display->drawString(x + w / 2, y + 1,
                        localDeadlineActive(menuPinErrorUntilMs, now) ? "PIN FALSCH" : "PIN EINGABE");

    char digits[16] = {};
    uint8_t values[6] = {};
    for (uint8_t i = 0; i < 6U; ++i) {
        if (i < menuPinIndex)
            values[i] = menuPinDigits[i];
        else if (i == menuPinIndex)
            values[i] = menuPinDigit;
    }
    std::snprintf(digits, sizeof(digits), "%u%u%u %u%u%u", (unsigned)values[0], (unsigned)values[1],
                  (unsigned)values[2], (unsigned)values[3], (unsigned)values[4], (unsigned)values[5]);
    display->setFont(FONT_MEDIUM);
    display->drawString(x + w / 2, y + (h >= 64 ? 22 : 16), digits);

    char position[24] = {};
    std::snprintf(position, sizeof(position), "STELLE %u/6", (unsigned)(menuPinIndex < 6U ? menuPinIndex + 1U : 6U));
    display->setFont(FONT_SMALL);
    display->drawString(x + w / 2, y + h - 13, position);
}
'''
    common = replace_once(common, state_anchor, state_block, "Shared display PIN state/helpers")

    common = replace_once(
        common,
        "        if (menuView != MenuView::NONE) {\n            drawMenu(display, x, y);\n            return;\n        }\n",
        "        if (menuPinMode) {\n            drawMenuPin(display, x, y);\n            return;\n        }\n"
        "        if (menuView != MenuView::NONE) {\n            drawMenu(display, x, y);\n            return;\n        }\n",
        "Shared display render PIN first",
    )

    common = replace_once(
        common,
        "    if (menuView != MenuView::NONE) {\n        const uint8_t count = menuCount();\n",
        "    if (menuPinMode) {\n        menuPinStep(next);\n        return true;\n    }\n"
        "    if (menuView != MenuView::NONE) {\n        const uint8_t count = menuCount();\n",
        "Shared display PIN digit step",
    )

    common = replace_once(
        common,
        "    if (stockUiActive)\n        return false;\n    if (menuView == MenuView::NONE) {\n",
        "    if (stockUiActive)\n        return false;\n"
        "    if (menuPinMode) {\n        menuPinSelect();\n        return true;\n    }\n"
        "    if (menuView == MenuView::NONE) {\n",
        "Shared display PIN confirm",
    )

    common = replace_once(
        common,
        "        case jarnsen::MainMenuItem::PROFILE:\n            menuView = MenuView::PROFILE;\n",
        "        case jarnsen::MainMenuItem::PROFILE:\n"
        "            if (!requireMenuAuthorization())\n                return true;\n"
        "            menuView = MenuView::PROFILE;\n",
        "Protect shared PROFILE entry",
    )

    common = replace_once(
        common,
        "    if (menuView == MenuView::PROFILE) {\n        if (menuSelection < 3U) {\n            const auto profile = static_cast<jarnsen::RadioProfileSlot>(menuSelection);\n",
        "    if (menuView == MenuView::PROFILE) {\n        if (menuSelection < 3U) {\n"
        "            if (!requireMenuAuthorization())\n                return true;\n"
        "            const auto profile = static_cast<jarnsen::RadioProfileSlot>(menuSelection);\n",
        "Protect shared PROFILE mutation",
    )

    common = replace_once(
        common,
        "bool jarnsenDisplayHandleBack()\n{\n    if (stockUiActive) {\n",
        "bool jarnsenDisplayHandleBack()\n{\n"
        "    if (menuPinMode) {\n        cancelMenuPinRequest();\n        redraw();\n        return true;\n    }\n"
        "    if (stockUiActive) {\n",
        "Shared display cancel PIN",
    )

COMMON.write_text(common, encoding="utf-8")

for path, marker in ((TRACKER, "JARNSEN_TRACKER_MENU_PIN_SHARED_CORE"), (COMMON, MARKER)):
    text = path.read_text(encoding="utf-8")
    if marker not in text:
        raise SystemExit(f"shared menu PIN validation failed for {path}: {marker}")
