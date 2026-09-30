#include "jarnsen/core/mesh/JarnsenNodeStateCache.h"

#include "jarnsen/core/position/JarnsenPositionCore.h"

#include <algorithm>
#include <climits>

namespace jarnsen
{
namespace
{
constexpr double MOVEMENT_DISTANCE_M = 25.0;

uint32_t addSaturated(uint32_t base, uint32_t delta)
{
    if (UINT32_MAX - base < delta)
        return UINT32_MAX;
    return base + delta;
}

bool positionValid(const NodeStateRecord &record)
{
    return (record.latitudeI != 0 || record.longitudeI != 0) &&
           record.latitudeI >= -900000000 && record.latitudeI <= 900000000 &&
           record.longitudeI >= -1800000000 && record.longitudeI <= 1800000000;
}

NodeMovement inferMovement(const NodeStateRecord &incoming, const NodeStateRecord *previous)
{
    if (incoming.movement != NodeMovement::UNKNOWN)
        return incoming.movement;

    if (incoming.speedRaw > 50U)
        return NodeMovement::MOVING;

    if (previous && previous->valid && positionValid(*previous) && positionValid(incoming)) {
        const double distance =
            jarnsenPositionDistanceMeters(previous->latitudeI, previous->longitudeI, incoming.latitudeI, incoming.longitudeI);
        return distance > MOVEMENT_DISTANCE_M ? NodeMovement::MOVING : NodeMovement::STATIONARY;
    }

    // First sighting without a movement indication is treated conservatively:
    // do not grant a two-hour stationary lifetime until a later update proves it.
    return NodeMovement::MOVING;
}

uint32_t effectiveExpiry(const NodeStateRecord &record)
{
    const uint32_t policyExpiry = addSaturated(record.sourceEpoch, nodeStateCacheTtlSecs(record.role, record.movement));
    if (record.origin == NodeStateOrigin::SYNC && record.expiresEpoch != 0U)
        return std::min(policyExpiry, record.expiresEpoch);
    return policyExpiry;
}

} // namespace

static_assert(nodeStateCacheTtlSecs(DeviceRole::TAK, NodeMovement::STATIONARY) == 7200U,
              "Stationary TAK cache must remain two hours");
static_assert(nodeStateCacheTtlSecs(DeviceRole::TAK_TRACKER, NodeMovement::STATIONARY) == 7200U,
              "Stationary TAK Tracker cache must remain two hours");
static_assert(nodeStateCacheTtlSecs(DeviceRole::TAK_TRACKER, NodeMovement::MOVING) == 1200U,
              "Moving TAK Tracker cache must remain short-lived");

int NodeStateCache::findIndex(uint32_t nodeNum) const
{
    for (size_t i = 0; i < JARNSEN_NODE_STATE_CACHE_CAPACITY; ++i)
        if (records_[i].valid && records_[i].nodeNum == nodeNum)
            return static_cast<int>(i);
    return -1;
}

int NodeStateCache::replacementIndex(uint32_t nowEpoch) const
{
    int oldest = -1;
    uint32_t oldestSource = UINT32_MAX;
    for (size_t i = 0; i < JARNSEN_NODE_STATE_CACHE_CAPACITY; ++i) {
        if (!records_[i].valid)
            return static_cast<int>(i);
        if (nowEpoch != 0U && records_[i].expiresEpoch != 0U && records_[i].expiresEpoch <= nowEpoch)
            return static_cast<int>(i);
        if (records_[i].sourceEpoch < oldestSource) {
            oldestSource = records_[i].sourceEpoch;
            oldest = static_cast<int>(i);
        }
    }
    return oldest;
}

bool NodeStateCache::note(const NodeStateRecord &incoming, uint32_t nowEpoch)
{
    if (incoming.nodeNum == 0U || !positionValid(incoming))
        return false;

    NodeStateRecord candidate = incoming;
    if (candidate.sourceEpoch == 0U)
        candidate.sourceEpoch = candidate.rxEpoch;
    if (candidate.sourceEpoch == 0U)
        return false;
    if (candidate.rxEpoch == 0U)
        candidate.rxEpoch = nowEpoch;

    const int existingIndex = findIndex(candidate.nodeNum);
    const NodeStateRecord *previous = existingIndex >= 0 ? &records_[existingIndex] : nullptr;
    candidate.movement = inferMovement(candidate, previous);
    candidate.expiresEpoch = effectiveExpiry(candidate);

    if (nowEpoch != 0U && candidate.expiresEpoch != 0U && candidate.expiresEpoch <= nowEpoch)
        return false;

    if (previous) {
        if (candidate.sourceEpoch < previous->sourceEpoch)
            return false;
        if (candidate.sourceEpoch == previous->sourceEpoch &&
            previous->origin == NodeStateOrigin::DIRECT && candidate.origin == NodeStateOrigin::SYNC)
            return false;

        // A cache transfer is not a sighting of the original node.
        if (candidate.origin == NodeStateOrigin::SYNC)
            candidate.lastSeenEpoch = previous->lastSeenEpoch;
        else
            candidate.lastSeenEpoch = std::max(previous->lastSeenEpoch,
                                               candidate.lastSeenEpoch ? candidate.lastSeenEpoch : candidate.rxEpoch);
    } else if (candidate.origin == NodeStateOrigin::DIRECT) {
        candidate.lastSeenEpoch = candidate.lastSeenEpoch ? candidate.lastSeenEpoch : candidate.rxEpoch;
    }

    candidate.valid = true;
    const int target = existingIndex >= 0 ? existingIndex : replacementIndex(nowEpoch);
    if (target < 0)
        return false;
    records_[target] = candidate;
    return true;
}

void NodeStateCache::updateRole(uint32_t nodeNum, DeviceRole role, uint32_t nowEpoch)
{
    const int index = findIndex(nodeNum);
    if (index < 0)
        return;
    NodeStateRecord &record = records_[index];
    record.role = role;
    const uint32_t policyExpiry = addSaturated(record.sourceEpoch, nodeStateCacheTtlSecs(record.role, record.movement));
    if (record.origin == NodeStateOrigin::SYNC && record.expiresEpoch != 0U)
        record.expiresEpoch = std::min(record.expiresEpoch, policyExpiry);
    else
        record.expiresEpoch = policyExpiry;
    if (nowEpoch != 0U && record.expiresEpoch <= nowEpoch)
        record.valid = false;
}

bool NodeStateCache::find(uint32_t nodeNum, NodeStateRecord &out) const
{
    const int index = findIndex(nodeNum);
    if (index < 0)
        return false;
    out = records_[index];
    return true;
}

size_t NodeStateCache::snapshot(NodeStateRecord *out, size_t capacity, uint32_t nowEpoch) const
{
    if (!out || capacity == 0U)
        return 0U;
    size_t written = 0U;
    for (const auto &record : records_) {
        if (!record.valid)
            continue;
        if (nowEpoch != 0U && record.expiresEpoch != 0U && record.expiresEpoch <= nowEpoch)
            continue;
        out[written++] = record;
        if (written >= capacity)
            break;
    }
    return written;
}

size_t NodeStateCache::snapshotPage(NodeStateRecord *out, size_t capacity, size_t liveOffset, uint32_t nowEpoch) const
{
    if (!out || capacity == 0U)
        return 0U;

    size_t skipped = 0U;
    size_t written = 0U;
    for (const auto &record : records_) {
        if (!record.valid)
            continue;
        if (nowEpoch != 0U && record.expiresEpoch != 0U && record.expiresEpoch <= nowEpoch)
            continue;
        if (skipped < liveOffset) {
            skipped++;
            continue;
        }
        out[written++] = record;
        if (written >= capacity)
            break;
    }
    return written;
}

size_t NodeStateCache::count(uint32_t nowEpoch) const
{
    size_t result = 0U;
    for (const auto &record : records_) {
        if (record.valid && (nowEpoch == 0U || record.expiresEpoch == 0U || record.expiresEpoch > nowEpoch))
            ++result;
    }
    return result;
}

void NodeStateCache::prune(uint32_t nowEpoch)
{
    if (nowEpoch == 0U)
        return;
    for (auto &record : records_)
        if (record.valid && record.expiresEpoch != 0U && record.expiresEpoch <= nowEpoch)
            record = NodeStateRecord{};
}

void NodeStateCache::clear()
{
    for (auto &record : records_)
        record = NodeStateRecord{};
}

NodeStateCache &nodeStateCache()
{
    static NodeStateCache cache;
    return cache;
}

} // namespace jarnsen
