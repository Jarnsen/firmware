#include "jarnsen/core/mesh/JarnsenNodeStateSync.h"

#include "MeshService.h"
#include "Router.h"
#include "configuration.h"
#include "concurrency/OSThread.h"
#include "gps/RTC.h"
#include "jarnsen/core/mesh/JarnsenNodeStateCache.h"
#include "jarnsen/core/service/JarnsenDiagnosticLog.h"
#include "jarnsen/core/status/JarnsenStatusProvider.h"
#include "mesh/MeshModule.h"
#include "mesh/NodeDB.h"
#include "meshtastic/atak.pb.h"
#include "meshtastic/mesh.pb.h"
#include "pb_decode.h"
#include "pb_encode.h"

#include <algorithm>
#include <atomic>
#include <climits>
#include <cstdio>
#include <cstring>

namespace jarnsen
{
namespace
{

constexpr uint8_t SYNC_MAGIC[4] = {'J', 'S', 'C', '1'};
constexpr uint8_t SYNC_VERSION = 1U;
constexpr uint32_t HELLO_INTERVAL_MS = 60UL * 60UL * 1000UL;
constexpr uint32_t FULL_RECONCILE_INTERVAL_MS = 6UL * 60UL * 60UL * 1000UL;
constexpr uint8_t HELLO_META_VERSION = 1U;
constexpr size_t HELLO_META_SIZE = 20U;
constexpr size_t MAX_DIGEST_ENTRIES = 18U;
constexpr size_t MAX_PEERS = JARNSEN_NODE_STATE_CACHE_CAPACITY;

enum class SyncMessage : uint8_t {
    HELLO = 1,
    DIGEST = 2,
    REQUEST = 3,
    RECORD = 4,
    RECEIPT_REQUEST = 5,
    RECEIPT = 6,
};

struct PeerState {
    uint32_t nodeNum = 0;
    DeviceRole role = DeviceRole::UNCONFIGURED;
    uint32_t lastHelloEpoch = 0;
    uint32_t lastDigestMs = 0;
};

struct CacheSignature {
    uint16_t count = 0;
    uint32_t xorHash = 0;
    uint32_t sumHash = 0;

    bool matches(uint16_t remoteCount, uint32_t remoteXor, uint32_t remoteSum) const
    {
        return count == remoteCount && xorHash == remoteXor && sumHash == remoteSum;
    }
};

uint32_t readU32(const uint8_t *p)
{
    return static_cast<uint32_t>(p[0]) | (static_cast<uint32_t>(p[1]) << 8U) |
           (static_cast<uint32_t>(p[2]) << 16U) | (static_cast<uint32_t>(p[3]) << 24U);
}

int32_t readI32(const uint8_t *p)
{
    return static_cast<int32_t>(readU32(p));
}

uint16_t readU16(const uint8_t *p)
{
    return static_cast<uint16_t>(p[0]) | (static_cast<uint16_t>(p[1]) << 8U);
}

void writeU32(uint8_t *p, uint32_t value)
{
    p[0] = static_cast<uint8_t>(value);
    p[1] = static_cast<uint8_t>(value >> 8U);
    p[2] = static_cast<uint8_t>(value >> 16U);
    p[3] = static_cast<uint8_t>(value >> 24U);
}

void writeI32(uint8_t *p, int32_t value)
{
    writeU32(p, static_cast<uint32_t>(value));
}

void writeU16(uint8_t *p, uint16_t value)
{
    p[0] = static_cast<uint8_t>(value);
    p[1] = static_cast<uint8_t>(value >> 8U);
}

bool validRoleByte(uint8_t value)
{
    return value <= static_cast<uint8_t>(DeviceRole::DRONE_REPEATER);
}

bool validKindByte(uint8_t value)
{
    return value == static_cast<uint8_t>(NodeStateKind::POSITION) ||
           value == static_cast<uint8_t>(NodeStateKind::ATAK_PLI);
}

bool validMovementByte(uint8_t value)
{
    return value <= static_cast<uint8_t>(NodeMovement::MOVING);
}

bool deadlineReached(uint32_t now, uint32_t deadline)
{
    return static_cast<int32_t>(now - deadline) >= 0;
}

uint32_t timeUntil(uint32_t now, uint32_t deadline)
{
    return deadlineReached(now, deadline) ? 0U : deadline - now;
}

uint32_t currentEpoch()
{
    return getValidTime(RTCQualityDevice);
}

DeviceRole roleFromNativeNode(uint32_t nodeNum)
{
    if (!nodeDB)
        return DeviceRole::UNCONFIGURED;
    const meshtastic_NodeInfoLite *node = nodeDB->getMeshNode(nodeNum);
    if (!node)
        return DeviceRole::UNCONFIGURED;
    if (node->role == meshtastic_Config_DeviceConfig_Role_TAK)
        return DeviceRole::TAK;
    if (node->role == meshtastic_Config_DeviceConfig_Role_TAK_TRACKER)
        return DeviceRole::TAK_TRACKER;
    return DeviceRole::UNCONFIGURED;
}

NodeMovement movementFromSpeed(bool hasSpeed, uint32_t speedRaw)
{
    if (!hasSpeed)
        return NodeMovement::UNKNOWN;
    // Both source encodings use 50 raw units as a conservative movement gate:
    // POSITION_APP: 0.50 km/h, ATAK_PLI: 0.50 m/s.
    return speedRaw > 50U ? NodeMovement::MOVING : NodeMovement::STATIONARY;
}

uint32_t nativeSpeedToAtakCmS(uint32_t centiKmh)
{
    // 0.01 km/h -> 5/18 cm/s.
    return static_cast<uint32_t>((static_cast<uint64_t>(centiKmh) * 5ULL + 9ULL) / 18ULL);
}

uint32_t atakSpeedToNativeCentiKmh(uint32_t cmPerSec)
{
    // 1 cm/s -> 3.6 centi-km/h.
    const uint64_t value = (static_cast<uint64_t>(cmPerSec) * 18ULL + 2ULL) / 5ULL;
    return static_cast<uint32_t>(std::min<uint64_t>(value, UINT32_MAX));
}

uint32_t avalanche32(uint32_t value)
{
    value ^= value >> 16U;
    value *= 0x7feb352dU;
    value ^= value >> 15U;
    value *= 0x846ca68bU;
    value ^= value >> 16U;
    return value;
}

uint32_t recordFingerprint(const NodeStateRecord &record)
{
    // Keep this aligned with DIGEST semantics. If two peers know the same
    // latest source epoch/kind for a node, a digest cannot improve either side.
    uint32_t hash = 2166136261U;
    hash ^= avalanche32(record.nodeNum + 0x9e3779b9U);
    hash *= 16777619U;
    hash ^= avalanche32(record.sourceEpoch + 0x85ebca6bU);
    hash *= 16777619U;
    hash ^= avalanche32(static_cast<uint32_t>(record.kind) + 0xc2b2ae35U);
    return avalanche32(hash);
}

class JarnsenNodeStateSyncModule final : public MeshModule, private concurrency::OSThread
{
  public:
    JarnsenNodeStateSyncModule()
        : MeshModule("JarnsenStateSync"), concurrency::OSThread("JarnsenSync")
    {
        isPromiscuous = true;
        const uint32_t now = millis();
        const uint32_t self = nodeDB ? nodeDB->getNodeNum() : 0U;
        nextHelloMs_ = now + 1200U + (self % 1200U);
        setIntervalFromNow(1200U + (self % 1200U));
    }

