#include "TacticalMapModule.h"

#if defined(HAS_TACTICAL_MAP) && HAS_TACTICAL_MAP && HAS_SCREEN && !MESHTASTIC_EXCLUDE_GPS && !MESHTASTIC_EXCLUDE_POSITIONDB

#include "GPSStatus.h"
#include "NodeDB.h"
#include "TacticalMapMath.h"
#include "TacticalMapPageModule.h"
#include "TacticalMenuModule.h"
#include "TacticalNavPageModule.h"
#include "graphics/ScreenFonts.h"
#include "graphics/SharedUIDisplay.h"
#include "graphics/TacticalDisplayMirrorThread.h"

#include <cstdio>

TacticalMapModule::TacticalMapModule() : MeshModule("tactical-me")
{
    // MeshModule registers this ME page first. Add NAV and MAP afterwards so
    // the tactical pages appear in the field-use order: ME, NAV, MAP.
    new TacticalNavPageModule();
    new TacticalMapPageModule();
    new TacticalMenuModule();
#if defined(HAS_TACTICAL_DISPLAY_MIRROR) && HAS_TACTICAL_DISPLAY_MIRROR
    new graphics::TacticalDisplayMirrorThread();
#endif
}

bool TacticalMapModule::wantUIFrame()
{
    return config.device.role == meshtastic_Config_DeviceConfig_Role_TRACKER ||
           config.device.role == meshtastic_Config_DeviceConfig_Role_TAK_TRACKER;
}

void TacticalMapModule::drawFrame(OLEDDisplay *display, OLEDDisplayUiState *, int16_t x, int16_t y)
{
    if (!display || !nodeDB)
        return;

    display->clear();
    display->setTextAlignment(TEXT_ALIGN_LEFT);
    display->setFont(FONT_SMALL);
    graphics::drawCommonHeader(display, x, y, "ME / OWN POSITION");

    meshtastic_PositionLite ownPosition;
    const bool haveOwnPosition = nodeDB->copyNodePosition(nodeDB->getNodeNum(), ownPosition) &&
                                 (ownPosition.latitude_i != 0 || ownPosition.longitude_i != 0) &&
                                 TacticalMapMath::isValidCoordinate(ownPosition.latitude_i, ownPosition.longitude_i);

    if (!haveOwnPosition) {
        display->setFont(FONT_LARGE);
        display->drawString(x + 5, y + 23, "NO FIX");
        display->setFont(FONT_SMALL);
        display->drawString(x + 5, y + 57, "Waiting for own GPS position");
        return;
    }

    char mgrs[24];
    if (!TacticalMapMath::formatMgrs10(ownPosition.latitude_i, ownPosition.longitude_i, mgrs, sizeof(mgrs))) {
        display->drawString(x + 5, y + 30, "MGRS unavailable");
        return;
    }

    unsigned zone = 0;
    char band = '-';
    char squareEast = '-';
    char squareNorth = '-';
    unsigned long easting = 0;
    unsigned long northing = 0;
    if (sscanf(mgrs, "%u%c %c%c %lu %lu", &zone, &band, &squareEast, &squareNorth, &easting, &northing) != 6) {
        display->setFont(FONT_MEDIUM);
        display->drawString(x + 3, y + 27, mgrs);
        return;
    }

    char gridZone[12];
    char digits[20];
    snprintf(gridZone, sizeof(gridZone), "%u%c %c%c", zone, band, squareEast, squareNorth);
    snprintf(digits, sizeof(digits), "%05lu %05lu", easting, northing);

    display->setTextAlignment(TEXT_ALIGN_CENTER);
    display->setFont(FONT_LARGE);
    display->drawString(x + display->getWidth() / 2, y + 14, gridZone);
    display->setFont(FONT_MEDIUM);
    display->drawString(x + display->getWidth() / 2, y + 40, digits);
    if (gpsStatus) {
        char status[40];
        snprintf(status, sizeof(status), "%s S%lu D%.1f %ldm", gpsStatus->getHasLock() ? "3D" : "NO",
                 static_cast<unsigned long>(gpsStatus->getNumSatellites()), gpsStatus->getDOP() / 100.0f,
                 static_cast<long>(gpsStatus->getAltitude()));
        display->setFont(FONT_SMALL);
        display->drawString(x + display->getWidth() / 2, y + 64, status);
    }
    display->setTextAlignment(TEXT_ALIGN_LEFT);
}

#endif
