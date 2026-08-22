#include "configuration.h"
#include "infrastructure/HeltecV3MeshPages.h"

#if defined(_VARIANT_HELTEC_V3) && HAS_SCREEN

#include "graphics/Screen.h"
#include "graphics/ScreenFonts.h"
#include "infrastructure/HeltecV3MeshMonitor.h"

#include <Arduino.h>
#include <cmath>
#include <cstdio>
#include <cstring>

namespace
{
volatile uint32_t lastMeshHealthDrawMs = 0;
volatile uint32_t lastAntennaDrawMs = 0;

bool roleEnabled()
{
    return config.device.role == meshtastic_Config_DeviceConfig_Role_ROUTER_LATE ||
           config.device.role == meshtastic_Config_DeviceConfig_Role_REPEATER;
}

void drawLine(OLEDDisplay *display, int16_t x, int16_t y, const char *text)
{
    display->setTextAlignment(TEXT_ALIGN_CENTER);
    display->setFont(FONT_SMALL);
    display->drawString(display->getWidth() / 2 + x, y, text ? text : "");
}

void formatAge(uint32_t ageSecs, char *out, size_t outSize)
{
    if (ageSecs == UINT32_MAX)
        snprintf(out, outSize, "--");
    else if (ageSecs < 60U)
        snprintf(out, outSize, "%us", (unsigned)ageSecs);
    else if (ageSecs < 3600U)
        snprintf(out, outSize, "%um", (unsigned)(ageSecs / 60U));
    else
        snprintf(out, outSize, "%uh", (unsigned)(ageSecs / 3600U));
}

bool findReferenceRadio(uint32_t nodeNum, HeltecV3DirectNodeView &out)
{
    HeltecV3DirectNodeView nodes[12];
    const size_t count = heltecV3MeshMonitorRecentDirect(nodes, 12);
    for (size_t i = 0; i < count; ++i) {
        if (nodes[i].nodeNum == nodeNum) {
            out = nodes[i];
            return true;
        }
    }
    return false;
}

const char *comparisonText(int deltaDb)
{
    if (deltaDb >= 3)
        return "B DEUTLICH BESSER";
    if (deltaDb <= -3)
        return "A DEUTLICH BESSER";
    if (deltaDb >= 1)
        return "B LEICHT BESSER";
    if (deltaDb <= -1)
        return "A LEICHT BESSER";
    return "PRAKTISCH GLEICH";
}
} // namespace

bool heltecV3MeshHealthPageEnabled()
{
    return roleEnabled();
}

bool heltecV3AntennaPageEnabled()
{
    return roleEnabled();
}

void heltecV3MeshHealthPageDrawFrame(OLEDDisplay *display, OLEDDisplayUiState *, int16_t x, int16_t y)
{
    if (!display || !roleEnabled())
        return;
    lastMeshHealthDrawMs = millis() ? millis() : 1;

    const HeltecV3MeshSummary s = heltecV3MeshMonitorSummary();
    HeltecV3DirectNodeView nodes[2];
    const size_t count = heltecV3MeshMonitorRecentDirect(nodes, 2);
    char line[72] = {};

    display->setTextAlignment(TEXT_ALIGN_CENTER);
    display->setFont(FONT_MEDIUM);
    display->drawString(display->getWidth() / 2 + x, 0 + y, "MESH HEALTH");

    snprintf(line, sizeof(line), "KNOWN:%u  A15:%u  A1H:%u", (unsigned)s.knownNodes, (unsigned)s.active15m,
             (unsigned)s.active1h);
    drawLine(display, x, 17 + y, line);
    snprintf(line, sizeof(line), "A24:%u DIRECT15:%u RX1H:%u", (unsigned)s.active24h, (unsigned)s.direct15m,
             (unsigned)s.rx1h);
    drawLine(display, x, 28 + y, line);

    for (size_t i = 0; i < 2; ++i) {
        if (i < count) {
            char age[12] = {};
            formatAge(nodes[i].ageSecs, age, sizeof(age));
            snprintf(line, sizeof(line), "%s %s %ddBm %+.1fdB", nodes[i].shortName, age, (int)nodes[i].rssiDbm,
                     nodes[i].snrQ4 / 4.0f);
        } else {
            snprintf(line, sizeof(line), "%s", i == 0 ? "NO DIRECT NODE YET" : "");
        }
        drawLine(display, x, (int16_t)(40 + i * 11) + y, line);
    }
}