    bool requestPositionReceipt(uint32_t packetId)
    {
        if (packetId == 0U)
            return false;
        receiptExpectedPacketId_.store(packetId);
        receiptConfirmedPacketId_.store(0U);
        receiptRequestDueMs_.store((millis() ? millis() : 1U) + 650U);
        setIntervalFromNow(650U);
        return true;
    }

    bool positionReceiptConfirmed(uint32_t packetId) const
    {
        return packetId != 0U && receiptConfirmedPacketId_.load() == packetId;
    }

    void cancelPositionReceipt()
    {
        receiptExpectedPacketId_.store(0U);
        receiptConfirmedPacketId_.store(0U);
        receiptRequestDueMs_.store(0U);
    }

  protected:
    bool wantPacket(const meshtastic_MeshPacket *p) override
    {
        if (!p || p->via_mqtt || p->which_payload_variant != meshtastic_MeshPacket_decoded_tag)
            return false;
        return p->decoded.portnum == meshtastic_PortNum_POSITION_APP ||
               p->decoded.portnum == meshtastic_PortNum_ATAK_PLUGIN_V2 ||
               p->decoded.portnum == meshtastic_PortNum_PRIVATE_APP;
    }

    ProcessMessage handleReceived(const meshtastic_MeshPacket &mp) override
    {
        if (mp.from == 0U || (nodeDB && mp.from == nodeDB->getNodeNum()))
            return ProcessMessage::CONTINUE;

        if (mp.decoded.portnum == meshtastic_PortNum_POSITION_APP) {
            capturePosition(mp);
            return ProcessMessage::CONTINUE;
        }

        if (mp.decoded.portnum == meshtastic_PortNum_ATAK_PLUGIN_V2) {
            captureAtakPli(mp);
            return ProcessMessage::CONTINUE;
        }

        if (mp.decoded.portnum == meshtastic_PortNum_PRIVATE_APP && isSyncPayload(mp.decoded.payload.bytes, mp.decoded.payload.size)) {
            handleSync(mp);
            return ProcessMessage::STOP;
        }

        return ProcessMessage::CONTINUE;
    }

    int32_t runOnce() override
    {
        if (!nodeDB || !service || !router)
            return 1000;

        const uint32_t nowMs = millis();
        const uint32_t now = currentEpoch();
        if (now)
            nodeStateCache().prune(now);
        seedSelf(now);

        if (pendingDigestNode_ != 0U && deadlineReached(nowMs, pendingDigestDueMs_)) {
            const uint32_t target = pendingDigestNode_;
            const uint8_t channel = pendingDigestChannel_;
            pendingDigestNode_ = 0U;
            sendDigest(target, channel);
        }

        const uint32_t receiptRequestDue = receiptRequestDueMs_.load();
        if (receiptRequestDue != 0U && deadlineReached(nowMs, receiptRequestDue)) {
            receiptRequestDueMs_.store(0U);
            sendReceiptRequest(receiptExpectedPacketId_.load());
        }

        if (pendingReceiptRequester_ != 0U && deadlineReached(nowMs, pendingReceiptDueMs_)) {
            const uint32_t requester = pendingReceiptRequester_;
            const uint32_t packetId = pendingReceiptPacketId_;
            const uint8_t channel = pendingReceiptChannel_;
            pendingReceiptRequester_ = 0U;
            sendReceipt(requester, channel, packetId);
        }

        if (deadlineReached(nowMs, nextHelloMs_)) {
            sendHello();
            nextHelloMs_ = nowMs + HELLO_INTERVAL_MS;
        }

        uint32_t delayMs = timeUntil(nowMs, nextHelloMs_);
        if (pendingDigestNode_ != 0U)
            delayMs = std::min(delayMs, timeUntil(nowMs, pendingDigestDueMs_));
        const uint32_t nextReceiptRequest = receiptRequestDueMs_.load();
        if (nextReceiptRequest != 0U)
            delayMs = std::min(delayMs, timeUntil(nowMs, nextReceiptRequest));
        if (pendingReceiptRequester_ != 0U)
            delayMs = std::min(delayMs, timeUntil(nowMs, pendingReceiptDueMs_));
        if (delayMs < 10U)
            delayMs = 10U;
        return static_cast<int32_t>(std::min<uint32_t>(delayMs, INT32_MAX));
    }

