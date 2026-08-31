#include "JarnsenLiveDisplay.h"
#include "jarnsen/core/display/JarnsenLiveDisplayBackend.h"

#include <atomic>
#include <cstring>

namespace
{
std::atomic<bool> liveActive{false};
uint16_t frameSequence = 0;

bool parseCommand(const char *command, jarnsen::display::LiveDisplayCommand &parsed)
{
    using jarnsen::display::LiveDisplayCommand;

    if (!command)
        return false;
    if (strcmp(command, "WAKE") == 0)
        parsed = LiveDisplayCommand::WAKE;
    else if (strcmp(command, "NEXT") == 0)
        parsed = LiveDisplayCommand::NEXT;
    else if (strcmp(command, "PREV") == 0)
        parsed = LiveDisplayCommand::PREV;
    else if (strcmp(command, "UP") == 0)
        parsed = LiveDisplayCommand::UP;
    else if (strcmp(command, "DOWN") == 0)
        parsed = LiveDisplayCommand::DOWN;
    else if (strcmp(command, "SELECT") == 0)
        parsed = LiveDisplayCommand::SELECT;
    else if (strcmp(command, "BACK") == 0)
        parsed = LiveDisplayCommand::BACK;
    else
        return false;
    return true;
}
} // namespace

void jarnsenLiveSetActive(bool active)
{
    const auto &backend = jarnsen::display::platformLiveDisplayBackend();
    if (!backend.available()) {
        liveActive = false;
        return;
    }

    liveActive = active;
    backend.setActive(active);
    if (active)
        backend.requestRender();
}

bool jarnsenLiveIsActive()
{
    return liveActive;
}

bool jarnsenLiveHandleCommand(const char *command)
{
    jarnsen::display::LiveDisplayCommand parsed{};
    if (!parseCommand(command, parsed))
        return false;

    const auto &backend = jarnsen::display::platformLiveDisplayBackend();
    if (!backend.available() || !backend.handleCommand(parsed))
        return false;

    backend.requestRender();
    return true;
}

void jarnsenLiveRequestRender()
{
    const auto &backend = jarnsen::display::platformLiveDisplayBackend();
    if (backend.available())
        backend.requestRender();
}

size_t jarnsenLiveCapture(uint8_t *buffer, size_t capacity, JarnsenLiveFrameInfo &info)
{
    const auto &backend = jarnsen::display::platformLiveDisplayBackend();
    if (!backend.available())
        return 0;

    const size_t bytes = backend.capture(buffer, capacity, info);
    if (bytes > 0)
        info.sequence = ++frameSequence;
    return bytes;
}
