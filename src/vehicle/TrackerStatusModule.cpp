#include "configuration.h"

#if defined(HELTEC_TRACKER_V1_1) && HAS_SCREEN

#include "BluetoothStatus.h"
#include "GPSStatus.h"
#include "NodeDB.h"
#include "PowerStatus.h"
#include "gps/RTC.h"
#include "graphics/Screen.h"
#include "graphics/ScreenFonts.h"
#include "graphics/TFTColorRegions.h"
#include "graphics/TFTPalette.h"
#include "jarnsen/adapters/JarnsenLegacyStatusBridge.h"
#include "jarnsen/core/display/JarnsenDisplayModel.h"
#include "jarnsen/core/position/JarnsenPositionCore.h"
#include "jarnsen/core/status/JarnsenStatusProvider.h"
#include "mesh/Channels.h"
#include "mesh/MeshModule.h"
#include "mesh/http/JarnsenServiceWeb.h"
#include "vehicle/JarnsenBuildInfo.h"
#include "vehicle/TrackerAntennaTest.h"
#include "vehicle/TrackerCommonPolicy.h"
#include "vehicle/TrackerDiagnosticLog.h"
#include "vehicle/TrackerEnhancements.h"
#include "vehicle/TrackerPowerMonitor.h"
#include "vehicle/TrackerServiceSettings.h"
#include "vehicle/TrackerStatusModule.h"

#include <algorithm>
#include <cmath>
#include <cstdio>
#include <cstring>

