#pragma once

#include <cstddef>
#include <cstdint>

struct JarnsenLiveFrameInfo {
    uint8_t width = 0;
    uint8_t height = 0;
    uint16_t sequence = 0;
    bool screenOn = false;
};

void jarnsenLiveSetActive(bool active);
bool jarnsenLiveIsActive();
bool jarnsenLiveHandleCommand(const char *command);
void jarnsenLiveRequestRender();
size_t jarnsenLiveCapture(uint8_t *buffer, size_t capacity, JarnsenLiveFrameInfo &info);
