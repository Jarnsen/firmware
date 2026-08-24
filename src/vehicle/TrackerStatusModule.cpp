#include "configuration.h"

#if defined(HELTEC_TRACKER_V1_1) && HAS_SCREEN

#include "GPSStatus.h"
#include "NodeDB.h"
#include "PowerStatus.h"
#include "gps/RTC.h"
#include "graphics/Screen.h"
#include "graphics/ScreenFonts.h"
#include "graphics/SharedUIDisplay.h"
#include "graphics/draw/NotificationRenderer.h"
#include "graphics/draw/UIRenderer.h"
#include "graphics/TFTColorRegions.h"
#include "graphics/TFTPalette.h"
#include "mesh/MeshModule.h"
#include "vehicle/JarnsenBuildInfo.h"
#include "vehicle/TrackerEnhancements.h"
#include "vehicle/TrackerDiagnosticLog.h"
#include "vehicle/TrackerPowerMonitor.h"
#include "vehicle/TrackerAntennaTest.h"
#include "vehicle/TrackerServiceSettings.h"
#include "vehicle/TrackerStatusModule.h"
#include "vehicle/TrackerCommonPolicy.h"

#include <algorithm>
#include <cmath>
#include <cstdio>
#include <cstring>

namespace
{
volatile bool trackerMotionActive = false;

enum class TrackerMenu : uint8_t {
    NONE = 0,
    ROOT,
    POSITION,
    DISTANCE,
    INTERVAL,
    MOVING_GNSS,
    MOTION,
    MOTION_SENS,
    PARK_POWER,
    PARK_INTERVAL,
    PARK_GPS_SEARCH,
    BLUETOOTH,
    BLE_IDLE,
    BLE_HARD,
    DIAG_LOG,
    LOGGING,
    LOG_STATUS,
    LOG_EXPORT_CONFIRM,
    LOG_EXPORT,
    LOG_CLEAR,
    LOG_CLEARED,
    SYSTEM,
    SYSTEM_INFO,
    DIAGNOSTICS,
    POWER_STATS,
    INA226_HW,
    ANTENNA_TEST,
};

bool trackerServiceMenuMode = false;
TrackerMenu trackerMenuCurrent = TrackerMenu::NONE;
TrackerMenu trackerMenuPending = TrackerMenu::NONE;
int8_t trackerMenuPendingSelection = 0;
int8_t trackerRootSelection = 0;
int8_t trackerPositionSelection = 0;
int8_t trackerMotionSelection = 0;
int8_t trackerParkSelection = 0;
int8_t trackerBluetoothSelection = 0;
int8_t trackerDiagSelection = 0;
volatile uint8_t trackerServiceFrameIndex = 255;
char trackerLogExportStatus[48] = "Status: Bereit";
char trackerLogExportProgress[40] = "Log: 0 KB";
uint32_t trackerLogExportLastRefreshMs = 0;

bool trackerUiRoleEnabled()
{
    return config.device.role == meshtastic_Config_DeviceConfig_Role_TAK ||
           config.device.role == meshtastic_Config_DeviceConfig_Role_TAK_TRACKER;
}

char latitudeBand(double latitude)
{
    static constexpr char bands[] = "CDEFGHJKLMNPQRSTUVWX";
    if (latitude < -80.0 || latitude > 84.0)
        return 0;
    int index = static_cast<int>(floor((latitude + 80.0) / 8.0));
    if (index < 0)
        index = 0;
    if (index > 19)
        index = 19;
    return bands[index];
}

int utmZone(double latitude, double longitude)
{
    int zone = static_cast<int>(floor((longitude + 180.0) / 6.0)) + 1;
    if (zone < 1)
        zone = 1;
    if (zone > 60)
        zone = 60;

    // Standard UTM Norway/Svalbard exceptions.
    if (latitude >= 56.0 && latitude < 64.0 && longitude >= 3.0 && longitude < 12.0)
        zone = 32;
    if (latitude >= 72.0 && latitude < 84.0) {
        if (longitude >= 0.0 && longitude < 9.0)
            zone = 31;
        else if (longitude < 21.0)
            zone = 33;
        else if (longitude < 33.0)
            zone = 35;
        else if (longitude < 42.0)
            zone = 37;
    }
    return zone;
}

bool latLonToMgrs(int32_t latitudeI, int32_t longitudeI, char *out, size_t outSize)
{
    if (!out || outSize < 24 || (latitudeI == 0 && longitudeI == 0))
        return false;

    const double latitude = latitudeI * 1e-7;
    const double longitude = longitudeI * 1e-7;
    const char band = latitudeBand(latitude);
    if (!band)
        return false; // MGRS/UTM coverage is 80 S to 84 N.

    constexpr double a = 6378137.0;
    constexpr double eccSquared = 0.00669438;
    constexpr double k0 = 0.9996;
    constexpr double degToRad = 0.017453292519943295769;

    const int zone = utmZone(latitude, longitude);
    const double lonOrigin = (zone - 1) * 6.0 - 180.0 + 3.0;
    const double latRad = latitude * degToRad;
    const double lonRad = longitude * degToRad;
    const double lonOriginRad = lonOrigin * degToRad;

    const double eccPrimeSquared = eccSquared / (1.0 - eccSquared);
    const double sinLat = sin(latRad);
    const double cosLat = cos(latRad);
    const double tanLat = tan(latRad);
    const double n = a / sqrt(1.0 - eccSquared * sinLat * sinLat);
    const double t = tanLat * tanLat;
    const double c = eccPrimeSquared * cosLat * cosLat;
    const double aa = cosLat * (lonRad - lonOriginRad);

    const double m = a * ((1.0 - eccSquared / 4.0 - 3.0 * eccSquared * eccSquared / 64.0 -
                           5.0 * eccSquared * eccSquared * eccSquared / 256.0) *
                              latRad -
                          (3.0 * eccSquared / 8.0 + 3.0 * eccSquared * eccSquared / 32.0 +
                           45.0 * eccSquared * eccSquared * eccSquared / 1024.0) *
                              sin(2.0 * latRad) +
                          (15.0 * eccSquared * eccSquared / 256.0 +
                           45.0 * eccSquared * eccSquared * eccSquared / 1024.0) *
                              sin(4.0 * latRad) -
                          (35.0 * eccSquared * eccSquared * eccSquared / 3072.0) * sin(6.0 * latRad));

    double easting = k0 * n *
                         (aa + (1.0 - t + c) * aa * aa * aa / 6.0 +
                          (5.0 - 18.0 * t + t * t + 72.0 * c - 58.0 * eccPrimeSquared) *
                              aa * aa * aa * aa * aa / 120.0) +
                     500000.0;

    double northing =
        k0 * (m + n * tanLat *
                      (aa * aa / 2.0 + (5.0 - t + 9.0 * c + 4.0 * c * c) * aa * aa * aa * aa / 24.0 +
                       (61.0 - 58.0 * t + t * t + 600.0 * c - 330.0 * eccPrimeSquared) *
                           aa * aa * aa * aa * aa * aa / 720.0));
    if (latitude < 0.0)
        northing += 10000000.0;

    static constexpr const char *eastingSets[] = {"ABCDEFGH", "JKLMNPQR", "STUVWXYZ"};
    static constexpr char northingLetters[] = "ABCDEFGHJKLMNPQRSTUV";

    int e100k = static_cast<int>(floor(easting / 100000.0));
    if (e100k < 1 || e100k > 8)
        return false;
    const char eLetter = eastingSets[(zone - 1) % 3][e100k - 1];

    int n100k = static_cast<int>(floor(northing / 100000.0)) % 20;
    const int northOffset = (zone % 2 == 0) ? 5 : 0;
    const char nLetter = northingLetters[(n100k + northOffset) % 20];

    int eMeters = static_cast<int>(floor(easting + 0.5)) % 100000;
    int nMeters = static_cast<int>(floor(northing + 0.5)) % 100000;
    if (eMeters < 0)
        eMeters += 100000;
    if (nMeters < 0)
        nMeters += 100000;

    snprintf(out, outSize, "%02d%c %c%c %05d %05d", zone, band, eLetter, nLetter, eMeters, nMeters);
    return true;
}

bool readLastOwnPosition(meshtastic_PositionLite &position)
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

void formatAge(uint32_t ageSecs, char *out, size_t outSize)
{
    if (ageSecs == UINT32_MAX) {
        snprintf(out, outSize, "Alter unbekannt");
    } else if (ageSecs < 60U) {
        snprintf(out, outSize, "vor %us", (unsigned)ageSecs);
    } else if (ageSecs < 3600U) {
        snprintf(out, outSize, "vor %umin", (unsigned)(ageSecs / 60U));
    } else if (ageSecs < 86400U) {
        const unsigned hours = ageSecs / 3600U;
        const unsigned mins = (ageSecs % 3600U) / 60U;
        snprintf(out, outSize, "vor %uh %02umin", hours, mins);
    } else {
        snprintf(out, outSize, "vor %ut", (unsigned)(ageSecs / 86400U));
    }
}

uint16_t ageColor(uint32_t ageSecs, bool havePosition)
{
    if (!havePosition || ageSecs == UINT32_MAX || ageSecs > 300U)
        return graphics::TFTPalette::Red;
    if (ageSecs > 60U)
        return graphics::TFTPalette::Yellow;
    return graphics::getThemeBodyFg();
}

unsigned estimatedAccuracyMeters()
{
    if (!gpsStatus || gpsStatus->getDOP() == 0)
        return 0;

    // Meshtastic Position stores DOP in 1/100 units and documents ~3 m as
    // the default hardware GPS accuracy constant. PDOP is used as a conservative
    // fallback because GPSStatus currently exposes PDOP but not HDOP/gps_accuracy.
    const double meters = (gpsStatus->getDOP() / 100.0) * 3.0;
    return std::max(1U, static_cast<unsigned>(ceil(meters)));
}

class TrackerStatusModule : public MeshModule
{
  public:
    TrackerStatusModule() : MeshModule("Tracker") {}

