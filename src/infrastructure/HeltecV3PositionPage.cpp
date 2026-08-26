#include "configuration.h"

#if defined(_VARIANT_HELTEC_V3) && HAS_SCREEN

#include "HeltecV3PositionPage.h"
#include "graphics/Screen.h"
#include "graphics/ScreenFonts.h"
#include "graphics/SharedUIDisplay.h"
#include "graphics/draw/UIRenderer.h"
#include "mesh/MeshModule.h"

#include <algorithm>
#include <cmath>
#include <cstdio>
#include <cstring>

namespace
{
volatile uint32_t lastPositionPageDrawMs = 0;

bool v3PositionUiRoleEnabled()
{
    return config.device.role == meshtastic_Config_DeviceConfig_Role_ROUTER_LATE ||
           config.device.role == meshtastic_Config_DeviceConfig_Role_REPEATER;
}

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

// 8-digit MGRS, 10 m display resolution. Internal position calculations keep
// full latitude/longitude precision.
bool latLonToMgrs8(int32_t latitudeI, int32_t longitudeI, char *out, size_t outSize)
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

    const double m =
        a *
        ((1.0 - eccSquared / 4.0 - 3.0 * eccSquared * eccSquared / 64.0 - 5.0 * eccSquared * eccSquared * eccSquared / 256.0) *
             latRad -
         (3.0 * eccSquared / 8.0 + 3.0 * eccSquared * eccSquared / 32.0 + 45.0 * eccSquared * eccSquared * eccSquared / 1024.0) *
             sin(2.0 * latRad) +
         (15.0 * eccSquared * eccSquared / 256.0 + 45.0 * eccSquared * eccSquared * eccSquared / 1024.0) * sin(4.0 * latRad) -
         (35.0 * eccSquared * eccSquared * eccSquared / 3072.0) * sin(6.0 * latRad));

    const double easting = k0 * n *
                               (aa + (1.0 - t + c) * aa * aa * aa / 6.0 +
                                (5.0 - 18.0 * t + t * t + 72.0 * c - 58.0 * eccPrimeSquared) * aa * aa * aa * aa * aa / 120.0) +
                           500000.0;

    double northing =
        k0 * (m + n * tanLat *
                      (aa * aa / 2.0 + (5.0 - t + 9.0 * c + 4.0 * c * c) * aa * aa * aa * aa / 24.0 +
                       (61.0 - 58.0 * t + t * t + 600.0 * c - 330.0 * eccPrimeSquared) * aa * aa * aa * aa * aa * aa / 720.0));
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

    int eMeters = static_cast<int>(floor(easting)) % 100000;
    int nMeters = static_cast<int>(floor(northing)) % 100000;
    if (eMeters < 0)
        eMeters += 100000;
    if (nMeters < 0)
        nMeters += 100000;

    snprintf(out, outSize, "%02d%c %c%c %04d %04d", zone, band, eLetter, nLetter, eMeters / 10, nMeters / 10);
    return true;
}

bool splitMgrs(const char *mgrs, char *prefix, size_t prefixSize, char *digits, size_t digitsSize)
{
    char zoneBand[8] = {};
    char grid[4] = {};
    char east[8] = {};
    char north[8] = {};
    if (!mgrs || sscanf(mgrs, "%7s %3s %7s %7s", zoneBand, grid, east, north) != 4) {
        snprintf(prefix, prefixSize, "---");
        snprintf(digits, digitsSize, "---");
        return false;
    }
    snprintf(prefix, prefixSize, "%s %s", zoneBand, grid);
    snprintf(digits, digitsSize, "%s %s", east, north);
    return true;
}

void formatCompactDistance(uint32_t meters, char *out, size_t outSize)
{
    if (!out || outSize == 0)
        return;
    if (meters < 1000U)
        snprintf(out, outSize, "%um", (unsigned)meters);
    else if (meters < 100000U)
        snprintf(out, outSize, "%.1fk", meters / 1000.0);
    else
        snprintf(out, outSize, "%uk", (unsigned)((meters + 500U) / 1000U));
}

void formatWaitTime(uint32_t seconds, char *out, size_t outSize)
{
    if (!out || outSize == 0)
        return;
    const uint32_t minutes = seconds / 60U;
    const uint32_t remainder = seconds % 60U;
    snprintf(out, outSize, "WAIT %lu:%02lu", (unsigned long)minutes, (unsigned long)remainder);
}

