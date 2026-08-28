#include "drone/DroneStatusPages.h"

#if defined(HELTEC_TRACKER_V1_1) && defined(JARNSEN_DRONE_REPEATER_BUILD) && HAS_SCREEN

#include "GPS.h"
#include "GPSStatus.h"
#include "drone/DroneMeshHealth.h"
#include "drone/DronePowerMonitor.h"
#include "drone/DroneSystemHealth.h"
#include "graphics/Screen.h"
#include "graphics/ScreenFonts.h"
#include "graphics/SharedUIDisplay.h"
#include "graphics/draw/UIRenderer.h"
#include "mesh/MeshModule.h"
#include "vehicle/JarnsenBuildInfo.h"

#include <algorithm>
#include <cmath>
#include <cstdio>
#include <cstring>

namespace
{
char latitudeBand(double latitude)
{
    static constexpr char bands[] = "CDEFGHJKLMNPQRSTUVWX";
    if (latitude < -80.0 || latitude > 84.0)
        return 0;
    int index = static_cast<int>(floor((latitude + 80.0) / 8.0));
    index = std::max(0, std::min(19, index));
    return bands[index];
}

int utmZone(double latitude, double longitude)
{
    int zone = static_cast<int>(floor((longitude + 180.0) / 6.0)) + 1;
    zone = std::max(1, std::min(60, zone));
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
        return false;

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
                          (5.0 - 18.0 * t + t * t + 72.0 * c - 58.0 * eccPrimeSquared) * aa * aa * aa * aa * aa / 120.0) +
                     500000.0;
    double northing = k0 *
                      (m + n * tanLat *
                               (aa * aa / 2.0 + (5.0 - t + 9.0 * c + 4.0 * c * c) * aa * aa * aa * aa / 24.0 +
                                (61.0 - 58.0 * t + t * t + 600.0 * c - 330.0 * eccPrimeSquared) * aa * aa * aa * aa * aa * aa /
                                    720.0));
    if (latitude < 0.0)
        northing += 10000000.0;

    static constexpr const char *eastingSets[] = {"ABCDEFGH", "JKLMNPQR", "STUVWXYZ"};
    static constexpr char northingLetters[] = "ABCDEFGHJKLMNPQRSTUV";
    const int e100k = static_cast<int>(floor(easting / 100000.0));
    if (e100k < 1 || e100k > 8)
        return false;
    const char eLetter = eastingSets[(zone - 1) % 3][e100k - 1];
    const int n100k = static_cast<int>(floor(northing / 100000.0)) % 20;
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

void commonBegin(OLEDDisplay *display, int16_t x, int16_t y, const char *title)
{
    display->clear();
    graphics::drawCommonHeader(display, x, y, title);
    display->setColor(WHITE);
    display->setFont(FONT_SMALL);
}

void commonEnd(OLEDDisplay *display, OLEDDisplayUiState *state, int16_t x, int16_t y)
{
    graphics::drawCommonFooter(display, x, y);
    if (state)
        graphics::UIRenderer::drawNavigationBar(display, state);
}

class DronePositionPage : public MeshModule
{
  public:
    DronePositionPage() : MeshModule("Drone Position") {}
    bool wantPacket(const meshtastic_MeshPacket *) override { return false; }
    bool wantUIFrame() override { return true; }

    void drawFrame(OLEDDisplay *display, OLEDDisplayUiState *state, int16_t x, int16_t y) override
    {
        if (!display)
            return;
        commonBegin(display, x, y, "Drone Position");
        const int *pos = graphics::getTextPositions(display);
        const int left = x + 2;
        const int right = x + display->getWidth() - 2;
        char line[48] = {};
        char mgrs[32] = {};
        const bool haveFix = gpsStatus && gpsStatus->getHasLock();
        const bool haveMgrs = haveFix && latLonToMgrs(gpsStatus->getLatitude(), gpsStatus->getLongitude(), mgrs, sizeof(mgrs));

        display->setTextAlignment(TEXT_ALIGN_LEFT);
        display->drawString(left, pos[1], haveMgrs ? mgrs : (haveFix ? "MGRS --" : "GPS sucht..."));

        const unsigned sats = gpsStatus ? gpsStatus->getNumSatellites() : 0U;
        const unsigned accuracy = gpsStatus && gpsStatus->getDOP() ? std::max(1U, (unsigned)ceil((gpsStatus->getDOP() / 100.0) * 3.0)) : 0U;
        snprintf(line, sizeof(line), "GPS:%s SAT:%u +/-:%um", haveFix ? "FIX" : "--", sats, accuracy);
        display->drawString(left, pos[2], line);

        const int altitude = gpsStatus ? gpsStatus->getAltitude() : 0;
        const float speed = gps ? (float)gps->p.ground_speed : 0.0f;
        snprintf(line, sizeof(line), "ALT:%dm SPD:%.1fkm/h", altitude, speed);
        display->drawString(left, pos[3], line);

        uint32_t age = UINT32_MAX;
        if (gpsStatus && gpsStatus->getLastFixMillis() != 0)
            age = (millis() - gpsStatus->getLastFixMillis()) / 1000UL;
        display->setTextAlignment(TEXT_ALIGN_LEFT);
        snprintf(line, sizeof(line), "AGE:%s", age == UINT32_MAX ? "--" : "");
        if (age != UINT32_MAX)
            snprintf(line, sizeof(line), "AGE:%us", (unsigned)age);
        display->drawString(left, pos[4], line);
        display->setTextAlignment(TEXT_ALIGN_RIGHT);
        display->drawString(right, pos[4], "25m adaptive");
        commonEnd(display, state, x, y);
    }
};

class DroneMeshPage : public MeshModule
{
  public:
    DroneMeshPage() : MeshModule("Drone Mesh") {}
    bool wantPacket(const meshtastic_MeshPacket *) override { return false; }
    bool wantUIFrame() override { return true; }

