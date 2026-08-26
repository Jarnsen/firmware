#pragma once

#include "configuration.h"
#include "mesh-pb-constants.h"

#include <cstdint>

struct HeltecV3PositionUiState {
    bool serviceActive = false;
    bool haveSavedPosition = false;
    bool havePhonePosition = false;
    bool phoneFresh = false;
    bool phoneAccurate = false;
    bool lastSaveValid = false;
    bool lastSaveAutomatic = false;
    bool lastSaveMeshSent = false;

    int32_t savedLatitudeI = 0;
    int32_t savedLongitudeI = 0;
    int32_t phoneLatitudeI = 0;
    int32_t phoneLongitudeI = 0;

    uint32_t differenceM = 0;
    uint32_t accuracyMm = 0;
    uint32_t phoneAgeSecs = UINT32_MAX;
    uint32_t lastSavedDifferenceM = 0;
    uint32_t lastSaveAgeMs = UINT32_MAX;

    uint8_t autoConfirmCount = 0;
    uint8_t autoConfirmRequired = 0;
    uint16_t ignoreDistanceM = 25;
    uint16_t autoDistanceM = 50;
};

struct HeltecV3PhoneMotionState {
    bool available = false;
    bool moving = false;
    bool stabilizing = false;
    bool stationaryConfirmed = false;

    uint8_t stabilizingCount = 0;
    uint8_t stabilizingRequired = 3;
    uint32_t movementStepM = 0;
    uint32_t stabilizingElapsedSecs = 0;
    uint32_t stabilizingRemainingSecs = 0;
};

struct HeltecV3PhoneEstimateUiState {
    bool available = false;
    bool reportedAccuracyValid = false;
    bool estimatedAccuracyValid = false;
    bool fixedDifferenceValid = false;
    bool phoneTimestampStale = false;
    bool manualSaveAvailable = false;
    bool lastManualSaveValid = false;
    bool lastManualSaveMeshSent = false;
    bool moving = false;
    bool stabilizing = false;

    int32_t latitudeI = 0;
    int32_t longitudeI = 0;

    uint32_t reportedAccuracyM = 0;
    uint32_t estimatedAccuracyM = 0;
    uint32_t fixedDifferenceM = 0;
    uint32_t movementStepM = 0;
    uint32_t phoneAgeSecs = UINT32_MAX;
    uint32_t lastManualSaveAgeMs = UINT32_MAX;
    uint32_t stabilizingElapsedSecs = 0;
    uint32_t stabilizingRemainingSecs = 0;
    uint8_t sampleCount = 0;
    uint8_t stabilizingCount = 0;
    uint8_t stabilizingRequired = 3;
};

// Called directly from PhoneAPI after authorization but before Router and the
// normal PositionModule can rewrite a phone-originated POSITION_APP payload.
void heltecV3CapturePhonePosition(const meshtastic_Position &position);

// Position policy data consumed by the native Meshtastic UI page.
bool heltecV3GetPositionUiState(HeltecV3PositionUiState &state);
bool heltecV3ManualSaveLatestPosition();

// Shared phone-motion state. The manager owns this state and both the live
// position policy and OLED quality estimator consume it. Exact duplicate
// coordinates can provide stationary evidence over time, but never count as
// independent accuracy samples.
void heltecV3PhoneMotionObserve(const meshtastic_Position &position, bool requireStationaryConfirmation);
bool heltecV3GetPhoneMotionState(HeltecV3PhoneMotionState &state);
void heltecV3PhonePositionAcceptFixed(const meshtastic_Position &position);

// Independent phone-fix quality estimate. Actual phone-reported accuracy is
// preferred; otherwise stationary scatter from distinct fixes is estimated.
bool heltecV3GetPhoneEstimateUiState(HeltecV3PhoneEstimateUiState &state);

// Native Meshtastic position page helpers.
void heltecV3PositionPageRequestFocus();
void heltecV3PositionPageRefresh();
bool heltecV3PositionPageRecentlyVisible();