  private:
    PeerState peers_[MAX_PEERS]{};
    uint32_t nextHelloMs_ = 0U;
    uint32_t pendingDigestNode_ = 0U;
    uint32_t pendingDigestDueMs_ = 0U;
    uint8_t pendingDigestChannel_ = 0U;

    std::atomic<uint32_t> receiptExpectedPacketId_{0U};
    std::atomic<uint32_t> receiptConfirmedPacketId_{0U};
    std::atomic<uint32_t> receiptRequestDueMs_{0U};

    uint32_t pendingReceiptRequester_ = 0U;
    uint32_t pendingReceiptPacketId_ = 0U;
    uint32_t pendingReceiptDueMs_ = 0U;
    uint8_t pendingReceiptChannel_ = 0U;

    DeviceRole localRole() const
    {
        return activeDeviceRoleOr(DeviceRole::UNCONFIGURED);
    }

    CacheSignature cacheSignature(uint32_t now)
    {
        CacheSignature signature;
        size_t offset = 0U;
        for (;;) {
            NodeStateRecord records[MAX_DIGEST_ENTRIES]{};
            const size_t count = nodeStateCache().snapshotPage(records, MAX_DIGEST_ENTRIES, offset, now);
            if (count == 0U)
                break;
            for (size_t i = 0; i < count; ++i) {
                const uint32_t item = recordFingerprint(records[i]);
                signature.xorHash ^= item;
                signature.sumHash += avalanche32(item ^ 0xa5a5a5a5U);
                if (signature.count != UINT16_MAX)
                    ++signature.count;
            }
            offset += count;
            if (count < MAX_DIGEST_ENTRIES)
                break;
        }
        signature.xorHash ^= avalanche32(static_cast<uint32_t>(signature.count) ^ 0x51c3e7a9U);
        signature.sumHash += avalanche32(static_cast<uint32_t>(signature.count) ^ 0x3d2f1b87U);
        return signature;
    }

    uint32_t responderBackoffMs() const
    {
        uint32_t base = 1200U;
        switch (localRole()) {
        case DeviceRole::TAK_REPEATER: base = 120U; break;
        case DeviceRole::DRONE_REPEATER: base = 260U; break;
        case DeviceRole::TAK: base = 560U; break;
        case DeviceRole::TAK_TRACKER: base = 900U; break;
        case DeviceRole::UNCONFIGURED:
        default: break;
        }
        const uint32_t self = nodeDB ? nodeDB->getNodeNum() : 0U;
        return base + ((self & 0x3fU) * 3U);
    }

    PeerState *peer(uint32_t nodeNum)
    {
        PeerState *empty = nullptr;
        PeerState *oldest = nullptr;
        for (auto &entry : peers_) {
            if (entry.nodeNum == nodeNum)
                return &entry;
            if (entry.nodeNum == 0U && !empty)
                empty = &entry;
            if (!oldest || entry.lastHelloEpoch < oldest->lastHelloEpoch)
                oldest = &entry;
        }
        PeerState *slot = empty ? empty : oldest;
        if (slot)
            *slot = PeerState{nodeNum, DeviceRole::UNCONFIGURED, 0U, 0U};
        return slot;
    }

    DeviceRole knownRole(uint32_t nodeNum)
    {
        for (const auto &entry : peers_)
            if (entry.nodeNum == nodeNum && entry.role != DeviceRole::UNCONFIGURED)
                return entry.role;
        return roleFromNativeNode(nodeNum);
    }

    PeerState *rememberPeer(uint32_t nodeNum, DeviceRole role, uint32_t seenEpoch)
    {
        PeerState *entry = peer(nodeNum);
        if (!entry)
            return nullptr;
        if (role != DeviceRole::UNCONFIGURED)
            entry->role = role;
        if (seenEpoch)
            entry->lastHelloEpoch = seenEpoch;
        nodeStateCache().updateRole(nodeNum, entry->role, seenEpoch ? seenEpoch : currentEpoch());
        return entry;
    }

    bool isSyncPayload(const uint8_t *payload, size_t size) const
    {
        return payload && size >= 8U && std::memcmp(payload, SYNC_MAGIC, sizeof(SYNC_MAGIC)) == 0 &&
               payload[4] == SYNC_VERSION;
    }

    void fillHeader(uint8_t *payload, SyncMessage type)
    {
        std::memcpy(payload, SYNC_MAGIC, sizeof(SYNC_MAGIC));
        payload[4] = SYNC_VERSION;
        payload[5] = static_cast<uint8_t>(type);
        payload[6] = static_cast<uint8_t>(localRole());
        payload[7] = 0U;
    }

