#include "jarnsen/core/service/JarnsenHardwareIdentity.h"

#include "FSCommon.h"
#include "SPILock.h"
#include "concurrency/LockGuard.h"
#include "jarnsen/hardware/JarnsenHardwareProfiles.h"

#include <Arduino.h>
#include <cstddef>
#include <cstdio>
#include <cstring>

#if defined(ARCH_ESP32)
#include <Preferences.h>
#endif

#if defined(ARCH_NRF52)
#include <nrf.h>
#endif

namespace jarnsen
{
namespace
{

constexpr uint32_t HARDWARE_ID_MAGIC = 0x3148574aU; // little-endian bytes: "JWH1"
constexpr uint8_t HARDWARE_ID_SCHEMA = 1U;
constexpr const char *ESP32_NAMESPACE = "jarnHw";
constexpr const char *ESP32_KEY = "record";
constexpr const char *NRF52_FILE = "/jarnsen_hw.bin";

// The numeric HardwareKind values are part of the persistent record format.
// Reordering the enum must therefore fail the build instead of silently
// changing the meaning of already provisioned devices.
static_assert(static_cast<uint8_t>(HardwareKind::BOARD_HELTEC_TRACKER_V11) == 1U, "persisted Tracker hardware id changed");
static_assert(static_cast<uint8_t>(HardwareKind::BOARD_HELTEC_V3) == 2U, "persisted V3 hardware id changed");
static_assert(static_cast<uint8_t>(HardwareKind::BOARD_HELTEC_V4) == 3U, "persisted V4 hardware id changed");
static_assert(static_cast<uint8_t>(HardwareKind::BOARD_SEEED_WIO_TRACKER_L1) == 4U, "persisted Wio hardware id changed");
static_assert(static_cast<uint8_t>(HardwareKind::BOARD_LILYGO_TBEAM) == 5U, "persisted T-Beam hardware id changed");
static_assert(static_cast<uint8_t>(HardwareKind::BOARD_LILYGO_TBEAM_SUPREME) == 6U,
              "persisted T-Beam Supreme hardware id changed");

struct __attribute__((packed)) HardwareIdentityRecord {
    uint32_t magic;
    uint8_t schema;
    uint8_t boardKind;
    uint16_t size;
    uint64_t chipId;
    uint32_t crc32;
};
static_assert(sizeof(HardwareIdentityRecord) == 20U, "hardware identity persistence layout changed");

enum class ReadResult : uint8_t { EMPTY = 0, RECORD, INVALID, ERROR, UNSUPPORTED };

HardwareIdentityInfo identity{};
bool initialized = false;

bool knownKind(HardwareKind kind)
{
    const uint8_t raw = static_cast<uint8_t>(kind);
    return raw >= static_cast<uint8_t>(HardwareKind::BOARD_HELTEC_TRACKER_V11) &&
           raw <= static_cast<uint8_t>(HardwareKind::BOARD_LILYGO_TBEAM_SUPREME);
}

uint32_t crc32(const uint8_t *data, size_t length)
{
    uint32_t crc = 0xffffffffU;
    for (size_t i = 0; i < length; ++i) {
        crc ^= data[i];
        for (uint8_t bit = 0; bit < 8U; ++bit)
            crc = (crc >> 1U) ^ (0xedb88320U & (0U - (crc & 1U)));
    }
    return ~crc;
}

uint32_t recordCrc(const HardwareIdentityRecord &record)
{
    return crc32(reinterpret_cast<const uint8_t *>(&record), offsetof(HardwareIdentityRecord, crc32));
}

bool validRecord(const HardwareIdentityRecord &record)
{
    if (record.magic != HARDWARE_ID_MAGIC || record.schema != HARDWARE_ID_SCHEMA || record.size != sizeof(record))
        return false;
    const HardwareKind kind = static_cast<HardwareKind>(record.boardKind);
    return knownKind(kind) && record.crc32 == recordCrc(record);
}

uint64_t readChipId()
{
#if defined(ARCH_ESP32)
    // Read-only eFuse-backed factory identifier. JARNSEN never writes eFuses.
    return ESP.getEfuseMac();
#elif defined(ARCH_NRF52)
    // Factory-programmed nRF52840 DEVICEID, read-only.
    return (static_cast<uint64_t>(NRF_FICR->DEVICEID[1]) << 32U) | static_cast<uint64_t>(NRF_FICR->DEVICEID[0]);
#else
    return 0U;
#endif
}

ReadResult readStoredRecord(HardwareIdentityRecord &record)
{
    memset(&record, 0, sizeof(record));
#if defined(ARCH_ESP32)
    Preferences prefs;
    if (!prefs.begin(ESP32_NAMESPACE, false))
        return ReadResult::ERROR;
    const size_t length = prefs.getBytesLength(ESP32_KEY);
    if (length == 0U) {
        prefs.end();
        return ReadResult::EMPTY;
    }
    if (length != sizeof(record)) {
        prefs.end();
        return ReadResult::INVALID;
    }
    const size_t got = prefs.getBytes(ESP32_KEY, &record, sizeof(record));
    prefs.end();
    if (got != sizeof(record))
        return ReadResult::ERROR;
    return validRecord(record) ? ReadResult::RECORD : ReadResult::INVALID;
#elif defined(ARCH_NRF52)
#ifdef FSCom
    concurrency::LockGuard guard(spiLock);
    if (!FSCom.exists(NRF52_FILE))
        return ReadResult::EMPTY;
    File file = FSCom.open(NRF52_FILE, FILE_O_READ);
    if (!file)
        return ReadResult::ERROR;
    if (file.size() != sizeof(record)) {
        file.close();
        return ReadResult::INVALID;
    }
    const size_t got = file.read(reinterpret_cast<uint8_t *>(&record), sizeof(record));
    file.close();
    if (got != sizeof(record))
        return ReadResult::ERROR;
    return validRecord(record) ? ReadResult::RECORD : ReadResult::INVALID;
#else
    return ReadResult::UNSUPPORTED;
#endif
#else
    return ReadResult::UNSUPPORTED;
#endif
}

bool writeFirstRecord(const HardwareIdentityRecord &record)
{
#if defined(ARCH_ESP32)
    Preferences prefs;
    if (!prefs.begin(ESP32_NAMESPACE, false))
        return false;
    // Refuse to replace anything that appeared since the read. This keeps a
    // valid physical identity write-once from normal firmware's perspective.
    if (prefs.getBytesLength(ESP32_KEY) != 0U) {
        prefs.end();
        return false;
    }
    const size_t written = prefs.putBytes(ESP32_KEY, &record, sizeof(record));
    prefs.end();
    return written == sizeof(record);
#elif defined(ARCH_NRF52)
#ifdef FSCom
    concurrency::LockGuard guard(spiLock);
    if (FSCom.exists(NRF52_FILE))
        return false;
    File file = FSCom.open(NRF52_FILE, FILE_O_WRITE);
    if (!file)
        return false;
    const size_t written = file.write(reinterpret_cast<const uint8_t *>(&record), sizeof(record));
    file.flush();
    file.close();
    return written == sizeof(record);
#else
    return false;
#endif
#else
    (void)record;
    return false;
#endif
}

HardwareIdentityRecord makeRecord(HardwareKind kind, uint64_t chipId)
{
    HardwareIdentityRecord record{};
    record.magic = HARDWARE_ID_MAGIC;
    record.schema = HARDWARE_ID_SCHEMA;
    record.boardKind = static_cast<uint8_t>(kind);
    record.size = sizeof(record);
    record.chipId = chipId;
    record.crc32 = recordCrc(record);
    return record;
}

} // namespace

const char *hardwareKindKey(HardwareKind kind)
{
    switch (kind) {
    case HardwareKind::BOARD_HELTEC_TRACKER_V11:
        return "heltec_tracker_v1_1";
    case HardwareKind::BOARD_HELTEC_V3:
        return "heltec_v3";
    case HardwareKind::BOARD_HELTEC_V4:
        return "heltec_v4";
    case HardwareKind::BOARD_SEEED_WIO_TRACKER_L1:
        return "seeed_wio_tracker_l1";
    case HardwareKind::BOARD_LILYGO_TBEAM:
        return "tbeam";
    case HardwareKind::BOARD_LILYGO_TBEAM_SUPREME:
        return "tbeam_supreme";
    case HardwareKind::UNKNOWN:
    default:
        return "unknown";
    }
}

const char *hardwareIdentityStateKey(HardwareIdentityState state)
{
    switch (state) {
    case HardwareIdentityState::VALID:
        return "valid";
    case HardwareIdentityState::EMPTY:
        return "empty";
    case HardwareIdentityState::INVALID:
        return "invalid";
    case HardwareIdentityState::CHIP_MISMATCH:
        return "chip_mismatch";
    case HardwareIdentityState::STORAGE_ERROR:
        return "storage_error";
    case HardwareIdentityState::UNSUPPORTED:
        return "unsupported";
    case HardwareIdentityState::UNINITIALIZED:
    default:
        return "uninitialized";
    }
}

void hardwareIdentityInit()
{
    if (initialized)
        return;
    initialized = true;

    identity = {};
    identity.firmwareKind = currentHardwareRoleProfile().hardware.kind;
    identity.chipId = readChipId();

    if (!knownKind(identity.firmwareKind) || identity.chipId == 0U) {
        identity.state = HardwareIdentityState::UNSUPPORTED;
        return;
    }

    HardwareIdentityRecord record{};
    const ReadResult result = readStoredRecord(record);
    if (result == ReadResult::RECORD) {
        identity.storedKind = static_cast<HardwareKind>(record.boardKind);
        if (record.chipId != identity.chipId) {
            identity.state = HardwareIdentityState::CHIP_MISMATCH;
            identity.mismatch = true;
            return;
        }
        identity.state = HardwareIdentityState::VALID;
        identity.mismatch = identity.storedKind != identity.firmwareKind;
        return;
    }

    if (result == ReadResult::INVALID) {
        identity.state = HardwareIdentityState::INVALID;
        return;
    }
    if (result == ReadResult::ERROR) {
        identity.state = HardwareIdentityState::STORAGE_ERROR;
        return;
    }
    if (result == ReadResult::UNSUPPORTED) {
        identity.state = HardwareIdentityState::UNSUPPORTED;
        return;
    }

    // First provisioning after an empty/erased identity store. This records
    // the board target of the known-good firmware currently booting. From this
    // point on, a different firmware target can only report a mismatch; it is
    // never allowed to relabel the device automatically.
    identity.state = HardwareIdentityState::EMPTY;
    const HardwareIdentityRecord first = makeRecord(identity.firmwareKind, identity.chipId);
    if (!writeFirstRecord(first)) {
        identity.state = HardwareIdentityState::STORAGE_ERROR;
        return;
    }

    HardwareIdentityRecord verify{};
    if (readStoredRecord(verify) != ReadResult::RECORD || verify.chipId != identity.chipId ||
        verify.boardKind != static_cast<uint8_t>(identity.firmwareKind)) {
        identity.state = HardwareIdentityState::STORAGE_ERROR;
        return;
    }

    identity.storedKind = identity.firmwareKind;
    identity.state = HardwareIdentityState::VALID;
    identity.provisionedThisBoot = true;
}

const HardwareIdentityInfo &hardwareIdentity()
{
    hardwareIdentityInit();
    return identity;
}

bool hardwareIdentityFormat(char *out, size_t capacity)
{
    if (!out || capacity == 0U)
        return false;
    const HardwareIdentityInfo &info = hardwareIdentity();
    const int written = snprintf(out, capacity,
                                 "JARNSEN_HW_INFO schema=%u board=%s chip=%016llX state=%s firmware_target=%s mismatch=%u "
                                 "provisioned=%u",
                                 (unsigned)HARDWARE_ID_SCHEMA, hardwareKindKey(info.storedKind),
                                 (unsigned long long)info.chipId, hardwareIdentityStateKey(info.state),
                                 hardwareKindKey(info.firmwareKind), info.mismatch ? 1U : 0U,
                                 info.provisionedThisBoot ? 1U : 0U);
    return written > 0 && static_cast<size_t>(written) < capacity;
}

} // namespace jarnsen