    bool wantPacket(const meshtastic_MeshPacket *) override { return false; }
    bool wantUIFrame() override { return trackerUiRoleEnabled(); }
    void requestTrackerFocus() { requestFocus(); }

    void drawFrame(OLEDDisplay *display, OLEDDisplayUiState *, int16_t x, int16_t y) override
    {
        if (!display)
            return;

        meshtastic_PositionLite position = meshtastic_PositionLite_init_default;
        const bool havePosition = readLastOwnPosition(position);
        const uint32_t age = havePosition ? positionAgeSecs(position) : UINT32_MAX;
        const uint16_t color = ageColor(age, havePosition);
        const uint16_t bg = graphics::getThemeBodyBg();

        display->setTextAlignment(TEXT_ALIGN_CENTER);
        const int center = display->getWidth() / 2 + x;

        if (!havePosition) {
            display->setFont(FONT_MEDIUM);
            display->drawString(center, 22 + y, "KEINE POSITION");
            display->setFont(FONT_SMALL);
            display->drawString(center, 45 + y, gpsStatus && gpsStatus->getIsConnected() ? "GPS sucht..." : "GPS nicht bereit");
#if GRAPHICS_TFT_COLORING_ENABLED
            graphics::registerTFTColorRegionDirect(x, 18 + y, display->getWidth(), 42, graphics::TFTPalette::Red, bg);
#endif
            return;
        }

        char mgrs[32] = {};
        if (!latLonToMgrs(position.latitude_i, position.longitude_i, mgrs, sizeof(mgrs))) {
            display->setFont(FONT_MEDIUM);
            display->drawString(center, 22 + y, "MGRS NICHT VERFUEGBAR");
            display->setFont(FONT_SMALL);
            display->drawString(center, 45 + y, "Position ausser UTM-Bereich");
#if GRAPHICS_TFT_COLORING_ENABLED
            graphics::registerTFTColorRegionDirect(x, 18 + y, display->getWidth(), 42, graphics::TFTPalette::Red, bg);
#endif
            return;
        }

        // Split after the 100 km grid designator so the 1 m MGRS digits can be
        // substantially larger without colliding with Meshtastic's normal header.
        char zoneGrid[12] = {};
        char digits[16] = {};
        const char *secondSpace = strchr(mgrs, ' ');
        const char *thirdSpace = secondSpace ? strchr(secondSpace + 1, ' ') : nullptr;
        if (thirdSpace) {
            const size_t prefixLen = std::min(sizeof(zoneGrid) - 1, static_cast<size_t>(thirdSpace - mgrs));
            memcpy(zoneGrid, mgrs, prefixLen);
            zoneGrid[prefixLen] = '\0';
            snprintf(digits, sizeof(digits), "%s", thirdSpace + 1);
        } else {
            snprintf(zoneGrid, sizeof(zoneGrid), "%s", mgrs);
        }

        display->setFont(FONT_SMALL);
        display->drawString(center, 13 + y, zoneGrid);
        display->setFont(FONT_LARGE);
        display->drawString(center, 27 + y, digits);

        char ageText[32] = {};
        formatAge(age, ageText, sizeof(ageText));
        const unsigned accuracy = estimatedAccuracyMeters();
        char info[56] = {};
        if (accuracy)
            snprintf(info, sizeof(info), "~+/- %um  |  %s", accuracy, ageText);
        else
            snprintf(info, sizeof(info), "%s", ageText);
        display->setFont(FONT_SMALL);
        display->drawString(center, 52 + y, info);

        const bool gpsLock = gpsStatus && gpsStatus->getHasLock();
        char status[48] = {};
        snprintf(status, sizeof(status), "%s | %s", gpsLock ? "GPS FIX" : "LETZTE POSITION",
                 trackerMotionActive ? "MOTION" : "PARKED");
        display->drawString(center, 65 + y, status);

#if GRAPHICS_TFT_COLORING_ENABLED
        graphics::registerTFTColorRegionDirect(x, 10 + y, display->getWidth(), 52, color, bg);
#endif
    }
};

TrackerStatusModule trackerStatusModule;

class TrackerServiceModule : public MeshModule
{
  public:
    TrackerServiceModule() : MeshModule("Service") {}

