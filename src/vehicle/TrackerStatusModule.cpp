#include "configuration.h"

#if defined(HELTEC_TRACKER_V1_1) && HAS_SCREEN

#include "GPSStatus.h"
#include "NodeDB.h"
#include "gps/RTC.h"
#include "graphics/Screen.h"
#include "graphics/ScreenFonts.h"
#include "graphics/TFTColorRegions.h"
#include "graphics/TFTPalette.h"
#include "mesh/MeshModule.h"
#include "vehicle/TrackerStatusModule.h"

#include <algorithm>
#include <cmath>
#include <cstdio>
#include <cstring>

namespace
{
volatile bool trackerMotionActive = false;

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
} // namespace

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

#endif
