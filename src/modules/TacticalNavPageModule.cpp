#include "TacticalNavPageModule.h"

#if defined(HAS_TACTICAL_MAP) && HAS_TACTICAL_MAP && HAS_SCREEN && !MESHTASTIC_EXCLUDE_GPS && !MESHTASTIC_EXCLUDE_POSITIONDB

#include "NodeDB.h"
#include "TacticalMapMath.h"
#include "TacticalTargetManager.h"
#include "gps/RTC.h"
#include "graphics/ScreenFonts.h"
#include "graphics/SharedUIDisplay.h"
#include "graphics/draw/CompassRenderer.h"

#include <cmath>
#include <cstdio>

bool TacticalNavPageModule::wantUIFrame()
{
    return config.device.role == meshtastic_Config_DeviceConfig_Role_TRACKER ||
           config.device.role == meshtastic_Config_DeviceConfig_Role_TAK_TRACKER;
}

void TacticalNavPageModule::drawFrame(OLEDDisplay *display, OLEDDisplayUiState *, int16_t x, int16_t y)
{
    if (!display || !nodeDB)
        return;

    display->clear();
    display->setTextAlignment(TEXT_ALIGN_LEFT);
    display->setFont(FONT_SMALL);
    graphics::drawCommonHeader(display, x, y, "TACTICAL NAV");

    meshtastic_PositionLite ownPosition;
    const bool haveOwnPosition = nodeDB->copyNodePosition(nodeDB->getNodeNum(), ownPosition) &&
                                 (ownPosition.latitude_i != 0 || ownPosition.longitude_i != 0) &&
                                 TacticalMapMath::isValidCoordinate(ownPosition.latitude_i, ownPosition.longitude_i);
    if (!haveOwnPosition) {
        display->drawString(x + 4, y + 25, "NO GPS FIX");
        display->drawString(x + 4, y + 42, "Waiting for position");
        return;
    }

    meshtastic_PositionLite targetPosition;
    char targetName[12];
    if (!TacticalTargetManager::instance().copyActiveTarget(targetPosition, targetName, sizeof(targetName))) {
        display->drawString(x + 4, y + 25, "NO TARGET");
        display->drawString(x + 4, y + 42, "Select/favorite a node");
        return;
    }

    const float bearing = TacticalMapMath::bearingDegrees(ownPosition.latitude_i, ownPosition.longitude_i,
                                                          targetPosition.latitude_i, targetPosition.longitude_i);
    const uint16_t mil = TacticalMapMath::degreesToMil(bearing);
    const float distance = TacticalMapMath::distanceMeters(ownPosition.latitude_i, ownPosition.longitude_i,
                                                           targetPosition.latitude_i, targetPosition.longitude_i);
    const uint32_t now = getValidTime(RTCQuality::RTCQualityDevice);
    const bool haveAge = now && targetPosition.time;
    const uint32_t age = haveAge && now > targetPosition.time ? now - targetPosition.time : 0;

    char line[32];
    char value[16];
    display->setFont(FONT_LARGE);
    snprintf(line, sizeof(line), "%04u mil", static_cast<unsigned>(mil));
    display->drawString(x + 4, y + 15, line);
    graphics::CompassRenderer::drawArrowToNode(display, x + display->getWidth() - 20, y + 30, 16, bearing);

    display->setFont(FONT_SMALL);
    snprintf(line, sizeof(line), "%s  %s", targetName, TacticalMapMath::formatDistance(distance, value, sizeof(value)));
    display->drawString(x + 4, y + 47, line);
    snprintf(line, sizeof(line), "AGE %s", haveAge ? TacticalMapMath::formatPositionAge(age, value, sizeof(value)) : "--");
    display->drawString(x + 4, y + 62, line);
}

#endif
