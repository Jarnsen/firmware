#include "jarnsen/adapters/JarnsenDisplayRuntime.h"

#include "configuration.h"

#if HAS_SCREEN && !defined(HELTEC_TRACKER_V1_1) && \
    (defined(HELTEC_V3) || defined(_VARIANT_HELTEC_V3) || defined(HELTEC_V4) || defined(SEEED_WIO_TRACKER_L1) || \
     defined(TBEAM_V10) || defined(LILYGO_TBEAM_S3_CORE))

#include "BluetoothStatus.h"
#include "GPSStatus.h"
#include "NodeDB.h"
#include "PowerStatus.h"
#include "gps/RTC.h"
#include "graphics/Screen.h"
#include "graphics/ScreenFonts.h"
#include "jarnsen/adapters/JarnsenLegacyStatusBridge.h"
#include "jarnsen/core/build/JarnsenBuildInfo.h"
#include "jarnsen/core/display/JarnsenDisplayModel.h"
#include "jarnsen/core/mesh/JarnsenRadioProfiles.h"
#include "jarnsen/core/power/JarnsenBatteryLearning.h"
#include "jarnsen/core/runtime/JarnsenTakRepeaterPolicy.h"
#include "jarnsen/core/status/JarnsenStatusProvider.h"
#include "jarnsen/core/position/JarnsenPositionCore.h"
#include "mesh/Channels.h"
#include "mesh/MeshModule.h"
#include "mesh/http/JarnsenServiceWeb.h"

#include <Arduino.h>
#include <OLEDDisplay.h>
#include <algorithm>
#include <cmath>
#include <cstdio>
#include <cstring>

