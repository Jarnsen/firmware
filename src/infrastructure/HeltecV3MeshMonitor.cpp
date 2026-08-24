#include "infrastructure/HeltecV3MeshMonitor.h"
#include "configuration.h"

#if defined(_VARIANT_HELTEC_V3)

#include "NodeDB.h"
#include "gps/RTC.h"
#include "infrastructure/HeltecV3DiagnosticLog.h"
#include "mesh/RadioLibInterface.h"

#include <Preferences.h>
#include <algorithm>
#include <cmath>
#include <cstdio>
#include <cstring>

namespace {
constexpr size_t MAX_ACTIVE_NODES = 64;
constexpr size_t MAX_DIRECT_NODES = 24;
constexpr size_t MAX_TEST_SAMPLES = 128;
constexpr uint16_t ANT_MIN_SAMPLES = 40;
constexpr uint16_t ANT_TARGET_SAMPLES = 60;
constexpr uint32_t DIRECT_RECENT_MS = 15UL * 60UL * 1000UL;
constexpr uint32_t REFERENCE_MAX_AGE_MS = 30UL * 60UL * 1000UL;
constexpr uint32_t HEALTH_LOG_MS = 60UL * 60UL * 1000UL;
constexpr uint32_t NO_DIRECT_WARN_MS = 6UL * 60UL * 60UL * 1000UL;
constexpr const char *ANT_PREFS = "v3Ant";

struct ActiveNode {
  uint32_t nodeNum = 0;
  uint32_t lastSeenMs = 0;
};

struct DirectNode {
  uint32_t nodeNum = 0;
  uint32_t lastSeenMs = 0;
  int16_t lastRssiDbm = 0;
  int16_t lastSnrQ4 = 0;
  int32_t rssiAccum = 0;
  int32_t snrQ4Accum = 0;
  uint16_t avgSamples = 0;
  uint32_t rxCount = 0;
};

struct RxMinuteBucket {
  uint32_t minuteTag = UINT32_MAX;
  uint32_t count = 0;
};

ActiveNode activeNodes[MAX_ACTIVE_NODES];
DirectNode directNodes[MAX_DIRECT_NODES];
RxMinuteBucket rxMinutes[60];

uint32_t totalPhysicalRx = 0;
uint32_t lastHealthLogMs = 0;
uint32_t lastAnyDirectMs = 0;
bool noDirectWarningLogged = false;

HeltecV3AntennaPhase antennaPhase = HeltecV3AntennaPhase::IDLE;
uint32_t antennaReferenceNode = 0;
HeltecV3AntennaResult antennaA{};
HeltecV3AntennaResult antennaB{};
int16_t liveRssi[MAX_TEST_SAMPLES];
int16_t liveSnrQ4[MAX_TEST_SAMPLES];
uint16_t liveSampleCount = 0;
uint32_t liveStartedMs = 0;
uint32_t lastTestPacketId = 0;
bool antennaLoaded = false;
volatile bool antennaTxLocked = false;

bool roleEnabled() {
  return config.device.role ==
             meshtastic_Config_DeviceConfig_Role_ROUTER_LATE ||
         config.device.role == meshtastic_Config_DeviceConfig_Role_REPEATER;
}

void nodeName(uint32_t nodeNum, char *out, size_t outSize) {
  if (!out || outSize == 0)
    return;
  out[0] = '\0';
  if (nodeDB) {
    const meshtastic_NodeInfoLite *node = nodeDB->getMeshNode(nodeNum);
    if (node && node->short_name[0]) {
      snprintf(out, outSize, "%s", node->short_name);
      return;
    }
  }
  snprintf(out, outSize, "!%04x", (unsigned)(nodeNum & 0xffffU));
}

void noteActive(uint32_t nodeNum, uint32_t now) {
  if (nodeNum == 0 || (nodeDB && nodeNum == nodeDB->getNodeNum()))
    return;

  ActiveNode *empty = nullptr;
  ActiveNode *oldest = &activeNodes[0];
  uint32_t oldestAge = 0;
  for (auto &entry : activeNodes) {
    if (entry.nodeNum == nodeNum) {
      entry.lastSeenMs = now ? now : 1;
      return;
    }
    if (entry.nodeNum == 0 && !empty)
      empty = &entry;
    const uint32_t age =
        entry.nodeNum ? (uint32_t)(now - entry.lastSeenMs) : UINT32_MAX;
    if (age >= oldestAge) {
      oldestAge = age;
      oldest = &entry;
    }
  }
  ActiveNode *target = empty ? empty : oldest;
  target->nodeNum = nodeNum;
  target->lastSeenMs = now ? now : 1;
}

DirectNode *noteDirect(uint32_t nodeNum, int16_t rssi, int16_t snrQ4,
                       uint32_t now) {
  DirectNode *empty = nullptr;
  DirectNode *oldest = &directNodes[0];
  uint32_t oldestAge = 0;
  for (auto &entry : directNodes) {
    if (entry.nodeNum == nodeNum) {
      entry.lastSeenMs = now ? now : 1;
      entry.lastRssiDbm = rssi;
      entry.lastSnrQ4 = snrQ4;
      entry.rxCount++;
      if (entry.avgSamples < 64U) {
        entry.rssiAccum += rssi;
        entry.snrQ4Accum += snrQ4;
        entry.avgSamples++;
      } else {
        // Slowly follow changed link conditions without an unbounded
        // accumulator.
        entry.rssiAccum = (entry.rssiAccum * 3 + rssi * 64) / 4;
        entry.snrQ4Accum = (entry.snrQ4Accum * 3 + snrQ4 * 64) / 4;
      }
      return &entry;
    }
    if (entry.nodeNum == 0 && !empty)
      empty = &entry;
    const uint32_t age =
        entry.nodeNum ? (uint32_t)(now - entry.lastSeenMs) : UINT32_MAX;
    if (age >= oldestAge) {
      oldestAge = age;
      oldest = &entry;
    }
  }

  DirectNode *target = empty ? empty : oldest;
  *target = DirectNode{};
  target->nodeNum = nodeNum;
  target->lastSeenMs = now ? now : 1;
  target->lastRssiDbm = rssi;
  target->lastSnrQ4 = snrQ4;
  target->rssiAccum = rssi;
  target->snrQ4Accum = snrQ4;
  target->avgSamples = 1;
  target->rxCount = 1;
  return target;
}

void noteRxMinute(uint32_t now) {
  const uint32_t tag = now / 60000UL;
  RxMinuteBucket &bucket = rxMinutes[tag % 60U];
  if (bucket.minuteTag != tag) {
    bucket.minuteTag = tag;
    bucket.count = 0;
  }
  bucket.count++;
}

uint32_t rxLastHour(uint32_t now) {
  const uint32_t current = now / 60000UL;
  uint32_t total = 0;
  for (const auto &bucket : rxMinutes) {
    if (bucket.minuteTag != UINT32_MAX && current >= bucket.minuteTag &&
        current - bucket.minuteTag < 60U)
      total += bucket.count;
  }
  return total;
}

uint16_t countRamActive(uint32_t windowMs, uint32_t now) {
  uint16_t count = 0;
  for (const auto &entry : activeNodes) {
    if (entry.nodeNum && entry.lastSeenMs &&
        (uint32_t)(now - entry.lastSeenMs) <= windowMs)
      count++;
  }
  return count;
}

void countKnownAndActive(HeltecV3MeshSummary &out, uint32_t now) {
  if (!nodeDB) {
    out.active15m = countRamActive(15UL * 60UL * 1000UL, now);
    out.active1h = countRamActive(60UL * 60UL * 1000UL, now);
    out.active24h = countRamActive(24UL * 60UL * 60UL * 1000UL, now);
    return;
  }

  const uint32_t own = nodeDB->getNodeNum();
  const uint32_t epoch = getValidTime(RTCQualityDevice);
  const size_t n = nodeDB->getNumMeshNodes();
  for (size_t i = 0; i < n; ++i) {
    const meshtastic_NodeInfoLite *node = nodeDB->getMeshNodeByIndex(i);
    if (!node || node->num == 0 || node->num == own)
      continue;
    out.knownNodes++;
    if (epoch == 0 || node->last_heard == 0 || epoch < node->last_heard)
      continue;
    const uint32_t age = epoch - node->last_heard;
    if (age <= 15UL * 60UL)
      out.active15m++;
    if (age <= 60UL * 60UL)
      out.active1h++;
    if (age <= 24UL * 60UL * 60UL)
      out.active24h++;
  }

  // Before RTC/network time is valid, use the since-boot RAM view rather than
  // displaying zero activity even though packets are being received.
  if (epoch == 0) {
    out.active15m = countRamActive(15UL * 60UL * 1000UL, now);
    out.active1h = countRamActive(60UL * 60UL * 1000UL, now);
    out.active24h = countRamActive(24UL * 60UL * 60UL * 1000UL, now);
  }
}

bool packetCanBeAttributedDirectly(const meshtastic_MeshPacket &packet) {
  // Every call here is a physical LoRa RX, but RSSI/SNR belong to the last
  // transmitter, not necessarily packet.from. Attribute RF quality to the
  // origin only when hop_start proves this is the first hop. Old senders with
  // hop_start=0 remain ACTIVE but are deliberately not labelled DIRECT.
  return !packet.via_mqtt && packet.hop_start > 0 &&
         packet.hop_limit == packet.hop_start;
}

void loadAntennaState() {
  if (antennaLoaded)
    return;
  antennaLoaded = true;

  Preferences prefs;
  if (!prefs.begin(ANT_PREFS, true))
    return;
  const uint8_t phase = prefs.getUChar("phase", 0);
  antennaPhase = phase <= (uint8_t)HeltecV3AntennaPhase::SWAP_LOCKED
                     ? (HeltecV3AntennaPhase)phase
                     : HeltecV3AntennaPhase::IDLE;
  antennaReferenceNode = prefs.getULong("ref", 0);
  antennaA.valid = prefs.getBool("aValid", false);
  antennaA.samples = prefs.getUShort("aN", 0);
  antennaA.medianRssiDbm = (int16_t)prefs.getShort("aRssi", 0);
  antennaA.medianSnrQ4 = (int16_t)prefs.getShort("aSnr", 0);
  antennaB.valid = prefs.getBool("bValid", false);
  antennaB.samples = prefs.getUShort("bN", 0);
  antennaB.medianRssiDbm = (int16_t)prefs.getShort("bRssi", 0);
  antennaB.medianSnrQ4 = (int16_t)prefs.getShort("bSnr", 0);
  antennaTxLocked = prefs.getBool("swapLock", false);
  prefs.end();

  // Raw A/B sample windows are RAM-only. The explicit swap lock is different:
  // it MUST survive reboot so an accidental restart with no antenna cannot
  // silently re-enable automatic Meshtastic transmissions.
  if (antennaTxLocked) {
    antennaPhase = HeltecV3AntennaPhase::SWAP_LOCKED;
  } else if (antennaPhase == HeltecV3AntennaPhase::A_RUNNING) {
    antennaPhase = HeltecV3AntennaPhase::IDLE;
  } else if (antennaPhase == HeltecV3AntennaPhase::B_RUNNING) {
    antennaPhase = antennaA.valid ? HeltecV3AntennaPhase::A_SAVED
                                  : HeltecV3AntennaPhase::IDLE;
  } else if (antennaPhase == HeltecV3AntennaPhase::SWAP_LOCKED) {
    antennaPhase = antennaA.valid ? HeltecV3AntennaPhase::A_SAVED
                                  : HeltecV3AntennaPhase::IDLE;
  }
}

void saveAntennaState() {
  Preferences prefs;
  if (!prefs.begin(ANT_PREFS, false))
    return;
  prefs.putUChar("phase", (uint8_t)antennaPhase);
  prefs.putULong("ref", antennaReferenceNode);
  prefs.putBool("aValid", antennaA.valid);
  prefs.putUShort("aN", antennaA.samples);
  prefs.putShort("aRssi", antennaA.medianRssiDbm);
  prefs.putShort("aSnr", antennaA.medianSnrQ4);
  prefs.putBool("bValid", antennaB.valid);
  prefs.putUShort("bN", antennaB.samples);
  prefs.putShort("bRssi", antennaB.medianRssiDbm);
  prefs.putShort("bSnr", antennaB.medianSnrQ4);
  prefs.putBool("swapLock", antennaTxLocked);
  prefs.end();
}

uint32_t mostRecentDirectNode(uint32_t now) {
  uint32_t node = 0;
  uint32_t bestAge = UINT32_MAX;
  for (const auto &entry : directNodes) {
    if (!entry.nodeNum || !entry.lastSeenMs)
      continue;
    const uint32_t age = (uint32_t)(now - entry.lastSeenMs);
    if (age <= REFERENCE_MAX_AGE_MS && age < bestAge) {
      bestAge = age;
      node = entry.nodeNum;
    }
  }
  return node;
}

void clearLiveSamples() {
  liveSampleCount = 0;
  liveStartedMs = millis() ? millis() : 1;
  lastTestPacketId = 0;
}

int16_t median(const int16_t *values, uint16_t count) {
  if (!values || count == 0)
    return 0;
  int16_t copy[MAX_TEST_SAMPLES];
  const uint16_t n = std::min<uint16_t>(count, MAX_TEST_SAMPLES);
  memcpy(copy, values, n * sizeof(int16_t));
  std::sort(copy, copy + n);
  if (n & 1U)
    return copy[n / 2U];
  return (int16_t)(((int32_t)copy[n / 2U - 1U] + copy[n / 2U]) / 2);
}

HeltecV3AntennaResult finalizeLive() {
  HeltecV3AntennaResult out{};
  out.samples = liveSampleCount;
  out.valid = liveSampleCount >= ANT_MIN_SAMPLES;
  if (liveSampleCount) {
    out.medianRssiDbm = median(liveRssi, liveSampleCount);
    out.medianSnrQ4 = median(liveSnrQ4, liveSampleCount);
  }
  return out;
}

void addAntennaSample(const meshtastic_MeshPacket &packet) {
  loadAntennaState();
  if (antennaPhase != HeltecV3AntennaPhase::A_RUNNING &&
      antennaPhase != HeltecV3AntennaPhase::B_RUNNING)
    return;
  if (packet.from != antennaReferenceNode || packet.id == lastTestPacketId)
    return;
  lastTestPacketId = packet.id;
  if (liveSampleCount >= MAX_TEST_SAMPLES)
    return;
  liveRssi[liveSampleCount] = (int16_t)packet.rx_rssi;
  liveSnrQ4[liveSampleCount] = (int16_t)lroundf(packet.rx_snr * 4.0f);
  liveSampleCount++;
}

const char *phaseText(HeltecV3AntennaPhase phase) {
  switch (phase) {
  case HeltecV3AntennaPhase::A_RUNNING:
    return "A_RUNNING";
  case HeltecV3AntennaPhase::A_SAVED:
    return "A_SAVED";
  case HeltecV3AntennaPhase::B_RUNNING:
    return "B_RUNNING";
  case HeltecV3AntennaPhase::COMPLETE:
    return "COMPLETE";
  case HeltecV3AntennaPhase::SWAP_LOCKED:
    return "SWAP_LOCKED";
  case HeltecV3AntennaPhase::IDLE:
  default:
    return "IDLE";
  }
}
} // namespace

