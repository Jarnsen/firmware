#pragma once

#include "NodeDB.h"

#include <stddef.h>
#include <stdint.h>

#if defined(HELTEC_TRACKER_V1_1)

void trackerDiagInit();
bool trackerDiagEnabled();
void trackerDiagSetEnabled(bool enabled);
size_t trackerDiagLogSize();
void trackerDiagClear();
void trackerDiagLog(const char *event, const char *fmt = nullptr, ...);
void trackerDiagLogPosition(const char *event, int32_t latitudeI, int32_t longitudeI, uint32_t ageSecs, uint8_t sats, bool fresh);

// USB export is intentionally output-only. The downloader opens native USB CDC
// and the Tracker waits one second for that connection to settle before it
// sends the begin marker. This prevents the start of a transfer from being
// lost while Windows/pyserial is still opening the port.
void trackerDiagRequestUsbExport();
void trackerDiagPumpUsbExport();
bool trackerDiagUsbExportPending();
const char *trackerDiagUsbExportStatusText();
uint8_t trackerDiagUsbExportProgress();

#endif
