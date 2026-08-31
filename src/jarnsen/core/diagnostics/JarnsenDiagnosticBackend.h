#pragma once

#include <stddef.h>
#include <stdint.h>

namespace jarnsen
{
namespace diagnostics
{

// Board-neutral diagnostics contract used by shared Core services.
// Concrete Tracker/V3/other implementations live outside the Core.
struct Backend {
    bool (*startExport)();
    size_t (*readExport)(uint8_t *buffer, size_t capacity);
    void (*cancelExport)();
    void (*logEvent)(const char *event, const char *detail);
};

// Implemented by the hardware layer. Unsupported boards return a no-op
// backend so Core consumers never need board-specific preprocessor branches.
const Backend &platformBackend();

} // namespace diagnostics
} // namespace jarnsen
