#pragma once

#include "configuration.h"

#if defined(HAS_TACTICAL_MAP) && HAS_TACTICAL_MAP && !MESHTASTIC_EXCLUDE_POSITIONDB

#include "mesh/MeshTypes.h"
#include "mesh/generated/meshtastic/deviceonly.pb.h"

#include <cstddef>

class TacticalTargetManager
{
  public:
    enum class Mode : uint8_t { AUTO = 0, LOCKED_NODE = 1, MANUAL_MGRS = 2 };

    static TacticalTargetManager &instance();

    bool copyActiveTarget(meshtastic_PositionLite &position, char *name, size_t nameSize);
    bool cycleNode(int direction);
    bool setManualMgrs(const char *mgrs);
    void useAutoTarget();
    void lockCurrentNode();
    Mode getMode() const { return mode; }
    NodeNum getLockedNode() const { return lockedNode; }
    const char *getManualMgrs() const { return manualMgrs; }
    const char *modeName() const;

  private:
    Mode mode = Mode::AUTO;
    NodeNum selectedNode = 0;
    NodeNum lockedNode = 0;
    meshtastic_PositionLite manualPosition = {};
    char manualMgrs[24] = {0};

    TacticalTargetManager() = default;
    NodeNum newestPositionedNode() const;
    bool copyNodeTarget(NodeNum nodeNum, meshtastic_PositionLite &position, char *name, size_t nameSize) const;
};

#endif
