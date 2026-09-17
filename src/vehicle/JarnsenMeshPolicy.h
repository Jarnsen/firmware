#pragma once

#include <stdint.h>

#if defined(HELTEC_TRACKER_V1_1)

void jarnsenMeshPolicyInit();
void jarnsenMeshPolicyEnforce();
bool jarnsenNeighborInfoEnabled();
void jarnsenSetNeighborInfoEnabled(bool enabled);

#endif
