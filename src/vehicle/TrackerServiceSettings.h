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
uint16_t trackerMovingGnssSecs();
uint16_t trackerParkGpsSearchSecs();
uint16_t trackerBleIdleTimeoutSecs();
uint16_t trackerBleHardTimeoutSecs();
uint16_t trackerParkIntervalMinutes();
uint32_t trackerParkIntervalSecs();
uint32_t trackerEffectiveParkIntervalSecs();
void trackerFormatParkInterval(char *out, size_t outSize);

bool trackerIna226Enabled();

bool trackerSetMotionSensitivityIndex(uint8_t index);
bool trackerSetSmartDistanceM(uint16_t meters);
bool trackerSetSmartIntervalSecs(uint16_t seconds);
bool trackerSetMovingGnssSecs(uint16_t seconds);
bool trackerSetParkGpsSearchSecs(uint16_t seconds);
bool trackerSetBleIdleTimeoutSecs(uint16_t seconds);
bool trackerSetBleHardTimeoutSecs(uint16_t seconds);
bool trackerSetParkIntervalMinutes(uint16_t minutes);
bool trackerSetIna226Enabled(bool enabled);

void trackerCycleMotionSensitivity();
void trackerCycleSmartDistance();
void trackerCycleSmartInterval();
void trackerCycleParkInterval();

#endif
