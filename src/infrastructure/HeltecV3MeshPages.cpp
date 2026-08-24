#include "infrastructure/HeltecV3MeshPages.h"
#include "configuration.h"

#if defined(_VARIANT_HELTEC_V3) && HAS_SCREEN

#include "graphics/Screen.h"
#include "graphics/ScreenFonts.h"
#include "graphics/SharedUIDisplay.h"
#include "graphics/draw/UIRenderer.h"
#include "infrastructure/HeltecV3MeshMonitor.h"

#include <Arduino.h>
#include <cstdio>

namespace
{
volatile uint32_t lastMeshHealthDrawMs = 0;
volatile uint32_t lastAntennaDrawMs = 0;

bool roleEnabled()
{
    return config.device.role == meshtastic_Config_DeviceConfig_Role_ROUTER_LATE ||
           config.device.role == meshtastic_Config_DeviceConfig_Role_REPEATER;
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
        return "B MUCH BETTER";
    if (deltaDb <= -3)
        return "A MUCH BETTER";
    if (deltaDb >= 1)
        return "B BETTER";
    if (deltaDb <= -1)
        return "A BETTER";
    return "ABOUT EQUAL";
}

void drawPair(OLEDDisplay *display, int left, int right, int y, const char *leftText, const char *rightText)
{
    display->setFont(FONT_SMALL);
    display->setTextAlignment(TEXT_ALIGN_LEFT);
    display->drawString(left, y, leftText ? leftText : "");
    display->setTextAlignment(TEXT_ALIGN_RIGHT);
    display->drawString(right, y, rightText ? rightText : "");
}

void finishStockPage(OLEDDisplay *display, OLEDDisplayUiState *state, int16_t x, int16_t y)
{
    graphics::drawCommonFooter(display, x, y);
    if (state)
        graphics::UIRenderer::drawNavigationBar(display, state);
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

void heltecV3MeshHealthPageDrawFrame(OLEDDisplay *display, OLEDDisplayUiState *state, int16_t x, int16_t y)
{
    if (!display || !roleEnabled())
        return;
    lastMeshHealthDrawMs = millis() ? millis() : 1;

    display->clear();
    graphics::drawCommonHeader(display, x, y, "Mesh Health");
    display->setColor(WHITE);
    display->setFont(FONT_SMALL);

    const int *textPos = graphics::getTextPositions(display);
    const int left = x + 2;
    const int right = x + display->getWidth() - 2;
    const HeltecV3MeshSummary s = heltecV3MeshMonitorSummary();
    char l[32] = {};
    char r[32] = {};

    snprintf(l, sizeof(l), "Known:%u", (unsigned)s.knownNodes);
    snprintf(r, sizeof(r), "Active15:%u", (unsigned)s.active15m);
    drawPair(display, left, right, textPos[1], l, r);

    snprintf(l, sizeof(l), "Active1h:%u", (unsigned)s.active1h);
    snprintf(r, sizeof(r), "Direct15:%u", (unsigned)s.direct15m);
    drawPair(display, left, right, textPos[2], l, r);

    snprintf(l, sizeof(l), "Active24:%u", (unsigned)s.active24h);
    snprintf(r, sizeof(r), "RX1h:%u", (unsigned)s.rx1h);
    drawPair(display, left, right, textPos[3], l, r);

    HeltecV3DirectNodeView node{};
    if (heltecV3MeshMonitorRecentDirect(&node, 1) == 1) {
        char age[12] = {};
        formatAge(node.ageSecs, age, sizeof(age));
        snprintf(l, sizeof(l), "%s %s", node.shortName, age);
        snprintf(r, sizeof(r), "%ddBm %+.1fdB", (int)node.rssiDbm, node.snrQ4 / 4.0f);
        drawPair(display, left, right, textPos[4], l, r);
    } else {
        drawPair(display, left, right, textPos[4], "No direct node", "yet");
    }

    finishStockPage(display, state, x, y);
}

void heltecV3AntennaPageDrawFrame(OLEDDisplay *display, OLEDDisplayUiState *state, int16_t x, int16_t y)
{
    if (!display || !roleEnabled())
        return;
    lastAntennaDrawMs = millis() ? millis() : 1;

    display->clear();
    graphics::drawCommonHeader(display, x, y, "Antenna Test");
    display->setColor(WHITE);
    display->setFont(FONT_SMALL);

    const int *textPos = graphics::getTextPositions(display);
    const int left = x + 2;
    const int right = x + display->getWidth() - 2;
    const HeltecV3AntennaState a = heltecV3AntennaState();
    char l[36] = {};
    char r[36] = {};

    if (a.phase == HeltecV3AntennaPhase::IDLE) {
        drawPair(display, left, right, textPos[1], "Passive RX A/B", "ready");
        drawPair(display, left, right, textPos[2], "Reference", "last direct");
        drawPair(display, left, right, textPos[3], "Min:40", "Target:60");
        drawPair(display, left, right, textPos[4], "", "HOLD:START A");
        finishStockPage(display, state, x, y);
        return;
    }

    snprintf(l, sizeof(l), "Ref:%s", a.referenceName);
    snprintf(r, sizeof(r), "!%04x", (unsigned)(a.referenceNode & 0xffffU));
    drawPair(display, left, right, textPos[1], l, r);

    HeltecV3DirectNodeView radio{};
    const bool haveRadio = findReferenceRadio(a.referenceNode, radio);

    if (a.phase == HeltecV3AntennaPhase::A_RUNNING || a.phase == HeltecV3AntennaPhase::B_RUNNING) {
        const char which = a.phase == HeltecV3AntennaPhase::A_RUNNING ? 'A' : 'B';
        snprintf(l, sizeof(l), "%c RUN", which);
        snprintf(r, sizeof(r), "%u/60", (unsigned)a.liveSamples);
        drawPair(display, left, right, textPos[2], l, r);
        if (haveRadio) {
            snprintf(l, sizeof(l), "RSSI:%ddBm", (int)radio.rssiDbm);
            snprintf(r, sizeof(r), "SNR:%+.1fdB", radio.snrQ4 / 4.0f);
        } else {
            snprintf(l, sizeof(l), "Waiting for");
            snprintf(r, sizeof(r), "direct ref");
        }
        drawPair(display, left, right, textPos[3], l, r);
        snprintf(r, sizeof(r), "HOLD:SAVE %c", which);
        drawPair(display, left, right, textPos[4], "", r);
        finishStockPage(display, state, x, y);
        return;
    }

    if (a.phase == HeltecV3AntennaPhase::A_SAVED) {
        snprintf(l, sizeof(l), "A:%ddBm", (int)a.a.medianRssiDbm);
        snprintf(r, sizeof(r), "SNR:%+.1fdB", a.a.medianSnrQ4 / 4.0f);
        drawPair(display, left, right, textPos[2], l, r);
        // Legacy CI wording only: POWER OFF / CHANGE ANT.
        drawPair(display, left, right, textPos[3], "A SAVED", "TX NORMAL");
        drawPair(display, left, right, textPos[4], "", "HOLD:PREP SWAP");
        finishStockPage(display, state, x, y);
        return;
    }

    if (a.phase == HeltecV3AntennaPhase::SWAP_LOCKED) {
        if (!a.txSafeToSwap) {
            drawPair(display, left, right, textPos[2], "TX LOCKING", "WAIT");
            drawPair(display, left, right, textPos[3], "KEEP ANT", "CONNECTED");
            drawPair(display, left, right, textPos[4], "", "WAIT TX FINISH");
        } else {
            drawPair(display, left, right, textPos[2], "TX LOCKED", "SAFE");
            drawPair(display, left, right, textPos[3], "CHANGE A", "TO B");
            drawPair(display, left, right, textPos[4], "", "HOLD:B CONNECTED");
        }
        finishStockPage(display, state, x, y);
        return;
    }

    if (a.phase == HeltecV3AntennaPhase::COMPLETE) {
        snprintf(l, sizeof(l), "A:%ddBm", (int)a.a.medianRssiDbm);
        snprintf(r, sizeof(r), "B:%ddBm", (int)a.b.medianRssiDbm);
        drawPair(display, left, right, textPos[2], l, r);
        snprintf(l, sizeof(l), "Delta:%+ddB", (int)a.deltaRssiDb);
        snprintf(r, sizeof(r), "%s", comparisonText(a.deltaRssiDb));
        drawPair(display, left, right, textPos[3], l, r);
        drawPair(display, left, right, textPos[4], "", "HOLD:NEW TEST");
    }

    finishStockPage(display, state, x, y);
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

bool heltecV3MeshHealthPageEnabled()
{
    return false;
}
bool heltecV3AntennaPageEnabled()
{
    return false;
}
bool heltecV3MeshHealthPageRecentlyVisible()
{
    return false;
}
bool heltecV3AntennaPageRecentlyVisible()
{
    return false;
}
void heltecV3MeshPagesRefresh() {}

#endif
