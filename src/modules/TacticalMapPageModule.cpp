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
#include <array>
#include <cstdio>
#include <cstring>

namespace
{
constexpr size_t MAX_MONO_FRAME_BYTES = 1024;
constexpr size_t TRACK_POINTS = 24;
constexpr float TRACK_MIN_DISTANCE_METERS = 12.0f;

struct TrackPoint {
    int32_t latitudeI = 0;
    int32_t longitudeI = 0;
    bool valid = false;
};

std::array<uint8_t, MAX_MONO_FRAME_BYTES> cachedBase{};
size_t cachedBaseBytes = 0;
bool cachedBaseValid = false;
uint8_t cachedZoom = 0xff;
int32_t cachedCenterLatitudeI = 0;
int32_t cachedCenterLongitudeI = 0;
JTMapRenderer::Bounds cachedViewport;
std::array<TrackPoint, TRACK_POINTS> track{};
size_t trackHead = 0;
size_t trackCount = 0;

void registerMapRegion(int16_t x, int16_t y, int16_t width, int16_t height, uint16_t color)
{
#if GRAPHICS_TFT_COLORING_ENABLED
    graphics::registerTFTColorRegionDirect(x, y, width, height, color, graphics::TFTPalette::Black);
#else
    (void)x; (void)y; (void)width; (void)height; (void)color;
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

uint8_t chooseZoom(bool haveOwn, bool haveTarget, const meshtastic_PositionLite &ownPosition,
                   const meshtastic_PositionLite &targetPosition)
{
    if (!haveOwn)
        return 0;
    if (!haveTarget)
        return 2;
    const float distance = TacticalMapMath::distanceMeters(ownPosition.latitude_i, ownPosition.longitude_i,
                                                           targetPosition.latitude_i, targetPosition.longitude_i);
    if (distance < 250.0f)
        return 3;
    if (distance < 1000.0f)
        return 2;
    if (distance < 4000.0f)
        return 1;
    return 0;
}

void appendTrackPoint(const meshtastic_PositionLite &position)
{
    if (!TacticalMapMath::isValidCoordinate(position.latitude_i, position.longitude_i))
        return;
    if (trackCount) {
        const size_t previous = (trackHead + TRACK_POINTS - 1) % TRACK_POINTS;
        if (track[previous].valid &&
            TacticalMapMath::distanceMeters(track[previous].latitudeI, track[previous].longitudeI,
                                            position.latitude_i, position.longitude_i) < TRACK_MIN_DISTANCE_METERS)
            return;
    }
    track[trackHead] = {position.latitude_i, position.longitude_i, true};
    trackHead = (trackHead + 1) % TRACK_POINTS;
    trackCount = std::min(trackCount + 1, TRACK_POINTS);
}

void drawTrack(OLEDDisplay *display, const JTMapRenderer::Bounds &bounds, int16_t left, int16_t top, int16_t width, int16_t height)
{
    bool havePrevious = false;
    int16_t previousX = 0, previousY = 0;
    const size_t first = (trackHead + TRACK_POINTS - trackCount) % TRACK_POINTS;
    for (size_t i = 0; i < trackCount; ++i) {
        const TrackPoint &point = track[(first + i) % TRACK_POINTS];
        if (!point.valid || !JTMapRenderer::contains(bounds, point.latitudeI, point.longitudeI)) {
            havePrevious = false;
            continue;
        }
        const int16_t px = JTMapRenderer::projectX(bounds, point.longitudeI, left, width);
        const int16_t py = JTMapRenderer::projectY(bounds, point.latitudeI, top, height);
        if (havePrevious)
            display->drawLine(previousX, previousY, px, py);
        previousX = px;
        previousY = py;
        havePrevious = true;
    }
    registerMapRegion(left, top, width, height, graphics::TFTPalette::LightGray);
}

bool baseCacheMatches(uint8_t zoom, int32_t latitudeI, int32_t longitudeI)
{
    if (!cachedBaseValid || cachedZoom != zoom)
        return false;
    return TacticalMapMath::distanceMeters(cachedCenterLatitudeI, cachedCenterLongitudeI, latitudeI, longitudeI) < 40.0f;
}
} // namespace

bool TacticalMapPageModule::wantUIFrame()
{
    return config.device.role == meshtastic_Config_DeviceConfig_Role_TRACKER ||
           config.device.role == meshtastic_Config_DeviceConfig_Role_TAK_TRACKER;
}

void TacticalMapPageModule::drawFrame(OLEDDisplay *display, OLEDDisplayUiState *, int16_t x, int16_t y)
{
    if (!display || !nodeDB || !display->buffer)
        return;

    meshtastic_PositionLite ownPosition{};
    const bool haveOwn = nodeDB->copyNodePosition(nodeDB->getNodeNum(), ownPosition) &&
                         TacticalMapMath::isValidCoordinate(ownPosition.latitude_i, ownPosition.longitude_i);
    if (haveOwn)
        appendTrackPoint(ownPosition);

    meshtastic_PositionLite targetPosition{};
    char targetName[12]{};
    const bool haveTarget = TacticalTargetManager::instance().copyActiveTarget(targetPosition, targetName, sizeof(targetName));
    const uint8_t zoom = chooseZoom(haveOwn, haveTarget, ownPosition, targetPosition);

    display->clear();
    display->setTextAlignment(TEXT_ALIGN_LEFT);
    display->setFont(FONT_SMALL);
    char title[16];
    snprintf(title, sizeof(title), "MAP Z%u", static_cast<unsigned>(zoom + 1));
    graphics::drawCommonHeader(display, x, y, title);

    const int16_t mapLeft = x + 1;
    const int16_t mapTop = y + FONT_HEIGHT_SMALL + 2;
    const int16_t mapWidth = display->getWidth() - 2;
    const int16_t mapHeight = display->getHeight() - mapTop - 1;
    if (mapWidth < 4 || mapHeight < 4)
        return;

    const size_t frameBytes = static_cast<size_t>(display->getWidth()) * display->getHeight() / 8;
    const bool stableFrame = x == 0 && y == 0 && frameBytes <= cachedBase.size();
    const int32_t centerLat = haveOwn ? ownPosition.latitude_i : 495000000;
    const int32_t centerLon = haveOwn ? ownPosition.longitude_i : 84000000;

    if (stableFrame && baseCacheMatches(zoom, centerLat, centerLon) && cachedBaseBytes == frameBytes) {
        memcpy(display->buffer, cachedBase.data(), frameBytes);
    } else {
        display->drawRect(mapLeft, mapTop, mapWidth, mapHeight);
        const bool haveMap = JTMapRenderer::drawViewport(display, JTMapRenderer::DEFAULT_MAP_PATH, mapLeft + 1, mapTop + 1,
                                                         mapWidth - 2, mapHeight - 2, centerLat, centerLon, zoom,
                                                         &cachedViewport, JTMapRenderer::Theme::HIGH_CONTRAST);
        if (!haveMap) {
            display->drawString(mapLeft + 18, mapTop + 15, "NO JTMAP");
            display->drawString(mapLeft + 8, mapTop + 29, "Install Friesenheim");
            registerMapRegion(mapLeft + 6, mapTop + 12, mapWidth - 12, 32, graphics::TFTPalette::Orange);
            cachedBaseValid = false;
            return;
        }
        display->drawString(mapLeft + 3, mapTop + 1, "N");
        display->drawLine(mapLeft + 6, mapTop + 12, mapLeft + 6, mapTop + 5);
        display->drawLine(mapLeft + 6, mapTop + 5, mapLeft + 3, mapTop + 9);
        display->drawLine(mapLeft + 6, mapTop + 5, mapLeft + 9, mapTop + 9);
        if (stableFrame) {
            memcpy(cachedBase.data(), display->buffer, frameBytes);
            cachedBaseBytes = frameBytes;
            cachedBaseValid = true;
            cachedZoom = zoom;
            cachedCenterLatitudeI = centerLat;
            cachedCenterLongitudeI = centerLon;
        }
    }

    registerMapRegion(mapLeft, mapTop, mapWidth, mapHeight, graphics::TFTPalette::LightGray);
    registerMapRegion(mapLeft + 1, mapTop, 12, 14, graphics::TFTPalette::Cyan);

    drawTrack(display, cachedViewport, mapLeft + 1, mapTop + 1, mapWidth - 2, mapHeight - 2);

    const bool ownInside = haveOwn && JTMapRenderer::contains(cachedViewport, ownPosition.latitude_i, ownPosition.longitude_i);
    int16_t ownX = 0, ownY = 0;
    if (ownInside) {
        ownX = JTMapRenderer::projectX(cachedViewport, ownPosition.longitude_i, mapLeft + 1, mapWidth - 2);
        ownY = JTMapRenderer::projectY(cachedViewport, ownPosition.latitude_i, mapTop + 1, mapHeight - 2);
    }

    const bool targetInside = haveTarget && JTMapRenderer::contains(cachedViewport, targetPosition.latitude_i,
                                                                    targetPosition.longitude_i);
    if (targetInside) {
        const int16_t targetX = JTMapRenderer::projectX(cachedViewport, targetPosition.longitude_i, mapLeft + 1, mapWidth - 2);
        const int16_t targetY = JTMapRenderer::projectY(cachedViewport, targetPosition.latitude_i, mapTop + 1, mapHeight - 2);
        if (ownInside)
            display->drawLine(ownX, ownY, targetX, targetY);
        drawTarget(display, targetX, targetY);
        display->drawString(mapLeft + mapWidth - 34, mapTop + 1, targetName);
        registerMapRegion(mapLeft + mapWidth - 36, mapTop, 36, FONT_HEIGHT_SMALL + 2, graphics::TFTPalette::Red);
    }

    if (ownInside)
        drawCross(display, ownX, ownY);

    char mgrs[24];
    if (haveOwn && TacticalMapMath::formatMgrs10(ownPosition.latitude_i, ownPosition.longitude_i, mgrs, sizeof(mgrs))) {
        display->setFont(FONT_SMALL);
        display->drawString(mapLeft + 2, mapTop + mapHeight - FONT_HEIGHT_SMALL, mgrs);
        registerMapRegion(mapLeft, mapTop + mapHeight - FONT_HEIGHT_SMALL - 1, mapWidth, FONT_HEIGHT_SMALL + 2,
                          graphics::TFTPalette::Cyan);
    }
}

#endif