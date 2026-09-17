#pragma once

#include "mesh/generated/meshtastic/mesh.pb.h"
#include <cstdint>

struct TrackerMeshHealthSummary {
    uint16_t observedNodes = 0;
    uint16_t active15m = 0;
    uint16_t active1h = 0;
    uint16_t active24h = 0;
    uint16_t direct15m = 0;
    uint32_t rx1h = 0;
    uint32_t totalRx = 0;
    int16_t lastDirectRssiDbm = 0;
    int16_t lastDirectSnrQ4 = 0;
    uint32_t lastDirectAgeSecs = UINT32_MAX;
    uint32_t lastDirectNode = 0;
};

#if defined(HELTEC_TRACKER_V1_1)
void trackerMeshHealthOnRadioPacket(const meshtastic_MeshPacket &packet);
TrackerMeshHealthSummary trackerMeshHealthSummary();
#else
inline void trackerMeshHealthOnRadioPacket(const meshtastic_MeshPacket &) {}
inline TrackerMeshHealthSummary trackerMeshHealthSummary() { return {}; }
#endif
