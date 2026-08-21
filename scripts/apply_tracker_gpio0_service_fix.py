from pathlib import Path

PATH = Path("src/vehicle/TrackerCommonPolicy.cpp")
text = PATH.read_text()


def replace_once(old: str, new: str, label: str):
    global text
    if new in text:
        print(f"{label}: already applied")
        return
    if old not in text:
        raise SystemExit(f"{label}: anchor not found")
    text = text.replace(old, new, 1)
    print(f"{label}: applied")


replace_once(
    '#include "graphics/Screen.h"\n#include "main.h"\n',
    '#include "graphics/Screen.h"\n#include "input/ButtonThread.h"\n#include "main.h"\n',
    "tracker common ButtonThread include",
)

replace_once(
    '#include <esp_sleep.h>\n',
    '#include <esp_sleep.h>\n#include <esp_timer.h>\n',
    "tracker common ISR timing include",
)

replace_once(
    'void vehicleAdaptiveRecordTimerResult(bool freshFix);\n\n#ifndef TRACKER_COMMON_SERVICE_IDLE_MS\n',
    'void vehicleAdaptiveRecordTimerResult(bool freshFix);\n\n'
    '#if HAS_BUTTON && defined(BUTTON_PIN)\n'
    'extern ButtonThread *UserButtonThread;\n'
    '#endif\n\n'
    '#ifndef TRACKER_COMMON_SERVICE_IDLE_MS\n',
    "tracker common UserButton declaration",
)

replace_once(
    '#ifndef TRACKER_COMMON_MOTION_STUCK_LOW_MS\n#define TRACKER_COMMON_MOTION_STUCK_LOW_MS (30UL * 1000UL)\n#endif\n',
    '#ifndef TRACKER_COMMON_MOTION_STUCK_LOW_MS\n#define TRACKER_COMMON_MOTION_STUCK_LOW_MS (30UL * 1000UL)\n#endif\n'
    '#ifndef TRACKER_COMMON_MOTION_ISR_DEBOUNCE_US\n'
    '#define TRACKER_COMMON_MOTION_ISR_DEBOUNCE_US 25000U\n'
    '#endif\n',
    "tracker common motion ISR debounce constant",
)

replace_once(
    'std::atomic<uint32_t> rawBleActivitySequence{0};\n',
    'std::atomic<uint32_t> rawBleActivitySequence{0};\n'
    'std::atomic<bool> buttonOwnershipRefreshRequested{true};\n'
    'std::atomic<bool> userWakeServiceRequested{false};\n',
    "tracker common button ownership state",
)

replace_once(
    'volatile uint32_t motionEdgeSequence = 0;\n',
    'volatile uint32_t motionEdgeSequence = 0;\n'
    'volatile uint32_t lastMotionAcceptedUs = 0;\n',
    "tracker common motion ISR debounce state",
)

replace_once(
    '''void IRAM_ATTR motionISR()\n{\n    motionEdgeSequence++;\n}\n''',
    '''void IRAM_ATTR motionISR()\n{\n    const uint32_t nowUs = (uint32_t)esp_timer_get_time();\n    const uint32_t lastUs = lastMotionAcceptedUs;\n    if (lastUs != 0 && (uint32_t)(nowUs - lastUs) < TRACKER_COMMON_MOTION_ISR_DEBOUNCE_US)\n        return;\n    lastMotionAcceptedUs = nowUs;\n    motionEdgeSequence++;\n}\n''',
    "tracker common motion ISR debounce",
)

replace_once(
    '''gpio_num_t serviceButtonPin()\n{\n#ifdef BUTTON_PIN\n    return (gpio_num_t)(config.device.button_gpio ? config.device.button_gpio : BUTTON_PIN);\n#else\n    return GPIO_NUM_NC;\n#endif\n}\n\n''',
    '''gpio_num_t serviceButtonPin()\n{\n#ifdef BUTTON_PIN\n    return (gpio_num_t)(config.device.button_gpio ? config.device.button_gpio : BUTTON_PIN);\n#else\n    return GPIO_NUM_NC;\n#endif\n}\n\nbool claimServiceButton()\n{\n#if HAS_BUTTON && defined(BUTTON_PIN)\n    if (UserButtonThread) {\n        UserButtonThread->detachButtonInterrupts();\n        UserButtonThread->disable();\n        return true;\n    }\n#endif\n    return false;\n}\n\n''',
    "tracker common direct GPIO0 ownership",
)

