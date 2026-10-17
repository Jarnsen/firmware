#include "jarnsen/core/diagnostics/JarnsenDiagnosticBackend.h"
#include "configuration.h"

// Tracker V1.1 retains its proven native BLE/USB diagnostic snapshot.
// All other ESP32 boards (including HELTEC_V3) use the shared FS log. The
// former _VARIANT_HELTEC_V3-only branch was never compiled for HELTEC_V3.
#if defined(HELTEC_TRACKER_V1_1)
#include "vehicle/TrackerDiagnosticLog.h"
#elif defined(ARCH_ESP32) || defined(HELTEC_V3) || defined(_VARIANT_HELTEC_V3)
#include "jarnsen/core/service/JarnsenDiagnosticLog.h"
#endif

namespace
{
bool noDiagnosticsStartExport()
{
    return false;
}

size_t noDiagnosticsReadExport(uint8_t *, size_t)
{
    return 0;
}

void noDiagnosticsCancelExport() {}

void noDiagnosticsLogEvent(const char *, const char *) {}

#if defined(HELTEC_TRACKER_V1_1)
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
#elif defined(ARCH_ESP32) || defined(HELTEC_V3) || defined(_VARIANT_HELTEC_V3)
// JARNSEN_V3_DIAG_HTTP_409_BACKEND_FIX_V1
bool boardDiagnosticsStartExport()
{
    return jarnsen::diagnosticLogStartWebExport();
}

size_t boardDiagnosticsReadExport(uint8_t *buffer, size_t capacity)
{
    return jarnsen::diagnosticLogReadWebExport(buffer, capacity);
}

void boardDiagnosticsCancelExport()
{
    jarnsen::diagnosticLogCancelWebExport();
}

void boardDiagnosticsLogEvent(const char *event, const char *detail)
{
    jarnsen::diagnosticLog(event, "%s", detail ? detail : "");
}
#endif
} // namespace

namespace jarnsen
{
namespace diagnostics
{
const Backend &platformBackend()
{
#if defined(HELTEC_TRACKER_V1_1) || defined(ARCH_ESP32) || defined(HELTEC_V3) || defined(_VARIANT_HELTEC_V3)
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
