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
#include "jarnsen/core/service/JarnsenDiagnosticLog.h"
#include "jarnsen/core/service/JarnsenMenuAuthorization.h"
#include "jarnsen/core/service/JarnsenServiceSecurity.h"
#include "jarnsen/hardware/JarnsenHardwareProfiles.h"
#include "concurrency/OSThread.h"
#include "jarnsen/core/status/JarnsenStatusProvider.h"
#include "jarnsen/core/position/JarnsenPositionCore.h"
#include "mesh/Channels.h"
#include "mesh/MeshModule.h"
#include "mesh/http/JarnsenServiceWeb.h"
#include "modules/PositionModule.h"
#ifdef ARCH_ESP32
#include <esp_sleep.h>
#endif

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
    MAIN,
    PROFILE,
    TRACKER,
    POSITION,
    SMART_DISTANCE,
    MIN_TX_INTERVAL,
    MOVING_GNSS,
    MOTION,
    MOTION_STATUS,
    WAKE_SENSOR,
    MOTION_SENSITIVITY,
    PARKING,
    PARK_INTERVAL,
    GPS_SEARCH_TIME,
    SERVICE,
    BLUETOOTH,
    BLE_IDLE,
    BLE_HARD,
    WLAN,
    DIAG_LOG,
    LOGGING,
    LOG_STATUS,
    LOG_EXPORT,
    LOG_CLEAR,
    SYSTEM,
    SYSTEM_INFO,
    DIAGNOSTICS,
    POWER,
    POWER_STATS,
    INA226,
    ANTENNA_TEST,
    NODES,
};

constexpr uint32_t MENU_TIMEOUT_MS = 30000UL;
constexpr uint32_t MENU_PIN_ERROR_MS = 1500UL;

DisplayPage currentPage = DisplayPage::MGRS;
MenuView menuView = MenuView::NONE;
uint8_t menuSelection = 0;
bool stockUiActive = false;
bool nodeNavigationMode = false;
uint32_t selectedNodeNum = 0;
size_t selectedNodeIndex = 0;
const char *profileError = nullptr;
bool suppressNextOneButtonEvent = false;
uint32_t menuLastActivityMs = 0;

// JARNSEN_SHARED_MENU_PIN_AUTH_V1
bool menuPinMode = false;
MenuView menuPinPendingView = MenuView::NONE;
uint8_t menuPinPendingSelection = 0;
uint8_t menuPinDigits[6] = {};
uint8_t menuPinIndex = 0;
uint8_t menuPinDigit = 0;
uint32_t menuPinErrorUntilMs = 0;

// JARNSEN_SHARED_WLAN_SERVICE_MENU_V1
bool wlanPasswordVisible = false;
bool wlanLastActionFailed = false;

void redraw();

bool sharedHasWlanService()
{
    return jarnsen::currentHardwareRoleProfile().hardware.capabilities.wifi;
}

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
    jarnsenDisplayHandleSelect();
}

void menuPinStep(bool next)
{
    if (jarnsen::menuAuthorizationBlockRemainingMs() != 0U) {
        redraw();
        return;
    }
    menuPinErrorUntilMs = 0;
    menuPinDigit = next ? (uint8_t)((menuPinDigit + 1U) % 10U) : (uint8_t)((menuPinDigit + 9U) % 10U);
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
    uint8_t values[6] = {};
    for (uint8_t i = 0; i < 6U; ++i) {
        if (i < menuPinIndex)
            values[i] = menuPinDigits[i];
        else if (i == menuPinIndex)
            values[i] = menuPinDigit;
    }
    char digits[16] = {};
    std::snprintf(digits, sizeof(digits), "%u%u%u %u%u%u", (unsigned)values[0], (unsigned)values[1],
                  (unsigned)values[2], (unsigned)values[3], (unsigned)values[4], (unsigned)values[5]);
    display->setFont(FONT_MEDIUM);
    display->drawString(x + w / 2, y + (h >= 64 ? 22 : 16), digits);
    char position[24] = {};
    std::snprintf(position, sizeof(position), "STELLE %u/6",
                  (unsigned)(menuPinIndex < 6U ? menuPinIndex + 1U : 6U));
    display->setFont(FONT_SMALL);
    display->drawString(x + w / 2, y + h - 13, position);
}

class JarnsenSharedServicePump final : public concurrency::OSThread
{
  public:
    JarnsenSharedServicePump() : concurrency::OSThread("JarnsenService") {}

  protected:
    int32_t runOnce() override
    {
        jarnsenServiceWebPump();
        jarnsen::serviceSecurityPump();
        if ((menuView != MenuView::NONE || nodeNavigationMode || menuPinMode) && menuLastActivityMs != 0 &&
            (uint32_t)(millis() - menuLastActivityMs) >= MENU_TIMEOUT_MS) {
            menuView = MenuView::NONE;
            nodeNavigationMode = false;
            cancelMenuPinRequest();
            menuSelection = 0;
            profileError = nullptr;
            menuLastActivityMs = 0;
            redraw();
        }
        return jarnsenServiceWebActive() ? 20 : 250;
    }
};

JarnsenSharedServicePump *sharedServicePump = nullptr;

void ensureSharedServicePump()
{
    if (!sharedServicePump)
        sharedServicePump = new JarnsenSharedServicePump();
}

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

meshtastic_NodeInfoLite *nodeAtOtherIndex(size_t otherIndex)
{
    if (!nodeDB)
        return nullptr;
    size_t seen = 0;
    for (size_t i = 0; i < nodeDB->getNumMeshNodes(); ++i) {
        meshtastic_NodeInfoLite *node = nodeDB->getMeshNodeByIndex(i);
        if (!node || node->num == nodeDB->getNodeNum())
            continue;
        if (seen == otherIndex)
            return node;
        ++seen;
    }
    return nullptr;
}

