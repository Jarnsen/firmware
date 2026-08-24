#pragma once

void setupTrackerCommonPolicy();
bool trackerCommonScreenPowerAllowed(bool on);
void trackerCommonBleActivity();
bool trackerCommonServiceActive();
void trackerCommonSetPairingDisplay(bool active);
const char *trackerCommonRuntimeState();
bool trackerCommonIsParked();
bool trackerCommonParkGpsSearchPending();
uint32_t trackerCommonParkNextTxSecs();
