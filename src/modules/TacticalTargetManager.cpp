#include "TacticalTargetManager.h"

#if defined(HAS_TACTICAL_MAP) && HAS_TACTICAL_MAP && !MESHTASTIC_EXCLUDE_POSITIONDB

#include "NodeDB.h"
#include "TacticalMapMath.h"
#include "graphics/draw/UIRenderer.h"

#include <algorithm>
#include <cstdio>
#include <cstring>
#include <vector>

TacticalTargetManager &TacticalTargetManager::instance()
{
    static TacticalTargetManager manager;
    return manager;
}

bool TacticalTargetManager::copyNodeTarget(NodeNum nodeNum, meshtastic_PositionLite &position, char *name, size_t nameSize) const
{
    if (!nodeDB || !nodeNum || nodeNum == nodeDB->getNodeNum() || !name || nameSize == 0 ||
        !nodeDB->copyNodePosition(nodeNum, position) || (position.latitude_i == 0 && position.longitude_i == 0) ||
        !TacticalMapMath::isValidCoordinate(position.latitude_i, position.longitude_i))
        return false;

    const meshtastic_NodeInfoLite *node = nodeDB->getMeshNode(nodeNum);
    if (nodeInfoLiteHasUser(node) && node->short_name[0])
        snprintf(name, nameSize, "%s", node->short_name);
    else
        snprintf(name, nameSize, "!%04lx", static_cast<unsigned long>(nodeNum & 0xffffU));
    return true;
}

NodeNum TacticalTargetManager::newestPositionedNode() const
{
    if (!nodeDB)
        return 0;

    NodeNum newest = 0;
    uint32_t newestTime = 0;
    for (const NodeNum candidate : nodeDB->snapshotPositionNodeNums(nodeDB->getNodeNum())) {
        meshtastic_PositionLite position;
        if (!nodeDB->copyNodePosition(candidate, position) || (position.latitude_i == 0 && position.longitude_i == 0) ||
            !TacticalMapMath::isValidCoordinate(position.latitude_i, position.longitude_i))
            continue;
        const uint32_t time = position.time ? position.time : nodeDB->hotNodeLastHeard(candidate);
        if (!newest || time > newestTime) {
            newest = candidate;
            newestTime = time;
        }
    }
    return newest;
}

bool TacticalTargetManager::copyActiveTarget(meshtastic_PositionLite &position, char *name, size_t nameSize)
{
    if (!name || nameSize == 0)
        return false;

    if (mode == Mode::MANUAL_MGRS && TacticalMapMath::isValidCoordinate(manualPosition.latitude_i, manualPosition.longitude_i)) {
        position = manualPosition;
        snprintf(name, nameSize, "GRID");
        return true;
    }

    if (mode == Mode::LOCKED_NODE && copyNodeTarget(lockedNode, position, name, nameSize)) {
        selectedNode = lockedNode;
        return true;
    }

    const NodeNum favorite = graphics::UIRenderer::currentFavoriteNodeNum;
    if (favorite && copyNodeTarget(favorite, position, name, nameSize)) {
        selectedNode = favorite;
        return true;
    }

    if (copyNodeTarget(selectedNode, position, name, nameSize))
        return true;

    selectedNode = newestPositionedNode();
    return copyNodeTarget(selectedNode, position, name, nameSize);
}

bool TacticalTargetManager::cycleNode(int direction)
{
    if (!nodeDB)
        return false;

    std::vector<NodeNum> nodes = nodeDB->snapshotPositionNodeNums(nodeDB->getNodeNum());
    nodes.erase(std::remove_if(nodes.begin(), nodes.end(),
                               [this](NodeNum node) {
                                   meshtastic_PositionLite position;
                                   char name[2];
                                   return !copyNodeTarget(node, position, name, sizeof(name));
                               }),
                nodes.end());
    if (nodes.empty())
        return false;

    NodeNum current = mode == Mode::LOCKED_NODE ? lockedNode : selectedNode;
    auto found = std::find(nodes.begin(), nodes.end(), current);
    int index = found == nodes.end() ? 0 : static_cast<int>(found - nodes.begin());
    if (found != nodes.end())
        index = (index + (direction < 0 ? -1 : 1) + static_cast<int>(nodes.size())) % static_cast<int>(nodes.size());

    selectedNode = nodes[index];
    lockedNode = selectedNode;
    mode = Mode::LOCKED_NODE;
    return true;
}

bool TacticalTargetManager::setManualMgrs(const char *mgrs)
{
    int32_t latitude = 0;
    int32_t longitude = 0;
    if (!TacticalMapMath::parseMgrs10(mgrs, latitude, longitude))
        return false;

    manualPosition = {};
    manualPosition.latitude_i = latitude;
    manualPosition.longitude_i = longitude;
    manualPosition.location_source = meshtastic_Position_LocSource_LOC_MANUAL;
    if (!TacticalMapMath::formatMgrs10(latitude, longitude, manualMgrs, sizeof(manualMgrs)))
        return false;
    mode = Mode::MANUAL_MGRS;
    return true;
}

void TacticalTargetManager::useAutoTarget()
{
    mode = Mode::AUTO;
    lockedNode = 0;
}

void TacticalTargetManager::lockCurrentNode()
{
    if (!selectedNode) {
        meshtastic_PositionLite position;
        char name[12];
        copyActiveTarget(position, name, sizeof(name));
    }
    if (selectedNode) {
        lockedNode = selectedNode;
        mode = Mode::LOCKED_NODE;
    }
}

const char *TacticalTargetManager::modeName() const
{
    switch (mode) {
    case Mode::LOCKED_NODE:
        return "LOCKED";
    case Mode::MANUAL_MGRS:
        return "MGRS";
    default:
        return "AUTO";
    }
}

#endif
