#pragma once

#include "mesh/generated/meshtastic/mesh.pb.h"

#include <Arduino.h>
#include <cstddef>
#include <cstdint>

struct HeltecV3MeshSummary {
  uint16_t knownNodes = 0;
  uint16_t active15m = 0;
  uint16_t active1h = 0;
  uint16_t active24h = 0;
  uint16_t direct15m = 0;
  uint32_t rx1h = 0;
};

struct HeltecV3DirectNodeView {
  uint32_t nodeNum = 0;
  char shortName[8] = {};
  uint32_t ageSecs = UINT32_MAX;
  int16_t rssiDbm = 0;
  int16_t snrQ4 = 0;
  uint32_t rxCount = 0;
};

enum class HeltecV3AntennaPhase : uint8_t {
  IDLE = 0,
  A_RUNNING = 1,
  A_SAVED = 2,
  B_RUNNING = 3,
  COMPLETE = 4,
  SWAP_LOCKED = 5,
};

struct HeltecV3AntennaResult {
  bool valid = false;
  uint16_t samples = 0;
  int16_t medianRssiDbm = 0;
  int16_t medianSnrQ4 = 0;
};

struct HeltecV3AntennaState {
  HeltecV3AntennaPhase phase = HeltecV3AntennaPhase::IDLE;
  uint32_t referenceNode = 0;
  char referenceName[8] = {};
  uint16_t liveSamples = 0;
  uint32_t liveSeconds = 0;
  bool txLocked = false;
  bool txSafeToSwap = false;
  HeltecV3AntennaResult a;
  HeltecV3AntennaResult b;
  int16_t deltaRssiDb = 0;
  int16_t deltaSnrQ4 = 0;
};

// Called at the physical LoRa receive boundary after RSSI/SNR metadata has been
// attached. It never changes routing/rebroadcast behavior.
void heltecV3MeshMonitorOnRadioPacket(const meshtastic_MeshPacket &packet);
void heltecV3MeshMonitorTick();

HeltecV3MeshSummary heltecV3MeshMonitorSummary();
size_t heltecV3MeshMonitorRecentDirect(HeltecV3DirectNodeView *out,
                                       size_t maxCount);
void heltecV3MeshMonitorPrintSnapshot(Print &out);

HeltecV3AntennaState heltecV3AntennaState();
// One long-press action for the dedicated ANTENNA TEST page. Returns true when
// the action was consumed (including "need more samples" feedback state).
bool heltecV3AntennaHandleLongPress();

// Persistent safety lock used only during the deliberate A -> B antenna swap.
// RX/BLE/display/diagnostics continue; every new LoRa TX is blocked.
bool heltecV3AntennaTxLocked();
bool heltecV3AntennaTxSafeToSwap();
