#pragma once

#include <stdint.h>

namespace jarnsen
{

struct DroneRepeaterStats {
    bool active = false;
    bool gpsConnected = false;
    bool gpsFix = false;
    bool serviceActive = false;
    bool usbPowered = false;
    uint8_t satsInView = 0;
    uint16_t speedKmhX10 = 0;
    uint16_t channelUtilizationX10 = 0;
    uint32_t dynamicPositionIntervalSecs = 0;
    uint32_t positionTxCount = 0;
    uint32_t gpsRecoveryCount = 0;
    uint32_t lastPositionTxAgeSecs = UINT32_MAX;
    uint32_t minFreeHeap = 0;
};

bool droneRepeaterRoleActive();
bool droneRepeaterApplyBaseConfig(bool persist);
void droneRepeaterRuntimeInit();
DroneRepeaterStats droneRepeaterStats();

} // namespace jarnsen
