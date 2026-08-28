#include "drone/DroneMeshHealth.h"

#if defined(HELTEC_TRACKER_V1_1) && defined(JARNSEN_DRONE_REPEATER_BUILD)

#include "drone/DronePowerMonitor.h"

#include <Arduino.h>

namespace
{
constexpr size_t MAX_NODES = 96;
constexpr size_t RX_HISTORY = 384;

struct NodeSeen {
    uint32_t node = 0;
    uint32_t lastSeenMs = 0;
    uint32_t lastDirectMs = 0;
};

NodeSeen nodes[MAX_NODES] = {};
uint32_t rxHistory[RX_HISTORY] = {};
size_t rxHistoryWrite = 0;
uint32_t totalRx = 0;
uint32_t lastDirectMs = 0;
uint32_t lastDirectNode = 0;
int16_t lastDirectRssiDbm = 0;
float lastDirectSnrDb = 0.0f;

bool isDirectPacket(const meshtastic_MeshPacket &packet)
{
    return packet.hop_start > 0 && packet.hop_limit == packet.hop_start;
}

NodeSeen &slotFor(uint32_t node)
{
    size_t empty = MAX_NODES;
    size_t oldest = 0;
    uint32_t oldestTime = UINT32_MAX;
    for (size_t i = 0; i < MAX_NODES; ++i) {
        if (nodes[i].node == node)
            return nodes[i];
        if (nodes[i].node == 0 && empty == MAX_NODES)
            empty = i;
        if (nodes[i].lastSeenMs < oldestTime) {
            oldestTime = nodes[i].lastSeenMs;
            oldest = i;
        }
    }
    const size_t index = empty != MAX_NODES ? empty : oldest;
    nodes[index] = {};
    nodes[index].node = node;
    return nodes[index];
}

uint32_t ageSecs(uint32_t now, uint32_t timestamp)
{
    return timestamp == 0 ? UINT32_MAX : (now - timestamp) / 1000UL;
}
}

void droneMeshHealthOnRadioPacket(const meshtastic_MeshPacket &packet)
{
    if (packet.from == 0)
        return;

    const uint32_t now = millis() ? millis() : 1;
    NodeSeen &entry = slotFor(packet.from);
    entry.lastSeenMs = now;

    if (isDirectPacket(packet)) {
        entry.lastDirectMs = now;
        lastDirectMs = now;
        lastDirectNode = packet.from;
        lastDirectRssiDbm = packet.rx_rssi;
        lastDirectSnrDb = packet.rx_snr;
    }

    rxHistory[rxHistoryWrite++ % RX_HISTORY] = now;
    totalRx++;
    dronePowerMonitorNoteRadioRx();
}

DroneMeshHealthSummary droneMeshHealthSummary()
{
    DroneMeshHealthSummary out{};
    const uint32_t now = millis();
    out.totalRx = totalRx;
    out.lastDirectNode = lastDirectNode;
    out.lastDirectRssiDbm = lastDirectRssiDbm;
    out.lastDirectSnrDb = lastDirectSnrDb;
    out.lastDirectAgeSecs = ageSecs(now, lastDirectMs);

    for (const auto &entry : nodes) {
        if (entry.node == 0)
            continue;
        out.observedNodes++;
        const uint32_t seenAge = ageSecs(now, entry.lastSeenMs);
        if (seenAge <= 15UL * 60UL)
            out.active15m++;
        if (seenAge <= 60UL * 60UL)
            out.active1h++;
        if (seenAge <= 24UL * 60UL * 60UL)
            out.active24h++;
        const uint32_t directAge = ageSecs(now, entry.lastDirectMs);
        if (directAge <= 15UL * 60UL)
            out.direct15m++;
    }

    for (const uint32_t timestamp : rxHistory) {
        if (timestamp != 0 && (uint32_t)(now - timestamp) <= 60UL * 60UL * 1000UL)
            out.rx1h++;
    }
    return out;
}

#endif
