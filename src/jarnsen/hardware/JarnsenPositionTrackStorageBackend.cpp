#include "jarnsen/core/position/JarnsenPositionTrackStorage.h"
#include "configuration.h"

#if defined(ARCH_ESP32) && HAS_WIFI
#include "FSCommon.h"
#include "concurrency/Lock.h"
#endif

namespace
{
using jarnsen::position::TrackStorageFile;

#if defined(ARCH_ESP32) && HAS_WIFI
concurrency::Lock trackStorageLock;

bool storageAvailable()
{
    return true;
}

void storageLock()
{
    trackStorageLock.lock();
}

void storageUnlock()
{
    trackStorageLock.unlock();
}

const char *trackPath(TrackStorageFile file)
{
    return file == TrackStorageFile::PREVIOUS ? "/jarnsen_track.prev.bin" : "/jarnsen_track.bin";
}

bool storageExists(TrackStorageFile file)
{
    return FSCom.exists(trackPath(file));
}

size_t storageSize(TrackStorageFile file)
{
    File handle = FSCom.open(trackPath(file), FILE_O_READ);
    if (!handle)
        return 0;
    const size_t bytes = handle.size();
    handle.close();
    return bytes;
}

bool storageRead(TrackStorageFile file, size_t offset, uint8_t *buffer, size_t length)
{
    if (!buffer || length == 0)
        return false;
    File handle = FSCom.open(trackPath(file), FILE_O_READ);
    if (!handle)
        return false;
    if (!handle.seek(offset)) {
        handle.close();
        return false;
    }
    const bool ok = handle.read(buffer, length) == length;
    handle.close();
    return ok;
}

bool storageAppend(TrackStorageFile file, const uint8_t *buffer, size_t length)
{
    if (!buffer || length == 0)
        return false;
    File handle = FSCom.open(trackPath(file), "a");
    if (!handle)
        return false;
    const bool ok = handle.write(buffer, length) == length;
    handle.flush();
    handle.close();
    return ok;
}

bool storageRemove(TrackStorageFile file)
{
    return !FSCom.exists(trackPath(file)) || FSCom.remove(trackPath(file));
}

bool storageRename(TrackStorageFile from, TrackStorageFile to)
{
    return FSCom.rename(trackPath(from), trackPath(to));
}
#else
bool storageAvailable()
{
    return false;
}
void storageLock() {}
void storageUnlock() {}
bool storageExists(TrackStorageFile)
{
    return false;
}
size_t storageSize(TrackStorageFile)
{
    return 0;
}
bool storageRead(TrackStorageFile, size_t, uint8_t *, size_t)
{
    return false;
}
bool storageAppend(TrackStorageFile, const uint8_t *, size_t)
{
    return false;
}
bool storageRemove(TrackStorageFile)
{
    return true;
}
bool storageRename(TrackStorageFile, TrackStorageFile)
{
    return false;
}
#endif
} // namespace

namespace jarnsen
{
namespace position
{

const TrackStorageBackend &platformTrackStorageBackend()
{
    static const TrackStorageBackend backend = {
        storageAvailable,
        storageLock,
        storageUnlock,
        storageExists,
        storageSize,
        storageRead,
        storageAppend,
        storageRemove,
        storageRename,
    };
    return backend;
}

} // namespace position
} // namespace jarnsen
