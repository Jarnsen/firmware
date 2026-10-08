#pragma once

#include <stdint.h>

namespace jarnsen
{

// ESP32-only crash breadcrumbs live in RTC no-init memory so they survive panic
// and software resets without touching flash, heap allocation, or mutexes.
void crashTraceInit();
void crashTraceReport(uint32_t bootCount);
void crashTraceBreadcrumb(uint16_t step, const char *name);
void crashTraceTouch();
const char *crashTraceResetReasonName(uint32_t reason);

} // namespace jarnsen
