#include "configuration.h"

#if defined(HELTEC_TRACKER_V1_1) && defined(VEHICLE_MOTION_WAKE_PIN) && !MESHTASTIC_EXCLUDE_GPS

#include "JarnsenBuildInfo.h"
#include "NodeDB.h"
#include "PowerFSM.h"
#include "PowerStatus.h"
#include "TrackerEnhancements.h"
#include "TrackerServiceSettings.h"
#include "concurrency/OSThread.h"
#include "gps/RTC.h"
#include "graphics/Screen.h"
#include "graphics/ScreenFonts.h"
#include "graphics/draw/NotificationRenderer.h"
#include "input/ButtonThread.h"
#include "main.h"
#include "modules/PositionModule.h"
#include "sleep.h"
#include "target_specific.h"

#include <cstdio>
#include <cstring>
#include <driver/gpio.h>

#ifndef TAK_LEADER_SERVICE_MS
#define TAK_LEADER_SERVICE_MS (120UL * 1000UL)
#endif
#ifndef TAK_LEADER_SERVICE_MAX_MS
#define TAK_LEADER_SERVICE_MAX_MS (15UL * 60UL * 1000UL)
#endif
#ifndef TAK_LEADER_SERVICE_ACTIVITY_WINDOW_MS
#define TAK_LEADER_SERVICE_ACTIVITY_WINDOW_MS (10UL * 1000UL)
#endif
#ifndef TAK_LEADER_SERVICE_ACTIVITY_THRESHOLD
#define TAK_LEADER_SERVICE_ACTIVITY_THRESHOLD 3U
#endif
#ifndef TAK_LEADER_DISPLAY_MS
#define TAK_LEADER_DISPLAY_MS 20000UL
#endif
#ifndef TAK_LEADER_LOW_BATTERY_DISPLAY_MS
#define TAK_LEADER_LOW_BATTERY_DISPLAY_MS 10000UL
#endif
#ifndef TAK_LEADER_LOW_BATTERY_PERCENT
#define TAK_LEADER_LOW_BATTERY_PERCENT 20U
#endif
#ifndef TAK_LEADER_MOTION_QUIET_MS
#define TAK_LEADER_MOTION_QUIET_MS (120UL * 1000UL)
#endif
#ifndef TAK_LEADER_MOTION_STUCK_LOW_MS
#define TAK_LEADER_MOTION_STUCK_LOW_MS 30000UL
#endif
#ifndef TAK_LEADER_MENU_LONG_PRESS_MS
#define TAK_LEADER_MENU_LONG_PRESS_MS 1200UL
#endif
#ifndef TAK_LEADER_FINAL_GPS_WAIT_MS
#define TAK_LEADER_FINAL_GPS_WAIT_MS 30000UL
#endif
#ifndef TAK_LEADER_POSITION_FRESH_SECS
#define TAK_LEADER_POSITION_FRESH_SECS 60UL
#endif
enum TakLeaderServicePage : uint8_t {
    TAK_PAGE_STATUS = 0,
    TAK_PAGE_DIAG,
    TAK_PAGE_VERSION,
    TAK_PAGE_MOTION,
    TAK_PAGE_DISTANCE,
    TAK_PAGE_INTERVAL,
    TAK_PAGE_PARK,
    TAK_PAGE_COUNT,
};

static bool leaderServiceActive = false;
static bool leaderBluetoothOn = false;
static bool leaderBootHandoffComplete = false;
static uint32_t leaderBleTrafficLast = 0;
static uint32_t leaderBleActivityWindowStartedMs = 0;
static uint8_t leaderBleActivityWindowCount = 0;
static uint32_t leaderServiceStartedMs = 0;
static uint32_t leaderServiceLastActivityMs = 0;
static uint32_t leaderDisplayStartedMs = 0;
static uint32_t leaderDisplayWindowMs = TAK_LEADER_DISPLAY_MS;
static bool leaderButtonLatched = false;
static bool leaderOpenedServiceThisPress = false;
static bool leaderLongPressHandled = false;
static uint32_t leaderButtonLowSinceMs = 0;
static uint32_t leaderButtonHighSinceMs = 0;
static uint8_t leaderServicePage = TAK_PAGE_STATUS;
static char leaderBanner[160];
static bool leaderServiceFrameActive = false;

static volatile uint32_t leaderMotionEdgeSequence = 0;
static uint32_t leaderProcessedMotionEdgeSequence = 0;
static uint8_t leaderMotionCandidateCount = 0;
static uint32_t leaderMotionCandidateStartedMs = 0;
static bool leaderMotionCandidatePending = false;
static bool leaderMotionActive = false;
static uint32_t leaderLastMotionMs = 0;
static bool leaderMotionLevelWasLow = false;
static uint32_t leaderMotionPinLowSinceMs = 0;
static bool leaderMotionWakeDisabledForStuckLow = false;
static bool leaderMotionLightSleepPrepared = false;
static bool leaderMotionLightSleepWakeArmed = false;
static bool leaderMotionLightSleepObserversInstalled = false;
static uint32_t leaderLastPositionHeartbeatEpoch = 0;
static uint32_t leaderFinalPositionWaitStartedMs = 0;