namespace
{
using jarnsen::DisplayPage;

enum class MenuView : uint8_t {
    NONE = 0,
    ROOT,
    PROFILE,
    SYSTEM,
};

DisplayPage currentPage = DisplayPage::MGRS;
MenuView menuView = MenuView::NONE;
uint8_t menuSelection = 0;
bool stockUiActive = false;
const char *profileError = nullptr;
bool suppressNextOneButtonEvent = false;

const char *boardLabel()
{
#if defined(HELTEC_V3) || defined(_VARIANT_HELTEC_V3)
    return "HELTEC V3";
#elif defined(HELTEC_V4)
    return "HELTEC V4";
#elif defined(SEEED_WIO_TRACKER_L1)
    return "WIO L1";
#elif defined(TBEAM_V10)
    return "T-BEAM";
#elif defined(LILYGO_TBEAM_S3_CORE)
    return "T-BEAM SUPREME";
#else
    return "JARNSEN";
#endif
}

const char *roleLabel()
{
    jarnsen::ensureLegacyStatusBridge();
    switch (jarnsen::activeDeviceRoleOr(jarnsen::DeviceRole::UNCONFIGURED)) {
    case jarnsen::DeviceRole::TAK:
        return "TAK";
    case jarnsen::DeviceRole::TAK_TRACKER:
        return "TAK TRACKER";
    case jarnsen::DeviceRole::TAK_REPEATER:
        return "TAK REPEATER";
    case jarnsen::DeviceRole::DRONE_REPEATER:
        return "DRONE REPEATER";
    default:
        return "JARNSEN";
    }
}

const char *regionLabel()
{
    switch (config.lora.region) {
    case meshtastic_Config_LoRaConfig_RegionCode_EU_868:
        return "EU868";
    case meshtastic_Config_LoRaConfig_RegionCode_US:
        return "US";
    default:
        return "REGION";
    }
}

const char *presetLabel()
{
    switch (config.lora.modem_preset) {
    case meshtastic_Config_LoRaConfig_ModemPreset_LONG_FAST:
        return "LONG FAST";
    case meshtastic_Config_LoRaConfig_ModemPreset_LONG_SLOW:
        return "LONG SLOW";
    case meshtastic_Config_LoRaConfig_ModemPreset_MEDIUM_FAST:
        return "MED FAST";
    case meshtastic_Config_LoRaConfig_ModemPreset_MEDIUM_SLOW:
        return "MED SLOW";
    case meshtastic_Config_LoRaConfig_ModemPreset_SHORT_FAST:
        return "SHORT FAST";
    case meshtastic_Config_LoRaConfig_ModemPreset_SHORT_SLOW:
        return "SHORT SLOW";
    default:
        return "CUSTOM";
    }
}

DisplayPage previousPage(DisplayPage page)
{
    switch (page) {
    case DisplayPage::MGRS:
        return DisplayPage::SYSTEM;
    case DisplayPage::NODE_STATUS:
        return DisplayPage::MGRS;
    case DisplayPage::RADIO:
        return DisplayPage::NODE_STATUS;
    case DisplayPage::NETWORK:
        return DisplayPage::RADIO;
    case DisplayPage::SYSTEM:
    case DisplayPage::SERVICE:
    default:
        return DisplayPage::NETWORK;
    }
}

void drawFittedCentered(OLEDDisplay *display, int16_t centerX, int16_t y, const char *text, int maxWidth, bool preferMedium)
{
    if (!display || !text || maxWidth <= 0)
        return;

    char fitted[64] = {};
    std::snprintf(fitted, sizeof(fitted), "%s", text);
    display->setTextAlignment(TEXT_ALIGN_CENTER);
    display->setFont(preferMedium ? FONT_MEDIUM : FONT_SMALL);

    // Compact 128x64 panels (especially Heltec V3) must never paint outside
    // their content band. Prefer the normal medium font, then fall back to the
    // small font and finally trim by rendered pixel width.
    if (preferMedium && display->getStringWidth(fitted) > maxWidth)
        display->setFont(FONT_SMALL);
    size_t len = std::strlen(fitted);
    while (len > 1U && display->getStringWidth(fitted) > maxWidth)
        fitted[--len] = '\0';

    display->drawString(centerX, y, fitted);
}

void drawBattery(OLEDDisplay *display, int16_t x, int16_t y)
{
    if (!display)
        return;
    const int w = display->getWidth();
    display->setTextAlignment(TEXT_ALIGN_RIGHT);
    display->setFont(FONT_SMALL);
    if (powerStatus && powerStatus->getHasBattery()) {
        const unsigned pct = powerStatus->getBatteryChargePercent();
        char text[12] = {};
        std::snprintf(text, sizeof(text), "%s%u%%", powerStatus->getIsCharging() ? "+" : "", pct);
        display->drawString(x + w - 2, y + 1, text);
        const int iconX = x + w - 39;
        const int iconY = y + 5;
        display->drawRect(iconX, iconY, 12, 6);
        display->fillRect(iconX + 12, iconY + 2, 2, 2);
        const int fill = std::min(10, static_cast<int>((pct * 10U) / 100U));
        if (fill > 0)
            display->fillRect(iconX + 1, iconY + 1, fill, 4);
    } else {
        display->drawString(x + w - 2, y + 1, "--");
    }
}

void drawHeader(OLEDDisplay *display, int16_t x, int16_t y, const char *title)
{
    display->setTextAlignment(TEXT_ALIGN_CENTER);
    display->setFont(FONT_SMALL);
    drawFittedCentered(display, x + display->getWidth() / 2, y + 1, title ? title : "",
                       std::max(24, display->getWidth() - 64), false);
    drawBattery(display, x, y);
}

void drawPageNumber(OLEDDisplay *display, int16_t x, int16_t y, DisplayPage page)
{
    char text[12] = {};
    std::snprintf(text, sizeof(text), "%u/%u", (unsigned)jarnsen::displayPageNumber(page),
                  (unsigned)jarnsen::displayPageCount());
    display->setFont(FONT_SMALL);
    display->setTextAlignment(TEXT_ALIGN_LEFT);
    display->drawString(x + 2, y + 1, text);
}

bool ownPosition(meshtastic_PositionLite &position)
{
    if (!nodeDB)
        return false;
    if (!nodeDB->copyNodePosition(nodeDB->getNodeNum(), position))
        return false;
    return position.latitude_i != 0 || position.longitude_i != 0;
}

const char *fixText()
{
    if (!gpsStatus || !gpsStatus->getHasLock())
        return "NO FIX";
    if (localPosition.fix_type >= 3)
        return "3D FIX";
    if (localPosition.fix_type == 2)
        return "2D FIX";
    return "GPS FIX";
}

unsigned horizontalAccuracyMeters()
{
    if (config.position.fixed_position || !gpsStatus || !gpsStatus->getHasLock())
        return 0;
    uint32_t dop = localPosition.HDOP;
    if (dop == 0)
        dop = gpsStatus->getDOP();
    if (dop == 0)
        return 0;
    const uint32_t accuracyMm = localPosition.gps_accuracy ? localPosition.gps_accuracy : 3000U;
    const double meters = (dop / 100.0) * (accuracyMm / 1000.0);
    return std::max(1U, static_cast<unsigned>(std::ceil(meters)));
}

void splitMgrs(const char *mgrs, char *zoneGrid, size_t zoneSize, char *digits, size_t digitSize)
{
    if (!mgrs || !zoneGrid || !digits)
        return;
    zoneGrid[0] = '\0';
    digits[0] = '\0';
    const char *second = std::strchr(mgrs, ' ');
    const char *third = second ? std::strchr(second + 1, ' ') : nullptr;
    if (!third) {
        std::snprintf(zoneGrid, zoneSize, "%s", mgrs);
        return;
    }
    const size_t prefix = std::min(zoneSize - 1, static_cast<size_t>(third - mgrs));
    std::memcpy(zoneGrid, mgrs, prefix);
    zoneGrid[prefix] = '\0';
    std::snprintf(digits, digitSize, "%s", third + 1);
}

void drawMgrs(OLEDDisplay *display, int16_t x, int16_t y)
{
    const int w = display->getWidth();
    const int h = display->getHeight();
    const auto bands = jarnsen::displayBands(h);
    meshtastic_PositionLite position = meshtastic_PositionLite_init_default;
    const bool havePosition = ownPosition(position);
    const bool fixed = config.position.fixed_position && havePosition;
    const bool liveFix = gpsStatus && gpsStatus->getHasLock() && havePosition;

    if (!fixed && !liveFix) {
        const bool waiting = gpsStatus && gpsStatus->getIsConnected();
        drawHeader(display, x, y, waiting ? "GPS WAIT" : "MGRS");
        display->setTextAlignment(TEXT_ALIGN_CENTER);
        display->setFont(FONT_MEDIUM);
        display->drawString(x + w / 2,
                            y + bands.middleY + bands.middleHeight / 2 - FONT_HEIGHT_MEDIUM / 2,
                            "KEINE POSITION");
        display->setFont(FONT_SMALL);
        display->drawString(x + w / 2, y + bands.bottomY + 2,
                            waiting ? "GPS     NO FIX       --" : "QUELLE --           --");
        return;
    }

    char mgrs[32] = {};
    if (!jarnsenPositionFormatMgrs10(position.latitude_i, position.longitude_i, mgrs, sizeof(mgrs))) {
        drawHeader(display, x, y, "MGRS");
        display->setTextAlignment(TEXT_ALIGN_CENTER);
        display->setFont(FONT_MEDIUM);
        display->drawString(x + w / 2, y + bands.middleY + 8, "KEINE POSITION");
        return;
    }

    char zoneGrid[12] = {};
    char digits[20] = {};
    splitMgrs(mgrs, zoneGrid, sizeof(zoneGrid), digits, sizeof(digits));
    display->setTextAlignment(TEXT_ALIGN_CENTER);
    display->setFont(FONT_MEDIUM);
    display->drawString(x + w / 2, y + 1, zoneGrid);
    drawBattery(display, x, y);

    display->setFont(FONT_LARGE);
    display->drawString(x + w / 2,
                        y + bands.middleY + std::max(0, (static_cast<int>(bands.middleHeight) - FONT_HEIGHT_LARGE) / 2),
                        digits);

    const char *motion = fixed ? "FIXED" : (jarnsen::takRepeaterRoleActive() ? "MOBILE" : "MOVING");
    const char *fix = fixed ? "STORED" : fixText();
    char accuracy[12] = "--";
    const unsigned accuracyM = fixed ? 0U : horizontalAccuracyMeters();
    if (accuracyM)
        std::snprintf(accuracy, sizeof(accuracy), "+/-%um", accuracyM);

    display->setFont(FONT_SMALL);
    display->setTextAlignment(TEXT_ALIGN_LEFT);
    display->drawString(x + 2, y + bands.bottomY + 2, motion);
    display->setTextAlignment(TEXT_ALIGN_CENTER);
    display->drawString(x + w / 2, y + bands.bottomY + 2, fix);
    display->setTextAlignment(TEXT_ALIGN_RIGHT);
    display->drawString(x + w - 2, y + bands.bottomY + 2, accuracy);
}

void drawNode(OLEDDisplay *display, int16_t x, int16_t y)
{
    const int w = display->getWidth();
    const int h = display->getHeight();
    const auto bands = jarnsen::displayBands(h);

    display->setFont(FONT_SMALL);
    display->setTextAlignment(TEXT_ALIGN_LEFT);
    display->drawString(x + 2, y + 1, "2/5");
    drawBattery(display, x, y);

    char name[32] = "NODE";
    const meshtastic_NodeInfoLite *node = nodeDB ? nodeDB->getMeshNode(nodeDB->getNodeNum()) : nullptr;
    if (node && nodeInfoLiteHasUser(node) && node->long_name[0])
        std::snprintf(name, sizeof(name), "%.24s", node->long_name);

    const int maxNameWidth = std::max(1, w - 8);
    int nameHeight = FONT_HEIGHT_LARGE;
    display->setFont(FONT_LARGE);
    if (display->getStringWidth(name) > maxNameWidth) {
        display->setFont(FONT_MEDIUM);
        nameHeight = FONT_HEIGHT_MEDIUM;
    }
    if (display->getStringWidth(name) > maxNameWidth) {
        display->setFont(FONT_SMALL);
        nameHeight = FONT_HEIGHT_SMALL;
    }
    while (std::strlen(name) > 1U && display->getStringWidth(name) > maxNameWidth)
        name[std::strlen(name) - 1U] = '\0';

    display->setTextAlignment(TEXT_ALIGN_CENTER);
    display->drawString(x + w / 2,
                        y + bands.middleY + std::max(0, (static_cast<int>(bands.middleHeight) - nameHeight) / 2),
                        name);

    const auto learned = jarnsen::batteryLearningStats();
    char ontime[16] = {};
    char remaining[16] = "LERNT";
    jarnsen::batteryLearningFormatCompactDuration(millis() / 1000UL, ontime, sizeof(ontime));
    if (learned.usbPowered)
        std::snprintf(remaining, sizeof(remaining), "USB");
    else if (learned.charging)
        std::snprintf(remaining, sizeof(remaining), "LAEDT");
    else if (learned.estimateReady)
        jarnsen::batteryLearningFormatCompactDuration(learned.remainingSecs, remaining, sizeof(remaining));

    char onText[24] = {};
    char restText[24] = {};
    std::snprintf(onText, sizeof(onText), "ON %s", ontime);
    std::snprintf(restText, sizeof(restText), "REST %s", remaining);
    display->setFont(FONT_SMALL);
    display->setTextAlignment(TEXT_ALIGN_LEFT);
    display->drawString(x + 2, y + bands.bottomY + 2, onText);
    display->setTextAlignment(TEXT_ALIGN_RIGHT);
    display->drawString(x + w - 2, y + bands.bottomY + 2, restText);
}

void drawRadio(OLEDDisplay *display, int16_t x, int16_t y)
{
    const int w = display->getWidth();
    const int h = display->getHeight();
    const auto bands = jarnsen::displayBands(h);
    drawBattery(display, x, y);
    display->setFont(FONT_SMALL);
    display->setTextAlignment(TEXT_ALIGN_LEFT);
    display->drawString(x + 2, y + 1, regionLabel());
    display->setTextAlignment(TEXT_ALIGN_CENTER);
    display->drawString(x + w / 2, y + 1, jarnsen::radioProfileLabel(jarnsen::radioProfileActive()));

    display->setFont(FONT_MEDIUM);
    display->drawString(x + w / 2,
                        y + bands.middleY + std::max(0, (static_cast<int>(bands.middleHeight) - FONT_HEIGHT_MEDIUM) / 2),
                        presetLabel());

    char bottom[64] = {};
    if (config.lora.tx_power > 0)
        std::snprintf(bottom, sizeof(bottom), "TX%ddBm   RSSI--   SNR--", (int)config.lora.tx_power);
    else
        std::snprintf(bottom, sizeof(bottom), "TX AUTO   RSSI--   SNR--");
    display->setFont(FONT_SMALL);
    display->drawString(x + w / 2, y + bands.bottomY + 2, bottom);
}

size_t otherNodeCount()
{
    if (!nodeDB)
        return 0;
    size_t count = 0;
    for (size_t i = 0; i < nodeDB->getNumMeshNodes(); ++i) {
        const meshtastic_NodeInfoLite *n = nodeDB->getMeshNodeByIndex(i);
        if (n && n->num != nodeDB->getNodeNum())
            ++count;
    }
    return count;
}

size_t directNodeCount()
{
    if (!nodeDB)
        return 0;
    size_t count = 0;
    for (size_t i = 0; i < nodeDB->getNumMeshNodes(); ++i) {
        const meshtastic_NodeInfoLite *n = nodeDB->getMeshNodeByIndex(i);
        if (n && n->num != nodeDB->getNodeNum() && n->has_hops_away && n->hops_away == 0)
            ++count;
    }
    return count;
}

uint32_t newestOtherNodeAge()
{
    if (!nodeDB)
        return UINT32_MAX;
    uint32_t best = UINT32_MAX;
    for (size_t i = 0; i < nodeDB->getNumMeshNodes(); ++i) {
        const meshtastic_NodeInfoLite *n = nodeDB->getMeshNodeByIndex(i);
        if (!n || n->num == nodeDB->getNodeNum())
            continue;
        const uint32_t age = sinceLastSeen(n);
        if (age < best)
            best = age;
    }
    return best;
}

void drawNetwork(OLEDDisplay *display, int16_t x, int16_t y)
{
    const int w = display->getWidth();
    const int h = display->getHeight();
    const auto bands = jarnsen::displayBands(h);
    const char *channel = channels.getName(channels.getPrimaryIndex());
    drawHeader(display, x, y, channel && channel[0] ? channel : "NETZ");

    char middle[32] = {};
    char bottom[64] = {};
    if (jarnsen::takRepeaterRoleActive()) {
        const auto repeater = jarnsen::takRepeaterStats();
        const char *mode = repeater.positionMode == jarnsen::TakRepeaterPositionMode::FIXED
                               ? "FIX"
                               : repeater.positionMode == jarnsen::TakRepeaterPositionMode::MOBILE ? "MOB" : "--";
        std::snprintf(middle, sizeof(middle), "TAK REPEATER %s", mode);
        std::snprintf(bottom, sizeof(bottom), "CU%u%%  RX%u  TX%u  FWD%u",
                      (unsigned)(repeater.channelUtilizationX10 / 10U), (unsigned)repeater.rxPackets,
                      (unsigned)repeater.txPackets, (unsigned)repeater.forwardedPackets);
    } else {
        std::snprintf(middle, sizeof(middle), "%u NODES", (unsigned)otherNodeCount());
        char age[16] = "--";
        const uint32_t newest = newestOtherNodeAge();
        if (newest != UINT32_MAX) {
            if (newest < 60)
                std::snprintf(age, sizeof(age), "%us", (unsigned)newest);
            else
                std::snprintf(age, sizeof(age), "%umin", (unsigned)(newest / 60U));
        }
        const size_t online = nodeDB ? std::max<size_t>(0, nodeDB->getNumOnlineMeshNodes(true)) : 0;
        std::snprintf(bottom, sizeof(bottom), "DIRECT %u   ONLINE %u   %s",
                      (unsigned)directNodeCount(), (unsigned)online, age);
    }
    display->setTextAlignment(TEXT_ALIGN_CENTER);
    display->setFont(FONT_MEDIUM);
    display->drawString(x + w / 2,
                        y + bands.middleY + std::max(0, (static_cast<int>(bands.middleHeight) - FONT_HEIGHT_MEDIUM) / 2),
                        middle);
    display->setFont(FONT_SMALL);
    display->drawString(x + w / 2, y + bands.bottomY + 2, bottom);
}

void drawSystem(OLEDDisplay *display, int16_t x, int16_t y)
{
    const int w = display->getWidth();
    const int h = display->getHeight();
    const auto bands = jarnsen::displayBands(h);
    const auto learned = jarnsen::batteryLearningStats();
    drawHeader(display, x, y, "SYSTEM");

    char uptime[24] = {};
    jarnsen::batteryLearningFormatDuration(millis() / 1000UL, uptime, sizeof(uptime));
    char remaining[24] = "--";
    if (!learned.usbPowered && !learned.charging && learned.estimateReady)
        jarnsen::batteryLearningFormatDuration(learned.remainingSecs, remaining, sizeof(remaining));

    const unsigned voltageMv =
        powerStatus && powerStatus->isInitialized() && powerStatus->getHasBattery() ? (unsigned)powerStatus->getBatteryVoltageMv() : 0U;
    char line1[64] = {};
    char line2[64] = {};
    char line3[64] = {};
    if (voltageMv)
        std::snprintf(line1, sizeof(line1), "UP %-8s      %u.%03u V", uptime, voltageMv / 1000U, voltageMv % 1000U);
    else
        std::snprintf(line1, sizeof(line1), "UP %-8s          -- V", uptime);
    std::snprintf(line2, sizeof(line2), "REST %-8s        -- mA", remaining);
    std::snprintf(line3, sizeof(line3), "VOLL --             -- W");

    display->setTextAlignment(TEXT_ALIGN_CENTER);
    display->setFont(FONT_SMALL);
    const int top = y + bands.middleY + 2;
    display->drawString(x + w / 2, top, line1);
    display->drawString(x + w / 2, top + 11, line2);
    display->drawString(x + w / 2, top + 22, line3);

    char bottom[64] = {};
    const char *source = learned.charging ? "CHARGE" : (learned.usbPowered ? "USB" : "BAT");
    const char *battery = learned.batteryValid ? "OK" : "--";
    std::snprintf(bottom, sizeof(bottom), "%s      INA OFF      %s", source, battery);
    display->drawString(x + w / 2, y + bands.bottomY + 2, bottom);
}

void drawService(OLEDDisplay *display, int16_t x, int16_t y)
{
    const int w = display->getWidth();
    const int h = display->getHeight();
    const auto bands = jarnsen::displayBands(h);
    drawHeader(display, x, y, "SERVICE");

    const char *state = "READY";
    char detail[64] = {};
    if (jarnsenServiceWebActive()) {
        state = "AP ON";
        std::snprintf(detail, sizeof(detail), "WLAN   %s", jarnsenServiceWebAddress());
    } else if (bluetoothStatus &&
               bluetoothStatus->getConnectionState() == meshtastic::BluetoothStatus::ConnectionState::CONNECTED) {
        state = "CONNECTED";
        std::snprintf(detail, sizeof(detail), "BLE   OK");
    } else if (jarnsen::takRepeaterRoleActive() && jarnsen::takRepeaterStats().serviceActive) {
        state = "READY";
        std::snprintf(detail, sizeof(detail), "USB %s   BLE READY",
                      powerStatus && powerStatus->getHasUSB() ? "ON" : "--");
    } else {
        std::snprintf(detail, sizeof(detail), "USB %s   BLE READY",
                      powerStatus && powerStatus->getHasUSB() ? "ON" : "--");
    }

    display->setTextAlignment(TEXT_ALIGN_CENTER);
    display->setFont(FONT_MEDIUM);
    display->drawString(x + w / 2,
                        y + bands.middleY + std::max(0, (static_cast<int>(bands.middleHeight) - FONT_HEIGHT_MEDIUM) / 2),
                        state);
    display->setFont(FONT_SMALL);
    display->drawString(x + w / 2, y + bands.bottomY + 2, detail);
}

uint8_t menuCount()
{
    if (menuView == MenuView::PROFILE)
        return 4U;
    return menuView == MenuView::SYSTEM ? 3U : 6U;
}

const char *menuLabel(uint8_t index)
{
    if (menuView == MenuView::PROFILE) {
        static const char *items[] = {"STANDARD", "JARNSEN 1", "JARNSEN 2", "ZURUECK"};
        return items[index % 4U];
    }
    if (menuView == MenuView::SYSTEM) {
        static const char *items[] = {"SYSTEM INFO", "MESHTASTIC", "ZURUECK"};
        return items[index % 3U];
    }
    return jarnsen::mainMenuLabel(static_cast<jarnsen::MainMenuItem>(index % 6U));
}

void drawMenu(OLEDDisplay *display, int16_t x, int16_t y)
{
    const char *header = menuView == MenuView::PROFILE ? "FUNKPROFIL" : (menuView == MenuView::SYSTEM ? "SYSTEM MENUE" : "MENUE");
    drawHeader(display, x, y, header);
    const uint8_t count = menuCount();
    if (menuSelection >= count)
        menuSelection = 0;
    const auto bands = jarnsen::displayBands(display->getHeight());
    const int w = display->getWidth();
    char selected[48] = {};
    std::snprintf(selected, sizeof(selected), "> %s", menuLabel(menuSelection));
    drawFittedCentered(display, x + w / 2, y + bands.middleY + 3, selected, w - 4, true);
    char next[48] = {};
    if (menuView == MenuView::PROFILE && profileError)
        std::snprintf(next, sizeof(next), "%s", profileError);
    else if (menuView == MenuView::PROFILE)
        std::snprintf(next, sizeof(next), "aktiv: %s", jarnsen::radioProfileLabel(jarnsen::radioProfileActive()));
    else
        std::snprintf(next, sizeof(next), "danach: %s", menuLabel((menuSelection + 1U) % count));
    drawFittedCentered(display, x + w / 2, y + bands.bottomY + 1, next, w - 4, false);
}

class JarnsenDisplayModule final : public MeshModule
{
  public:
    JarnsenDisplayModule() : MeshModule("JarnsenCore") {}
    bool wantPacket(const meshtastic_MeshPacket *) override { return false; }
    bool wantUIFrame() override { return true; }
    void requestDisplayFocus() { requestFocus(); }

