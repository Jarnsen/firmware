#pragma once

#include <stdint.h>

namespace jarnsen
{
constexpr uint32_t kJarnsenUserPin = 240180U;
constexpr const char kJarnsenWifiPassword[] = "24011980";

void serviceSecurityInit();
bool serviceSecurityLocked();
bool serviceSecurityVerifyPin(uint32_t pin);
bool serviceSecurityLock();
bool serviceSecurityUnlock(uint32_t pin);
void serviceSecurityPump();
bool serviceSecurityMeshAlertsEnabled();
void serviceSecuritySetMeshAlertsEnabled(bool enabled);
bool serviceSecurityWifiAllowed();
} // namespace jarnsen
