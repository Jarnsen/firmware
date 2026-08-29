#include "mesh/http/JarnsenPositionTrack.h"
#include "configuration.h"

#if defined(ARCH_ESP32) && HAS_WIFI && (defined(_VARIANT_HELTEC_V3) || defined(HELTEC_TRACKER_V1_1))

#if defined(_VARIANT_HELTEC_V3)
#include "infrastructure/HeltecV3DiagnosticLog.h"
#else
#include "vehicle/TrackerDiagnosticLog.h"
#endif

void jarnsenPositionTrackDiagnosticStored(const JarnsenTrackPoint &point, const char *mgrs)
{
#if defined(_VARIANT_HELTEC_V3)
    heltecV3DiagLog("TRACK_POINT", "lat=%.7f lon=%.7f epoch=%u mgrs=%s source=%s acc=%umm", point.latitudeI * 1e-7,
                    point.longitudeI * 1e-7, (unsigned)point.epoch, mgrs,
                    jarnsenPositionTrackSourceName(point.source), (unsigned)point.accuracyMm);
#else
    trackerDiagLog("TRACK_POINT", "lat=%.7f lon=%.7f epoch=%u mgrs=%s source=%s acc=%umm", point.latitudeI * 1e-7,
                   point.longitudeI * 1e-7, (unsigned)point.epoch, mgrs,
                   jarnsenPositionTrackSourceName(point.source), (unsigned)point.accuracyMm);
#endif
}

#endif