    void drawFrame(OLEDDisplay *display, OLEDDisplayUiState *, int16_t x, int16_t y) override
    {
        if (!display)
            return;
        if (menuView != MenuView::NONE) {
            drawMenu(display, x, y);
            return;
        }
        switch (currentPage) {
        case DisplayPage::MGRS:
            drawMgrs(display, x, y);
            break;
        case DisplayPage::NODE_STATUS:
            drawNode(display, x, y);
            break;
        case DisplayPage::SERVICE:
            drawService(display, x, y);
            break;
        case DisplayPage::RADIO:
            drawRadio(display, x, y);
            break;
        case DisplayPage::NETWORK:
            drawNetwork(display, x, y);
            break;
        case DisplayPage::SYSTEM:
            drawSystem(display, x, y);
            break;
        default:
            drawMgrs(display, x, y);
            break;
        }
    }
};

JarnsenDisplayModule displayModule;

void wakeSharedDisplay(bool openRepeaterService)
{
    if (openRepeaterService && jarnsen::takRepeaterRoleActive() && !jarnsen::takRepeaterStats().serviceActive)
        jarnsen::takRepeaterServiceOpen();

    if (!screen)
        return;

    if (!screen->isScreenOn())
        screen->setOn(true);

    if (!stockUiActive) {
        displayModule.requestDisplayFocus();
        screen->setFrames(graphics::Screen::FOCUS_MODULE);
    }
    screen->runNow();
}

bool consumeWakeOnlyOneButtonEvent()
{
    if (!suppressNextOneButtonEvent)
        return false;
    suppressNextOneButtonEvent = false;
    jarnsen::diagnosticLog("BUTTON", "event=wake_or_service_only ui_action=consumed");
    return true;
}

void redraw()
{
    displayModule.requestDisplayFocus();
    if (screen)
        screen->runNow();
}

void closeMenuTo(DisplayPage page)
{
    if (page == DisplayPage::SERVICE)
        jarnsen::takRepeaterServiceOpen();
    currentPage = page;
    menuView = MenuView::NONE;
    menuSelection = 0;
    profileError = nullptr;
    redraw();
}
} // namespace

