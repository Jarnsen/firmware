#pragma once

#include <stdint.h>

namespace jarnsen
{

constexpr uint32_t JARNSEN_DISPLAY_ON_MS = 20000U;

// Apply the board-wide JARNSEN interaction policy after NodeDB/config and the
// filesystem are available, but before PowerFSM is configured.
void runtimePolicyInit();

} // namespace jarnsen
