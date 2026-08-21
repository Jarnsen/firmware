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

// Called directly from PhoneAPI before Router/PositionModule can rewrite a
// phone-originated POSITION_APP packet. This is deliberately separate from UI.
void heltecV3CapturePhoneMeshPacket(const meshtastic_MeshPacket &packet);

// Position policy data consumed by the native Meshtastic UI page.
bool heltecV3GetPositionUiState(HeltecV3PositionUiState &state);
bool heltecV3ManualSaveLatestPosition();

// Native Meshtastic position page helpers.
void heltecV3PositionPageRequestFocus();
void heltecV3PositionPageRefresh();
bool heltecV3PositionPageRecentlyVisible();