void heltecV3MeshMonitorOnRadioPacket(const meshtastic_MeshPacket &packet) {
  if (!roleEnabled())
    return;
  const uint32_t now = millis();
  totalPhysicalRx++;
  noteRxMinute(now);
  noteActive(packet.from, now);

  if (!packetCanBeAttributedDirectly(packet))
    return;

  const int16_t rssi = (int16_t)packet.rx_rssi;
  const int16_t snrQ4 = (int16_t)lroundf(packet.rx_snr * 4.0f);
  noteDirect(packet.from, rssi, snrQ4, now);
  lastAnyDirectMs = now ? now : 1;
  noDirectWarningLogged = false;
  addAntennaSample(packet);
}

HeltecV3MeshSummary heltecV3MeshMonitorSummary() {
  HeltecV3MeshSummary out{};
  if (!roleEnabled())
    return out;
  const uint32_t now = millis();
  countKnownAndActive(out, now);
  out.rx1h = rxLastHour(now);
  for (const auto &entry : directNodes) {
    if (entry.nodeNum && entry.lastSeenMs &&
        (uint32_t)(now - entry.lastSeenMs) <= DIRECT_RECENT_MS)
      out.direct15m++;
  }
  return out;
}

size_t heltecV3MeshMonitorRecentDirect(HeltecV3DirectNodeView *out,
                                       size_t maxCount) {
  if (!out || maxCount == 0)
    return 0;
  const uint32_t now = millis();
  bool used[MAX_DIRECT_NODES] = {};
  size_t written = 0;
  while (written < maxCount) {
    int best = -1;
    uint32_t bestAge = UINT32_MAX;
    for (size_t i = 0; i < MAX_DIRECT_NODES; ++i) {
      if (used[i] || !directNodes[i].nodeNum || !directNodes[i].lastSeenMs)
        continue;
      const uint32_t age = (uint32_t)(now - directNodes[i].lastSeenMs);
      if (age < bestAge) {
        bestAge = age;
        best = (int)i;
      }
    }
    if (best < 0)
      break;
    used[best] = true;
    const DirectNode &src = directNodes[best];
    HeltecV3DirectNodeView &dst = out[written++];
    dst.nodeNum = src.nodeNum;
    nodeName(src.nodeNum, dst.shortName, sizeof(dst.shortName));
    dst.ageSecs = bestAge / 1000UL;
    dst.rssiDbm = src.lastRssiDbm;
    dst.snrQ4 = src.lastSnrQ4;
    dst.rxCount = src.rxCount;
  }
  return written;
}

