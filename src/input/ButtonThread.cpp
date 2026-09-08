#include "ButtonThread.h"
#include "meshUtils.h"

#include "configuration.h"
#if !MESHTASTIC_EXCLUDE_GPS
#include "GPS.h"
#endif
#include "MeshService.h"
#include "Power.h"
#include "PowerFSM.h"
#include "RadioLibInterface.h"
#include "buzz.h"
#include "input/InputBroker.h"
#include "jarnsen/core/runtime/JarnsenRuntimePolicy.h"
#include "jarnsen/core/service/JarnsenDiagnosticLog.h"
#include "main.h"
#include "modules/CannedMessageModule.h"
#include "modules/ExternalNotificationModule.h"
#include "sleep.h"
#ifdef ARCH_PORTDUINO
#include "platform/portduino/PortduinoGlue.h"
#endif
#ifdef ARCH_ESP32
#include <esp_sleep.h>
#endif
#include <cstring>

using namespace concurrency;

#if defined(HELTEC_TRACKER_V1_1) || defined(HELTEC_V3) || defined(_VARIANT_HELTEC_V3) || defined(HELTEC_V4) ||              \
    defined(SEEED_WIO_TRACKER_L1) || defined(TBEAM_V10) || defined(LILYGO_TBEAM_S3_CORE)
#define JARNSEN_BUTTON_TARGET 1
#else
#define JARNSEN_BUTTON_TARGET 0
#endif

#if JARNSEN_BUTTON_TARGET
namespace
{
constexpr uint16_t JARNSEN_BUTTON_DEBOUNCE_MS = 20U;

bool isJarnsenUserButton(const char *origin)
{
    return origin && std::strcmp(origin, "UserButton") == 0;
}

void logJarnsenButtonEvent(const char *event, const char *origin, uint8_t pin, uint32_t heldMs = 0U)
{
    if (!isJarnsenUserButton(origin))
        return;
    jarnsen::diagnosticLog("BUTTON", "event=%s pin=%u held_ms=%u display_until_ms=%lu", event ? event : "unknown",
                           (unsigned)pin, (unsigned)heldMs, (unsigned long)(millis() + jarnsen::JARNSEN_DISPLAY_ON_MS));
}

#ifdef ARCH_ESP32
bool jarnsenBootWakePending = false;
bool jarnsenBootWakeHoldActive = false;
bool jarnsenBootWakeInitialized = false;

void initJarnsenBootWakeSuppression(const char *origin, uint8_t pin)
{
    if (jarnsenBootWakeInitialized || !isJarnsenUserButton(origin))
        return;
    jarnsenBootWakeInitialized = true;
    if (esp_sleep_get_wakeup_cause() != ESP_SLEEP_WAKEUP_EXT1)
        return;
    if (pin >= 64U)
        return;
    jarnsenBootWakePending = (esp_sleep_get_ext1_wakeup_status() & (1ULL << pin)) != 0;
    if (jarnsenBootWakePending)
        jarnsen::diagnosticLog("WAKE", "deep_button_hold=detected pin=%u wake_only=1", (unsigned)pin);
}
#endif
} // namespace
#endif

#if HAS_BUTTON
#endif
ButtonThread::ButtonThread(const char *name) : OSThread(name)
{
    _originName = name;
}

