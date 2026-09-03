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
    uint32_t dischargeRateMilliPercentPerHour;

    uint32_t measuredSecs;
    uint32_t movingSecs;
    uint32_t parkedSecs;
    uint32_t gnssSecs;
    uint32_t bleSecs;
    uint32_t displaySecs;
    uint32_t otherSecs;
    uint32_t positionTxCount;

    bool inaConfigured;
    bool inaPresent;
    bool inaValid;
    uint16_t inaBusVoltageMv;
    bool vbusValid;
    int32_t currentMilliAmpsX10;
    int32_t powerMilliWattsX10;
    uint32_t dischargedMahX10;
    uint32_t dischargedMwhX10;
    uint32_t awakeMeasuredMahX10;
    uint32_t awakeMeasuredMwhX10;
    uint32_t sleepEstimatedMahX10;
    uint32_t sleepEstimatedMwhX10;
    uint32_t lightSleepSecs;
    uint32_t deepSleepSecs;
    int32_t lightSleepMilliAmpsX10;
    int32_t deepSleepMilliAmpsX10;

    bool capacityReady;
    uint32_t learnedCapacityMah;
    uint32_t remainingCapacityMah;
    uint8_t capacityConfidence;
    uint16_t capacityCycles;
};

void trackerPowerMonitorInit();
void trackerPowerMonitorTick(bool moving, bool parked, bool gnssActive, bool bleActive, bool displayActive);
void trackerPowerMonitorNotePositionTx();
void trackerPowerMonitorPersist();
void trackerPowerMonitorPrepareForLightSleep();
void trackerPowerMonitorCompleteLightSleep();
void trackerPowerMonitorPrepareForDeepSleep(uint32_t plannedSleepSecs);
TrackerPowerStats trackerPowerMonitorStats();
void trackerPowerFormatDuration(uint32_t seconds, char *out, size_t outSize);

#endif