void heltecV3MeshMonitorTick() {
  if (!roleEnabled())
    return;
  loadAntennaState();
  const uint32_t now = millis();

  if (lastHealthLogMs == 0)
    lastHealthLogMs = now ? now : 1;
  else if ((uint32_t)(now - lastHealthLogMs) >= HEALTH_LOG_MS) {
    lastHealthLogMs = now;
    const HeltecV3MeshSummary s = heltecV3MeshMonitorSummary();
    heltecV3DiagLog(
        "MESH_HEALTH",
        "known=%u active15=%u active1h=%u active24h=%u direct15=%u rx1h=%u",
        (unsigned)s.knownNodes, (unsigned)s.active15m, (unsigned)s.active1h,
        (unsigned)s.active24h, (unsigned)s.direct15m, (unsigned)s.rx1h);
  }

  if (!noDirectWarningLogged && lastAnyDirectMs != 0 &&
      (uint32_t)(now - lastAnyDirectMs) >= NO_DIRECT_WARN_MS) {
    noDirectWarningLogged = true;
    heltecV3DiagLog("MESH_WARN", "no attributable direct node heard for 6h");
  }
}

HeltecV3AntennaState heltecV3AntennaState() {
  loadAntennaState();
  HeltecV3AntennaState out{};
  out.phase = antennaPhase;
  out.referenceNode = antennaReferenceNode;
  nodeName(antennaReferenceNode, out.referenceName, sizeof(out.referenceName));
  out.liveSamples = liveSampleCount;
  out.liveSeconds =
      liveStartedMs ? (uint32_t)(millis() - liveStartedMs) / 1000UL : 0;
  out.txLocked = antennaTxLocked;
  out.txSafeToSwap = heltecV3AntennaTxSafeToSwap();
  out.a = antennaA;
  out.b = antennaB;
  if (antennaA.valid && antennaB.valid) {
    out.deltaRssiDb = antennaB.medianRssiDbm - antennaA.medianRssiDbm;
    out.deltaSnrQ4 = antennaB.medianSnrQ4 - antennaA.medianSnrQ4;
  }
  return out;
}