bool ButtonThread::initButton(const ButtonConfig &config)
{
    if (inputBroker)
        inputBroker->registerSource(this);
    _longPressTime = config.longPressTime;
    _longLongPressTime = config.longLongPressTime;
    _pinNum = config.pinNumber;
    _activeLow = config.activeLow;
    _touchQuirk = config.touchQuirk;
    _intRoutine = config.intRoutine;
    _pressHandler = config.onPress;
    _releaseHandler = config.onRelease;
    _suppressLeadUp = config.suppressLeadUpSound;
    _longLongPress = config.longLongPress;

#if JARNSEN_BUTTON_TARGET && defined(ARCH_ESP32)
    initJarnsenBootWakeSuppression(_originName, _pinNum);
#endif

    userButton = OneButton(config.pinNumber, config.activeLow, config.activePullup);

    if (config.pullupSense != 0) {
        pinMode(config.pinNumber, config.pullupSense);
    }

    _singlePress = config.singlePress;
    userButton.attachClick(
        [](void *callerThread) -> void {
            ButtonThread *thread = (ButtonThread *)callerThread;
            thread->btnEvent = BUTTON_EVENT_PRESSED;
        },
        this);

    _longPress = config.longPress;
    userButton.attachLongPressStart(
        [](void *callerThread) -> void {
            ButtonThread *thread = (ButtonThread *)callerThread;
            // if (millis() > 30000) // hold off 30s after boot
            thread->btnEvent = BUTTON_EVENT_LONG_PRESSED;
        },
        this);
    userButton.attachLongPressStop(
        [](void *callerThread) -> void {
            ButtonThread *thread = (ButtonThread *)callerThread;
            // if (millis() > 30000) // hold off 30s after boot
            thread->btnEvent = BUTTON_EVENT_LONG_RELEASED;
        },
        this);

    if (config.doublePress != INPUT_BROKER_NONE) {
        _doublePress = config.doublePress;
        userButton.attachDoubleClick(
            [](void *callerThread) -> void {
                ButtonThread *thread = (ButtonThread *)callerThread;
                thread->btnEvent = BUTTON_EVENT_DOUBLE_PRESSED;
            },
            this);
    }

    if (config.triplePress != INPUT_BROKER_NONE) {
        _triplePress = config.triplePress;
        userButton.attachMultiClick(
            [](void *callerThread) -> void {
                ButtonThread *thread = (ButtonThread *)callerThread;
                thread->storeClickCount();
                thread->btnEvent = BUTTON_EVENT_MULTI_PRESSED;
            },
            this);
    }
    if (config.shortLong != INPUT_BROKER_NONE) {
        _shortLong = config.shortLong;
    }
#ifdef USE_EINK
    userButton.setDebounceMs(0);
#elif JARNSEN_BUTTON_TARGET
    // The former 1 ms debounce was too short for the physical Userbutton on
    // several JARNSEN boards and could split one press into multiple edges.
    userButton.setDebounceMs(JARNSEN_BUTTON_DEBOUNCE_MS);
#else
    userButton.setDebounceMs(1);
#endif
    userButton.setPressMs(_longPressTime);

#if JARNSEN_BUTTON_TARGET
    if (isJarnsenUserButton(_originName))
        jarnsen::diagnosticLog("BUTTON", "event=init pin=%u debounce_ms=%u long_ms=%u active_low=%u", (unsigned)_pinNum,
                               (unsigned)JARNSEN_BUTTON_DEBOUNCE_MS, (unsigned)_longPressTime, _activeLow ? 1U : 0U);
#endif

    if (screen) {
        userButton.setClickMs(20);
    } else {
        userButton.setClickMs(BUTTON_CLICK_MS);
    }
    attachButtonInterrupts();
#ifdef ARCH_ESP32
    // Register callbacks for before and after lightsleep
    // Used to detach and reattach interrupts
    lsObserver.observe(&notifyLightSleep);
    lsEndObserver.observe(&notifyLightSleepEnd);
#endif
    return true;
}

