#pragma once

#include "jarnsen/core/roles/JarnsenDeviceRole.h"

#include <cstddef>
#include <cstdint>

namespace jarnsen
{

enum class NodeStateKind : uint8_t {
    POSITION = 1,
    ATAK_PLI = 2,
};

enum class NodeStateOrigin : uint8_t {
    DIRECT = 1,
    SYNC = 2,
};

enum class NodeMovement : uint8_t {
    UNKNOWN = 0,
    STATIONARY = 1,
    MOVING = 2,
};

struct NodeStateRecord {
    bool valid = false;
    uint32_t nodeNum = 0;
    uint32_t sourceEpoch = 0;
    uint32_t rxEpoch = 0;
    uint32_t expiresEpoch = 0;
    uint32_t lastSeenEpoch = 0;

    int32_t latitudeI = 0;
    int32_t longitudeI = 0;
    int32_t altitude = 0;
    uint32_t speedCmS = 0;
    uint16_t courseCentiDeg = 0;
    uint8_t battery = 0;
    uint8_t locationSource = 0;
    uint8_t takTeam = 0;
    uint8_t takMemberRole = 0;

    DeviceRole role = DeviceRole::UNCONFIGURED;
    NodeStateKind kind = NodeStateKind::POSITION;
    NodeStateOrigin origin = NodeStateOrigin::DIRECT;
    NodeMovement movement = NodeMovement::UNKNOWN;
};

constexpr size_t JARNSEN_NODE_STATE_CACHE_CAPACITY = 32U;
constexpr uint32_t JARNSEN_TAK_STATIONARY_CACHE_SECS = 2U * 60U * 60U;
constexpr uint32_t JARNSEN_TAK_MOVING_CACHE_SECS = 20U * 60U;
constexpr uint32_t JARNSEN_REPEATER_STATIONARY_CACHE_SECS = 6U * 60U * 60U;
constexpr uint32_t JARNSEN_REPEATER_MOVING_CACHE_SECS = 15U * 60U;
constexpr uint32_t JARNSEN_DRONE_MOVING_CACHE_SECS = 10U * 60U;
constexpr uint32_t JARNSEN_GENERIC_STATIONARY_CACHE_SECS = 60U * 60U;
constexpr uint32_t JARNSEN_GENERIC_MOVING_CACHE_SECS = 15U * 60U;

constexpr uint32_t nodeStateCacheTtlSecs(DeviceRole role, NodeMovement movement)
{
    const bool stationary = movement == NodeMovement::STATIONARY;
    switch (role) {
    case DeviceRole::TAK:
    case DeviceRole::TAK_TRACKER:
        return stationary ? JARNSEN_TAK_STATIONARY_CACHE_SECS : JARNSEN_TAK_MOVING_CACHE_SECS;
    case DeviceRole::TAK_REPEATER:
        return stationary ? JARNSEN_REPEATER_STATIONARY_CACHE_SECS : JARNSEN_REPEATER_MOVING_CACHE_SECS;
    case DeviceRole::DRONE_REPEATER:
        return stationary ? JARNSEN_GENERIC_STATIONARY_CACHE_SECS : JARNSEN_DRONE_MOVING_CACHE_SECS;
    case DeviceRole::UNCONFIGURED:
    default:
        return stationary ? JARNSEN_GENERIC_STATIONARY_CACHE_SECS : JARNSEN_GENERIC_MOVING_CACHE_SECS;
    }
}

class NodeStateCache
{
  public:
    // Newer source time always wins. For the same source time, DIRECT wins
    // over SYNC. Cache forwarding therefore never makes an old position new.
    bool note(const NodeStateRecord &incoming, uint32_t nowEpoch);

    // Learning a JARNSEN role later (for example from a sync HELLO) may extend
    // or shorten the active TTL, but never changes the original source time.
    void updateRole(uint32_t nodeNum, DeviceRole role, uint32_t nowEpoch);

    bool find(uint32_t nodeNum, NodeStateRecord &out) const;
    size_t snapshot(NodeStateRecord *out, size_t capacity, uint32_t nowEpoch) const;
    size_t count(uint32_t nowEpoch) const;
    void prune(uint32_t nowEpoch);
    void clear();

  private:
    NodeStateRecord records_[JARNSEN_NODE_STATE_CACHE_CAPACITY]{};

    int findIndex(uint32_t nodeNum) const;
    int replacementIndex(uint32_t nowEpoch) const;
};

NodeStateCache &nodeStateCache();

} // namespace jarnsen