    bool sendPayload(NodeNum to, uint8_t channel, const uint8_t *payload, size_t size,
                     meshtastic_MeshPacket_Priority priority = meshtastic_MeshPacket_Priority_BACKGROUND)
    {
        if (!payload || size == 0U || !router || !service)
            return false;
        meshtastic_MeshPacket *packet = router->allocForSending();
        if (!packet)
            return false;
        if (size > sizeof(packet->decoded.payload.bytes)) {
            packetPool.release(packet);
            return false;
        }
        packet->decoded.portnum = meshtastic_PortNum_PRIVATE_APP;
        packet->to = to;
        packet->channel = channel;
        packet->priority = priority;
        packet->decoded.want_response = false;
        std::memcpy(packet->decoded.payload.bytes, payload, size);
        packet->decoded.payload.size = size;
        service->sendToMesh(packet, RX_SRC_LOCAL, false);
        return true;
    }

    void sendReceiptRequest(uint32_t packetId)
    {
        if (packetId == 0U || !nodeDB)
            return;
        uint8_t payload[16]{};
        fillHeader(payload, SyncMessage::RECEIPT_REQUEST);
        writeU32(payload + 8U, nodeDB->getNodeNum());
        writeU32(payload + 12U, packetId);
        if (sendPayload(NODENUM_BROADCAST, 0U, payload, sizeof(payload), meshtastic_MeshPacket_Priority_RELIABLE))
            diagnosticLog("FINAL_ACK", "request packet=%08x", (unsigned)packetId);
    }

    void sendReceipt(uint32_t requester, uint8_t channel, uint32_t packetId)
    {
        if (requester == 0U || packetId == 0U)
            return;
        uint8_t payload[16]{};
        fillHeader(payload, SyncMessage::RECEIPT);
        writeU32(payload + 8U, requester);
        writeU32(payload + 12U, packetId);
        if (sendPayload(requester, channel, payload, sizeof(payload), meshtastic_MeshPacket_Priority_RELIABLE))
            diagnosticLog("FINAL_ACK", "confirm to=%08x packet=%08x", (unsigned)requester, (unsigned)packetId);
    }

    void scheduleReceipt(uint32_t requester, uint8_t channel, uint32_t packetId)
    {
        if (requester == 0U || packetId == 0U)
            return;
        pendingReceiptRequester_ = requester;
        pendingReceiptChannel_ = channel;
        pendingReceiptPacketId_ = packetId;
        pendingReceiptDueMs_ = millis() + responderBackoffMs();
        setIntervalFromNow(responderBackoffMs());
    }

    void sendHello()
    {
        // JARNSEN_STATE_SYNC_SIGNATURE_HELLO_V1
        // Backward-compatible extension: old peers accept the longer HELLO and
        // ignore the trailing metadata; new peers can skip a full digest when
        // both caches already represent the same state.
        const uint32_t now = currentEpoch();
        seedSelf(now);
        const CacheSignature signature = cacheSignature(now);
        uint8_t payload[HELLO_META_SIZE]{};
        fillHeader(payload, SyncMessage::HELLO);
        payload[8] = HELLO_META_VERSION;
        payload[9] = 0U;
        writeU16(payload + 10U, signature.count);
        writeU32(payload + 12U, signature.xorHash);
        writeU32(payload + 16U, signature.sumHash);
        if (sendPayload(NODENUM_BROADCAST, 0U, payload, sizeof(payload)))
            diagnosticLog("STATE_SYNC", "hello role=%s cache=%u sig=%08x/%08x", roleKey(localRole()),
                          (unsigned)signature.count, (unsigned)signature.xorHash, (unsigned)signature.sumHash);
    }

    void scheduleDigest(uint32_t requester, uint8_t channel)
    {
        if (requester == 0U)
            return;
        pendingDigestNode_ = requester;
        pendingDigestChannel_ = channel;
        pendingDigestDueMs_ = millis() + responderBackoffMs();
        setIntervalFromNow(responderBackoffMs());
    }

    void seedSelf(uint32_t now)
    {
        if (!nodeDB || now == 0U)
            return;
        const uint32_t self = nodeDB->getNodeNum();
        if (self == 0U || (localPosition.latitude_i == 0 && localPosition.longitude_i == 0) || localPosition.time == 0U)
            return;

        NodeStateRecord record;
        record.valid = true;
        record.nodeNum = self;
        // The GPS-solution timestamp is authoritative. position.time is only
        // the RTC/network time fallback and must never make an old fix look new.
        record.sourceEpoch = localPosition.timestamp ? localPosition.timestamp : localPosition.time;
        record.rxEpoch = now;
        record.lastSeenEpoch = now;
        record.latitudeI = localPosition.latitude_i;
        record.longitudeI = localPosition.longitude_i;
        record.role = localRole();
        record.kind = config.device.role == meshtastic_Config_DeviceConfig_Role_TAK_TRACKER ? NodeStateKind::ATAK_PLI
                                                                                            : NodeStateKind::POSITION;
        record.altitude = record.kind == NodeStateKind::ATAK_PLI && localPosition.has_altitude_hae
                              ? localPosition.altitude_hae
                              : localPosition.altitude;
        record.speedRaw = record.kind == NodeStateKind::ATAK_PLI
                              ? nativeSpeedToAtakCmS(localPosition.ground_speed)
                              : localPosition.ground_speed;
        record.courseCentiDeg = static_cast<uint16_t>(std::min<uint32_t>(36000U, localPosition.ground_track / 1000U));
        record.locationSource = static_cast<uint8_t>(localPosition.location_source);
        record.origin = NodeStateOrigin::DIRECT;
        record.movement = movementFromSpeed(localPosition.has_ground_speed, localPosition.ground_speed);
        nodeStateCache().note(record, now);
    }