void heltecV3AntennaPageDrawFrame(OLEDDisplay *display, OLEDDisplayUiState *, int16_t x, int16_t y)
{
    if (!display || !roleEnabled())
        return;
    lastAntennaDrawMs = millis() ? millis() : 1;

    const HeltecV3AntennaState a = heltecV3AntennaState();
    char line[72] = {};
    display->setTextAlignment(TEXT_ALIGN_CENTER);
    display->setFont(FONT_MEDIUM);
    display->drawString(display->getWidth() / 2 + x, 0 + y, "ANTENNA TEST");

    if (a.phase == HeltecV3AntennaPhase::IDLE) {
        drawLine(display, x, 18 + y, "PASSIVER RX A/B VERGLEICH");
        drawLine(display, x, 30 + y, "REF = LETZTER DIRECT NODE");
        drawLine(display, x, 42 + y, "MIN 40  ZIEL 60 SAMPLES");
        drawLine(display, x, 54 + y, "HOLD: START A");
        return;
    }

    snprintf(line, sizeof(line), "REF %s !%04x", a.referenceName, (unsigned)(a.referenceNode & 0xffffU));
    drawLine(display, x, 16 + y, line);

    HeltecV3DirectNodeView radio{};
    const bool haveRadio = findReferenceRadio(a.referenceNode, radio);

    if (a.phase == HeltecV3AntennaPhase::A_RUNNING || a.phase == HeltecV3AntennaPhase::B_RUNNING) {
        const char which = a.phase == HeltecV3AntennaPhase::A_RUNNING ? 'A' : 'B';
        snprintf(line, sizeof(line), "%c RUN  %u/60  %us", which, (unsigned)a.liveSamples, (unsigned)a.liveSeconds);
        drawLine(display, x, 28 + y, line);
        if (haveRadio)
            snprintf(line, sizeof(line), "LIVE %ddBm  %+.1fdB", (int)radio.rssiDbm, radio.snrQ4 / 4.0f);
        else
            snprintf(line, sizeof(line), "WARTE AUF DIRECT REF");
        drawLine(display, x, 40 + y, line);
        snprintf(line, sizeof(line), "HOLD: SAVE %c", which);
        drawLine(display, x, 53 + y, line);
        return;
    }

    if (a.phase == HeltecV3AntennaPhase::A_SAVED) {
        snprintf(line, sizeof(line), "A %ddBm %+.1fdB  n=%u", (int)a.a.medianRssiDbm, a.a.medianSnrQ4 / 4.0f,
                 (unsigned)a.a.samples);
        drawLine(display, x, 28 + y, line);
        drawLine(display, x, 40 + y, "POWER OFF TO CHANGE ANT");
        drawLine(display, x, 53 + y, "DANN HOLD: START B");
        return;
    }

    if (a.phase == HeltecV3AntennaPhase::COMPLETE) {
        snprintf(line, sizeof(line), "A %ddBm/%+.1f  B %ddBm/%+.1f", (int)a.a.medianRssiDbm, a.a.medianSnrQ4 / 4.0f,
                 (int)a.b.medianRssiDbm, a.b.medianSnrQ4 / 4.0f);
        drawLine(display, x, 28 + y, line);
        snprintf(line, sizeof(line), "RX DELTA B-A %+ddB", (int)a.deltaRssiDb);
        drawLine(display, x, 40 + y, line);
        drawLine(display, x, 51 + y, comparisonText(a.deltaRssiDb));
        drawLine(display, x, 61 + y, "HOLD: NEW TEST");
    }
}

bool heltecV3MeshHealthPageRecentlyVisible()
{
    const uint32_t last = lastMeshHealthDrawMs;
    return last != 0 && (uint32_t)(millis() - last) <= 1500UL;
}

bool heltecV3AntennaPageRecentlyVisible()
{
    const uint32_t last = lastAntennaDrawMs;
    return last != 0 && (uint32_t)(millis() - last) <= 1500UL;
}

void heltecV3MeshPagesRefresh()
{
    if (screen && screen->isScreenOn())
        screen->runNow();
}

#else

bool heltecV3MeshHealthPageEnabled() { return false; }
bool heltecV3AntennaPageEnabled() { return false; }
bool heltecV3MeshHealthPageRecentlyVisible() { return false; }
bool heltecV3AntennaPageRecentlyVisible() { return false; }
void heltecV3MeshPagesRefresh() {}

#endif
