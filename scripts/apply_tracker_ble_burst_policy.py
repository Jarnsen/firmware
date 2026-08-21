from pathlib import Path

POLICY_PATH = Path("src/vehicle/VehicleServicePolicyV3Style.cpp")
MOTION_PATH = Path("src/vehicle/HeltecTrackerV11VehicleMotionTracker.cpp")
POWER_FSM_PATH = Path("src/PowerFSM.cpp")
NIMBLE_H_PATH = Path("src/nimble/NimbleBluetooth.h")
NIMBLE_CPP_PATH = Path("src/nimble/NimbleBluetooth.cpp")

policy = POLICY_PATH.read_text()
motion = MOTION_PATH.read_text()
power_fsm = POWER_FSM_PATH.read_text()
nimble_h = NIMBLE_H_PATH.read_text()
nimble_cpp = NIMBLE_CPP_PATH.read_text()


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if new in text:
        print(f"{label}: already applied")
        return text
    if old not in text:
        raise SystemExit(f"{label}: anchor not found")
    print(f"{label}: applied")
    return text.replace(old, new, 1)


# ---------------------------------------------------------------------------
# Tracker BLE service: same meaningful-traffic burst policy as the proven V3
# service, while keeping the Tracker-specific rule that motion/timer wakes do
# not turn Bluetooth on. Local GPIO0 menu use is independent of BLE.
# ---------------------------------------------------------------------------
policy = replace_once(
    policy,
    "#ifndef VEHICLE_V3_SERVICE_MAX_MS\n#define VEHICLE_V3_SERVICE_MAX_MS (15UL * 60UL * 1000UL)\n#endif\n",
    "#ifndef VEHICLE_V3_SERVICE_MAX_MS\n#define VEHICLE_V3_SERVICE_MAX_MS (15UL * 60UL * 1000UL)\n#endif\n"
    "#ifndef VEHICLE_V3_SERVICE_ACTIVITY_WINDOW_MS\n#define VEHICLE_V3_SERVICE_ACTIVITY_WINDOW_MS (10UL * 1000UL)\n#endif\n"
    "#ifndef VEHICLE_V3_SERVICE_ACTIVITY_THRESHOLD\n#define VEHICLE_V3_SERVICE_ACTIVITY_THRESHOLD 3U\n#endif\n",
    "Tracker BLE burst constants",
)

policy = replace_once(
    policy,
    "static bool v3TrackerServiceFrameActive = false;\n"
    "static volatile uint32_t v3TrackerPendingBleActivityMs = 0;\n"
    "static uint32_t v3TrackerServiceStartedMs = 0;\n",
    "static bool v3TrackerServiceFrameActive = false;\n"
    "static uint32_t v3TrackerBleTrafficLast = 0;\n"
    "static uint32_t v3TrackerBleActivityWindowStartedMs = 0;\n"
    "static uint8_t v3TrackerBleActivityWindowCount = 0;\n"
    "static uint32_t v3TrackerServiceStartedMs = 0;\n",
    "Tracker BLE burst state",
)

policy = replace_once(
    policy,
    """static bool v3TrackerPositionKnown()\n{\n    return nodeDB && nodeDB->hasLocalPositionSinceBoot();\n}\n\nstatic bool v3TrackerDisplayWindowActive()\n""",
    """static bool v3TrackerPositionKnown()\n{\n    return nodeDB && nodeDB->hasLocalPositionSinceBoot();\n}\n\nstatic uint32_t v3TrackerBleMeaningfulTrafficCount()\n{\n#if defined(ARCH_ESP32) && !defined(CONFIG_IDF_TARGET_ESP32S2) && !MESHTASTIC_EXCLUDE_BLUETOOTH\n    return nimbleBluetooth ? nimbleBluetooth->getMeaningfulTrafficCount() : 0U;\n#else\n    return 0U;\n#endif\n}\n\nstatic bool v3TrackerDisplayWindowActive()\n""",
    "Tracker meaningful BLE accessor",
)

policy = replace_once(
    policy,
    """void vehicleV3StyleBleActivity()\n{\n    v3TrackerPendingBleActivityMs = millis() ? millis() : 1;\n}\n""",
    """void vehicleV3StyleBleActivity()\n{\n    // Compatibility hook for the Tracker policy router. Service lifetime is\n    // driven by NimBLE's meaningful-traffic counter below, not by every BLE\n    // callback and not by the mere existence of a connection.\n}\n""",
    "stop raw BLE callbacks refreshing Tracker service",
)

