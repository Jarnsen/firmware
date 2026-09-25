#pragma once

#include <stdint.h>

namespace jarnsen
{

enum class TakRepeaterPositionMode : uint8_t {
    FIXED = 0,
    MOBILE,
    NO_POSITION,
};

struct TakRepeaterStats {
    bool active = false;
    TakRepeaterPositionMode positionMode = TakRepeaterPositionMode::NO_POSITION;
    bool positionAvailable = false;
    bool gpsConnected = false;
    bool gpsFix = false;
    bool serviceActive = false;
    bool wifiServiceActive = false;
    bool usbPowered = false;
    bool lightSleepSupported = false;
    uint32_t bootCount = 0;
    uint32_t watchdogReboots = 0;
    uint32_t resetReason = 0;
    uint32_t rxPackets = 0;
    uint32_t txPackets = 0;
    uint32_t forwardedPackets = 0;
    uint32_t positionTxCount = 0;
    uint32_t lastRadioAgeSecs = UINT32_MAX;
    uint32_t lastRxAgeSecs = UINT32_MAX;
    uint32_t lastTxAgeSecs = UINT32_MAX;
    uint16_t channelUtilizationX10 = 0;
    uint16_t txAirUtilizationX10 = 0;
    uint32_t usbDropCount = 0;
    uint32_t usbRestoreCount = 0;
    uint32_t lightSleepEntries = 0;
    uint32_t lightSleepWakes = 0;
    uint32_t minFreeHeap = 0;
    uint8_t watchdogStage = 0;
    uint8_t lastLightSleepWakeCause = 0;
};

bool takRepeaterRoleActive();
bool takRepeaterApplyBaseConfig(bool persist);
void takRepeaterRuntimeInit();

TakRepeaterStats takRepeaterStats();
const char *takRepeaterPositionModeKey(TakRepeaterPositionMode mode);

bool takRepeaterServiceOpen();
void takRepeaterServiceTouch();
void takRepeaterServiceClose(const char *reason = nullptr);

// Router calls this only after the radio interface accepted a TX. "forwarded"
// means the original packet did not originate from this node.
void takRepeaterNoteRadioTx(bool forwarded);

} // namespace jarnsen