    bool wantPacket(const meshtastic_MeshPacket *) override { return false; }
    bool wantUIFrame() override { return trackerUiRoleEnabled(); }
    void requestServiceFocus() { requestFocus(); }

    void drawFrame(OLEDDisplay *display, OLEDDisplayUiState *state, int16_t x, int16_t y) override
    {
        if (!display)
            return;

        if (state) {
            if (state->frameState == IN_TRANSITION &&
                state->transitionFrameRelationship == TransitionRelationship_INCOMING)
                trackerServiceFrameIndex = state->transitionFrameTarget;
            else
                trackerServiceFrameIndex = state->currentFrame;
        }

        // FOCUS_MODULE does not receive the normal stock frame chrome, so draw
        // the same shared Meshtastic header and navigation overlay explicitly.
        // This page still has no wake behavior of its own: it is only rendered
        // while TrackerCommon already has the display on after a GPIO0 press.
        display->clear();
        graphics::drawCommonHeader(display, x, y, "Service");

        display->setColor(WHITE);
        display->setFont(FONT_SMALL);
        const int *textPos = graphics::getTextPositions(display);
        const int left = x + 2;
        const int right = x + display->getWidth() - 2;
        char line[72] = {};

        // Row 1: role and live Tracker state, matching the compact two-column
        // layout used by stock Meshtastic status pages.
        const char *role = config.device.role == meshtastic_Config_DeviceConfig_Role_TAK_TRACKER ? "TAK-TRK" : "TAK";
        display->setTextAlignment(TEXT_ALIGN_LEFT);
        display->drawString(left, textPos[1], role);
        display->setTextAlignment(TEXT_ALIGN_RIGHT);
        display->drawString(right, textPos[1], trackerCommonRuntimeState());

        // Determine current GNSS state without waking GNSS just for the screen.
        const char *gpsState = "WAIT";
        if (trackerCommonParkGpsSearchPending())
            gpsState = "SEARCH";
        else if (trackerCommonIsParked() && config.device.role == meshtastic_Config_DeviceConfig_Role_TAK)
            gpsState = "SLEEP";
        else if (gpsStatus && gpsStatus->getHasLock())
            gpsState = "FIX";

        // Row 2: motion preset + GNSS state.
        display->setTextAlignment(TEXT_ALIGN_LEFT);
        snprintf(line, sizeof(line), "Motion:%s", trackerMotionSensitivityName());
        display->drawString(left, textPos[2], line);
        display->setTextAlignment(TEXT_ALIGN_RIGHT);
        snprintf(line, sizeof(line), "GPS:%s", gpsState);
        display->drawString(right, textPos[2], line);

        // Row 3: Smart Position + parked heartbeat interval.
        display->setTextAlignment(TEXT_ALIGN_LEFT);
        snprintf(line, sizeof(line), "Smart:%um/%us", (unsigned)trackerSmartDistanceM(),
                 (unsigned)trackerSmartIntervalSecs());
        display->drawString(left, textPos[3], line);
        char park[20] = {};
        trackerFormatParkInterval(park, sizeof(park));
        display->setTextAlignment(TEXT_ALIGN_RIGHT);
        snprintf(line, sizeof(line), "Park:%s", park);
        display->drawString(right, textPos[3], line);

        // Row 4: next parked TX (when meaningful), Bluetooth and diagnostic log.
        const uint32_t nextTx = trackerCommonParkNextTxSecs();
        char next[24] = {};
        if (nextTx == UINT32_MAX) {
            next[0] = '\0';
        } else if (nextTx == 0) {
            snprintf(next, sizeof(next), "Next:NOW ");
        } else if (nextTx < 60U) {
            snprintf(next, sizeof(next), "Next:%us ", (unsigned)nextTx);
        } else if (nextTx < 3600U) {
            snprintf(next, sizeof(next), "Next:%um ", (unsigned)((nextTx + 59U) / 60U));
        } else {
            const uint32_t hours = nextTx / 3600U;
            const uint32_t mins = (nextTx % 3600U) / 60U;
            snprintf(next, sizeof(next), "Next:%uh%02um ", (unsigned)hours, (unsigned)mins);
        }

        display->setTextAlignment(TEXT_ALIGN_LEFT);
        if (trackerAntennaTxLocked())
            snprintf(line, sizeof(line), "%sTX:LOCK  Log:%s", next, trackerDiagEnabled() ? "ON" : "OFF");
        else
            snprintf(line, sizeof(line), "%sBT:%s  Log:%s", next,
                     config.bluetooth.enabled ? "ON" : "OFF", trackerDiagEnabled() ? "ON" : "OFF");
        display->drawString(left, textPos[4], line);

        // Same stock footer/link indicator and temporary navigation-icon bar as
        // the user's original Messages/Hops/Position pages.
        graphics::drawCommonFooter(display, x, y);
        if (state)
            graphics::UIRenderer::drawNavigationBar(display, state);
    }
};

TrackerServiceModule trackerServiceModule;

void queueTrackerMenu(TrackerMenu menu, int selection)
{
    trackerMenuPending = menu;
    trackerMenuPendingSelection = selection < 0 ? 0 : (int8_t)selection;
}

void showTrackerOptions(const char *title, const char **options, uint8_t count, int selected,
                        std::function<void(int)> callback)
{
    if (!screen)
        return;
    graphics::BannerOverlayOptions banner;
    banner.message = title;
    banner.optionsArrayPtr = options;
    banner.optionsCount = count;
    banner.bannerCallback = callback;
    banner.InitialSelected = selected;
    banner.durationMs = 0; // Tracker's own 20s display timer owns visibility.
    banner.notificationType = graphics::notificationTypeEnum::selection_picker;
    screen->showOverlayBanner(banner);
}

int distanceSelection()
{
    switch (trackerSmartDistanceM()) {
    case 50: return 1;
    case 75: return 2;
    case 100: return 3;
    case 150: return 4;
    default: return 1;
    }
}

int intervalSelection()
{
    switch (trackerSmartIntervalSecs()) {
    case 30: return 1;
    case 45: return 2;
    case 60: return 3;
    case 90: return 4;
    default: return 1;
    }
}

int parkIntervalSelection()
{
    switch (trackerParkIntervalMinutes()) {
    case 20: return 1;
    case 30: return 2;
    case 60: return 3;
    case 120: return 4;
    case 240: return 5;
    case 360: return 6;
    case 540: return 7;
    case 720: return 8;
    default: return 3;
    }
}

void markOption(char *out, size_t outSize, bool selected, const char *label)
{
    snprintf(out, outSize, "[%c] %s", selected ? 'x' : ' ', label);
}

void refreshTrackerLogExportText()
{
    snprintf(trackerLogExportStatus, sizeof(trackerLogExportStatus), "Status: %s", trackerDiagUsbExportStatusText());
    const uint8_t progress = trackerDiagUsbExportProgress();
    if (trackerDiagUsbExportPending() || progress > 0)
        snprintf(trackerLogExportProgress, sizeof(trackerLogExportProgress), "Fortschritt: %u%%", (unsigned)progress);
    else
        snprintf(trackerLogExportProgress, sizeof(trackerLogExportProgress), "Log: %u KB",
                 (unsigned)((trackerDiagLogSize() + 1023U) / 1024U));
}

int movingGnssSelection()
{
    switch (trackerMovingGnssSecs()) {
    case 5: return 1;
    case 10: return 2;
    case 15: return 3;
    case 30: return 4;
    default: return 2;
    }
}

int parkGpsSearchSelection()
{
    switch (trackerParkGpsSearchSecs()) {
    case 15: return 1;
    case 30: return 2;
    case 45: return 3;
    case 60: return 4;
    default: return 2;
    }
}

int bleIdleSelection()
{
    switch (trackerBleIdleTimeoutSecs()) {
    case 60: return 1;
    case 120: return 2;
    case 180: return 3;
    case 300: return 4;
    default: return 2;
    }
}

int bleHardSelection()
{
    switch (trackerBleHardTimeoutSecs()) {
    case 300: return 1;
    case 600: return 2;
    case 900: return 3;
    case 1800: return 4;
    default: return 3;
    }
}

void showTrackerMenu(TrackerMenu menu, int initialSelection)
{
    trackerMenuCurrent = menu;
    trackerMenuPending = TrackerMenu::NONE;

    switch (menu) {
    case TrackerMenu::ROOT: {
        static const char *opts[] = {"Back", "Position", "Motion", "Parking", "Bluetooth", "Diagnostic Log", "System"};
        showTrackerOptions("Service Settings", opts, 7, initialSelection, [](int selected) {
            trackerRootSelection = selected;
            switch (selected) {
            case 0:
                trackerServiceMenuMode = false;
                trackerMenuCurrent = TrackerMenu::NONE;
                trackerServiceModule.requestServiceFocus();
                if (screen) { screen->setFrames(graphics::Screen::FOCUS_MODULE); screen->runNow(); }
                break;
            case 1: queueTrackerMenu(TrackerMenu::POSITION, 0); break;
            case 2: queueTrackerMenu(TrackerMenu::MOTION, 0); break;
            case 3: queueTrackerMenu(TrackerMenu::PARK_POWER, 0); break;
            case 4: queueTrackerMenu(TrackerMenu::BLUETOOTH, 0); break;
            case 5: queueTrackerMenu(TrackerMenu::DIAG_LOG, 0); break;
            case 6: queueTrackerMenu(TrackerMenu::SYSTEM, 0); break;
            }
        });
        break;
    }

    case TrackerMenu::POSITION: {
        static const char *opts[] = {"Back", "Smart Distance", "Min TX Interval", "Moving GNSS"};
        showTrackerOptions("Position", opts, 4, initialSelection, [](int selected) {
            trackerPositionSelection = selected;
            if (selected == 0) queueTrackerMenu(TrackerMenu::ROOT, trackerRootSelection);
            else if (selected == 1) queueTrackerMenu(TrackerMenu::DISTANCE, 0);
            else if (selected == 2) queueTrackerMenu(TrackerMenu::INTERVAL, 0);
            else if (selected == 3) queueTrackerMenu(TrackerMenu::MOVING_GNSS, 0);
        });
        break;
    }

    case TrackerMenu::DISTANCE: {
        static char labels[5][24];
        static const char *opts[5] = {labels[0], labels[1], labels[2], labels[3], labels[4]};
        snprintf(labels[0], sizeof(labels[0]), "Back");
        const uint16_t vals[] = {50, 75, 100, 150};
        for (int i = 0; i < 4; ++i) {
            char raw[12]; snprintf(raw, sizeof(raw), "%u m", (unsigned)vals[i]);
            markOption(labels[i + 1], sizeof(labels[i + 1]), trackerSmartDistanceM() == vals[i], raw);
        }
        showTrackerOptions("Smart Distance", opts, 5, initialSelection, [](int selected) {
            if (selected == 0) queueTrackerMenu(TrackerMenu::POSITION, trackerPositionSelection);
            else { const uint16_t vals[] = {50, 75, 100, 150}; trackerSetSmartDistanceM(vals[selected - 1]); queueTrackerMenu(TrackerMenu::DISTANCE, 0); }
        });
        break;
    }

    case TrackerMenu::INTERVAL: {
        static char labels[5][24];
        static const char *opts[5] = {labels[0], labels[1], labels[2], labels[3], labels[4]};
        snprintf(labels[0], sizeof(labels[0]), "Back");
        const uint16_t vals[] = {30, 45, 60, 90};
        for (int i = 0; i < 4; ++i) {
            char raw[12]; snprintf(raw, sizeof(raw), "%u s", (unsigned)vals[i]);
            markOption(labels[i + 1], sizeof(labels[i + 1]), trackerSmartIntervalSecs() == vals[i], raw);
        }
        showTrackerOptions("Min TX Interval", opts, 5, initialSelection, [](int selected) {
            if (selected == 0) queueTrackerMenu(TrackerMenu::POSITION, trackerPositionSelection);
            else { const uint16_t vals[] = {30, 45, 60, 90}; trackerSetSmartIntervalSecs(vals[selected - 1]); queueTrackerMenu(TrackerMenu::INTERVAL, 0); }
        });
        break;
    }

    case TrackerMenu::MOVING_GNSS: {
        static char labels[5][24];
        static const char *opts[5] = {labels[0], labels[1], labels[2], labels[3], labels[4]};
        snprintf(labels[0], sizeof(labels[0]), "Back");
        const uint16_t vals[] = {5, 10, 15, 30};
        for (int i = 0; i < 4; ++i) {
            char raw[12]; snprintf(raw, sizeof(raw), "%u s", (unsigned)vals[i]);
            markOption(labels[i + 1], sizeof(labels[i + 1]), trackerMovingGnssSecs() == vals[i], raw);
        }
        showTrackerOptions("Moving GNSS", opts, 5, initialSelection, [](int selected) {
            if (selected == 0) queueTrackerMenu(TrackerMenu::POSITION, trackerPositionSelection);
            else { const uint16_t vals[] = {5, 10, 15, 30}; trackerSetMovingGnssSecs(vals[selected - 1]); queueTrackerMenu(TrackerMenu::MOVING_GNSS, 0); }
        });
        break;
    }

    case TrackerMenu::MOTION: {
        static const char *opts[] = {"Back", "Sensitivity"};
        showTrackerOptions("Motion", opts, 2, initialSelection, [](int selected) {
            trackerMotionSelection = selected;
            if (selected == 0) queueTrackerMenu(TrackerMenu::ROOT, trackerRootSelection);
            else if (selected == 1) queueTrackerMenu(TrackerMenu::MOTION_SENS, 0);
        });
        break;
    }

    case TrackerMenu::MOTION_SENS: {
        static char labels[5][28];
        static const char *opts[5] = {labels[0], labels[1], labels[2], labels[3], labels[4]};
        snprintf(labels[0], sizeof(labels[0]), "Back");
        const char *names[] = {"VERY SENS", "SENSITIVE", "NORMAL", "ROBUST"};
        for (int i = 0; i < 4; ++i)
            markOption(labels[i + 1], sizeof(labels[i + 1]), trackerMotionSensitivityIndex() == i, names[i]);
        showTrackerOptions("Sensitivity", opts, 5, initialSelection, [](int selected) {
            if (selected == 0) queueTrackerMenu(TrackerMenu::MOTION, trackerMotionSelection);
            else { trackerSetMotionSensitivityIndex((uint8_t)(selected - 1)); queueTrackerMenu(TrackerMenu::MOTION_SENS, 0); }
        });
        break;
    }

    case TrackerMenu::PARK_POWER: {
        static const char *opts[] = {"Back", "Park Interval", "GPS Search Time"};
        showTrackerOptions("Parking", opts, 3, initialSelection, [](int selected) {
            trackerParkSelection = selected;
            if (selected == 0) queueTrackerMenu(TrackerMenu::ROOT, trackerRootSelection);
            else if (selected == 1) queueTrackerMenu(TrackerMenu::PARK_INTERVAL, 0);
            else if (selected == 2) queueTrackerMenu(TrackerMenu::PARK_GPS_SEARCH, 0);
        });
        break;
    }

    case TrackerMenu::PARK_INTERVAL: {
        static char labels[9][24];
        static const char *opts[9] = {labels[0], labels[1], labels[2], labels[3], labels[4], labels[5], labels[6], labels[7], labels[8]};
        const uint16_t vals[] = {20, 30, 60, 120, 240, 360, 540, 720};
        const char *names[] = {"20 min", "30 min", "60 min", "2 h", "4 h", "6 h", "9 h", "12 h"};
        snprintf(labels[0], sizeof(labels[0]), "Back");
        for (int i = 0; i < 8; ++i)
            markOption(labels[i + 1], sizeof(labels[i + 1]), trackerParkIntervalMinutes() == vals[i], names[i]);
        showTrackerOptions("Park Interval", opts, 9, initialSelection, [](int selected) {
            if (selected == 0) queueTrackerMenu(TrackerMenu::PARK_POWER, trackerParkSelection);
            else { const uint16_t vals[] = {20, 30, 60, 120, 240, 360, 540, 720}; trackerSetParkIntervalMinutes(vals[selected - 1]); queueTrackerMenu(TrackerMenu::PARK_INTERVAL, 0); }
        });
        break;
    }

    case TrackerMenu::PARK_GPS_SEARCH: {
        static char labels[5][24];
        static const char *opts[5] = {labels[0], labels[1], labels[2], labels[3], labels[4]};
        snprintf(labels[0], sizeof(labels[0]), "Back");
        const uint16_t vals[] = {15, 30, 45, 60};
        for (int i = 0; i < 4; ++i) {
            char raw[12]; snprintf(raw, sizeof(raw), "%u s", (unsigned)vals[i]);
            markOption(labels[i + 1], sizeof(labels[i + 1]), trackerParkGpsSearchSecs() == vals[i], raw);
        }
        showTrackerOptions("GPS Search Time", opts, 5, initialSelection, [](int selected) {
            if (selected == 0) queueTrackerMenu(TrackerMenu::PARK_POWER, trackerParkSelection);
            else { const uint16_t vals[] = {15, 30, 45, 60}; trackerSetParkGpsSearchSecs(vals[selected - 1]); queueTrackerMenu(TrackerMenu::PARK_GPS_SEARCH, 0); }
        });
        break;
    }

    case TrackerMenu::BLUETOOTH: {
        static const char *opts[] = {"Back", "Idle Timeout", "Hard Timeout"};
        showTrackerOptions("Bluetooth", opts, 3, initialSelection, [](int selected) {
            trackerBluetoothSelection = selected;
            if (selected == 0) queueTrackerMenu(TrackerMenu::ROOT, trackerRootSelection);
            else if (selected == 1) queueTrackerMenu(TrackerMenu::BLE_IDLE, 0);
            else if (selected == 2) queueTrackerMenu(TrackerMenu::BLE_HARD, 0);
        });
        break;
    }

    case TrackerMenu::BLE_IDLE: {
        static char labels[5][24];
        static const char *opts[5] = {labels[0], labels[1], labels[2], labels[3], labels[4]};
        snprintf(labels[0], sizeof(labels[0]), "Back");
        const uint16_t vals[] = {60, 120, 180, 300};
        const char *names[] = {"60 s", "120 s", "180 s", "300 s"};
        for (int i = 0; i < 4; ++i) markOption(labels[i + 1], sizeof(labels[i + 1]), trackerBleIdleTimeoutSecs() == vals[i], names[i]);
        showTrackerOptions("Idle Timeout", opts, 5, initialSelection, [](int selected) {
            if (selected == 0) queueTrackerMenu(TrackerMenu::BLUETOOTH, trackerBluetoothSelection);
            else { const uint16_t vals[] = {60, 120, 180, 300}; trackerSetBleIdleTimeoutSecs(vals[selected - 1]); queueTrackerMenu(TrackerMenu::BLE_IDLE, 0); }
        });
        break;
    }

    case TrackerMenu::BLE_HARD: {
        static char labels[5][24];
        static const char *opts[5] = {labels[0], labels[1], labels[2], labels[3], labels[4]};
        snprintf(labels[0], sizeof(labels[0]), "Back");
        const uint16_t vals[] = {300, 600, 900, 1800};
        const char *names[] = {"5 min", "10 min", "15 min", "30 min"};
        for (int i = 0; i < 4; ++i) markOption(labels[i + 1], sizeof(labels[i + 1]), trackerBleHardTimeoutSecs() == vals[i], names[i]);
        showTrackerOptions("Hard Timeout", opts, 5, initialSelection, [](int selected) {
            if (selected == 0) queueTrackerMenu(TrackerMenu::BLUETOOTH, trackerBluetoothSelection);
            else { const uint16_t vals[] = {300, 600, 900, 1800}; trackerSetBleHardTimeoutSecs(vals[selected - 1]); queueTrackerMenu(TrackerMenu::BLE_HARD, 0); }
        });
        break;
    }

    case TrackerMenu::DIAG_LOG: {
        static const char *opts[] = {"Back", "Logging", "Log Status", "Export via USB", "Clear Log"};
        showTrackerOptions("Diagnostic Log", opts, 5, initialSelection, [](int selected) {
            trackerDiagSelection = selected;
            if (selected == 0) queueTrackerMenu(TrackerMenu::ROOT, trackerRootSelection);
            else if (selected == 1) queueTrackerMenu(TrackerMenu::LOGGING, 0);
            else if (selected == 2) queueTrackerMenu(TrackerMenu::LOG_STATUS, 0);
            else if (selected == 3) { queueTrackerMenu(TrackerMenu::LOG_EXPORT_CONFIRM, 0); }
            else if (selected == 4) queueTrackerMenu(TrackerMenu::LOG_CLEAR, 0);
        });
        break;
    }

    case TrackerMenu::LOGGING: {
        static char off[24], on[24];
        static const char *opts[] = {"Back", off, on};
        markOption(off, sizeof(off), !trackerDiagEnabled(), "Off");
        markOption(on, sizeof(on), trackerDiagEnabled(), "On");
        showTrackerOptions("Diagnostic Logging", opts, 3, initialSelection, [](int selected) {
            if (selected == 0) queueTrackerMenu(TrackerMenu::DIAG_LOG, trackerDiagSelection);
            else { trackerDiagSetEnabled(selected == 2); queueTrackerMenu(TrackerMenu::LOGGING, 0); }
        });
        break;
    }

    case TrackerMenu::LOG_STATUS: {
        static char sizeLine[40], exportLine[40];
        static const char *opts[] = {"Back", sizeLine, exportLine};
        snprintf(sizeLine, sizeof(sizeLine), "Size: %u KB", (unsigned)((trackerDiagLogSize() + 1023U) / 1024U));
        snprintf(exportLine, sizeof(exportLine), "USB export: %s", trackerDiagUsbExportPending() ? "WAIT/RUN" : "READY");
        showTrackerOptions("Log Status", opts, 3, initialSelection, [](int selected) {
            if (selected == 0) queueTrackerMenu(TrackerMenu::DIAG_LOG, trackerDiagSelection);
            else queueTrackerMenu(TrackerMenu::LOG_STATUS, 0);
        });
        break;
    }

    case TrackerMenu::LOG_EXPORT_CONFIRM: {
        static const char *opts[] = {"Back", "HOLD: EXPORT NOW"};
        showTrackerOptions("Export Diagnostic Log?", opts, 2, 0, [](int selected) {
            if (selected == 0)
                queueTrackerMenu(TrackerMenu::DIAG_LOG, trackerDiagSelection);
            else if (selected == 1) {
                trackerPowerMonitorPersist();
                trackerDiagRequestUsbExport();
                queueTrackerMenu(TrackerMenu::LOG_EXPORT, 0);
            }
        });
        break;
    }
    case TrackerMenu::LOG_EXPORT: {
        static const char *opts[] = {"Back", trackerLogExportStatus, trackerLogExportProgress};
        refreshTrackerLogExportText();
        showTrackerOptions("Log Download", opts, 3, 0, [](int selected) {
            if (selected == 0)
                queueTrackerMenu(TrackerMenu::DIAG_LOG, trackerDiagSelection);
            else
                queueTrackerMenu(TrackerMenu::LOG_EXPORT, 0);
        });
        break;
    }

    case TrackerMenu::LOG_CLEAR: {
        static const char *opts[] = {"Back", "CLEAR LOG NOW"};
        showTrackerOptions("Clear Diagnostic Log?", opts, 2, initialSelection, [](int selected) {
            if (selected == 0) {
                queueTrackerMenu(TrackerMenu::DIAG_LOG, trackerDiagSelection);
            } else {
                trackerDiagClear();
                queueTrackerMenu(TrackerMenu::LOG_CLEARED, 0);
            }
        });
        break;
    }

    case TrackerMenu::LOG_CLEARED: {
        static const char *opts[] = {"Back"};
        showTrackerOptions("LOG CLEARED", opts, 1, 0, [](int) {
            queueTrackerMenu(TrackerMenu::DIAG_LOG, trackerDiagSelection);
        });
        break;
    }

    case TrackerMenu::SYSTEM: {
        static const char *opts[] = {"Back", "System Info", "Diagnostics", "Power Statistics", "INA226 Hardware", "Antenna Test"};
        showTrackerOptions("System", opts, 6, initialSelection, [](int selected) {
            if (selected == 0) queueTrackerMenu(TrackerMenu::ROOT, trackerRootSelection);
            else if (selected == 1) queueTrackerMenu(TrackerMenu::SYSTEM_INFO, 0);
            else if (selected == 2) queueTrackerMenu(TrackerMenu::DIAGNOSTICS, 0);
            else if (selected == 3) queueTrackerMenu(TrackerMenu::POWER_STATS, 0);
            else if (selected == 4) queueTrackerMenu(TrackerMenu::INA226_HW, 0);
            else if (selected == 5) queueTrackerMenu(TrackerMenu::ANTENNA_TEST, 0);
        });
        break;
    }

    case TrackerMenu::SYSTEM_INFO: {
        static char version[48], build[40], role[40];
        static const char *opts[] = {"Back", version, build, role};
        snprintf(version, sizeof(version), "FW: %s", JARNSEN_FIRMWARE_VERSION);
        snprintf(build, sizeof(build), "Build: %.8s", JARNSEN_BUILD_SHA);
        snprintf(role, sizeof(role), "Role: %s", config.device.role == meshtastic_Config_DeviceConfig_Role_TAK_TRACKER ? "TAK_TRACKER" : "TAK");
        showTrackerOptions("System Info", opts, 4, initialSelection, [](int selected) {
            if (selected == 0) queueTrackerMenu(TrackerMenu::SYSTEM, 1);
            else queueTrackerMenu(TrackerMenu::SYSTEM_INFO, 0);
        });
        break;
    }

    case TrackerMenu::DIAGNOSTICS: {
        static char state[40], gpsAge[40], sensor[40], wake[48], mode[40];
        static const char *opts[] = {"Back", state, gpsAge, sensor, wake, mode};
        snprintf(state, sizeof(state), "State: %s", trackerCommonRuntimeState());
        const uint32_t age = trackerLastFixAgeSecs();
        if (age == UINT32_MAX) snprintf(gpsAge, sizeof(gpsAge), "GPS age: ?");
        else snprintf(gpsAge, sizeof(gpsAge), "GPS age: %us", (unsigned)age);
        snprintf(sensor, sizeof(sensor), "Sensor: %s", trackerMotionSensorStatus());
        snprintf(wake, sizeof(wake), "Wake: %s", trackerBootWakeReason());
        snprintf(mode, sizeof(mode), "Sleep: %s", config.device.role == meshtastic_Config_DeviceConfig_Role_TAK_TRACKER ? "Deep" : "Light");
        showTrackerOptions("Diagnostics", opts, 6, initialSelection, [](int selected) {
            if (selected == 0) queueTrackerMenu(TrackerMenu::SYSTEM, 2);
            else queueTrackerMenu(TrackerMenu::DIAGNOSTICS, 0);
        });
        break;
    }

    case TrackerMenu::INA226_HW: {
        static char offLine[24], onLine[24];
        static const char *opts[] = {"Back", offLine, onLine};
        const bool enabled = trackerIna226Enabled();
        markOption(offLine, sizeof(offLine), !enabled, "Off");
        markOption(onLine, sizeof(onLine), enabled, "On");
        showTrackerOptions("INA226 Hardware", opts, 3, initialSelection, [](int selected) {
            if (selected == 0) queueTrackerMenu(TrackerMenu::SYSTEM, 4);
            else {
                trackerSetIna226Enabled(selected == 2);
                queueTrackerMenu(TrackerMenu::INA226_HW, 0);
            }
        });
        break;
    }

    case TrackerMenu::POWER_STATS: {
        static char batteryLine[48], remainingLine[48], inaLine[48], currentLine[48], powerLine[48];
        static char usedLine[48], capacityLine[48], confidenceLine[48], measuredLine[48], movingLine[48];
        static char parkedLine[48], gnssLine[48], bleLine[48], displayLine[48], txLine[48], trendLine[48];
        static const char *opts[] = {"Back", batteryLine, remainingLine, inaLine, currentLine, powerLine, usedLine,
                                     capacityLine, confidenceLine, measuredLine, movingLine, parkedLine, gnssLine,
                                     bleLine, displayLine, txLine, trendLine};
        const TrackerPowerStats p = trackerPowerMonitorStats();
        if (p.batteryValid)
            snprintf(batteryLine, sizeof(batteryLine), "Battery: %u%%  %u.%03uV", (unsigned)p.batteryPercent,
                     (unsigned)(p.voltageMv / 1000U), (unsigned)(p.voltageMv % 1000U));
        else
            snprintf(batteryLine, sizeof(batteryLine), "Battery: unavailable");

        char duration[32] = {};
        if (p.usbPowered || p.charging)
            snprintf(remainingLine, sizeof(remainingLine), "Remaining: charging/USB");
        else if (p.estimateReady) {
            trackerPowerFormatDuration(p.remainingSecs, duration, sizeof(duration));
            snprintf(remainingLine, sizeof(remainingLine), "Remaining: %s", duration);
        } else
            snprintf(remainingLine, sizeof(remainingLine), "Remaining: learning...");

        if (!p.inaConfigured) snprintf(inaLine, sizeof(inaLine), "INA226: OFF");
        else if (!p.inaPresent) snprintf(inaLine, sizeof(inaLine), "INA226: MISSING");
        else if (!p.inaValid) snprintf(inaLine, sizeof(inaLine), "INA226: WAIT");
        else if (!p.vbusValid) snprintf(inaLine, sizeof(inaLine), "INA226: VBUS MISSING");
        else snprintf(inaLine, sizeof(inaLine), "INA226: ACTIVE  %umV", (unsigned)p.inaBusVoltageMv);

        if (p.inaValid) {
            const int32_t c = p.currentMilliAmpsX10;
            const int32_t ac = c < 0 ? -c : c;
            snprintf(currentLine, sizeof(currentLine), "Current: %s%ld.%ld mA", c < 0 ? "-" : "",
                     (long)(ac / 10), (long)(ac % 10));
        } else {
            snprintf(currentLine, sizeof(currentLine), "Current: --");
        }
        if (p.inaValid && p.vbusValid) {
            const int32_t w = p.powerMilliWattsX10;
            const int32_t aw = w < 0 ? -w : w;
            snprintf(powerLine, sizeof(powerLine), "Power: %s%ld.%ld mW", w < 0 ? "-" : "",
                     (long)(aw / 10), (long)(aw % 10));
        } else if (p.inaValid) {
            snprintf(powerLine, sizeof(powerLine), "Power: -- (VBUS)");
        } else {
            snprintf(powerLine, sizeof(powerLine), "Power: --");
        }

        if (p.vbusValid)
            snprintf(usedLine, sizeof(usedLine), "Used: %u.%u mAh / %u.%u mWh",
                     (unsigned)(p.dischargedMahX10 / 10U), (unsigned)(p.dischargedMahX10 % 10U),
                     (unsigned)(p.dischargedMwhX10 / 10U), (unsigned)(p.dischargedMwhX10 % 10U));
        else
            snprintf(usedLine, sizeof(usedLine), "Used: %u.%u mAh / -- mWh",
                     (unsigned)(p.dischargedMahX10 / 10U), (unsigned)(p.dischargedMahX10 % 10U));
        if (p.capacityReady)
            snprintf(capacityLine, sizeof(capacityLine), "Capacity: %u mAh", (unsigned)p.learnedCapacityMah);
        else
            snprintf(capacityLine, sizeof(capacityLine), "Capacity: learning...");
        snprintf(confidenceLine, sizeof(confidenceLine), "Confidence: %u%%  Cycles:%u",
                 (unsigned)p.capacityConfidence, (unsigned)p.capacityCycles);

        trackerPowerFormatDuration(p.measuredSecs, duration, sizeof(duration));
        snprintf(measuredLine, sizeof(measuredLine), "Measured: %s", duration);
        trackerPowerFormatDuration(p.movingSecs, duration, sizeof(duration));
        snprintf(movingLine, sizeof(movingLine), "Moving: %s", duration);
        trackerPowerFormatDuration(p.parkedSecs, duration, sizeof(duration));
        snprintf(parkedLine, sizeof(parkedLine), "Parked: %s", duration);
        trackerPowerFormatDuration(p.gnssSecs, duration, sizeof(duration));
        snprintf(gnssLine, sizeof(gnssLine), "GNSS: %s", duration);
        trackerPowerFormatDuration(p.bleSecs, duration, sizeof(duration));
        snprintf(bleLine, sizeof(bleLine), "BLE: %s", duration);
        trackerPowerFormatDuration(p.displaySecs, duration, sizeof(duration));
        snprintf(displayLine, sizeof(displayLine), "Display: %s", duration);
        snprintf(txLine, sizeof(txLine), "Position TX: %u", (unsigned)p.positionTxCount);
        if (p.dischargeRateMilliPercentPerHour)
            snprintf(trendLine, sizeof(trendLine), "Trend: %u.%03u%%/h",
                     (unsigned)(p.dischargeRateMilliPercentPerHour / 1000U),
                     (unsigned)(p.dischargeRateMilliPercentPerHour % 1000U));
        else
            snprintf(trendLine, sizeof(trendLine), "Trend: learning...");

        showTrackerOptions("Power Statistics", opts, 17, initialSelection, [](int selected) {
            if (selected == 0) queueTrackerMenu(TrackerMenu::SYSTEM, 3);
            else queueTrackerMenu(TrackerMenu::POWER_STATS, 0);
        });
        break;
    }

    case TrackerMenu::ANTENNA_TEST: {
        static char stateLine[40], refLine[40], sampleLine[40], aLine[48], bLine[48], safetyLine[48], resultLine[48], actionLine[48];
        static const char *opts[] = {"Back", stateLine, refLine, sampleLine, aLine, bLine, safetyLine, resultLine, actionLine};
        const TrackerAntennaState a = trackerAntennaState();

        snprintf(stateLine, sizeof(stateLine), "State: %s", trackerAntennaPhaseText(a.phase));
        if (a.referenceNode)
            snprintf(refLine, sizeof(refLine), "Ref: %s !%04x", a.referenceName, (unsigned)(a.referenceNode & 0xffffU));
        else
            snprintf(refLine, sizeof(refLine), "Ref: last direct on start");

        if (a.phase == TrackerAntennaPhase::A_RUNNING || a.phase == TrackerAntennaPhase::B_RUNNING)
            snprintf(sampleLine, sizeof(sampleLine), "Samples: %u/60  min 40", (unsigned)a.liveSamples);
        else
            snprintf(sampleLine, sizeof(sampleLine), "Samples: min 40 / target 60");

        if (a.a.valid)
            snprintf(aLine, sizeof(aLine), "A: %ddBm  SNR %+.1fdB", (int)a.a.medianRssiDbm, a.a.medianSnrQ4 / 4.0f);
        else
            snprintf(aLine, sizeof(aLine), "A: --");
        if (a.b.valid)
            snprintf(bLine, sizeof(bLine), "B: %ddBm  SNR %+.1fdB", (int)a.b.medianRssiDbm, a.b.medianSnrQ4 / 4.0f);
        else
            snprintf(bLine, sizeof(bLine), "B: --");

        if (a.txLocked)
            snprintf(safetyLine, sizeof(safetyLine), "TX: LOCKED %s", a.txSafeToSwap ? "SAFE" : "WAIT");
        else
            snprintf(safetyLine, sizeof(safetyLine), "TX: NORMAL");

        if (a.a.valid && a.b.valid) {
            const char *winner = a.deltaRssiDb >= 3 ? "B MUCH BETTER" :
                                 a.deltaRssiDb <= -3 ? "A MUCH BETTER" :
                                 a.deltaRssiDb >= 1 ? "B BETTER" :
                                 a.deltaRssiDb <= -1 ? "A BETTER" : "ABOUT EQUAL";
            snprintf(resultLine, sizeof(resultLine), "Delta: %+ddB  %s", (int)a.deltaRssiDb, winner);
        } else {
            snprintf(resultLine, sizeof(resultLine), "Compare: passive direct RX");
        }

        switch (a.phase) {
        case TrackerAntennaPhase::IDLE:
            snprintf(actionLine, sizeof(actionLine), "ACTION: START A");
            break;
        case TrackerAntennaPhase::A_RUNNING:
            snprintf(actionLine, sizeof(actionLine), "ACTION: %s", a.liveSamples >= 40 ? "SAVE A" : "CHECK A");
            break;
        case TrackerAntennaPhase::A_SAVED:
            snprintf(actionLine, sizeof(actionLine), "ACTION: PREP SWAP / LOCK TX");
            break;
        case TrackerAntennaPhase::SWAP_LOCKED:
            snprintf(actionLine, sizeof(actionLine), "ACTION: %s", a.txSafeToSwap ? "B CONNECTED / START B" : "WAIT TX FINISH");
            break;
        case TrackerAntennaPhase::B_RUNNING:
            snprintf(actionLine, sizeof(actionLine), "ACTION: %s", a.liveSamples >= 40 ? "SAVE B" : "CHECK B");
            break;
        case TrackerAntennaPhase::COMPLETE:
            snprintf(actionLine, sizeof(actionLine), "ACTION: NEW TEST");
            break;
        }

        showTrackerOptions("Antenna Test", opts, 9, initialSelection, [](int selected) {
            if (selected == 0) {
                queueTrackerMenu(TrackerMenu::SYSTEM, 5);
            } else if (selected == 8) {
                trackerAntennaHandleAction();
                queueTrackerMenu(TrackerMenu::ANTENNA_TEST, 8);
            } else {
                // Informational rows are selectable only so one-button users can
                // refresh the live sample/TX-safe state without changing it.
                queueTrackerMenu(TrackerMenu::ANTENNA_TEST, selected);
            }
        });
        break;
    }

    default:
        break;
    }
}

} // namespace

