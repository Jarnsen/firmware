#pragma once

void setupTrackerCommonPolicy();
bool trackerCommonScreenPowerAllowed(bool on);
void trackerCommonBleActivity();
const char *trackerCommonRuntimeState();
bool trackerCommonIsParked();
bool trackerCommonParkGpsSearchPending();
uint32_t trackerCommonParkNextTxSecs();
