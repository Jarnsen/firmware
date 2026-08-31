#pragma once

#include <stddef.h>
#include <stdint.h>

namespace jarnsen
{

// Transitional facade over the existing board diagnostic backends. Service
// consumers depend on this contract; board-specific loggers can then be
// migrated behind it independently.
bool serviceDiagStartExport();
size_t serviceDiagReadExport(uint8_t *buffer, size_t capacity);
void serviceDiagCancelExport();
void serviceDiagLog(const char *event, const char *detail);

} // namespace jarnsen
