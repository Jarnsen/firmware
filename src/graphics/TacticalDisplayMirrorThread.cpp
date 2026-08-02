#include "TacticalDisplayMirrorThread.h"

#if defined(HAS_TACTICAL_DISPLAY_MIRROR) && HAS_TACTICAL_DISPLAY_MIRROR && HAS_SCREEN

#include "TacticalDisplayMirror.h"
#include "graphics/Screen.h"
#include "input/InputBroker.h"
#include "main.h"

#include <Arduino.h>
#include <cstdlib>
#include <cstring>

namespace graphics
{
namespace
{
constexpr size_t COMMAND_BUFFER_SIZE = 96;
char commandBuffer[COMMAND_BUFFER_SIZE];
size_t commandLength = 0;

bool injectMirrorInput(input_broker_event eventType)
{
    if (!inputBroker)
        return false;

    const InputEvent event{
        .source = "usb-display-mirror",
        .inputEvent = eventType,
        .kbchar = 0,
        .touchX = 0,
        .touchY = 0,
    };
    inputBroker->injectInputEvent(&event);
    return true;
}

void emitMirrorAck(uint32_t requestId, const char *status)
{
    Serial.printf("@TMA %lu %s %lu\n", static_cast<unsigned long>(requestId), status,
                  static_cast<unsigned long>(millis()));
}

bool resolveMirrorKey(const char *key, input_broker_event &eventType)
{
    if (strcmp(key, "LEFT") == 0)
        eventType = INPUT_BROKER_LEFT;
    else if (strcmp(key, "RIGHT") == 0)
        eventType = INPUT_BROKER_RIGHT;
    else if (strcmp(key, "UP") == 0)
        eventType = INPUT_BROKER_UP;
    else if (strcmp(key, "DOWN") == 0)
        eventType = INPUT_BROKER_DOWN;
    else if (strcmp(key, "SPACE") == 0 || strcmp(key, "SELECT") == 0 || strcmp(key, "ENTER") == 0)
        eventType = INPUT_BROKER_SELECT;
    else if (strcmp(key, "BACK") == 0 || strcmp(key, "ESC") == 0)
        eventType = INPUT_BROKER_BACK;
    else
        return false;
    return true;
}

void handleMirrorCommand(char *command)
{
    if (!command || strncmp(command, "@TMC ", 5) != 0)
        return;

    char *payload = command + 5;
    while (*payload == ' ')
        ++payload;

    if (strncmp(payload, "CAPS", 4) == 0) {
        Serial.printf("@TMA CAPS TMF3 ACK1\n");
        return;
    }

    uint32_t requestId = 0;
    bool hasRequestId = false;
    char *key = payload;
    char *numberEnd = nullptr;
    const unsigned long parsedId = strtoul(payload, &numberEnd, 10);
    if (numberEnd != payload && *numberEnd == ' ') {
        while (*numberEnd == ' ')
            ++numberEnd;
        if (*numberEnd != '\0') {
            requestId = static_cast<uint32_t>(parsedId);
            hasRequestId = true;
            key = numberEnd;
        }
    }

    input_broker_event eventType;
    if (!resolveMirrorKey(key, eventType)) {
        if (hasRequestId)
            emitMirrorAck(requestId, "ERR");
        return;
    }

    // Stop the current image transfer immediately so the input event wins the
    // next scheduler slices instead of waiting behind display chunks.
    prioritizeMirrorInput();
    const bool injected = injectMirrorInput(eventType);
    if (hasRequestId)
        emitMirrorAck(requestId, injected ? "OK" : "NOINPUT");
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
            // Drop an overlong/non-mirror line and resynchronize at the next newline.
            commandLength = 0;
        }
    }
}
} // namespace

TacticalDisplayMirrorThread::TacticalDisplayMirrorThread() : concurrency::OSThread("display-mirror", 10) {}

int32_t TacticalDisplayMirrorThread::runOnce()
{
    readMirrorCommands();

    if (screen != nullptr && screen->isScreenOn()) {
        mirrorDisplayFrame(screen->getDisplayDevice());
    }
    return 10;
}
} // namespace graphics

#endif