    void drawFrame(OLEDDisplay *display, OLEDDisplayUiState *state, int16_t x, int16_t y) override
    {
        if (!display)
            return;
        commonBegin(display, x, y, "Mesh Health");
        const DroneMeshHealthSummary mesh = droneMeshHealthSummary();
        const int *pos = graphics::getTextPositions(display);
        const int left = x + 2;
        char line[56] = {};
        display->setTextAlignment(TEXT_ALIGN_LEFT);
        snprintf(line, sizeof(line), "Nodes:%u 15m:%u Direct:%u", (unsigned)mesh.observedNodes, (unsigned)mesh.active15m,
                 (unsigned)mesh.direct15m);
        display->drawString(left, pos[1], line);
        snprintf(line, sizeof(line), "RX 1h:%u total:%u", (unsigned)mesh.rx1h, (unsigned)mesh.totalRx);
        display->drawString(left, pos[2], line);
        if (mesh.lastDirectNode != 0)
            snprintf(line, sizeof(line), "Last !%08x", (unsigned)mesh.lastDirectNode);
        else
            snprintf(line, sizeof(line), "Last direct: --");
        display->drawString(left, pos[3], line);
        if (mesh.lastDirectNode != 0)
            snprintf(line, sizeof(line), "RSSI:%ddBm SNR:%.1fdB", (int)mesh.lastDirectRssiDbm, mesh.lastDirectSnrDb);
        else
            snprintf(line, sizeof(line), "RSSI/SNR: --");
        display->drawString(left, pos[4], line);
        commonEnd(display, state, x, y);
    }
};

class DroneSystemPage : public MeshModule
{
  public:
    DroneSystemPage() : MeshModule("Drone System") {}
    bool wantPacket(const meshtastic_MeshPacket *) override { return false; }
    bool wantUIFrame() override { return true; }

    void drawFrame(OLEDDisplay *display, OLEDDisplayUiState *state, int16_t x, int16_t y) override
    {
        if (!display)
            return;
        commonBegin(display, x, y, "Drone System");
        const DronePowerStats power = dronePowerMonitorStats();
        const DroneSystemHealthStats health = droneSystemHealthStats();
        const int *pos = graphics::getTextPositions(display);
        const int left = x + 2;
        char line[56] = {};
        display->setTextAlignment(TEXT_ALIGN_LEFT);
        if (power.hasBattery)
            snprintf(line, sizeof(line), "Power:%s Bat:%u%% %umV", dronePowerSourceText(), (unsigned)power.batteryPercent,
                     (unsigned)power.voltageMv);
        else
            snprintf(line, sizeof(line), "Power:%s", dronePowerSourceText());
        display->drawString(left, pos[1], line);
        snprintf(line, sizeof(line), "USB drops:%u restore:%u", (unsigned)power.usbDropCount, (unsigned)power.usbRestoreCount);
        display->drawString(left, pos[2], line);
        snprintf(line, sizeof(line), "Health:%s Reset:%s", droneSystemHealthStatusText(), droneSystemHealthResetReasonText());
        display->drawString(left, pos[3], line);
        snprintf(line, sizeof(line), "Heap:%uK Boot:%u %.8s", (unsigned)(health.minFreeHeap / 1024U), (unsigned)health.bootCount,
                 JARNSEN_BUILD_SHA);
        display->drawString(left, pos[4], line);
        commonEnd(display, state, x, y);
    }
};

DronePositionPage *positionPage = nullptr;
DroneMeshPage *meshPage = nullptr;
DroneSystemPage *systemPage = nullptr;
}

void setupDroneStatusPages()
{
    if (!positionPage)
        positionPage = new DronePositionPage();
    if (!meshPage)
        meshPage = new DroneMeshPage();
    if (!systemPage)
        systemPage = new DroneSystemPage();
}

void droneStatusPagesRefresh()
{
    if (screen && screen->isScreenOn())
        screen->runNow();
}

#elif defined(HELTEC_TRACKER_V1_1) && defined(JARNSEN_DRONE_REPEATER_BUILD)

void setupDroneStatusPages() {}
void droneStatusPagesRefresh() {}

#endif