bool trackerServiceMenuActive()
{
    return trackerServiceMenuMode;
}

bool trackerServicePageVisible()
{
    return !trackerServiceMenuMode && screen && trackerServiceFrameIndex != 255 &&
           screen->currentFrameIndex() == trackerServiceFrameIndex;
}

void trackerServiceMenuOpen()
{
    if (!trackerUiRoleEnabled() || !trackerServicePageVisible())
        return;
    trackerServiceMenuMode = true;
    trackerRootSelection = 0;
    queueTrackerMenu(TrackerMenu::ROOT, trackerRootSelection);
}

void trackerServiceMenuShortPress()
{
    if (!trackerServiceMenuMode || !screen)
        return;
    graphics::NotificationRenderer::inEvent.inputEvent = INPUT_BROKER_USER_PRESS;
    screen->runNow();
}

void trackerServiceMenuSelect()
{
    if (!trackerServiceMenuMode || !screen)
        return;
    graphics::NotificationRenderer::inEvent.inputEvent = INPUT_BROKER_SELECT;
    screen->runNow();
}

void trackerServiceMenuPump()
{
    if (!trackerServiceMenuMode)
        return;

    if (trackerMenuCurrent == TrackerMenu::LOG_EXPORT) {
        const uint32_t now = millis();
        if (trackerLogExportLastRefreshMs == 0 || (uint32_t)(now - trackerLogExportLastRefreshMs) >= 250U) {
            trackerLogExportLastRefreshMs = now ? now : 1;
            refreshTrackerLogExportText();
            if (screen)
                screen->runNow();
        }
    }

    if (trackerMenuPending == TrackerMenu::NONE)
        return;
    const TrackerMenu menu = trackerMenuPending;
    const int selection = trackerMenuPendingSelection;
    showTrackerMenu(menu, selection);
}

