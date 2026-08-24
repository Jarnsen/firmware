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

namespace {
volatile uint32_t lastPositionPageDrawMs = 0;

bool v3PositionUiRoleEnabled() {
  return config.device.role ==
             meshtastic_Config_DeviceConfig_Role_ROUTER_LATE ||
         config.device.role == meshtastic_Config_DeviceConfig_Role_REPEATER;
}

char latitudeBand(double latitude) {
  static constexpr char bands[] = "CDEFGHJKLMNPQRSTUVWX";
  if (latitude < -80.0 || latitude > 84.0)
    return 0;
  int index = static_cast<int>(floor((latitude + 80.0) / 8.0));
  index = std::max(0, std::min(19, index));
  return bands[index];
}

int utmZone(double latitude, double longitude) {
  int zone = static_cast<int>(floor((longitude + 180.0) / 6.0)) + 1;
  zone = std::max(1, std::min(60, zone));

  if (latitude >= 56.0 && latitude < 64.0 && longitude >= 3.0 &&
      longitude < 12.0)
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

// 8-digit MGRS (10 m display resolution). Internal position/distance logic
// keeps the full latitude/longitude precision; only the OLED presentation is
// rounded down to the normal 10 m MGRS grid precision.
bool latLonToMgrs8(int32_t latitudeI, int32_t longitudeI, char *out,
                   size_t outSize) {
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
      a * ((1.0 - eccSquared / 4.0 - 3.0 * eccSquared * eccSquared / 64.0 -
            5.0 * eccSquared * eccSquared * eccSquared / 256.0) *
               latRad -
           (3.0 * eccSquared / 8.0 + 3.0 * eccSquared * eccSquared / 32.0 +
            45.0 * eccSquared * eccSquared * eccSquared / 1024.0) *
               sin(2.0 * latRad) +
           (15.0 * eccSquared * eccSquared / 256.0 +
            45.0 * eccSquared * eccSquared * eccSquared / 1024.0) *
               sin(4.0 * latRad) -
           (35.0 * eccSquared * eccSquared * eccSquared / 3072.0) *
               sin(6.0 * latRad));

  const double easting =
      k0 * n *
          (aa + (1.0 - t + c) * aa * aa * aa / 6.0 +
           (5.0 - 18.0 * t + t * t + 72.0 * c - 58.0 * eccPrimeSquared) * aa *
               aa * aa * aa * aa / 120.0) +
      500000.0;

  double northing =
      k0 *
      (m +
       n * tanLat *
           (aa * aa / 2.0 +
            (5.0 - t + 9.0 * c + 4.0 * c * c) * aa * aa * aa * aa / 24.0 +
            (61.0 - 58.0 * t + t * t + 600.0 * c - 330.0 * eccPrimeSquared) *
                aa * aa * aa * aa * aa * aa / 720.0));
  if (latitude < 0.0)
    northing += 10000000.0;

  static constexpr const char *eastingSets[] = {"ABCDEFGH", "JKLMNPQR",
                                                "STUVWXYZ"};
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

  snprintf(out, outSize, "%02d%c %c%c %04d %04d", zone, band, eLetter, nLetter,
           eMeters / 10, nMeters / 10);
  return true;
}

void drawCenteredLine(OLEDDisplay *display, int16_t x, int16_t y,
                      const char *text) {
  display->setTextAlignment(TEXT_ALIGN_CENTER);
  display->setFont(FONT_SMALL);
  display->drawString(display->getWidth() / 2 + x, y, text ? text : "");
}

class HeltecV3PositionModule : public MeshModule {
public:
  HeltecV3PositionModule() : MeshModule("V3 Position") {}

  bool wantPacket(const meshtastic_MeshPacket *) override { return false; }
  // Screen.cpp inserts this V3 page explicitly as the first normal frame.
  // Returning false here prevents a duplicate module copy at the end.
  bool wantUIFrame() override { return false; }
  void requestPositionFocus() { requestFocus(); }

  void drawFrame(OLEDDisplay *display, OLEDDisplayUiState *uiState, int16_t x,
                 int16_t y) override {
    if (!display)
      return;

    lastPositionPageDrawMs = millis() ? millis() : 1;

    HeltecV3PositionUiState state;
    heltecV3GetPositionUiState(state);

    char oldMgrs[28] = "---";
    char newMgrs[28] = "---";
    if (state.haveSavedPosition)
      latLonToMgrs8(state.savedLatitudeI, state.savedLongitudeI, oldMgrs,
                    sizeof(oldMgrs));
    if (state.havePhonePosition)
      latLonToMgrs8(state.phoneLatitudeI, state.phoneLongitudeI, newMgrs,
                    sizeof(newMgrs));

    char line[64] = {};
    const int16_t center = display->getWidth() / 2 + x;
    const int left = x + 2;
    const int right = x + display->getWidth() - 2;

    auto splitMgrs = [](const char *mgrs, char *prefix, size_t prefixSize,
                        char *digits, size_t digitsSize) {
      char zoneBand[8] = {};
      char grid[4] = {};
      char east[8] = {};
      char north[8] = {};
      if (!mgrs ||
          sscanf(mgrs, "%7s %3s %7s %7s", zoneBand, grid, east, north) != 4) {
        snprintf(prefix, prefixSize, "---");
        snprintf(digits, digitsSize, "---");
        return false;
      }
      snprintf(prefix, prefixSize, "%s %s", zoneBand, grid);
      snprintf(digits, digitsSize, "%s %s", east, north);
      return true;
    };

    char oldPrefix[16] = "---";
    char oldDigits[20] = "---";
    char newPrefix[16] = "---";
    char newDigits[20] = "---";
    const bool oldMgrsValid = state.haveSavedPosition &&
                              splitMgrs(oldMgrs, oldPrefix, sizeof(oldPrefix),
                                        oldDigits, sizeof(oldDigits));
    const bool newMgrsValid = state.havePhonePosition &&
                              splitMgrs(newMgrs, newPrefix, sizeof(newPrefix),
                                        newDigits, sizeof(newDigits));
    const bool goodPhone = state.havePhonePosition && state.phoneFresh &&
                           state.phoneAccurate && newMgrsValid;
    const unsigned accM = (unsigned)(state.accuracyMm / 1000UL);

    display->clear();
    graphics::drawCommonHeader(display, x, y, "Position");
    display->setColor(WHITE);
    const int *textPos = graphics::getTextPositions(display);

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

    if (state.lastSaveValid && state.lastSaveAgeMs <= 3000U && oldMgrsValid) {
      drawPair(textPos[1], "POSITION SAVED",
               state.lastSaveAutomatic ? "AUTO" : "MANUAL");
      display->setTextAlignment(TEXT_ALIGN_CENTER);
      display->setFont(FONT_SMALL);
      display->drawString(center, textPos[2], oldPrefix);
      display->setFont(FONT_MEDIUM);
      display->drawString(center, textPos[3], oldDigits);
      snprintf(line, sizeof(line), "DIFF %um%s",
               (unsigned)state.lastSavedDifferenceM,
               state.lastSaveMeshSent ? "  SENT" : "");
      display->setFont(FONT_SMALL);
      display->drawString(center, textPos[4], line);
      finishPage();
      return;
    }

    const bool compareMode =
        goodPhone && oldMgrsValid && state.differenceM > state.ignoreDistanceM;
    if (compareMode) {
      snprintf(line, sizeof(line), "OLD %s %s", oldPrefix, oldDigits);
      display->setTextAlignment(TEXT_ALIGN_CENTER);
      display->setFont(FONT_SMALL);
      display->drawString(center, textPos[1], line);
      snprintf(line, sizeof(line), "NEW %s %s", newPrefix, newDigits);
      display->drawString(center, textPos[2], line);
      char l[28] = {};
      char r[28] = {};
      snprintf(l, sizeof(l), "DIFF:%um", (unsigned)state.differenceM);
      snprintf(r, sizeof(r), "ACC:%um", accM);
      drawPair(textPos[3], l, r);
      if (state.differenceM > state.autoDistanceM)
        snprintf(line, sizeof(line), "AUTO %u/%u   HOLD:SAVE",
                 (unsigned)state.autoConfirmCount,
                 (unsigned)state.autoConfirmRequired);
      else
        snprintf(line, sizeof(line), "POSITION CHECK   HOLD:SAVE");
      display->setTextAlignment(TEXT_ALIGN_CENTER);
      display->drawString(center, textPos[4], line);
      finishPage();
      return;
    }

    if (!oldMgrsValid && goodPhone) {
      display->setTextAlignment(TEXT_ALIGN_CENTER);
      display->setFont(FONT_SMALL);
      display->drawString(center, textPos[1], "NEW POSITION");
      display->drawString(center, textPos[2], newPrefix);
      display->setFont(FONT_MEDIUM);
      display->drawString(center, textPos[3], newDigits);
      snprintf(line, sizeof(line), "ACC %um   HOLD:SAVE", accM);
      display->setFont(FONT_SMALL);
      display->drawString(center, textPos[4], line);
      finishPage();
      return;
    }

    if (!oldMgrsValid) {
      display->setTextAlignment(TEXT_ALIGN_CENTER);
      display->setFont(FONT_MEDIUM);
      display->drawString(center, textPos[2], "NO POSITION");
      display->setFont(FONT_SMALL);
      display->drawString(center, textPos[4],
                          state.havePhonePosition ? "PHONE GPS WAIT"
                                                  : "WAIT FOR PHONE GPS");
      finishPage();
      return;
    }

    display->setTextAlignment(TEXT_ALIGN_CENTER);
    display->setFont(FONT_SMALL);
    display->drawString(center, textPos[1], oldPrefix);
    display->setFont(FONT_MEDIUM);
    display->drawString(center, textPos[2], oldDigits);
    display->setFont(FONT_SMALL);

    if (!state.havePhonePosition) {
      snprintf(line, sizeof(line), "FIXED POSITION");
    } else if (!state.phoneFresh) {
      snprintf(line, sizeof(line), "GPS AGE %us",
               state.phoneAgeSecs == UINT32_MAX ? 9999U
                                                : (unsigned)state.phoneAgeSecs);
    } else if (!state.phoneAccurate) {
      snprintf(line, sizeof(line), "GPS ACC %um - WAIT", accM);
    } else {
      snprintf(line, sizeof(line), "POSITION OK  %um  ACC %um",
               (unsigned)state.differenceM, accM);
    }
    display->drawString(center, textPos[4], line);
    finishPage();
  }
};

HeltecV3PositionModule heltecV3PositionModule;
} // namespace

bool heltecV3PositionPageEnabled() { return v3PositionUiRoleEnabled(); }

void heltecV3PositionPageDrawFrame(OLEDDisplay *display,
                                   OLEDDisplayUiState *state, int16_t x,
                                   int16_t y) {
  heltecV3PositionModule.drawFrame(display, state, x, y);
}

void heltecV3PositionPageRequestFocus() {
  if (!v3PositionUiRoleEnabled())
    return;
  if (screen) {
    // On the V3, FOCUS_DEFAULT points to our explicitly inserted first
    // position frame. No module-focus request or end-of-list jump needed.
    screen->setFrames(graphics::Screen::FOCUS_DEFAULT);
    screen->runNow();
  }
}

void heltecV3PositionPageRefresh() {
  if (screen && screen->isScreenOn())
    screen->runNow();
}

bool heltecV3PositionPageRecentlyVisible() {
  const uint32_t last = lastPositionPageDrawMs;
  return last != 0 && (uint32_t)(millis() - last) <= 1500UL;
}

#else

bool heltecV3PositionPageEnabled() { return false; }
void heltecV3PositionPageDrawFrame(OLEDDisplay *, OLEDDisplayUiState *, int16_t,
                                   int16_t) {}
void heltecV3PositionPageRequestFocus() {}
void heltecV3PositionPageRefresh() {}
bool heltecV3PositionPageRecentlyVisible() { return false; }

#endif
