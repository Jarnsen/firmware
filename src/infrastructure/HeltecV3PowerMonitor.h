#pragma once

#include "configuration.h"

#include <stddef.h>
#include <stdint.h>

#if defined(_VARIANT_HELTEC_V3)

enum class HeltecV3PowerSource : uint8_t {
    INTERNAL = 0,
    INA226 = 1,
};

struct HeltecV3PowerStats {
    HeltecV3PowerSource source;
    bool batteryValid;
    bool usbPowered;
    bool charging;
    uint16_t voltageMv;
    uint8_t batteryPercent;

    bool estimateReady;
    uint32_t remainingSecs;
    uint32_t dischargeRateMilliPercentPerHour;

    uint32_t measuredSecs;
    uint32_t listenSecs;
    uint32_t serviceSecs;
    uint32_t bleSecs;
    uint32_t displaySecs;
    uint32_t positionTxCount;

    // Reserved INA226-facing fields. They remain invalid while the V3 is using
    // the internal Meshtastic battery source. A later INA226 backend can fill
    // these without changing the menu, persistence model or learning UI.
    bool inaPresent;
    uint16_t inaBusVoltageMv;
    bool vbusValid;
    bool currentValid;
    bool energyValid;
    int32_t currentMa;
    uint32_t powerMw;
    uint32_t consumedMah;
    uint32_t consumedMwh;
    int32_t listenAvgMa;
    int32_t serviceAvgMa;
    int32_t bleAvgMa;
    int32_t displayAvgMa;
};

void heltecV3PowerMonitorInit();
void heltecV3PowerMonitorTick(bool listening, bool serviceActive, bool bleActive, bool displayActive);
void heltecV3PowerMonitorNotePositionTx();
void heltecV3PowerMonitorPersist();
HeltecV3PowerStats heltecV3PowerMonitorStats();
const char *heltecV3PowerMonitorSourceText();
void heltecV3PowerFormatDuration(uint32_t seconds, char *out, size_t outSize);

#endif
