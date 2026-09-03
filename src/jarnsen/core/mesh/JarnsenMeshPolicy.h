#pragma once

#include <stdint.h>

namespace jarnsen
{

constexpr uint32_t MESH_POLICY_DEFAULT_POSITION_INTERVAL_SECS = 900U;
constexpr uint32_t MESH_POLICY_MIN_NEIGHBOR_INTERVAL_SECS = 14400U;

struct MeshPolicyState {
    uint32_t positionBroadcastSecs = 0;
    bool positionSmartEnabled = false;
    bool neighborEnabled = false;
    bool neighborTransmitOverLora = false;
    uint32_t neighborUpdateInterval = 0;
};

struct MeshPolicyResult {
    MeshPolicyState state{};
    bool corrected = false;
};

constexpr MeshPolicyResult normalizeMeshPolicy(const MeshPolicyState &current, uint32_t preferredPositionIntervalSecs,
                                               bool desiredNeighborEnabled)
{
    MeshPolicyResult result{current, false};

    if (result.state.positionBroadcastSecs == 0) {
        result.state.positionBroadcastSecs = preferredPositionIntervalSecs ? preferredPositionIntervalSecs
                                                                          : MESH_POLICY_DEFAULT_POSITION_INTERVAL_SECS;
        result.corrected = true;
    }
    if (!result.state.positionSmartEnabled) {
        result.state.positionSmartEnabled = true;
        result.corrected = true;
    }
    if (result.state.neighborEnabled != desiredNeighborEnabled) {
        result.state.neighborEnabled = desiredNeighborEnabled;
        result.corrected = true;
    }
    if (result.state.neighborTransmitOverLora != desiredNeighborEnabled) {
        result.state.neighborTransmitOverLora = desiredNeighborEnabled;
        result.corrected = true;
    }
    if (result.state.neighborUpdateInterval < MESH_POLICY_MIN_NEIGHBOR_INTERVAL_SECS) {
        result.state.neighborUpdateInterval = MESH_POLICY_MIN_NEIGHBOR_INTERVAL_SECS;
        result.corrected = true;
    }

    return result;
}

} // namespace jarnsen