const char *safeNodeName(meshtastic_NodeInfoLite *node, char *out, size_t outSize)
{
    if (!out || outSize == 0)
        return "NODE";
    if (node && nodeInfoLiteHasUser(node)) {
        if (node->long_name[0]) {
            std::snprintf(out, outSize, "%s", node->long_name);
            return out;
        }
        if (node->short_name[0]) {
            std::snprintf(out, outSize, "%s", node->short_name);
            return out;
        }
    }
    std::snprintf(out, outSize, "!%08lx", node ? (unsigned long)node->num : 0UL);
    return out;
}

void drawLargeRelativeArrow(OLEDDisplay *display, int centerX, int centerY, double relativeDegrees)
{
    constexpr double pi = 3.14159265358979323846;
    const double a = (relativeDegrees - 90.0) * pi / 180.0;
    const double leftA = a + 2.55;
    const double rightA = a - 2.55;
    const int len = 18;
    const int head = 7;
    const int endX = centerX + static_cast<int>(std::cos(a) * len);
    const int endY = centerY + static_cast<int>(std::sin(a) * len);
    display->drawLine(centerX, centerY, endX, endY);
    display->drawLine(endX, endY, endX + static_cast<int>(std::cos(leftA) * head),
                      endY + static_cast<int>(std::sin(leftA) * head));
    display->drawLine(endX, endY, endX + static_cast<int>(std::cos(rightA) * head),
                      endY + static_cast<int>(std::sin(rightA) * head));
}

void drawNodeNavigation(OLEDDisplay *display, int16_t x, int16_t y)
{
    meshtastic_NodeInfoLite *node = nodeDB ? nodeDB->getMeshNode(selectedNodeNum) : nullptr;
    char name[40] = {};
    drawHeader(display, x, y, safeNodeName(node, name, sizeof(name)));

    const int w = display->getWidth();
    const int h = display->getHeight();
    const auto bands = jarnsen::displayBands(h);
    meshtastic_PositionLite own = meshtastic_PositionLite_init_default;
    meshtastic_PositionLite remote = meshtastic_PositionLite_init_default;
    const bool ownOk = ownPosition(own);
    const bool remoteOk = nodeDB && selectedNodeNum != 0 && nodeDB->copyNodePosition(selectedNodeNum, remote) &&
                          (remote.latitude_i != 0 || remote.longitude_i != 0);

    if (!ownOk || !remoteOk) {
        display->setTextAlignment(TEXT_ALIGN_CENTER);
        display->setFont(FONT_MEDIUM);
        display->drawString(x + w / 2, y + bands.middleY + 8, "KEINE POSITION");
        display->setFont(FONT_SMALL);
        display->drawString(x + w / 2, y + bands.bottomY + 2, "DIST --   RICHTUNG --");
        return;
    }

    const double distance =
        jarnsenPositionDistanceMeters(own.latitude_i, own.longitude_i, remote.latitude_i, remote.longitude_i);
    const double bearing =
        jarnsenPositionBearingDegrees(own.latitude_i, own.longitude_i, remote.latitude_i, remote.longitude_i);
    const uint16_t mils = jarnsenPositionHeadingMils6400(bearing);
    char strich[12] = {};
    char distanceText[20] = {};
    std::snprintf(strich, sizeof(strich), "%04u", (unsigned)mils);
    if (distance >= 1000.0)
        std::snprintf(distanceText, sizeof(distanceText), "%.2f km", distance / 1000.0);
    else
        std::snprintf(distanceText, sizeof(distanceText), "%.0f m", distance);

    display->setTextAlignment(TEXT_ALIGN_CENTER);
    display->setFont(FONT_LARGE);
    display->drawString(x + w / 4, y + bands.middleY + 2, strich);
    display->setFont(FONT_SMALL);
    display->drawString(x + w / 4, y + bands.middleY + bands.middleHeight - 13, distanceText);

    const bool headingValid = gpsStatus && gpsStatus->getHasLock() && localPosition.has_ground_track;
    if (headingValid) {
        double relative = bearing - (localPosition.ground_track / 100.0);
        while (relative < 0.0)
            relative += 360.0;
        while (relative >= 360.0)
            relative -= 360.0;
        drawLargeRelativeArrow(display, x + (w * 3) / 4, y + bands.middleY + bands.middleHeight / 2, relative);
    } else {
        display->setFont(FONT_SMALL);
        display->drawString(x + (w * 3) / 4, y + bands.middleY + bands.middleHeight / 2 - 4, "PFEIL --");
    }

    char age[20] = "POS --";
    const uint32_t nowEpoch = getValidTime(RTCQualityDevice);
    if (remote.time && nowEpoch && nowEpoch >= remote.time) {
        const uint32_t secs = nowEpoch - remote.time;
        if (secs < 60)
            std::snprintf(age, sizeof(age), "POS %us", (unsigned)secs);
        else
            std::snprintf(age, sizeof(age), "POS %umin", (unsigned)(secs / 60U));
    }
    display->setFont(FONT_SMALL);
    display->setTextAlignment(TEXT_ALIGN_LEFT);
    display->drawString(x + 2, y + bands.bottomY + 2, age);
    display->setTextAlignment(TEXT_ALIGN_RIGHT);
    display->drawString(x + w - 2, y + bands.bottomY + 2, headingValid ? "TRACK OK" : "TRACK --");
}

