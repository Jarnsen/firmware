#pragma once

#include <cstddef>
#include <cstdint>

struct HeltecV3DiagStats {
    uint32_t bootCount = 0;
    uint32_t crashResetCount = 0;
    uint32_t serviceOpenCount = 0;
    uint32_t bleConnectionCount = 0;
    uint32_t bleRecoveryCount = 0;
    uint32_t autoPositionSaveCount = 0;
    uint32_t manualPositionSaveCount = 0;
};

void heltecV3DiagInit();
void heltecV3DiagLog(const char *event, const char *fmt = nullptr, ...);
void heltecV3DiagNoteServiceOpen();
void heltecV3DiagNoteBleConnection();
void heltecV3DiagNoteBleRecovery();
void heltecV3DiagNotePositionSave(bool automatic, uint32_t differenceM);
HeltecV3DiagStats heltecV3DiagStats();
const char *heltecV3DiagResetReasonText();

size_t heltecV3DiagLogSize();
void heltecV3DiagClear();
void heltecV3DiagRequestUsbExport();
bool heltecV3DiagUsbExportPending();
const char *heltecV3DiagUsbExportStatusText();
uint8_t heltecV3DiagUsbExportProgress();
void heltecV3DiagPumpUsbExport();
