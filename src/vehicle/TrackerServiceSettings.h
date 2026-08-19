#pragma once

#include <stdint.h>

#if defined(HELTEC_TRACKER_V1_1)

void trackerServiceSettingsInit();
void trackerApplyPositionSettings();

uint8_t trackerMotionSensitivityIndex();
const char *trackerMotionSensitivityName();
uint8_t trackerMotionConfirmCount();
uint32_t trackerMotionConfirmWindowMs();

uint16_t trackerSmartDistanceM();
uint16_t trackerSmartIntervalSecs();
uint16_t trackerParkIntervalMinutes();
uint32_t trackerParkIntervalSecs();

void trackerCycleMotionSensitivity();
void trackerCycleSmartDistance();
void trackerCycleSmartInterval();
void trackerCycleParkInterval();

#endif
