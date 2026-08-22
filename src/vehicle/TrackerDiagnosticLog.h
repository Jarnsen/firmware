#pragma once

#include <stddef.h>
#include <stdint.h>

#if defined(HELTEC_TRACKER_V1_1)

void trackerDiagInit();
bool trackerDiagEnabled();
void trackerDiagSetEnabled(bool enabled);
size_t trackerDiagLogSize();
void trackerDiagClear();
void trackerDiagLog(const char *event, const char *fmt = nullptr, ...);
void trackerDiagLogPosition(const char *event, int32_t latitudeI, int32_t longitudeI, uint32_t ageSecs, uint8_t sats,
                            bool fresh);

// USB export is deliberately output-only. The PC downloader opens native USB
// CDC first, then the user selects "Export via USB" on the Tracker menu. This
// avoids adding a second command parser beside Meshtastic's serial API.
void trackerDiagRequestUsbExport();
void trackerDiagPumpUsbExport();
bool trackerDiagUsbExportPending();

#endif
