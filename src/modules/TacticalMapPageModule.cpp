#include "TacticalMapPageModule.h"

#if defined(HAS_TACTICAL_MAP) && HAS_TACTICAL_MAP && HAS_SCREEN && !MESHTASTIC_EXCLUDE_GPS && !MESHTASTIC_EXCLUDE_POSITIONDB

#include "JTMapRenderer.h"
#include "NodeDB.h"
#include "TacticalMapMath.h"
#include "TacticalTargetManager.h"
#include "graphics/ScreenFonts.h"
#include "graphics/SharedUIDisplay.h"
#include "graphics/TFTColorRegions.h"
#include "graphics/TFTPalette.h"

#include <algorithm>
#include <cstdlib>
#include <cstdio>

namespace
{
void registerMapRegion(int16_t x, int16_t y, int16_t width, int16_t height, uint16_t color)
{
#if GRAPHICS_TFT_COLORING_ENABLED
    graphics::registerTFTColorRegionDirect(x, y, width, height, color, graphics::TFTPalette::Black);
#else
    (void)x;
    (void)y;
    (void)width;
    (void)height;
    (void)color;
#endif
}

void drawCross(OLEDDisplay *display, int16_t x, int16_t y)
{
    display->drawLine(x - 3, y, x + 3, y);
    display->drawLine(x, y - 3, x, y + 3);
    display->drawCircle(x, y, 2);
    registerMapRegion(x - 4, y - 4, 9, 9, graphics::TFTPalette::Green);
}

void drawTarget(OLEDDisplay *display, int16_t x, int16_t y)
{
    display->drawCircle(x, y, 3);
    display->setPixel(x, y);
    registerMapRegion(x - 4, y - 4, 9, 9, graphics::TFTPalette::Red);
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

    // Keep the map renderer monochrome and add color through the lightweight
    // TFT region mapper. This avoids rebuilding and copying a full RGB565
    // framebuffer during every page-transition animation frame.
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

    // One base region colors all map geometry. Later, smaller regions override
    // this for the north marker, own position and target.
    registerMapRegion(mapLeft, mapTop, mapWidth, mapHeight, graphics::TFTPalette::LightGray);

    if (!haveMap) {
        display->drawString(mapLeft + 18, mapTop + 15, "NO JTMAP");
        display->drawString(mapLeft + 8, mapTop + 29, "Install Friesenheim");
        registerMapRegion(mapLeft + 6, mapTop + 12, mapWidth - 12, 32, graphics::TFTPalette::Orange);
        return;
    }

    display->drawString(mapLeft + 3, mapTop + 1, "N");
    display->drawLine(mapLeft + 6, mapTop + 12, mapLeft + 6, mapTop + 5);
    display->drawLine(mapLeft + 6, mapTop + 5, mapLeft + 3, mapTop + 9);
    display->drawLine(mapLeft + 6, mapTop + 5, mapLeft + 9, mapTop + 9);
    registerMapRegion(mapLeft + 1, mapTop, 12, 14, graphics::TFTPalette::Cyan);

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
        registerMapRegion(mapLeft + 25, mapTop, 48, FONT_HEIGHT_SMALL + 2, graphics::TFTPalette::Orange);
    } else {
        display->drawString(mapLeft + 25, mapTop + 1, "OUTSIDE");
        registerMapRegion(mapLeft + 22, mapTop, 56, FONT_HEIGHT_SMALL + 2, graphics::TFTPalette::Orange);
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
        registerMapRegion(mapLeft + mapWidth - 36, mapTop, 36, FONT_HEIGHT_SMALL + 2, graphics::TFTPalette::Red);
    }

    if (ownInside)
        drawCross(display, ownX, ownY);
}

#endif
