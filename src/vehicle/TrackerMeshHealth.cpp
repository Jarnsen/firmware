#include "vehicle/TrackerMeshHealth.h"
#include "configuration.h"

#if defined(HELTEC_TRACKER_V1_1)

#include "NodeDB.h"
#include <Arduino.h>
#include <cmath>

namespace
{
constexpr size_t MAX_ACTIVE_NODES = 64;
constexpr size_t MAX_DIRECT_NODES = 24;
constexpr uint32_t MINUTE_MS = 60UL * 1000UL;

struct ActiveNode {
    uint32_t nodeNum = 0;
    uint32_t lastSeenMs = 0;
};

struct DirectNode {
    uint32_t nodeNum = 0;
    uint32_t lastSeenMs = 0;
    int16_t rssiDbm = 0;
    int16_t snrQ4 = 0;
};

struct RxMinuteBucket {
    uint32_t minuteTag = UINT32_MAX;
    uint32_t count = 0;
};

ActiveNode activeNodes[MAX_ACTIVE_NODES];
DirectNode directNodes[MAX_DIRECT_NODES];
RxMinuteBucket rxMinutes[60];
uint32_t totalPhysicalRx = 0;
uint32_t lastDirectNode = 0;
uint32_t lastDirectMs = 0;
int16_t lastDirectRssi = 0;
int16_t lastDirectSnrQ4 = 0;

bool roleEnabled()
{
    return config.device.role == meshtastic_Config_DeviceConfig_Role_TAK ||
           config.device.role == meshtastic_Config_DeviceConfig_Role_TAK_TRACKER;
}

bool packetDirect(const meshtastic_MeshPacket &packet)
{
    return !packet.via_mqtt && packet.hop_start > 0 && packet.hop_limit == packet.hop_start;
}

void noteActive(uint32_t nodeNum, uint32_t now)
{
    if (nodeNum == 0 || (nodeDB && nodeNum == nodeDB->getNodeNum()))
        return;
    ActiveNode *empty = nullptr;
    ActiveNode *oldest = &activeNodes[0];
    uint32_t oldestAge = 0;
    for (auto &entry : activeNodes) {
        if (entry.nodeNum == nodeNum) {
            entry.lastSeenMs = now ? now : 1U;
            return;
        }
        if (entry.nodeNum == 0 && !empty)
            empty = &entry;
        const uint32_t age = entry.nodeNum ? (uint32_t)(now - entry.lastSeenMs) : UINT32_MAX;
        if (age >= oldestAge) {
            oldestAge = age;
            oldest = &entry;
        }
    }
    ActiveNode *target = empty ? empty : oldest;
    target->nodeNum = nodeNum;
    target->lastSeenMs = now ? now : 1U;
}

void noteDirect(uint32_t nodeNum, int16_t rssi, int16_t snrQ4, uint32_t now)
{
    DirectNode *empty = nullptr;
    DirectNode *oldest = &directNodes[0];
    uint32_t oldestAge = 0;
    for (auto &entry : directNodes) {
        if (entry.nodeNum == nodeNum) {
            entry.lastSeenMs = now ? now : 1U;
            entry.rssiDbm = rssi;
            entry.snrQ4 = snrQ4;
            return;
        }
        if (entry.nodeNum == 0 && !empty)
            empty = &entry;
        const uint32_t age = entry.nodeNum ? (uint32_t)(now - entry.lastSeenMs) : UINT32_MAX;
        if (age >= oldestAge) {
            oldestAge = age;
            oldest = &entry;
        }
    }
    DirectNode *target = empty ? empty : oldest;
    target->nodeNum = nodeNum;
    target->lastSeenMs = now ? now : 1U;
    target->rssiDbm = rssi;
    target->snrQ4 = snrQ4;
}

void noteRxMinute(uint32_t now)
{
    const uint32_t tag = now / MINUTE_MS;
    RxMinuteBucket &bucket = rxMinutes[tag % 60U];
    if (bucket.minuteTag != tag) {
        bucket.minuteTag = tag;
        bucket.count = 0;
    }
    bucket.count++;
}

uint32_t rxLastHour(uint32_t now)
{
    const uint32_t current = now / MINUTE_MS;
    uint32_t total = 0;
    for (const auto &bucket : rxMinutes) {
        if (bucket.minuteTag != UINT32_MAX && current >= bucket.minuteTag && current - bucket.minuteTag < 60U)
            total += bucket.count;
    }
    return total;
}
} // namespace

void trackerMeshHealthOnRadioPacket(const meshtastic_MeshPacket &packet)
{
    if (!roleEnabled())
        return;
    const uint32_t now = millis();
    totalPhysicalRx++;
    noteRxMinute(now);
    noteActive(packet.from, now);

    if (!packetDirect(packet))
        return;

    const int16_t rssi = (int16_t)packet.rx_rssi;
    const int16_t snrQ4 = (int16_t)lroundf(packet.rx_snr * 4.0f);
    noteDirect(packet.from, rssi, snrQ4, now);
    lastDirectNode = packet.from;
    lastDirectMs = now ? now : 1U;
    lastDirectRssi = rssi;
    lastDirectSnrQ4 = snrQ4;
}

TrackerMeshHealthSummary trackerMeshHealthSummary()
{
    TrackerMeshHealthSummary out{};
    if (!roleEnabled())
        return out;

    const uint32_t now = millis();
    for (const auto &entry : activeNodes) {
        if (!entry.nodeNum)
            continue;
        out.observedNodes++;
        const uint32_t age = (uint32_t)(now - entry.lastSeenMs);
        if (age <= 15UL * 60UL * 1000UL)
            out.active15m++;
        if (age <= 60UL * 60UL * 1000UL)
            out.active1h++;
        if (age <= 24UL * 60UL * 60UL * 1000UL)
            out.active24h++;
    }
    for (const auto &entry : directNodes) {
        if (entry.nodeNum && (uint32_t)(now - entry.lastSeenMs) <= 15UL * 60UL * 1000UL)
            out.direct15m++;
    }
    out.rx1h = rxLastHour(now);
    out.totalRx = totalPhysicalRx;
    out.lastDirectNode = lastDirectNode;
    out.lastDirectRssiDbm = lastDirectRssi;
    out.lastDirectSnrQ4 = lastDirectSnrQ4;
    out.lastDirectAgeSecs = lastDirectMs ? (uint32_t)(now - lastDirectMs) / 1000UL : UINT32_MAX;
    return out;
}

#endif
