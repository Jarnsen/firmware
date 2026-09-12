#pragma once

#include "jarnsen/core/capabilities/JarnsenCapabilities.h"

#include <stddef.h>
#include <stdint.h>

namespace jarnsen
{

enum class HardwareIdentityState : uint8_t {
    UNINITIALIZED = 0,
    VALID,
    EMPTY,
    INVALID,
    CHIP_MISMATCH,
    STORAGE_ERROR,
    UNSUPPORTED,
};

struct HardwareIdentityInfo {
    HardwareIdentityState state = HardwareIdentityState::UNINITIALIZED;
    HardwareKind storedKind = HardwareKind::UNKNOWN;
    HardwareKind firmwareKind = HardwareKind::UNKNOWN;
    uint64_t chipId = 0;
    bool mismatch = false;
    bool provisionedThisBoot = false;
};

// Initializes the persistent physical-hardware marker once. A valid existing
// marker is immutable during normal runtime: firmware for a different board is
// reported as a mismatch and must never silently relabel the node.
void hardwareIdentityInit();
const HardwareIdentityInfo &hardwareIdentity();

// Stable machine-readable keys used by Service Tool and persistence. These are
// deliberately independent from operator-facing board names.
const char *hardwareKindKey(HardwareKind kind);
const char *hardwareIdentityStateKey(HardwareIdentityState state);

// Formats one stable Service Tool response line without the trailing newline.
// Example: JARNSEN_HW_INFO schema=1 board=tbeam_supreme ... mismatch=0
bool hardwareIdentityFormat(char *out, size_t capacity);

} // namespace jarnsen
