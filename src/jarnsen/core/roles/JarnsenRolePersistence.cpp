#include "jarnsen/core/roles/JarnsenRolePersistence.h"

#include "FSCommon.h"
#include "SPILock.h"
#include "concurrency/LockGuard.h"
#include "jarnsen/hardware/JarnsenHardwareProfiles.h"

#include <ctype.h>

namespace jarnsen
{
namespace
{

constexpr const char *ROLE_PATH = "/prefs/jarnsen-role-v1";
constexpr uint8_t ROLE_MAGIC = 0xD7U;
constexpr uint8_t ROLE_RECORD_VERSION = 1U;

bool cacheLoaded = false;
bool cacheKnown = false;
DeviceRole cachedRole = DeviceRole::UNCONFIGURED;

bool equalIgnoreCase(const char *a, const char *b)
{
    if (!a || !b)
        return false;
    while (*a && *b) {
        if (tolower((unsigned char)*a) != tolower((unsigned char)*b))
            return false;
        ++a;
        ++b;
    }
    return *a == '\0' && *b == '\0';
}

bool decodeRole(int raw, DeviceRole &role)
{
    if (raw < (int)DeviceRole::UNCONFIGURED || raw > (int)DeviceRole::DRONE_REPEATER)
        return false;
    role = static_cast<DeviceRole>((uint8_t)raw);
    return true;
}

uint8_t roleChecksum(uint8_t role)
{
    return (uint8_t)(ROLE_MAGIC ^ ROLE_RECORD_VERSION ^ role ^ 0x5AU);
}

} // namespace

bool parseDeviceRoleKey(const char *text, DeviceRole &role)
{
    if (equalIgnoreCase(text, "unconfigured")) {
        role = DeviceRole::UNCONFIGURED;
        return true;
    }
    if (equalIgnoreCase(text, "tak")) {
        role = DeviceRole::TAK;
        return true;
    }
    if (equalIgnoreCase(text, "tak_tracker")) {
        role = DeviceRole::TAK_TRACKER;
        return true;
    }
    if (equalIgnoreCase(text, "tak_repeater")) {
        role = DeviceRole::TAK_REPEATER;
        return true;
    }
    if (equalIgnoreCase(text, "drone_repeater")) {
        role = DeviceRole::DRONE_REPEATER;
        return true;
    }
    return false;
}

bool deviceRoleAllowedOnCurrentHardware(DeviceRole role)
{
    if (role == DeviceRole::UNCONFIGURED)
        return true;
    const auto profile = currentHardwareRoleProfile();
    return profile.hardware.kind != HardwareKind::UNKNOWN && roleAllowed(role, profile.roles);
}

bool readPersistedDeviceRole(DeviceRole &role)
{
    if (cacheLoaded) {
        role = cachedRole;
        return cacheKnown;
    }

    role = DeviceRole::UNCONFIGURED;
    cacheLoaded = true;
    cacheKnown = false;
    cachedRole = DeviceRole::UNCONFIGURED;

#ifdef FSCom
    concurrency::LockGuard guard(spiLock);
    File file = FSCom.open(ROLE_PATH, FILE_O_READ);
    if (!file)
        return false;

    const int magic = file.read();
    const int version = file.read();
    const int raw = file.read();
    const int checksum = file.read();
    file.close();

    DeviceRole decoded = DeviceRole::UNCONFIGURED;
    if (magic != ROLE_MAGIC || version != ROLE_RECORD_VERSION || checksum < 0 || !decodeRole(raw, decoded) ||
        checksum != roleChecksum((uint8_t)raw))
        return false;

    if (!deviceRoleAllowedOnCurrentHardware(decoded))
        return false;

    cachedRole = decoded;
    cacheKnown = true;
    role = decoded;
    return true;
#else
    return false;
#endif
}

bool writePersistedDeviceRole(DeviceRole role)
{
    if (!deviceRoleAllowedOnCurrentHardware(role))
        return false;

#ifdef FSCom
    const uint8_t raw = static_cast<uint8_t>(role);
    const uint8_t record[4] = {ROLE_MAGIC, ROLE_RECORD_VERSION, raw, roleChecksum(raw)};

    concurrency::LockGuard guard(spiLock);
    File file = FSCom.open(ROLE_PATH, FILE_O_WRITE);
    if (!file)
        return false;
    const bool ok = file.write(record, sizeof(record)) == sizeof(record);
    file.flush();
    file.close();
    if (ok) {
        cacheLoaded = true;
        cacheKnown = true;
        cachedRole = role;
    }
    return ok;
#else
    return false;
#endif
}

} // namespace jarnsen