#if HAS_BUTTON && defined(BUTTON_PIN)
// InputBroker creates this before lateInitVariant(). TAK owns GPIO0 itself, so
// disable that generic button thread after it has been constructed.
extern ButtonThread *UserButtonThread;
#endif

static bool takLeaderEnabled()
{
    return config.device.role == meshtastic_Config_DeviceConfig_Role_TAK;
}

static bool takLeaderWantsScreenOn()
{
    if (!leaderServiceActive || leaderDisplayStartedMs == 0)
        return false;
    return (uint32_t)(millis() - leaderDisplayStartedMs) < leaderDisplayWindowMs;
}

bool takLeaderScreenPowerAllowed(bool on)
{
    if (!takLeaderEnabled() || !leaderBootHandoffComplete)
        return true;
    return on == takLeaderWantsScreenOn();
}

void takLeaderBleActivity()
{
    // Compatibility hook. Service lifetime is driven by the meaningful BLE
    // payload counter, not every callback or passive connection activity.
}

static uint32_t takLeaderBleMeaningfulTrafficCount()
{
#if defined(ARCH_ESP32) && !defined(CONFIG_IDF_TARGET_ESP32S2) && !MESHTASTIC_EXCLUDE_BLUETOOTH
    return nimbleBluetooth ? nimbleBluetooth->getMeaningfulTrafficCount() : 0U;
#else
    return 0U;
#endif
}

static void setTakLeaderScreenPower(bool on)
{
    if (screen)
        screen->setOn(on);
}

static gpio_num_t takLeaderButtonPin()
{
#ifdef BUTTON_PIN
    return (gpio_num_t)BUTTON_PIN;
#else
    return GPIO_NUM_NC;
#endif
}

static bool takLeaderLowBattery()
{
    if (!powerStatus || !powerStatus->getHasBattery())
        return false;
    const uint8_t percent = powerStatus->getBatteryChargePercent();
    return percent > 0 && percent <= TAK_LEADER_LOW_BATTERY_PERCENT;
}

static void setTakLeaderBluetooth(bool enabled)
{
#if defined(ARCH_ESP32) && !defined(CONFIG_IDF_TARGET_ESP32S2) && !MESHTASTIC_EXCLUDE_BLUETOOTH
    if (enabled) {
        config.bluetooth.enabled = true;
        if (!nimbleBluetooth || !nimbleBluetooth->isActive())
            setBluetoothEnable(true);
    } else {
        config.bluetooth.enabled = false;
        if (nimbleBluetooth && nimbleBluetooth->isActive())
            nimbleBluetooth->deinit();
    }
#else
    config.bluetooth.enabled = enabled;
    setBluetoothEnable(enabled);
#endif
    leaderBluetoothOn = enabled;
}

static unsigned takLeaderDisplayAge(uint32_t age)
{
    return age == UINT32_MAX ? 9999U : (unsigned)age;
}

static unsigned takLeaderHeartbeatAgeSecs()
{
    if (leaderLastPositionHeartbeatEpoch == 0)
        return 9999U;
    const uint32_t nowEpoch = getValidTime(RTCQualityDevice);
    if (nowEpoch == 0 || nowEpoch < leaderLastPositionHeartbeatEpoch)
        return 9999U;
    return (unsigned)(nowEpoch - leaderLastPositionHeartbeatEpoch);
}

static void markTakLeaderPositionSent()
{
    const uint32_t nowEpoch = getValidTime(RTCQualityDevice);
    if (nowEpoch != 0)
        leaderLastPositionHeartbeatEpoch = nowEpoch;
}

static bool takLeaderHasFreshPosition()
{
    if (!positionModule || !nodeDB || !nodeDB->hasLocalPositionSinceBoot())
        return false;
    const uint32_t age = trackerLastFixAgeSecs();
    return age != UINT32_MAX && age <= TAK_LEADER_POSITION_FRESH_SECS;
}

static void resetTakLeaderFinalPositionWait()
{
    leaderFinalPositionWaitStartedMs = 0;
}

static void IRAM_ATTR takLeaderMotionISR()
{
    leaderMotionEdgeSequence++;
}

