#include "jarnsen/core/position/JarnsenPositionTrack.h"
#include "jarnsen/core/position/JarnsenPositionCore.h"
#include "configuration.h"

#if defined(ARCH_ESP32) && HAS_WIFI

#include "FSCommon.h"
#include "concurrency/Lock.h"
#include "concurrency/LockGuard.h"

#include <Arduino.h>
#include <cstdio>

namespace
{
constexpr const char *CURRENT_TRACK = "/jarnsen_track.bin";
constexpr const char *PREVIOUS_TRACK = "/jarnsen_track.prev.bin";
constexpr uint32_t RECORD_MAGIC = 0x3152544aU; // JTR1 in little-endian storage
constexpr size_t MAX_TRACK_FILE_BYTES = 65520U; // 2,730 records; two files retain up to 5,460 points
constexpr double MIN_TRACK_DISTANCE_M = 25.0;

#pragma pack(push, 1)
struct StoredTrackPoint {
    uint32_t magic;
    uint32_t epoch;
    int32_t latitudeI;
    int32_t longitudeI;
    uint32_t accuracyMm;
    uint8_t source;
    uint8_t flags;
    uint16_t crc;
};
#pragma pack(pop)

static_assert(sizeof(StoredTrackPoint) == 24, "Unexpected track record size");

concurrency::Lock trackLock;
bool initialized = false;
bool lastPointValid = false;
JarnsenTrackPoint lastPoint;
bool exportActive = false;
uint8_t exportPhase = 0;
size_t exportRemaining = 0;
File exportFile;

uint16_t crc16(const uint8_t *data, size_t length)
{
    uint16_t crc = 0xffffU;
    while (length--) {
        crc ^= static_cast<uint16_t>(*data++) << 8U;
        for (uint8_t bit = 0; bit < 8; bit++)
            crc = (crc & 0x8000U) ? static_cast<uint16_t>((crc << 1U) ^ 0x1021U) : static_cast<uint16_t>(crc << 1U);
    }
    return crc;
}

bool validRecord(const StoredTrackPoint &record)
{
    if (record.magic != RECORD_MAGIC || record.source < static_cast<uint8_t>(JarnsenTrackSource::PHONE) ||
        record.source > static_cast<uint8_t>(JarnsenTrackSource::GPS))
        return false;
    if (record.latitudeI < -900000000 || record.latitudeI > 900000000 || record.longitudeI < -1800000000 ||
        record.longitudeI > 1800000000 || (record.latitudeI == 0 && record.longitudeI == 0))
        return false;
    return record.crc == crc16(reinterpret_cast<const uint8_t *>(&record), sizeof(record) - sizeof(record.crc));
}

void toPublic(const StoredTrackPoint &stored, JarnsenTrackPoint &point)
{
    point.epoch = stored.epoch;
    point.latitudeI = stored.latitudeI;
    point.longitudeI = stored.longitudeI;
    point.accuracyMm = stored.accuracyMm;
    point.source = static_cast<JarnsenTrackSource>(stored.source);
}

size_t fileRecordCount(const char *path)
{
    File file = FSCom.open(path, FILE_O_READ);
    if (!file)
        return 0;
    const size_t count = file.size() / sizeof(StoredTrackPoint);
    file.close();
    return count;
}

bool readLastValid(const char *path, JarnsenTrackPoint &point)
{
    File file = FSCom.open(path, FILE_O_READ);
    if (!file)
        return false;
    const size_t count = file.size() / sizeof(StoredTrackPoint);
    for (size_t index = count; index > 0; index--) {
        if (!file.seek((index - 1U) * sizeof(StoredTrackPoint)))
            break;
        StoredTrackPoint stored{};
        if (file.read(reinterpret_cast<uint8_t *>(&stored), sizeof(stored)) == sizeof(stored) && validRecord(stored)) {
            toPublic(stored, point);
            file.close();
            return true;
        }
    }
    file.close();
    return false;
}

void ensureInitialized()
{
    if (initialized)
        return;
    lastPointValid = readLastValid(CURRENT_TRACK, lastPoint) || readLastValid(PREVIOUS_TRACK, lastPoint);
    initialized = true;
}

bool openExportPhase()
{
    if (exportFile)
        exportFile.close();
    while (exportPhase <= 2U) {
        const char *path = exportPhase == 1U ? PREVIOUS_TRACK : CURRENT_TRACK;
        exportPhase++;
        exportFile = FSCom.open(path, FILE_O_READ);
        if (!exportFile)
            continue;
        exportRemaining = exportFile.size() / sizeof(StoredTrackPoint);
        if (exportRemaining != 0)
            return true;
        exportFile.close();
    }
    return false;
}
} // namespace

__attribute__((weak)) void jarnsenPositionTrackDiagnosticStored(const JarnsenTrackPoint &, const char *) {}

