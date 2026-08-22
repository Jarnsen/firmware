#include "configuration.h"
#include "infrastructure/HeltecV3ServicePage.h"

#if defined(_VARIANT_HELTEC_V3) && HAS_SCREEN

#include "PowerStatus.h"
#include "graphics/Screen.h"
#include "graphics/ScreenFonts.h"
#include "infrastructure/HeltecV3BuildInfo.h"
#include "infrastructure/HeltecV3DiagnosticLog.h"
#include "infrastructure/HeltecV3Runtime.h"

#include <Arduino.h>
#include <cstdio>

namespace
{
volatile uint32_t lastServicePageDrawMs = 0;

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

void drawCentered(OLEDDisplay *display, int16_t x, int16_t y, const char *text)
{
    display->setTextAlignment(TEXT_ALIGN_CENTER);
    display->setFont(FONT_SMALL);
    display->drawString(display->getWidth() / 2 + x, y, text ? text : "");
}
} // namespace

bool heltecV3ServicePageEnabled()
{
    return roleEnabled();
}

void heltecV3ServicePageDrawFrame(OLEDDisplay *display, OLEDDisplayUiState *, int16_t x, int16_t y)
{
    if (!display || !roleEnabled())
        return;

    lastServicePageDrawMs = millis() ? millis() : 1;

    char line[72] = {};
    char uptime[24] = {};
    formatUptime(uptime, sizeof(uptime));

    drawCentered(display, x, 0 + y, "SERVICE  " JARNSEN_V3_BUILD_SHA);

    const char *role = config.device.role == meshtastic_Config_DeviceConfig_Role_ROUTER_LATE ? "ROUTER_LATE" : "REPEATER";
    snprintf(line, sizeof(line), "%s  %s", role, heltecV3RuntimeStateText());
    drawCentered(display, x, 11 + y, line);

    snprintf(line, sizeof(line), "BLE:%s  USB:%s", heltecV3RuntimeBleStateText(),
             heltecV3RuntimeUsbMaintenanceActive() ? "MAINT" : "OFF");
    drawCentered(display, x, 22 + y, line);

    unsigned battery = 0;
    bool haveBattery = powerStatus && powerStatus->getHasBattery();
    if (haveBattery)
        battery = powerStatus->getBatteryChargePercent();
    if (haveBattery)
        snprintf(line, sizeof(line), "BAT:%u%%  UP:%s", battery, uptime);
    else
        snprintf(line, sizeof(line), "BAT:--  UP:%s", uptime);
    drawCentered(display, x, 33 + y, line);

    const HeltecV3DiagStats stats = heltecV3DiagStats();
    if (heltecV3DiagUsbExportPending()) {
        const unsigned progress = heltecV3DiagUsbExportProgress();
        snprintf(line, sizeof(line), "%s  %u%%", heltecV3DiagUsbExportStatusText(), progress);
    } else {
        snprintf(line, sizeof(line), "RST:%s CR:%u RCV:%u", heltecV3DiagResetReasonText(),
                 (unsigned)stats.crashResetCount, (unsigned)stats.bleRecoveryCount);
    }
    drawCentered(display, x, 44 + y, line);

    if (heltecV3DiagUsbExportPending())
        snprintf(line, sizeof(line), "S:%u C:%u POS:%u/%u", (unsigned)stats.serviceOpenCount,
                 (unsigned)stats.bleConnectionCount, (unsigned)stats.autoPositionSaveCount,
                 (unsigned)stats.manualPositionSaveCount);
    else
        snprintf(line, sizeof(line), "HOLD: LOG EXPORT");
    drawCentered(display, x, 55 + y, line);
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

#else

bool heltecV3ServicePageEnabled() { return false; }
void heltecV3ServicePageRefresh() {}
bool heltecV3ServicePageRecentlyVisible() { return false; }

#endif