static void drawTakLeaderServiceFrame(OLEDDisplay *display, OLEDDisplayUiState *state, int16_t x, int16_t y)
{
    if (!display)
        return;

    display->clear();
    display->setTextAlignment(TEXT_ALIGN_CENTER);

    char lines[4][64] = {};
    uint8_t lineCount = 0;
    const char *p = leaderBanner;
    while (*p && lineCount < 4) {
        size_t len = 0;
        while (p[len] && p[len] != '\n' && len < sizeof(lines[0]) - 1)
            len++;
        memcpy(lines[lineCount], p, len);
        lines[lineCount][len] = '\0';
        lineCount++;
        p += len;
        if (*p == '\n')
            p++;
    }

    const int titleHeight = FONT_HEIGHT_MEDIUM;
    const int bodyHeight = FONT_HEIGHT_SMALL;
    const int spacing = 3;
    int totalHeight = lineCount ? titleHeight : 0;
    if (lineCount > 1)
        totalHeight += (lineCount - 1) * (bodyHeight + spacing);

    int top = (display->getHeight() - totalHeight) / 2;
    if (top < 0)
        top = 0;

    for (uint8_t i = 0; i < lineCount; i++) {
        display->setFont(i == 0 ? FONT_MEDIUM : FONT_SMALL);
        display->drawString(display->getWidth() / 2 + x, top + y, lines[i]);
        top += (i == 0 ? titleHeight : bodyHeight) + spacing;
    }

    if (graphics::NotificationRenderer::current_notification_type == graphics::notificationTypeEnum::pairing_pin)
        graphics::NotificationRenderer::drawBannercallback(display, state);
}

static void stopTakLeaderServiceFrame()
{
    if (screen && leaderServiceFrameActive)
        screen->endAlert();
    leaderServiceFrameActive = false;
}

static void startTakLeaderServiceFrame()
{
    if (!screen || !leaderBootHandoffComplete)
        return;

    if (!screen->isScreenOn()) {
        // SET_ON reinitializes the Tracker TFT. Queue our alert after SET_ON so
        // the custom frame is the final UI state in the same Screen pass.
        setTakLeaderScreenPower(true);
        screen->startAlert(drawTakLeaderServiceFrame);
        leaderServiceFrameActive = true;
        screen->runNow();
    } else if (!leaderServiceFrameActive) {
        screen->startAlert(drawTakLeaderServiceFrame);
        leaderServiceFrameActive = true;
        screen->runNow();
    } else {
        // Normal page changes only redraw the already-installed frame. Never
        // restart the alert or power-cycle/reinitialize the TFT.
        screen->runNow();
    }
}

static void buildTakLeaderServicePage()
{
    unsigned battery = 0;
    if (powerStatus && powerStatus->getHasBattery())
        battery = powerStatus->getBatteryChargePercent();
    const bool positionKnown = nodeDB && nodeDB->hasLocalPositionSinceBoot();

    switch ((TakLeaderServicePage)leaderServicePage) {
    case TAK_PAGE_STATUS:
        snprintf(leaderBanner, sizeof(leaderBanner), "TAK SERVICE\nBAT %u%% GPS %s\nSHORT = NEXT", battery,
                 positionKnown ? "FIX" : "WAIT");
        break;
    case TAK_PAGE_DIAG:
        snprintf(leaderBanner, sizeof(leaderBanner), "DIAG GPS %s\nFIX %us HB %us\nSENSOR %s", positionKnown ? "FIX" : "WAIT",
                 takLeaderDisplayAge(trackerLastFixAgeSecs()), takLeaderHeartbeatAgeSecs(), trackerMotionSensorStatus());
        break;
    case TAK_PAGE_VERSION:
        snprintf(leaderBanner, sizeof(leaderBanner), "%s\nBUILD %.8s\nUP %umin %s", JARNSEN_FIRMWARE_VERSION,
                 JARNSEN_BUILD_SHA, (unsigned)(millis() / 60000UL), trackerBootWakeReason());
        break;
    case TAK_PAGE_MOTION:
        snprintf(leaderBanner, sizeof(leaderBanner), "MOTION %s\n%u PULSES / %us\nLONG = CHANGE",
                 trackerMotionSensitivityName(), (unsigned)trackerMotionConfirmCount(),
                 (unsigned)(trackerMotionConfirmWindowMs() / 1000UL));
        break;
    case TAK_PAGE_DISTANCE:
        snprintf(leaderBanner, sizeof(leaderBanner), "MIN DISTANCE\n%u m\nLONG = CHANGE", (unsigned)trackerSmartDistanceM());
        break;
    case TAK_PAGE_INTERVAL:
        snprintf(leaderBanner, sizeof(leaderBanner), "MIN INTERVAL\n%u s\nLONG = CHANGE", (unsigned)trackerSmartIntervalSecs());
        break;
    case TAK_PAGE_PARK:
        snprintf(leaderBanner, sizeof(leaderBanner), "HEARTBEAT\n%u min / eff %us\nLONG = CHANGE",
                 (unsigned)trackerParkIntervalMinutes(), (unsigned)trackerEffectiveParkIntervalSecs());
        break;
    default:
        leaderServicePage = TAK_PAGE_STATUS;
        buildTakLeaderServicePage();
        break;
    }
}

