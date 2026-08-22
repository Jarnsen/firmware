#include "configuration.h"
#include "infrastructure/HeltecV3ServicePage.h"

#if defined(_VARIANT_HELTEC_V3) && HAS_SCREEN

#include "PowerStatus.h"
#include "graphics/Screen.h"
#include "graphics/ScreenFonts.h"
#include "graphics/SharedUIDisplay.h"
#include "graphics/draw/NotificationRenderer.h"
#include "graphics/draw/UIRenderer.h"
#include "infrastructure/HeltecV3DiagnosticLog.h"
#include "infrastructure/HeltecV3Runtime.h"

#include <Arduino.h>
#include <cstdio>
#include <functional>

namespace
{
volatile uint32_t lastServicePageDrawMs = 0;

enum class V3ServiceMenu : uint8_t { NONE = 0, ROOT, DIAG_LOG, CLEAR_CONFIRM };
enum class V3MenuAction : uint8_t { NONE = 0, CLOSE, NAV_MESH, NAV_ANTENNA, EXPORT_LOG, CLEAR_LOG };

bool menuActive = false;
V3ServiceMenu currentMenu = V3ServiceMenu::NONE;
V3ServiceMenu pendingMenu = V3ServiceMenu::NONE;
V3MenuAction pendingAction = V3MenuAction::NONE;
bool overlayRequestPending = false;
bool menuNeedsReopen = false;
uint32_t overlayRequestedAtMs = 0;

bool roleEnabled()
{
    return config.device.role == meshtastic_Config_DeviceConfig_Role_ROUTER_LATE ||
           config.device.role == meshtastic_Config_DeviceConfig_Role_REPEATER;
}

void formatUptime(char *out, size_t outSize)
{
    if (!out || outSize == 0)
        return;
    const uint32_t total = millis() / 1000UL;
    const uint32_t days = total / 86400UL;
    const uint32_t hours = (total % 86400UL) / 3600UL;
    const uint32_t mins = (total % 3600UL) / 60UL;
    if (days)
        snprintf(out, outSize, "%ud%02uh", (unsigned)days, (unsigned)hours);
    else if (hours)
        snprintf(out, outSize, "%uh%02um", (unsigned)hours, (unsigned)mins);
    else
        snprintf(out, outSize, "%um", (unsigned)mins);
}

void showOptions(const char *title, const char **options, uint8_t count, std::function<void(int)> callback)
{
    if (!screen || !menuActive)
        return;

    graphics::BannerOverlayOptions banner;
    banner.message = title;
    banner.optionsArrayPtr = options;
    banner.optionsCount = count;
    banner.bannerCallback = callback;
    banner.InitialSelected = 0;
    banner.durationMs = 0;
    banner.notificationType = graphics::notificationTypeEnum::selection_picker;
    screen->showOverlayBanner(banner);
    overlayRequestPending = true;
    overlayRequestedAtMs = millis() ? millis() : 1;
}

void queueMenu(V3ServiceMenu menu)
{
    pendingMenu = menu;
}

void queueAction(V3MenuAction action)
{
    pendingAction = action;
}

void showMenu(V3ServiceMenu menu)
{
    if (!menuActive)
        return;

    currentMenu = menu;
    pendingMenu = V3ServiceMenu::NONE;
    menuNeedsReopen = false;

    switch (menu) {
    case V3ServiceMenu::ROOT: {
        static const char *options[] = {"Back", "Mesh Health", "Antenna Test", "Diagnostic Log"};
        showOptions("V3 Service", options, 4, [](int selected) {
            switch (selected) {
            case 0: queueAction(V3MenuAction::CLOSE); break;
            case 1: queueAction(V3MenuAction::NAV_MESH); break;
            case 2: queueAction(V3MenuAction::NAV_ANTENNA); break;
            case 3: queueMenu(V3ServiceMenu::DIAG_LOG); break;
            default: break;
            }
        });
        break;
    }
    case V3ServiceMenu::DIAG_LOG: {
        static const char *options[] = {"Back", "Export via USB", "Clear Log"};
        showOptions("Diagnostic Log", options, 3, [](int selected) {
            if (selected == 0)
                queueMenu(V3ServiceMenu::ROOT);
            else if (selected == 1)
                queueAction(V3MenuAction::EXPORT_LOG);
            else if (selected == 2)
                queueMenu(V3ServiceMenu::CLEAR_CONFIRM);
        });
        break;
    }
    case V3ServiceMenu::CLEAR_CONFIRM: {
        static const char *options[] = {"Back", "CLEAR LOG"};
        showOptions("Clear Diagnostic Log?", options, 2, [](int selected) {
            if (selected == 0)
                queueMenu(V3ServiceMenu::DIAG_LOG);
            else if (selected == 1)
                queueAction(V3MenuAction::CLEAR_LOG);
        });
        break;
    }
    case V3ServiceMenu::NONE:
    default:
        currentMenu = V3ServiceMenu::ROOT;
        showMenu(V3ServiceMenu::ROOT);
        break;
    }
}

void closeMenuInternal(bool redraw)
{
    if (graphics::NotificationRenderer::current_notification_type == graphics::notificationTypeEnum::selection_picker)
        graphics::NotificationRenderer::resetBanner();

    menuActive = false;
    currentMenu = V3ServiceMenu::NONE;
    pendingMenu = V3ServiceMenu::NONE;
    pendingAction = V3MenuAction::NONE;
    overlayRequestPending = false;
    menuNeedsReopen = false;
    overlayRequestedAtMs = 0;

    if (redraw && screen && screen->isScreenOn())
        screen->runNow();
}

void navigateFromService(unsigned pagesForward)
{
    closeMenuInternal(false);
    if (!screen)
        return;
    for (unsigned i = 0; i < pagesForward; ++i)
        screen->showNextFrame();
    screen->runNow();
}

void processAction(V3MenuAction action)
{
    pendingAction = V3MenuAction::NONE;
    switch (action) {
    case V3MenuAction::CLOSE:
        closeMenuInternal(true);
        break;
    case V3MenuAction::NAV_MESH:
        // Local page order is Position -> Service -> Mesh Health -> Antenna Test.
        navigateFromService(1);
        break;
    case V3MenuAction::NAV_ANTENNA:
        navigateFromService(2);
        break;
    case V3MenuAction::EXPORT_LOG:
        closeMenuInternal(false);
        heltecV3DiagRequestUsbExport();
        heltecV3ServicePageRefresh();
        break;
    case V3MenuAction::CLEAR_LOG:
        closeMenuInternal(false);
        heltecV3DiagClear();
        if (screen)
            screen->showSimpleBanner("LOG CLEARED", 1500);
        break;
    case V3MenuAction::NONE:
    default:
        break;
    }
}
} // namespace

