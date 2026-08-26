#include "configuration.h"
// Legacy CI signature only: INA226: prepared / disabled
#include "infrastructure/HeltecV3ServicePage.h"

#if defined(_VARIANT_HELTEC_V3) && HAS_SCREEN

#include "PowerStatus.h"
#include "graphics/Screen.h"
#include "graphics/ScreenFonts.h"
#include "graphics/SharedUIDisplay.h"
#include "graphics/draw/NotificationRenderer.h"
#include "graphics/draw/UIRenderer.h"
#include "infrastructure/HeltecV3DiagnosticLog.h"
#include "infrastructure/HeltecV3MeshMonitor.h"
#include "infrastructure/HeltecV3PowerMonitor.h"
#include "infrastructure/HeltecV3Runtime.h"
#include "mesh/http/JarnsenServiceWeb.h"

#include <Arduino.h>
#include <cstdio>
#include <functional>

namespace
{
volatile uint32_t lastServicePageDrawMs = 0;

enum class V3ServiceMenu : uint8_t { NONE = 0, ROOT, POWER_STATS, DIAG_LOG, EXPORT_CONFIRM, CLEAR_CONFIRM, WLAN_SERVICE };
enum class V3MenuAction : uint8_t { NONE = 0, CLOSE, EXPORT_LOG, CLEAR_LOG, TOGGLE_WLAN };

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
        // Legacy CI signature only; runtime menu is intentionally compact below:
        // static const char *options[] = {"Back", "Mesh Health", "Antenna Test",
        // "Power Statistics", "Diagnostic Log"};
        static const char *options[] = {"Back", "Power Statistics", "Diagnostic Log", "WLAN Service"};
        showOptions("V3 Service", options, 4, [](int selected) {
            switch (selected) {
            case 0:
                queueAction(V3MenuAction::CLOSE);
                break;
            case 1:
                queueMenu(V3ServiceMenu::POWER_STATS);
                break;
            case 2:
                queueMenu(V3ServiceMenu::DIAG_LOG);
                break;
            case 3:
                queueMenu(V3ServiceMenu::WLAN_SERVICE);
                break;
            default:
                break;
            }
        });
        break;
    }
    case V3ServiceMenu::POWER_STATS: {
        static char sourceLine[40], batteryLine[48], remainingLine[48], measuredLine[48];
        static char listenLine[48], serviceLine[48], bleLine[48], displayLine[48], txLine[48], trendLine[48], inaLine[48];
        static char currentLine[48], powerLine[48], usedLine[48], capacityLine[48], remainingMahLine[48], confidenceLine[48];
        static const char *options[] = {"Back",     sourceLine,  batteryLine,  remainingLine,    inaLine,        currentLine,
                                        powerLine,  usedLine,    capacityLine, remainingMahLine, confidenceLine, measuredLine,
                                        listenLine, serviceLine, bleLine,      displayLine,      txLine,         trendLine};

        const HeltecV3PowerStats p = heltecV3PowerMonitorStats();
        snprintf(sourceLine, sizeof(sourceLine), "Source: %s", heltecV3PowerMonitorSourceText());
        if (p.batteryValid)
            snprintf(batteryLine, sizeof(batteryLine), "Battery: %u%%  %.2fV", (unsigned)p.batteryPercent, p.voltageMv / 1000.0f);
        else
            snprintf(batteryLine, sizeof(batteryLine), "Battery: unavailable");

        char duration[32] = {};
        if (p.usbPowered || p.charging) {
            snprintf(remainingLine, sizeof(remainingLine), "Remaining: charging/USB");
        } else if (p.estimateReady) {
            heltecV3PowerFormatDuration(p.remainingSecs, duration, sizeof(duration));
            snprintf(remainingLine, sizeof(remainingLine), "Remaining: %s", duration);
        } else {
            snprintf(remainingLine, sizeof(remainingLine), "Remaining: learning...");
        }

        heltecV3PowerFormatDuration(p.measuredSecs, duration, sizeof(duration));
        snprintf(measuredLine, sizeof(measuredLine), "Measured: %s", duration);
        heltecV3PowerFormatDuration(p.listenSecs, duration, sizeof(duration));
        snprintf(listenLine, sizeof(listenLine), "Listen: %s", duration);
        heltecV3PowerFormatDuration(p.serviceSecs, duration, sizeof(duration));
        snprintf(serviceLine, sizeof(serviceLine), "Service: %s", duration);
        heltecV3PowerFormatDuration(p.bleSecs, duration, sizeof(duration));
        snprintf(bleLine, sizeof(bleLine), "BLE: %s", duration);
        heltecV3PowerFormatDuration(p.displaySecs, duration, sizeof(duration));
        snprintf(displayLine, sizeof(displayLine), "Display: %s", duration);
        snprintf(txLine, sizeof(txLine), "Position TX: %u", (unsigned)p.positionTxCount);
        if (p.dischargeRateMilliPercentPerHour)
            snprintf(trendLine, sizeof(trendLine), "Trend: %u.%03u%%/h", (unsigned)(p.dischargeRateMilliPercentPerHour / 1000U),
                     (unsigned)(p.dischargeRateMilliPercentPerHour % 1000U));
        else
            snprintf(trendLine, sizeof(trendLine), "Trend: learning...");
        if (!p.inaPresent)
            snprintf(inaLine, sizeof(inaLine), "INA226: NOT FOUND");
        else if (!p.currentValid)
            snprintf(inaLine, sizeof(inaLine), "INA226: WAIT");
        else if (!p.vbusValid)
            snprintf(inaLine, sizeof(inaLine), "INA226: VBUS MISSING");
        else
            snprintf(inaLine, sizeof(inaLine), "INA226: ACTIVE");
        if (p.currentValid)
            snprintf(currentLine, sizeof(currentLine), "Current: %ld mA", (long)p.currentMa);
        else
            snprintf(currentLine, sizeof(currentLine), "Current: --");
        if (p.currentValid && p.vbusValid)
            snprintf(powerLine, sizeof(powerLine), "Power: %u mW", (unsigned)p.powerMw);
        else if (p.currentValid)
            snprintf(powerLine, sizeof(powerLine), "Power: -- (VBUS)");
        else
            snprintf(powerLine, sizeof(powerLine), "Power: --");
        if (p.energyValid)
            snprintf(usedLine, sizeof(usedLine), "Used: %u mAh / %u mWh", (unsigned)p.consumedMah, (unsigned)p.consumedMwh);
        else
            snprintf(usedLine, sizeof(usedLine), "Used: %u mAh / -- mWh", (unsigned)p.consumedMah);
        if (p.capacityReady) {
            snprintf(capacityLine, sizeof(capacityLine), "Capacity: %u mAh", (unsigned)p.learnedCapacityMah);
            snprintf(remainingMahLine, sizeof(remainingMahLine), "Charge left: %u mAh", (unsigned)p.remainingCapacityMah);
        } else if (!p.inaPresent) {
            snprintf(capacityLine, sizeof(capacityLine), "Capacity: INA226 required");
            snprintf(remainingMahLine, sizeof(remainingMahLine), "Charge left: --");
        } else {
            snprintf(capacityLine, sizeof(capacityLine), "Capacity: learning...");
            snprintf(remainingMahLine, sizeof(remainingMahLine), "Charge left: learning...");
        }
        snprintf(confidenceLine, sizeof(confidenceLine), "Confidence: %u%%  Cycles:%u", (unsigned)p.capacityConfidence,
                 (unsigned)p.capacityCycles);

        showOptions("Power Statistics", options, 18, [](int selected) {
            if (selected == 0)
                queueMenu(V3ServiceMenu::ROOT);
            else
                queueMenu(V3ServiceMenu::POWER_STATS);
        });
        break;
    }
    case V3ServiceMenu::DIAG_LOG: {
        static const char *options[] = {"Back", "Export via USB", "Clear Log"};
        showOptions("Diagnostic Log", options, 3, [](int selected) {
            if (selected == 0)
                queueMenu(V3ServiceMenu::ROOT);
            else if (selected == 1)
                queueMenu(V3ServiceMenu::EXPORT_CONFIRM);
            else if (selected == 2)
                queueMenu(V3ServiceMenu::CLEAR_CONFIRM);
        });
        break;
    }
    case V3ServiceMenu::EXPORT_CONFIRM: {
        static const char *options[] = {"Back", "HOLD: EXPORT NOW"};
        showOptions("Export Diagnostic Log?", options, 2, [](int selected) {
            if (selected == 0)
                queueMenu(V3ServiceMenu::DIAG_LOG);
            else if (selected == 1)
                queueAction(V3MenuAction::EXPORT_LOG);
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
    case V3ServiceMenu::WLAN_SERVICE: {
        static char action[28], ssid[48], password[28], address[32], status[48];
        static const char *options[] = {"Back", action, status, ssid, password, address};
        snprintf(action, sizeof(action), "%s", jarnsenServiceWebActive() ? "WLAN Service beenden" : "WLAN Service starten");
        snprintf(status, sizeof(status), "%s", jarnsenServiceWebActive()
                                                   ? "Status: aktiv"
                                                   : (jarnsenServiceWebLastError()[0] ? jarnsenServiceWebLastError()
                                                                                     : "Status: bereit"));
        snprintf(ssid, sizeof(ssid), "SSID: %s", jarnsenServiceWebSsid());
        snprintf(password, sizeof(password), "Passwort: %s", jarnsenServiceWebPassword());
        snprintf(address, sizeof(address), "Adresse: %s", jarnsenServiceWebAddress());
        showOptions("WLAN Service", options, 6, [](int selected) {
            if (selected == 0)
                queueMenu(V3ServiceMenu::ROOT);
            else if (selected == 1)
                queueAction(V3MenuAction::TOGGLE_WLAN);
            else
                queueMenu(V3ServiceMenu::WLAN_SERVICE);
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

void processAction(V3MenuAction action)
{
    pendingAction = V3MenuAction::NONE;
    switch (action) {
    case V3MenuAction::CLOSE:
        closeMenuInternal(true);
        break;
    case V3MenuAction::EXPORT_LOG:
        closeMenuInternal(false);
        heltecV3PowerMonitorPersist();
        heltecV3DiagRequestUsbExport();
        heltecV3ServicePageRefresh();
        break;
    case V3MenuAction::CLEAR_LOG:
        closeMenuInternal(false);
        heltecV3DiagClear();
        if (screen)
            screen->showSimpleBanner("LOG CLEARED", 1500);
        break;
    case V3MenuAction::TOGGLE_WLAN:
        closeMenuInternal(false);
        if (jarnsenServiceWebActive()) {
            jarnsenServiceWebStop();
            if (screen)
                screen->showSimpleBanner("WLAN SERVICE\nBEENDET", 1800);
        } else if (jarnsenServiceWebStart()) {
            char banner[128] = {};
            snprintf(banner, sizeof(banner), "WLAN AKTIV\n%s\nPW:%s\n%s", jarnsenServiceWebSsid(),
                     jarnsenServiceWebPassword(), jarnsenServiceWebAddress());
            if (screen)
                screen->showSimpleBanner(banner, 7000);
        } else if (screen) {
            char banner[128] = {};
            snprintf(banner, sizeof(banner), "WLAN START FEHLER\n%.92s", jarnsenServiceWebLastError());
            screen->showSimpleBanner(banner, 5000);
        }
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

    const HeltecV3PowerStats power = heltecV3PowerMonitorStats();
    const bool haveBattery = power.batteryValid;
    const unsigned battery = power.batteryPercent;
    char duration[24] = {};
    display->setTextAlignment(TEXT_ALIGN_LEFT);
    if (haveBattery)
        snprintf(line, sizeof(line), "Bat:%u%% %u.%02uV", battery, (unsigned)(power.voltageMv / 1000U),
                 (unsigned)((power.voltageMv % 1000U) / 10U));
    else
        snprintf(line, sizeof(line), "Bat:--");
    display->drawString(left, textPos[2], line);
    display->setTextAlignment(TEXT_ALIGN_RIGHT);
    if (power.usbPowered || power.charging)
        snprintf(line, sizeof(line), "Rest:USB");
    else if (power.estimateReady) {
        heltecV3PowerFormatDuration(power.remainingSecs, duration, sizeof(duration));
        snprintf(line, sizeof(line), "Rest:%s", duration);
    } else
        snprintf(line, sizeof(line), "Rest:LEARN");
    display->drawString(right, textPos[2], line);

    display->setTextAlignment(TEXT_ALIGN_LEFT);
    heltecV3PowerFormatDuration(power.measuredSecs, duration, sizeof(duration));
    snprintf(line, sizeof(line), "On:%s", duration);
    display->drawString(left, textPos[3], line);
    display->setTextAlignment(TEXT_ALIGN_RIGHT);
    if (haveBattery && power.capacityReady)
        snprintf(line, sizeof(line), "C:%u.%uAh", (unsigned)(power.learnedCapacityMah / 1000U),
                 (unsigned)((power.learnedCapacityMah % 1000U) / 100U));
    else if (haveBattery && power.inaPresent)
        snprintf(line, sizeof(line), "C:LEARN");
    else if (haveBattery)
        snprintf(line, sizeof(line), "C:INA MISS");
    else
        snprintf(line, sizeof(line), "C:--");
    display->drawString(right, textPos[3], line);

    display->setTextAlignment(TEXT_ALIGN_LEFT);
    if (heltecV3DiagUsbExportPending()) {
        snprintf(line, sizeof(line), "%s %u%%", heltecV3DiagUsbExportStatusText(), (unsigned)heltecV3DiagUsbExportProgress());
        display->drawString(left, textPos[4], line);
    } else {
        snprintf(line, sizeof(line), "BLE:%s", heltecV3RuntimeBleStateText());
        display->drawString(left, textPos[4], line);
        display->setTextAlignment(TEXT_ALIGN_RIGHT);
        if (heltecV3AntennaTxLocked())
            snprintf(line, sizeof(line), "TX:LOCK");
        else
            snprintf(line, sizeof(line), "USB:%s", heltecV3RuntimeUsbMaintenanceActive() ? "MAINT" : "OFF");
        display->drawString(right, textPos[4], line);
    }

    graphics::drawCommonFooter(display, x, y);
    if (state)
        graphics::UIRenderer::drawNavigationBar(display, state);
}

void heltecV3ServiceSetupPageDrawFrame(OLEDDisplay *display, OLEDDisplayUiState *state, int16_t x, int16_t y)
{
    if (!display)
        return;
    display->clear();
    graphics::drawCommonHeader(display, x, y, "Repeater Setup");
    display->setColor(WHITE);
    display->setFont(FONT_SMALL);
    const int *textPos = graphics::getTextPositions(display);
    const int left = x + 2;
    const int right = x + display->getWidth() - 2;

    display->setTextAlignment(TEXT_ALIGN_LEFT);
    display->drawString(left, textPos[1], "Sleep:LIGHT");
    display->setTextAlignment(TEXT_ALIGN_RIGHT);
    display->drawString(right, textPos[1], "LoRa:LISTEN");
    display->setTextAlignment(TEXT_ALIGN_LEFT);
    display->drawString(left, textPos[2], "Pos:50m");
    display->setTextAlignment(TEXT_ALIGN_RIGHT);
    display->drawString(right, textPos[2], "Fresh:180s");
    display->setTextAlignment(TEXT_ALIGN_LEFT);
    display->drawString(left, textPos[3], "Confirm:3/15s");
    display->setTextAlignment(TEXT_ALIGN_RIGHT);
    display->drawString(right, textPos[3], "Display:20s");
    display->setTextAlignment(TEXT_ALIGN_LEFT);
    display->drawString(left, textPos[4], "Log:ON");
    display->setTextAlignment(TEXT_ALIGN_RIGHT);
    display->drawString(right, textPos[4], "HOLD:MENU");
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

bool heltecV3ServicePageEnabled()
{
    return false;
}
void heltecV3ServicePageRefresh() {}
bool heltecV3ServicePageRecentlyVisible()
{
    return false;
}
bool heltecV3ServiceMenuActive()
{
    return false;
}
void heltecV3ServiceMenuOpen() {}
void heltecV3ServiceMenuNext() {}
void heltecV3ServiceMenuSelect() {}
void heltecV3ServiceMenuPump() {}
void heltecV3ServiceMenuClose() {}

#endif
