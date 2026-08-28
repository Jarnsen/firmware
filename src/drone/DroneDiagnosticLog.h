#pragma once

#include <stddef.h>
#include <stdint.h>

#if defined(HELTEC_TRACKER_V1_1) && defined(JARNSEN_DRONE_REPEATER_BUILD)

void droneDiagInit();
void droneDiagTick();
void droneDiagLog(const char *event, const char *fmt = nullptr, ...);
size_t droneDiagLogSize();
void droneDiagClear();

void droneDiagRequestUsbExport();
bool droneDiagUsbExportPending();
uint8_t droneDiagUsbExportProgress();
const char *droneDiagUsbExportStatusText();

bool droneDiagStartBleExport();
size_t droneDiagReadBleExport(uint8_t *buffer, size_t capacity);
void droneDiagCancelBleExport();
bool droneDiagBleExportActive();

#endif
