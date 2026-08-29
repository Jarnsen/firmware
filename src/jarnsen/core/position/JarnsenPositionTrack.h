#pragma once

#include <cstddef>
#include <cstdint>

enum class JarnsenTrackSource : uint8_t { PHONE = 1, GPS = 2 };

struct JarnsenTrackPoint {
    uint32_t epoch = 0;
    int32_t latitudeI = 0;
    int32_t longitudeI = 0;
    uint32_t accuracyMm = 0;
    JarnsenTrackSource source = JarnsenTrackSource::GPS;
};

// Persists the first valid point and then only points more than 25 metres from
// the last persisted point. Returns true when a new point was written.
bool jarnsenPositionTrackNote(int32_t latitudeI, int32_t longitudeI, uint32_t epoch, uint32_t accuracyMm,
                              JarnsenTrackSource source);
size_t jarnsenPositionTrackCount();
void jarnsenPositionTrackClear();

// Only one snapshot export may be active at a time. While it is active, new
// samples are skipped so rotation cannot invalidate the snapshot.
bool jarnsenPositionTrackStartExport();
bool jarnsenPositionTrackReadExport(JarnsenTrackPoint &point);
void jarnsenPositionTrackEndExport();

// Compatibility name retained for existing service-web callers. The actual
// MGRS calculation now lives in the common position core.
bool jarnsenPositionTrackFormatMgrs8(int32_t latitudeI, int32_t longitudeI, char *out, size_t outSize);
const char *jarnsenPositionTrackSourceName(JarnsenTrackSource source);

// Implemented by a board/service adapter when diagnostic logging is available;
// the common track core supplies a weak no-op fallback.
void jarnsenPositionTrackDiagnosticStored(const JarnsenTrackPoint &point, const char *mgrs);
