#pragma once

#include "mesh/Throttle.h"

#include <cstddef>
#include <cstdint>
#include <cstring>

namespace jarnsen
{

struct NodeStateRecord;
constexpr uint32_t DIAGNOSTIC_LOG_FORMAT = 3U;
constexpr uint32_t DIAGNOSTIC_DETAIL_MS = 10U * 60U * 1000U;

// Fixed-size, allocation-free repetition tracking shared by both log backends.
class DiagnosticRepeatGate
{
  public:
    bool accept(const char *event, const char *detail, uint32_t now, bool verbose, uint32_t &repeats)
    {
        repeats = 0;
        if (verbose || !event || !std::strcmp(event, "WARN ") || !std::strcmp(event, "ERROR") || !std::strcmp(event, "CRIT "))
            return true;
        uint32_t hash = 2166136261U;
        for (const char *p = event; *p; ++p)
            hash = (hash ^ static_cast<uint8_t>(*p)) * 16777619U;
        const char *body = detail ? detail : "";
        if (!std::strncmp(body, "at_ms=", 6)) {
            const char *space = std::strchr(body, ' ');
            if (space)
                body = space + 1;
        }
        for (const char *p = body; *p; ++p)
            hash = (hash ^ static_cast<uint8_t>(*p)) * 16777619U;
        Slot *slot = nullptr;
        for (auto &candidate : slots_) {
            if (candidate.used && candidate.hash == hash) {
                slot = &candidate;
                break;
            }
        }
        if (slot && Throttle::isWithinTimespanMs(slot->lastMs, 60000U)) {
            ++slot->repeats;
            return false;
        }
        if (!slot) {
            slot = &slots_[next_++ % 12U];
            // Evicted suppression counts remain in the global counters.
            *slot = {};
        }
        repeats = slot->repeats;
        slot->hash = hash;
        slot->lastMs = now;
        slot->repeats = 0;
        slot->used = true;
        std::strncpy(slot->event, event, sizeof(slot->event) - 1U);
        std::strncpy(slot->context, body, sizeof(slot->context) - 1U);
        return true;
    }

    bool takeSummary(char *event, size_t eventSize, char *context, size_t contextSize, uint32_t &repeats)
    {
        for (auto &slot : slots_) {
            if (slot.used && slot.repeats && !Throttle::isWithinTimespanMs(slot.lastMs, 60000U)) {
                std::strncpy(event, slot.event, eventSize - 1U);
                event[eventSize - 1U] = '\0';
                std::strncpy(context, slot.context, contextSize - 1U);
                context[contextSize - 1U] = '\0';
                repeats = slot.repeats;
                slot.repeats = 0;
                return true;
            }
        }
        return false;
    }

  private:
    struct Slot {
        uint32_t hash = 0;
        uint32_t lastMs = 0;
        uint32_t repeats = 0;
        bool used = false;
        char event[24]{};
        char context[64]{};
    };
    Slot slots_[12]{};
    size_t next_ = 0;
};

inline uint32_t diagnosticCrc32(uint32_t crc, const uint8_t *data, size_t size)
{
    for (size_t i = 0; i < size; ++i) {
        crc ^= data[i];
        for (unsigned bit = 0; bit < 8U; ++bit)
            crc = (crc >> 1U) ^ (0xedb88320U & (0U - (crc & 1U)));
    }
    return crc;
}

void diagnosticPolicyInit();
const char *diagnosticRoleKey();
bool diagnosticDetailEnabled();
void diagnosticSetDetailEnabled(bool enabled);
bool diagnosticConsoleLevelEnabled(const char *level);
bool diagnosticTryWrite();
void diagnosticEndWrite();
bool diagnosticFormatLine(char *out, size_t capacity, const char *event, const char *detail);
void diagnosticNoteWrite(bool success);
void diagnosticNoteTruncation();
void diagnosticNoteRotation(size_t discardedBytes);
void diagnosticQueueEvent(const char *event, const char *fmt, ...);
void diagnosticCacheEvent(const char *action, const NodeStateRecord &record, const char *reason);
void diagnosticSleepEnter(bool deep, uint32_t plannedMs);
void diagnosticSleepWake(uint32_t plannedMs, uint32_t actualMs, int result, int cause, int buttonLevel, int radioLevel,
                         int motionLevel);
void diagnosticRuntimeTick();
bool diagnosticSnapshotMetadata(char *out, size_t capacity, const char *previousPath, size_t previousBytes,
                                const char *currentPath, size_t currentBytes);

class DiagnosticWriteScope
{
  public:
    DiagnosticWriteScope() : acquired_(diagnosticTryWrite()) {}
    ~DiagnosticWriteScope()
    {
        if (acquired_)
            diagnosticEndWrite();
    }
    explicit operator bool() const { return acquired_; }
    DiagnosticWriteScope(const DiagnosticWriteScope &) = delete;
    DiagnosticWriteScope &operator=(const DiagnosticWriteScope &) = delete;

  private:
    bool acquired_;
};

} // namespace jarnsen
