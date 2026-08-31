#pragma once

#include <cstddef>
#include <cstdint>

namespace jarnsen
{
namespace position
{

enum class TrackStorageFile : uint8_t { CURRENT = 0, PREVIOUS = 1 };

struct TrackStorageBackend {
    bool (*exists)(TrackStorageFile file);
    size_t (*size)(TrackStorageFile file);
    bool (*read)(TrackStorageFile file, size_t offset, uint8_t *buffer, size_t length);
    bool (*append)(TrackStorageFile file, const uint8_t *buffer, size_t length);
    bool (*remove)(TrackStorageFile file);
    bool (*rename)(TrackStorageFile from, TrackStorageFile to);
};

const TrackStorageBackend &platformTrackStorageBackend();

} // namespace position
} // namespace jarnsen
