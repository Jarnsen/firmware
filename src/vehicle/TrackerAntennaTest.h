#pragma once

#include "configuration.h"
#include "mesh/generated/meshtastic/mesh.pb.h"

#include <cstdint>

#if defined(HELTEC_TRACKER_V1_1)

enum class TrackerAntennaPhase : uint8_t {
    IDLE = 0,
    A_RUNNING = 1,
    A_SAVED = 2,
    B_RUNNING = 3,
    COMPLETE = 4,
    SWAP_LOCKED = 5,
};

struct TrackerAntennaResult {
    bool valid = false;
    uint16_t samples = 0;
    int16_t medianRssiDbm = 0;
    int16_t medianSnrQ4 = 0;
};

struct TrackerAntennaState {
    TrackerAntennaPhase phase = TrackerAntennaPhase::IDLE;
    uint32_t referenceNode = 0;
    char referenceName[8] = {};
    uint16_t liveSamples = 0;
    uint32_t liveSeconds = 0;
    bool txLocked = false;
    bool txSafeToSwap = false;
    TrackerAntennaResult a;
    TrackerAntennaResult b;
    int16_t deltaRssiDb = 0;
    int16_t deltaSnrQ4 = 0;
};

// Called early by TrackerCommonPolicy. Until initialization completes, TAK /
// TAK_TRACKER TX is fail-safe blocked so no startup packet can bypass a saved
// antenna-swap lock from the previous boot.
void trackerAntennaTestInit();

// Passive physical-LoRa RX observer. It never changes routing/rebroadcasting.
void trackerAntennaOnRadioPacket(const meshtastic_MeshPacket &packet);

TrackerAntennaState trackerAntennaState();

// One explicit user action from System -> Antenna Test. The state machine is:
// IDLE -> A_RUNNING -> A_SAVED -> SWAP_LOCKED -> B_RUNNING -> COMPLETE.
// SAVE A does not lock TX. A second deliberate action enters SWAP_LOCKED.
bool trackerAntennaHandleAction();

// Central radio safety gate. New TX is rejected at send(), and queued packets
// are gated again immediately before RadioLib startTransmit().
bool trackerAntennaTxLocked();
bool trackerAntennaTxSafeToSwap();

const char *trackerAntennaPhaseText(TrackerAntennaPhase phase);

#else

inline void trackerAntennaTestInit() {}
inline void trackerAntennaOnRadioPacket(const meshtastic_MeshPacket &) {}
inline bool trackerAntennaTxLocked()
{
    return false;
}
inline bool trackerAntennaTxSafeToSwap()
{
    return false;
}

#endif
