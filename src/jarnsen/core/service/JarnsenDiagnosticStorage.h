#pragma once

#include "mesh/Throttle.h"
#include <Arduino.h>
#include <algorithm>
#include <cstddef>
#include <cstdint>
#include <cstdio>

namespace jarnsen
{
constexpr size_t DIAGNOSTIC_STORAGE_MAX_BYTES = 2U * 1024U * 1024U;
constexpr uint32_t DIAGNOSTIC_EXPORT_IDLE_MS = 60000U;
constexpr uint32_t DIAGNOSTIC_EXPORT_MAX_MS = 20U * 60U * 1000U;

struct DiagnosticStorageLimits {
    bool measured = false;
    size_t total = 0;
    size_t used = 0;
    size_t free = 0;
    size_t reserve = 0;
    size_t budget = 0;
    size_t perFile = 0;
};

inline DiagnosticStorageLimits diagnosticStorageLimits(size_t total, size_t used, size_t logBytes)
{
    DiagnosticStorageLimits out;
    if (!total || used > total)
        return out;
    out.measured = true;
    out.total = total;
    out.used = used;
    out.free = total - used;
    out.reserve = std::min(total, std::max<size_t>(16U * 1024U, total / 4U));
    const size_t other = used - std::min(used, logBytes);
    const size_t available = total - other;
    const size_t budget = available > out.reserve ? available - out.reserve : 0U;
    out.perFile = (std::min(budget, DIAGNOSTIC_STORAGE_MAX_BYTES) / 2U / 4096U) * 4096U;
    out.budget = out.perFile * 2U;
    return out;
}

inline bool diagnosticExportExpired(uint32_t started, uint32_t progress)
{
    return !Throttle::isWithinTimespanMs(started, DIAGNOSTIC_EXPORT_MAX_MS) ||
           !Throttle::isWithinTimespanMs(progress, DIAGNOSTIC_EXPORT_IDLE_MS);
}

class DiagnosticLogStorage
{
  public:
    using SizeOf = size_t (*)(const char *);
    const DiagnosticStorageLimits &limits() const { return limits_; }
    uint32_t skipped() const { return skipped_; }
    bool ioError() const { return ioError_; }
    bool rotated() const { return rotated_; }
    size_t discarded() const { return discarded_; }
    void format(char *out, size_t capacity) const
    {
        char values[6][3U * sizeof(size_t) + 1U]{};
        const size_t numbers[] = {limits_.total, limits_.used, limits_.free, limits_.reserve, limits_.budget, limits_.perFile};
        for (size_t i = 0; i < 6U; ++i) {
            size_t value = numbers[i], digits = 0;
            do {
                values[i][digits++] = '0' + value % 10U;
                value /= 10U;
            } while (value);
            std::reverse(values[i], values[i] + digits);
        }
        snprintf(out, capacity, "measured=%u total=%s used=%s free=%s reserve=%s budget=%s per_file=%s skipped=%u",
                 limits_.measured ? 1U : 0U, values[0], values[1], values[2], values[3], values[4], values[5],
                 (unsigned)skipped_);
    }

    template <typename FS> void measure(FS &fs, size_t current, size_t previous, bool force = false)
    {
        if (sampled_ && !force && pendingBytes_ < 16384U && Throttle::isWithinTimespanMs(sampledAt_, 30000U))
            return;
        const auto reading = readSpace(fs, 0);
        if (current > reading.total || previous > reading.total - current)
            limits_ = {};
        else
            limits_ = diagnosticStorageLimits(reading.total, reading.used, current + previous);
        sampledAt_ = millis();
        sampled_ = true;
        pendingBytes_ = 0;
    }

    template <typename FS>
    bool prepare(FS &fs, const char *currentPath, const char *previousPath, SizeOf sizeOf, size_t incoming, bool pinned)
    {
        ioError_ = rotated_ = false;
        discarded_ = 0;
        size_t current = sizeOf(currentPath), previous = sizeOf(previousPath);
        measure(fs, current, previous);
        if (!limits_.measured || !incoming)
            return skip();
        if (current > limits_.total || previous > limits_.total - current)
            return skip();

        if (fits(current, previous, incoming))
            return true;
        measure(fs, current, previous, true);
        if (fits(current, previous, incoming))
            return true;
        if (pinned)
            return skip();

        if (fs.exists(previousPath)) {
            if (!fs.remove(previousPath))
                return fail();
            discarded_ += previous;
            previous = 0;
            rotated_ = true;
        }
        if ((incoming > limits_.perFile || current > limits_.perFile - incoming) && fs.exists(currentPath)) {
            if (!fs.rename(currentPath, previousPath))
                return fail();
            previous = current;
            current = 0;
            rotated_ = true;
        }
        measure(fs, current, previous, true);
        if (!fits(current, previous, incoming) && fs.exists(previousPath)) {
            if (!fs.remove(previousPath))
                return fail();
            discarded_ += previous;
            previous = 0;
            rotated_ = true;
            measure(fs, current, previous, true);
        }
        if (!fits(current, previous, incoming) && fs.exists(currentPath)) {
            if (!fs.remove(currentPath))
                return fail();
            discarded_ += current;
            current = 0;
            rotated_ = true;
            measure(fs, current, previous, true);
        }
        return fits(current, previous, incoming) ? true : skip();
    }

    void noteWritten(size_t bytes, bool success)
    {
        pendingBytes_ = bytes > SIZE_MAX - pendingBytes_ ? SIZE_MAX : pendingBytes_ + bytes;
        if (!success)
            sampled_ = false;
    }

    void invalidate() { sampled_ = false; }

  private:
    struct Space {
        size_t total, used;
    };
    template <typename FS> static auto readSpace(FS &fs, int) -> decltype(fs.totalBytes(), fs.usedBytes(), Space{})
    {
        return {fs.totalBytes(), fs.usedBytes()};
    }
    template <typename FS> static Space readSpace(FS &, long) { return {}; }

    bool fits(size_t current, size_t previous, size_t incoming) const
    {
        if (!limits_.measured || incoming > limits_.perFile || current > limits_.perFile - incoming ||
            previous > limits_.budget || current > limits_.budget - previous || incoming > limits_.budget - previous - current)
            return false;
        const size_t free = limits_.free - std::min(limits_.free, pendingBytes_);
        return free >= limits_.reserve && free - limits_.reserve >= 4096U && incoming <= free - limits_.reserve - 4096U;
    }
    bool skip()
    {
        if (skipped_ != UINT32_MAX)
            ++skipped_;
        return false;
    }
    bool fail()
    {
        ioError_ = true;
        sampled_ = false;
        return skip();
    }
    DiagnosticStorageLimits limits_;
    uint32_t sampledAt_ = 0, skipped_ = 0;
    size_t pendingBytes_ = 0, discarded_ = 0;
    bool sampled_ = false, ioError_ = false, rotated_ = false;
};
} // namespace jarnsen