const char *menuTitle(MenuView view)
{
    switch (view) {
    case MenuView::MAIN: return "MENUE";
    case MenuView::PROFILE: return "PROFIL";
    case MenuView::TRACKER: return "TRACKER";
    case MenuView::POSITION: return "POSITION";
    case MenuView::SMART_DISTANCE: return "SMART DISTANCE";
    case MenuView::MIN_TX_INTERVAL: return "MIN TX INTERVAL";
    case MenuView::MOVING_GNSS: return "MOVING GNSS";
    case MenuView::MOTION: return "MOTION";
    case MenuView::MOTION_STATUS: return "MOTION STATUS";
    case MenuView::WAKE_SENSOR: return "WAKE SENSOR";
    case MenuView::MOTION_SENSITIVITY: return "EMPFINDLICHKEIT";
    case MenuView::PARKING: return "PARKING";
    case MenuView::PARK_INTERVAL: return "PARK-INTERVALL";
    case MenuView::GPS_SEARCH_TIME: return "GPS-SUCHZEIT";
    case MenuView::SERVICE: return "SERVICE";
    case MenuView::BLUETOOTH: return "BLUETOOTH";
    case MenuView::BLE_IDLE: return "IDLE TIMEOUT";
    case MenuView::BLE_HARD: return "HARD TIMEOUT";
    case MenuView::WLAN: return "WLAN SERVICE";
    case MenuView::DIAG_LOG: return "DIAGNOSTIC LOG";
    case MenuView::LOGGING: return "LOGGING";
    case MenuView::LOG_STATUS: return "LOG STATUS";
    case MenuView::LOG_EXPORT: return "USB-EXPORT";
    case MenuView::LOG_CLEAR: return "LOG LOESCHEN";
    case MenuView::SYSTEM: return "SYSTEM";
    case MenuView::SYSTEM_INFO: return "SYSTEM INFO";
    case MenuView::DIAGNOSTICS: return "DIAGNOSTICS";
    case MenuView::POWER: return "POWER";
    case MenuView::POWER_STATS: return "POWER STATISTICS";
    case MenuView::INA226: return "INA226 HARDWARE";
    case MenuView::ANTENNA_TEST: return "ANTENNENTEST";
    case MenuView::NODES: return "NODES";
    default: return "MENUE";
    }
}

uint8_t menuCount(MenuView view)
{
    switch (view) {
    case MenuView::MAIN: return 6;
    case MenuView::PROFILE: return 4;
    case MenuView::TRACKER: return 4;
    case MenuView::POSITION: return 4;
    case MenuView::SMART_DISTANCE:
    case MenuView::MIN_TX_INTERVAL:
    case MenuView::MOVING_GNSS:
    case MenuView::MOTION_SENSITIVITY:
    case MenuView::GPS_SEARCH_TIME:
    case MenuView::BLE_IDLE:
    case MenuView::BLE_HARD: return 5;
    case MenuView::MOTION:
    case MenuView::MOTION_STATUS: return 4;
    case MenuView::WAKE_SENSOR: return 3;
    case MenuView::PARKING: return 3;
    case MenuView::PARK_INTERVAL: return 9;
    case MenuView::SERVICE: return 4;
    case MenuView::BLUETOOTH: return 3;
    case MenuView::WLAN: return 6;
    case MenuView::DIAG_LOG: return 5;
    case MenuView::LOGGING: return 3;
    case MenuView::LOG_STATUS: return 4;
    case MenuView::LOG_EXPORT:
    case MenuView::LOG_CLEAR: return 2;
    case MenuView::SYSTEM: return 6;
    case MenuView::SYSTEM_INFO: return 5;
    case MenuView::DIAGNOSTICS: return 6;
    case MenuView::POWER: return 3;
    case MenuView::POWER_STATS: return 9;
    case MenuView::INA226: return 3;
    case MenuView::ANTENNA_TEST: return 9;
    case MenuView::NODES: return static_cast<uint8_t>(std::min<size_t>(254, otherNodeCount() + 1));
    default: return 1;
    }
}