static void renderTakLeaderServicePage()
{
    if (!leaderServiceActive)
        return;

    buildTakLeaderServicePage();
    if (!leaderBootHandoffComplete) {
        leaderDisplayStartedMs = 0;
        return;
    }

    leaderDisplayStartedMs = millis();
    leaderDisplayWindowMs = takLeaderLowBattery() ? TAK_LEADER_LOW_BATTERY_DISPLAY_MS : TAK_LEADER_DISPLAY_MS;
    startTakLeaderServiceFrame();
}

static void changeTakLeaderServiceSetting()
{
    switch ((TakLeaderServicePage)leaderServicePage) {
    case TAK_PAGE_MOTION:
        trackerCycleMotionSensitivity();
        break;
    case TAK_PAGE_DISTANCE:
        trackerCycleSmartDistance();
        break;
    case TAK_PAGE_INTERVAL:
        trackerCycleSmartInterval();
        break;
    case TAK_PAGE_PARK:
        trackerCycleParkInterval();
        config.power.ls_secs = trackerEffectiveParkIntervalSecs();
        break;
    default:
        return;
    }
    renderTakLeaderServicePage();
}

static void startTakLeaderService()
{
    const uint32_t now = millis();
    leaderServiceActive = true;
    leaderServiceStartedMs = now;
    leaderServiceLastActivityMs = now;
    leaderServicePage = TAK_PAGE_STATUS;
    leaderBleActivityWindowStartedMs = 0;
    leaderBleActivityWindowCount = 0;

    // GPIO0 always opens a temporary local BLE service window regardless of
    // the persisted Bluetooth setting. It is deinitialized again on timeout.
    setTakLeaderBluetooth(true);
    leaderBleTrafficLast = takLeaderBleMeaningfulTrafficCount();
    renderTakLeaderServicePage();
    LOG_INFO("TAK leader: GPIO0 opened ATAK/Bluetooth/settings; %us idle, activity=%u/%us, %us hard cap",
             (unsigned)(TAK_LEADER_SERVICE_MS / 1000UL),
             (unsigned)TAK_LEADER_SERVICE_ACTIVITY_THRESHOLD,
             (unsigned)(TAK_LEADER_SERVICE_ACTIVITY_WINDOW_MS / 1000UL),
             (unsigned)(TAK_LEADER_SERVICE_MAX_MS / 1000UL));
}

static bool takLeaderServiceStillActive(uint32_t now)
{
    if (!leaderServiceActive)
        return false;
    return (uint32_t)(now - leaderServiceStartedMs) < (uint32_t)TAK_LEADER_SERVICE_MAX_MS &&
           (uint32_t)(now - leaderServiceLastActivityMs) < (uint32_t)TAK_LEADER_SERVICE_MS;
}

static bool takLeaderDisplayWindowActive(uint32_t now)
{
    (void)now;
    const uint32_t current = millis();
    return leaderDisplayStartedMs != 0 && (uint32_t)(current - leaderDisplayStartedMs) < leaderDisplayWindowMs;
}

static void updateTakLeaderMotionWakeHealth(uint32_t now)
{
    const gpio_num_t motionPin = (gpio_num_t)VEHICLE_MOTION_WAKE_PIN;
    const bool low = digitalRead(VEHICLE_MOTION_WAKE_PIN) == LOW;
    if (low) {
        if (leaderMotionPinLowSinceMs == 0) {
            leaderMotionPinLowSinceMs = now ? now : 1;
        } else if (!leaderMotionWakeDisabledForStuckLow &&
                   (uint32_t)(now - leaderMotionPinLowSinceMs) >= TAK_LEADER_MOTION_STUCK_LOW_MS) {
            leaderMotionWakeDisabledForStuckLow = true;
            LOG_WARN("TAK leader: GPIO%d LOW for %us; light-sleep motion wake temporarily disabled",
                     VEHICLE_MOTION_WAKE_PIN, (unsigned)(TAK_LEADER_MOTION_STUCK_LOW_MS / 1000UL));
        }
    } else {
        leaderMotionPinLowSinceMs = 0;
        if (leaderMotionWakeDisabledForStuckLow) {
            leaderMotionWakeDisabledForStuckLow = false;
            LOG_INFO("TAK leader: GPIO%d recovered HIGH; light-sleep motion wake available", VEHICLE_MOTION_WAKE_PIN);
        }
    }
}

