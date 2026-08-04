#include "TacticalMapPageModule.h"

#if defined(HAS_TACTICAL_MAP) && HAS_TACTICAL_MAP && HAS_SCREEN && !MESHTASTIC_EXCLUDE_GPS && !MESHTASTIC_EXCLUDE_POSITIONDB

#include "JTMapRenderer.h"
#include "NodeDB.h"
#include "TacticalMapMath.h"
#include "TacticalTargetManager.h"
#include "graphics/ScreenFonts.h"
#include "graphics/SharedUIDisplay.h"

#include <algorithm>
#include <cstdlib>
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

void TacticalMapPageModule::drawFrame(OLEDDisplay *display, OLEDDisplayUiState *, int16_t x, int16_t y)
{
    if (!display || !nodeDB)
        return;

    // Keep the device-side map page strictly monochrome. Building the optional
    // 128x64 RGB565 mirror frame here allocated and copied several large
    // vectors on every animation frame, even when no mirror client was open.
    // The normal display mirror can still transmit the final OLED buffer.
    display->clear();
    display->setTextAlignment(TEXT_ALIGN_LEFT);
    display->setFont(FONT_SMALL);
    graphics::drawCommonHeader(display, x, y, "MAP NIGHT");

    const int16_t mapLeft = x + 1;
    const int16_t mapTop = y + FONT_HEIGHT_SMALL + 2;
    const int16_t mapWidth = display->getWidth() - 2;
    const int16_t mapHeight = display->getHeight() - mapTop - 1;

    if (mapWidth < 4 || mapHeight < 4)
        return;

    display->drawRect(mapLeft, mapTop, mapWidth, mapHeight);
    JTMapRenderer::Bounds bounds;
    const bool haveMap = JTMapRenderer::draw(display, JTMapRenderer::DEFAULT_MAP_PATH, mapLeft + 1, mapTop + 1, mapWidth - 2,
                                             mapHeight - 2, &bounds, JTMapRenderer::Theme::HIGH_CONTRAST);
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
    const bool haveTarget = TacticalTargetManager::instance().copyActiveTarget(targetPosition, targetName, sizeof(targetName));
    const bool targetInside =
        haveTarget && JTMapRenderer::contains(bounds, targetPosition.latitude_i, targetPosition.longitude_i);
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