const char *menuLabel(MenuView view, uint8_t index, char *buffer, size_t size)
{
    if (!buffer || size == 0)
        return "";
    buffer[0] = '\0';

    switch (view) {
    case MenuView::MAIN: {
        static const char *items[] = {"NODES", "PROFIL", "TRACKER", "SERVICE", "SYSTEM", "ZURUECK"};
        return items[index % 6];
    }
    case MenuView::PROFILE: {
        static const char *items[] = {"Standard", "Jarnsen 1", "Jarnsen 2", "ZURUECK"};
        return items[index % 4];
    }
    case MenuView::TRACKER: {
        static const char *items[] = {"POSITION", "MOTION", "PARKING", "ZURUECK"};
        return items[index % 4];
    }
    case MenuView::POSITION: {
        static const char *items[] = {"Smart Distance", "Min TX Interval", "Moving GNSS", "ZURUECK"};
        return items[index % 4];
    }
    case MenuView::SMART_DISTANCE: {
        if (index == 0) return "ZURUECK";
        const uint16_t vals[] = {50, 75, 100, 150};
        std::snprintf(buffer, size, "%c %u m",
                      config.position.broadcast_smart_minimum_distance == vals[index - 1] ? '*' : ' ',
                      (unsigned)vals[index - 1]);
        return buffer;
    }
    case MenuView::MIN_TX_INTERVAL: {
        if (index == 0) return "ZURUECK";
        const uint16_t vals[] = {30, 45, 60, 90};
        std::snprintf(buffer, size, "%c %u s",
                      config.position.broadcast_smart_minimum_interval_secs == vals[index - 1] ? '*' : ' ',
                      (unsigned)vals[index - 1]);
        return buffer;
    }
    case MenuView::MOVING_GNSS: {
        if (index == 0) return "ZURUECK";
        const uint16_t vals[] = {5, 10, 15, 30};
        std::snprintf(buffer, size, "%c %u s", config.position.gps_update_interval == vals[index - 1] ? '*' : ' ',
                      (unsigned)vals[index - 1]);
        return buffer;
    }
    case MenuView::MOTION: {
        static const char *items[] = {"Bewegungsstatus", "WAKE SENSOR", "Empfindlichkeit", "ZURUECK"};
        return items[index % 4];
    }
    case MenuView::MOTION_STATUS:
        if (index == 0) return "ZURUECK";
        if (index == 1) {
            std::snprintf(buffer, size, "Motion: %s",
                          jarnsen::takRepeaterRoleActive() &&
                                  jarnsen::takRepeaterStats().positionMode == jarnsen::TakRepeaterPositionMode::MOBILE
                              ? "MOBILE"
                              : "AUTO");
            return buffer;
        }
        if (index == 2) {
            std::snprintf(buffer, size, "Sensor: %s",
                          jarnsen::currentHardwareRoleProfile().hardware.capabilities.supportsMotion ? "OK" : "--");
            return buffer;
        }
        std::snprintf(buffer, size, "Runtime: %s", roleLabel());
        return buffer;
    case MenuView::WAKE_SENSOR:
        if (index == 0) return "ZURUECK";
        if (index == 1) {
            std::snprintf(buffer, size, "Status: %s",
                          jarnsen::currentHardwareRoleProfile().hardware.capabilities.supportsMotion ? "OK" : "--");
            return buffer;
        }
        return "Sens: --";
    case MenuView::MOTION_SENSITIVITY: {
        if (index == 0) return "ZURUECK";
        static const char *names[] = {"VERY SENS", "SENSITIVE", "NORMAL", "ROBUST"};
        std::snprintf(buffer, size, "  %s", names[index - 1]);
        return buffer;
    }
    case MenuView::PARKING: {
        static const char *items[] = {"Park-Intervall", "GPS-Suchzeit", "ZURUECK"};
        return items[index % 3];
    }
    case MenuView::PARK_INTERVAL: {
        if (index == 0) return "ZURUECK";
        const uint16_t vals[] = {20, 30, 60, 120, 240, 360, 540, 720};
        const char *names[] = {"20 min", "30 min", "60 min", "2 h", "4 h", "6 h", "9 h", "12 h"};
        const uint32_t minutes = config.position.position_broadcast_secs / 60U;
        std::snprintf(buffer, size, "%c %s", minutes == vals[index - 1] ? '*' : ' ', names[index - 1]);
        return buffer;
    }
    case MenuView::GPS_SEARCH_TIME: {
        if (index == 0) return "ZURUECK";
        const uint16_t vals[] = {15, 30, 45, 60};
        std::snprintf(buffer, size, "  %u s", (unsigned)vals[index - 1]);
        return buffer;
    }
    case MenuView::SERVICE: {
        static const char *items[] = {"BLUETOOTH", "WLAN SERVICE", "DIAGNOSTIC LOG", "ZURUECK"};
        return items[index % 4];
    }
    case MenuView::BLUETOOTH: {
        static const char *items[] = {"Idle Timeout", "Hard Timeout", "ZURUECK"};
        return items[index % 3];
    }
    case MenuView::BLE_IDLE: {
        if (index == 0) return "ZURUECK";
        const uint16_t vals[] = {60, 120, 180, 300};
        std::snprintf(buffer, size, "%c %u s", vals[index - 1] == 120U ? '*' : ' ', (unsigned)vals[index - 1]);
        return buffer;
    }
    case MenuView::BLE_HARD: {
        if (index == 0) return "ZURUECK";
        const uint16_t vals[] = {300, 600, 900, 1800};
        const char *names[] = {"5 min", "10 min", "15 min", "30 min"};
        std::snprintf(buffer, size, "%c %s", vals[index - 1] == 900U ? '*' : ' ', names[index - 1]);
        return buffer;
    }
    case MenuView::WLAN:
        if (index == 0) return "ZURUECK";
        if (index == 1) return sharedHasWlanService() ? (jarnsenServiceWebActive() ? "WLAN BEENDEN" : "WLAN STARTEN") : "WLAN N/A";
        if (index == 2) {
            std::snprintf(buffer, size, "Status: %s", sharedHasWlanService() ? (jarnsenServiceWebActive() ? "AKTIV" : "AUS") : "N/A");
            return buffer;
        }
        if (index == 3) {
            std::snprintf(buffer, size, "SSID: %s", sharedHasWlanService() ? jarnsenServiceWebSsid() : "--");
            return buffer;
        }
        if (index == 4) {
            std::snprintf(buffer, size, "PW: %s",
                          sharedHasWlanService() && wlanPasswordVisible && jarnsen::menuAuthorizationValid()
                              ? jarnsenServiceWebPassword()
                              : "PIN GESCHUETZT");
            return buffer;
        }
        std::snprintf(buffer, size, "IP: %s", sharedHasWlanService() ? jarnsenServiceWebAddress() : "--");
        return buffer;
    case MenuView::DIAG_LOG: {
        static const char *items[] = {"Status", "Logging Ein/Aus", "USB-Export", "Log loeschen", "ZURUECK"};
        return items[index % 5];
    }
    case MenuView::LOGGING:
        if (index == 0) return "ZURUECK";
        if (index == 1) return jarnsen::diagnosticLogEnabled() ? "* EIN" : "  EIN";
        return !jarnsen::diagnosticLogEnabled() ? "* AUS" : "  AUS";
    case MenuView::LOG_STATUS:
        if (index == 0) return "ZURUECK";
        if (index == 1) {
            std::snprintf(buffer, size, "Logging: %s", jarnsen::diagnosticLogEnabled() ? "EIN" : "AUS");
            return buffer;
        }
        if (index == 2) {
            std::snprintf(buffer, size, "Log: %u KB", (unsigned)((jarnsen::diagnosticLogSize() + 1023U) / 1024U));
            return buffer;
        }
        std::snprintf(buffer, size, "USB: %s", jarnsen::diagnosticLogUsbExportStatusText());
        return buffer;
    case MenuView::LOG_EXPORT:
        if (index == 0) return "ZURUECK";
        std::snprintf(buffer, size, "%s %u%%",
                      jarnsen::diagnosticLogUsbExportPending() ? "EXPORT" : "EXPORT START",
                      (unsigned)jarnsen::diagnosticLogUsbExportProgress());
        return buffer;
    case MenuView::LOG_CLEAR:
        return index == 0 ? "ZURUECK" : "LOESCHEN BESTAETIGEN";
    case MenuView::SYSTEM: {
        static const char *items[] = {"SYSTEM INFO", "DIAGNOSTICS", "POWER", "ANTENNENTEST", "MESHTASTIC", "ZURUECK"};
        return items[index % 6];
    }
    case MenuView::SYSTEM_INFO:
        if (index == 0) return "ZURUECK";
        if (index == 1) {
            std::snprintf(buffer, size, "FW: %s", jarnsen::build::version);
            return buffer;
        }
        if (index == 2) {
            std::snprintf(buffer, size, "Build: %.8s", jarnsen::build::gitSha);
            return buffer;
        }
        if (index == 3) {
            std::snprintf(buffer, size, "Role: %s", roleLabel());
            return buffer;
        }
        std::snprintf(buffer, size, "Display: %dx%d", screen ? screen->getWidth() : 0, screen ? screen->getHeight() : 0);
        return buffer;
    case MenuView::DIAGNOSTICS:
        if (index == 0) return "ZURUECK";
        if (index == 1) {
            std::snprintf(buffer, size, "State: %s", roleLabel());
            return buffer;
        }
        if (index == 2) {
            uint32_t age = UINT32_MAX;
            if (gpsStatus && gpsStatus->getLastFixMillis() != 0 && millis() >= gpsStatus->getLastFixMillis())
                age = (millis() - gpsStatus->getLastFixMillis()) / 1000UL;
            if (age == UINT32_MAX) std::snprintf(buffer, size, "GPS age: --");
            else std::snprintf(buffer, size, "GPS age: %us", (unsigned)age);
            return buffer;
        }
        if (index == 3) {
            std::snprintf(buffer, size, "Sensor: %s",
                          jarnsen::currentHardwareRoleProfile().hardware.capabilities.supportsMotion ? "OK" : "--");
            return buffer;
        }
        if (index == 4) {
#ifdef ARCH_ESP32
            std::snprintf(buffer, size, "Wake: %u", (unsigned)esp_sleep_get_wakeup_cause());
#else
            std::snprintf(buffer, size, "Wake: PLATFORM");
#endif
            return buffer;
        }
        std::snprintf(buffer, size, "Sleep: %s",
                      jarnsen::currentHardwareRoleProfile().hardware.capabilities.lightSleep ? "LIGHT" : "--");
        return buffer;
    case MenuView::POWER: {
        static const char *items[] = {"Power Statistics", "INA226 Hardware", "ZURUECK"};
        return items[index % 3];
    }
    case MenuView::POWER_STATS: {
        const auto p = jarnsen::batteryLearningStats();
        if (index == 0) return "ZURUECK";
        if (index == 1) {
            const unsigned mv = powerStatus && powerStatus->getHasBattery() ? (unsigned)powerStatus->getBatteryVoltageMv() : 0U;
            std::snprintf(buffer, size, "Akku: %u%% %u.%03uV", (unsigned)p.batteryPercent, mv / 1000U, mv % 1000U);
            return buffer;
        }
        if (index == 2) {
            char d[20] = "--";
            if (p.estimateReady && !p.usbPowered && !p.charging)
                jarnsen::batteryLearningFormatDuration(p.remainingSecs, d, sizeof(d));
            std::snprintf(buffer, size, "Rest: %s", d);
            return buffer;
        }
        if (index == 3) return "Strom: --";
        if (index == 4) return "Power: --";
        if (index == 5) return "Used: --";
        if (index == 6) return "Kapazitaet: N/A";
        if (index == 7) {
            const auto rep = jarnsen::takRepeaterStats();
            std::snprintf(buffer, size, "Pos TX: %u", rep.active ? (unsigned)rep.positionTxCount : 0U);
            return buffer;
        }
        return "INA: OFF";
    }
    case MenuView::INA226:
        if (index == 0) return "ZURUECK";
        return index == 1 ? "  N/A" : "* AUS";
    case MenuView::ANTENNA_TEST:
        if (index == 0) return "ZURUECK";
        return index == 8 ? "AKTION N/A" : "NICHT VERFUEGBAR";
    case MenuView::NODES:
        if (index == 0) return "ZURUECK";
        if (meshtastic_NodeInfoLite *node = nodeAtOtherIndex(index - 1))
            return safeNodeName(node, buffer, size);
        return "NODE --";
    default:
        return "ZURUECK";
    }
}

