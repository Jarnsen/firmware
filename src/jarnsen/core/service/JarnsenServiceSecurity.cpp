#include "jarnsen/core/service/JarnsenServiceSecurity.h"

#include "NodeDB.h"
#include "configuration.h"
#include "gps/RTC.h"
#include "jarnsen/adapters/JarnsenLegacyStatusBridge.h"
#include "jarnsen/core/roles/JarnsenDeviceRole.h"
#include "jarnsen/core/status/JarnsenStatusProvider.h"
#include "modules/TextMessageModule.h"

#include <Arduino.h>
#include <cstdio>
#include <cstring>

#if defined(ARCH_ESP32)
#include <Preferences.h>
#endif

namespace jarnsen
{
namespace
{
enum class AlertKind : uint8_t { NONE = 0, LOCKED, UNLOCKED };
bool initialized = false;
bool lockedState = false;
bool meshAlerts = true;
AlertKind pendingAlert = AlertKind::NONE;
uint8_t pendingSendIndex = 0;
uint32_t nextSendMs = 0;

void loadState()
{
#if defined(ARCH_ESP32)
    Preferences prefs;
    if (prefs.begin("jarnSec", true)) {
        lockedState = prefs.getBool("locked", false);
        meshAlerts = prefs.getBool("alert", true);
        prefs.end();
    }
#endif
}

void persistBool(const char *key, bool value)
{
#if defined(ARCH_ESP32)
    Preferences prefs;
    if (prefs.begin("jarnSec", false)) {
        prefs.putBool(key, value);
        prefs.end();
    }
#else
    (void)key;
    (void)value;
#endif
}

void queueAlert(AlertKind kind)
{
    if (!meshAlerts)
        return;
    pendingAlert = kind;
    pendingSendIndex = 0;
    nextSendMs = millis();
}

bool timeReached(uint32_t now, uint32_t target)
{
    return (int32_t)(now - target) >= 0;
}

bool buildAlert(char *out, size_t capacity, AlertKind kind)
{
    if (!out || capacity < 32 || !nodeDB)
        return false;

    const NodeNum selfNum = nodeDB->getNodeNum();
    const meshtastic_NodeInfoLite *self = nodeDB->getMeshNode(selfNum);
    const char *name = self && self->long_name[0] ? self->long_name : "JARN-MESH";
    const uint32_t nowEpoch = getValidTime(RTCQuality::RTCQualityDevice, true);
    meshtastic_PositionLite position{};
    const bool havePosition = nodeDB->copyNodePosition(selfNum, position) &&
                              (position.latitude_i != 0 || position.longitude_i != 0);

    char positionText[72] = "pos=unknown";
    if (havePosition) {
        uint32_t age = 0;
        if (nowEpoch != 0 && position.time != 0 && nowEpoch >= position.time)
            age = nowEpoch - position.time;
        snprintf(positionText, sizeof(positionText), "pos=%.7f,%.7f age=%us", position.latitude_i * 1e-7,
                 position.longitude_i * 1e-7, (unsigned)age);
    }

    snprintf(out, capacity, "JARN %s name=%s id=!%08x time=%u %s",
             kind == AlertKind::LOCKED ? "LOCKED_FULL" : "UNLOCKED", name, (unsigned)selfNum,
             (unsigned)nowEpoch, positionText);
    return true;
}

bool transmitPendingAlert()
{
    if (!textMessageModule)
        return false;
    char message[196] = {};
    if (!buildAlert(message, sizeof(message), pendingAlert))
        return false;
    return textMessageModule->sendLocalBroadcast(message, 0);
}
} // namespace

void serviceSecurityInit()
{
    if (initialized)
        return;
    initialized = true;
    loadState();
}

bool serviceSecurityLocked()
{
    serviceSecurityInit();
    return lockedState;
}

bool serviceSecurityVerifyPin(uint32_t pin)
{
    return pin == kJarnsenUserPin;
}

bool serviceSecurityLock()
{
    serviceSecurityInit();
    if (lockedState)
        return false;
    lockedState = true;
    persistBool("locked", true);
    queueAlert(AlertKind::LOCKED);
    return true;
}

bool serviceSecurityUnlock(uint32_t pin)
{
    serviceSecurityInit();
    if (!serviceSecurityVerifyPin(pin) || !lockedState)
        return false;
    lockedState = false;
    persistBool("locked", false);
    queueAlert(AlertKind::UNLOCKED);
    return true;
}

void serviceSecurityPump()
{
    serviceSecurityInit();
    if (pendingAlert == AlertKind::NONE || !meshAlerts)
        return;
    const uint32_t now = millis();
    if (!timeReached(now, nextSendMs))
        return;
    if (!transmitPendingAlert()) {
        nextSendMs = now + 1000U;
        return;
    }
    pendingSendIndex++;
    if (pendingAlert == AlertKind::UNLOCKED || pendingSendIndex >= 3) {
        pendingAlert = AlertKind::NONE;
        pendingSendIndex = 0;
        nextSendMs = 0;
        return;
    }
    nextSendMs = now + (pendingSendIndex == 1 ? 3000U : 7000U);
}

bool serviceSecurityMeshAlertsEnabled()
{
    serviceSecurityInit();
    return meshAlerts;
}

void serviceSecuritySetMeshAlertsEnabled(bool enabled)
{
    serviceSecurityInit();
    meshAlerts = enabled;
    persistBool("alert", enabled);
    if (!enabled) {
        pendingAlert = AlertKind::NONE;
        pendingSendIndex = 0;
        nextSendMs = 0;
    }
}

bool serviceSecurityWifiAllowed()
{
    serviceSecurityInit();
    if (lockedState)
        return false;
    ensureLegacyStatusBridge();
    return !activeDeviceRoleIs(DeviceRole::DRONE_REPEATER);
}
} // namespace jarnsen