    void capturePosition(const meshtastic_MeshPacket &mp)
    {
        meshtastic_Position position = meshtastic_Position_init_zero;
        if (!pb_decode_from_bytes(mp.decoded.payload.bytes, mp.decoded.payload.size, &meshtastic_Position_msg, &position))
            return;
        if ((position.latitude_i == 0 && position.longitude_i == 0) || (!position.has_latitude_i && !position.has_longitude_i))
            return;

        const uint32_t now = mp.rx_time ? mp.rx_time : currentEpoch();
        NodeStateRecord record;
        record.valid = true;
        record.nodeNum = mp.from;
        record.sourceEpoch = position.timestamp ? position.timestamp : (position.time ? position.time : now);
        record.rxEpoch = now;
        record.lastSeenEpoch = now;
        record.packetId = mp.id;
        record.latitudeI = position.latitude_i;
        record.longitudeI = position.longitude_i;
        record.altitude = position.has_altitude ? position.altitude : position.altitude_hae;
        record.speedRaw = position.ground_speed;
        record.courseCentiDeg = static_cast<uint16_t>(std::min<uint32_t>(36000U, position.ground_track / 1000U));
        record.locationSource = static_cast<uint8_t>(position.location_source);
        record.role = knownRole(mp.from);
        record.kind = NodeStateKind::POSITION;
        record.origin = NodeStateOrigin::DIRECT;
        record.movement = movementFromSpeed(position.has_ground_speed, position.ground_speed);

        if (nodeStateCache().note(record, now))
            diagnosticLog("STATE_CACHE", "direct position node=%08x source=%u expires=%u role=%s", (unsigned)record.nodeNum,
                          (unsigned)record.sourceEpoch, (unsigned)(record.sourceEpoch + nodeStateCacheTtlSecs(record.role, record.movement)),
                          roleKey(record.role));
    }

    void captureAtakPli(const meshtastic_MeshPacket &mp)
    {
        if (mp.decoded.payload.size < 2U || mp.decoded.payload.bytes[0] != 0xFFU)
            return;

        meshtastic_TAKPacketV2 tak = meshtastic_TAKPacketV2_init_zero;
        if (!pb_decode_from_bytes(mp.decoded.payload.bytes + 1U, mp.decoded.payload.size - 1U,
                                  &meshtastic_TAKPacketV2_msg, &tak))
            return;
        if (tak.cot_type_id != meshtastic_CotType_CotType_a_f_G_U_C ||
            (tak.latitude_i == 0 && tak.longitude_i == 0))
            return;

        const uint32_t now = mp.rx_time ? mp.rx_time : currentEpoch();
        NodeStateRecord record;
        record.valid = true;
        record.nodeNum = mp.from;
        record.sourceEpoch = now;
        record.rxEpoch = now;
        record.lastSeenEpoch = now;
        record.packetId = mp.id;
        record.latitudeI = tak.latitude_i;
        record.longitudeI = tak.longitude_i;
        record.altitude = tak.altitude;
        record.speedRaw = tak.speed;
        record.courseCentiDeg = tak.course;
        record.battery = tak.battery;
        record.takTeam = static_cast<uint8_t>(tak.team);
        record.takMemberRole = static_cast<uint8_t>(tak.role);
        record.locationSource = static_cast<uint8_t>(
            tak.geo_src == meshtastic_GeoPointSource_GeoPointSource_USER ? meshtastic_Position_LocSource_LOC_MANUAL
                                                                         : meshtastic_Position_LocSource_LOC_EXTERNAL);
        record.role = knownRole(mp.from);
        if (record.role == DeviceRole::UNCONFIGURED)
            record.role = DeviceRole::TAK_TRACKER;
        record.kind = NodeStateKind::ATAK_PLI;
        record.origin = NodeStateOrigin::DIRECT;
        record.movement = movementFromSpeed(true, tak.speed);

        if (nodeStateCache().note(record, now))
            diagnosticLog("STATE_CACHE", "direct tak node=%08x source=%u role=%s", (unsigned)record.nodeNum,
                          (unsigned)record.sourceEpoch, roleKey(record.role));
    }

    uint32_t nodeKnownEpoch(uint32_t nodeNum, uint32_t now)
    {
        uint32_t known = 0U;
        NodeStateRecord cached;
        if (nodeStateCache().find(nodeNum, cached) &&
            (now == 0U || cached.expiresEpoch == 0U || cached.expiresEpoch > now))
            known = cached.sourceEpoch;

        if (nodeDB) {
            meshtastic_PositionLite pos = meshtastic_PositionLite_init_zero;
            if (nodeDB->copyNodePosition(nodeNum, pos))
                known = std::max(known, pos.time);
        }
        return known;
    }