bool jarnsenDisplayOwnsScreen()
{
    return true;
}

bool jarnsenDisplayStockUiActive()
{
    return stockUiActive;
}

void jarnsenDisplayRequestFocus()
{
    if (stockUiActive)
        return;
    displayModule.requestDisplayFocus();
    if (screen) {
        screen->setFrames(graphics::Screen::FOCUS_MODULE);
        screen->runNow();
    }
}

void jarnsenDisplayHandlePhysicalPressStart()
{
#if defined(HELTEC_V3) || defined(_VARIANT_HELTEC_V3) || defined(HELTEC_V4) || defined(_VARIANT_HELTEC_V4) || \
    defined(TBEAM_V10) || defined(LILYGO_TBEAM_S3_CORE)
    if (stockUiActive)
        return;

    const bool screenWasOff = screen && !screen->isScreenOn();
    const bool serviceWasClosed = jarnsen::takRepeaterRoleActive() && !jarnsen::takRepeaterStats().serviceActive;
    if (!screenWasOff && !serviceWasClosed)
        return;

    suppressNextOneButtonEvent = true;
    wakeSharedDisplay(true);
    jarnsen::diagnosticLog("BUTTON", "event=raw_down wake_only=1 screen_was_off=%u service_was_closed=%u",
                          screenWasOff ? 1U : 0U, serviceWasClosed ? 1U : 0U);
#endif
}