static void confirmTakLeaderMotion(uint32_t now)
{
    leaderMotionActive = true;
    leaderLastMotionMs = now;
    leaderMotionCandidateCount = 0;
    leaderMotionCandidateStartedMs = 0;
    leaderMotionCandidatePending = false;
    resetTakLeaderFinalPositionWait();
    LOG_INFO("TAK leader: movement confirmed (%u pulses within %ums)", (unsigned)trackerMotionConfirmCount(),
             (unsigned)trackerMotionConfirmWindowMs());
}

static void finishTakLeaderMotionWithPosition(uint32_t now)
{
    if (!leaderMotionActive || (uint32_t)(now - leaderLastMotionMs) < TAK_LEADER_MOTION_QUIET_MS)
        return;

    if (takLeaderHasFreshPosition()) {
        positionModule->sendOurPosition();
        markTakLeaderPositionSent();
        resetTakLeaderFinalPositionWait();
        leaderMotionActive = false;
        LOG_INFO("TAK leader: 120s motion quiet; fresh final position sent, returning to light sleep");
        return;
    }

    if (leaderFinalPositionWaitStartedMs == 0) {
        leaderFinalPositionWaitStartedMs = now ? now : 1;
        LOG_INFO("TAK leader: 120s motion quiet; waiting up to %us for fresh final GNSS fix",
                 (unsigned)(TAK_LEADER_FINAL_GPS_WAIT_MS / 1000UL));
        return;
    }
    if ((uint32_t)(now - leaderFinalPositionWaitStartedMs) < TAK_LEADER_FINAL_GPS_WAIT_MS)
        return;

    if (positionModule && nodeDB && nodeDB->hasLocalPositionSinceBoot()) {
        positionModule->sendOurPosition();
        markTakLeaderPositionSent();
        LOG_WARN("TAK leader: final GNSS wait expired; sent best available position before light sleep");
    } else {
        LOG_WARN("TAK leader: final GNSS wait expired with no position available");
    }

    resetTakLeaderFinalPositionWait();
    leaderMotionActive = false;
    LOG_INFO("TAK leader: returning to always-listening light sleep");
}

static void processTakLeaderMotion(uint32_t now)
{
    const bool pinLow = digitalRead(VEHICLE_MOTION_WAKE_PIN) == LOW;
    const uint32_t currentSequence = leaderMotionEdgeSequence;
    uint32_t newEdges = currentSequence - leaderProcessedMotionEdgeSequence;
    if (newEdges == 0 && pinLow && !leaderMotionLevelWasLow)
        newEdges = 1;

    leaderProcessedMotionEdgeSequence = currentSequence;
    leaderMotionLevelWasLow = pinLow;

    if (newEdges != 0) {
        LOG_DEBUG("TAK motion: GPIO%d +%u edge(s), candidate=%u/%u active=%u", VEHICLE_MOTION_WAKE_PIN,
                  (unsigned)newEdges, (unsigned)leaderMotionCandidateCount, (unsigned)trackerMotionConfirmCount(),
                  leaderMotionActive ? 1U : 0U);
        if (leaderMotionActive) {
            leaderLastMotionMs = now;
            resetTakLeaderFinalPositionWait();
        } else {
            const uint32_t confirmWindowMs = trackerMotionConfirmWindowMs();
            if (!leaderMotionCandidatePending || (uint32_t)(now - leaderMotionCandidateStartedMs) > confirmWindowMs) {
                leaderMotionCandidateCount = 0;
                leaderMotionCandidateStartedMs = now;
                leaderMotionCandidatePending = true;
            }
            const uint8_t confirmCount = trackerMotionConfirmCount();
            const uint32_t needed = confirmCount > leaderMotionCandidateCount
                                        ? (uint32_t)confirmCount - leaderMotionCandidateCount
                                        : 0U;
            const uint32_t accepted = newEdges < needed ? newEdges : needed;
            leaderMotionCandidateCount = (uint8_t)(leaderMotionCandidateCount + accepted);
            if (leaderMotionCandidateCount >= confirmCount)
                confirmTakLeaderMotion(now);
        }
    }

    if (leaderMotionCandidatePending &&
        (uint32_t)(now - leaderMotionCandidateStartedMs) >= trackerMotionConfirmWindowMs()) {
        LOG_DEBUG("TAK leader: rejected vibration candidate (%u/%u pulses)", (unsigned)leaderMotionCandidateCount,
                  (unsigned)trackerMotionConfirmCount());
        leaderMotionCandidateCount = 0;
        leaderMotionCandidateStartedMs = 0;
        leaderMotionCandidatePending = false;
    }

    finishTakLeaderMotionWithPosition(now);
    updateTakLeaderMotionWakeHealth(now);
}

