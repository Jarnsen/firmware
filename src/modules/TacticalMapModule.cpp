#include "TacticalMapModule.h"

#if defined(HAS_TACTICAL_MAP) && HAS_TACTICAL_MAP && HAS_SCREEN && !MESHTASTIC_EXCLUDE_GPS && !MESHTASTIC_EXCLUDE_POSITIONDB

#include "NodeDB.h"
#include "TacticalMapMath.h"
#include "gps/RTC.h"
#include "graphics/SharedUIDisplay.h"
#include "graphics/ScreenFonts.h"
#include "graphics/draw/UIRenderer.h"

#include <algorithm>
#include <cmath>
#include <cstdio>

#if defined(HAS_TACTICAL_DISPLAY_MIRROR) && HAS_TACTICAL_DISPLAY_MIRROR
#include <Arduino.h>
#include <cstring>
#endif

namespace
{
#if defined(HAS_TACTICAL_DISPLAY_MIRROR) && HAS_TACTICAL_DISPLAY_MIRROR
constexpr uint16_t TACTICAL_MIRROR_WIDTH = 128;
constexpr uint16_t TACTICAL_MIRROR_HEIGHT = 64;
constexpr size_t TACTICAL_MIRROR_BYTES = TACTICAL_MIRROR_WIDTH * TACTICAL_MIRROR_HEIGHT / 8;
constexpr uint32_t TACTICAL_MIRROR_INTERVAL_MS = 500;

void emitTacticalDisplayMirror(OLEDDisplay *display)
{
    if (!display || !display->buffer || display->getWidth() != TACTICAL_MIRROR_WIDTH ||
        display->getHeight() != TACTICAL_MIRROR_HEIGHT || !Serial)
        return;

    static uint8_t previous[TACTICAL_MIRROR_BYTES] = {};
    static bool havePrevious = false;
    static uint32_t lastEmit = 0;

    const uint32_t now = millis();
    if (havePrevious && static_cast<uint32_t>(now - lastEmit) < TACTICAL_MIRROR_INTERVAL_MS)
        return;
    if (havePrevious && memcmp(previous, display->buffer, TACTICAL_MIRROR_BYTES) == 0)
        return;

    static constexpr char HEX[] = "0123456789ABCDEF";
    char encoded[64];

    Serial.printf("@TMF %u %u ", static_cast<unsigned>(TACTICAL_MIRROR_WIDTH),
                  static_cast<unsigned>(TACTICAL_MIRROR_HEIGHT));
    for (size_t offset = 0; offset < TACTICAL_MIRROR_BYTES; offset += 32) {
        const size_t count = std::min<size_t>(32, TACTICAL_MIRROR_BYTES - offset);
        for (size_t i = 0; i < count; ++i) {
            const uint8_t value = display->buffer[offset + i];
            encoded[i * 2] = HEX[value >> 4];
            encoded[i * 2 + 1] = HEX[value & 0x0f];
        }
        Serial.write(reinterpret_cast<const uint8_t *>(encoded), count * 2);
    }
    Serial.write('\n');

    memcpy(previous, display->buffer, TACTICAL_MIRROR_BYTES);
    havePrevious = true;
    lastEmit = now;
}
#else
void emitTacticalDisplayMirror(OLEDDisplay *) {}
#endif
} // namespace

bool TacticalMapModule::wantUIFrame()
{
    return config.device.role == meshtastic_Config_DeviceConfig_Role_TRACKER ||
           config.device.role == meshtastic_Config_DeviceConfig_Role_TAK_TRACKER;
}

NodeNum TacticalMapModule::selectNewestPositionedNode() const
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

bool TacticalMapModule::copyTarget(meshtastic_PositionLite &position, char *name, size_t nameSize)
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

