#pragma once

#include "MeshService.h"

#include <cstdint>

#ifdef DEG_TO_RAD
#undef DEG_TO_RAD
#endif

bool heltecV3RuntimeRoleEnabled();
bool heltecV3RuntimeServiceActive();
bool heltecV3RuntimeSetBleQueueHold(bool active);
void heltecV3RuntimeSetPairingDisplay(bool active);
bool heltecV3RuntimeUsbMaintenanceActive();
const char *heltecV3RuntimeStateText();
const char *heltecV3RuntimeBleStateText();
uint32_t heltecV3RuntimeServiceRemainingSecs();