static void updateTakLeaderPositionHeartbeat()
{
    if (!positionModule || !nodeDB || !nodeDB->hasLocalPositionSinceBoot())
        return;
    const uint32_t nowEpoch = getValidTime(RTCQualityDevice);
    if (nowEpoch == 0)
        return;
    if (leaderLastPositionHeartbeatEpoch == 0) {
        leaderLastPositionHeartbeatEpoch = nowEpoch;
        return;
    }

    const uint32_t heartbeatSecs = trackerEffectiveParkIntervalSecs();
    if (nowEpoch >= leaderLastPositionHeartbeatEpoch &&
        (nowEpoch - leaderLastPositionHeartbeatEpoch) >= heartbeatSecs) {
        positionModule->sendOurPosition();
        leaderLastPositionHeartbeatEpoch = nowEpoch;
        LOG_INFO("TAK leader: autonomous position heartbeat sent after %us", (unsigned)heartbeatSecs);
    }
}

class TakLeaderMotionLightSleepBeginObserver : public Observer<void *>
{
  protected:
    int onNotify(void *) override
    {
        if (!takLeaderEnabled())
            return 0;

        const gpio_num_t pin = (gpio_num_t)VEHICLE_MOTION_WAKE_PIN;
        detachInterrupt(digitalPinToInterrupt(VEHICLE_MOTION_WAKE_PIN));
        leaderMotionLightSleepPrepared = true;
        leaderMotionLightSleepWakeArmed = false;
        gpio_wakeup_disable(pin);
        pinMode(VEHICLE_MOTION_WAKE_PIN, INPUT_PULLUP);

        if (!leaderMotionWakeDisabledForStuckLow && digitalRead(VEHICLE_MOTION_WAKE_PIN) != LOW) {
            const esp_err_t err = gpio_wakeup_enable(pin, GPIO_INTR_LOW_LEVEL);
            if (err == ESP_OK)
                leaderMotionLightSleepWakeArmed = true;
            else
                LOG_ERROR("TAK leader: failed to arm GPIO%d light-sleep motion wake: %d",
                          VEHICLE_MOTION_WAKE_PIN, (int)err);
        }
        return 0;
    }
};

class TakLeaderMotionLightSleepEndObserver : public Observer<esp_sleep_wakeup_cause_t>
{
  protected:
    int onNotify(esp_sleep_wakeup_cause_t cause) override
    {
        if (!leaderMotionLightSleepPrepared)
            return 0;

        const gpio_num_t pin = (gpio_num_t)VEHICLE_MOTION_WAKE_PIN;
        if (leaderMotionLightSleepWakeArmed)
            gpio_wakeup_disable(pin);
        pinMode(VEHICLE_MOTION_WAKE_PIN, INPUT_PULLUP);

        if (cause == ESP_SLEEP_WAKEUP_GPIO && leaderMotionLightSleepWakeArmed &&
            digitalRead(VEHICLE_MOTION_WAKE_PIN) == LOW)
            leaderMotionEdgeSequence++;

        attachInterrupt(digitalPinToInterrupt(VEHICLE_MOTION_WAKE_PIN), takLeaderMotionISR, FALLING);
        leaderMotionLightSleepPrepared = false;
        leaderMotionLightSleepWakeArmed = false;
        return 0;
    }
};

static TakLeaderMotionLightSleepBeginObserver takLeaderMotionLightSleepBeginObserver;
static TakLeaderMotionLightSleepEndObserver takLeaderMotionLightSleepEndObserver;

class TakLeaderSleepVeto : public Observer<void *>
{
  protected:
    int onNotify(void *deepSleepMarker) override
    {
        if (!takLeaderEnabled() || deepSleepMarker != nullptr)
            return 0;
        return (leaderServiceActive || leaderMotionActive || leaderMotionCandidatePending) ? 1 : 0;
    }
};

class HeltecTrackerV11TakLeaderPolicyThread : public concurrency::OSThread
{
  public:
    HeltecTrackerV11TakLeaderPolicyThread() : concurrency::OSThread("TakLeaderPolicy") {}

