#pragma once

#include <Arduino.h>
#include <cstdarg>

namespace jarnsen
{

// Shared persistent diagnostic log used by every JARNSEN-MESH board.
// Tracker V1.1 keeps its richer proven logger behind the same interface.
void diagnosticLogInit();
void diagnosticLog(const char *event, const char *fmt = nullptr, ...);
void diagnosticLogV(const char *level, const char *fmt, va_list args);
void diagnosticLogRequestUsbExport(Print &output);
void diagnosticLogPumpUsbExport();
bool diagnosticLogUsbExportPending();

} // namespace jarnsen