policy = replace_once(
    policy,
    """    v3TrackerServicePage = VEHICLE_V3_PAGE_STATUS;\n    v3TrackerDisplayVisible = false;\n    v3TrackerLastFrameAssertMs = 0;\n\n    // Keep power saving ON exactly like the V3 repeater. The preflight sleep\n""",
    """    v3TrackerServicePage = VEHICLE_V3_PAGE_STATUS;\n    v3TrackerDisplayVisible = false;\n    v3TrackerLastFrameAssertMs = 0;\n    v3TrackerBleActivityWindowStartedMs = 0;\n    v3TrackerBleActivityWindowCount = 0;\n\n    // Keep power saving ON exactly like the V3 repeater. The preflight sleep\n""",
    "reset Tracker BLE burst window at service start",
)

policy = replace_once(
    policy,
    """    config.power.is_power_saving = true;\n    config.bluetooth.enabled = true;\n    v3TrackerBluetoothOn();\n    v3TrackerShowPage();\n\n    LOG_INFO(\"Tracker service: GPIO0 opened display/Bluetooth; idle=%us hard-cap=%us power-save=%s\",\n             (unsigned)(VEHICLE_V3_SERVICE_IDLE_MS / 1000UL), (unsigned)(VEHICLE_V3_SERVICE_MAX_MS / 1000UL),\n             config.power.is_power_saving ? \"on\" : \"off\");\n""",
    """    config.power.is_power_saving = true;\n    config.bluetooth.enabled = true;\n    v3TrackerBluetoothOn();\n    v3TrackerBleTrafficLast = v3TrackerBleMeaningfulTrafficCount();\n    v3TrackerShowPage();\n\n    LOG_INFO(\"Tracker service: GPIO0 opened display/Bluetooth; idle=%us activity=%u/%us hard-cap=%us power-save=%s\",\n             (unsigned)(VEHICLE_V3_SERVICE_IDLE_MS / 1000UL),\n             (unsigned)VEHICLE_V3_SERVICE_ACTIVITY_THRESHOLD,\n             (unsigned)(VEHICLE_V3_SERVICE_ACTIVITY_WINDOW_MS / 1000UL),\n             (unsigned)(VEHICLE_V3_SERVICE_MAX_MS / 1000UL),\n             config.power.is_power_saving ? \"on\" : \"off\");\n""",
    "initialize Tracker meaningful BLE counter",
)

policy = replace_once(
    policy,
    """        const uint32_t pendingBleActivity = v3TrackerPendingBleActivityMs;\n        if (pendingBleActivity != 0) {\n            v3TrackerPendingBleActivityMs = 0;\n            if (v3TrackerServiceActive) {\n                v3TrackerServiceLastActivityMs = now;\n                // Feed the deep-sleep tracker holdoff from the main task, not\n                // directly from the NimBLE callback task.\n                meshtasticVehiclePhoneContact();\n            }\n        }\n\n        if (!v3TrackerServiceActive) {\n""",
    """        // Three meaningful payload transactions inside ten seconds count\n        // as active app use and reset the 120 s inactivity timer. A passive\n        // connection, empty polling reads, duplicate writes and isolated\n        // heartbeat/GPS traffic cannot pin Bluetooth on.\n        const uint32_t trafficNow = v3TrackerBleMeaningfulTrafficCount();\n        if (trafficNow < v3TrackerBleTrafficLast) {\n            v3TrackerBleTrafficLast = trafficNow;\n            v3TrackerBleActivityWindowStartedMs = 0;\n            v3TrackerBleActivityWindowCount = 0;\n        } else if (trafficNow > v3TrackerBleTrafficLast) {\n            uint32_t delta = trafficNow - v3TrackerBleTrafficLast;\n            v3TrackerBleTrafficLast = trafficNow;\n\n            if (v3TrackerBleActivityWindowStartedMs == 0 ||\n                (uint32_t)(now - v3TrackerBleActivityWindowStartedMs) >\n                    (uint32_t)VEHICLE_V3_SERVICE_ACTIVITY_WINDOW_MS) {\n                v3TrackerBleActivityWindowStartedMs = now ? now : 1;\n                v3TrackerBleActivityWindowCount = 0;\n            }\n\n            if (delta > (uint32_t)VEHICLE_V3_SERVICE_ACTIVITY_THRESHOLD)\n                delta = (uint32_t)VEHICLE_V3_SERVICE_ACTIVITY_THRESHOLD;\n            const uint32_t activityCount = (uint32_t)v3TrackerBleActivityWindowCount + delta;\n            v3TrackerBleActivityWindowCount =\n                activityCount > (uint32_t)VEHICLE_V3_SERVICE_ACTIVITY_THRESHOLD\n                    ? (uint8_t)VEHICLE_V3_SERVICE_ACTIVITY_THRESHOLD\n                    : (uint8_t)activityCount;\n\n            if (v3TrackerServiceActive &&\n                v3TrackerBleActivityWindowCount >= (uint8_t)VEHICLE_V3_SERVICE_ACTIVITY_THRESHOLD) {\n                v3TrackerServiceLastActivityMs = now;\n                meshtasticVehiclePhoneContact();\n                LOG_DEBUG(\"Tracker service: active BLE burst detected; 120s idle timer reset\");\n                v3TrackerBleActivityWindowStartedMs = now ? now : 1;\n                v3TrackerBleActivityWindowCount = 0;\n            }\n        }\n\n        if (!v3TrackerServiceActive) {\n""",
    "Tracker 3-in-10s meaningful BLE activity detector",
)

