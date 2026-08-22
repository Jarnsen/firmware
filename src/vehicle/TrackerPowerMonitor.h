#pragma once

#include <stddef.h>
#include <stdint.h>

#if defined(HELTEC_TRACKER_V1_1)

struct TrackerPowerStats {
    bool batteryValid;
    bool usbPowered;
    bool charging;
    uint16_t voltageMv;
    uint8_t batteryPercent;
    bool estimateReady;
    uint32_t remainingSecs;
    uint32_t measuredSecs;
    uint32_t movingSecs;
    uint32_t parkedSecs;
    uint32_t gnssSecs;
    uint32_t bleSecs;
    uint32_t displaySecs;
    uint32_t otherSecs;
    uint32_t positionTxCount;
    uint32_t dischargeRateMilliPercentPerHour;
};

void trackerPowerMonitorInit();
void trackerPowerMonitorTick(bool moving, bool parked, bool gnssActive, bool bleActive, bool displayActive);
void trackerPowerMonitorNotePositionTx();
void trackerPowerMonitorPersist();
TrackerPowerStats trackerPowerMonitorStats();
void trackerPowerFormatDuration(uint32_t seconds, char *out, size_t outSize);

#endif
