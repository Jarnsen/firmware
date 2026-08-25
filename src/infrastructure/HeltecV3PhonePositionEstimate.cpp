#include "configuration.h"

#ifdef _VARIANT_HELTEC_V3

#include "MeshService.h"
#include "NodeDB.h"
#include "PositionPrecision.h"
#include "ProtobufModule.h"
#include "Throttle.h"
#include "TypeConversions.h"
#include "concurrency/OSThread.h"
#include "gps/RTC.h"
#include "infrastructure/HeltecV3DiagnosticLog.h"
#include "infrastructure/HeltecV3PositionPage.h"
#include "infrastructure/HeltecV3PowerMonitor.h"
#include "infrastructure/HeltecV3Runtime.h"
#include "main.h"

#include <cmath>
#include <driver/gpio.h>

namespace
{
constexpr uint8_t SAMPLE_CAPACITY = 8U;
constexpr uint8_t ESTIMATE_MIN_SAMPLES = 3U;
constexpr uint32_t SAMPLE_WINDOW_MS = 5UL * 60UL * 1000UL;
constexpr uint32_t SAMPLE_CLUSTER_BREAK_M = 75UL;
constexpr uint32_t ESTIMATE_MAX_RMS_M = 50UL;
constexpr uint32_t PHONE_TIMESTAMP_FRESH_SECS = 60UL;
constexpr uint32_t REPORTED_ACCURACY_LIMIT_MM = 20000UL;
constexpr uint32_t MANUAL_SAVE_HOLD_MS = 1200UL;

portMUX_TYPE estimateMux = portMUX_INITIALIZER_UNLOCKED;
meshtastic_Position latestCandidate = meshtastic_Position_init_default;
bool latestCandidateValid = false;

meshtastic_Position fixedBaseline = meshtastic_Position_init_default;
bool fixedBaselineValid = false;
bool sessionSeen = false;

meshtastic_Position samples[SAMPLE_CAPACITY];
uint8_t sampleCount = 0;
uint32_t sampleWindowStartedMs = 0;

HeltecV3PhoneEstimateUiState uiState;
uint32_t lastManualSaveAtMs = 0;

uint32_t manualHoldStartedMs = 0;
bool manualHoldHandled = false;

uint32_t distanceMeters(const meshtastic_Position &a, const meshtastic_Position &b)
{
    constexpr double DEG_TO_RAD_LOCAL = 0.017453292519943295;
    constexpr double EARTH_RADIUS_M = 6371000.0;
    const double lat1 = ((double)a.latitude_i / 10000000.0) * DEG_TO_RAD_LOCAL;
    const double lat2 = ((double)b.latitude_i / 10000000.0) * DEG_TO_RAD_LOCAL;
    const double dLat = lat2 - lat1;
    const double dLon = (((double)b.longitude_i - (double)a.longitude_i) / 10000000.0) * DEG_TO_RAD_LOCAL;
    const double x = dLon * std::cos((lat1 + lat2) * 0.5);
    const double d = std::sqrt(dLat * dLat + x * x) * EARTH_RADIUS_M;
    return d > 0.0 ? (uint32_t)std::lround(d) : 0U;
}

bool hasCoordinates(const meshtastic_Position &position)
{
    return position.has_latitude_i && position.has_longitude_i && (position.latitude_i != 0 || position.longitude_i != 0);
}

uint32_t phoneAgeSecs(const meshtastic_Position &position)
{
    if (position.time == 0)
        return UINT32_MAX;
    const uint32_t nowEpoch = getValidTime(RTCQualityFromNet);
    if (nowEpoch == 0)
        return UINT32_MAX;
    return nowEpoch >= position.time ? nowEpoch - position.time : position.time - nowEpoch;
}

bool phoneTimestampFresh(const meshtastic_Position &position)
{
    const uint32_t age = phoneAgeSecs(position);
    return age != UINT32_MAX && age <= PHONE_TIMESTAMP_FRESH_SECS;
}

bool reportedAccuracyAcceptable(const meshtastic_Position &position)
{
    return position.gps_accuracy == 0 || position.gps_accuracy <= REPORTED_ACCURACY_LIMIT_MM;
}

bool loadCurrentFixedPosition(meshtastic_Position &position)
{
    if (!nodeDB)
        return false;

    meshtastic_PositionLite lite;
    if (nodeDB->copyNodePosition(nodeDB->getNodeNum(), lite) && (lite.latitude_i != 0 || lite.longitude_i != 0)) {
        position = TypeConversions::ConvertToPosition(lite);
        return true;
    }

    if (localPosition.latitude_i != 0 || localPosition.longitude_i != 0) {
        position = localPosition;
        return true;
    }
    return false;
}

void resetSamples()
{
    sampleCount = 0;
    sampleWindowStartedMs = 0;
}

void resetSession()
{
    portENTER_CRITICAL(&estimateMux);
    latestCandidate = meshtastic_Position_init_default;
    latestCandidateValid = false;
    fixedBaseline = meshtastic_Position_init_default;
    fixedBaselineValid = false;
    sessionSeen = false;
    uiState = HeltecV3PhoneEstimateUiState{};
    lastManualSaveAtMs = 0;
    resetSamples();
    portEXIT_CRITICAL(&estimateMux);
    manualHoldStartedMs = 0;
    manualHoldHandled = false;
}

void ensureSessionBaseline()
{
    if (sessionSeen)
        return;

    meshtastic_Position baseline = meshtastic_Position_init_default;
    const bool valid = loadCurrentFixedPosition(baseline);

    portENTER_CRITICAL(&estimateMux);
    if (!sessionSeen) {
        fixedBaseline = baseline;
        fixedBaselineValid = valid;
        sessionSeen = true;
        resetSamples();
    }
    portEXIT_CRITICAL(&estimateMux);
}

void updateScatterEstimate(bool &valid, uint32_t &estimateM)
{
    valid = false;
    estimateM = 0;
    if (sampleCount < ESTIMATE_MIN_SAMPLES)
        return;

    double meanLat = 0.0;
    double meanLon = 0.0;
    for (uint8_t i = 0; i < sampleCount; ++i) {
        meanLat += samples[i].latitude_i;
        meanLon += samples[i].longitude_i;
    }
    meanLat /= sampleCount;
    meanLon /= sampleCount;

    meshtastic_Position center = meshtastic_Position_init_default;
    center.has_latitude_i = true;
    center.has_longitude_i = true;
    center.latitude_i = (int32_t)std::llround(meanLat);
    center.longitude_i = (int32_t)std::llround(meanLon);

    double sumSquares = 0.0;
    for (uint8_t i = 0; i < sampleCount; ++i) {
        const double d = distanceMeters(center, samples[i]);
        sumSquares += d * d;
    }
    const double rms = std::sqrt(sumSquares / sampleCount);
    if (rms > ESTIMATE_MAX_RMS_M)
        return;

    estimateM = (uint32_t)std::ceil(rms);
    if (estimateM < 3U)
        estimateM = 3U;
    valid = true;
}

void addSample(const meshtastic_Position &position, uint32_t now)
{
    if (sampleWindowStartedMs != 0 && !Throttle::isWithinTimespanMs(sampleWindowStartedMs, SAMPLE_WINDOW_MS))
        resetSamples();

    if (sampleCount > 0) {
        const meshtastic_Position &previous = samples[sampleCount - 1];
        if (previous.latitude_i == position.latitude_i && previous.longitude_i == position.longitude_i) {
            return;
        }
        if (distanceMeters(previous, position) > SAMPLE_CLUSTER_BREAK_M)
            resetSamples();
    }

    if (sampleCount == 0)
        sampleWindowStartedMs = now ? now : 1;

    if (sampleCount < SAMPLE_CAPACITY) {
        samples[sampleCount++] = position;
    } else {
        for (uint8_t i = 1; i < SAMPLE_CAPACITY; ++i)
            samples[i - 1] = samples[i];
        samples[SAMPLE_CAPACITY - 1] = position;
    }
}

bool buttonPressed()
{
#ifdef BUTTON_PIN
    return digitalRead(BUTTON_PIN) == LOW;
#else
    return false;
#endif
}

class V3PhoneEstimateModule;

class V3PhoneEstimateWorker : public concurrency::OSThread
{
  public:
    explicit V3PhoneEstimateWorker(V3PhoneEstimateModule *owner)
        : concurrency::OSThread("V3PhoneEstimate"), owner(owner)
    {
    }