  protected:
    int32_t runOnce() override
    {
        if (!takLeaderEnabled())
            return 30000;

        const uint32_t now = millis();

#if HAS_BUTTON && defined(BUTTON_PIN)
        // ButtonThread's light-sleep observer can reattach its IRQ after wake.
        // The thread itself is disabled, but detach again so GPIO0 remains a
        // simple polled service input while the CPU is awake.
        if (UserButtonThread)
            UserButtonThread->detachButtonInterrupts();
#endif

        if (!leaderBootHandoffComplete && graphics::isBootScreenComplete()) {
            leaderBootHandoffComplete = true;
            LOG_INFO("TAK leader: Meshtastic boot screen complete; custom display ownership active");
            if (leaderServiceActive)
                renderTakLeaderServicePage();
            else if (screen && screen->isScreenOn())
                setTakLeaderScreenPower(false);
        }

        processTakLeaderMotion(now);
        updateTakLeaderPositionHeartbeat();

        const gpio_num_t button = takLeaderButtonPin();
        if (button != GPIO_NUM_NC) {
            const bool pressed = digitalRead(button) == LOW;
            if (pressed) {
                leaderButtonHighSinceMs = 0;

                // Latch immediately on the first sampled LOW. With the 10 ms
                // policy cadence below, normal short taps are captured reliably.
                // Bounce is filtered on RELEASE instead of requiring a long hold.
                if (!leaderButtonLatched) {
                    leaderButtonLatched = true;
                    leaderButtonLowSinceMs = now ? now : 1;
                    leaderOpenedServiceThisPress = false;
                    leaderLongPressHandled = false;

                    if (leaderServiceActive)
                        leaderServiceLastActivityMs = now;

                    if (!leaderServiceActive) {
                        startTakLeaderService();
                        leaderOpenedServiceThisPress = true;
                    } else if (!leaderBootHandoffComplete || !takLeaderDisplayWindowActive(now) ||
                               (screen && !screen->isScreenOn())) {
                        // First press after display timeout only wakes the current page.
                        renderTakLeaderServicePage();
                        leaderOpenedServiceThisPress = true;
                    }
                }

                if (leaderButtonLatched && leaderServiceActive && !leaderOpenedServiceThisPress && !leaderLongPressHandled &&
                    (uint32_t)(now - leaderButtonLowSinceMs) >= (uint32_t)TAK_LEADER_MENU_LONG_PRESS_MS) {
                    changeTakLeaderServiceSetting();
                    leaderLongPressHandled = true;
                }
            } else if (leaderButtonLatched) {
                // Require a stable HIGH for 25 ms before accepting release. This
                // removes contact bounce without making the user hold the key.
                if (leaderButtonHighSinceMs == 0)
                    leaderButtonHighSinceMs = now ? now : 1;

                if ((uint32_t)(now - leaderButtonHighSinceMs) >= 25U) {
                    if (leaderServiceActive && !leaderOpenedServiceThisPress && !leaderLongPressHandled) {
                        leaderServicePage = (uint8_t)((leaderServicePage + 1U) % TAK_PAGE_COUNT);
                        renderTakLeaderServicePage();
                        LOG_DEBUG("TAK leader: GPIO0 short press -> page %u/%u",
                                  (unsigned)(leaderServicePage + 1U), (unsigned)TAK_PAGE_COUNT);
                    }
                    leaderButtonLatched = false;
                    leaderOpenedServiceThisPress = false;
                    leaderLongPressHandled = false;
                    leaderButtonLowSinceMs = 0;
                    leaderButtonHighSinceMs = 0;
                }
            } else {
                leaderButtonHighSinceMs = 0;
            }
        }

        // Same policy as the V3 service: only a burst of meaningful GATT
        // payload traffic counts as active app use. Passive connections, empty
        // polling reads, duplicate writes and isolated heartbeat packets do not
        // keep the 120 s service window alive.
        const uint32_t trafficNow = takLeaderBleMeaningfulTrafficCount();
        if (trafficNow < leaderBleTrafficLast) {
            leaderBleTrafficLast = trafficNow;
            leaderBleActivityWindowStartedMs = 0;
            leaderBleActivityWindowCount = 0;
        } else if (trafficNow > leaderBleTrafficLast) {
            uint32_t delta = trafficNow - leaderBleTrafficLast;
            leaderBleTrafficLast = trafficNow;

            if (leaderBleActivityWindowStartedMs == 0 ||
                (uint32_t)(now - leaderBleActivityWindowStartedMs) > TAK_LEADER_SERVICE_ACTIVITY_WINDOW_MS) {
                leaderBleActivityWindowStartedMs = now ? now : 1;
                leaderBleActivityWindowCount = 0;
            }
            if (delta > (uint32_t)TAK_LEADER_SERVICE_ACTIVITY_THRESHOLD)
                delta = (uint32_t)TAK_LEADER_SERVICE_ACTIVITY_THRESHOLD;
            const uint32_t count = (uint32_t)leaderBleActivityWindowCount + delta;
            leaderBleActivityWindowCount = count > (uint32_t)TAK_LEADER_SERVICE_ACTIVITY_THRESHOLD
                                               ? (uint8_t)TAK_LEADER_SERVICE_ACTIVITY_THRESHOLD
                                               : (uint8_t)count;

            if (leaderServiceActive &&
                leaderBleActivityWindowCount >= (uint8_t)TAK_LEADER_SERVICE_ACTIVITY_THRESHOLD) {
                leaderServiceLastActivityMs = now;
                LOG_DEBUG("TAK leader: active BLE burst detected; 120s idle timer reset");
                leaderBleActivityWindowStartedMs = now ? now : 1;
                leaderBleActivityWindowCount = 0;
            }
        }

        if (leaderServiceActive) {
            if (!takLeaderServiceStillActive(now)) {
                leaderServiceActive = false;
                leaderDisplayStartedMs = 0;
                stopTakLeaderServiceFrame();
                setTakLeaderBluetooth(false);
                if (leaderBootHandoffComplete && screen && screen->isScreenOn())
                    setTakLeaderScreenPower(false);
                LOG_INFO("TAK leader: ATAK/Bluetooth/settings window complete");
            } else if (leaderBootHandoffComplete && screen) {
                if (leaderDisplayStartedMs == 0)
                    renderTakLeaderServicePage();

                if (takLeaderDisplayWindowActive(now)) {
                    // Normally no call is needed here. If something external did
                    // power the TFT down, restore it once and reinstall our page.
                    if (!screen->isScreenOn())
                        startTakLeaderServiceFrame();
                } else if (screen->isScreenOn()) {
                    // Keep the alert installed; only power the physical panel off.
                    setTakLeaderScreenPower(false);
                }
            }
        } else {
            setTakLeaderBluetooth(false);
            if (leaderBootHandoffComplete) {
                stopTakLeaderServiceFrame();
                if (screen && screen->isScreenOn())
                    setTakLeaderScreenPower(false);
            }
        }

        // 10 ms while awake captures normal quick GPIO0 taps. Light sleep
        // still suspends the CPU, so this does not create a continuous awake drain.
        return leaderBootHandoffComplete ? 10 : 20;
    }
};

