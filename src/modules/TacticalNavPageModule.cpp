#include "TacticalNavPageModule.h"

#if defined(HAS_TACTICAL_MAP) && HAS_TACTICAL_MAP && HAS_SCREEN && !MESHTASTIC_EXCLUDE_GPS && !MESHTASTIC_EXCLUDE_POSITIONDB

#include "NodeDB.h"
#include "TacticalMapMath.h"
#include "gps/RTC.h"
#include "graphics/ScreenFonts.h"
#include "graphics/SharedUIDisplay.h"
#include "graphics/draw/UIRenderer.h"

#include <cmath>
#include <cstdio>

bool TacticalNavPageModule::wantUIFrame()
{
    return config.device.role == meshtastic_Config_DeviceConfig_Role_TRACKER ||
           config.device.role == meshtastic_Config_DeviceConfig_Role_TAK_TRACKER;
}

NodeNum TacticalNavPageModule::selectNewestPositionedNode() const
{
    if (!nodeDB)
        return 0;

    const NodeNum ownNode = nodeDB->getNodeNum();
    const std::vector<NodeNum> candidates = nodeDB->snapshotPositionNodeNums(ownNode);
    NodeNum newestNode = 0;
    uint32_t newestTime = 0;
    for (const NodeNum candidate : candidates) {
        meshtastic_PositionLite position;
        if (!nodeDB->copyNodePosition(candidate, position) || (position.latitude_i == 0 && position.longitude_i == 0) ||
            !TacticalMapMath::isValidCoordinate(position.latitude_i, position.longitude_i))
            continue;

        const uint32_t candidateTime = position.time ? position.time : nodeDB->hotNodeLastHeard(candidate);
        if (!newestNode || candidateTime > newestTime) {
            newestNode = candidate;
            newestTime = candidateTime;
        }
    }
    return newestNode;
}

bool TacticalNavPageModule::copyTarget(meshtastic_PositionLite &position, char *name, size_t nameSize)
{
    if (!nodeDB || !name || nameSize == 0)
        return false;

    const NodeNum favoriteNode = graphics::UIRenderer::currentFavoriteNodeNum;
    if (favoriteNode && favoriteNode != nodeDB->getNodeNum()) {
        meshtastic_PositionLite favoritePosition;
        if (nodeDB->copyNodePosition(favoriteNode, favoritePosition) &&
            (favoritePosition.latitude_i != 0 || favoritePosition.longitude_i != 0) &&
            TacticalMapMath::isValidCoordinate(favoritePosition.latitude_i, favoritePosition.longitude_i)) {
            selectedNode = favoriteNode;
        }
    }

    if (!selectedNode || !nodeDB->copyNodePosition(selectedNode, position) ||
        (position.latitude_i == 0 && position.longitude_i == 0) ||
        !TacticalMapMath::isValidCoordinate(position.latitude_i, position.longitude_i)) {
        selectedNode = selectNewestPositionedNode();
        if (!selectedNode || !nodeDB->copyNodePosition(selectedNode, position))
            return false;
    }

    const meshtastic_NodeInfoLite *node = nodeDB->getMeshNode(selectedNode);
    if (nodeInfoLiteHasUser(node) && node->short_name[0])
        snprintf(name, nameSize, "%s", node->short_name);
    else
        snprintf(name, nameSize, "!%04lx", static_cast<unsigned long>(selectedNode & 0xffffU));
    return true;
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
    if (!copyTarget(targetPosition, targetName, sizeof(targetName))) {
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

    display->setFont(FONT_SMALL);
    snprintf(line, sizeof(line), "%s  %s", targetName, TacticalMapMath::formatDistance(distance, value, sizeof(value)));
    display->drawString(x + 4, y + 47, line);
    snprintf(line, sizeof(line), "AGE %s", haveAge ? TacticalMapMath::formatPositionAge(age, value, sizeof(value)) : "--");
    display->drawString(x + 4, y + 62, line);
}

#endif