# ---------------------------------------------------------------------------
# NimBLE meaningful traffic counter. Accepted non-duplicate writes and nonempty
# reads count. Empty polling reads and duplicate writes do not.
# ---------------------------------------------------------------------------
nimble_h = replace_once(
    nimble_h,
    "    bool isConnected();\n    int getRssi();\n",
    "    bool isConnected();\n    uint32_t getMeaningfulTrafficCount();\n    int getRssi();\n",
    "declare Tracker meaningful BLE counter",
)

nimble_cpp = replace_once(
    nimble_cpp,
    "static std::atomic<bool> bleDraining{false};\n",
    "static std::atomic<bool> bleDraining{false};\n"
    "static std::atomic<uint32_t> meaningfulBleTrafficCount{0};\n",
    "Tracker meaningful BLE traffic atomic",
)

nimble_cpp = replace_once(
    nimble_cpp,
    """        int currentWriteCount = bluetoothPhoneAPI->writeCount.fetch_add(1);\n        if (meshtasticTrackerBleActivity)\n            meshtasticTrackerBleActivity();\n\n#ifdef DEBUG_NIMBLE_ON_WRITE_TIMING\n""",
    """        int currentWriteCount = bluetoothPhoneAPI->writeCount.fetch_add(1);\n\n#ifdef DEBUG_NIMBLE_ON_WRITE_TIMING\n""",
    "remove raw Tracker activity hook before duplicate filter",
)

nimble_cpp = replace_once(
    nimble_cpp,
    """                memcpy(lastToRadio, val.getData(), val.getLength());\n\n                { // scope for fromPhoneMutex mutexv, pCharacteristic->getLen\n""",
    """                memcpy(lastToRadio, val.getData(), val.getLength());\n                meaningfulBleTrafficCount.fetch_add(1);\n                if (meshtasticTrackerBleActivity)\n                    meshtasticTrackerBleActivity();\n\n                { // scope for fromPhoneMutex mutexv, pCharacteristic->getLen\n""",
    "count only accepted non-duplicate Tracker writes",
)

nimble_cpp = replace_once(
    nimble_cpp,
    """        // If we sent something, wake up the main loop if it's sleeping in case there are more packets ready to enqueue.\n        if (numBytes != 0) {\n            bluetoothPhoneAPI->setIntervalFromNow(0);\n""",
    """        // Count only non-empty payload reads. Empty client polling reads\n        // must not make a background connection look actively used.\n        if (numBytes != 0) {\n            meaningfulBleTrafficCount.fetch_add(1);\n            bluetoothPhoneAPI->setIntervalFromNow(0);\n""",
    "count non-empty Tracker BLE reads",
)

nimble_cpp = replace_once(
    nimble_cpp,
    """        bluetoothPhoneAPI->readCount = 0;\n        bluetoothPhoneAPI->notifyCount = 0;\n        bluetoothPhoneAPI->writeCount = 0;\n""",
    """        bluetoothPhoneAPI->readCount = 0;\n        bluetoothPhoneAPI->notifyCount = 0;\n        bluetoothPhoneAPI->writeCount = 0;\n        meaningfulBleTrafficCount = 0;\n""",
    "reset Tracker meaningful BLE counter",
)

