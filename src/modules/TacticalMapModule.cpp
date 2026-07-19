#include "configuration.h"

#if HAS_SCREEN && !MESHTASTIC_EXCLUDE_GPS && !MESHTASTIC_EXCLUDE_POSITIONDB

#include "TacticalMapModule.h"
#include "NodeDB.h"
#include "gps/GeoCoord.h"
#include "gps/RTC.h"
#include "graphics/ScreenFonts.h"
#include <algorithm>
#include <cmath>
#include <cstdio>
#include <cstring>

TacticalMapModule *tacticalMapModule = new TacticalMapModule();

TacticalMapModule::TacticalMapModule() : MeshModule("tactical-map") {}

const meshtastic_NodeInfoLite *TacticalMapModule::findNode(uint32_t nodeNum) const
{
    if (!nodeDB || !nodeDB->meshNodes)
        return nullptr;
    for (const auto &node : *nodeDB->meshNodes) {
        if (node.num == nodeNum)
            return &node;
    }
    return nullptr;
}

uint32_t TacticalMapModule::selectNextPositionedNode(uint32_t ownNode)
{
    if (!nodeDB)
        return 0;

    uint32_t first = 0;
    bool takeNext = selectedNode == 0;
    for (const auto &entry : nodeDB->nodePositions) {
        const uint32_t nodeNum = entry.first;
        const auto &position = entry.second;
        if (nodeNum == ownNode || position.latitude_i == 0 || position.longitude_i == 0)
            continue;
        if (first == 0)
            first = nodeNum;
        if (takeNext)
            return nodeNum;
        if (nodeNum == selectedNode)
            takeNext = true;
    }
    return first;
}

void TacticalMapModule::formatMgrs10(int32_t latitudeI, int32_t longitudeI, char *out, size_t outSize)
{
    if (!out || outSize == 0)
        return;
    if (latitudeI == 0 && longitudeI == 0) {
        std::snprintf(out, outSize, "NO POSITION");
        return;
    }

    GeoCoord coord(latitudeI, longitudeI, 0);
    const uint32_t easting = coord.getMGRSEasting() % 100000U;
    const uint32_t northing = coord.getMGRSNorthing() % 100000U;
    std::snprintf(out, outSize, "%02u%c %c%c %05lu %05lu", coord.getMGRSZone(), coord.getMGRSBand(),
                  coord.getMGRSEast100k(), coord.getMGRSNorth100k(), static_cast<unsigned long>(easting),
                  static_cast<unsigned long>(northing));
}

uint16_t TacticalMapModule::degreesToMil(float degrees)
{
    while (degrees < 0.0f)
        degrees += 360.0f;
    while (degrees >= 360.0f)
        degrees -= 360.0f;
    return static_cast<uint16_t>(std::lround(degrees * (6400.0f / 360.0f))) % 6400U;
}

const char *TacticalMapModule::formatDistance(float meters, char *out, size_t outSize)
{
    if (meters >= 1000.0f)
        std::snprintf(out, outSize, "%.2f km", meters / 1000.0f);
    else
        std::snprintf(out, outSize, "%.0f m", meters);
    return out;
}

uint32_t TacticalMapModule::positionAgeSeconds(const meshtastic_PositionLite &position)
{
    const uint32_t now = getTime();
    if (position.time == 0 || now <= position.time)
        return 0;
    return now - position.time;
}

