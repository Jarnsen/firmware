#pragma once

#include <cstdint>

#if defined(HELTEC_TRACKER_V1_1)

struct TrackerServiceHealthStats {
    uint32_t bootCount = 0;
    uint32_t crashResetCount = 0;
    uint32_t serviceOpenCount = 0;
    uint32_t bleConnectionCount = 0;
    uint32_t wlanStartCount = 0;
    uint32_t wlanFailureCount = 0;
};

void trackerServiceUpgradeInit();
void trackerServiceUpgradeTick();
bool trackerServiceUpgradeRequestWlan();
void trackerServiceUpgradeNoteServiceOpen();
TrackerServiceHealthStats trackerServiceUpgradeHealth();
const char *trackerServiceUpgradeResetReasonText();

#else

inline void trackerServiceUpgradeInit() {}
inline void trackerServiceUpgradeTick() {}
inline bool trackerServiceUpgradeRequestWlan() { return false; }
inline void trackerServiceUpgradeNoteServiceOpen() {}
inline TrackerServiceHealthStats trackerServiceUpgradeHealth() { return {}; }
inline const char *trackerServiceUpgradeResetReasonText() { return "N/A"; }

#endif
