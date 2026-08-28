#include "mesh/http/JarnsenPositionTrack.h"

#if defined(ARCH_ESP32) && HAS_WIFI && (defined(_VARIANT_HELTEC_V3) || defined(HELTEC_TRACKER_V1_1))

#include "FSCommon.h"
#include "concurrency/Lock.h"
#include "concurrency/LockGuard.h"

#if defined(_VARIANT_HELTEC_V3)
#include "infrastructure/HeltecV3DiagnosticLog.h"
#else
#include "vehicle/TrackerDiagnosticLog.h"
#endif

#include <Arduino.h>
#include <algorithm>
#include <cmath>
#include <cstdio>
#include <cstring>

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
        crc ^= (uint16_t)(*data++) << 8U;
        for (uint8_t bit = 0; bit < 8; bit++)
            crc = (crc & 0x8000U) ? (uint16_t)((crc << 1U) ^ 0x1021U) : (uint16_t)(crc << 1U);
    }
    return crc;
}

bool validRecord(const StoredTrackPoint &record)
{
    if (record.magic != RECORD_MAGIC || record.source < (uint8_t)JarnsenTrackSource::PHONE ||
        record.source > (uint8_t)JarnsenTrackSource::GPS)
        return false;
    if (record.latitudeI < -900000000 || record.latitudeI > 900000000 || record.longitudeI < -1800000000 ||
        record.longitudeI > 1800000000 || (record.latitudeI == 0 && record.longitudeI == 0))
        return false;
    return record.crc == crc16((const uint8_t *)&record, sizeof(record) - sizeof(record.crc));
}

