#include "TacticalDisplayMirrorThread.h"

#if defined(HAS_TACTICAL_DISPLAY_MIRROR) && HAS_TACTICAL_DISPLAY_MIRROR && HAS_SCREEN

#include "TacticalDisplayMirror.h"
#include "graphics/Screen.h"
#include "input/InputBroker.h"
#include "main.h"

#include <Arduino.h>
#include <cstring>

namespace graphics
{
namespace
{
constexpr size_t COMMAND_BUFFER_SIZE = 32;
char commandBuffer[COMMAND_BUFFER_SIZE];
size_t commandLength = 0;

void injectMirrorInput(input_broker_event eventType)
{
    if (!inputBroker)
        return;

    const InputEvent event{
        .source = "usb-display-mirror",
        .inputEvent = eventType,
        .kbchar = 0,
        .touchX = 0,
        .touchY = 0,
    };
    inputBroker->injectInputEvent(&event);
}

void handleMirrorCommand(const char *command)
{
    if (!command || strncmp(command, "@TMC ", 5) != 0)
        return;

    const char *key = command + 5;
    if (strcmp(key, "LEFT") == 0)
        injectMirrorInput(INPUT_BROKER_LEFT);
    else if (strcmp(key, "RIGHT") == 0)
        injectMirrorInput(INPUT_BROKER_RIGHT);
    else if (strcmp(key, "UP") == 0)
        injectMirrorInput(INPUT_BROKER_UP);
    else if (strcmp(key, "DOWN") == 0)
        injectMirrorInput(INPUT_BROKER_DOWN);
    else if (strcmp(key, "SPACE") == 0 || strcmp(key, "SELECT") == 0)
        injectMirrorInput(INPUT_BROKER_SELECT);
}

void readMirrorCommands()
{
    while (Serial.available() > 0) {
        const int value = Serial.read();
        if (value < 0)
            return;

        const char character = static_cast<char>(value);
        if (character == '\r')
            continue;

        if (character == '\n') {
            commandBuffer[commandLength] = '\0';
            handleMirrorCommand(commandBuffer);
            commandLength = 0;
            continue;
        }

        if (commandLength + 1 < COMMAND_BUFFER_SIZE) {
            commandBuffer[commandLength++] = character;
        } else {
            // Drop overlong/non-mirror input and wait for the next line.
            commandLength = 0;
        }
    }
}
} // namespace

TacticalDisplayMirrorThread::TacticalDisplayMirrorThread() : concurrency::OSThread("display-mirror", 50) {}

int32_t TacticalDisplayMirrorThread::runOnce()
{
    readMirrorCommands();

    if (screen != nullptr && screen->isScreenOn()) {
        mirrorDisplayFrame(screen->getDisplayDevice());
    }
    return 50;
}
} // namespace graphics

#endif