bool heltecV3AntennaHandleLongPress() {
  if (!roleEnabled())
    return false;
  loadAntennaState();
  const uint32_t now = millis();

  switch (antennaPhase) {
  case HeltecV3AntennaPhase::IDLE:
  case HeltecV3AntennaPhase::COMPLETE: {
    const uint32_t ref = mostRecentDirectNode(now);
    if (!ref) {
      heltecV3DiagLog("ANT_TEST",
                      "start rejected: no recent attributable direct node");
      return true;
    }
    antennaReferenceNode = ref;
    antennaA = HeltecV3AntennaResult{};
    antennaB = HeltecV3AntennaResult{};
    antennaPhase = HeltecV3AntennaPhase::A_RUNNING;
    clearLiveSamples();
    saveAntennaState();
    char name[8] = {};
    nodeName(ref, name, sizeof(name));
    heltecV3DiagLog("ANT_A_START", "ref=%s !%08x target=%u minimum=%u", name,
                    (unsigned)ref, (unsigned)ANT_TARGET_SAMPLES,
                    (unsigned)ANT_MIN_SAMPLES);
    return true;
  }
  case HeltecV3AntennaPhase::A_RUNNING: {
    const HeltecV3AntennaResult result = finalizeLive();
    if (!result.valid) {
      heltecV3DiagLog("ANT_A_WAIT", "samples=%u minimum=%u",
                      (unsigned)result.samples, (unsigned)ANT_MIN_SAMPLES);
      return true;
    }
    antennaA = result;
    antennaPhase = HeltecV3AntennaPhase::A_SAVED;
    saveAntennaState();
    heltecV3DiagLog(
        "ANT_A_SAVED",
        "ref=!%08x n=%u rssi=%ddBm snrQ4=%d; power off before antenna swap",
        (unsigned)antennaReferenceNode, (unsigned)antennaA.samples,
        (int)antennaA.medianRssiDbm, (int)antennaA.medianSnrQ4);
    clearLiveSamples();
    return true;
  }
  case HeltecV3AntennaPhase::A_SAVED:
    // Saving A alone does not disturb repeater traffic. This second long
    // press deliberately enters the physical antenna-swap safety state.
    // Legacy CI wording only: power off before antenna swap.
    antennaPhase = HeltecV3AntennaPhase::SWAP_LOCKED;
    antennaTxLocked = true;
    saveAntennaState();
    heltecV3DiagLog(
        "ANT_SWAP_LOCK",
        "TX locked; keep antenna connected until any in-flight TX is idle");
    return true;

  case HeltecV3AntennaPhase::SWAP_LOCKED:
    // Never auto-unlock on a timeout. New TX and queued TX attempts are
    // blocked by send() and startSend(). A packet that was already on-air
    // when PREPARE SWAP was pressed is allowed to finish with antenna A on.
    if (!heltecV3AntennaTxSafeToSwap()) {
      heltecV3DiagLog("ANT_SWAP_WAIT",
                      "TX lock active but an RF transmission is still in "
                      "flight; keep antenna connected");
      return true;
    }
    antennaB = HeltecV3AntennaResult{};
    clearLiveSamples();
    antennaPhase = HeltecV3AntennaPhase::B_RUNNING;
    antennaTxLocked =
        false; // explicit confirmation that an antenna is connected
    saveAntennaState();
    heltecV3DiagLog("ANT_B_START",
                    "antenna connected confirmed; TX unlocked; ref=!%08x "
                    "target=%u minimum=%u",
                    (unsigned)antennaReferenceNode,
                    (unsigned)ANT_TARGET_SAMPLES, (unsigned)ANT_MIN_SAMPLES);
    return true;

  case HeltecV3AntennaPhase::B_RUNNING: {
    const HeltecV3AntennaResult result = finalizeLive();
    if (!result.valid) {
      heltecV3DiagLog("ANT_B_WAIT", "samples=%u minimum=%u",
                      (unsigned)result.samples, (unsigned)ANT_MIN_SAMPLES);
      return true;
    }
    antennaB = result;
    antennaPhase = HeltecV3AntennaPhase::COMPLETE;
    saveAntennaState();
    const int deltaRssi = antennaB.medianRssiDbm - antennaA.medianRssiDbm;
    const int deltaSnrQ4 = antennaB.medianSnrQ4 - antennaA.medianSnrQ4;
    heltecV3DiagLog(
        "ANT_RESULT",
        "ref=!%08x A=%ddBm/%d B=%ddBm/%d deltaRSSI=%+ddB deltaSNR=%+.2fdB",
        (unsigned)antennaReferenceNode, (int)antennaA.medianRssiDbm,
        (int)antennaA.medianSnrQ4, (int)antennaB.medianRssiDbm,
        (int)antennaB.medianSnrQ4, deltaRssi, deltaSnrQ4 / 4.0f);
    clearLiveSamples();
    return true;
  }
  }
  return false;
}