void TacticalMapModule::drawFrame(OLEDDisplay *display, OLEDDisplayUiState *, int16_t x, int16_t y)
{
    if (!display || !nodeDB)
        return;

    const uint32_t ownNode = nodeDB->getNodeNum();
    auto ownIt = nodeDB->nodePositions.find(ownNode);

    display->setTextAlignment(TEXT_ALIGN_LEFT);
    display->setFont(FONT_SMALL);
    display->drawString(x, y, "TACTICAL MGRS / 6400");

    if (ownIt == nodeDB->nodePositions.end() || ownIt->second.latitude_i == 0 || ownIt->second.longitude_i == 0) {
        display->drawString(x, y + 18, "Waiting for own GPS fix");
        return;
    }

    // Rotate the selected target every five seconds. This works on one-button devices without
    // stealing the system button; each positioned node remains visible long enough to read.
    if (selectedNode == 0 || millis() - lastSelectionAt >= 5000U || nodeDB->nodePositions.count(selectedNode) == 0) {
        selectedNode = selectNextPositionedNode(ownNode);
        lastSelectionAt = millis();
    }

    char ownMgrs[32];
    formatMgrs10(ownIt->second.latitude_i, ownIt->second.longitude_i, ownMgrs, sizeof(ownMgrs));
    display->drawString(x, y + 12, "OWN " + String(ownMgrs));

    if (selectedNode == 0) {
        display->drawString(x, y + 27, "No remote position");
        return;
    }

    const auto targetIt = nodeDB->nodePositions.find(selectedNode);
    if (targetIt == nodeDB->nodePositions.end())
        return;

    char targetMgrs[32];
    formatMgrs10(targetIt->second.latitude_i, targetIt->second.longitude_i, targetMgrs, sizeof(targetMgrs));

    const auto *node = findNode(selectedNode);
    char name[16];
    if (node && node->short_name[0])
        std::snprintf(name, sizeof(name), "%s", node->short_name);
    else
        std::snprintf(name, sizeof(name), "!%08lx", static_cast<unsigned long>(selectedNode));

    const double ownLat = ownIt->second.latitude_i * 1e-7;
    const double ownLon = ownIt->second.longitude_i * 1e-7;
    const double targetLat = targetIt->second.latitude_i * 1e-7;
    const double targetLon = targetIt->second.longitude_i * 1e-7;
    const float meters = GeoCoord::latLongToMeter(ownLat, ownLon, targetLat, targetLon);
    const float bearingDeg = GeoCoord::bearing(ownLat, ownLon, targetLat, targetLon) * RAD_TO_DEG;
    const uint16_t mil = degreesToMil(bearingDeg);
    const uint32_t age = positionAgeSeconds(targetIt->second);

    char distance[16];
    char line[48];
    std::snprintf(line, sizeof(line), "%s %s", name, targetMgrs);
    display->drawString(x, y + 24, line);
    std::snprintf(line, sizeof(line), "%04u mil  %s", mil, formatDistance(meters, distance, sizeof(distance)));
    display->drawString(x, y + 36, line);
    std::snprintf(line, sizeof(line), "Position age %lus", static_cast<unsigned long>(age));
    display->drawString(x, y + 48, line);

    // Compact north-up tactical plot. The selected target is projected relative to own position;
    // all available node positions are shown as small points.
    const int mapLeft = display->getWidth() > 180 ? display->getWidth() - 72 : display->getWidth() - 34;
    const int mapTop = y + 10;
    const int mapSize = display->getWidth() > 180 ? 62 : 30;
    const int cx = mapLeft + mapSize / 2;
    const int cy = mapTop + mapSize / 2;
    const float plotRadius = mapSize / 2.0f - 3.0f;
    const float scale = std::max(50.0f, meters) / plotRadius;

    display->drawRect(mapLeft, mapTop, mapSize, mapSize);
    display->drawLine(cx - 2, cy, cx + 2, cy);
    display->drawLine(cx, cy - 2, cx, cy + 2);

    for (const auto &entry : nodeDB->nodePositions) {
        if (entry.first == ownNode || entry.second.latitude_i == 0 || entry.second.longitude_i == 0)
            continue;
        const double lat = entry.second.latitude_i * 1e-7;
        const double lon = entry.second.longitude_i * 1e-7;
        const float d = GeoCoord::latLongToMeter(ownLat, ownLon, lat, lon);
        const float b = GeoCoord::bearing(ownLat, ownLon, lat, lon);
        const float r = std::min(plotRadius, d / scale);
        const int px = cx + static_cast<int>(std::sin(b) * r);
        const int py = cy - static_cast<int>(std::cos(b) * r);
        if (entry.first == selectedNode)
            display->fillCircle(px, py, 2);
        else
            display->setPixel(px, py);
    }
    display->drawLine(cx, cy, cx + static_cast<int>(std::sin(bearingDeg * DEG_TO_RAD) * plotRadius),
                      cy - static_cast<int>(std::cos(bearingDeg * DEG_TO_RAD) * plotRadius));
}

#endif