  protected:
    int32_t runOnce() override;

  private:
    V3PhoneEstimateModule *owner;
};

class V3PhoneEstimateModule : public ProtobufModule<meshtastic_Position>
{
  public:
    V3PhoneEstimateModule()
        : ProtobufModule("v3-phone-estimate", meshtastic_PortNum_POSITION_APP, &meshtastic_Position_msg)
    {
        loopbackOk = true;
        isPromiscuous = true;
    }

    bool saveManualCandidate()
    {
        if (!nodeDB || !service)
            return false;

        meshtastic_Position candidate = meshtastic_Position_init_default;
        meshtastic_Position baseline = meshtastic_Position_init_default;
        bool baselineValid = false;
        portENTER_CRITICAL(&estimateMux);
        if (!latestCandidateValid) {
            portEXIT_CRITICAL(&estimateMux);
            return false;
        }
        candidate = latestCandidate;
        baseline = fixedBaseline;
        baselineValid = fixedBaselineValid;
        portEXIT_CRITICAL(&estimateMux);

        if (!hasCoordinates(candidate))
            return false;

        const uint32_t previousDifferenceM = baselineValid ? distanceMeters(baseline, candidate) : 0U;
        const uint32_t nowEpoch = getValidTime(RTCQualityFromNet);

        meshtastic_Position fixed = candidate;
        fixed.location_source = meshtastic_Position_LocSource_LOC_MANUAL;
        fixed.ground_speed = 0;
        fixed.has_ground_speed = false;
        fixed.ground_track = 0;
        fixed.has_ground_track = false;
        if (nowEpoch != 0) {
            fixed.time = nowEpoch;
            fixed.timestamp = nowEpoch;
        }

        config.position.fixed_position = true;
        nodeDB->setLocalPosition(fixed);
        nodeDB->updatePosition(nodeDB->getNodeNum(), fixed);
        nodeDB->saveToDisk(SEGMENT_CONFIG | SEGMENT_NODEDATABASE);

        bool meshSent = false;
        const uint32_t precision = getPositionPrecisionForChannel(0);
        if (precision != 0) {
            meshtastic_Position outgoing = fixed;
            applyPositionPrecision(outgoing, precision);
            meshtastic_MeshPacket *packet = allocDataProtobuf(outgoing);
            if (packet) {
                packet->to = NODENUM_BROADCAST;
                packet->channel = 0;
                service->sendToMesh(packet, RX_SRC_USER);
                heltecV3PowerMonitorNotePositionTx();
                meshSent = true;
            }
        }

        portENTER_CRITICAL(&estimateMux);
        fixedBaseline = fixed;
        fixedBaselineValid = true;
        uiState.fixedDifferenceValid = true;
        uiState.fixedDifferenceM = 0;
        uiState.lastManualSaveValid = true;
        uiState.lastManualSaveMeshSent = meshSent;
        lastManualSaveAtMs = millis() ? millis() : 1;
        portEXIT_CRITICAL(&estimateMux);

        heltecV3DiagNotePositionSave(false, previousDifferenceM);
        heltecV3DiagLog("PHONE_POS_FIXED", "manual-override lat=%d lon=%d diff=%um mesh=%u phone-time-overridden=%u",
                        fixed.latitude_i, fixed.longitude_i, (unsigned)previousDifferenceM, meshSent ? 1U : 0U,
                        nowEpoch != 0 ? 1U : 0U);
        LOG_INFO("Heltec V3 phone candidate manually saved: diff=%um mesh=%s; phone timestamp replaced with current node time",
                 (unsigned)previousDifferenceM, meshSent ? "sent" : "not-sent");
        heltecV3PositionPageRefresh();
        return true;
    }

