#pragma once

#include <stdint.h>

#if defined(HELTEC_TRACKER_V1_1)

void setupTrackerEnhancements();

uint32_t trackerLearnedTtffMs();
uint32_t trackerLastFixAgeSecs();
uint32_t trackerEnhancementBootCount();
bool trackerMotionSensorSuspect();
uint32_t trackerMotionSensorMissedMovementEvents();
const char *trackerMotionSensorStatus();
const char *trackerBootWakeReason();

#endif