void jarnsenDisplayHandleLightSleepButtonWake()
{
#if defined(HELTEC_V3) || defined(_VARIANT_HELTEC_V3) || defined(HELTEC_V4) || defined(_VARIANT_HELTEC_V4) || \
    defined(TBEAM_V10) || defined(LILYGO_TBEAM_S3_CORE)
    // The ButtonThread suppresses the corresponding short/long event until the
    // wake button is released. Here we only restore display/service state.
    wakeSharedDisplay(true);
    jarnsen::diagnosticLog("WAKE", "light_button display=on focus=jarnsen wake_only=1");
#endif
}

bool jarnsenDisplayHandleFrameStep(bool next)
{
    if (stockUiActive)
        return false;
    if (menuView != MenuView::NONE) {
        const uint8_t count = menuCount();
        menuSelection = next ? (uint8_t)((menuSelection + 1U) % count)
                             : (uint8_t)((menuSelection + count - 1U) % count);
        if (menuView == MenuView::PROFILE)
            profileError = nullptr;
    } else {
        currentPage = next ? jarnsen::nextDisplayPage(currentPage) : previousPage(currentPage);
    }
    redraw();
    return true;
}

bool jarnsenDisplayHandlePrimaryPress()
{
#if defined(HELTEC_V3) || defined(_VARIANT_HELTEC_V3) || defined(HELTEC_V4) || defined(_VARIANT_HELTEC_V4) || \
    defined(TBEAM_V10) || defined(LILYGO_TBEAM_S3_CORE)
    if (consumeWakeOnlyOneButtonEvent())
        return true;
    // Match Tracker V1.1 one-button interaction: short press advances the
    // current JARNSEN page, or the current menu selection when a menu is open.
    // Long press remains INPUT_BROKER_SELECT and therefore opens/confirms.
    return jarnsenDisplayHandleFrameStep(true);
#else
    // Wio Tracker L1 has directional/trackball input and must keep UP/DOWN.
    return false;
#endif
}

