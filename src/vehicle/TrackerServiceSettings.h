#pragma once

#include <stddef.h>
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
uint32_t trackerEffectiveParkIntervalSecs();
void trackerFormatParkInterval(char *out, size_t outSize);

bool trackerSetMotionSensitivityIndex(uint8_t index);
bool trackerSetSmartDistanceM(uint16_t meters);
bool trackerSetSmartIntervalSecs(uint16_t seconds);
bool trackerSetParkIntervalMinutes(uint16_t minutes);

void trackerCycleMotionSensitivity();
void trackerCycleSmartDistance();
void trackerCycleSmartInterval();
void trackerCycleParkInterval();

#endif
