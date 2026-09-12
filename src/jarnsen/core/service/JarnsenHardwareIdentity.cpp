#include "jarnsen/core/service/JarnsenHardwareIdentity.h"

#include "configuration.h"
#include "jarnsen/hardware/JarnsenHardwareProfiles.h"

#include <Arduino.h>
#include <cstddef>
#include <cstdio>
#include <cstring>

#if defined(ARCH_ESP32)
#include <Preferences.h>
#include <esp_flash.h>
#endif

#if defined(ARCH_NRF52)
#include "FSCommon.h"
#include "SPILock.h"
#include "concurrency/LockGuard.h"
#include "flash/flash_nrf5x.h"
#include <nrf.h>
#endif

namespace jarnsen
{
namespace
{

constexpr uint32_t HARDWARE_ID_MAGIC = 0x3148574aU; // little-endian bytes: "JWH1"
constexpr uint8_t HARDWARE_ID_SCHEMA = 1U;
constexpr uint32_t HARDWARE_ID_SECTOR_SIZE = 0x1000U;
constexpr uint32_t WIO_HARDWARE_ID_ADDRESS = 0x000E9000U;
constexpr const char *LEGACY_ESP32_NAMESPACE = "jarnHw";
constexpr const char *LEGACY_ESP32_KEY = "record";
constexpr const char *LEGACY_NRF52_FILE = "/jarnsen_hw.bin";

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

enum class ReadResult : uint8_t { EMPTY = 0, RECORD, INVALID, ERROR, UNSUPPORTED, CHIP_MISMATCH };

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

bool allErased(const uint8_t *data, size_t length)
{
    for (size_t i = 0; i < length; ++i)
        if (data[i] != 0xffU)
            return false;
    return true;
}

uint64_t readChipId()
{
#if defined(ARCH_ESP32)
    // Read-only eFuse-backed factory identifier. JARNSEN never writes eFuses.
    return ESP.getEfuseMac();
#elif defined(ARCH_NRF52)
    // Factory-programmed nRF52840 DEVICEID, read-only. UICR is never modified.
    return (static_cast<uint64_t>(NRF_FICR->DEVICEID[1]) << 32U) | static_cast<uint64_t>(NRF_FICR->DEVICEID[0]);
#else
    return 0U;
#endif
}

uint32_t expectedEspFlashBytes(HardwareKind kind)
{
    switch (kind) {
    case HardwareKind::BOARD_LILYGO_TBEAM:
        return 4U * 1024U * 1024U;
    case HardwareKind::BOARD_HELTEC_TRACKER_V11:
    case HardwareKind::BOARD_HELTEC_V3:
    case HardwareKind::BOARD_LILYGO_TBEAM_SUPREME:
        return 8U * 1024U * 1024U;
    case HardwareKind::BOARD_HELTEC_V4:
        return 16U * 1024U * 1024U;
    default:
        return 0U;
    }
}

#if defined(ARCH_ESP32)
uint32_t espMarkerAddress()
{
    const uint32_t flashBytes = ESP.getFlashChipSize();
    if (flashBytes < HARDWARE_ID_SECTOR_SIZE)
        return 0U;
    return flashBytes - HARDWARE_ID_SECTOR_SIZE;
}

bool espRead(uint32_t address, void *data, size_t length)
{
    return address != 0U && data && length > 0U &&
           esp_flash_read(esp_flash_default_chip, data, address, length) == ESP_OK;
}

bool espMarkerSectorErased()
{
    const uint32_t base = espMarkerAddress();
    if (base == 0U)
        return false;
    uint8_t scratch[64];
    for (uint32_t offset = 0; offset < HARDWARE_ID_SECTOR_SIZE; offset += sizeof(scratch)) {
        if (!espRead(base + offset, scratch, sizeof(scratch)) || !allErased(scratch, sizeof(scratch)))
            return false;
    }
    return true;
}
#endif

ReadResult readDedicatedRecord(HardwareIdentityRecord &record)
{
    memset(&record, 0, sizeof(record));
#if defined(ARCH_ESP32)
    const uint32_t address = espMarkerAddress();
    if (address == 0U || !espRead(address, &record, sizeof(record)))
        return ReadResult::ERROR;
    if (allErased(reinterpret_cast<const uint8_t *>(&record), sizeof(record)))
        return ReadResult::EMPTY;
    return validRecord(record) ? ReadResult::RECORD : ReadResult::INVALID;
#elif defined(ARCH_NRF52) && defined(SEEED_WIO_TRACKER_L1)
    concurrency::LockGuard guard(spiLock);
    flash_nrf5x_read(&record, WIO_HARDWARE_ID_ADDRESS, sizeof(record));
    if (allErased(reinterpret_cast<const uint8_t *>(&record), sizeof(record)))
        return ReadResult::EMPTY;
    return validRecord(record) ? ReadResult::RECORD : ReadResult::INVALID;
#else
    return ReadResult::UNSUPPORTED;
#endif
}

bool writeDedicatedFirstRecord(const HardwareIdentityRecord &record)
{
#if defined(ARCH_ESP32)
    const uint32_t address = espMarkerAddress();
    if (address == 0U || !espMarkerSectorErased())
        return false;
    if (esp_flash_write(esp_flash_default_chip, &record, address, sizeof(record)) != ESP_OK)
        return false;
    HardwareIdentityRecord verify{};
    return espRead(address, &verify, sizeof(verify)) && memcmp(&verify, &record, sizeof(record)) == 0;
#elif defined(ARCH_NRF52) && defined(SEEED_WIO_TRACKER_L1)
    concurrency::LockGuard guard(spiLock);
    uint8_t scratch[64];
    for (uint32_t offset = 0; offset < HARDWARE_ID_SECTOR_SIZE; offset += sizeof(scratch)) {
        flash_nrf5x_read(scratch, WIO_HARDWARE_ID_ADDRESS + offset, sizeof(scratch));
        if (!allErased(scratch, sizeof(scratch)))
            return false;
    }
    flash_nrf5x_write(WIO_HARDWARE_ID_ADDRESS, &record, sizeof(record));
    flash_nrf5x_flush();
    HardwareIdentityRecord verify{};
    flash_nrf5x_read(&verify, WIO_HARDWARE_ID_ADDRESS, sizeof(verify));
    return memcmp(&verify, &record, sizeof(record)) == 0;
#else
    (void)record;
    return false;
#endif
}

ReadResult readLegacyRecord(HardwareIdentityRecord &record, uint64_t currentChipId)
{
    memset(&record, 0, sizeof(record));
#if defined(ARCH_ESP32)
    Preferences prefs;
    if (!prefs.begin(LEGACY_ESP32_NAMESPACE, true))
        return ReadResult::EMPTY;
    const size_t length = prefs.getBytesLength(LEGACY_ESP32_KEY);
    if (length == 0U) {
        prefs.end();
        return ReadResult::EMPTY;
    }
    if (length != sizeof(record)) {
        prefs.end();
        return ReadResult::INVALID;
    }
    const size_t got = prefs.getBytes(LEGACY_ESP32_KEY, &record, sizeof(record));
    prefs.end();
    if (got != sizeof(record))
        return ReadResult::ERROR;
#elif defined(ARCH_NRF52) && defined(SEEED_WIO_TRACKER_L1)
#ifdef FSCom
    concurrency::LockGuard guard(spiLock);
    if (!FSCom.exists(LEGACY_NRF52_FILE))
        return ReadResult::EMPTY;
    File file = FSCom.open(LEGACY_NRF52_FILE, FILE_O_READ);
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
#else
    return ReadResult::EMPTY;
#endif
#else
    return ReadResult::EMPTY;
#endif
    if (!validRecord(record))
        return ReadResult::INVALID;
    return record.chipId == currentChipId ? ReadResult::RECORD : ReadResult::CHIP_MISMATCH;
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

bool targetCanProvision(HardwareKind kind)
{
#if defined(ARCH_ESP32)
    const uint32_t expected = expectedEspFlashBytes(kind);
    return expected != 0U && ESP.getFlashChipSize() == expected;
#elif defined(ARCH_NRF52)
    return kind == HardwareKind::BOARD_SEEED_WIO_TRACKER_L1;
#else
    (void)kind;
    return false;
#endif
}

void applyValidRecord(const HardwareIdentityRecord &record)
{
    identity.storedKind = static_cast<HardwareKind>(record.boardKind);
    if (record.chipId != identity.chipId) {
        identity.state = HardwareIdentityState::CHIP_MISMATCH;
        identity.mismatch = true;
        return;
    }
    identity.state = HardwareIdentityState::VALID;
    identity.mismatch = identity.storedKind != identity.firmwareKind;
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
    const ReadResult dedicated = readDedicatedRecord(record);
    if (dedicated == ReadResult::RECORD) {
        applyValidRecord(record);
        return;
    }
    if (dedicated == ReadResult::INVALID) {
        identity.state = HardwareIdentityState::INVALID;
        LOG_ERROR("JARNSEN HW-ID: dedicated marker is corrupt; refusing automatic replacement");
        return;
    }
    if (dedicated == ReadResult::ERROR) {
        identity.state = HardwareIdentityState::STORAGE_ERROR;
        return;
    }
    if (dedicated == ReadResult::UNSUPPORTED) {
        identity.state = HardwareIdentityState::UNSUPPORTED;
        return;
    }

    // Migration path for alpha builds that stored the same v1 record in normal
    // Preferences/LittleFS. A valid legacy record is copied byte-for-byte so a
    // different firmware target can never relabel an already learned device.
    HardwareIdentityRecord legacy{};
    const ReadResult legacyResult = readLegacyRecord(legacy, identity.chipId);
    if (legacyResult == ReadResult::RECORD) {
        if (!writeDedicatedFirstRecord(legacy)) {
            identity.state = HardwareIdentityState::STORAGE_ERROR;
            return;
        }
        identity.provisionedThisBoot = true;
        applyValidRecord(legacy);
        return;
    }
    if (legacyResult == ReadResult::CHIP_MISMATCH) {
        identity.storedKind = static_cast<HardwareKind>(legacy.boardKind);
        identity.state = HardwareIdentityState::CHIP_MISMATCH;
        identity.mismatch = true;
        LOG_ERROR("JARNSEN HW-ID: legacy marker belongs to a different chip; refusing automatic replacement");
        return;
    }
    if (legacyResult == ReadResult::INVALID || legacyResult == ReadResult::ERROR) {
        identity.state = legacyResult == ReadResult::INVALID ? HardwareIdentityState::INVALID
                                                            : HardwareIdentityState::STORAGE_ERROR;
        LOG_ERROR("JARNSEN HW-ID: legacy marker is not safe to migrate; refusing automatic replacement");
        return;
    }

    // First provisioning. Compile-time board identity may initialize an empty
    // marker, but on ESP32 we additionally require the physical flash capacity
    // expected for that target. This blocks obvious cross-board mistakes such
    // as 8 MB firmware on a 16 MB V4 or 4 MB T-Beam before any identity is set.
    identity.state = HardwareIdentityState::EMPTY;
    if (!targetCanProvision(identity.firmwareKind)) {
        identity.state = HardwareIdentityState::UNSUPPORTED;
        identity.mismatch = true;
        LOG_ERROR("JARNSEN HW-ID: physical flash does not match firmware target; provisioning blocked");
        return;
    }

    const HardwareIdentityRecord first = makeRecord(identity.firmwareKind, identity.chipId);
    if (!writeDedicatedFirstRecord(first)) {
        identity.state = HardwareIdentityState::STORAGE_ERROR;
        return;
    }

    HardwareIdentityRecord verify{};
    if (readDedicatedRecord(verify) != ReadResult::RECORD || verify.chipId != identity.chipId ||
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