bool jarnsenDisplayHandleSelect()
{
    if (stockUiActive)
        return false;
#if defined(HELTEC_V3) || defined(_VARIANT_HELTEC_V3) || defined(HELTEC_V4) || defined(_VARIANT_HELTEC_V4) || \
    defined(TBEAM_V10) || defined(LILYGO_TBEAM_S3_CORE)
    if (consumeWakeOnlyOneButtonEvent())
        return true;
#endif
    if (menuView == MenuView::NONE) {
        menuView = MenuView::ROOT;
        menuSelection = 0;
        profileError = nullptr;
        redraw();
        return true;
    }

    if (menuView == MenuView::ROOT) {
        switch (static_cast<jarnsen::MainMenuItem>(menuSelection % 6U)) {
        case jarnsen::MainMenuItem::NODES:
            closeMenuTo(DisplayPage::NETWORK);
            return true;
        case jarnsen::MainMenuItem::PROFILE:
            menuView = MenuView::PROFILE;
            menuSelection = static_cast<uint8_t>(jarnsen::radioProfileActive());
            profileError = nullptr;
            redraw();
            return true;
        case jarnsen::MainMenuItem::TRACKER:
            closeMenuTo(DisplayPage::MGRS);
            return true;
        case jarnsen::MainMenuItem::SERVICE:
            closeMenuTo(DisplayPage::SERVICE);
            return true;
        case jarnsen::MainMenuItem::SYSTEM:
            menuView = MenuView::SYSTEM;
            menuSelection = 0;
            redraw();
            return true;
        case jarnsen::MainMenuItem::BACK:
        default:
            menuView = MenuView::NONE;
            menuSelection = 0;
            profileError = nullptr;
            redraw();
            return true;
        }
    }

    if (menuView == MenuView::PROFILE) {
        if (menuSelection < 3U) {
            const auto profile = static_cast<jarnsen::RadioProfileSlot>(menuSelection);
            const bool slotExists = jarnsen::radioProfileSlotExists(profile);
            if (jarnsen::radioProfileSelect(profile, true)) {
                closeMenuTo(DisplayPage::RADIO);
            } else {
                profileError = slotExists ? "PROFILWECHSEL FEHLER" : "PROFIL NICHT GESPEICHERT";
                redraw();
            }
        } else {
            menuView = MenuView::ROOT;
            menuSelection = 0;
            profileError = nullptr;
            redraw();
        }
        return true;
    }

    // SYSTEM INFO, MESHTASTIC, ZURUECK
    if (menuSelection == 0U) {
        closeMenuTo(DisplayPage::SYSTEM);
    } else if (menuSelection == 1U) {
        menuView = MenuView::NONE;
        menuSelection = 0;
        profileError = nullptr;
        stockUiActive = true;
        if (screen) {
            screen->setFrames(graphics::Screen::FOCUS_DEFAULT);
            screen->runNow();
        }
    } else {
        menuView = MenuView::ROOT;
        menuSelection = 0;
        redraw();
    }
    return true;
}

