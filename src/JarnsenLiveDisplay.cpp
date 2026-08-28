#include "JarnsenLiveDisplay.h"
#include "configuration.h"

#if HAS_SCREEN && defined(ARCH_ESP32)

#include "graphics/Screen.h"
#include "input/InputBroker.h"

#include <atomic>
#include <cstring>

namespace
{
std::atomic<bool> liveActive{false};
uint16_t frameSequence = 0;
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
} // namespace

void jarnsenLiveSetActive(bool active)
{
    liveActive = active;
    if (active) {
        if (!renderTaskHandle)
            xTaskCreate(renderTask, "LiveDisplay", 4096, nullptr, 1, &renderTaskHandle);
        jarnsenLiveRequestRender();
    }
}

bool jarnsenLiveIsActive()
{
    return liveActive;
}

bool jarnsenLiveHandleCommand(const char *command)
{
    if (!command || !screen)
        return false;
    if (strcmp(command, "WAKE") == 0) {
        screen->setOn(true);
    } else if (strcmp(command, "NEXT") == 0) {
        inject(INPUT_BROKER_RIGHT);
    } else if (strcmp(command, "PREV") == 0) {
        inject(INPUT_BROKER_LEFT);
    } else if (strcmp(command, "UP") == 0) {
        inject(INPUT_BROKER_UP);
    } else if (strcmp(command, "DOWN") == 0) {
        inject(INPUT_BROKER_DOWN);
    } else if (strcmp(command, "SELECT") == 0) {
        inject(INPUT_BROKER_SELECT);
    } else if (strcmp(command, "BACK") == 0) {
        inject(INPUT_BROKER_BACK);
    } else {
        return false;
    }
    jarnsenLiveRequestRender();
    return true;
}

void jarnsenLiveRequestRender()
{
    if (renderTaskHandle)
        xTaskNotifyGive(renderTaskHandle);
}

size_t jarnsenLiveCapture(uint8_t *buffer, size_t capacity, JarnsenLiveFrameInfo &info)
{
    if (!buffer || !screen)
        return 0;
    OLEDDisplay *display = screen->getDisplayDevice();
    if (!display || !display->buffer)
        return 0;
    const size_t bytes = (size_t)display->getWidth() * ((display->getHeight() + 7U) / 8U);
    if (capacity < bytes || display->getWidth() > UINT8_MAX || display->getHeight() > UINT8_MAX)
        return 0;
    memcpy(buffer, display->buffer, bytes);
    info.width = (uint8_t)display->getWidth();
    info.height = (uint8_t)display->getHeight();
    info.sequence = ++frameSequence;
    info.screenOn = screen->isScreenOn();
    return bytes;
}

#else

void jarnsenLiveSetActive(bool) {}
bool jarnsenLiveIsActive() { return false; }
bool jarnsenLiveHandleCommand(const char *) { return false; }
void jarnsenLiveRequestRender() {}
size_t jarnsenLiveCapture(uint8_t *, size_t, JarnsenLiveFrameInfo &) { return 0; }

#endif
