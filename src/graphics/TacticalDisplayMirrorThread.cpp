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
constexpr uint32_t PAGE_NAVIGATION_INTERVAL_MS = 240;
constexpr uint32_t MENU_NAVIGATION_INTERVAL_MS = 110;
constexpr uint32_t ACTION_INTERVAL_MS = 180;

enum class MirrorInputClass : uint8_t { PAGE, MENU, ACTION };

struct PendingMirrorInput {
    bool valid = false;
    bool hasRequestId = false;
    uint32_t requestId = 0;
    input_broker_event eventType = INPUT_BROKER_NONE;
    MirrorInputClass inputClass = MirrorInputClass::ACTION;
};

char commandBuffer[COMMAND_BUFFER_SIZE];
size_t commandLength = 0;
bool discardUntilNewline = false;
PendingMirrorInput pendingInput;
uint32_t lastPageInputAt = 0;
uint32_t lastMenuInputAt = 0;
uint32_t lastActionInputAt = 0;

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
#if defined(HAS_FREE_RTOS) && !defined(ARCH_RP2040)
    inputBroker->queueInputEvent(&event);
#else
    inputBroker->injectInputEvent(&event);
#endif
    return true;
}

void emitMirrorAck(uint32_t requestId, const char *status)
{
    Serial.printf("@TMA %lu %s %lu\n", static_cast<unsigned long>(requestId), status, static_cast<unsigned long>(millis()));
}

bool resolveMirrorKey(const char *key, input_broker_event &eventType, MirrorInputClass &inputClass)
{
    if (strcmp(key, "LEFT") == 0) {
        eventType = INPUT_BROKER_LEFT;
        inputClass = MirrorInputClass::PAGE;
    } else if (strcmp(key, "RIGHT") == 0) {
        eventType = INPUT_BROKER_RIGHT;
        inputClass = MirrorInputClass::PAGE;
    } else if (strcmp(key, "UP") == 0) {
        eventType = INPUT_BROKER_UP;
        inputClass = MirrorInputClass::MENU;
    } else if (strcmp(key, "DOWN") == 0) {
        eventType = INPUT_BROKER_DOWN;
        inputClass = MirrorInputClass::MENU;
    } else if (strcmp(key, "SPACE") == 0 || strcmp(key, "SELECT") == 0 || strcmp(key, "ENTER") == 0) {
        eventType = INPUT_BROKER_SELECT;
        inputClass = MirrorInputClass::ACTION;
    } else if (strcmp(key, "BACK") == 0 || strcmp(key, "ESC") == 0) {
        eventType = INPUT_BROKER_BACK;
        inputClass = MirrorInputClass::ACTION;
    } else {
        return false;
    }
    return true;
}

void queueMirrorInput(uint32_t requestId, bool hasRequestId, input_broker_event eventType, MirrorInputClass inputClass)
{
    if (pendingInput.valid && pendingInput.hasRequestId)
        emitMirrorAck(pendingInput.requestId, "COALESCED");

    pendingInput.valid = true;
    pendingInput.hasRequestId = hasRequestId;
    pendingInput.requestId = requestId;
    pendingInput.eventType = eventType;
    pendingInput.inputClass = inputClass;
}

bool intervalElapsed(uint32_t now, uint32_t previous, uint32_t interval)
{
    return !previous || static_cast<uint32_t>(now - previous) >= interval;
}

void processPendingMirrorInput()
{
    if (!pendingInput.valid)
        return;

    const uint32_t now = millis();
    uint32_t *lastInputAt = &lastActionInputAt;
    uint32_t minimumInterval = ACTION_INTERVAL_MS;
    if (pendingInput.inputClass == MirrorInputClass::PAGE) {
        lastInputAt = &lastPageInputAt;
        minimumInterval = PAGE_NAVIGATION_INTERVAL_MS;
    } else if (pendingInput.inputClass == MirrorInputClass::MENU) {
        lastInputAt = &lastMenuInputAt;
        minimumInterval = MENU_NAVIGATION_INTERVAL_MS;
    }

    if (!intervalElapsed(now, *lastInputAt, minimumInterval))
        return;

    const PendingMirrorInput command = pendingInput;
    pendingInput = PendingMirrorInput{};

    prioritizeMirrorInput();
    const bool injected = injectMirrorInput(command.eventType);
    if (injected)
        *lastInputAt = now;
    if (command.hasRequestId)
        emitMirrorAck(command.requestId, injected ? "OK" : "NOINPUT");
}

void handleMirrorCommand(char *command)
{
    if (!command || strncmp(command, "@TMC ", 5) != 0)
        return;

    char *payload = command + 5;
    while (*payload == ' ')
        ++payload;

    if (strncmp(payload, "CAPS", 4) == 0) {
        Serial.printf("@TMA CAPS TMF3 ACK1 SAFE-NAV1 RECONNECT1\n");
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

    char *keyEnd = key + strlen(key);
    while (keyEnd > key && keyEnd[-1] == ' ')
        *--keyEnd = '\0';

    input_broker_event eventType;
    MirrorInputClass inputClass;
    if (!resolveMirrorKey(key, eventType, inputClass)) {
        if (hasRequestId)
            emitMirrorAck(requestId, "ERR");
        return;
    }

    queueMirrorInput(requestId, hasRequestId, eventType, inputClass);
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
            if (!discardUntilNewline) {
                commandBuffer[commandLength] = '\0';
                handleMirrorCommand(commandBuffer);
            }
            commandLength = 0;
            discardUntilNewline = false;
            continue;
        }

        if (discardUntilNewline)
            continue;

        if (commandLength + 1 < COMMAND_BUFFER_SIZE) {
            commandBuffer[commandLength++] = character;
        } else {
            commandLength = 0;
            discardUntilNewline = true;
        }
    }
}
} // namespace

TacticalDisplayMirrorThread::TacticalDisplayMirrorThread() : concurrency::OSThread("display-mirror", 5) {}

int32_t TacticalDisplayMirrorThread::runOnce()
{
    readMirrorCommands();
    processPendingMirrorInput();

    if (screen != nullptr && screen->isScreenOn())
        mirrorDisplayFrame(screen->getDisplayDevice());
    return 5;
}
} // namespace graphics

#endif
