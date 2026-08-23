#include "configuration.h"
#include "vehicle/TrackerAntennaTest.h"

#if defined(HELTEC_TRACKER_V1_1)

#include "NodeDB.h"
#include "mesh/RadioLibInterface.h"
#include "vehicle/TrackerDiagnosticLog.h"

#include <Preferences.h>
#include <algorithm>
#include <atomic>
#include <cmath>
#include <cstdio>
#include <cstring>

namespace
{
constexpr size_t MAX_DIRECT_NODES = 16;
constexpr size_t MAX_TEST_SAMPLES = 128;
constexpr uint16_t ANT_MIN_SAMPLES = 40;
constexpr uint16_t ANT_TARGET_SAMPLES = 60;
constexpr uint32_t REFERENCE_MAX_AGE_MS = 30UL * 60UL * 1000UL;
constexpr const char *ANT_PREFS = "trkAnt";

struct DirectNode {
    uint32_t nodeNum = 0;
    uint32_t lastSeenMs = 0;
    int16_t lastRssiDbm = 0;
    int16_t lastSnrQ4 = 0;
};

DirectNode directNodes[MAX_DIRECT_NODES];
TrackerAntennaPhase phase = TrackerAntennaPhase::IDLE;
uint32_t referenceNode = 0;
TrackerAntennaResult resultA{};
TrackerAntennaResult resultB{};
int16_t liveRssi[MAX_TEST_SAMPLES];
int16_t liveSnrQ4[MAX_TEST_SAMPLES];
uint16_t liveSampleCount = 0;
uint32_t liveStartedMs = 0;
uint32_t lastTestPacketId = 0;
std::atomic<bool> initialized{false};
// Fail-safe while TAK/TAK_TRACKER startup has not yet loaded NVS state.
std::atomic<bool> txLocked{true};

bool roleEnabled()
{
    return config.device.role == meshtastic_Config_DeviceConfig_Role_TAK ||
           config.device.role == meshtastic_Config_DeviceConfig_Role_TAK_TRACKER;
}

void nodeName(uint32_t nodeNum, char *out, size_t outSize)
{
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

bool packetDirect(const meshtastic_MeshPacket &packet)
{
    // RSSI/SNR belong to the physical last hop. Attribute them to packet.from
    // only when hop_start proves this packet is still on its first RF hop.
    return !packet.via_mqtt && packet.hop_start > 0 && packet.hop_limit == packet.hop_start;
}

void noteDirect(uint32_t nodeNum, int16_t rssi, int16_t snrQ4, uint32_t now)
{
    DirectNode *empty = nullptr;
    DirectNode *oldest = &directNodes[0];
    uint32_t oldestAge = 0;
    for (auto &entry : directNodes) {
        if (entry.nodeNum == nodeNum) {
            entry.lastSeenMs = now ? now : 1;
            entry.lastRssiDbm = rssi;
            entry.lastSnrQ4 = snrQ4;
            return;
        }
        if (entry.nodeNum == 0 && !empty)
            empty = &entry;
        const uint32_t age = entry.nodeNum ? (uint32_t)(now - entry.lastSeenMs) : UINT32_MAX;
        if (age >= oldestAge) {
            oldestAge = age;
            oldest = &entry;
        }
    }
    DirectNode *target = empty ? empty : oldest;
    target->nodeNum = nodeNum;
    target->lastSeenMs = now ? now : 1;
    target->lastRssiDbm = rssi;
    target->lastSnrQ4 = snrQ4;
}

uint32_t mostRecentDirect(uint32_t now)
{
    uint32_t bestNode = 0;
    uint32_t bestAge = UINT32_MAX;
    for (const auto &entry : directNodes) {
        if (!entry.nodeNum || !entry.lastSeenMs)
            continue;
        const uint32_t age = (uint32_t)(now - entry.lastSeenMs);
        if (age <= REFERENCE_MAX_AGE_MS && age < bestAge) {
            bestAge = age;
            bestNode = entry.nodeNum;
        }
    }
    return bestNode;
}

void clearLive()
{
    liveSampleCount = 0;
    liveStartedMs = millis() ? millis() : 1;
    lastTestPacketId = 0;
}

int16_t median(const int16_t *values, uint16_t count)
{
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

TrackerAntennaResult finalizeLive()
{
    TrackerAntennaResult out{};
    out.samples = liveSampleCount;
    out.valid = liveSampleCount >= ANT_MIN_SAMPLES;
    if (liveSampleCount) {
        out.medianRssiDbm = median(liveRssi, liveSampleCount);
        out.medianSnrQ4 = median(liveSnrQ4, liveSampleCount);
    }
    return out;
}

bool saveState()
{
    Preferences prefs;
    if (!prefs.begin(ANT_PREFS, false))
        return false;
    bool ok = true;
    ok &= prefs.putUChar("phase", (uint8_t)phase) > 0;
    ok &= prefs.putBool("swapLock", txLocked.load()) > 0;
    ok &= prefs.putULong("ref", referenceNode) > 0;
    ok &= prefs.putBool("aValid", resultA.valid) > 0;
    ok &= prefs.putUShort("aN", resultA.samples) > 0;
    ok &= prefs.putShort("aRssi", resultA.medianRssiDbm) > 0;
    ok &= prefs.putShort("aSnr", resultA.medianSnrQ4) > 0;
    ok &= prefs.putBool("bValid", resultB.valid) > 0;
    ok &= prefs.putUShort("bN", resultB.samples) > 0;
    ok &= prefs.putShort("bRssi", resultB.medianRssiDbm) > 0;
    ok &= prefs.putShort("bSnr", resultB.medianSnrQ4) > 0;
    prefs.end();
    return ok;
}

void addSample(const meshtastic_MeshPacket &packet)
{
    if (phase != TrackerAntennaPhase::A_RUNNING && phase != TrackerAntennaPhase::B_RUNNING)
        return;
    if (packet.from != referenceNode || packet.id == lastTestPacketId)
        return;
    lastTestPacketId = packet.id;
    if (liveSampleCount >= MAX_TEST_SAMPLES)
        return;
    liveRssi[liveSampleCount] = (int16_t)packet.rx_rssi;
    liveSnrQ4[liveSampleCount] = (int16_t)lroundf(packet.rx_snr * 4.0f);
    liveSampleCount++;
}
} // namespace

const char *trackerAntennaPhaseText(TrackerAntennaPhase value)
{
    switch (value) {
    case TrackerAntennaPhase::A_RUNNING: return "A RUNNING";
    case TrackerAntennaPhase::A_SAVED: return "A SAVED";
    case TrackerAntennaPhase::B_RUNNING: return "B RUNNING";
    case TrackerAntennaPhase::COMPLETE: return "COMPLETE";
    case TrackerAntennaPhase::SWAP_LOCKED: return "SWAP LOCKED";
    case TrackerAntennaPhase::IDLE:
    default: return "READY";
    }
}

void trackerAntennaTestInit()
{
    if (!roleEnabled()) {
        txLocked.store(false);
        initialized.store(true);
        return;
    }

    // Keep the fail-safe boot lock set until the entire persisted state has
    // been read successfully.
    Preferences prefs;
    if (!prefs.begin(ANT_PREFS, true)) {
        phase = TrackerAntennaPhase::SWAP_LOCKED;
        txLocked.store(true);
        initialized.store(true);
        trackerDiagLog("ANT_LOCK", "NVS read failed; fail-safe TX lock retained");
        return;
    }

    const uint8_t storedPhase = prefs.getUChar("phase", 0);
    phase = storedPhase <= (uint8_t)TrackerAntennaPhase::SWAP_LOCKED
                ? (TrackerAntennaPhase)storedPhase
                : TrackerAntennaPhase::IDLE;
    const bool storedLock = prefs.getBool("swapLock", false);
    referenceNode = prefs.getULong("ref", 0);
    resultA.valid = prefs.getBool("aValid", false);
    resultA.samples = prefs.getUShort("aN", 0);
    resultA.medianRssiDbm = (int16_t)prefs.getShort("aRssi", 0);
    resultA.medianSnrQ4 = (int16_t)prefs.getShort("aSnr", 0);
    resultB.valid = prefs.getBool("bValid", false);
    resultB.samples = prefs.getUShort("bN", 0);
    resultB.medianRssiDbm = (int16_t)prefs.getShort("bRssi", 0);
    resultB.medianSnrQ4 = (int16_t)prefs.getShort("bSnr", 0);
    prefs.end();

    if (storedLock) {
        phase = TrackerAntennaPhase::SWAP_LOCKED;
        txLocked.store(true);
    } else {
        // Raw sample arrays are intentionally RAM-only. If power was lost while
        // measuring, fall back to the last persistent safe checkpoint.
        if (phase == TrackerAntennaPhase::A_RUNNING)
            phase = TrackerAntennaPhase::IDLE;
        else if (phase == TrackerAntennaPhase::B_RUNNING || phase == TrackerAntennaPhase::SWAP_LOCKED)
            phase = resultA.valid ? TrackerAntennaPhase::A_SAVED : TrackerAntennaPhase::IDLE;
        txLocked.store(false);
    }

    initialized.store(true);
    trackerDiagLog("ANT_BOOT", "phase=%s txLock=%u A=%u B=%u", trackerAntennaPhaseText(phase),
                   txLocked.load() ? 1U : 0U, resultA.valid ? 1U : 0U, resultB.valid ? 1U : 0U);
}

bool trackerAntennaTxLocked()
{
    if (!roleEnabled())
        return false;
    // Block startup TX until TrackerCommonPolicy has loaded persisted state.
    if (!initialized.load())
        return true;
    return txLocked.load();
}

bool trackerAntennaTxSafeToSwap()
{
    if (!trackerAntennaTxLocked())
        return false;
    return !RadioLibInterface::instance || !RadioLibInterface::instance->isSending();
}

void trackerAntennaOnRadioPacket(const meshtastic_MeshPacket &packet)
{
    if (!roleEnabled() || !packetDirect(packet))
        return;
    const uint32_t now = millis();
    const int16_t rssi = (int16_t)packet.rx_rssi;
    const int16_t snrQ4 = (int16_t)lroundf(packet.rx_snr * 4.0f);
    noteDirect(packet.from, rssi, snrQ4, now);
    addSample(packet);
}

TrackerAntennaState trackerAntennaState()
{
    TrackerAntennaState out{};
    out.phase = phase;
    out.referenceNode = referenceNode;
    nodeName(referenceNode, out.referenceName, sizeof(out.referenceName));
    out.liveSamples = liveSampleCount;
    out.liveSeconds = liveStartedMs ? (uint32_t)(millis() - liveStartedMs) / 1000UL : 0;
    out.txLocked = trackerAntennaTxLocked();
    out.txSafeToSwap = trackerAntennaTxSafeToSwap();
    out.a = resultA;
    out.b = resultB;
    if (resultA.valid && resultB.valid) {
        out.deltaRssiDb = resultB.medianRssiDbm - resultA.medianRssiDbm;
        out.deltaSnrQ4 = resultB.medianSnrQ4 - resultA.medianSnrQ4;
    }
    return out;
}

bool trackerAntennaHandleAction()
{
    if (!roleEnabled())
        return false;
    if (!initialized.load())
        trackerAntennaTestInit();

    const uint32_t now = millis();
    switch (phase) {
    case TrackerAntennaPhase::IDLE:
    case TrackerAntennaPhase::COMPLETE: {
        const uint32_t ref = mostRecentDirect(now);
        if (!ref) {
            trackerDiagLog("ANT_TEST", "start rejected: no recent attributable direct node");
            return true;
        }
        referenceNode = ref;
        resultA = TrackerAntennaResult{};
        resultB = TrackerAntennaResult{};
        phase = TrackerAntennaPhase::A_RUNNING;
        clearLive();
        saveState();
        char name[8] = {};
        nodeName(ref, name, sizeof(name));
        trackerDiagLog("ANT_A_START", "ref=%s !%08x target=%u minimum=%u", name, (unsigned)ref,
                       (unsigned)ANT_TARGET_SAMPLES, (unsigned)ANT_MIN_SAMPLES);
        return true;
    }

    case TrackerAntennaPhase::A_RUNNING: {
        const TrackerAntennaResult r = finalizeLive();
        if (!r.valid) {
            trackerDiagLog("ANT_A_WAIT", "samples=%u minimum=%u", (unsigned)r.samples, (unsigned)ANT_MIN_SAMPLES);
            return true;
        }
        resultA = r;
        phase = TrackerAntennaPhase::A_SAVED;
        saveState();
        trackerDiagLog("ANT_A_SAVED", "ref=!%08x n=%u rssi=%ddBm snr=%+.2fdB; TX remains normal",
                       (unsigned)referenceNode, (unsigned)resultA.samples, (int)resultA.medianRssiDbm,
                       resultA.medianSnrQ4 / 4.0f);
        clearLive();
        return true;
    }

    case TrackerAntennaPhase::A_SAVED: {
        // Deliberate second action: only now is TX locked for physical antenna
        // removal. If persistence fails we refuse the swap instead of creating
        // a lock that would disappear on reboot.
        phase = TrackerAntennaPhase::SWAP_LOCKED;
        txLocked.store(true);
        if (!saveState()) {
            txLocked.store(false);
            phase = TrackerAntennaPhase::A_SAVED;
            trackerDiagLog("ANT_LOCK", "PREP SWAP rejected: failed to persist TX lock");
            return true;
        }
        trackerDiagLog("ANT_SWAP_LOCK", "TX locked; KEEP ANT CONNECTED until any in-flight TX finishes");
        return true;
    }

    case TrackerAntennaPhase::SWAP_LOCKED:
        if (!trackerAntennaTxSafeToSwap()) {
            trackerDiagLog("ANT_SWAP_WAIT", "TX lock active but RF TX still in flight; keep antenna connected");
            return true;
        }
        // This action is the user's explicit confirmation that antenna B (or at
        // least a valid antenna/load) is physically connected. Do not unlock on
        // a timer or merely because RF became idle.
        phase = TrackerAntennaPhase::B_RUNNING;
        resultB = TrackerAntennaResult{};
        clearLive();
        txLocked.store(false);
        if (!saveState()) {
            // Persistence failure while unlocking is handled fail-safe: restore
            // the persistent-style lock in RAM and require another confirmation.
            txLocked.store(true);
            phase = TrackerAntennaPhase::SWAP_LOCKED;
            trackerDiagLog("ANT_UNLOCK", "confirmation not accepted: state persistence failed; TX remains locked");
            return true;
        }
        trackerDiagLog("ANT_B_START", "antenna connected confirmed; TX unlocked; ref=!%08x target=%u minimum=%u",
                       (unsigned)referenceNode, (unsigned)ANT_TARGET_SAMPLES, (unsigned)ANT_MIN_SAMPLES);
        return true;

    case TrackerAntennaPhase::B_RUNNING: {
        const TrackerAntennaResult r = finalizeLive();
        if (!r.valid) {
            trackerDiagLog("ANT_B_WAIT", "samples=%u minimum=%u", (unsigned)r.samples, (unsigned)ANT_MIN_SAMPLES);
            return true;
        }
        resultB = r;
        phase = TrackerAntennaPhase::COMPLETE;
        saveState();
        const int deltaRssi = resultB.medianRssiDbm - resultA.medianRssiDbm;
        const int deltaSnrQ4 = resultB.medianSnrQ4 - resultA.medianSnrQ4;
        trackerDiagLog("ANT_RESULT", "ref=!%08x A=%ddBm/%+.2fdB B=%ddBm/%+.2fdB deltaRSSI=%+ddB deltaSNR=%+.2fdB",
                       (unsigned)referenceNode, (int)resultA.medianRssiDbm, resultA.medianSnrQ4 / 4.0f,
                       (int)resultB.medianRssiDbm, resultB.medianSnrQ4 / 4.0f, deltaRssi, deltaSnrQ4 / 4.0f);
        clearLive();
        return true;
    }
    }
    return false;
}

#endif