namespace
{
constexpr uint32_t MENU_TIMEOUT_MS = 30000UL;

volatile bool trackerMotionActive = false;
bool trackerInteractionActive = false;
bool trackerMenuMode = false;
bool trackerStockUiMode = false;
bool trackerNodeNavigationMode = false;
uint32_t trackerMenuLastActivityMs = 0;
uint8_t trackerMenuSelection = 0;
uint8_t trackerStatusFrameIndex = 255;
uint32_t selectedNodeNum = 0;
size_t selectedNodeIndex = 0;
jarnsen::DisplayPage currentPage = jarnsen::DisplayPage::MGRS;

enum class MenuView : uint8_t {
    MAIN = 0,
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

MenuView menuView = MenuView::MAIN;

jarnsen::DeviceRole trackerUiRole()
{
    jarnsen::ensureLegacyStatusBridge();
    return jarnsen::activeDeviceRoleOr(jarnsen::DeviceRole::UNCONFIGURED);
}

bool trackerUiRoleEnabled()
{
    switch (trackerUiRole()) {
    case jarnsen::DeviceRole::TAK:
    case jarnsen::DeviceRole::TAK_TRACKER:
    case jarnsen::DeviceRole::TAK_REPEATER:
    case jarnsen::DeviceRole::DRONE_REPEATER:
        return true;
    default:
        return false;
    }
}

const char *trackerRoleText()
{
    switch (trackerUiRole()) {
    case jarnsen::DeviceRole::TAK:
        return "TAK";
    case jarnsen::DeviceRole::TAK_TRACKER:
        return "TAK TRACKER";
    case jarnsen::DeviceRole::TAK_REPEATER:
        return "TAK REPEATER";
    case jarnsen::DeviceRole::DRONE_REPEATER:
        return "DRONE REPEATER";
    default:
        return "--";
    }
}

const char *trackerSleepText()
{
    switch (trackerUiRole()) {
    case jarnsen::DeviceRole::TAK_TRACKER:
        return "DEEP";
    case jarnsen::DeviceRole::TAK:
        return "LIGHT";
    default:
        return "--";
    }
}

bool readOwnPosition(meshtastic_PositionLite &position)
{
    if (!nodeDB || !nodeDB->hasLocalPositionSinceBoot())
        return false;
    if (!nodeDB->copyNodePosition(nodeDB->getNodeNum(), position))
        return false;
    return position.latitude_i != 0 || position.longitude_i != 0;
}

uint32_t positionAgeSecs(const meshtastic_PositionLite &position)
{
    const uint32_t nowEpoch = getValidTime(RTCQualityDevice);
    if (position.time != 0 && nowEpoch != 0 && nowEpoch >= position.time)
        return nowEpoch - position.time;
    if (gpsStatus && gpsStatus->getLastFixMillis() != 0 && millis() >= gpsStatus->getLastFixMillis())
        return (millis() - gpsStatus->getLastFixMillis()) / 1000UL;
    return UINT32_MAX;
}

unsigned horizontalAccuracyMeters()
{
    if (config.position.fixed_position || !gpsStatus || !gpsStatus->getHasLock())
        return 0;

    // Prefer the receiver-provided horizontal DOP and hardware accuracy when
    // available. Older Tracker paths only expose PDOP, so preserve the proven
    // ~3 m hardware-accuracy fallback instead of fabricating a precise value.
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
    display->drawString(x + display->getWidth() / 2, y + 1, title ? title : "");
    drawBattery(display, x, y);
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

const char *regionText()
{
    switch (config.lora.region) {
    case meshtastic_Config_LoRaConfig_RegionCode_EU_868:
        return "EU868";
    case meshtastic_Config_LoRaConfig_RegionCode_EU_433:
        return "EU433";
    case meshtastic_Config_LoRaConfig_RegionCode_US:
        return "US";
    case meshtastic_Config_LoRaConfig_RegionCode_ANZ:
        return "ANZ";
    case meshtastic_Config_LoRaConfig_RegionCode_EU_866:
        return "EU866";
    case meshtastic_Config_LoRaConfig_RegionCode_EU_874:
        return "EU874";
    case meshtastic_Config_LoRaConfig_RegionCode_EU_917:
        return "EU917";
    case meshtastic_Config_LoRaConfig_RegionCode_EU_N_868:
        return "EUN868";
    case meshtastic_Config_LoRaConfig_RegionCode_UNSET:
        return "REGION--";
    default:
        return "REGION";
    }
}

const char *presetText()
{
    if (!config.lora.use_preset)
        return "CUSTOM";
    switch (config.lora.modem_preset) {
    case meshtastic_Config_LoRaConfig_ModemPreset_LONG_FAST:
        return "LONGFAST";
    case meshtastic_Config_LoRaConfig_ModemPreset_LONG_SLOW:
        return "LONGSLOW";
    case meshtastic_Config_LoRaConfig_ModemPreset_VERY_LONG_SLOW:
        return "V-LONGSLOW";
    case meshtastic_Config_LoRaConfig_ModemPreset_MEDIUM_SLOW:
        return "MED-SLOW";
    case meshtastic_Config_LoRaConfig_ModemPreset_MEDIUM_FAST:
        return "MED-FAST";
    case meshtastic_Config_LoRaConfig_ModemPreset_SHORT_SLOW:
        return "SHORTSLOW";
    case meshtastic_Config_LoRaConfig_ModemPreset_SHORT_FAST:
        return "SHORTFAST";
    case meshtastic_Config_LoRaConfig_ModemPreset_LONG_MODERATE:
        return "LONG-MOD";
    case meshtastic_Config_LoRaConfig_ModemPreset_SHORT_TURBO:
        return "SHORTTURBO";
    case meshtastic_Config_LoRaConfig_ModemPreset_LONG_TURBO:
        return "LONGTURBO";
    default:
        return "PRESET";
    }
}

void drawMgrsPage(OLEDDisplay *display, int16_t x, int16_t y)
{
    const int w = display->getWidth();
    const int h = display->getHeight();
    const jarnsen::DisplayBands bands = jarnsen::displayBands(h);
    meshtastic_PositionLite position = meshtastic_PositionLite_init_default;
    const bool havePosition = readOwnPosition(position);
    const bool fixed = config.position.fixed_position && havePosition;
    const bool liveFix = gpsStatus && gpsStatus->getHasLock() && havePosition;

    if (!fixed && !liveFix) {
        const bool waiting = gpsStatus && gpsStatus->getIsConnected();
        drawHeader(display, x, y, waiting ? "GPS WAIT" : "MGRS");
        display->setTextAlignment(TEXT_ALIGN_CENTER);
        display->setFont(FONT_MEDIUM);
        display->drawString(x + w / 2, y + bands.middleY + bands.middleHeight / 2 - FONT_HEIGHT_MEDIUM / 2, "KEINE POSITION");
        display->setFont(FONT_SMALL);
        display->drawString(x + w / 2, y + bands.bottomY + 2, waiting ? "GPS     NO FIX       --" : "QUELLE --           --");
#if GRAPHICS_TFT_COLORING_ENABLED
        graphics::registerTFTColorRegionDirect(x, y, w, h, graphics::TFTPalette::Red, graphics::getThemeBodyBg());
#endif
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

    display->setTextAlignment(TEXT_ALIGN_CENTER);
    display->setFont(FONT_LARGE);
    display->drawString(x + w / 2, y + bands.middleY + std::max(0, (static_cast<int>(bands.middleHeight) - FONT_HEIGHT_LARGE) / 2), digits);

    const char *motion = fixed ? "FIXED" : (trackerMotionActive ? "MOVING" : "PARK");
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

const char *ownLongName(char *out, size_t outSize)
{
    if (!out || outSize == 0)
        return "NODE";
    out[0] = '\0';
    if (nodeDB) {
        meshtastic_NodeInfoLite *node = nodeDB->getMeshNode(nodeDB->getNodeNum());
        if (node && nodeInfoLiteHasUser(node) && node->long_name[0]) {
            std::snprintf(out, outSize, "%.24s", node->long_name);
            return out;
        }
    }
    std::snprintf(out, outSize, "NODE");
    return out;
}

void formatCompactDuration(uint32_t seconds, char *out, size_t outSize)
{
    if (!out || outSize == 0)
        return;
    const uint32_t days = seconds / 86400UL;
    const uint32_t hours = (seconds % 86400UL) / 3600UL;
    const uint32_t mins = (seconds % 3600UL) / 60UL;
    if (days)
        std::snprintf(out, outSize, "%ud%02uh", (unsigned)days, (unsigned)hours);
    else if (hours)
        std::snprintf(out, outSize, "%uh%02um", (unsigned)hours, (unsigned)mins);
    else
        std::snprintf(out, outSize, "%umin", (unsigned)mins);
}

void drawOwnNodePage(OLEDDisplay *display, int16_t x, int16_t y)
{
    const int w = display->getWidth();
    const int h = display->getHeight();
    const auto bands = jarnsen::displayBands(h);
    const TrackerPowerStats p = trackerPowerMonitorStats();

    // Page 2 uses the same compact status header as the other pages:
    // page index on the left, battery indicator on the right, center intentionally empty.
    display->setFont(FONT_SMALL);
    display->setTextAlignment(TEXT_ALIGN_LEFT);
    display->drawString(x + 2, y + 1, "2/5");
    drawBattery(display, x, y);

    char name[32] = {};
    ownLongName(name, sizeof(name));
    const int maxNameWidth = std::max(1, w - 8);
    int nameHeight = FONT_HEIGHT_LARGE;

    // Fit by actual rendered pixel width, not character count. This matters on
    // the Tracker's 160x80 TFT because glyphs are variable-width.
    display->setFont(FONT_LARGE);
    if (display->getStringWidth(name) > maxNameWidth) {
        display->setFont(FONT_MEDIUM);
        nameHeight = FONT_HEIGHT_MEDIUM;
    }
    if (display->getStringWidth(name) > maxNameWidth) {
        display->setFont(FONT_SMALL);
        nameHeight = FONT_HEIGHT_SMALL;
    }
    if (display->getStringWidth(name) > maxNameWidth) {
        constexpr char ellipsis[] = "...";
        const int ellipsisWidth = display->getStringWidth(ellipsis);
        size_t len = std::strlen(name);
        while (len > 0 && display->getStringWidth(name) + ellipsisWidth > maxNameWidth)
            name[--len] = '\0';
        if (len + 3 < sizeof(name))
            std::strcat(name, ellipsis);
    }

    display->setTextAlignment(TEXT_ALIGN_CENTER);
    display->drawString(x + w / 2,
                        y + bands.middleY +
                            std::max(0, (static_cast<int>(bands.middleHeight) - nameHeight) / 2),
                        name);

    char ontime[16] = {};
    char remaining[16] = "LERNT";
    formatCompactDuration(millis() / 1000UL, ontime, sizeof(ontime));
    if (p.usbPowered)
        std::snprintf(remaining, sizeof(remaining), "USB");
    else if (p.charging)
        std::snprintf(remaining, sizeof(remaining), "LAEDT");
    else if (p.estimateReady)
        formatCompactDuration(p.remainingSecs, remaining, sizeof(remaining));

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

void drawServicePage(OLEDDisplay *display, int16_t x, int16_t y)
{
    const int w = display->getWidth();
    const int h = display->getHeight();
    const auto bands = jarnsen::displayBands(h);
    drawHeader(display, x, y, "SERVICE");

    const char *state = "READY";
    char detail[64] = {};
    bool error = false;
    if (trackerDiagUsbExportPending()) {
        state = "LOG DOWNLOAD";
        std::snprintf(detail, sizeof(detail), "USB   %u%%", (unsigned)trackerDiagUsbExportProgress());
    } else if (trackerDiagBleExportActive()) {
        state = "LOG DOWNLOAD";
        std::snprintf(detail, sizeof(detail), "BLE   %u%%", (unsigned)trackerDiagBleExportProgress());
    } else if (jarnsenServiceWebActive()) {
        state = "AP ON";
        std::snprintf(detail, sizeof(detail), "WLAN   %s", jarnsenServiceWebAddress());
    } else if (bluetoothStatus && bluetoothStatus->getConnectionState() == meshtastic::BluetoothStatus::ConnectionState::CONNECTED) {
        state = "CONNECTED";
        std::snprintf(detail, sizeof(detail), "BLE   OK");
    } else if (jarnsenServiceWebLastError()[0]) {
        // A previous AP error is useful only when it is genuinely present; merely
        // viewing this page never starts the AP and therefore creates no error.
        state = "READY";
        std::snprintf(detail, sizeof(detail), "USB %s   BLE READY", powerStatus && powerStatus->getHasUSB() ? "ON" : "--");
    } else {
        std::snprintf(detail, sizeof(detail), "USB %s   BLE READY", powerStatus && powerStatus->getHasUSB() ? "ON" : "--");
    }

    display->setTextAlignment(TEXT_ALIGN_CENTER);
    display->setFont(FONT_MEDIUM);
    display->drawString(x + w / 2, y + bands.middleY + std::max(0, (static_cast<int>(bands.middleHeight) - FONT_HEIGHT_MEDIUM) / 2), state);
    display->setFont(FONT_SMALL);
    display->drawString(x + w / 2, y + bands.bottomY + 2, detail);
#if GRAPHICS_TFT_COLORING_ENABLED
    if (error)
        graphics::registerTFTColorRegionDirect(x, y + bands.middleY, w, bands.middleHeight, graphics::TFTPalette::Red,
                                               graphics::getThemeBodyBg());
#endif
}

void drawRadioPage(OLEDDisplay *display, int16_t x, int16_t y)
{
    const int w = display->getWidth();
    const int h = display->getHeight();
    const auto bands = jarnsen::displayBands(h);
    drawBattery(display, x, y);
    display->setFont(FONT_SMALL);
    display->setTextAlignment(TEXT_ALIGN_LEFT);
    display->drawString(x + 2, y + 1, regionText());
    display->setTextAlignment(TEXT_ALIGN_CENTER);
    display->drawString(x + w / 2, y + 1, "PROFIL --");

    display->setFont(FONT_MEDIUM);
    display->drawString(x + w / 2, y + bands.middleY + std::max(0, (static_cast<int>(bands.middleHeight) - FONT_HEIGHT_MEDIUM) / 2), presetText());

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

void drawNetworkPage(OLEDDisplay *display, int16_t x, int16_t y)
{
    const int w = display->getWidth();
    const int h = display->getHeight();
    const auto bands = jarnsen::displayBands(h);
    const char *channel = channels.getName(channels.getPrimaryIndex());
    drawHeader(display, x, y, channel && channel[0] ? channel : "NETZ");

    char middle[32] = {};
    const size_t known = otherNodeCount();
    std::snprintf(middle, sizeof(middle), "%u NODES", (unsigned)known);
    display->setTextAlignment(TEXT_ALIGN_CENTER);
    display->setFont(FONT_MEDIUM);
    display->drawString(x + w / 2, y + bands.middleY + std::max(0, (static_cast<int>(bands.middleHeight) - FONT_HEIGHT_MEDIUM) / 2), middle);

    char age[16] = "--";
    const uint32_t newest = newestOtherNodeAge();
    if (newest != UINT32_MAX) {
        if (newest < 60)
            std::snprintf(age, sizeof(age), "%us", (unsigned)newest);
        else
            std::snprintf(age, sizeof(age), "%umin", (unsigned)(newest / 60U));
    }
    char bottom[64] = {};
    const size_t online = nodeDB ? std::max<size_t>(0, nodeDB->getNumOnlineMeshNodes(true)) : 0;
    std::snprintf(bottom, sizeof(bottom), "DIRECT %u   ONLINE %u   %s", (unsigned)directNodeCount(), (unsigned)online, age);
    display->setFont(FONT_SMALL);
    display->drawString(x + w / 2, y + bands.bottomY + 2, bottom);
}

void drawSystemPage(OLEDDisplay *display, int16_t x, int16_t y)
{
    const int w = display->getWidth();
    const int h = display->getHeight();
    const auto bands = jarnsen::displayBands(h);
    const TrackerPowerStats p = trackerPowerMonitorStats();
    drawHeader(display, x, y, "SYSTEM");

    char uptime[24] = {};
    trackerPowerFormatDuration(millis() / 1000UL, uptime, sizeof(uptime));
    char remaining[24] = "--";
    if (!p.usbPowered && !p.charging && p.estimateReady)
        trackerPowerFormatDuration(p.remainingSecs, remaining, sizeof(remaining));

    char line1[64] = {};
    char line2[64] = {};
    char line3[64] = {};
    std::snprintf(line1, sizeof(line1), "UP %-8s      %u.%03u V", uptime, (unsigned)(p.voltageMv / 1000U), (unsigned)(p.voltageMv % 1000U));
    if (p.inaValid) {
        const int32_t c = p.currentMilliAmpsX10;
        const int32_t ac = c < 0 ? -c : c;
        std::snprintf(line2, sizeof(line2), "REST %-8s   %s%ld.%ld mA", remaining, c < 0 ? "-" : "", (long)(ac / 10), (long)(ac % 10));
    } else {
        std::snprintf(line2, sizeof(line2), "REST %-8s        -- mA", remaining);
    }
    if (p.inaValid && p.vbusValid) {
        const int32_t mw = p.powerMilliWattsX10;
        const int32_t amw = mw < 0 ? -mw : mw;
        std::snprintf(line3, sizeof(line3), "VOLL --       %s%ld.%03ld W", mw < 0 ? "-" : "", (long)(amw / 10000),
                      (long)((amw % 10000) / 10));
    } else {
        std::snprintf(line3, sizeof(line3), "VOLL --             -- W");
    }

    display->setTextAlignment(TEXT_ALIGN_CENTER);
    display->setFont(FONT_SMALL);
    const int top = y + bands.middleY + 2;
    display->drawString(x + w / 2, top, line1);
    display->drawString(x + w / 2, top + 11, line2);
    display->drawString(x + w / 2, top + 22, line3);

    char bottom[64] = {};
    const char *source = p.charging ? "CHARGE" : (p.usbPowered ? "USB" : "BAT");
    const char *ina = !p.inaConfigured ? "INA OFF" : (!p.inaPresent ? "INA MISS" : (p.inaValid ? "INA OK" : "INA WAIT"));
    std::snprintf(bottom, sizeof(bottom), "%s      %s      %s", source, ina, p.batteryValid ? "OK" : "--");
    display->drawString(x + w / 2, y + bands.bottomY + 2, bottom);
}

meshtastic_NodeInfoLite *nodeAtOtherIndex(size_t otherIndex, size_t *rawIndex = nullptr)
{
    if (!nodeDB)
        return nullptr;
    size_t seen = 0;
    for (size_t i = 0; i < nodeDB->getNumMeshNodes(); ++i) {
        meshtastic_NodeInfoLite *n = nodeDB->getMeshNodeByIndex(i);
        if (!n || n->num == nodeDB->getNodeNum())
            continue;
        if (seen == otherIndex) {
            if (rawIndex)
                *rawIndex = i;
            return n;
        }
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
    const int len = 21;
    const int head = 8;
    const int endX = centerX + static_cast<int>(std::cos(a) * len);
    const int endY = centerY + static_cast<int>(std::sin(a) * len);
    display->drawLine(centerX, centerY, endX, endY);
    display->drawLine(endX, endY, endX + static_cast<int>(std::cos(leftA) * head), endY + static_cast<int>(std::sin(leftA) * head));
    display->drawLine(endX, endY, endX + static_cast<int>(std::cos(rightA) * head), endY + static_cast<int>(std::sin(rightA) * head));
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
    const bool ownOk = readOwnPosition(own);
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

    const double distance = jarnsenPositionDistanceMeters(own.latitude_i, own.longitude_i, remote.latitude_i, remote.longitude_i);
    const double bearing = jarnsenPositionBearingDegrees(own.latitude_i, own.longitude_i, remote.latitude_i, remote.longitude_i);
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

    const bool headingValid = trackerMotionActive && gpsStatus && gpsStatus->getHasLock() && localPosition.has_ground_track;
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
    case MenuView::MAIN:
        return "MENUE";
    case MenuView::PROFILE:
        return "PROFIL";
    case MenuView::TRACKER:
        return "TRACKER";
    case MenuView::POSITION:
        return "POSITION";
    case MenuView::SMART_DISTANCE:
        return "SMART DISTANCE";
    case MenuView::MIN_TX_INTERVAL:
        return "MIN TX INTERVAL";
    case MenuView::MOVING_GNSS:
        return "MOVING GNSS";
    case MenuView::MOTION:
        return "MOTION";
    case MenuView::MOTION_STATUS:
        return "MOTION STATUS";
    case MenuView::WAKE_SENSOR:
        return "WAKE SENSOR";
    case MenuView::MOTION_SENSITIVITY:
        return "EMPFINDLICHKEIT";
    case MenuView::PARKING:
        return "PARKING";
    case MenuView::PARK_INTERVAL:
        return "PARK-INTERVALL";
    case MenuView::GPS_SEARCH_TIME:
        return "GPS-SUCHZEIT";
    case MenuView::SERVICE:
        return "SERVICE";
    case MenuView::BLUETOOTH:
        return "BLUETOOTH";
    case MenuView::BLE_IDLE:
        return "IDLE TIMEOUT";
    case MenuView::BLE_HARD:
        return "HARD TIMEOUT";
    case MenuView::WLAN:
        return "WLAN SERVICE";
    case MenuView::DIAG_LOG:
        return "DIAGNOSTIC LOG";
    case MenuView::LOGGING:
        return "LOGGING";
    case MenuView::LOG_STATUS:
        return "LOG STATUS";
    case MenuView::LOG_EXPORT:
        return "USB-EXPORT";
    case MenuView::LOG_CLEAR:
        return "LOG LOESCHEN";
    case MenuView::SYSTEM:
        return "SYSTEM";
    case MenuView::SYSTEM_INFO:
        return "SYSTEM INFO";
    case MenuView::DIAGNOSTICS:
        return "DIAGNOSTICS";
    case MenuView::POWER:
        return "POWER";
    case MenuView::POWER_STATS:
        return "POWER STATISTICS";
    case MenuView::INA226:
        return "INA226 HARDWARE";
    case MenuView::ANTENNA_TEST:
        return "ANTENNENTEST";
    case MenuView::NODES:
        return "NODES";
    default:
        return "MENUE";
    }
}

uint8_t menuCount(MenuView view)
{
    switch (view) {
    case MenuView::MAIN:
        return 6;
    case MenuView::PROFILE:
        return 4;
    case MenuView::TRACKER:
        return 4;
    case MenuView::POSITION:
        return 4;
    case MenuView::SMART_DISTANCE:
    case MenuView::MIN_TX_INTERVAL:
    case MenuView::MOVING_GNSS:
    case MenuView::MOTION_SENSITIVITY:
    case MenuView::GPS_SEARCH_TIME:
    case MenuView::BLE_IDLE:
    case MenuView::BLE_HARD:
        return 5;
    case MenuView::MOTION:
        return 4;
    case MenuView::MOTION_STATUS:
        return 4;
    case MenuView::WAKE_SENSOR:
        return 3;
    case MenuView::PARKING:
        return 3;
    case MenuView::PARK_INTERVAL:
        return 9;
    case MenuView::SERVICE:
        return 4;
    case MenuView::BLUETOOTH:
        return 3;
    case MenuView::WLAN:
        return 6;
    case MenuView::DIAG_LOG:
        return 5;
    case MenuView::LOGGING:
        return 3;
    case MenuView::LOG_STATUS:
        return 4;
    case MenuView::LOG_EXPORT:
    case MenuView::LOG_CLEAR:
        return 2;
    case MenuView::SYSTEM:
        return 6;
    case MenuView::SYSTEM_INFO:
        return 5;
    case MenuView::DIAGNOSTICS:
        return 6;
    case MenuView::POWER:
        return 3;
    case MenuView::POWER_STATS:
        return 9;
    case MenuView::INA226:
        return 3;
    case MenuView::ANTENNA_TEST:
        return 9;
    case MenuView::NODES:
        return static_cast<uint8_t>(std::min<size_t>(254, otherNodeCount() + 1));
    default:
        return 1;
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
        if (index == 0)
            return "ZURUECK";
        const uint16_t vals[] = {50, 75, 100, 150};
        std::snprintf(buffer, size, "%c %u m", trackerSmartDistanceM() == vals[index - 1] ? '*' : ' ', (unsigned)vals[index - 1]);
        return buffer;
    }
    case MenuView::MIN_TX_INTERVAL: {
        if (index == 0)
            return "ZURUECK";
        const uint16_t vals[] = {30, 45, 60, 90};
        std::snprintf(buffer, size, "%c %u s", trackerSmartIntervalSecs() == vals[index - 1] ? '*' : ' ', (unsigned)vals[index - 1]);
        return buffer;
    }
    case MenuView::MOVING_GNSS: {
        if (index == 0)
            return "ZURUECK";
        const uint16_t vals[] = {5, 10, 15, 30};
        std::snprintf(buffer, size, "%c %u s", trackerMovingGnssSecs() == vals[index - 1] ? '*' : ' ', (unsigned)vals[index - 1]);
        return buffer;
    }
    case MenuView::MOTION: {
        static const char *items[] = {"Bewegungsstatus", "WAKE SENSOR", "Empfindlichkeit", "ZURUECK"};
        return items[index % 4];
    }
    case MenuView::MOTION_STATUS:
        if (index == 0)
            return "ZURUECK";
        if (index == 1) {
            std::snprintf(buffer, size, "Motion: %s", trackerMotionActive ? "MOVING" : "PARK");
            return buffer;
        }
        if (index == 2) {
            std::snprintf(buffer, size, "Sensor: %s", trackerMotionSensorStatus());
            return buffer;
        }
        std::snprintf(buffer, size, "Runtime: %s", trackerCommonRuntimeState());
        return buffer;
    case MenuView::WAKE_SENSOR:
        if (index == 0)
            return "ZURUECK";
        if (index == 1) {
            std::snprintf(buffer, size, "Status: %s", trackerMotionSensorStatus());
            return buffer;
        }
        std::snprintf(buffer, size, "Sens: %s", trackerMotionSensitivityName());
        return buffer;
    case MenuView::MOTION_SENSITIVITY: {
        if (index == 0)
            return "ZURUECK";
        static const char *names[] = {"VERY SENS", "SENSITIVE", "NORMAL", "ROBUST"};
        std::snprintf(buffer, size, "%c %s", trackerMotionSensitivityIndex() == index - 1 ? '*' : ' ', names[index - 1]);
        return buffer;
    }
    case MenuView::PARKING: {
        static const char *items[] = {"Park-Intervall", "GPS-Suchzeit", "ZURUECK"};
        return items[index % 3];
    }
    case MenuView::PARK_INTERVAL: {
        if (index == 0)
            return "ZURUECK";
        const uint16_t vals[] = {20, 30, 60, 120, 240, 360, 540, 720};
        const char *names[] = {"20 min", "30 min", "60 min", "2 h", "4 h", "6 h", "9 h", "12 h"};
        std::snprintf(buffer, size, "%c %s", trackerParkIntervalMinutes() == vals[index - 1] ? '*' : ' ', names[index - 1]);
        return buffer;
    }
    case MenuView::GPS_SEARCH_TIME: {
        if (index == 0)
            return "ZURUECK";
        const uint16_t vals[] = {15, 30, 45, 60};
        std::snprintf(buffer, size, "%c %u s", trackerParkGpsSearchSecs() == vals[index - 1] ? '*' : ' ', (unsigned)vals[index - 1]);
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
        if (index == 0)
            return "ZURUECK";
        const uint16_t vals[] = {60, 120, 180, 300};
        std::snprintf(buffer, size, "%c %u s", trackerBleIdleTimeoutSecs() == vals[index - 1] ? '*' : ' ', (unsigned)vals[index - 1]);
        return buffer;
    }
    case MenuView::BLE_HARD: {
        if (index == 0)
            return "ZURUECK";
        const uint16_t vals[] = {300, 600, 900, 1800};
        const char *names[] = {"5 min", "10 min", "15 min", "30 min"};
        std::snprintf(buffer, size, "%c %s", trackerBleHardTimeoutSecs() == vals[index - 1] ? '*' : ' ', names[index - 1]);
        return buffer;
    }
    case MenuView::WLAN:
        if (index == 0)
            return "ZURUECK";
        if (index == 1)
            return jarnsenServiceWebActive() ? "WLAN BEENDEN" : "WLAN STARTEN";
        if (index == 2) {
            std::snprintf(buffer, size, "Status: %s", jarnsenServiceWebActive() ? "AKTIV" : "AUS");
            return buffer;
        }
        if (index == 3) {
            std::snprintf(buffer, size, "SSID: %s", jarnsenServiceWebSsid());
            return buffer;
        }
        if (index == 4) {
            std::snprintf(buffer, size, "PW: %s", jarnsenServiceWebPassword());
            return buffer;
        }
        std::snprintf(buffer, size, "IP: %s", jarnsenServiceWebAddress());
        return buffer;
    case MenuView::DIAG_LOG: {
        static const char *items[] = {"Status", "Logging Ein/Aus", "USB-Export", "Log loeschen", "ZURUECK"};
        return items[index % 5];
    }
    case MenuView::LOGGING:
        if (index == 0)
            return "ZURUECK";
        if (index == 1)
            return trackerDiagEnabled() ? "* EIN" : "  EIN";
        return !trackerDiagEnabled() ? "* AUS" : "  AUS";
    case MenuView::LOG_STATUS:
        if (index == 0)
            return "ZURUECK";
        if (index == 1) {
            std::snprintf(buffer, size, "Logging: %s", trackerDiagEnabled() ? "EIN" : "AUS");
            return buffer;
        }
        if (index == 2) {
            std::snprintf(buffer, size, "Log: %u KB", (unsigned)((trackerDiagLogSize() + 1023U) / 1024U));
            return buffer;
        }
        std::snprintf(buffer, size, "USB: %s", trackerDiagUsbExportStatusText());
        return buffer;
    case MenuView::LOG_EXPORT:
        if (index == 0)
            return "ZURUECK";
        std::snprintf(buffer, size, "%s %u%%", trackerDiagUsbExportPending() ? "EXPORT" : "EXPORT START", (unsigned)trackerDiagUsbExportProgress());
        return buffer;
    case MenuView::LOG_CLEAR:
        return index == 0 ? "ZURUECK" : "LOESCHEN BESTAETIGEN";
    case MenuView::SYSTEM: {
        static const char *items[] = {"SYSTEM INFO", "DIAGNOSTICS", "POWER", "ANTENNENTEST", "MESHTASTIC", "ZURUECK"};
        return items[index % 6];
    }
    case MenuView::SYSTEM_INFO:
        if (index == 0)
            return "ZURUECK";
        if (index == 1) {
            std::snprintf(buffer, size, "FW: %s", JARNSEN_FIRMWARE_VERSION);
            return buffer;
        }
        if (index == 2) {
            std::snprintf(buffer, size, "Build: %.8s", JARNSEN_BUILD_SHA);
            return buffer;
        }
        if (index == 3) {
            std::snprintf(buffer, size, "Role: %s", trackerRoleText());
            return buffer;
        }
        const int displayWidth = screen ? screen->getWidth() : 0;
        const int displayHeight = screen ? screen->getHeight() : 0;
        std::snprintf(buffer, size, "Display: %dx%d", displayWidth, displayHeight);
        return buffer;
    case MenuView::DIAGNOSTICS:
        if (index == 0)
            return "ZURUECK";
        if (index == 1) {
            std::snprintf(buffer, size, "State: %s", trackerCommonRuntimeState());
            return buffer;
        }
        if (index == 2) {
            const uint32_t age = trackerLastFixAgeSecs();
            if (age == UINT32_MAX)
                std::snprintf(buffer, size, "GPS age: --");
            else
                std::snprintf(buffer, size, "GPS age: %us", (unsigned)age);
            return buffer;
        }
        if (index == 3) {
            std::snprintf(buffer, size, "Sensor: %s", trackerMotionSensorStatus());
            return buffer;
        }
        if (index == 4) {
            std::snprintf(buffer, size, "Wake: %s", trackerBootWakeReason());
            return buffer;
        }
        std::snprintf(buffer, size, "Sleep: %s", trackerSleepText());
        return buffer;
    case MenuView::POWER: {
        static const char *items[] = {"Power Statistics", "INA226 Hardware", "ZURUECK"};
        return items[index % 3];
    }
    case MenuView::POWER_STATS: {
        const TrackerPowerStats p = trackerPowerMonitorStats();
        if (index == 0)
            return "ZURUECK";
        if (index == 1) {
            std::snprintf(buffer, size, "Akku: %u%% %u.%03uV", (unsigned)p.batteryPercent, (unsigned)(p.voltageMv / 1000U),
                          (unsigned)(p.voltageMv % 1000U));
            return buffer;
        }
        if (index == 2) {
            char d[20] = "--";
            if (p.estimateReady && !p.usbPowered && !p.charging)
                trackerPowerFormatDuration(p.remainingSecs, d, sizeof(d));
            std::snprintf(buffer, size, "Rest: %s", d);
            return buffer;
        }
        if (index == 3) {
            if (p.inaValid) {
                const int32_t c = p.currentMilliAmpsX10;
                std::snprintf(buffer, size, "Strom: %ld.%ldmA", (long)(c / 10), (long)std::abs(c % 10));
            } else
                std::snprintf(buffer, size, "Strom: --");
            return buffer;
        }
        if (index == 4) {
            if (p.inaValid && p.vbusValid)
                std::snprintf(buffer, size, "Power: %ld.%ldmW", (long)(p.powerMilliWattsX10 / 10),
                              (long)std::abs(p.powerMilliWattsX10 % 10));
            else
                std::snprintf(buffer, size, "Power: --");
            return buffer;
        }
        if (index == 5) {
            std::snprintf(buffer, size, "Used: %u.%umAh", (unsigned)(p.dischargedMahX10 / 10U), (unsigned)(p.dischargedMahX10 % 10U));
            return buffer;
        }
        if (index == 6) {
            std::snprintf(buffer, size, "Kapazitaet: %s", p.capacityReady ? "GELERNT" : "LERNT");
            return buffer;
        }
        if (index == 7) {
            std::snprintf(buffer, size, "Pos TX: %u", (unsigned)p.positionTxCount);
            return buffer;
        }
        std::snprintf(buffer, size, "INA: %s", p.inaValid ? "OK" : (p.inaConfigured ? "WAIT" : "OFF"));
        return buffer;
    }
    case MenuView::INA226:
        if (index == 0)
            return "ZURUECK";
        if (index == 1)
            return trackerIna226Enabled() ? "* EIN" : "  EIN";
        return !trackerIna226Enabled() ? "* AUS" : "  AUS";
    case MenuView::ANTENNA_TEST: {
        const TrackerAntennaState a = trackerAntennaState();
        if (index == 0)
            return "ZURUECK";
        if (index == 1) {
            std::snprintf(buffer, size, "Phase: %s", trackerAntennaPhaseText(a.phase));
            return buffer;
        }
        if (index == 2) {
            std::snprintf(buffer, size, "Samples: %u", (unsigned)a.liveSamples);
            return buffer;
        }
        if (index == 3) {
            std::snprintf(buffer, size, "A RSSI: %d", a.a.valid ? a.a.medianRssiDbm : 0);
            return buffer;
        }
        if (index == 4) {
            std::snprintf(buffer, size, "B RSSI: %d", a.b.valid ? a.b.medianRssiDbm : 0);
            return buffer;
        }
        if (index == 5) {
            std::snprintf(buffer, size, "Delta: %d dB", a.deltaRssiDb);
            return buffer;
        }
        if (index == 6) {
            std::snprintf(buffer, size, "TX Lock: %s", a.txLocked ? "JA" : "NEIN");
            return buffer;
        }
        if (index == 7) {
            std::snprintf(buffer, size, "Swap: %s", a.txSafeToSwap ? "SICHER" : "WARTEN");
            return buffer;
        }
        return "AKTION AUSFUEHREN";
    }
    case MenuView::NODES:
        if (index == 0)
            return "ZURUECK";
        if (meshtastic_NodeInfoLite *n = nodeAtOtherIndex(index - 1))
            return safeNodeName(n, buffer, size);
        return "NODE --";
    default:
        return "ZURUECK";
    }
}

void drawMenu(OLEDDisplay *display, int16_t x, int16_t y)
{
    drawHeader(display, x, y, menuTitle(menuView));
    const uint8_t count = std::max<uint8_t>(1, menuCount(menuView));
    if (trackerMenuSelection >= count)
        trackerMenuSelection = 0;

    char current[72] = {};
    char next[72] = {};
    const char *cur = menuLabel(menuView, trackerMenuSelection, current, sizeof(current));
    const char *nxt = menuLabel(menuView, (trackerMenuSelection + 1U) % count, next, sizeof(next));
    display->setTextAlignment(TEXT_ALIGN_CENTER);
    display->setFont(FONT_MEDIUM);
    char selected[80] = {};
    std::snprintf(selected, sizeof(selected), "> %s", cur);
    display->drawString(x + display->getWidth() / 2, y + 25, selected);
    display->setFont(FONT_SMALL);
    char nextLine[80] = {};
    std::snprintf(nextLine, sizeof(nextLine), "danach: %s", nxt);
    display->drawString(x + display->getWidth() / 2, y + 48, nextLine);
    display->drawString(x + display->getWidth() / 2, y + display->getHeight() - 12, "KURZ: WEITER   LANG: OK");
}

class TrackerStatusModule : public MeshModule
{
  public:
    TrackerStatusModule() : MeshModule("Jarnsen") {}
    bool wantPacket(const meshtastic_MeshPacket *) override { return false; }
    bool wantUIFrame() override { return trackerUiRoleEnabled(); }
    void requestTrackerFocus() { requestFocus(); }

    void drawFrame(OLEDDisplay *display, OLEDDisplayUiState *state, int16_t x, int16_t y) override
    {
        if (!display)
            return;
        if (state)
            trackerStatusFrameIndex =
                state->frameState == IN_TRANSITION && state->transitionFrameRelationship == TransitionRelationship_INCOMING
                    ? state->transitionFrameTarget
                    : state->currentFrame;

        if (trackerMenuMode) {
            drawMenu(display, x, y);
            return;
        }
        if (trackerNodeNavigationMode) {
            drawNodeNavigation(display, x, y);
            return;
        }

        switch (currentPage) {
        case jarnsen::DisplayPage::MGRS:
            drawMgrsPage(display, x, y);
            break;
        case jarnsen::DisplayPage::NODE_STATUS:
            drawOwnNodePage(display, x, y);
            break;
        case jarnsen::DisplayPage::SERVICE:
            drawServicePage(display, x, y);
            break;
        case jarnsen::DisplayPage::RADIO:
            drawRadioPage(display, x, y);
            break;
        case jarnsen::DisplayPage::NETWORK:
            drawNetworkPage(display, x, y);
            break;
        case jarnsen::DisplayPage::SYSTEM:
            drawSystemPage(display, x, y);
            break;
        default:
            drawMgrsPage(display, x, y);
            break;
        }
    }
};

TrackerStatusModule trackerStatusModule;

void focusTracker()
{
    trackerStatusModule.requestTrackerFocus();
    if (screen) {
        screen->setFrames(graphics::Screen::FOCUS_MODULE);
        screen->runNow();
    }
}

void openMenu(MenuView view, uint8_t selection = 0)
{
    trackerInteractionActive = true;
    trackerMenuMode = true;
    trackerStockUiMode = false;
    trackerNodeNavigationMode = false;
    menuView = view;
    trackerMenuSelection = selection;
    trackerMenuLastActivityMs = millis() ? millis() : 1;
    focusTracker();
}

void parentMenu(MenuView parent)
{
    menuView = parent;
    trackerMenuSelection = 0;
    trackerMenuLastActivityMs = millis() ? millis() : 1;
    if (screen)
        screen->runNow();
}

void enterStockMeshtastic()
{
    trackerMenuMode = false;
    trackerNodeNavigationMode = false;
    trackerStockUiMode = true;
    trackerInteractionActive = true;
    if (screen) {
        screen->showNextFrame();
        screen->runNow();
    }
}

void selectMenuItem()
{
    trackerMenuLastActivityMs = millis() ? millis() : 1;
    const uint8_t s = trackerMenuSelection;
    switch (menuView) {
    case MenuView::MAIN:
        if (s == 0)
            parentMenu(MenuView::NODES);
        else if (s == 1)
            parentMenu(MenuView::PROFILE);
        else if (s == 2)
            parentMenu(MenuView::TRACKER);
        else if (s == 3)
            parentMenu(MenuView::SERVICE);
        else if (s == 4)
            parentMenu(MenuView::SYSTEM);
        else
            trackerServiceMenuClose();
        break;
    case MenuView::PROFILE:
        if (s == 3)
            parentMenu(MenuView::MAIN);
        // No profile setter exists in the current firmware. Keep the three
        // operator-visible names without silently changing unrelated LoRa fields.
        break;
    case MenuView::TRACKER:
        if (s == 0)
            parentMenu(MenuView::POSITION);
        else if (s == 1)
            parentMenu(MenuView::MOTION);
        else if (s == 2)
            parentMenu(MenuView::PARKING);
        else
            parentMenu(MenuView::MAIN);
        break;
    case MenuView::POSITION:
        if (s == 0)
            parentMenu(MenuView::SMART_DISTANCE);
        else if (s == 1)
            parentMenu(MenuView::MIN_TX_INTERVAL);
        else if (s == 2)
            parentMenu(MenuView::MOVING_GNSS);
        else
            parentMenu(MenuView::TRACKER);
        break;
    case MenuView::SMART_DISTANCE:
        if (s == 0)
            parentMenu(MenuView::POSITION);
        else {
            const uint16_t vals[] = {50, 75, 100, 150};
            trackerSetSmartDistanceM(vals[s - 1]);
            parentMenu(MenuView::POSITION);
        }
        break;
    case MenuView::MIN_TX_INTERVAL:
        if (s == 0)
            parentMenu(MenuView::POSITION);
        else {
            const uint16_t vals[] = {30, 45, 60, 90};
            trackerSetSmartIntervalSecs(vals[s - 1]);
            parentMenu(MenuView::POSITION);
        }
        break;
    case MenuView::MOVING_GNSS:
        if (s == 0)
            parentMenu(MenuView::POSITION);
        else {
            const uint16_t vals[] = {5, 10, 15, 30};
            trackerSetMovingGnssSecs(vals[s - 1]);
            parentMenu(MenuView::POSITION);
        }
        break;
    case MenuView::MOTION:
        if (s == 0)
            parentMenu(MenuView::MOTION_STATUS);
        else if (s == 1)
            parentMenu(MenuView::WAKE_SENSOR);
        else if (s == 2)
            parentMenu(MenuView::MOTION_SENSITIVITY);
        else
            parentMenu(MenuView::TRACKER);
        break;
    case MenuView::MOTION_STATUS:
        if (s == 0)
            parentMenu(MenuView::MOTION);
        break;
    case MenuView::WAKE_SENSOR:
        if (s == 0)
            parentMenu(MenuView::MOTION);
        else if (s == 2)
            parentMenu(MenuView::MOTION_SENSITIVITY);
        break;
    case MenuView::MOTION_SENSITIVITY:
        if (s == 0)
            parentMenu(MenuView::MOTION);
        else {
            trackerSetMotionSensitivityIndex(s - 1);
            parentMenu(MenuView::MOTION);
        }
        break;
    case MenuView::PARKING:
        if (s == 0)
            parentMenu(MenuView::PARK_INTERVAL);
        else if (s == 1)
            parentMenu(MenuView::GPS_SEARCH_TIME);
        else
            parentMenu(MenuView::TRACKER);
        break;
    case MenuView::PARK_INTERVAL:
        if (s == 0)
            parentMenu(MenuView::PARKING);
        else {
            const uint16_t vals[] = {20, 30, 60, 120, 240, 360, 540, 720};
            trackerSetParkIntervalMinutes(vals[s - 1]);
            parentMenu(MenuView::PARKING);
        }
        break;
    case MenuView::GPS_SEARCH_TIME:
        if (s == 0)
            parentMenu(MenuView::PARKING);
        else {
            const uint16_t vals[] = {15, 30, 45, 60};
            trackerSetParkGpsSearchSecs(vals[s - 1]);
            parentMenu(MenuView::PARKING);
        }
        break;
    case MenuView::SERVICE:
        if (s == 0)
            parentMenu(MenuView::BLUETOOTH);
        else if (s == 1)
            parentMenu(MenuView::WLAN);
        else if (s == 2)
            parentMenu(MenuView::DIAG_LOG);
        else
            parentMenu(MenuView::MAIN);
        break;
    case MenuView::BLUETOOTH:
        if (s == 0)
            parentMenu(MenuView::BLE_IDLE);
        else if (s == 1)
            parentMenu(MenuView::BLE_HARD);
        else
            parentMenu(MenuView::SERVICE);
        break;
    case MenuView::BLE_IDLE:
        if (s == 0)
            parentMenu(MenuView::BLUETOOTH);
        else {
            const uint16_t vals[] = {60, 120, 180, 300};
            trackerSetBleIdleTimeoutSecs(vals[s - 1]);
            parentMenu(MenuView::BLUETOOTH);
        }
        break;
    case MenuView::BLE_HARD:
        if (s == 0)
            parentMenu(MenuView::BLUETOOTH);
        else {
            const uint16_t vals[] = {300, 600, 900, 1800};
            trackerSetBleHardTimeoutSecs(vals[s - 1]);
            parentMenu(MenuView::BLUETOOTH);
        }
        break;
    case MenuView::WLAN:
        if (s == 0)
            parentMenu(MenuView::SERVICE);
        else if (s == 1) {
            if (jarnsenServiceWebActive())
                jarnsenServiceWebStop();
            else
                jarnsenServiceWebStart();
            if (screen)
                screen->runNow();
        }
        break;
    case MenuView::DIAG_LOG:
        if (s == 0)
            parentMenu(MenuView::LOG_STATUS);
        else if (s == 1)
            parentMenu(MenuView::LOGGING);
        else if (s == 2)
            parentMenu(MenuView::LOG_EXPORT);
        else if (s == 3)
            parentMenu(MenuView::LOG_CLEAR);
        else
            parentMenu(MenuView::SERVICE);
        break;
    case MenuView::LOGGING:
        if (s == 0)
            parentMenu(MenuView::DIAG_LOG);
        else {
            trackerDiagSetEnabled(s == 1);
            parentMenu(MenuView::DIAG_LOG);
        }
        break;
    case MenuView::LOG_STATUS:
        if (s == 0)
            parentMenu(MenuView::DIAG_LOG);
        break;
    case MenuView::LOG_EXPORT:
        if (s == 0)
            parentMenu(MenuView::DIAG_LOG);
        else {
            trackerPowerMonitorPersist();
            trackerDiagRequestUsbExport();
            if (screen)
                screen->runNow();
        }
        break;
    case MenuView::LOG_CLEAR:
        if (s == 0)
            parentMenu(MenuView::DIAG_LOG);
        else {
            trackerDiagClear();
            parentMenu(MenuView::DIAG_LOG);
        }
        break;
    case MenuView::SYSTEM:
        if (s == 0)
            parentMenu(MenuView::SYSTEM_INFO);
        else if (s == 1)
            parentMenu(MenuView::DIAGNOSTICS);
        else if (s == 2)
            parentMenu(MenuView::POWER);
        else if (s == 3)
            parentMenu(MenuView::ANTENNA_TEST);
        else if (s == 4)
            enterStockMeshtastic();
        else
            parentMenu(MenuView::MAIN);
        break;
    case MenuView::SYSTEM_INFO:
    case MenuView::DIAGNOSTICS:
        if (s == 0)
            parentMenu(MenuView::SYSTEM);
        break;
    case MenuView::POWER:
        if (s == 0)
            parentMenu(MenuView::POWER_STATS);
        else if (s == 1)
            parentMenu(MenuView::INA226);
        else
            parentMenu(MenuView::SYSTEM);
        break;
    case MenuView::POWER_STATS:
        if (s == 0)
            parentMenu(MenuView::POWER);
        break;
    case MenuView::INA226:
        if (s == 0)
            parentMenu(MenuView::POWER);
        else {
            trackerSetIna226Enabled(s == 1);
            parentMenu(MenuView::POWER);
        }
        break;
    case MenuView::ANTENNA_TEST:
        if (s == 0)
            parentMenu(MenuView::SYSTEM);
        else if (s == 8) {
            trackerAntennaHandleAction();
            if (screen)
                screen->runNow();
        }
        break;
    case MenuView::NODES:
        if (s == 0) {
            parentMenu(MenuView::MAIN);
        } else if (meshtastic_NodeInfoLite *n = nodeAtOtherIndex(s - 1)) {
            selectedNodeNum = n->num;
            selectedNodeIndex = s - 1;
            trackerMenuMode = false;
            trackerNodeNavigationMode = true;
            trackerStockUiMode = false;
            focusTracker();
        }
        break;
    default:
        parentMenu(MenuView::MAIN);
        break;
    }
}

void selectNextNavigationNode()
{
    const size_t count = otherNodeCount();
    if (!count)
        return;
    selectedNodeIndex = (selectedNodeIndex + 1U) % count;
    if (meshtastic_NodeInfoLite *n = nodeAtOtherIndex(selectedNodeIndex))
        selectedNodeNum = n->num;
    if (screen)
        screen->runNow();
}
} // namespace

bool trackerServiceMenuActive()
{
    // The Tracker owns its one physical button for the whole service/display
    // session. `trackerMenuMode` only says whether the menu itself is visible.
    return trackerInteractionActive;
}

bool trackerServicePageVisible()
{
    return screen && trackerStatusFrameIndex != 255 && screen->currentFrameIndex() == trackerStatusFrameIndex;
}

const char *trackerStatusCurrentPageText()
{
    if (!trackerInteractionActive)
        return "off";
    if (trackerMenuMode)
        return "menu";
    if (trackerNodeNavigationMode)
        return "nodes";
    if (trackerStockUiMode)
        return "meshtastic";
    return jarnsen::displayPageName(currentPage);
}

void trackerServiceMenuOpen()
{
    if (!trackerUiRoleEnabled())
        return;
    openMenu(MenuView::MAIN, 0);
}

void trackerServiceMenuShortPress()
{
    if (!trackerInteractionActive || !screen)
        return;
    trackerMenuLastActivityMs = millis() ? millis() : 1;
    if (trackerMenuMode) {
        const uint8_t count = std::max<uint8_t>(1, menuCount(menuView));
        trackerMenuSelection = (trackerMenuSelection + 1U) % count;
        screen->runNow();
        return;
    }
    if (trackerStockUiMode) {
        screen->showNextFrame();
        screen->runNow();
        return;
    }
    if (trackerNodeNavigationMode) {
        selectNextNavigationNode();
        return;
    }
    currentPage = jarnsen::nextDisplayPage(currentPage);
    focusTracker();
}

void trackerServiceMenuSelect()
{
    if (!trackerInteractionActive) {
        trackerServiceMenuOpen();
        return;
    }
    if (trackerStockUiMode) {
        openMenu(MenuView::MAIN, 0);
        return;
    }
    if (trackerNodeNavigationMode) {
        openMenu(MenuView::NODES, static_cast<uint8_t>(selectedNodeIndex + 1U));
        return;
    }
    if (!trackerMenuMode) {
        openMenu(MenuView::MAIN, 0);
        return;
    }
    selectMenuItem();
}

void trackerServiceMenuPump()
{
    if (!trackerInteractionActive)
        return;
    if (trackerMenuMode && trackerMenuLastActivityMs != 0 &&
        (uint32_t)(millis() - trackerMenuLastActivityMs) >= MENU_TIMEOUT_MS) {
        trackerServiceMenuClose();
        return;
    }
    if (trackerMenuMode && (menuView == MenuView::LOG_EXPORT || menuView == MenuView::ANTENNA_TEST) && screen)
        screen->runNow();
}

void trackerServiceMenuClose()
{
    trackerMenuMode = false;
    trackerStockUiMode = false;
    trackerNodeNavigationMode = false;
    menuView = MenuView::MAIN;
    trackerMenuSelection = 0;
    currentPage = jarnsen::DisplayPage::MGRS;
    trackerInteractionActive = true;
    focusTracker();
}

void trackerServiceMenuForceClose()
{
    trackerMenuMode = false;
    trackerStockUiMode = false;
    trackerNodeNavigationMode = false;
    menuView = MenuView::MAIN;
    trackerMenuSelection = 0;
    selectedNodeNum = 0;
    trackerInteractionActive = false;
}

void trackerStatusRequestFocus()
{
    if (!trackerUiRoleEnabled())
        return;
    trackerInteractionActive = true;
    trackerMenuMode = false;
    trackerStockUiMode = false;
    trackerNodeNavigationMode = false;
    currentPage = jarnsen::DisplayPage::MGRS;
    focusTracker();
}

void trackerStatusSetMotionActive(bool active)
{
    trackerMotionActive = active;
    if (screen && screen->isScreenOn())
        screen->runNow();
}

#else

void trackerStatusRequestFocus() {}
void trackerStatusSetMotionActive(bool) {}
bool trackerServiceMenuActive()
{
    return false;
}
bool trackerServicePageVisible()
{
    return false;
}
const char *trackerStatusCurrentPageText()
{
    return "off";
}
void trackerServiceMenuOpen() {}
void trackerServiceMenuShortPress() {}
void trackerServiceMenuSelect() {}
void trackerServiceMenuPump() {}
void trackerServiceMenuClose() {}
void trackerServiceMenuForceClose() {}

#endif
