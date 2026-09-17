#pragma once

#include <stdint.h>

namespace jarnsen
{

enum class MenuAuthorizationResult : uint8_t {
    GRANTED = 0,
    REJECTED,
    BLOCKED,
};

// Shared, RAM-only authorization for protected local menu changes.
// A successful PIN is valid for five minutes across all protected menu areas.
// Full Lock and reboot clear the authorization; this API never changes the
// persistent Full-Lock state and never emits mesh lock/unlock alerts.
bool menuAuthorizationValid();
uint32_t menuAuthorizationRemainingMs();
MenuAuthorizationResult menuAuthorizationSubmitPin(uint32_t pin);
uint32_t menuAuthorizationBlockRemainingMs();
uint8_t menuAuthorizationFailureCount();
void menuAuthorizationClear();
void menuAuthorizationPump();

} // namespace jarnsen
