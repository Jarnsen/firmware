#pragma once

#include <cstddef>
#include <cstdint>

namespace jarnsen
{
namespace position
{

enum class TrackStorageFile : uint8_t { CURRENT = 0, PREVIOUS = 1 };

struct TrackStorageBackend {
    bool (*available)();
    void (*lock)();
    void (*unlock)();
    bool (*exists)(TrackStorageFile file);
    size_t (*size)(TrackStorageFile file);
    bool (*read)(TrackStorageFile file, size_t offset, uint8_t *buffer, size_t length);
    bool (*append)(TrackStorageFile file, const uint8_t *buffer, size_t length);
    bool (*remove)(TrackStorageFile file);
    bool (*rename)(TrackStorageFile from, TrackStorageFile to);
};

class TrackStorageGuard
{
  public:
    explicit TrackStorageGuard(const TrackStorageBackend &backend) : backend_(backend)
    {
        backend_.lock();
    }

    ~TrackStorageGuard()
    {
        backend_.unlock();
    }

    TrackStorageGuard(const TrackStorageGuard &) = delete;
    TrackStorageGuard &operator=(const TrackStorageGuard &) = delete;

  private:
    const TrackStorageBackend &backend_;
};

const TrackStorageBackend &platformTrackStorageBackend();

} // namespace position
} // namespace jarnsen