bool jarnsenDisplayHandleBack()
{
    if (stockUiActive) {
        stockUiActive = false;
        menuView = MenuView::NONE;
        profileError = nullptr;
        currentPage = DisplayPage::MGRS;
        jarnsenDisplayRequestFocus();
        return true;
    }
    if (menuView == MenuView::SYSTEM || menuView == MenuView::PROFILE) {
        menuView = MenuView::ROOT;
        menuSelection = 0;
        profileError = nullptr;
        redraw();
        return true;
    }
    if (menuView == MenuView::ROOT) {
        menuView = MenuView::NONE;
        menuSelection = 0;
        profileError = nullptr;
        redraw();
        return true;
    }
    return false;
}

#else

bool jarnsenDisplayOwnsScreen()
{
    return false;
}
bool jarnsenDisplayStockUiActive()
{
    return false;
}
void jarnsenDisplayRequestFocus() {}
void jarnsenDisplayHandlePhysicalPressStart() {}
void jarnsenDisplayHandleLightSleepButtonWake() {}
bool jarnsenDisplayHandleFrameStep(bool)
{
    return false;
}
bool jarnsenDisplayHandlePrimaryPress()
{
    return false;
}
bool jarnsenDisplayHandleSelect()
{
    return false;
}
bool jarnsenDisplayHandleBack()
{
    return false;
}

#endif
