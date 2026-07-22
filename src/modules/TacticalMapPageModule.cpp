#include "TacticalMapPageModule.h"

#if defined(HAS_TACTICAL_MAP) && HAS_TACTICAL_MAP && HAS_SCREEN && !MESHTASTIC_EXCLUDE_GPS && !MESHTASTIC_EXCLUDE_POSITIONDB

#include "JTMapRenderer.h"
#include "NodeDB.h"
#include "TacticalMapMath.h"
#include "graphics/ScreenFonts.h"
#include "graphics/SharedUIDisplay.h"
#include "graphics/draw/UIRenderer.h"

#include <cstdio>

namespace
{
void drawCross(OLEDDisplay *display, int16_t x, int16_t y)
{
    display->drawLine(x - 3, y, x + 3, y);
    display->drawLine(x, y - 3, x, y + 3);
    display->drawCircle(x, y, 2);
}

void drawTarget(OLEDDisplay *display, int16_t x, int16_t y)
{
    display->drawCircle(x, y, 3);
    display->setPixel(x, y);
}
} // namespace

bool TacticalMapPageModule::wantUIFrame()
{
    return config.device.role == meshtastic_Config_DeviceConfig_Role_TRACKER ||
           config.device.role == meshtastic_Config_DeviceConfig_Role_TAK_TRACKER;
}

NodeNum TacticalMapPageModule::selectNewestPositionedNode() const
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

bool TacticalMapPageModule::copyTarget(meshtastic_PositionLite &position, char *name, size_t nameSize)
{
    if (!nodeDB || !name || nameSize == 0)
        return false;

    const NodeNum favoriteNode = graphics::UIRenderer::currentFavoriteNodeNum;
    if (favoriteNode && favoriteNode != nodeDB->getNodeNum())
        selectedNode = favoriteNode;

    if (!selectedNode || !nodeDB->copyNodePosition(selectedNode, position) ||
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

void TacticalMapPageModule::drawFrame(OLEDDisplay *display, OLEDDisplayUiState *, int16_t x, int16_t y)
{
    if (!display || !nodeDB)
        return;

    display->clear();
    display->setTextAlignment(TEXT_ALIGN_LEFT);
    display->setFont(FONT_SMALL);
    graphics::drawCommonHeader(display, x, y, "MAP NIGHT");

    const int16_t mapLeft = x + 1;
    const int16_t mapTop = y + FONT_HEIGHT_SMALL + 2;
    const int16_t mapWidth = display->getWidth() - 2;
    const int16_t mapHeight = display->getHeight() - mapTop - 1;

    display->drawRect(mapLeft, mapTop, mapWidth, mapHeight);
    JTMapRenderer::Bounds bounds;
    const bool haveMap = JTMapRenderer::draw(display, JTMapRenderer::DEFAULT_MAP_PATH, mapLeft + 1, mapTop + 1,
                                               mapWidth - 2, mapHeight - 2, &bounds,
                                               JTMapRenderer::Theme::TACTICAL_NIGHT);
    if (!haveMap) {
        display->drawString(mapLeft + 18, mapTop + 15, "NO JTMAP");
        display->drawString(mapLeft + 8, mapTop + 29, "Install Friesenheim");
        return;
    }

    display->drawString(mapLeft + 3, mapTop + 1, "N");
    display->drawLine(mapLeft + 6, mapTop + 12, mapLeft + 6, mapTop + 5);
    display->drawLine(mapLeft + 6, mapTop + 5, mapLeft + 3, mapTop + 9);
    display->drawLine(mapLeft + 6, mapTop + 5, mapLeft + 9, mapTop + 9);

    meshtastic_PositionLite ownPosition;
    const bool haveOwn = nodeDB->copyNodePosition(nodeDB->getNodeNum(), ownPosition) &&
                          TacticalMapMath::isValidCoordinate(ownPosition.latitude_i, ownPosition.longitude_i);
    const bool ownInside = haveOwn && JTMapRenderer::contains(bounds, ownPosition.latitude_i, ownPosition.longitude_i);
    int16_t ownX = 0;
    int16_t ownY = 0;
    if (ownInside) {
        ownX = JTMapRenderer::projectX(bounds, ownPosition.longitude_i, mapLeft + 1, mapWidth - 2);
        ownY = JTMapRenderer::projectY(bounds, ownPosition.latitude_i, mapTop + 1, mapHeight - 2);
    } else if (!haveOwn) {
        display->drawString(mapLeft + 28, mapTop + 1, "NO GPS");
    } else {
        display->drawString(mapLeft + 25, mapTop + 1, "OUTSIDE");
    }

    meshtastic_PositionLite targetPosition;
    char targetName[12];
    const bool haveTarget = copyTarget(targetPosition, targetName, sizeof(targetName));
    const bool targetInside = haveTarget && JTMapRenderer::contains(bounds, targetPosition.latitude_i, targetPosition.longitude_i);
    if (targetInside) {
        const int16_t targetX = JTMapRenderer::projectX(bounds, targetPosition.longitude_i, mapLeft + 1, mapWidth - 2);
        const int16_t targetY = JTMapRenderer::projectY(bounds, targetPosition.latitude_i, mapTop + 1, mapHeight - 2);
        if (ownInside)
            display->drawLine(ownX, ownY, targetX, targetY);
        drawTarget(display, targetX, targetY);
        display->drawString(mapLeft + mapWidth - 34, mapTop + 1, targetName);
    }

    if (ownInside)
        drawCross(display, ownX, ownY);
}

#endif