#pragma once

#include "configuration.h"

#include <cstddef>
#include <cstdint>

#if defined(ARCH_ESP32) && HAS_WIFI && (defined(_VARIANT_HELTEC_V3) || defined(HELTEC_TRACKER_V1_1))

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

bool jarnsenPositionTrackFormatMgrs8(int32_t latitudeI, int32_t longitudeI, char *out, size_t outSize);
const char *jarnsenPositionTrackSourceName(JarnsenTrackSource source);

#else

enum class JarnsenTrackSource : uint8_t { PHONE = 1, GPS = 2 };
struct JarnsenTrackPoint {};
inline bool jarnsenPositionTrackNote(int32_t, int32_t, uint32_t, uint32_t, JarnsenTrackSource)
{
    return false;
}
inline size_t jarnsenPositionTrackCount()
{
    return 0;
}
inline void jarnsenPositionTrackClear() {}
inline bool jarnsenPositionTrackStartExport()
{
    return false;
}
inline bool jarnsenPositionTrackReadExport(JarnsenTrackPoint &)
{
    return false;
}
inline void jarnsenPositionTrackEndExport() {}
inline bool jarnsenPositionTrackFormatMgrs8(int32_t, int32_t, char *, size_t)
{
    return false;
}
inline const char *jarnsenPositionTrackSourceName(JarnsenTrackSource)
{
    return "unknown";
}

#endif