int32_t ButtonThread::runOnce()
{
    // If the button is pressed we suppress CPU sleep until release
    canSleep = true; // Assume we should not keep the board awake

    // Check for combination timeout
    if (waitingForLongPress && (millis() - shortPressTime) > BUTTON_COMBO_TIMEOUT_MS) {
        waitingForLongPress = false;
    }

    userButton.tick();
    canSleep &= userButton.isIdle();

    // Check if we should play lead-up sound during long press
    // Play lead-up when button has been held for BUTTON_LEADUP_MS but before long press triggers
    bool buttonCurrentlyPressed = isButtonPressed(_pinNum);
#if JARNSEN_BUTTON_TARGET && defined(ARCH_ESP32)
    bool clearJarnsenBootWakeHold = false;
#endif

    // Detect start of button press
    if (buttonCurrentlyPressed && !buttonWasPressed) {
#if JARNSEN_BUTTON_TARGET && defined(ARCH_ESP32)
        if (jarnsenBootWakePending && isJarnsenUserButton(_originName))
            jarnsenBootWakeHoldActive = true;
#endif
        if (_pressHandler)
            _pressHandler();
        buttonPressStartTime = millis();
#if JARNSEN_BUTTON_TARGET
        logJarnsenButtonEvent("raw_down", _originName, _pinNum);
#endif
        leadUpPlayed = false;
        leadUpSequenceActive = false;
        resetLeadUpSequence();
    }
#ifdef INPUT_DEBUG
    if (buttonCurrentlyPressed)
        LOG_WARN("Button held for %u ms", millis() - buttonPressStartTime);
#endif

    // Progressive lead-up sound system
    if (!_suppressLeadUp && buttonCurrentlyPressed && (millis() - buttonPressStartTime) >= BUTTON_LEADUP_MS) {

        // Start the progressive sequence if not already active
        if (!leadUpSequenceActive) {
            leadUpSequenceActive = true;
            lastLeadUpNoteTime = millis();
            playNextLeadUpNote(); // Play the first note immediately
        }
        // Continue playing notes at intervals
        else if ((millis() - lastLeadUpNoteTime) >= 400) { // 400ms interval between notes
            if (playNextLeadUpNote()) {
                lastLeadUpNoteTime = millis();
            } else {
                leadUpPlayed = true;
            }
        }
    }

    // Reset when button is released
    if (!buttonCurrentlyPressed && buttonWasPressed) {
        if (_releaseHandler)
            _releaseHandler();
#if JARNSEN_BUTTON_TARGET
        const uint32_t heldMs = buttonPressStartTime != 0 ? (uint32_t)(millis() - buttonPressStartTime) : 0U;
        logJarnsenButtonEvent("raw_up", _originName, _pinNum, heldMs);
        // Single-click events reset PowerFSM on release through InputBroker.
        // Long-press SELECT fires while held, so explicitly restart the 20 s
        // display deadline again at release to make it truly "after last press".
        if (isJarnsenUserButton(_originName) && buttonPressStartTime != 0 && heldMs >= _longPressTime)
            powerFSM.trigger(EVENT_INPUT);
#endif
#if JARNSEN_BUTTON_TARGET && defined(ARCH_ESP32)
        if (jarnsenBootWakeHoldActive)
            clearJarnsenBootWakeHold = true;
#endif
        leadUpSequenceActive = false;
        resetLeadUpSequence();
    }

    buttonWasPressed = buttonCurrentlyPressed;

    // A deep-sleep wake press is consumed as wake-only. Without this guard the
    // same physical hold can wake the MCU and immediately advance/open the UI.
#if JARNSEN_BUTTON_TARGET && defined(ARCH_ESP32)
    const bool suppressJarnsenBootWakeEvent = jarnsenBootWakeHoldActive && isJarnsenUserButton(_originName);
#else
    const bool suppressJarnsenBootWakeEvent = false;
#endif

#if JARNSEN_BUTTON_TARGET
    if (btnEvent != BUTTON_EVENT_NONE && suppressJarnsenBootWakeEvent)
        jarnsen::diagnosticLog("BUTTON", "event=wake_only pin=%u raw_event=%u suppressed=1", (unsigned)_pinNum,
                               (unsigned)btnEvent);
#endif

    // new behavior
    if (btnEvent != BUTTON_EVENT_NONE && !suppressJarnsenBootWakeEvent) {
        InputEvent evt;
        evt.source = _originName;
        evt.kbchar = 0;
        evt.touchX = 0;
        evt.touchY = 0;
        switch (btnEvent) {
        case BUTTON_EVENT_PRESSED: {
#if JARNSEN_BUTTON_TARGET
            logJarnsenButtonEvent("short", _originName, _pinNum);
#endif
            // Forward single press to InputBroker (but NOT as DOWN/SELECT, just forward a "button press" event)
            evt.inputEvent = _singlePress;
            // evt.kbchar = _singlePress; // todo: fix this. Some events are kb characters rather than event types
            this->notifyObservers(&evt);

            // Start tracking for potential combination
            waitingForLongPress = true;
            shortPressTime = millis();

            break;
        }
        case BUTTON_EVENT_LONG_PRESSED: {
#if JARNSEN_BUTTON_TARGET
            logJarnsenButtonEvent("long", _originName, _pinNum,
                                  buttonPressStartTime != 0 ? (uint32_t)(millis() - buttonPressStartTime) : 0U);
#endif
            // Ignore if: TX in progress
            // Uncommon T-Echo hardware bug, LoRa TX triggers touch button
            if (_touchQuirk && RadioLibInterface::instance && RadioLibInterface::instance->isSending())
                break;

            // Check if this is part of a short-press + long-press combination
            if (_shortLong != INPUT_BROKER_NONE && waitingForLongPress &&
                (millis() - shortPressTime) <= BUTTON_COMBO_TIMEOUT_MS) {
                evt.inputEvent = _shortLong;
                // evt.kbchar = _shortLong;
                this->notifyObservers(&evt);
                // Play the combination tune
                playComboTune();

                break;
            }
            if (_longPress != INPUT_BROKER_NONE) {
                // Forward long press to InputBroker (but NOT as DOWN/SELECT, just forward a "button long press" event)
                evt.inputEvent = _longPress;
                this->notifyObservers(&evt);
            }
            // Reset combination tracking
            waitingForLongPress = false;

            break;
        }

        case BUTTON_EVENT_DOUBLE_PRESSED: { // not wired in if screen detected
#if JARNSEN_BUTTON_TARGET
            logJarnsenButtonEvent("double", _originName, _pinNum);
#endif
            LOG_INFO("Double press!");

            // Reset combination tracking
            waitingForLongPress = false;

            evt.inputEvent = _doublePress;
            // evt.kbchar = _doublePress;
            this->notifyObservers(&evt);
            playComboTune();

            break;
        }

        case BUTTON_EVENT_MULTI_PRESSED: { // not wired in when screen is present
#if JARNSEN_BUTTON_TARGET
            logJarnsenButtonEvent("multi", _originName, _pinNum);
#endif
            LOG_INFO("Mulitipress! %hux", multipressClickCount);

            // Reset combination tracking
            waitingForLongPress = false;

            switch (multipressClickCount) {
            case 3:
                evt.inputEvent = _triplePress;
                // evt.kbchar = _triplePress;
                this->notifyObservers(&evt);
                playComboTune();
                break;
#if !HAS_SCREEN
            case 4:
                if (moduleConfig.external_notification.enabled && externalNotificationModule) {
                    externalNotificationModule->setMute(!externalNotificationModule->getMute());
                    IF_SCREEN(if (!externalNotificationModule->getMute()) externalNotificationModule->stopNow();)
                    if (externalNotificationModule->getMute()) {
                        LOG_INFO("Temporarily Muted");
                        play4ClickDown(); // Disable tone
                    } else {
                        LOG_INFO("Unmuted");
                        play4ClickUp(); // Enable tone
                    }
                }
                break;
#endif
            // No valid multipress action
            default:
                break;
            } // end switch: click count

            break;
        } // end multipress event

        // Do actual shutdown when button released, otherwise the button release
        // may wake the board immediately.
        case BUTTON_EVENT_LONG_RELEASED: {
#if JARNSEN_BUTTON_TARGET
            logJarnsenButtonEvent("long_release", _originName, _pinNum,
                                  buttonPressStartTime != 0 ? (uint32_t)(millis() - buttonPressStartTime) : 0U);
#endif

            LOG_INFO("LONG PRESS RELEASE AFTER %u MILLIS", millis() - buttonPressStartTime);
            // Require press started after boot holdoff to avoid phantom shutdown from floating pins
            if (millis() > 30000 && buttonPressStartTime > 30000 && _longLongPress != INPUT_BROKER_NONE &&
                (millis() - buttonPressStartTime) >= _longLongPressTime && leadUpPlayed) {
                evt.inputEvent = _longLongPress;
                this->notifyObservers(&evt);
            }
            // Reset combination tracking
            waitingForLongPress = false;
            leadUpPlayed = false;

            break;
        }

        // doesn't handle BUTTON_EVENT_PRESSED_SCREEN BUTTON_EVENT_TOUCH_LONG_PRESSED BUTTON_EVENT_COMBO_SHORT_LONG
        default: {
            break;
        }
        }
    }
    btnEvent = BUTTON_EVENT_NONE;

#if JARNSEN_BUTTON_TARGET && defined(ARCH_ESP32)
    if (clearJarnsenBootWakeHold) {
        jarnsenBootWakePending = false;
        jarnsenBootWakeHoldActive = false;
        waitingForLongPress = false;
        jarnsen::diagnosticLog("WAKE", "deep_button_hold=released pin=%u wake_only_complete=1", (unsigned)_pinNum);
    }
#endif

    // only pull when the button is pressed, we get notified via IRQ on a new press
    if (!userButton.isIdle() || waitingForLongPress) {
        return 50;
    }
    return 100; // FIXME: Why can't we rely on interrupts and use INT32_MAX here?
}

