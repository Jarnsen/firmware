#pragma once

#include <stddef.h>
#include <stdint.h>

namespace jarnsen
{

// Shared SOC/time learner for JARNSEN boards that do not currently have a
// dedicated current sensor. It deliberately mirrors Tracker V1.1's proven
// discharge-rate / remaining-runtime algorithm while never inventing
// current, power or mAh values without real measurement hardware.
struct BatteryLearningStats {
    bool supported = false;
    bool batteryValid = false;
    bool usbPowered = false;
    bool charging = false;
    bool estimateReady = false;
    uint16_t voltageMv = 0;
    uint8_t batteryPercent = 0;
    uint32_t dischargeRateMilliPercentPerHour = 0;
    uint32_t remainingSecs = 0;
    uint32_t measuredSecs = 0;
    uint16_t observations = 0;
};

void batteryLearningInit();
void batteryLearningTick();
void batteryLearningPersist();
BatteryLearningStats batteryLearningStats();
void batteryLearningFormatDuration(uint32_t seconds, char *out, size_t outSize);
void batteryLearningFormatCompactDuration(uint32_t seconds, char *out, size_t outSize);

} // namespace jarnsen
