#pragma once

#include <cstddef>
#include <cstdint>

struct JarnsenLiveFrameInfo;

namespace jarnsen
{
namespace display
{

// Core-facing live-display contract. The Core owns protocol state and command
// parsing; the platform backend owns the actual screen, input broker and render
// scheduling implementation.
enum class LiveDisplayCommand : uint8_t {
    WAKE = 0,
    NEXT,
    PREV,
    UP,
    DOWN,
    SELECT,
    BACK,
};

struct LiveDisplayBackend {
    bool (*available)();
    void (*setActive)(bool active);
    bool (*handleCommand)(LiveDisplayCommand command);
    void (*requestRender)();
    size_t (*capture)(uint8_t *buffer, size_t capacity, JarnsenLiveFrameInfo &info);
};

// Implemented by the hardware layer. Unsupported platforms return a no-op
// backend so shared code never needs board/RTOS/display preprocessor branches.
const LiveDisplayBackend &platformLiveDisplayBackend();

} // namespace display
} // namespace jarnsen