/*
 * Attach (or re-attach) hardware interrupts for buttons
 * Public method. Used outside class when waking from MCU sleep
 */
void ButtonThread::attachButtonInterrupts()
{
    // Interrupt for user button, during normal use. Improves responsiveness.
    if (_intRoutine != nullptr)
        attachInterrupt(_pinNum, _intRoutine, CHANGE);
}

/*
 * Detach the "normal" button interrupts.
 * Public method. Used before attaching a "wake-on-button" interrupt for MCU sleep
 */
void ButtonThread::detachButtonInterrupts()
{
    if (_intRoutine != nullptr)
        detachInterrupt(_pinNum);
}

#ifdef ARCH_ESP32

// Detach our class' interrupts before lightsleep
// Allows sleep.cpp to configure its own interrupts, which wake the device on user-button press
int ButtonThread::beforeLightSleep(void *unused)
{
#if JARNSEN_BUTTON_TARGET
    if (isJarnsenUserButton(_originName))
        jarnsen::diagnosticLog("WAKE", "light=enter pin=%u", (unsigned)_pinNum);
#endif
    detachButtonInterrupts();
    return 0; // Indicates success
}

// Reconfigure our interrupts
// Our class' interrupts were disconnected during sleep, to allow the user button to wake the device from sleep
int ButtonThread::afterLightSleep(esp_sleep_wakeup_cause_t cause)
{
    attachButtonInterrupts();
#if JARNSEN_BUTTON_TARGET
    if (isJarnsenUserButton(_originName))
        jarnsen::diagnosticLog("WAKE", "light=exit pin=%u cause=%d", (unsigned)_pinNum, (int)cause);
#endif
    return 0; // Indicates success
}

#endif

// Non-static method, runs during callback. Grabs info while still valid
void ButtonThread::storeClickCount()
{
    multipressClickCount = userButton.getNumberClicks();
}