class HeltecV3PositionModule : public MeshModule
{
  public:
    HeltecV3PositionModule() : MeshModule("V3 Position") {}

    bool wantPacket(const meshtastic_MeshPacket *) override { return false; }
    bool wantUIFrame() override { return false; }
    void requestPositionFocus() { requestFocus(); }

    void drawFrame(OLEDDisplay *display, OLEDDisplayUiState *uiState, int16_t x, int16_t y) override
    {
        if (!display)
            return;

        lastPositionPageDrawMs = millis() ? millis() : 1;

        HeltecV3PositionUiState state;
        heltecV3GetPositionUiState(state);
        HeltecV3PhoneEstimateUiState estimate;
        heltecV3GetPhoneEstimateUiState(estimate);

        char savedMgrs[28] = "---";
        char estimateMgrs[28] = "---";
        const bool savedMgrsValid =
            state.haveSavedPosition && latLonToMgrs8(state.savedLatitudeI, state.savedLongitudeI, savedMgrs, sizeof(savedMgrs));
        const bool estimateMgrsValid =
            estimate.available && latLonToMgrs8(estimate.latitudeI, estimate.longitudeI, estimateMgrs, sizeof(estimateMgrs));

        char savedPrefix[16] = "---";
        char savedDigits[20] = "---";
        char estimatePrefix[16] = "---";
        char estimateDigits[20] = "---";
        if (savedMgrsValid)
            splitMgrs(savedMgrs, savedPrefix, sizeof(savedPrefix), savedDigits, sizeof(savedDigits));
        if (estimateMgrsValid)
            splitMgrs(estimateMgrs, estimatePrefix, sizeof(estimatePrefix), estimateDigits, sizeof(estimateDigits));

        display->clear();
        graphics::drawCommonHeader(display, x, y, "Position");
        display->setColor(WHITE);
        const int *textPos = graphics::getTextPositions(display);
        const int16_t center = display->getWidth() / 2 + x;
        const int left = x + 2;
        const int right = x + display->getWidth() - 2;
        const int bottomLineY = std::min<int>(display->getHeight() - FONT_HEIGHT_SMALL, textPos[3] + FONT_HEIGHT_MEDIUM - 1);

        auto finishPage = [&]() {
            graphics::drawCommonFooter(display, x, y);
            if (uiState)
                graphics::UIRenderer::drawNavigationBar(display, uiState);
        };
        auto drawPair = [&](int yy, const char *a, const char *b) {
            display->setFont(FONT_SMALL);
            display->setTextAlignment(TEXT_ALIGN_LEFT);
            display->drawString(left, yy, a ? a : "");
            display->setTextAlignment(TEXT_ALIGN_RIGHT);
            display->drawString(right, yy, b ? b : "");
        };
        auto drawMgrs = [&](const char *prefix, const char *digits) {
            display->setTextAlignment(TEXT_ALIGN_CENTER);
            display->setFont(FONT_SMALL);
            display->drawString(center, textPos[2], prefix);
            display->setFont(FONT_MEDIUM);
            display->drawString(center, textPos[3], digits);
        };

        if (estimate.lastManualSaveValid && estimate.lastManualSaveAgeMs <= 3000U && estimateMgrsValid) {
            drawPair(textPos[1], "POSITION SAVED", "MANUAL");
            drawMgrs(estimatePrefix, estimateDigits);
            display->setFont(FONT_SMALL);
            display->setTextAlignment(TEXT_ALIGN_CENTER);
            display->drawString(center, bottomLineY, estimate.lastManualSaveMeshSent ? "SENT TO MESH" : "MESH POS OFF");
            finishPage();
            return;
        }

        if (state.lastSaveValid && state.lastSaveAgeMs <= 3000U && savedMgrsValid) {
            drawPair(textPos[1], "POSITION SAVED", state.lastSaveAutomatic ? "AUTO" : "MANUAL");
            drawMgrs(savedPrefix, savedDigits);
            char status[32] = {};
            snprintf(status, sizeof(status), "DIFF %um%s", (unsigned)state.lastSavedDifferenceM,
                     state.lastSaveMeshSent ? " SENT" : "");
            display->setFont(FONT_SMALL);
            display->setTextAlignment(TEXT_ALIGN_CENTER);
            display->drawString(center, bottomLineY, status);
            finishPage();
            return;
        }

        if (estimate.available && estimateMgrsValid) {
            char fixedTag[18] = {};
            if (estimate.fixedDifferenceValid) {
                char distance[12] = {};
                formatCompactDistance(estimate.fixedDifferenceM, distance, sizeof(distance));
                snprintf(fixedTag, sizeof(fixedTag), "dF:%s", distance);
            } else {
                snprintf(fixedTag, sizeof(fixedTag), "NO FIX");
            }

            if (estimate.moving) {
                drawPair(textPos[1], "MOVING", fixedTag);
                drawMgrs(estimatePrefix, estimateDigits);
                char stepDistance[12] = {};
                char stepText[20] = {};
                formatCompactDistance(estimate.movementStepM, stepDistance, sizeof(stepDistance));
                snprintf(stepText, sizeof(stepText), "STEP %s", stepDistance);
                drawPair(bottomLineY, stepText, "HOLD:SAVE");
                finishPage();
                return;
            }

            if (estimate.stabilizing) {
                char status[24] = {};
                snprintf(status, sizeof(status), "STABILIZE %u/%u", (unsigned)estimate.stabilizingCount,
                         (unsigned)estimate.stabilizingRequired);
                drawPair(textPos[1], status, fixedTag);
                drawMgrs(estimatePrefix, estimateDigits);
                char waitText[20] = {};
                formatWaitTime(estimate.stabilizingRemainingSecs, waitText, sizeof(waitText));
                drawPair(bottomLineY, waitText, "HOLD:SAVE");
                finishPage();
                return;
            }

            char quality[28] = {};
            char detail[28] = {};
            if (estimate.reportedAccuracyValid)
                snprintf(quality, sizeof(quality), "ACC +/-%um", (unsigned)estimate.reportedAccuracyM);
            else if (estimate.estimatedAccuracyValid)
                snprintf(quality, sizeof(quality), "EST +/-%um", (unsigned)estimate.estimatedAccuracyM);
            else
                snprintf(quality, sizeof(quality), "EST ?");
            snprintf(detail, sizeof(detail), "N%u %s", (unsigned)estimate.sampleCount,
                     estimate.phoneTimestampStale ? "T:OLD" : "T:OK");
            drawPair(textPos[1], quality, fixedTag);
            drawMgrs(estimatePrefix, estimateDigits);
            drawPair(bottomLineY, detail, "HOLD:SAVE");
            finishPage();
            return;
        }

        if (savedMgrsValid) {
            drawPair(textPos[1], "FIXED POSITION", "");
            drawMgrs(savedPrefix, savedDigits);
            display->setFont(FONT_SMALL);
            display->setTextAlignment(TEXT_ALIGN_CENTER);
            display->drawString(center, bottomLineY, state.serviceActive ? "WAIT FOR PHONE GPS" : "STORED");
            finishPage();
            return;
        }

        display->setTextAlignment(TEXT_ALIGN_CENTER);
        display->setFont(FONT_MEDIUM);
        display->drawString(center, textPos[2], "NO POSITION");
        display->setFont(FONT_SMALL);
        display->drawString(center, bottomLineY, state.serviceActive ? "WAIT FOR PHONE GPS" : "OPEN SERVICE");
        finishPage();
    }
};