void toPublic(const StoredTrackPoint &stored, JarnsenTrackPoint &point)
{
    point.epoch = stored.epoch;
    point.latitudeI = stored.latitudeI;
    point.longitudeI = stored.longitudeI;
    point.accuracyMm = stored.accuracyMm;
    point.source = (JarnsenTrackSource)stored.source;
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
        if (file.read((uint8_t *)&stored, sizeof(stored)) == sizeof(stored) && validRecord(stored)) {
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

double distanceMeters(int32_t latitudeA, int32_t longitudeA, int32_t latitudeB, int32_t longitudeB)
{
    constexpr double DEG_TO_RAD_LOCAL = 0.017453292519943295769;
    constexpr double EARTH_RADIUS_M = 6371000.0;
    const double latA = latitudeA * 1e-7 * DEG_TO_RAD_LOCAL;
    const double latB = latitudeB * 1e-7 * DEG_TO_RAD_LOCAL;
    const double dLat = latB - latA;
    const double dLon = ((double)longitudeB - (double)longitudeA) * 1e-7 * DEG_TO_RAD_LOCAL;
    const double x = dLon * cos((latA + latB) * 0.5);
    return sqrt(dLat * dLat + x * x) * EARTH_RADIUS_M;
}

void logStoredPoint(const JarnsenTrackPoint &point)
{
    char mgrs[28] = "---";
    jarnsenPositionTrackFormatMgrs8(point.latitudeI, point.longitudeI, mgrs, sizeof(mgrs));
#if defined(_VARIANT_HELTEC_V3)
    heltecV3DiagLog("TRACK_POINT", "lat=%.7f lon=%.7f epoch=%u mgrs=%s source=%s acc=%umm", point.latitudeI * 1e-7,
                    point.longitudeI * 1e-7, (unsigned)point.epoch, mgrs,
                    jarnsenPositionTrackSourceName(point.source), (unsigned)point.accuracyMm);
#else
    trackerDiagLog("TRACK_POINT", "lat=%.7f lon=%.7f epoch=%u mgrs=%s source=%s acc=%umm", point.latitudeI * 1e-7,
                   point.longitudeI * 1e-7, (unsigned)point.epoch, mgrs,
                   jarnsenPositionTrackSourceName(point.source), (unsigned)point.accuracyMm);
#endif
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
            distanceMeters(lastPoint.latitudeI, lastPoint.longitudeI, latitudeI, longitudeI) <= MIN_TRACK_DISTANCE_M)
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
        stored.source = (uint8_t)source;
        stored.crc = crc16((const uint8_t *)&stored, sizeof(stored) - sizeof(stored.crc));

        File file = FSCom.open(CURRENT_TRACK, "a");
        if (!file)
            return false;
        const bool written = file.write((const uint8_t *)&stored, sizeof(stored)) == sizeof(stored);
        file.flush();
        file.close();
        if (!written)
            return false;

        toPublic(stored, lastPoint);
        lastPointValid = true;
        saved = lastPoint;
    }
    logStoredPoint(saved);
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
        const size_t count = exportFile.read((uint8_t *)&stored, sizeof(stored));
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

const char *jarnsenPositionTrackSourceName(JarnsenTrackSource source)
{
    return source == JarnsenTrackSource::PHONE ? "phone" : "gps";
}

namespace
{
char latitudeBand(double latitude)
{
    static constexpr char bands[] = "CDEFGHJKLMNPQRSTUVWX";
    if (latitude < -80.0 || latitude > 84.0)
        return 0;
    int index = (int)floor((latitude + 80.0) / 8.0);
    index = std::max(0, std::min(19, index));
    return bands[index];
}

int utmZone(double latitude, double longitude)
{
    int zone = (int)floor((longitude + 180.0) / 6.0) + 1;
    zone = std::max(1, std::min(60, zone));
    if (latitude >= 56.0 && latitude < 64.0 && longitude >= 3.0 && longitude < 12.0)
        zone = 32;
    if (latitude >= 72.0 && latitude < 84.0) {
        if (longitude >= 0.0 && longitude < 9.0)
            zone = 31;
        else if (longitude < 21.0)
            zone = 33;
        else if (longitude < 33.0)
            zone = 35;
        else if (longitude < 42.0)
            zone = 37;
    }
    return zone;
}
} // namespace

bool jarnsenPositionTrackFormatMgrs8(int32_t latitudeI, int32_t longitudeI, char *out, size_t outSize)
{
    if (!out || outSize < 24 || (latitudeI == 0 && longitudeI == 0))
        return false;
    const double latitude = latitudeI * 1e-7;
    const double longitude = longitudeI * 1e-7;
    const char band = latitudeBand(latitude);
    if (!band)
        return false;

    constexpr double a = 6378137.0;
    constexpr double eccSquared = 0.00669438;
    constexpr double k0 = 0.9996;
    constexpr double degToRad = 0.017453292519943295769;
    const int zone = utmZone(latitude, longitude);
    const double lonOrigin = (zone - 1) * 6.0 - 180.0 + 3.0;
    const double latRad = latitude * degToRad;
    const double lonRad = longitude * degToRad;
    const double lonOriginRad = lonOrigin * degToRad;
    const double eccPrimeSquared = eccSquared / (1.0 - eccSquared);
    const double sinLat = sin(latRad);
    const double cosLat = cos(latRad);
    const double tanLat = tan(latRad);
    const double n = a / sqrt(1.0 - eccSquared * sinLat * sinLat);
    const double t = tanLat * tanLat;
    const double c = eccPrimeSquared * cosLat * cosLat;
    const double aa = cosLat * (lonRad - lonOriginRad);
    const double m =
        a * ((1.0 - eccSquared / 4.0 - 3.0 * eccSquared * eccSquared / 64.0 -
              5.0 * eccSquared * eccSquared * eccSquared / 256.0) *
                 latRad -
             (3.0 * eccSquared / 8.0 + 3.0 * eccSquared * eccSquared / 32.0 +
              45.0 * eccSquared * eccSquared * eccSquared / 1024.0) *
                 sin(2.0 * latRad) +
             (15.0 * eccSquared * eccSquared / 256.0 + 45.0 * eccSquared * eccSquared * eccSquared / 1024.0) *
                 sin(4.0 * latRad) -
             (35.0 * eccSquared * eccSquared * eccSquared / 3072.0) * sin(6.0 * latRad));
    const double easting =
        k0 * n *
            (aa + (1.0 - t + c) * aa * aa * aa / 6.0 +
             (5.0 - 18.0 * t + t * t + 72.0 * c - 58.0 * eccPrimeSquared) * aa * aa * aa * aa * aa / 120.0) +
        500000.0;
    double northing =
        k0 * (m + n * tanLat *
                      (aa * aa / 2.0 + (5.0 - t + 9.0 * c + 4.0 * c * c) * aa * aa * aa * aa / 24.0 +
                       (61.0 - 58.0 * t + t * t + 600.0 * c - 330.0 * eccPrimeSquared) * aa * aa * aa * aa * aa *
                           aa / 720.0));
    if (latitude < 0.0)
        northing += 10000000.0;

    static constexpr const char *eastingSets[] = {"ABCDEFGH", "JKLMNPQR", "STUVWXYZ"};
    static constexpr char northingLetters[] = "ABCDEFGHJKLMNPQRSTUV";
    const int e100k = (int)floor(easting / 100000.0);
    if (e100k < 1 || e100k > 8)
        return false;
    const char eLetter = eastingSets[(zone - 1) % 3][e100k - 1];
    const int n100k = (int)floor(northing / 100000.0) % 20;
    const char nLetter = northingLetters[(n100k + (zone % 2 == 0 ? 5 : 0)) % 20];
    int eMeters = (int)floor(easting) % 100000;
    int nMeters = (int)floor(northing) % 100000;
    if (eMeters < 0)
        eMeters += 100000;
    if (nMeters < 0)
        nMeters += 100000;
    snprintf(out, outSize, "%02d%c %c%c %04d %04d", zone, band, eLetter, nLetter, eMeters / 10, nMeters / 10);
    return true;
}

#endif
