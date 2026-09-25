"""Add a PIN-gated five-minute authorization session to Tracker V1.1 menus.

Policy:
- Read-only/operator views remain free.
- PROFILE requires PIN before entering and again before a profile change if the
  session expired.
- Tracker settings, Bluetooth timeout changes, WLAN start/stop and password
  display, diagnostic logging mutation/clear, and INA226 enable/disable require
  PIN.
- Antenna test and Meshtastic UI remain free.
- The existing six-digit JARNSEN user PIN is reused; Full Lock semantics and
  mesh alerts are untouched.
- A successful PIN grants all protected menu actions for five minutes.
- Three wrong PIN attempts cause a 30-second local menu-PIN block.
- Menu authorization is RAM-only and is cleared immediately while Full Lock is
  active. Restart naturally clears it as well.
"""

from pathlib import Path

TARGET = Path("src/vehicle/TrackerStatusModule.cpp")
MARKER = "JARNSEN_TRACKER_MENU_PIN_AUTH_V1"


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected one anchor, got {count}")
    return text.replace(old, new, 1)


text = TARGET.read_text(encoding="utf-8")

if MARKER not in text:
    include_anchor = '#include "jarnsen/core/position/JarnsenPositionCore.h"\n'
    text = replace_once(
        text,
        include_anchor,
        include_anchor + '#include "jarnsen/core/service/JarnsenServiceSecurity.h"\n',
        "security include",
    )

    state_anchor = "MenuView menuView = MenuView::MAIN;\n"
    state_block = r'''MenuView menuView = MenuView::MAIN;

// JARNSEN_TRACKER_MENU_PIN_AUTH_V1
constexpr uint32_t MENU_AUTH_TTL_MS = 5UL * 60UL * 1000UL;
constexpr uint32_t MENU_PIN_BLOCK_MS = 30UL * 1000UL;
constexpr uint32_t MENU_PIN_ERROR_MS = 1500UL;

bool trackerMenuPinMode = false;
bool trackerMenuAuthPending = false;
MenuView trackerMenuAuthPendingView = MenuView::MAIN;
uint8_t trackerMenuAuthPendingSelection = 0;
uint32_t trackerMenuAuthUntilMs = 0;
uint8_t trackerMenuPinDigits[6] = {};
uint8_t trackerMenuPinIndex = 0;
uint8_t trackerMenuPinDigit = 0;
uint8_t trackerMenuPinFailures = 0;
uint32_t trackerMenuPinBlockedUntilMs = 0;
uint32_t trackerMenuPinErrorUntilMs = 0;
uint32_t trackerMenuPinLastRefreshMs = 0;

void selectMenuItem();

bool menuDeadlineActive(uint32_t deadline, uint32_t now)
{
    return deadline != 0U && (int32_t)(deadline - now) > 0;
}

void resetMenuPinDigits()
{
    memset(trackerMenuPinDigits, 0, sizeof(trackerMenuPinDigits));
    trackerMenuPinIndex = 0;
    trackerMenuPinDigit = 0;
}

void cancelMenuPinRequest()
{
    trackerMenuPinMode = false;
    trackerMenuAuthPending = false;
    trackerMenuPinErrorUntilMs = 0;
    trackerMenuPinLastRefreshMs = 0;
    resetMenuPinDigits();
}

void clearMenuAuthorization()
{
    trackerMenuAuthUntilMs = 0;
    trackerMenuPinFailures = 0;
    trackerMenuPinBlockedUntilMs = 0;
    cancelMenuPinRequest();
}

bool trackerMenuAuthorizationValid()
{
    if (jarnsen::serviceSecurityLocked()) {
        clearMenuAuthorization();
        return false;
    }

    const uint32_t now = millis();
    if (menuDeadlineActive(trackerMenuAuthUntilMs, now))
        return true;

    trackerMenuAuthUntilMs = 0;
    return false;
}

void beginMenuPinRequest()
{
    const uint32_t now = millis();
    trackerMenuAuthPending = true;
    trackerMenuAuthPendingView = menuView;
    trackerMenuAuthPendingSelection = trackerMenuSelection;
    trackerMenuPinMode = true;
    trackerMenuLastActivityMs = now ? now : 1;
    trackerMenuPinErrorUntilMs = 0;
    trackerMenuPinLastRefreshMs = now;

    if (trackerMenuPinBlockedUntilMs != 0U && !menuDeadlineActive(trackerMenuPinBlockedUntilMs, now)) {
        trackerMenuPinBlockedUntilMs = 0;
        trackerMenuPinFailures = 0;
    }

    resetMenuPinDigits();
    trackerDiagLog("MENU_AUTH", "PIN_REQUIRED view=%u item=%u", (unsigned)menuView, (unsigned)trackerMenuSelection);
    if (screen)
        screen->runNow();
}

bool requireMenuAuthorization()
{
    if (trackerMenuAuthorizationValid())
        return true;
    beginMenuPinRequest();
    return false;
}

void finishMenuPinSuccess()
{
    const uint32_t now = millis();
    trackerMenuAuthUntilMs = now + MENU_AUTH_TTL_MS;
    trackerMenuPinFailures = 0;
    trackerMenuPinBlockedUntilMs = 0;
    trackerMenuPinErrorUntilMs = 0;
    trackerMenuPinMode = false;

    const bool havePending = trackerMenuAuthPending;
    const MenuView pendingView = trackerMenuAuthPendingView;
    const uint8_t pendingSelection = trackerMenuAuthPendingSelection;
    trackerMenuAuthPending = false;
    resetMenuPinDigits();

    trackerDiagLog("MENU_AUTH", "GRANTED_5MIN");
    if (havePending) {
        menuView = pendingView;
        trackerMenuSelection = pendingSelection;
        trackerMenuLastActivityMs = now ? now : 1;
        selectMenuItem();
    } else if (screen) {
        screen->runNow();
    }
}

void rejectMenuPin()
{
    const uint32_t now = millis();
    trackerMenuPinFailures++;
    resetMenuPinDigits();

    if (trackerMenuPinFailures >= 3U) {
        trackerMenuPinFailures = 0;
        trackerMenuPinBlockedUntilMs = now + MENU_PIN_BLOCK_MS;
        trackerMenuPinErrorUntilMs = 0;
        trackerDiagLog("MENU_AUTH", "PIN_BLOCK_30S");
    } else {
        trackerMenuPinErrorUntilMs = now + MENU_PIN_ERROR_MS;
        trackerDiagLog("MENU_AUTH", "PIN_REJECT attempt=%u", (unsigned)trackerMenuPinFailures);
    }

    trackerMenuLastActivityMs = now ? now : 1;
    if (screen)
        screen->runNow();
}

void menuPinShortPress()
{
    const uint32_t now = millis();
    trackerMenuLastActivityMs = now ? now : 1;
    if (menuDeadlineActive(trackerMenuPinBlockedUntilMs, now)) {
        if (screen)
            screen->runNow();
        return;
    }

    if (trackerMenuPinBlockedUntilMs != 0U) {
        trackerMenuPinBlockedUntilMs = 0;
        trackerMenuPinFailures = 0;
    }
    trackerMenuPinErrorUntilMs = 0;
    trackerMenuPinDigit = (uint8_t)((trackerMenuPinDigit + 1U) % 10U);
    if (screen)
        screen->runNow();
}

void menuPinLongPress()
{
    const uint32_t now = millis();
    trackerMenuLastActivityMs = now ? now : 1;
    if (menuDeadlineActive(trackerMenuPinBlockedUntilMs, now)) {
        if (screen)
            screen->runNow();
        return;
    }

    if (trackerMenuPinBlockedUntilMs != 0U) {
        trackerMenuPinBlockedUntilMs = 0;
        trackerMenuPinFailures = 0;
    }
    trackerMenuPinErrorUntilMs = 0;

    if (trackerMenuPinIndex >= 6U)
        resetMenuPinDigits();
    trackerMenuPinDigits[trackerMenuPinIndex++] = trackerMenuPinDigit;
    trackerMenuPinDigit = 0;

    if (trackerMenuPinIndex < 6U) {
        if (screen)
            screen->runNow();
        return;
    }

    uint32_t entered = 0;
    for (uint8_t i = 0; i < 6U; ++i)
        entered = entered * 10U + trackerMenuPinDigits[i];

    if (jarnsen::serviceSecurityVerifyPin(entered))
        finishMenuPinSuccess();
    else
        rejectMenuPin();
}

void drawMenuPin(OLEDDisplay *display, int16_t x, int16_t y)
{
    if (!display)
        return;

    const int16_t screenW = display->getWidth();
    const int16_t screenH = display->getHeight();
    const uint32_t now = millis();
    const uint32_t blockedMs =
        menuDeadlineActive(trackerMenuPinBlockedUntilMs, now) ? trackerMenuPinBlockedUntilMs - now : 0U;

    display->setTextAlignment(TEXT_ALIGN_CENTER);
    if (blockedMs != 0U) {
        display->setFont(FONT_MEDIUM);
        display->drawString(x + screenW / 2, y + 8, "PIN GESPERRT");
        char waitText[24] = {};
        snprintf(waitText, sizeof(waitText), "NOCH %us", (unsigned)((blockedMs + 999U) / 1000U));
        display->setFont(FONT_SMALL);
        display->drawString(x + screenW / 2, y + 34, waitText);
        display->drawString(x + screenW / 2, y + screenH - 13, "3 FEHLVERSUCHE");
        return;
    }

    display->setFont(FONT_SMALL);
    if (menuDeadlineActive(trackerMenuPinErrorUntilMs, now))
        display->drawString(x + screenW / 2, y + 1, "PIN FALSCH");
    else
        display->drawString(x + screenW / 2, y + 1, "PIN EINGABE");

    const int16_t digitW = screenW >= 150 ? 20 : 16;
    const int16_t digitH = screenH >= 72 ? 38 : 28;
    const int16_t thickness = screenW >= 150 ? 4 : 3;
    const int16_t gap = 2;
    const int16_t groupGap = screenW >= 150 ? 6 : 4;
    const int16_t totalW = 6 * digitW + 5 * gap + groupGap;
    const int16_t top = y + (screenH >= 72 ? 28 : 22);
    int16_t left = x + (screenW - totalW) / 2;

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
        uint8_t value = 0U;
        if (digit < trackerMenuPinIndex)
            value = trackerMenuPinDigits[digit];
        else if (digit == trackerMenuPinIndex)
            value = trackerMenuPinDigit;
        drawSegmentDigit(value, left, top);
        if (digit == trackerMenuPinIndex)
            display->drawRect(left - 2, top - 2, digitW + 4, digitH + 4);
        left += digitW;
        if (digit != 5U)
            left += gap;
        if (digit == 2U)
            left += groupGap;
    }
}

'''
    text = replace_once(text, state_anchor, state_block, "menu PIN state/helpers")

    text = replace_once(
        text,
        '''        if (index == 4) {\n            std::snprintf(buffer, size, "PW: %s", jarnsenServiceWebPassword());\n            return buffer;\n        }\n''',
        '''        if (index == 4) {\n            if (trackerMenuAuthorizationValid())\n                std::snprintf(buffer, size, "PW: %s", jarnsenServiceWebPassword());\n            else\n                std::snprintf(buffer, size, "PW: ******");\n            return buffer;\n        }\n''',
        "hide WLAN password",
    )

    text = replace_once(
        text,
        '''        if (trackerMenuMode) {\n            drawMenu(display, x, y);\n            return;\n        }\n''',
        '''        if (trackerMenuPinMode) {\n            drawMenuPin(display, x, y);\n            return;\n        }\n        if (trackerMenuMode) {\n            drawMenu(display, x, y);\n            return;\n        }\n''',
        "draw menu PIN before menu",
    )

    text = replace_once(
        text,
        '''        else if (s == 1)\n            parentMenu(MenuView::PROFILE);\n        else if (s == 2)\n            parentMenu(MenuView::TRACKER);\n''',
        '''        else if (s == 1) {\n            if (!requireMenuAuthorization())\n                break;\n            parentMenu(MenuView::PROFILE);\n        } else if (s == 2)\n            parentMenu(MenuView::TRACKER);\n''',
        "protect PROFILE entry",
    )

    text = replace_once(
        text,
        '''        } else if (s < jarnsen::RADIO_PROFILE_SLOT_COUNT) {\n            const auto profile = static_cast<jarnsen::RadioProfileSlot>(s);\n''',
        '''        } else if (s < jarnsen::RADIO_PROFILE_SLOT_COUNT) {\n            if (!requireMenuAuthorization())\n                break;\n            const auto profile = static_cast<jarnsen::RadioProfileSlot>(s);\n''',
        "protect profile changes",
    )

    protected_cases = [
        ("SMART_DISTANCE", "POSITION", "const uint16_t vals[] = {50, 75, 100, 150};"),
        ("MIN_TX_INTERVAL", "POSITION", "const uint16_t vals[] = {30, 45, 60, 90};"),
        ("MOVING_GNSS", "POSITION", "const uint16_t vals[] = {5, 10, 15, 30};"),
        ("PARK_INTERVAL", "PARKING", "const uint16_t vals[] = {20, 30, 60, 120, 240, 360, 540, 720};"),
        ("GPS_SEARCH_TIME", "PARKING", "const uint16_t vals[] = {15, 30, 45, 60};"),
        ("BLE_IDLE", "BLUETOOTH", "const uint16_t vals[] = {60, 120, 180, 300};"),
        ("BLE_HARD", "BLUETOOTH", "const uint16_t vals[] = {300, 600, 900, 1800};"),
    ]
    for view, parent, value_line in protected_cases:
        old = f'''    case MenuView::{view}:\n        if (s == 0)\n            parentMenu(MenuView::{parent});\n        else {{\n            {value_line}\n'''
        new = f'''    case MenuView::{view}:\n        if (s == 0)\n            parentMenu(MenuView::{parent});\n        else {{\n            if (!requireMenuAuthorization())\n                break;\n            {value_line}\n'''
        text = replace_once(text, old, new, f"protect {view}")

    text = replace_once(
        text,
        '''    case MenuView::MOTION_SENSITIVITY:\n        if (s == 0)\n            parentMenu(MenuView::MOTION);\n        else {\n            trackerSetMotionSensitivityIndex(s - 1);\n''',
        '''    case MenuView::MOTION_SENSITIVITY:\n        if (s == 0)\n            parentMenu(MenuView::MOTION);\n        else {\n            if (!requireMenuAuthorization())\n                break;\n            trackerSetMotionSensitivityIndex(s - 1);\n''',
        "protect MOTION_SENSITIVITY",
    )

    text = replace_once(
        text,
        '''    case MenuView::WLAN:\n        if (s == 0) {\n            trackerWlanLastActionFailed = false;\n            parentMenu(MenuView::SERVICE);\n        } else if (s == 1) {\n            if (jarnsenServiceWebActive()) {\n                jarnsenServiceWebStop();\n                trackerWlanLastActionFailed = false;\n            } else {\n                trackerWlanLastActionFailed = !jarnsenServiceWebStart();\n            }\n            if (screen)\n                screen->runNow();\n        }\n        break;\n''',
        '''    case MenuView::WLAN:\n        if (s == 0) {\n            trackerWlanLastActionFailed = false;\n            parentMenu(MenuView::SERVICE);\n        } else if (s == 1) {\n            if (!requireMenuAuthorization())\n                break;\n            if (jarnsenServiceWebActive()) {\n                jarnsenServiceWebStop();\n                trackerWlanLastActionFailed = false;\n            } else {\n                trackerWlanLastActionFailed = !jarnsenServiceWebStart();\n            }\n            if (screen)\n                screen->runNow();\n        } else if (s == 4) {\n            if (!requireMenuAuthorization())\n                break;\n            if (screen)\n                screen->runNow();\n        }\n        break;\n''',
        "protect WLAN mutation/password",
    )

    for label, old, new in [
        (
            "logging toggle",
            '''    case MenuView::LOGGING:\n        if (s == 0)\n            parentMenu(MenuView::DIAG_LOG);\n        else {\n            trackerDiagSetEnabled(s == 1);\n''',
            '''    case MenuView::LOGGING:\n        if (s == 0)\n            parentMenu(MenuView::DIAG_LOG);\n        else {\n            if (!requireMenuAuthorization())\n                break;\n            trackerDiagSetEnabled(s == 1);\n''',
        ),
        (
            "log clear",
            '''    case MenuView::LOG_CLEAR:\n        if (s == 0)\n            parentMenu(MenuView::DIAG_LOG);\n        else {\n            trackerDiagClear();\n''',
            '''    case MenuView::LOG_CLEAR:\n        if (s == 0)\n            parentMenu(MenuView::DIAG_LOG);\n        else {\n            if (!requireMenuAuthorization())\n                break;\n            trackerDiagClear();\n''',
        ),
        (
            "INA226 toggle",
            '''    case MenuView::INA226:\n        if (s == 0)\n            parentMenu(MenuView::POWER);\n        else {\n            trackerSetIna226Enabled(s == 1);\n''',
            '''    case MenuView::INA226:\n        if (s == 0)\n            parentMenu(MenuView::POWER);\n        else {\n            if (!requireMenuAuthorization())\n                break;\n            trackerSetIna226Enabled(s == 1);\n''',
        ),
    ]:
        text = replace_once(text, old, new, f"protect {label}")

    text = replace_once(
        text,
        '''void trackerServiceMenuShortPress()\n{\n    if (!trackerInteractionActive || !screen)\n        return;\n    trackerMenuLastActivityMs = millis() ? millis() : 1;\n''',
        '''void trackerServiceMenuShortPress()\n{\n    if (!trackerInteractionActive || !screen)\n        return;\n    trackerMenuLastActivityMs = millis() ? millis() : 1;\n    if (trackerMenuPinMode) {\n        menuPinShortPress();\n        return;\n    }\n''',
        "route short press to PIN",
    )

    text = replace_once(
        text,
        '''void trackerServiceMenuSelect()\n{\n    if (!trackerInteractionActive) {\n        trackerServiceMenuOpen();\n        return;\n    }\n''',
        '''void trackerServiceMenuSelect()\n{\n    if (trackerMenuPinMode) {\n        menuPinLongPress();\n        return;\n    }\n    if (!trackerInteractionActive) {\n        trackerServiceMenuOpen();\n        return;\n    }\n''',
        "route long press to PIN",
    )

    text = replace_once(
        text,
        '''void trackerServiceMenuPump()\n{\n    if (!trackerInteractionActive)\n        return;\n    if (trackerMenuMode && trackerMenuLastActivityMs != 0 &&\n        (uint32_t)(millis() - trackerMenuLastActivityMs) >= MENU_TIMEOUT_MS) {\n        trackerServiceMenuClose();\n        return;\n    }\n    if (trackerMenuMode && (menuView == MenuView::LOG_EXPORT || menuView == MenuView::ANTENNA_TEST) && screen)\n        screen->runNow();\n}\n''',
        '''void trackerServiceMenuPump()\n{\n    if (jarnsen::serviceSecurityLocked()) {\n        if (trackerMenuAuthUntilMs != 0U || trackerMenuPinMode || trackerMenuAuthPending)\n            clearMenuAuthorization();\n        return;\n    }\n\n    const uint32_t now = millis();\n    const bool hadAuthorization = trackerMenuAuthUntilMs != 0U;\n    (void)trackerMenuAuthorizationValid();\n    if (hadAuthorization && trackerMenuAuthUntilMs == 0U && screen)\n        screen->runNow();\n\n    if (!trackerInteractionActive)\n        return;\n\n    if (trackerMenuPinMode) {\n        if (menuDeadlineActive(trackerMenuPinBlockedUntilMs, now)) {\n            if (screen && (trackerMenuPinLastRefreshMs == 0U ||\n                           (uint32_t)(now - trackerMenuPinLastRefreshMs) >= 500U)) {\n                trackerMenuPinLastRefreshMs = now ? now : 1;\n                screen->runNow();\n            }\n            return;\n        }\n        if (trackerMenuPinBlockedUntilMs != 0U) {\n            trackerMenuPinBlockedUntilMs = 0;\n            trackerMenuPinFailures = 0;\n            trackerMenuPinLastRefreshMs = 0;\n            trackerMenuLastActivityMs = now ? now : 1;\n            resetMenuPinDigits();\n            if (screen)\n                screen->runNow();\n            return;\n        }\n        if (trackerMenuLastActivityMs != 0U && (uint32_t)(now - trackerMenuLastActivityMs) >= MENU_TIMEOUT_MS) {\n            cancelMenuPinRequest();\n            if (screen)\n                screen->runNow();\n        }\n        return;\n    }\n\n    if (trackerMenuMode && trackerMenuLastActivityMs != 0 && (uint32_t)(now - trackerMenuLastActivityMs) >= MENU_TIMEOUT_MS) {\n        trackerServiceMenuClose();\n        return;\n    }\n    if (trackerMenuMode && (menuView == MenuView::LOG_EXPORT || menuView == MenuView::ANTENNA_TEST) && screen)\n        screen->runNow();\n}\n''',
        "menu auth pump",
    )

    text = replace_once(
        text,
        '''void trackerServiceMenuClose()\n{\n    trackerMenuMode = false;\n''',
        '''void trackerServiceMenuClose()\n{\n    cancelMenuPinRequest();\n    trackerMenuMode = false;\n''',
        "close cancels PIN request",
    )
    text = replace_once(
        text,
        '''void trackerServiceMenuForceClose()\n{\n    trackerMenuMode = false;\n''',
        '''void trackerServiceMenuForceClose()\n{\n    cancelMenuPinRequest();\n    trackerMenuMode = false;\n''',
        "force-close cancels PIN request",
    )

for required in (
    MARKER,
    "MENU_AUTH_TTL_MS = 5UL * 60UL * 1000UL",
    "MENU_PIN_BLOCK_MS = 30UL * 1000UL",
    "serviceSecurityVerifyPin(entered)",
    "PW: ******",
    "if (!requireMenuAuthorization())",
    "drawMenuPin(display, x, y)",
    "PIN GESPERRT",
):
    if required not in text:
        raise SystemExit(f"menu PIN validation failed: {required}")

TARGET.write_text(text, encoding="utf-8")