  protected:
    bool handleReceivedProtobuf(const meshtastic_MeshPacket &mp, meshtastic_Position *position) override
    {
        if (!position || !heltecV3RuntimeServiceActive())
            return false;

        const bool phoneTransport =
            mp.transport_mechanism == meshtastic_MeshPacket_TransportMechanism_TRANSPORT_API ||
            (mp.transport_mechanism == meshtastic_MeshPacket_TransportMechanism_TRANSPORT_INTERNAL && mp.from == 0);
        const bool phoneSource = isFromUs(&mp) || mp.from == 0;
        if (!phoneSource || !phoneTransport || !hasCoordinates(*position))
            return false;

        ensureSessionBaseline();
        if (!worker)
            worker = new V3PhoneEstimateWorker(this);

        const uint32_t now = millis();
        const uint32_t age = phoneAgeSecs(*position);

        meshtastic_Position baseline = meshtastic_Position_init_default;
        bool baselineValid = false;
        portENTER_CRITICAL(&estimateMux);
        baseline = fixedBaseline;
        baselineValid = fixedBaselineValid;
        portEXIT_CRITICAL(&estimateMux);

        addSample(*position, now);
        bool estimateValid = false;
        uint32_t estimateM = 0;
        updateScatterEstimate(estimateValid, estimateM);
        const uint8_t count = sampleCount;
        const uint32_t diffM = baselineValid ? distanceMeters(baseline, *position) : 0U;

        portENTER_CRITICAL(&estimateMux);
        latestCandidate = *position;
        latestCandidateValid = true;
        uiState.available = true;
        uiState.latitudeI = position->latitude_i;
        uiState.longitudeI = position->longitude_i;
        uiState.reportedAccuracyValid = position->gps_accuracy != 0;
        uiState.reportedAccuracyM = position->gps_accuracy == 0 ? 0U : (position->gps_accuracy + 999U) / 1000U;
        uiState.estimatedAccuracyValid = estimateValid;
        uiState.estimatedAccuracyM = estimateM;
        uiState.sampleCount = count;
        uiState.phoneAgeSecs = age;
        uiState.phoneTimestampStale = age == UINT32_MAX || age > PHONE_TIMESTAMP_FRESH_SECS;
        uiState.manualSaveAvailable = true;
        uiState.fixedDifferenceValid = baselineValid;
        uiState.fixedDifferenceM = diffM;
        portEXIT_CRITICAL(&estimateMux);
        const bool diffValid = baselineValid;

        heltecV3DiagLog("PHONE_POS_EST", "samples=%u reported=%um estimate=%s%um fixed-diff=%s%um phone-age=%us",
                        (unsigned)count, (unsigned)((position->gps_accuracy + 999U) / 1000U), estimateValid ? "" : "?",
                        (unsigned)estimateM, diffValid ? "" : "?", (unsigned)diffM,
                        age == UINT32_MAX ? 9999U : (unsigned)age);
        heltecV3PositionPageRefresh();
        return false;
    }

