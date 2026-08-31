#include "jarnsen/core/service/JarnsenServiceDiagnostics.h"
#include "jarnsen/core/diagnostics/JarnsenDiagnosticBackend.h"

namespace jarnsen
{

bool serviceDiagStartExport()
{
    const auto &backend = diagnostics::platformBackend();
    return backend.startExport ? backend.startExport() : false;
}

size_t serviceDiagReadExport(uint8_t *buffer, size_t capacity)
{
    const auto &backend = diagnostics::platformBackend();
    return backend.readExport ? backend.readExport(buffer, capacity) : 0;
}

void serviceDiagCancelExport()
{
    const auto &backend = diagnostics::platformBackend();
    if (backend.cancelExport) {
        backend.cancelExport();
    }
}

void serviceDiagLog(const char *event, const char *detail)
{
    const auto &backend = diagnostics::platformBackend();
    if (backend.logEvent) {
        backend.logEvent(event, detail);
    }
}

} // namespace jarnsen