bool heltecV3ServicePageEnabled()
{
    return roleEnabled();
}

void heltecV3ServicePageDrawFrame(OLEDDisplay *display, OLEDDisplayUiState *state, int16_t x, int16_t y)
{
    if (!display || !roleEnabled())
        return;

    lastServicePageDrawMs = millis() ? millis() : 1;

    display->clear();
    graphics::drawCommonHeader(display, x, y, "Service");
    display->setColor(WHITE);
    display->setFont(FONT_SMALL);

    const int *textPos = graphics::getTextPositions(display);
    const int left = x + 2;
    const int right = x + display->getWidth() - 2;
    char line[48] = {};

    const char *role = config.device.role == meshtastic_Config_DeviceConfig_Role_ROUTER_LATE ? "ROUTER_LATE" : "REPEATER";
    display->setTextAlignment(TEXT_ALIGN_LEFT);
    display->drawString(left, textPos[1], role);
    display->setTextAlignment(TEXT_ALIGN_RIGHT);
    display->drawString(right, textPos[1], heltecV3RuntimeStateText());

    display->setTextAlignment(TEXT_ALIGN_LEFT);
    snprintf(line, sizeof(line), "BLE:%s", heltecV3RuntimeBleStateText());
    display->drawString(left, textPos[2], line);
    display->setTextAlignment(TEXT_ALIGN_RIGHT);
    snprintf(line, sizeof(line), "USB:%s", heltecV3RuntimeUsbMaintenanceActive() ? "MAINT" : "OFF");
    display->drawString(right, textPos[2], line);

    unsigned battery = 0;
    const bool haveBattery = powerStatus && powerStatus->getHasBattery();
    if (haveBattery)
        battery = powerStatus->getBatteryChargePercent();
    char uptime[20] = {};
    formatUptime(uptime, sizeof(uptime));
    display->setTextAlignment(TEXT_ALIGN_LEFT);
    snprintf(line, sizeof(line), haveBattery ? "BAT:%u%%" : "BAT:--", battery);
    display->drawString(left, textPos[3], line);
    display->setTextAlignment(TEXT_ALIGN_RIGHT);
    snprintf(line, sizeof(line), "UP:%s", uptime);
    display->drawString(right, textPos[3], line);

    const HeltecV3DiagStats stats = heltecV3DiagStats();
    display->setTextAlignment(TEXT_ALIGN_LEFT);
    if (heltecV3DiagUsbExportPending()) {
        snprintf(line, sizeof(line), "%s %u%%", heltecV3DiagUsbExportStatusText(),
                 (unsigned)heltecV3DiagUsbExportProgress());
        display->drawString(left, textPos[4], line);
    } else {
        snprintf(line, sizeof(line), "RST:%s", heltecV3DiagResetReasonText());
        display->drawString(left, textPos[4], line);
        display->setTextAlignment(TEXT_ALIGN_RIGHT);
        if (stats.bleRecoveryCount)
            snprintf(line, sizeof(line), "RCV:%u", (unsigned)stats.bleRecoveryCount);
        else
            snprintf(line, sizeof(line), "HOLD:MENU");
        display->drawString(right, textPos[4], line);
    }

    graphics::drawCommonFooter(display, x, y);
    if (state)
        graphics::UIRenderer::drawNavigationBar(display, state);
}

