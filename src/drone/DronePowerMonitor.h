#pragma once

#include <stdint.h>

#if defined(HELTEC_TRACKER_V1_1) && defined(JARNSEN_DRONE_REPEATER_BUILD)

struct DronePowerStats {
    bool hasBattery = false;
    bool usbPowered = false;
    bool charging = false;
    uint16_t voltageMv = 0;
    uint8_t batteryPercent = 0;

    uint32_t uptimeSecs = 0;
    uint32_t usbDropCount = 0;
    uint32_t usbRestoreCount = 0;
    uint32_t gpsSecs = 0;
    uint32_t bleSecs = 0;
    uint32_t displaySecs = 0;
    uint32_t positionTxCount = 0;
    uint32_t loraRxCount = 0;
    uint32_t loraTxCount = 0;
    uint32_t relayTxCount = 0;
};

void dronePowerMonitorInit();
void dronePowerMonitorTick(bool gpsActive, bool bleActive, bool displayActive);
void dronePowerMonitorNotePositionTx();
void dronePowerMonitorNoteRadioRx();
void dronePowerMonitorNoteRadioTx(bool relay);
DronePowerStats dronePowerMonitorStats();
const char *dronePowerSourceText();

#endif