void trackerServiceMenuClose()
{
    trackerServiceMenuMode = false;
    trackerMenuCurrent = TrackerMenu::NONE;
    trackerMenuPending = TrackerMenu::NONE;
    graphics::NotificationRenderer::resetBanner();
    trackerServiceModule.requestServiceFocus();
    if (screen) {
        screen->setFrames(graphics::Screen::FOCUS_MODULE);
        screen->runNow();
    }
}

void trackerServiceMenuForceClose()
{
    trackerServiceMenuMode = false;
    trackerMenuCurrent = TrackerMenu::NONE;
    trackerMenuPending = TrackerMenu::NONE;
    graphics::NotificationRenderer::resetBanner();
}

void trackerStatusRequestFocus()
{
    if (!trackerUiRoleEnabled())
        return;
    trackerStatusModule.requestTrackerFocus();
    if (screen) {
        screen->setFrames(graphics::Screen::FOCUS_MODULE);
        screen->runNow();
    }
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
bool trackerServiceMenuActive() { return false; }
bool trackerServicePageVisible() { return false; }
void trackerServiceMenuOpen() {}
void trackerServiceMenuShortPress() {}
void trackerServiceMenuSelect() {}
void trackerServiceMenuPump() {}
void trackerServiceMenuClose() {}
void trackerServiceMenuForceClose() {}

#endif