void drawMenu(OLEDDisplay *display, int16_t x, int16_t y)
{
    drawHeader(display, x, y, menuTitle(menuView));
    const uint8_t count = std::max<uint8_t>(1, menuCount(menuView));
    if (menuSelection >= count)
        menuSelection = 0;

    char current[72] = {};
    char next[72] = {};
    const char *cur = menuLabel(menuView, menuSelection, current, sizeof(current));
    const char *nxt = menuLabel(menuView, (menuSelection + 1U) % count, next, sizeof(next));
    const int w = display->getWidth();
    const int h = display->getHeight();

    display->setTextAlignment(TEXT_ALIGN_CENTER);
    display->setFont(FONT_MEDIUM);
    char selected[80] = {};
    std::snprintf(selected, sizeof(selected), "> %s", cur);
    drawFittedCentered(display, x + w / 2, y + (h >= 80 ? 25 : 21), selected, w - 4, true);

    display->setFont(FONT_SMALL);
    char nextLine[80] = {};
    if (menuView == MenuView::PROFILE && profileError)
        std::snprintf(nextLine, sizeof(nextLine), "%s", profileError);
    else if (menuView == MenuView::PROFILE)
        std::snprintf(nextLine, sizeof(nextLine), "Aktiv: %s", jarnsen::radioProfileLabel(jarnsen::radioProfileActive()));
    else if (menuView == MenuView::WLAN && wlanLastActionFailed)
        std::snprintf(nextLine, sizeof(nextLine), "%s", jarnsenServiceWebLastError());
    else
        std::snprintf(nextLine, sizeof(nextLine), "danach: %s", nxt);
    drawFittedCentered(display, x + w / 2, y + (h >= 80 ? 48 : 39), nextLine, w - 4, false);
    drawFittedCentered(display, x + w / 2, y + h - 12, "KURZ: WEITER   LANG: OK", w - 4, false);
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
        if (menuPinMode) {
            drawMenuPin(display, x, y);
            return;
        }
        if (menuView != MenuView::NONE) {
            drawMenu(display, x, y);
            return;
        }
        if (nodeNavigationMode) {
            drawNodeNavigation(display, x, y);
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
    if (page == DisplayPage::SERVICE && jarnsen::takRepeaterRoleActive())
        jarnsen::takRepeaterServiceOpen();
    currentPage = page;
    menuView = MenuView::NONE;
    nodeNavigationMode = false;
    menuSelection = 0;
    profileError = nullptr;
    menuLastActivityMs = millis() ? millis() : 1U;
    redraw();
}

void parentMenu(MenuView parent, uint8_t selection = 0)
{
    menuView = parent;
    nodeNavigationMode = false;
    menuSelection = selection;
    profileError = nullptr;
    wlanPasswordVisible = false;
    menuLastActivityMs = millis() ? millis() : 1U;
    ensureSharedServicePump();
    redraw();
}

bool persistConfig()
{
    if (positionModule)
        positionModule->refreshSmartPositionMinimumInterval();
    return nodeDB && nodeDB->saveToDisk(SEGMENT_CONFIG);
}

void enterStockMeshtastic()
{
    menuView = MenuView::NONE;
    nodeNavigationMode = false;
    menuSelection = 0;
    profileError = nullptr;
    stockUiActive = true;
    menuLastActivityMs = millis() ? millis() : 1U;
    if (screen) {
        screen->setFrames(graphics::Screen::FOCUS_DEFAULT);
        screen->runNow();
    }
}

void selectNextNavigationNode()
{
    const size_t count = otherNodeCount();
    if (!count)
        return;
    selectedNodeIndex = (selectedNodeIndex + 1U) % count;
    if (meshtastic_NodeInfoLite *node = nodeAtOtherIndex(selectedNodeIndex))
        selectedNodeNum = node->num;
    menuLastActivityMs = millis() ? millis() : 1U;
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

    menuLastActivityMs = millis() ? millis() : 1U;
    ensureSharedServicePump();

    if (menuPinMode) {
        menuPinStep(next);
        return true;
    }
    if (nodeNavigationMode) {
        if (next)
            selectNextNavigationNode();
        else {
            const size_t count = otherNodeCount();
            if (count) {
                selectedNodeIndex = (selectedNodeIndex + count - 1U) % count;
                if (meshtastic_NodeInfoLite *node = nodeAtOtherIndex(selectedNodeIndex))
                    selectedNodeNum = node->num;
                redraw();
            }
        }
        return true;
    }
    if (menuView != MenuView::NONE) {
        const uint8_t count = std::max<uint8_t>(1, menuCount(menuView));
        menuSelection = next ? (uint8_t)((menuSelection + 1U) % count)
                             : (uint8_t)((menuSelection + count - 1U) % count);
        if (menuView == MenuView::PROFILE)
            profileError = nullptr;
        if (menuView == MenuView::WLAN)
            wlanPasswordVisible = false;
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
    return jarnsenDisplayHandleFrameStep(true);
#else
    return false;
#endif
}

bool jarnsenDisplayHandleSelect()
{
    if (stockUiActive) {
        stockUiActive = false;
        parentMenu(MenuView::MAIN);
        return true;
    }
#if defined(HELTEC_V3) || defined(_VARIANT_HELTEC_V3) || defined(HELTEC_V4) || defined(_VARIANT_HELTEC_V4) || \
    defined(TBEAM_V10) || defined(LILYGO_TBEAM_S3_CORE)
    if (consumeWakeOnlyOneButtonEvent())
        return true;
#endif

    menuLastActivityMs = millis() ? millis() : 1U;
    ensureSharedServicePump();

    if (menuPinMode) {
        menuPinSelect();
        return true;
    }
    if (nodeNavigationMode) {
        parentMenu(MenuView::NODES, static_cast<uint8_t>(selectedNodeIndex + 1U));
        return true;
    }
    if (menuView == MenuView::NONE) {
        parentMenu(MenuView::MAIN);
        return true;
    }

    const uint8_t selected = menuSelection;
    switch (menuView) {
    case MenuView::MAIN:
        if (selected == 0) parentMenu(MenuView::NODES);
        else if (selected == 1) {
            if (!requireMenuAuthorization()) return true;
            parentMenu(MenuView::PROFILE, static_cast<uint8_t>(jarnsen::radioProfileActive()));
        } else if (selected == 2) parentMenu(MenuView::TRACKER);
        else if (selected == 3) {
            if (jarnsen::takRepeaterRoleActive())
                jarnsen::takRepeaterServiceOpen();
            parentMenu(MenuView::SERVICE);
        } else if (selected == 4) parentMenu(MenuView::SYSTEM);
        else {
            menuView = MenuView::NONE;
            menuSelection = 0;
            redraw();
        }
        return true;

    case MenuView::PROFILE:
        if (selected == 3) {
            parentMenu(MenuView::MAIN, 1);
        } else if (selected < jarnsen::RADIO_PROFILE_SLOT_COUNT) {
            if (!requireMenuAuthorization()) return true;
            const auto profile = static_cast<jarnsen::RadioProfileSlot>(selected);
            const bool slotExists = jarnsen::radioProfileSlotExists(profile);
            if (jarnsen::radioProfileSelect(profile, true)) {
                closeMenuTo(DisplayPage::RADIO);
            } else {
                profileError = slotExists ? "PROFILWECHSEL FEHLER" : "PROFIL NICHT GESPEICHERT";
                redraw();
            }
        }
        return true;

    case MenuView::TRACKER:
        if (selected == 0) parentMenu(MenuView::POSITION);
        else if (selected == 1) parentMenu(MenuView::MOTION);
        else if (selected == 2) parentMenu(MenuView::PARKING);
        else parentMenu(MenuView::MAIN, 2);
        return true;

    case MenuView::POSITION:
        if (selected == 0) parentMenu(MenuView::SMART_DISTANCE);
        else if (selected == 1) parentMenu(MenuView::MIN_TX_INTERVAL);
        else if (selected == 2) parentMenu(MenuView::MOVING_GNSS);
        else parentMenu(MenuView::TRACKER);
        return true;

    case MenuView::SMART_DISTANCE:
        if (selected == 0) parentMenu(MenuView::POSITION);
        else {
            if (!requireMenuAuthorization()) return true;
            const uint16_t vals[] = {50, 75, 100, 150};
            config.position.position_broadcast_smart_enabled = true;
            config.position.broadcast_smart_minimum_distance = vals[selected - 1];
            persistConfig();
            parentMenu(MenuView::POSITION);
        }
        return true;

    case MenuView::MIN_TX_INTERVAL:
        if (selected == 0) parentMenu(MenuView::POSITION);
        else {
            if (!requireMenuAuthorization()) return true;
            const uint16_t vals[] = {30, 45, 60, 90};
            config.position.position_broadcast_smart_enabled = true;
            config.position.broadcast_smart_minimum_interval_secs = vals[selected - 1];
            persistConfig();
            parentMenu(MenuView::POSITION);
        }
        return true;

    case MenuView::MOVING_GNSS:
        if (selected == 0) parentMenu(MenuView::POSITION);
        else {
            if (!requireMenuAuthorization()) return true;
            const uint16_t vals[] = {5, 10, 15, 30};
            config.position.gps_update_interval = vals[selected - 1];
            persistConfig();
            parentMenu(MenuView::POSITION);
        }
        return true;

    case MenuView::MOTION:
        if (selected == 0) parentMenu(MenuView::MOTION_STATUS);
        else if (selected == 1) parentMenu(MenuView::WAKE_SENSOR);
        else if (selected == 2) parentMenu(MenuView::MOTION_SENSITIVITY);
        else parentMenu(MenuView::TRACKER);
        return true;
    case MenuView::MOTION_STATUS:
        if (selected == 0) parentMenu(MenuView::MOTION);
        return true;
    case MenuView::WAKE_SENSOR:
        if (selected == 0) parentMenu(MenuView::MOTION);
        else if (selected == 2) parentMenu(MenuView::MOTION_SENSITIVITY);
        return true;
    case MenuView::MOTION_SENSITIVITY:
        // Only Tracker V1.1 currently has a calibrated motion-sensitivity
        // backend. Keep the same menu shape but never invent a hardware setting.
        parentMenu(MenuView::MOTION);
        return true;

    case MenuView::PARKING:
        if (selected == 0) parentMenu(MenuView::PARK_INTERVAL);
        else if (selected == 1) parentMenu(MenuView::GPS_SEARCH_TIME);
        else parentMenu(MenuView::TRACKER);
        return true;
    case MenuView::PARK_INTERVAL:
        if (selected == 0) parentMenu(MenuView::PARKING);
        else {
            if (!requireMenuAuthorization()) return true;
            const uint16_t vals[] = {20, 30, 60, 120, 240, 360, 540, 720};
            config.position.position_broadcast_secs = (uint32_t)vals[selected - 1] * 60UL;
            persistConfig();
            parentMenu(MenuView::PARKING);
        }
        return true;
    case MenuView::GPS_SEARCH_TIME:
        // No common GNSS acquisition-window setting exists outside Tracker V1.1.
        parentMenu(MenuView::PARKING);
        return true;

    case MenuView::SERVICE:
        if (selected == 0) parentMenu(MenuView::BLUETOOTH);
        else if (selected == 1) parentMenu(MenuView::WLAN);
        else if (selected == 2) parentMenu(MenuView::DIAG_LOG);
        else parentMenu(MenuView::MAIN, 3);
        return true;
    case MenuView::BLUETOOTH:
        if (selected == 0) parentMenu(MenuView::BLE_IDLE);
        else if (selected == 1) parentMenu(MenuView::BLE_HARD);
        else parentMenu(MenuView::SERVICE);
        return true;
    case MenuView::BLE_IDLE:
    case MenuView::BLE_HARD:
        // Common boards currently use the same fixed 120s/15min service
        // contract. Show the Tracker choices for operator familiarity, but do
        // not pretend unsupported per-board persistence exists.
        parentMenu(MenuView::BLUETOOTH);
        return true;
    case MenuView::WLAN:
        if (selected == 0) {
            parentMenu(MenuView::SERVICE);
        } else if (selected == 1) {
            if (!sharedHasWlanService()) {
                wlanLastActionFailed = true;
                redraw();
                return true;
            }
            if (!requireMenuAuthorization()) return true;
            ensureSharedServicePump();
            if (jarnsen::takRepeaterRoleActive()) {
                jarnsen::takRepeaterServiceOpen();
                jarnsen::takRepeaterServiceTouch();
            }
            if (jarnsenServiceWebActive()) {
                jarnsenServiceWebStop();
                wlanLastActionFailed = false;
            } else {
                wlanLastActionFailed = !jarnsenServiceWebStart();
            }
            redraw();
        } else if (selected == 4) {
            if (!requireMenuAuthorization()) return true;
            wlanPasswordVisible = true;
            redraw();
        } else {
            wlanPasswordVisible = false;
            redraw();
        }
        return true;

    case MenuView::DIAG_LOG:
        if (selected == 0) parentMenu(MenuView::LOG_STATUS);
        else if (selected == 1) parentMenu(MenuView::LOGGING);
        else if (selected == 2) parentMenu(MenuView::LOG_EXPORT);
        else if (selected == 3) parentMenu(MenuView::LOG_CLEAR);
        else parentMenu(MenuView::SERVICE);
        return true;
    case MenuView::LOGGING:
        if (selected == 0) parentMenu(MenuView::DIAG_LOG);
        else {
            if (!requireMenuAuthorization()) return true;
            jarnsen::diagnosticLogSetEnabled(selected == 1);
            parentMenu(MenuView::DIAG_LOG);
        }
        return true;
    case MenuView::LOG_STATUS:
        if (selected == 0) parentMenu(MenuView::DIAG_LOG);
        return true;
    case MenuView::LOG_EXPORT:
        if (selected == 0) parentMenu(MenuView::DIAG_LOG);
        else {
            jarnsen::diagnosticLogRequestUsbExport(Serial);
            redraw();
        }
        return true;
    case MenuView::LOG_CLEAR:
        if (selected == 0) parentMenu(MenuView::DIAG_LOG);
        else {
            if (!requireMenuAuthorization()) return true;
            jarnsen::diagnosticLogClear();
            parentMenu(MenuView::DIAG_LOG);
        }
        return true;

    case MenuView::SYSTEM:
        if (selected == 0) parentMenu(MenuView::SYSTEM_INFO);
        else if (selected == 1) parentMenu(MenuView::DIAGNOSTICS);
        else if (selected == 2) parentMenu(MenuView::POWER);
        else if (selected == 3) parentMenu(MenuView::ANTENNA_TEST);
        else if (selected == 4) enterStockMeshtastic();
        else parentMenu(MenuView::MAIN, 4);
        return true;
    case MenuView::SYSTEM_INFO:
    case MenuView::DIAGNOSTICS:
        if (selected == 0) parentMenu(MenuView::SYSTEM);
        return true;
    case MenuView::POWER:
        if (selected == 0) parentMenu(MenuView::POWER_STATS);
        else if (selected == 1) parentMenu(MenuView::INA226);
        else parentMenu(MenuView::SYSTEM);
        return true;
    case MenuView::POWER_STATS:
        if (selected == 0) parentMenu(MenuView::POWER);
        return true;
    case MenuView::INA226:
        if (selected == 0) parentMenu(MenuView::POWER);
        else parentMenu(MenuView::POWER);
        return true;
    case MenuView::ANTENNA_TEST:
        if (selected == 0) parentMenu(MenuView::SYSTEM);
        return true;

    case MenuView::NODES:
        if (selected == 0) {
            parentMenu(MenuView::MAIN);
        } else if (meshtastic_NodeInfoLite *node = nodeAtOtherIndex(selected - 1)) {
            selectedNodeNum = node->num;
            selectedNodeIndex = selected - 1;
            menuView = MenuView::NONE;
            nodeNavigationMode = true;
            menuLastActivityMs = millis() ? millis() : 1U;
            redraw();
        }
        return true;

    default:
        parentMenu(MenuView::MAIN);
        return true;
    }
}

bool jarnsenDisplayHandleBack()
{
    menuLastActivityMs = millis() ? millis() : 1U;

    if (menuPinMode) {
        cancelMenuPinRequest();
        redraw();
        return true;
    }
    if (stockUiActive) {
        stockUiActive = false;
        parentMenu(MenuView::MAIN);
        return true;
    }
    if (nodeNavigationMode) {
        parentMenu(MenuView::NODES, static_cast<uint8_t>(selectedNodeIndex + 1U));
        return true;
    }

    switch (menuView) {
    case MenuView::PROFILE:
    case MenuView::TRACKER:
    case MenuView::SERVICE:
    case MenuView::SYSTEM:
    case MenuView::NODES:
        parentMenu(MenuView::MAIN);
        return true;
    case MenuView::POSITION:
    case MenuView::MOTION:
    case MenuView::PARKING:
        parentMenu(MenuView::TRACKER);
        return true;
    case MenuView::SMART_DISTANCE:
    case MenuView::MIN_TX_INTERVAL:
    case MenuView::MOVING_GNSS:
        parentMenu(MenuView::POSITION);
        return true;
    case MenuView::MOTION_STATUS:
    case MenuView::WAKE_SENSOR:
    case MenuView::MOTION_SENSITIVITY:
        parentMenu(MenuView::MOTION);
        return true;
    case MenuView::PARK_INTERVAL:
    case MenuView::GPS_SEARCH_TIME:
        parentMenu(MenuView::PARKING);
        return true;
    case MenuView::BLUETOOTH:
    case MenuView::WLAN:
    case MenuView::DIAG_LOG:
        parentMenu(MenuView::SERVICE);
        return true;
    case MenuView::BLE_IDLE:
    case MenuView::BLE_HARD:
        parentMenu(MenuView::BLUETOOTH);
        return true;
    case MenuView::LOGGING:
    case MenuView::LOG_STATUS:
    case MenuView::LOG_EXPORT:
    case MenuView::LOG_CLEAR:
        parentMenu(MenuView::DIAG_LOG);
        return true;
    case MenuView::SYSTEM_INFO:
    case MenuView::DIAGNOSTICS:
    case MenuView::POWER:
    case MenuView::ANTENNA_TEST:
        parentMenu(MenuView::SYSTEM);
        return true;
    case MenuView::POWER_STATS:
    case MenuView::INA226:
        parentMenu(MenuView::POWER);
        return true;
    case MenuView::MAIN:
        menuView = MenuView::NONE;
        menuSelection = 0;
        redraw();
        return true;
    case MenuView::NONE:
    default:
        return false;
    }
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
