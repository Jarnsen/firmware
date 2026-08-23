from pathlib import Path
import runpy

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
    "bool motionPinStuckLow = false;\nuint32_t motionPinLowSinceMs = 0;\n",
    "bool motionPinStuckLow = false;\nuint32_t motionPinLowSinceMs = 0;\n"
    "bool motionLightSleepWakeArmed = false;\n"
    "bool motionLightSleepObserversInstalled = false;\n",
    "shared motion light-sleep state",
)

replace_once(
    """        if (motionPinStuckLow) {\n            motionPinStuckLow = false;\n            gpio_wakeup_enable((gpio_num_t)VEHICLE_MOTION_WAKE_PIN, GPIO_INTR_LOW_LEVEL);\n            LOG_INFO(\"Tracker V1.1: GPIO%d recovered HIGH; motion wake restored\", VEHICLE_MOTION_WAKE_PIN);\n        }\n""",
    """        if (motionPinStuckLow) {\n            motionPinStuckLow = false;\n            // Do not call gpio_wakeup_enable() while awake: on ESP32-S3 it\n            // changes the GPIO interrupt mode to level-low and can turn one\n            // vibration pulse into an interrupt storm. Light-sleep observers\n            // arm LOW_LEVEL only immediately before sleep.\n            LOG_INFO(\"Tracker V1.1: GPIO%d recovered HIGH; motion wake available\", VEHICLE_MOTION_WAKE_PIN);\n        }\n""",
    "avoid awake LOW_LEVEL re-arm",
)

observer_block = r'''class TrackerCommonLightSleepBeginObserver : public Observer<void *>
{
  protected:
    int onNotify(void *) override
    {
        if (!trackerRoleEnabled())
            return 0;

        const gpio_num_t pin = (gpio_num_t)VEHICLE_MOTION_WAKE_PIN;
        detachInterrupt(digitalPinToInterrupt(VEHICLE_MOTION_WAKE_PIN));
        gpio_wakeup_disable(pin);
        pinMode(VEHICLE_MOTION_WAKE_PIN, INPUT_PULLUP);

        if (motionPinStuckLow || digitalRead(VEHICLE_MOTION_WAKE_PIN) == LOW) {
            motionLightSleepWakeArmed = false;
            attachInterrupt(digitalPinToInterrupt(VEHICLE_MOTION_WAKE_PIN), motionISR, FALLING);
            return 0;
        }

        const esp_err_t err = gpio_wakeup_enable(pin, GPIO_INTR_LOW_LEVEL);
        if (err == ESP_OK) {
            motionLightSleepWakeArmed = true;
        } else {
            LOG_ERROR("Tracker V1.1: failed to arm GPIO%d light-sleep motion wake: %d",
                      VEHICLE_MOTION_WAKE_PIN, (int)err);
            attachInterrupt(digitalPinToInterrupt(VEHICLE_MOTION_WAKE_PIN), motionISR, FALLING);
        }
        return 0;
    }
};

class TrackerCommonLightSleepEndObserver : public Observer<esp_sleep_wakeup_cause_t>
{
  protected:
    int onNotify(esp_sleep_wakeup_cause_t cause) override
    {
        if (!motionLightSleepWakeArmed)
            return 0;

        const gpio_num_t pin = (gpio_num_t)VEHICLE_MOTION_WAKE_PIN;
        gpio_wakeup_disable(pin);
        pinMode(VEHICLE_MOTION_WAKE_PIN, INPUT_PULLUP);

        // Ignore any stale ISR sequence accumulated before sleep. If GPIO7 was
        // still LOW when GPIO wake completed, count exactly one motion edge;
        // button wakes have GPIO7 HIGH and therefore do not count as motion.
        processedMotionEdgeSequence = motionEdgeSequence;
#if defined(ESP_SLEEP_WAKEUP_GPIO)
        if (cause == ESP_SLEEP_WAKEUP_GPIO && digitalRead(VEHICLE_MOTION_WAKE_PIN) == LOW)
            motionEdgeSequence++;
#else
        (void)cause;
#endif

        attachInterrupt(digitalPinToInterrupt(VEHICLE_MOTION_WAKE_PIN), motionISR, FALLING);
        motionLightSleepWakeArmed = false;
        return 0;
    }
};

TrackerCommonLightSleepBeginObserver commonLightSleepBeginObserver;
TrackerCommonLightSleepEndObserver commonLightSleepEndObserver;

'''

replace_once(
    "void armDeepSleepMotionWake()\n{\n",
    observer_block + "void armDeepSleepMotionWake()\n{\n",
    "shared safe GPIO7 light-sleep observers",
)

replace_once(
    """    pinMode(VEHICLE_MOTION_WAKE_PIN, INPUT_PULLUP);\n    processedMotionEdgeSequence = motionEdgeSequence;\n    attachInterrupt(digitalPinToInterrupt(VEHICLE_MOTION_WAKE_PIN), motionISR, FALLING);\n    gpio_wakeup_enable((gpio_num_t)VEHICLE_MOTION_WAKE_PIN, GPIO_INTR_LOW_LEVEL);\n\n    const gpio_num_t button = serviceButtonPin();\n""",
    """    pinMode(VEHICLE_MOTION_WAKE_PIN, INPUT_PULLUP);\n    processedMotionEdgeSequence = motionEdgeSequence;\n    attachInterrupt(digitalPinToInterrupt(VEHICLE_MOTION_WAKE_PIN), motionISR, FALLING);\n\n    if (!motionLightSleepObserversInstalled) {\n        commonLightSleepBeginObserver.observe(&notifyLightSleep);\n        commonLightSleepEndObserver.observe(&notifyLightSleepEnd);\n        motionLightSleepObserversInstalled = true;\n    }\n\n    const gpio_num_t button = serviceButtonPin();\n""",
    "install shared GPIO7 light-sleep observers",
)

PATH.write_text(text)
runpy.run_path("scripts/apply_tracker_sleep_power_profile_fix.py", run_name="__main__")