nimble_cpp = replace_once(
    nimble_cpp,
    """bool NimbleBluetooth::isConnected()\n{\n    return nimbleBluetoothConnHandle.load() != BLE_HS_CONN_HANDLE_NONE;\n}\n\nint NimbleBluetooth::getRssi()\n""",
    """bool NimbleBluetooth::isConnected()\n{\n    return nimbleBluetoothConnHandle.load() != BLE_HS_CONN_HANDLE_NONE;\n}\n\nuint32_t NimbleBluetooth::getMeaningfulTrafficCount()\n{\n    return meaningfulBleTrafficCount.load();\n}\n\nint NimbleBluetooth::getRssi()\n""",
    "implement Tracker meaningful BLE counter",
)

# ---------------------------------------------------------------------------
# GPIO7 motion sensor light-sleep wake. gpio_wakeup_enable() changes the GPIO
# interrupt type to level-low on ESP32-S3, so the normal FALLING ISR MUST be
# detached before arming wake. On wake, disable level wake and restore FALLING.
# This prevents the thousands-of-edges interrupt storm observed in the log.
# ---------------------------------------------------------------------------
motion = replace_once(
    motion,
    "#include <driver/rtc_io.h>\n#include <esp_sleep.h>\n",
    "#include <driver/gpio.h>\n#include <driver/rtc_io.h>\n#include <esp_sleep.h>\n",
    "include GPIO light-sleep API",
)

motion = replace_once(
    motion,
    "static bool managedSleepPermission = false;\nstatic bool suppressMotionWakeForSafetySleep = false;\n",
    "static bool managedSleepPermission = false;\nstatic bool suppressMotionWakeForSafetySleep = false;\n"
    "static bool motionLightSleepWakeArmed = false;\n"
    "static bool motionLightSleepObserversInstalled = false;\n",
    "motion light-sleep state",
)

motion = replace_once(
    motion,
    """void variant_shutdown()\n{\n    if (vehicleTrackerModeEnabled() && !suppressMotionWakeForSafetySleep)\n        armVehicleMotionWake();\n}\n""",
    """class TrackerMotionLightSleepBeginObserver : public Observer<void *>\n{\n  protected:\n    int onNotify(void *) override\n    {\n        if (!vehicleTrackerModeEnabled())\n            return 0;\n\n        const gpio_num_t pin = (gpio_num_t)VEHICLE_MOTION_WAKE_PIN;\n        // gpio_wakeup_enable() also changes the normal GPIO interrupt type.\n        // Remove our FALLING ISR first so a LOW sensor pulse cannot retrigger\n        // the ISR thousands of times while level wake is armed.\n        detachInterrupt(digitalPinToInterrupt(VEHICLE_MOTION_WAKE_PIN));\n        gpio_wakeup_disable(pin);\n        pinMode(VEHICLE_MOTION_WAKE_PIN, INPUT_PULLUP);\n        const esp_err_t err = gpio_wakeup_enable(pin, GPIO_INTR_LOW_LEVEL);\n        if (err == ESP_OK) {\n            motionLightSleepWakeArmed = true;\n        } else {\n            LOG_ERROR(\"Tracker V1.1: failed to arm GPIO%d light-sleep motion wake: %d\",\n                      VEHICLE_MOTION_WAKE_PIN, (int)err);\n            attachInterrupt(digitalPinToInterrupt(VEHICLE_MOTION_WAKE_PIN), vehicleMotionISR, FALLING);\n        }\n        return 0;\n    }\n};\n\nclass TrackerMotionLightSleepEndObserver : public Observer<esp_sleep_wakeup_cause_t>\n{\n  protected:\n    int onNotify(esp_sleep_wakeup_cause_t cause) override\n    {\n        if (!motionLightSleepWakeArmed)\n            return 0;\n\n        const gpio_num_t pin = (gpio_num_t)VEHICLE_MOTION_WAKE_PIN;\n        gpio_wakeup_disable(pin);\n        pinMode(VEHICLE_MOTION_WAKE_PIN, INPUT_PULLUP);\n\n        // A GPIO7 level wake represents one physical wake event. Record one\n        // candidate edge, then restore the normal edge-triggered ISR. GPIO0\n        // button wakes have GPIO7 HIGH and therefore do not count as motion.\n        if (cause == ESP_SLEEP_WAKEUP_GPIO && digitalRead(VEHICLE_MOTION_WAKE_PIN) == LOW)\n            motionEdgeSequence++;\n\n        attachInterrupt(digitalPinToInterrupt(VEHICLE_MOTION_WAKE_PIN), vehicleMotionISR, FALLING);\n        motionLightSleepWakeArmed = false;\n        return 0;\n    }\n};\n\nstatic TrackerMotionLightSleepBeginObserver trackerMotionLightSleepBeginObserver;\nstatic TrackerMotionLightSleepEndObserver trackerMotionLightSleepEndObserver;\n\nvoid variant_shutdown()\n{\n    if (vehicleTrackerModeEnabled() && !suppressMotionWakeForSafetySleep)\n        armVehicleMotionWake();\n}\n""",
    "safe GPIO7 light-sleep wake observers",
)