    void sendDigest(uint32_t to, uint8_t channel)
    {
        const uint32_t now = currentEpoch();
        seedSelf(now);
        const size_t count = nodeStateCache().count(now);
        const size_t pages = std::max<size_t>(1U, (count + MAX_DIGEST_ENTRIES - 1U) / MAX_DIGEST_ENTRIES);

        // JARNSEN_STATE_SYNC_PAGED_CACHE_V1
        // Materialize only one radio page at a time; the 128-node cache must
        // not create another full-cache temporary array on this thread stack.
        for (size_t page = 0; page < pages; ++page) {
            NodeStateRecord records[MAX_DIGEST_ENTRIES]{};
            const size_t start = page * MAX_DIGEST_ENTRIES;
            const size_t entries = nodeStateCache().snapshotPage(records, MAX_DIGEST_ENTRIES, start, now);
            uint8_t payload[12U + MAX_DIGEST_ENTRIES * 9U]{};
            fillHeader(payload, SyncMessage::DIGEST);
            payload[8] = static_cast<uint8_t>(entries);
            payload[9] = static_cast<uint8_t>(page);
            payload[10] = page + 1U < pages ? 1U : 0U;
            payload[11] = 0U;
            size_t offset = 12U;
            for (size_t i = 0; i < entries; ++i) {
                const auto &record = records[i];
                writeU32(payload + offset, record.nodeNum);
                writeU32(payload + offset + 4U, record.sourceEpoch);
                payload[offset + 8U] = static_cast<uint8_t>(record.kind);
                offset += 9U;
            }
            sendPayload(to, channel, payload, offset);
        }
        if (PeerState *entry = peer(to))
            entry->lastDigestMs = millis() ? millis() : 1U;
        diagnosticLog("STATE_SYNC", "digest to=%08x entries=%u pages=%u", (unsigned)to, (unsigned)count, (unsigned)pages);
    }

    void sendRequest(uint32_t to, uint8_t channel, const uint32_t *nodes, size_t count)
    {
        if (!nodes || count == 0U)
            return;
        uint8_t payload[9U + MAX_DIGEST_ENTRIES * 4U]{};
        fillHeader(payload, SyncMessage::REQUEST);
        const size_t limited = std::min(count, MAX_DIGEST_ENTRIES);
        payload[8] = static_cast<uint8_t>(limited);
        size_t offset = 9U;
        for (size_t i = 0; i < limited; ++i) {
            writeU32(payload + offset, nodes[i]);
            offset += 4U;
        }
        sendPayload(to, channel, payload, offset);
    }

    void sendRecord(uint32_t to, uint8_t channel, const NodeStateRecord &record)
    {
        uint8_t payload[50]{};
        fillHeader(payload, SyncMessage::RECORD);
        payload[8] = static_cast<uint8_t>(record.kind);
        payload[9] = static_cast<uint8_t>(record.role);
        payload[10] = static_cast<uint8_t>(record.movement);
        payload[11] = record.battery;
        payload[12] = record.locationSource;
        payload[13] = record.takTeam;
        payload[14] = record.takMemberRole;
        payload[15] = 0U;
        writeU32(payload + 16U, record.nodeNum);
        writeU32(payload + 20U, record.sourceEpoch);
        writeU32(payload + 24U, record.expiresEpoch);
        writeI32(payload + 28U, record.latitudeI);
        writeI32(payload + 32U, record.longitudeI);
        writeI32(payload + 36U, record.altitude);
        writeU32(payload + 40U, record.speedRaw);
        writeU16(payload + 44U, record.courseCentiDeg);
        writeU32(payload + 46U, record.packetId);
        sendPayload(to, channel, payload, sizeof(payload));
    }