void heltecV3ServicePageRefresh()
{
    if (screen && screen->isScreenOn())
        screen->runNow();
}

bool heltecV3ServicePageRecentlyVisible()
{
    const uint32_t last = lastServicePageDrawMs;
    return last != 0 && (uint32_t)(millis() - last) <= 1500UL;
}

bool heltecV3ServiceMenuActive()
{
    return menuActive;
}

void heltecV3ServiceMenuOpen()
{
    if (!roleEnabled() || !screen)
        return;

    menuActive = true;
    currentMenu = V3ServiceMenu::ROOT;
    pendingMenu = V3ServiceMenu::NONE;
    pendingAction = V3MenuAction::NONE;
    overlayRequestPending = false;
    menuNeedsReopen = false;

    if (graphics::NotificationRenderer::current_notification_type == graphics::notificationTypeEnum::pairing_pin) {
        menuNeedsReopen = true;
        return;
    }
    if (graphics::NotificationRenderer::current_notification_type == graphics::notificationTypeEnum::selection_picker)
        graphics::NotificationRenderer::resetBanner();
    showMenu(V3ServiceMenu::ROOT);
}

void heltecV3ServiceMenuNext()
{
    if (!menuActive || !screen ||
        graphics::NotificationRenderer::current_notification_type != graphics::notificationTypeEnum::selection_picker)
        return;
    graphics::NotificationRenderer::inEvent.inputEvent = INPUT_BROKER_USER_PRESS;
    screen->runNow();
}

void heltecV3ServiceMenuSelect()
{
    if (!menuActive || !screen ||
        graphics::NotificationRenderer::current_notification_type != graphics::notificationTypeEnum::selection_picker)
        return;
    graphics::NotificationRenderer::inEvent.inputEvent = INPUT_BROKER_SELECT;
    screen->runNow();
}

void heltecV3ServiceMenuPump()
{
    if (!menuActive)
        return;

    const auto type = graphics::NotificationRenderer::current_notification_type;
    if (type == graphics::notificationTypeEnum::pairing_pin) {
        menuNeedsReopen = true;
        overlayRequestPending = false;
        return;
    }

    if (type == graphics::notificationTypeEnum::selection_picker) {
        overlayRequestPending = false;
        return;
    }

    if (overlayRequestPending) {
        if ((uint32_t)(millis() - overlayRequestedAtMs) < 300UL)
            return;
        overlayRequestPending = false;
        menuNeedsReopen = true;
    }

    if (type != graphics::notificationTypeEnum::none)
        return;

    if (pendingAction != V3MenuAction::NONE) {
        const V3MenuAction action = pendingAction;
        processAction(action);
        return;
    }

    if (pendingMenu != V3ServiceMenu::NONE) {
        const V3ServiceMenu next = pendingMenu;
        pendingMenu = V3ServiceMenu::NONE;
        showMenu(next);
        return;
    }

    if (menuNeedsReopen) {
        menuNeedsReopen = false;
        showMenu(currentMenu == V3ServiceMenu::NONE ? V3ServiceMenu::ROOT : currentMenu);
    }
}

void heltecV3ServiceMenuClose()
{
    closeMenuInternal(true);
}

#else

bool heltecV3ServicePageEnabled() { return false; }
void heltecV3ServicePageRefresh() {}
bool heltecV3ServicePageRecentlyVisible() { return false; }
bool heltecV3ServiceMenuActive() { return false; }
void heltecV3ServiceMenuOpen() {}
void heltecV3ServiceMenuNext() {}
void heltecV3ServiceMenuSelect() {}
void heltecV3ServiceMenuPump() {}
void heltecV3ServiceMenuClose() {}

#endif
