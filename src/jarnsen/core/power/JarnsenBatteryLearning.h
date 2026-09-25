#pragma once

#include <stddef.h>
#include <stdint.h>

namespace jarnsen
{

// Battery learning shared with the Heltec V3 operator UI.  The V3 has no
// dedicated current sensor in the present hardware configuration, therefore
// this learner intentionally uses the same SOC/time discharge-rate algorithm
// that Tracker V1.1 already uses for its remaining-time estimate.  It never
// invents mAh/current/power values.
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