HeltecV3PositionModule heltecV3PositionModule;
} // namespace

bool heltecV3PositionPageEnabled()
{
    return v3PositionUiRoleEnabled();
}

void heltecV3PositionPageDrawFrame(OLEDDisplay *display, OLEDDisplayUiState *state, int16_t x, int16_t y)
{
    heltecV3PositionModule.drawFrame(display, state, x, y);
}

void heltecV3PositionPageRequestFocus()
{
    if (!v3PositionUiRoleEnabled())
        return;
    if (screen) {
        screen->setFrames(graphics::Screen::FOCUS_DEFAULT);
        screen->runNow();
    }
}

void heltecV3PositionPageRefresh()
{
    if (screen && screen->isScreenOn())
        screen->runNow();
}

bool heltecV3PositionPageRecentlyVisible()
{
    const uint32_t last = lastPositionPageDrawMs;
    return last != 0 && (uint32_t)(millis() - last) <= 1500UL;
}

#else

bool heltecV3PositionPageEnabled()
{
    return false;
}
void heltecV3PositionPageDrawFrame(OLEDDisplay *, OLEDDisplayUiState *, int16_t, int16_t) {}
void heltecV3PositionPageRequestFocus() {}
void heltecV3PositionPageRefresh() {}
bool heltecV3PositionPageRecentlyVisible()
{
    return false;
}

#endif