    void handleSync(const meshtastic_MeshPacket &mp)
    {
        const uint8_t *payload = mp.decoded.payload.bytes;
        const size_t size = mp.decoded.payload.size;
        const auto type = static_cast<SyncMessage>(payload[5]);
        const DeviceRole senderRole = validRoleByte(payload[6]) ? static_cast<DeviceRole>(payload[6])
                                                                : DeviceRole::UNCONFIGURED;
        const uint32_t seen = mp.rx_time ? mp.rx_time : currentEpoch();
        PeerState *senderPeer = rememberPeer(mp.from, senderRole, seen);

        if (type == SyncMessage::DIGEST && pendingDigestNode_ != 0U && mp.to == pendingDigestNode_) {
            diagnosticLog("STATE_SYNC", "election lost requester=%08x responder=%08x", (unsigned)pendingDigestNode_,
                          (unsigned)mp.from);
            pendingDigestNode_ = 0U;
        }

        if (type == SyncMessage::RECEIPT_REQUEST) {
            if (size < 16U)
                return;
            const uint32_t sourceNode = readU32(payload + 8U);
            const uint32_t packetId = readU32(payload + 12U);
            NodeStateRecord record;
            if (sourceNode == mp.from && packetId != 0U && nodeStateCache().find(sourceNode, record) &&
                record.packetId == packetId) {
                scheduleReceipt(sourceNode, mp.channel, packetId);
            }
            return;
        }

        if (type == SyncMessage::RECEIPT) {
            if (size < 16U)
                return;
            const uint32_t sourceNode = readU32(payload + 8U);
            const uint32_t packetId = readU32(payload + 12U);

            // Suppress lower-priority responders when another JARNSEN node has
            // already acknowledged the same concrete position packet.
            if (pendingReceiptRequester_ == sourceNode && pendingReceiptPacketId_ == packetId)
                pendingReceiptRequester_ = 0U;

            if (nodeDB && sourceNode == nodeDB->getNodeNum() &&
                packetId != 0U && receiptExpectedPacketId_.load() == packetId) {
                receiptConfirmedPacketId_.store(packetId);
                diagnosticLog("FINAL_ACK", "received from=%08x packet=%08x", (unsigned)mp.from, (unsigned)packetId);
            }
            return;
        }

        if (type == SyncMessage::HELLO) {
            // JARNSEN_STATE_SYNC_HASH_GATE_V1
            // Legacy HELLOs have no signature, so they retain the old full
            // digest behavior. New peers only exchange a digest when their
            // cache differs, on first contact, or once every six hours.
            const uint32_t nowMs = millis();
            const bool fullDue = !senderPeer || senderPeer->lastDigestMs == 0U ||
                                 (uint32_t)(nowMs - senderPeer->lastDigestMs) >= FULL_RECONCILE_INTERVAL_MS;

            if (size < HELLO_META_SIZE || payload[8] != HELLO_META_VERSION) {
                diagnosticLog("STATE_SYNC", "hello peer=%08x action=digest reason=legacy", (unsigned)mp.from);
                scheduleDigest(mp.from, mp.channel);
                return;
            }

            const uint16_t remoteCount = readU16(payload + 10U);
            const uint32_t remoteXor = readU32(payload + 12U);
            const uint32_t remoteSum = readU32(payload + 16U);
            const uint32_t now = currentEpoch();
            seedSelf(now);
            const CacheSignature local = cacheSignature(now);
            const bool same = local.matches(remoteCount, remoteXor, remoteSum);

            if (same && !fullDue) {
                diagnosticLog("STATE_SYNC", "hello peer=%08x cache=%u action=skip reason=signature_equal",
                              (unsigned)mp.from, (unsigned)local.count);
                return;
            }

            diagnosticLog("STATE_SYNC", "hello peer=%08x local=%u remote=%u action=digest reason=%s",
                          (unsigned)mp.from, (unsigned)local.count, (unsigned)remoteCount,
                          same ? "six_hour_verify" : (fullDue ? "new_or_changed" : "signature_changed"));
            scheduleDigest(mp.from, mp.channel);
            return;
        }

        if (!nodeDB || mp.to != nodeDB->getNodeNum())
            return;

        if (type == SyncMessage::DIGEST) {
            if (size < 12U)
                return;
            const size_t count = std::min<size_t>(payload[8], MAX_DIGEST_ENTRIES);
            if (size < 12U + count * 9U)
                return;
            uint32_t wanted[MAX_DIGEST_ENTRIES]{};
            size_t wantedCount = 0U;
            const uint32_t now = currentEpoch();
            size_t offset = 12U;
            for (size_t i = 0; i < count; ++i) {
                const uint32_t node = readU32(payload + offset);
                const uint32_t remoteEpoch = readU32(payload + offset + 4U);
                if (node != 0U && remoteEpoch > nodeKnownEpoch(node, now))
                    wanted[wantedCount++] = node;
                offset += 9U;
            }
            sendRequest(mp.from, mp.channel, wanted, wantedCount);
            return;
        }

        if (type == SyncMessage::REQUEST) {
            if (size < 9U)
                return;
            const size_t count = std::min<size_t>(payload[8], MAX_DIGEST_ENTRIES);
            if (size < 9U + count * 4U)
                return;
            const uint32_t now = currentEpoch();
            for (size_t i = 0; i < count; ++i) {
                const uint32_t node = readU32(payload + 9U + i * 4U);
                NodeStateRecord record;
                if (nodeStateCache().find(node, record) &&
                    (now == 0U || record.expiresEpoch == 0U || record.expiresEpoch > now))
                    sendRecord(mp.from, mp.channel, record);
            }
            return;
        }

        if (type == SyncMessage::RECORD) {
            if (size < 50U || !validKindByte(payload[8]) || !validRoleByte(payload[9]) ||
                !validMovementByte(payload[10]))
                return;

            NodeStateRecord record;
            record.valid = true;
            record.kind = static_cast<NodeStateKind>(payload[8]);
            record.role = static_cast<DeviceRole>(payload[9]);
            record.movement = static_cast<NodeMovement>(payload[10]);
            record.battery = payload[11];
            record.locationSource = payload[12];
            record.takTeam = payload[13];
            record.takMemberRole = payload[14];
            record.nodeNum = readU32(payload + 16U);
            record.sourceEpoch = readU32(payload + 20U);
            record.expiresEpoch = readU32(payload + 24U);
            record.latitudeI = readI32(payload + 28U);
            record.longitudeI = readI32(payload + 32U);
            record.altitude = readI32(payload + 36U);
            record.speedRaw = readU32(payload + 40U);
            record.courseCentiDeg = readU16(payload + 44U);
            record.packetId = readU32(payload + 46U);
            record.rxEpoch = seen;
            record.origin = NodeStateOrigin::SYNC;

            const uint32_t now = currentEpoch();
            if (nodeStateCache().note(record, now)) {
                applySyncedRecord(record, mp.channel, now);
                diagnosticLog("STATE_SYNC", "accept node=%08x source=%u expires=%u via=%08x", (unsigned)record.nodeNum,
                              (unsigned)record.sourceEpoch, (unsigned)record.expiresEpoch, (unsigned)mp.from);
            }
        }
    }