void TacticalMapModule::drawFrame(OLEDDisplay *display, OLEDDisplayUiState *, int16_t x, int16_t y)
{
    if (!display || !nodeDB)
        return;

    display->clear();
    display->setTextAlignment(TEXT_ALIGN_LEFT);
    display->setFont(FONT_SMALL);
    graphics::drawCommonHeader(display, x, y, "TACTICAL");

    const int *textY = graphics::getTextPositions(display);
    meshtastic_PositionLite ownPosition;
    const bool haveOwnPosition = nodeDB->copyNodePosition(nodeDB->getNodeNum(), ownPosition) &&
                                 (ownPosition.latitude_i != 0 || ownPosition.longitude_i != 0) &&
                                 TacticalMapMath::isValidCoordinate(ownPosition.latitude_i, ownPosition.longitude_i);

    char mgrs[24] = "MGRS unavailable";
    if (haveOwnPosition && !TacticalMapMath::formatMgrs10(ownPosition.latitude_i, ownPosition.longitude_i, mgrs, sizeof(mgrs)))
        snprintf(mgrs, sizeof(mgrs), "MGRS unavailable");

    const int16_t mgrsY = y + display->getHeight() - FONT_HEIGHT_SMALL - 2;
    display->drawString(x, mgrsY, mgrs);

    if (!haveOwnPosition) {
        display->drawString(x, y + textY[1], "NO GPS FIX");
        display->drawString(x, y + textY[2], "Waiting for position");
        emitTacticalDisplayMirror(display);
        return;
    }

    meshtastic_PositionLite targetPosition;
    char targetName[12];
    if (!copyTarget(targetPosition, targetName, sizeof(targetName))) {
        display->drawString(x, y + textY[1], "TGT --");
        display->drawString(x, y + textY[2], "Waiting for node");
        emitTacticalDisplayMirror(display);
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

    char line[28];
    char value[16];
    snprintf(line, sizeof(line), "TGT %s", targetName);
    display->drawString(x, y + textY[1], line);
    snprintf(line, sizeof(line), "BRG %03u DEG", static_cast<unsigned>(lroundf(bearing)) % 360U);
    display->drawString(x, y + textY[2], line);
    snprintf(line, sizeof(line), "MIL %04u", mil);
    display->drawString(x, y + textY[3], line);
    snprintf(line, sizeof(line), "DST %s", TacticalMapMath::formatDistance(distance, value, sizeof(value)));
    display->drawString(x, y + textY[4], line);
    snprintf(line, sizeof(line), "AGE %s",
             haveAge ? TacticalMapMath::formatPositionAge(age, value, sizeof(value)) : "--");
    display->drawString(x, y + textY[5], line);

    const int16_t mapTop = y + textY[1];
    const int16_t mapBottom = mgrsY - 2;
    const int16_t mapSize = std::max<int16_t>(24, std::min<int16_t>(display->getWidth() / 3, mapBottom - mapTop));
    const int16_t mapLeft = x + display->getWidth() - mapSize - 2;
    const int16_t centerX = mapLeft + mapSize / 2;
    const int16_t centerY = mapTop + mapSize / 2;
    const float plotRadius = mapSize / 2.0f - 4.0f;
    const float mapRange = TacticalMapMath::mapRangeMeters(distance);
    const float targetRadius = std::min(plotRadius, distance * plotRadius / mapRange);
    const float bearingRadians = bearing * 0.01745329252f;
    const int16_t targetX = centerX + static_cast<int16_t>(sinf(bearingRadians) * targetRadius);
    const int16_t targetY = centerY - static_cast<int16_t>(cosf(bearingRadians) * targetRadius);

    display->drawRect(mapLeft, mapTop, mapSize, mapSize);
    display->drawString(mapLeft + 2, mapTop, "N");
    display->drawLine(centerX - 2, centerY, centerX + 2, centerY);
    display->drawLine(centerX, centerY - 2, centerX, centerY + 2);
    display->drawLine(centerX, centerY, targetX, targetY);
    display->fillCircle(targetX, targetY, 2);
    emitTacticalDisplayMirror(display);
}

#endif