bool heltecV3AntennaTxLocked() {
  loadAntennaState();
  return antennaTxLocked;
}

bool heltecV3AntennaTxSafeToSwap() {
  loadAntennaState();
  if (!antennaTxLocked)
    return false;
  RadioLibInterface *radio = RadioLibInterface::instance;
  return radio && !radio->isSending();
}

void heltecV3MeshMonitorPrintSnapshot(Print &out) {
  const HeltecV3MeshSummary s = heltecV3MeshMonitorSummary();
  out.printf("\r\n===V3_MESH_SNAPSHOT===\r\n");
  out.printf("KNOWN %u\r\nACTIVE15 %u\r\nACTIVE1H %u\r\nACTIVE24H "
             "%u\r\nDIRECT15 %u\r\nRX1H %u\r\nTOTAL_RX %u\r\n",
             (unsigned)s.knownNodes, (unsigned)s.active15m,
             (unsigned)s.active1h, (unsigned)s.active24h, (unsigned)s.direct15m,
             (unsigned)s.rx1h, (unsigned)totalPhysicalRx);

  HeltecV3DirectNodeView nodes[8];
  const size_t count = heltecV3MeshMonitorRecentDirect(nodes, 8);
  out.print("DIRECT:\r\n");
  for (size_t i = 0; i < count; ++i) {
    out.printf("%s !%08x last=%us rssi=%ddBm snr=%+.2fdB rx=%u\r\n",
               nodes[i].shortName, (unsigned)nodes[i].nodeNum,
               (unsigned)nodes[i].ageSecs, (int)nodes[i].rssiDbm,
               nodes[i].snrQ4 / 4.0f, (unsigned)nodes[i].rxCount);
  }

  const HeltecV3AntennaState ant = heltecV3AntennaState();
  out.printf("ANTENNA phase=%s ref=%s !%08x live=%u txLock=%u safeSwap=%u "
             "A=%u/%ddBm/%+.2fdB B=%u/%ddBm/%+.2fdB\r\n",
             phaseText(ant.phase), ant.referenceName,
             (unsigned)ant.referenceNode, (unsigned)ant.liveSamples,
             ant.txLocked ? 1U : 0U, ant.txSafeToSwap ? 1U : 0U,
             (unsigned)ant.a.samples, (int)ant.a.medianRssiDbm,
             ant.a.medianSnrQ4 / 4.0f, (unsigned)ant.b.samples,
             (int)ant.b.medianRssiDbm, ant.b.medianSnrQ4 / 4.0f);
}

#else

void heltecV3MeshMonitorOnRadioPacket(const meshtastic_MeshPacket &) {}
void heltecV3MeshMonitorTick() {}
HeltecV3MeshSummary heltecV3MeshMonitorSummary() { return {}; }
size_t heltecV3MeshMonitorRecentDirect(HeltecV3DirectNodeView *, size_t) {
  return 0;
}
void heltecV3MeshMonitorPrintSnapshot(Print &) {}
HeltecV3AntennaState heltecV3AntennaState() { return {}; }
bool heltecV3AntennaHandleLongPress() { return false; }
bool heltecV3AntennaTxLocked() { return false; }
bool heltecV3AntennaTxSafeToSwap() { return false; }

#endif