button_observer = r'''class TrackerCommonButtonWakeObserver : public Observer<esp_sleep_wakeup_cause_t>
{
  protected:
    int onNotify(esp_sleep_wakeup_cause_t cause) override
    {
        if (!trackerRoleEnabled())
            return 0;

        // Generic ButtonThread can reattach its interrupt on light-sleep exit.
        // Defer the final reclaim to TrackerCommon so it runs after all wake observers.
        buttonOwnershipRefreshRequested.store(true);
#if defined(ESP_SLEEP_WAKEUP_GPIO)
        const gpio_num_t button = serviceButtonPin();
        if (cause == ESP_SLEEP_WAKEUP_GPIO && button != GPIO_NUM_NC && digitalRead(button) == LOW)
            userWakeServiceRequested.store(true);
#else
        (void)cause;
#endif
        return 0;
    }
};

TrackerCommonButtonWakeObserver commonButtonWakeObserver;
bool buttonWakeObserverInstalled = false;

'''

replace_once(
    'class TrackerCommonSleepObserver : public Observer<void *>\n{\n',
    button_observer + 'class TrackerCommonSleepObserver : public Observer<void *>\n{\n',
    "tracker common light-sleep GPIO0 wake observer",
)

replace_once(
    '''void armDeepSleepMotionWake()\n{\n''',
    '''void armDeepSleepButtonWake()\n{\n    const gpio_num_t pin = serviceButtonPin();\n    if (pin == GPIO_NUM_NC || !rtc_gpio_is_valid_gpio(pin))\n        return;\n\n    rtc_gpio_pulldown_dis(pin);\n    rtc_gpio_pullup_en(pin);\n    const uint64_t mask = 1ULL << (uint32_t)pin;\n    const esp_err_t err = esp_sleep_enable_ext1_wakeup(mask, ESP_EXT1_WAKEUP_ANY_LOW);\n    if (err != ESP_OK)\n        LOG_ERROR("Tracker V1.1: failed to enable deep-sleep GPIO0 service wake: %d", (int)err);\n}\n\nvoid armDeepSleepMotionWake()\n{\n''',
    "tracker common deep-sleep GPIO0 wake",
)

replace_once(
    '''        trackerStatusSetMotionActive(false);\n        armDeepSleepMotionWake();\n\n        const uint32_t sleepMs = trackerEffectiveParkIntervalSecs() * 1000UL;\n''',
    '''        trackerStatusSetMotionActive(false);\n        armDeepSleepButtonWake();\n        armDeepSleepMotionWake();\n\n        const uint32_t sleepMs = trackerEffectiveParkIntervalSecs() * 1000UL;\n''',
    "tracker common arm GPIO0 before deep sleep",
)

replace_once(
    '''        const uint32_t now = millis();\n\n        if (!bootHandoffComplete && graphics::isBootScreenComplete()) {\n''',
    '''        const uint32_t now = millis();\n\n        if (buttonOwnershipRefreshRequested.exchange(false)) {\n            if (!claimServiceButton())\n                buttonOwnershipRefreshRequested.store(true);\n        }\n\n        if (userWakeServiceRequested.exchange(false) && !serviceActive) {\n            startService();\n            openedServiceThisPress = true;\n        }\n\n        if (!bootHandoffComplete && graphics::isBootScreenComplete()) {\n''',
    "tracker common runtime GPIO0 reclaim",
)

replace_once(
    '''    const gpio_num_t button = serviceButtonPin();\n    if (button != GPIO_NUM_NC) {\n        pinMode(button, INPUT_PULLUP);\n        gpio_wakeup_enable(button, GPIO_INTR_LOW_LEVEL);\n    }\n\n    if (!sleepObserverInstalled) {\n''',
    '''    const gpio_num_t button = serviceButtonPin();\n    if (button != GPIO_NUM_NC) {\n        pinMode(button, INPUT_PULLUP);\n        gpio_wakeup_enable(button, GPIO_INTR_LOW_LEVEL);\n    }\n\n    if (claimServiceButton()) {\n        buttonOwnershipRefreshRequested.store(false);\n        LOG_INFO("Tracker V1.1: generic Meshtastic UserButton disabled; GPIO0 owned by tracker service");\n    } else {\n        buttonOwnershipRefreshRequested.store(true);\n        LOG_WARN("Tracker V1.1: UserButtonThread not ready; GPIO0 ownership will be retried");\n    }\n\n    if (!buttonWakeObserverInstalled) {\n        commonButtonWakeObserver.observe(&notifyLightSleepEnd);\n        buttonWakeObserverInstalled = true;\n    }\n\n    if (!sleepObserverInstalled) {\n''',
    "tracker common setup GPIO0 ownership",
)

for needle in [
    'UserButtonThread->detachButtonInterrupts();',
    'UserButtonThread->disable();',
    'TrackerCommonButtonWakeObserver',
    'userWakeServiceRequested',
    'esp_sleep_enable_ext1_wakeup(mask, ESP_EXT1_WAKEUP_ANY_LOW)',
    'TRACKER_COMMON_MOTION_ISR_DEBOUNCE_US 25000U',
    'esp_timer_get_time()',
    'generic Meshtastic UserButton disabled; GPIO0 owned by tracker service',
]:
    if needle not in text:
        raise SystemExit(f"tracker GPIO0 service verification failed: {needle}")

PATH.write_text(text)