    void applySyncedRecord(const NodeStateRecord &record, uint8_t channel, uint32_t now)
    {
        if (!nodeDB || record.nodeNum == 0U)
            return;

        meshtastic_PositionLite old = meshtastic_PositionLite_init_zero;
        const bool haveOld = nodeDB->copyNodePosition(record.nodeNum, old);
        if (haveOld && old.time > record.sourceEpoch)
            return;

        meshtastic_Position position = meshtastic_Position_init_zero;
        position.latitude_i = record.latitudeI;
        position.longitude_i = record.longitudeI;
        position.has_latitude_i = true;
        position.has_longitude_i = true;
        position.altitude = record.altitude;
        position.has_altitude = true;
        position.time = record.sourceEpoch;
        position.location_source =
            record.locationSource <= static_cast<uint8_t>(meshtastic_Position_LocSource_LOC_EXTERNAL)
                ? static_cast<meshtastic_Position_LocSource>(record.locationSource)
                : meshtastic_Position_LocSource_LOC_EXTERNAL;
        position.ground_speed = record.kind == NodeStateKind::ATAK_PLI
                                    ? atakSpeedToNativeCentiKmh(record.speedRaw)
                                    : record.speedRaw;
        position.has_ground_speed = true;
        position.ground_track = static_cast<uint32_t>(record.courseCentiDeg) * 1000U;
        position.has_ground_track = true;

        nodeDB->updatePosition(record.nodeNum, position, RX_SRC_RADIO);
        replayToPhone(record, position, channel, now);
    }

    void replayToPhone(const NodeStateRecord &record, const meshtastic_Position &position, uint8_t channel, uint32_t now)
    {
        if (!service)
            return;

        meshtastic_MeshPacket *packet = packetPool.allocZeroed(0);
        if (!packet)
            return;
        packet->which_payload_variant = meshtastic_MeshPacket_decoded_tag;
        packet->from = record.nodeNum;
        packet->to = nodeDB ? nodeDB->getNodeNum() : 0U;
        packet->channel = channel;
        packet->rx_time = record.sourceEpoch;

        if (record.kind == NodeStateKind::ATAK_PLI) {
            meshtastic_TAKPacketV2 tak = meshtastic_TAKPacketV2_init_zero;
            tak.cot_type_id = meshtastic_CotType_CotType_a_f_G_U_C;
            tak.latitude_i = record.latitudeI;
            tak.longitude_i = record.longitudeI;
            tak.altitude = record.altitude;
            tak.speed = record.speedRaw;
            tak.course = record.courseCentiDeg;
            tak.battery = record.battery;
            tak.team = static_cast<meshtastic_Team>(record.takTeam);
            tak.role = static_cast<meshtastic_MemberRole>(record.takMemberRole);
            tak.geo_src = record.locationSource == static_cast<uint8_t>(meshtastic_Position_LocSource_LOC_MANUAL)
                              ? meshtastic_GeoPointSource_GeoPointSource_USER
                              : meshtastic_GeoPointSource_GeoPointSource_NETWORK;
            tak.alt_src = tak.geo_src;
            const uint32_t remaining =
                record.expiresEpoch > now ? record.expiresEpoch - now : 1U;
            tak.stale_seconds = static_cast<uint16_t>(std::min<uint32_t>(remaining, UINT16_MAX));

            const meshtastic_NodeInfoLite *node = nodeDB ? nodeDB->getMeshNode(record.nodeNum) : nullptr;
            char fallback[16]{};
            std::snprintf(fallback, sizeof(fallback), "!%08x", (unsigned)record.nodeNum);
            const char *name = node && node->long_name[0] ? node->long_name : fallback;
            std::snprintf(tak.callsign, sizeof(tak.callsign), "%s", name);
            std::snprintf(tak.device_callsign, sizeof(tak.device_callsign), "%s", name);
            std::snprintf(tak.uid, sizeof(tak.uid), "!%08x", (unsigned)record.nodeNum);

            packet->decoded.portnum = meshtastic_PortNum_ATAK_PLUGIN_V2;
            packet->decoded.payload.bytes[0] = 0xFFU;
            const size_t encoded = pb_encode_to_bytes(packet->decoded.payload.bytes + 1U,
                                                      sizeof(packet->decoded.payload.bytes) - 1U,
                                                      &meshtastic_TAKPacketV2_msg, &tak);
            if (encoded == 0U) {
                packetPool.release(packet);
                return;
            }
            packet->decoded.payload.size = encoded + 1U;
        } else {
            packet->decoded.portnum = meshtastic_PortNum_POSITION_APP;
            const size_t encoded = pb_encode_to_bytes(packet->decoded.payload.bytes, sizeof(packet->decoded.payload.bytes),
                                                      &meshtastic_Position_msg, &position);
            if (encoded == 0U) {
                packetPool.release(packet);
                return;
            }
            packet->decoded.payload.size = encoded;
        }

        service->sendToPhone(packet);
    }
};

JarnsenNodeStateSyncModule *stateSyncModule = nullptr;

} // namespace

bool nodeStateSyncRequestPositionReceipt(uint32_t packetId)
{
    return stateSyncModule && stateSyncModule->requestPositionReceipt(packetId);
}

bool nodeStateSyncPositionReceiptConfirmed(uint32_t packetId)
{
    return stateSyncModule && stateSyncModule->positionReceiptConfirmed(packetId);
}

void nodeStateSyncCancelPositionReceipt()
{
    if (stateSyncModule)
        stateSyncModule->cancelPositionReceipt();
}

void nodeStateSyncInit()
{
    if (stateSyncModule)
        return;
    const DeviceRole role = activeDeviceRoleOr(DeviceRole::UNCONFIGURED);
    if (role == DeviceRole::UNCONFIGURED)
        return;
    stateSyncModule = new JarnsenNodeStateSyncModule();
    diagnosticLog("STATE_SYNC", "init role=%s stationary_tak_ttl=%us", roleKey(role),
                  (unsigned)JARNSEN_TAK_STATIONARY_CACHE_SECS);
}

} // namespace jarnsen
