#include "jarnsen/core/diagnostics/JarnsenDiagnosticBackend.h"
#include "configuration.h"

#if defined(_VARIANT_HELTEC_V3)
#include "infrastructure/HeltecV3DiagnosticLog.h"
#elif defined(HELTEC_TRACKER_V1_1)
#include "vehicle/TrackerDiagnosticLog.h"
#endif

namespace
{

bool noDiagnosticsStartExport()
{
    return false;
}

size_t noDiagnosticsReadExport(uint8_t *buffer, size_t capacity)
{
    (void)buffer;
    (void)capacity;
    return 0;
}

void noDiagnosticsCancelExport() {}

void noDiagnosticsLogEvent(const char *event, const char *detail)
{
    (void)event;
    (void)detail;
}

#if defined(_VARIANT_HELTEC_V3)
bool boardDiagnosticsStartExport()
{
    return heltecV3DiagStartBleExport();
}

size_t boardDiagnosticsReadExport(uint8_t *buffer, size_t capacity)
{
    return heltecV3DiagReadBleExport(buffer, capacity);
}

void boardDiagnosticsCancelExport()
{
    heltecV3DiagCancelBleExport();
}

void boardDiagnosticsLogEvent(const char *event, const char *detail)
{
    heltecV3DiagLog(event, "%s", detail ? detail : "");
}
#elif defined(HELTEC_TRACKER_V1_1)
bool boardDiagnosticsStartExport()
{
    return trackerDiagStartBleExport();
}

size_t boardDiagnosticsReadExport(uint8_t *buffer, size_t capacity)
{
    return trackerDiagReadBleExport(buffer, capacity);
}

void boardDiagnosticsCancelExport()
{
    trackerDiagCancelBleExport();
}

void boardDiagnosticsLogEvent(const char *event, const char *detail)
{
    trackerDiagLog(event, "%s", detail ? detail : "");
}
#endif

} // namespace

namespace jarnsen
{
namespace diagnostics
{

const Backend &platformBackend()
{
#if defined(_VARIANT_HELTEC_V3) || defined(HELTEC_TRACKER_V1_1)
    static const Backend backend = {
        boardDiagnosticsStartExport,
        boardDiagnosticsReadExport,
        boardDiagnosticsCancelExport,
        boardDiagnosticsLogEvent,
    };
#else
    static const Backend backend = {
        noDiagnosticsStartExport,
        noDiagnosticsReadExport,
        noDiagnosticsCancelExport,
        noDiagnosticsLogEvent,
    };
#endif
    return backend;
}

} // namespace diagnostics
} // namespace jarnsen
