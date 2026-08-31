#include "jarnsen/core/service/JarnsenServiceDiagnostics.h"
#include "configuration.h"

#if defined(_VARIANT_HELTEC_V3)
#include "infrastructure/HeltecV3DiagnosticLog.h"
#elif defined(HELTEC_TRACKER_V1_1)
#include "vehicle/TrackerDiagnosticLog.h"
#endif

namespace jarnsen
{

bool serviceDiagStartExport()
{
#if defined(_VARIANT_HELTEC_V3)
    return heltecV3DiagStartBleExport();
#elif defined(HELTEC_TRACKER_V1_1)
    return trackerDiagStartBleExport();
#else
    return false;
#endif
}

size_t serviceDiagReadExport(uint8_t *buffer, size_t capacity)
{
#if defined(_VARIANT_HELTEC_V3)
    return heltecV3DiagReadBleExport(buffer, capacity);
#elif defined(HELTEC_TRACKER_V1_1)
    return trackerDiagReadBleExport(buffer, capacity);
#else
    (void)buffer;
    (void)capacity;
    return 0;
#endif
}

void serviceDiagCancelExport()
{
#if defined(_VARIANT_HELTEC_V3)
    heltecV3DiagCancelBleExport();
#elif defined(HELTEC_TRACKER_V1_1)
    trackerDiagCancelBleExport();
#endif
}

void serviceDiagLog(const char *event, const char *detail)
{
#if defined(_VARIANT_HELTEC_V3)
    heltecV3DiagLog(event, "%s", detail ? detail : "");
#elif defined(HELTEC_TRACKER_V1_1)
    trackerDiagLog(event, "%s", detail ? detail : "");
#else
    (void)event;
    (void)detail;
#endif
}

} // namespace jarnsen
