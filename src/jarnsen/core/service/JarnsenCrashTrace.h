#pragma once

#include <stdint.h>

namespace jarnsen
{

// Boot stages share one schema; retained panic breadcrumbs depend on the platform.
void crashTraceInit();
void crashTraceReport(uint32_t bootCount);
void crashTraceBootStage(uint16_t step, const char *name);
void crashTraceBootLoggingReady();
void crashTraceBreadcrumb(uint16_t step, const char *name);
void crashTraceTouch();
const char *crashTraceResetReasonName(uint32_t reason);

} // namespace jarnsen