  private:
    V3PhoneEstimateWorker *worker = nullptr;
};

int32_t V3PhoneEstimateWorker::runOnce()
{
    if (!heltecV3RuntimeServiceActive()) {
        if (sessionSeen)
            resetSession();
        return 500;
    }

    if (!sessionSeen)
        ensureSessionBaseline();

    const bool pressed = buttonPressed();
    if (!pressed) {
        manualHoldStartedMs = 0;
        manualHoldHandled = false;
        return 100;
    }

    meshtastic_Position candidate = meshtastic_Position_init_default;
    bool candidateValid = false;
    portENTER_CRITICAL(&estimateMux);
    candidate = latestCandidate;
    candidateValid = latestCandidateValid;
    portEXIT_CRITICAL(&estimateMux);

    const bool policyNeedsOverride =
        candidateValid && (!phoneTimestampFresh(candidate) || !reportedAccuracyAcceptable(candidate));
    if (!policyNeedsOverride || !heltecV3PositionPageRecentlyVisible()) {
        manualHoldStartedMs = 0;
        return 100;
    }

    const uint32_t now = millis();
    if (manualHoldStartedMs == 0)
        manualHoldStartedMs = now ? now : 1;

    if (!manualHoldHandled && !Throttle::isWithinTimespanMs(manualHoldStartedMs, MANUAL_SAVE_HOLD_MS)) {
        manualHoldHandled = owner && owner->saveManualCandidate();
        manualHoldStartedMs = now ? now : 1;
    }
    return 100;
}

V3PhoneEstimateModule v3PhoneEstimateModule;

} // namespace

bool heltecV3GetPhoneEstimateUiState(HeltecV3PhoneEstimateUiState &out)
{
    portENTER_CRITICAL(&estimateMux);
    out = uiState;
    const uint32_t savedAt = lastManualSaveAtMs;
    portEXIT_CRITICAL(&estimateMux);

    if (out.lastManualSaveValid && savedAt != 0)
        out.lastManualSaveAgeMs = (uint32_t)(millis() - savedAt);
    return out.available || out.lastManualSaveValid;
}

#endif // _VARIANT_HELTEC_V3
