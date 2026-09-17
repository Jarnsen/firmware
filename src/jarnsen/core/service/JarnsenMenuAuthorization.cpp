#include "jarnsen/core/service/JarnsenMenuAuthorization.h"

#include "jarnsen/core/service/JarnsenServiceSecurity.h"

#include <Arduino.h>

namespace jarnsen
{
namespace
{
constexpr uint32_t kAuthorizationTtlMs = 5UL * 60UL * 1000UL;
constexpr uint32_t kPinBlockMs = 30UL * 1000UL;
constexpr uint8_t kMaxPinFailures = 3U;

uint32_t authorizationUntilMs = 0;
uint32_t blockedUntilMs = 0;
uint8_t pinFailures = 0;

bool deadlineActive(uint32_t deadline, uint32_t now)
{
    return deadline != 0U && (int32_t)(deadline - now) > 0;
}

void expireBlockIfNeeded(uint32_t now)
{
    if (blockedUntilMs != 0U && !deadlineActive(blockedUntilMs, now)) {
        blockedUntilMs = 0;
        pinFailures = 0;
    }
}

void clearAuthorizationOnly()
{
    authorizationUntilMs = 0;
}
} // namespace

void menuAuthorizationClear()
{
    authorizationUntilMs = 0;
    blockedUntilMs = 0;
    pinFailures = 0;
}

void menuAuthorizationPump()
{
    if (serviceSecurityLocked()) {
        menuAuthorizationClear();
        return;
    }

    const uint32_t now = millis();
    expireBlockIfNeeded(now);
    if (authorizationUntilMs != 0U && !deadlineActive(authorizationUntilMs, now))
        clearAuthorizationOnly();
}

bool menuAuthorizationValid()
{
    menuAuthorizationPump();
    return deadlineActive(authorizationUntilMs, millis());
}

uint32_t menuAuthorizationRemainingMs()
{
    menuAuthorizationPump();
    const uint32_t now = millis();
    return deadlineActive(authorizationUntilMs, now) ? authorizationUntilMs - now : 0U;
}

uint32_t menuAuthorizationBlockRemainingMs()
{
    menuAuthorizationPump();
    const uint32_t now = millis();
    return deadlineActive(blockedUntilMs, now) ? blockedUntilMs - now : 0U;
}

uint8_t menuAuthorizationFailureCount()
{
    menuAuthorizationPump();
    return pinFailures;
}

MenuAuthorizationResult menuAuthorizationSubmitPin(uint32_t pin)
{
    if (serviceSecurityLocked()) {
        menuAuthorizationClear();
        return MenuAuthorizationResult::BLOCKED;
    }

    const uint32_t now = millis();
    expireBlockIfNeeded(now);
    if (deadlineActive(blockedUntilMs, now))
        return MenuAuthorizationResult::BLOCKED;

    if (!serviceSecurityVerifyPin(pin)) {
        pinFailures++;
        if (pinFailures >= kMaxPinFailures) {
            pinFailures = 0;
            blockedUntilMs = now + kPinBlockMs;
            clearAuthorizationOnly();
            return MenuAuthorizationResult::BLOCKED;
        }
        clearAuthorizationOnly();
        return MenuAuthorizationResult::REJECTED;
    }

    pinFailures = 0;
    blockedUntilMs = 0;
    authorizationUntilMs = now + kAuthorizationTtlMs;
    return MenuAuthorizationResult::GRANTED;
}

} // namespace jarnsen