motion = replace_once(
    motion,
    """void setupHeltecTrackerV11VehicleMotionTracker()\n{\n    if (vehicleTrackerModeEnabled() && vehicleMotionThread == nullptr)\n        vehicleMotionThread = new HeltecTrackerV11VehicleMotionThread();\n}\n""",
    """void setupHeltecTrackerV11VehicleMotionTracker()\n{\n    if (!vehicleTrackerModeEnabled())\n        return;\n\n    if (!motionLightSleepObserversInstalled) {\n        trackerMotionLightSleepBeginObserver.observe(&notifyLightSleep);\n        trackerMotionLightSleepEndObserver.observe(&notifyLightSleepEnd);\n        motionLightSleepObserversInstalled = true;\n    }\n\n    if (vehicleMotionThread == nullptr)\n        vehicleMotionThread = new HeltecTrackerV11VehicleMotionThread();\n}\n""",
    "install GPIO7 light-sleep observers",
)

# ---------------------------------------------------------------------------
# USB serial/debugging: keep the Tracker CPU out of generic light sleep while
# USB is present. Do this in lsIdle BEFORE doLightSleep(), not with a permanent
# preflight veto (waitEnterSleep would otherwise time out/assert after 30 s).
# ---------------------------------------------------------------------------
power_fsm = replace_once(
    power_fsm,
    """static bool trackerOwnsInteractiveOutputs()\n{\n#if defined(HELTEC_TRACKER_V1_1)\n    return config.device.role == meshtastic_Config_DeviceConfig_Role_TAK ||\n           config.device.role == meshtastic_Config_DeviceConfig_Role_TAK_TRACKER;\n#else\n    return false;\n#endif\n}\n""",
    """static bool trackerOwnsInteractiveOutputs()\n{\n#if defined(HELTEC_TRACKER_V1_1)\n    return config.device.role == meshtastic_Config_DeviceConfig_Role_TAK ||\n           config.device.role == meshtastic_Config_DeviceConfig_Role_TAK_TRACKER;\n#else\n    return false;\n#endif\n}\n\nstatic bool trackerUsbKeepsCpuAwake()\n{\n#if defined(HELTEC_TRACKER_V1_1)\n    return trackerOwnsInteractiveOutputs() && powerStatus && powerStatus->getHasUSB();\n#else\n    return false;\n#endif\n}\n""",
    "Tracker USB awake helper",
)

power_fsm = replace_once(
    power_fsm,
    """    if (secsSlept < config.power.ls_secs) {\n        // If some other service would stall sleep, don't let sleep happen yet\n        if (doPreflightSleep()) {\n""",
    """    if (secsSlept < config.power.ls_secs) {\n        // Native USB CDC on the Tracker V1.1 can disappear across light sleep.\n        // While USB is connected stay fully awake so serial logging/flashing\n        // remains stable; this does not change autonomous battery operation.\n        if (trackerUsbKeepsCpuAwake()) {\n            delay(100);\n            return;\n        }\n\n        // If some other service would stall sleep, don't let sleep happen yet\n        if (doPreflightSleep()) {\n""",
    "keep Tracker out of light sleep on USB",
)

POLICY_PATH.write_text(policy)
MOTION_PATH.write_text(motion)
POWER_FSM_PATH.write_text(power_fsm)
NIMBLE_H_PATH.write_text(nimble_h)
NIMBLE_CPP_PATH.write_text(nimble_cpp)