bool jarnsenPositionTrackNote(int32_t latitudeI, int32_t longitudeI, uint32_t epoch, uint32_t accuracyMm,
                              JarnsenTrackSource source)
{
    if (latitudeI < -900000000 || latitudeI > 900000000 || longitudeI < -1800000000 || longitudeI > 1800000000 ||
        (latitudeI == 0 && longitudeI == 0) || epoch == 0)
        return false;

    JarnsenTrackPoint saved;
    {
        concurrency::LockGuard guard(&trackLock);
        ensureInitialized();
        if (exportActive)
            return false;
        if (lastPointValid &&
            jarnsenPositionDistanceMeters(lastPoint.latitudeI, lastPoint.longitudeI, latitudeI, longitudeI) <= MIN_TRACK_DISTANCE_M)
            return false;

        const size_t currentBytes = fileRecordCount(CURRENT_TRACK) * sizeof(StoredTrackPoint);
        if (currentBytes + sizeof(StoredTrackPoint) > MAX_TRACK_FILE_BYTES) {
            if (FSCom.exists(PREVIOUS_TRACK))
                FSCom.remove(PREVIOUS_TRACK);
            if (FSCom.exists(CURRENT_TRACK) && !FSCom.rename(CURRENT_TRACK, PREVIOUS_TRACK))
                return false;
        }

        StoredTrackPoint stored{};
        stored.magic = RECORD_MAGIC;
        stored.epoch = epoch;
        stored.latitudeI = latitudeI;
        stored.longitudeI = longitudeI;
        stored.accuracyMm = accuracyMm;
        stored.source = static_cast<uint8_t>(source);
        stored.crc = crc16(reinterpret_cast<const uint8_t *>(&stored), sizeof(stored) - sizeof(stored.crc));

        File file = FSCom.open(CURRENT_TRACK, "a");
        if (!file)
            return false;
        const bool written = file.write(reinterpret_cast<const uint8_t *>(&stored), sizeof(stored)) == sizeof(stored);
        file.flush();
        file.close();
        if (!written)
            return false;

        toPublic(stored, lastPoint);
        lastPointValid = true;
        saved = lastPoint;
    }

    char mgrs[28] = "---";
    jarnsenPositionFormatMgrs8(saved.latitudeI, saved.longitudeI, mgrs, sizeof(mgrs));
    jarnsenPositionTrackDiagnosticStored(saved, mgrs);
    return true;
}

size_t jarnsenPositionTrackCount()
{
    concurrency::LockGuard guard(&trackLock);
    ensureInitialized();
    return fileRecordCount(PREVIOUS_TRACK) + fileRecordCount(CURRENT_TRACK);
}

void jarnsenPositionTrackClear()
{
    concurrency::LockGuard guard(&trackLock);
    if (exportFile)
        exportFile.close();
    exportActive = false;
    exportPhase = 0;
    exportRemaining = 0;
    if (FSCom.exists(CURRENT_TRACK))
        FSCom.remove(CURRENT_TRACK);
    if (FSCom.exists(PREVIOUS_TRACK))
        FSCom.remove(PREVIOUS_TRACK);
    lastPoint = JarnsenTrackPoint{};
    lastPointValid = false;
    initialized = true;
}

bool jarnsenPositionTrackStartExport()
{
    concurrency::LockGuard guard(&trackLock);
    ensureInitialized();
    if (exportActive)
        return false;
    exportActive = true;
    exportPhase = 1;
    exportRemaining = 0;
    return true;
}

bool jarnsenPositionTrackReadExport(JarnsenTrackPoint &point)
{
    concurrency::LockGuard guard(&trackLock);
    if (!exportActive)
        return false;

    while (true) {
        if (!exportFile || exportRemaining == 0) {
            if (!openExportPhase())
                return false;
        }
        StoredTrackPoint stored{};
        const size_t count = exportFile.read(reinterpret_cast<uint8_t *>(&stored), sizeof(stored));
        if (exportRemaining)
            exportRemaining--;
        if (count == sizeof(stored) && validRecord(stored)) {
            toPublic(stored, point);
            return true;
        }
    }
}

void jarnsenPositionTrackEndExport()
{
    concurrency::LockGuard guard(&trackLock);
    if (exportFile)
        exportFile.close();
    exportActive = false;
    exportPhase = 0;
    exportRemaining = 0;
}

#else

__attribute__((weak)) void jarnsenPositionTrackDiagnosticStored(const JarnsenTrackPoint &, const char *) {}

bool jarnsenPositionTrackNote(int32_t, int32_t, uint32_t, uint32_t, JarnsenTrackSource)
{
    return false;
}
size_t jarnsenPositionTrackCount()
{
    return 0;
}
void jarnsenPositionTrackClear() {}
bool jarnsenPositionTrackStartExport()
{
    return false;
}
bool jarnsenPositionTrackReadExport(JarnsenTrackPoint &)
{
    return false;
}
void jarnsenPositionTrackEndExport() {}

#endif

bool jarnsenPositionTrackFormatMgrs8(int32_t latitudeI, int32_t longitudeI, char *out, size_t outSize)
{
    return jarnsenPositionFormatMgrs8(latitudeI, longitudeI, out, outSize);
}

const char *jarnsenPositionTrackSourceName(JarnsenTrackSource source)
{
    return source == JarnsenTrackSource::PHONE ? "phone" : "gps";
}
