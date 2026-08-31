#include "jarnsen/core/display/JarnsenLiveDisplay.h"
#include "jarnsen/core/display/JarnsenLiveDisplayBackend.h"
#include "configuration.h"

#if HAS_SCREEN && defined(ARCH_ESP32)
#include "graphics/Screen.h"
#include "input/InputBroker.h"

#include <atomic>
#include <cstring>
#endif

namespace
{
using jarnsen::display::LiveDisplayCommand;

#if HAS_SCREEN && defined(ARCH_ESP32)
std::atomic<bool> liveActive{false};
TaskHandle_t renderTaskHandle = nullptr;

void renderTask(void *)
{
    for (;;) {
        ulTaskNotifyTake(pdTRUE, portMAX_DELAY);
        vTaskDelay(pdMS_TO_TICKS(60));
        if (liveActive && screen && !screen->isScreenOn())
            screen->renderForMirror();
    }
}

void inject(input_broker_event event)
{
    if (!inputBroker)
        return;
    InputEvent input = {.source = "jarnsen-live", .inputEvent = event, .kbchar = 0, .touchX = 0, .touchY = 0};
#if defined(HAS_FREE_RTOS) && !defined(ARCH_RP2040)
    inputBroker->queueInputEvent(&input);
#else
    inputBroker->injectInputEvent(&input);
#endif
}

bool liveDisplayAvailable()
{
    return true;
}

void liveDisplaySetActive(bool active)
{
    liveActive = active;
    if (active && !renderTaskHandle)
        xTaskCreate(renderTask, "LiveDisplay", 4096, nullptr, 1, &renderTaskHandle);
}

bool liveDisplayHandleCommand(LiveDisplayCommand command)
{
    if (!screen)
        return false;

    switch (command) {
    case LiveDisplayCommand::WAKE:
        screen->setOn(true);
        break;
    case LiveDisplayCommand::NEXT:
        inject(INPUT_BROKER_RIGHT);
        break;
    case LiveDisplayCommand::PREV:
        inject(INPUT_BROKER_LEFT);
        break;
    case LiveDisplayCommand::UP:
        inject(INPUT_BROKER_UP);
        break;
    case LiveDisplayCommand::DOWN:
        inject(INPUT_BROKER_DOWN);
        break;
    case LiveDisplayCommand::SELECT:
        inject(INPUT_BROKER_SELECT);
        break;
    case LiveDisplayCommand::BACK:
        inject(INPUT_BROKER_BACK);
        break;
    default:
        return false;
    }
    return true;
}

void liveDisplayRequestRender()
{
    if (renderTaskHandle)
        xTaskNotifyGive(renderTaskHandle);
}

size_t liveDisplayCapture(uint8_t *buffer, size_t capacity, JarnsenLiveFrameInfo &info)
{
    if (!buffer || !screen)
        return 0;

    OLEDDisplay *display = screen->getDisplayDevice();
    if (!display || !display->buffer)
        return 0;

    const size_t bytes = static_cast<size_t>(display->getWidth()) * ((display->getHeight() + 7U) / 8U);
    if (capacity < bytes || display->getWidth() > UINT8_MAX || display->getHeight() > UINT8_MAX)
        return 0;

    memcpy(buffer, display->buffer, bytes);
    info.width = static_cast<uint8_t>(display->getWidth());
    info.height = static_cast<uint8_t>(display->getHeight());
    info.screenOn = screen->isScreenOn();
    return bytes;
}
#else
bool liveDisplayAvailable()
{
    return false;
}

void liveDisplaySetActive(bool) {}

bool liveDisplayHandleCommand(LiveDisplayCommand)
{
    return false;
}

void liveDisplayRequestRender() {}

size_t liveDisplayCapture(uint8_t *, size_t, JarnsenLiveFrameInfo &)
{
    return 0;
}
#endif
} // namespace

namespace jarnsen
{
namespace display
{

const LiveDisplayBackend &platformLiveDisplayBackend()
{
    static const LiveDisplayBackend backend = {
        liveDisplayAvailable,
        liveDisplaySetActive,
        liveDisplayHandleCommand,
        liveDisplayRequestRender,
        liveDisplayCapture,
    };
    return backend;
}

} // namespace display
} // namespace jarnsen