static HeltecTrackerV11TakLeaderPolicyThread *takLeaderPolicyThread = nullptr;
static TakLeaderSleepVeto *takLeaderSleepVeto = nullptr;

void setupHeltecTrackerV11TakLeaderPolicy()
{
    if (!takLeaderEnabled() || takLeaderPolicyThread != nullptr)
        return;

    trackerServiceSettingsInit();

    config.position.gps_mode = meshtastic_Config_PositionConfig_GpsMode_ENABLED;
    config.position.fixed_position = false;
    trackerApplyPositionSettings();

    config.device.button_gpio = 0;
    config.device.disable_triple_click = true;
    config.device.led_heartbeat_disabled = true;
    config.power.is_power_saving = true;
    config.power.min_wake_secs = 1;
    config.power.ls_secs = trackerEffectiveParkIntervalSecs();
    config.network.wifi_enabled = false;
    config.power.wait_bluetooth_secs = 1;

    const gpio_num_t button = takLeaderButtonPin();
    if (button != GPIO_NUM_NC) {
        pinMode(button, INPUT_PULLUP);
        gpio_wakeup_enable(button, GPIO_INTR_LOW_LEVEL);
    }

#if HAS_BUTTON && defined(BUTTON_PIN)
    if (UserButtonThread) {
        UserButtonThread->detachButtonInterrupts();
        UserButtonThread->disable();
        LOG_INFO("TAK leader: generic Meshtastic UserButton disabled; GPIO0 exclusively owned by TAK service");
    }
#endif

    pinMode(VEHICLE_MOTION_WAKE_PIN, INPUT_PULLUP);
    leaderProcessedMotionEdgeSequence = leaderMotionEdgeSequence;
    leaderMotionLevelWasLow = digitalRead(VEHICLE_MOTION_WAKE_PIN) == LOW;
    attachInterrupt(digitalPinToInterrupt(VEHICLE_MOTION_WAKE_PIN), takLeaderMotionISR, FALLING);

    if (!leaderMotionLightSleepObserversInstalled) {
        takLeaderMotionLightSleepBeginObserver.observe(&notifyLightSleep);
        takLeaderMotionLightSleepEndObserver.observe(&notifyLightSleepEnd);
        leaderMotionLightSleepObserversInstalled = true;
    }

    takLeaderSleepVeto = new TakLeaderSleepVeto();
    takLeaderSleepVeto->observe(&preflightSleep);

    // Do not touch the screen here. Meshtastic owns its normal boot logo until
    // Screen has actually processed STOP_BOOT_SCREEN.
    config.bluetooth.enabled = false;
    setTakLeaderBluetooth(false);

    LOG_INFO("TAK leader profile: GNSS + LoRa light sleep, Smart Position + final fix, jittered heartbeat, exclusive GPIO0 service");
    takLeaderPolicyThread = new HeltecTrackerV11TakLeaderPolicyThread();
}

#endif // HELTEC_TRACKER_V1_1 && VEHICLE_MOTION_WAKE_PIN && GPS
