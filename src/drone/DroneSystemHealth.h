#pragma once

#include <stdint.h>

#if defined(HELTEC_TRACKER_V1_1) && defined(JARNSEN_DRONE_REPEATER_BUILD)

struct DroneSystemHealthStats {
    uint32_t bootCount = 0;
    uint32_t crashResetCount = 0;
    uint32_t gpsRecoveryCount = 0;
    uint32_t bleRecoveryCount = 0;
    uint32_t loraRecoveryCount = 0;
    uint32_t minFreeHeap = 0;
    bool lastResetWasCrash = false;
};

void droneSystemHealthInit();
void droneSystemHealthTick();
void droneSystemHealthNoteGpsRecovery();
void droneSystemHealthNoteBleRecovery();
void droneSystemHealthNoteLoraRecovery();
DroneSystemHealthStats droneSystemHealthStats();
const char *droneSystemHealthStatusText();
const char *droneSystemHealthResetReasonText();

#endif
