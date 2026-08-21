from pathlib import Path

P = Path('src/vehicle/HeltecTrackerV11TakLeaderPolicy.cpp')
s = P.read_text()


def rep(old: str, new: str, label: str) -> None:
    global s
    if new in s:
        print(f'{label}: already applied')
        return
    if old not in s:
        raise SystemExit(f'{label}: anchor not found')
    s = s.replace(old, new, 1)
    print(f'{label}: applied')


rep(
    '#ifndef TAK_LEADER_SERVICE_MAX_MS\n#define TAK_LEADER_SERVICE_MAX_MS (15UL * 60UL * 1000UL)\n#endif\n',
    '#ifndef TAK_LEADER_SERVICE_MAX_MS\n#define TAK_LEADER_SERVICE_MAX_MS (15UL * 60UL * 1000UL)\n#endif\n'
    '#ifndef TAK_LEADER_SERVICE_ACTIVITY_WINDOW_MS\n#define TAK_LEADER_SERVICE_ACTIVITY_WINDOW_MS (10UL * 1000UL)\n#endif\n'
    '#ifndef TAK_LEADER_SERVICE_ACTIVITY_THRESHOLD\n#define TAK_LEADER_SERVICE_ACTIVITY_THRESHOLD 3U\n#endif\n',
    'TAK BLE burst constants',
)

rep(
    'static bool leaderBootHandoffComplete = false;\nstatic volatile uint32_t leaderPendingBleActivityMs = 0;\nstatic uint32_t leaderServiceStartedMs = 0;\n',
    'static bool leaderBootHandoffComplete = false;\n'
    'static uint32_t leaderBleTrafficLast = 0;\n'
    'static uint32_t leaderBleActivityWindowStartedMs = 0;\n'
    'static uint8_t leaderBleActivityWindowCount = 0;\n'
    'static uint32_t leaderServiceStartedMs = 0;\n',
    'TAK BLE burst state',
)

rep(
    'static bool leaderMotionWakeDisabledForStuckLow = false;\nstatic uint32_t leaderLastPositionHeartbeatEpoch = 0;\n',
    'static bool leaderMotionWakeDisabledForStuckLow = false;\n'
    'static bool leaderMotionLightSleepPrepared = false;\n'
    'static bool leaderMotionLightSleepWakeArmed = false;\n'
    'static bool leaderMotionLightSleepObserversInstalled = false;\n'
    'static uint32_t leaderLastPositionHeartbeatEpoch = 0;\n',
    'TAK motion light-sleep state',
)

rep(
    '''void takLeaderBleActivity()\n{\n    leaderPendingBleActivityMs = millis() ? millis() : 1;\n}\n''',
    '''void takLeaderBleActivity()\n{\n    // Compatibility hook. Service lifetime is driven by the meaningful BLE\n    // payload counter, not every callback or passive connection activity.\n}\n''',
    'disable raw TAK BLE activity refresh',
)

rep(
    '''static void setTakLeaderScreenPower(bool on)\n{\n    if (screen)\n        screen->setOn(on);\n}\n''',
    '''static uint32_t takLeaderBleMeaningfulTrafficCount()\n{\n#if defined(ARCH_ESP32) && !defined(CONFIG_IDF_TARGET_ESP32S2) && !MESHTASTIC_EXCLUDE_BLUETOOTH\n    return nimbleBluetooth ? nimbleBluetooth->getMeaningfulTrafficCount() : 0U;\n#else\n    return 0U;\n#endif\n}\n\nstatic void setTakLeaderScreenPower(bool on)\n{\n    if (screen)\n        screen->setOn(on);\n}\n''',
    'TAK meaningful BLE accessor',
)

rep(
    '''    leaderServiceStartedMs = now;\n    leaderServiceLastActivityMs = now;\n    leaderServicePage = TAK_PAGE_STATUS;\n\n    // GPIO0 always opens a temporary local BLE service window regardless of\n''',
    '''    leaderServiceStartedMs = now;\n    leaderServiceLastActivityMs = now;\n    leaderServicePage = TAK_PAGE_STATUS;\n    leaderBleActivityWindowStartedMs = 0;\n    leaderBleActivityWindowCount = 0;\n\n    // GPIO0 always opens a temporary local BLE service window regardless of\n''',
    'reset TAK BLE burst window',
)

rep(
    '''    setTakLeaderBluetooth(true);\n    renderTakLeaderServicePage();\n    LOG_INFO("TAK leader: GPIO0 opened ATAK/Bluetooth/settings; %us idle timeout, %us hard cap",\n             (unsigned)(TAK_LEADER_SERVICE_MS / 1000UL), (unsigned)(TAK_LEADER_SERVICE_MAX_MS / 1000UL));\n''',
    '''    setTakLeaderBluetooth(true);\n    leaderBleTrafficLast = takLeaderBleMeaningfulTrafficCount();\n    renderTakLeaderServicePage();\n    LOG_INFO("TAK leader: GPIO0 opened ATAK/Bluetooth/settings; %us idle, activity=%u/%us, %us hard cap",\n             (unsigned)(TAK_LEADER_SERVICE_MS / 1000UL),\n             (unsigned)TAK_LEADER_SERVICE_ACTIVITY_THRESHOLD,\n             (unsigned)(TAK_LEADER_SERVICE_ACTIVITY_WINDOW_MS / 1000UL),\n             (unsigned)(TAK_LEADER_SERVICE_MAX_MS / 1000UL));\n''',
    'initialize TAK meaningful BLE counter',
)

rep(
    '''            leaderMotionWakeDisabledForStuckLow = true;\n            gpio_wakeup_disable(motionPin);\n            LOG_WARN("TAK leader: GPIO%d LOW for %us; light-sleep motion wake temporarily disabled",\n''',
    '''            leaderMotionWakeDisabledForStuckLow = true;\n            LOG_WARN("TAK leader: GPIO%d LOW for %us; light-sleep motion wake temporarily disabled",\n''',
    'do not alter GPIO interrupt type on TAK stuck-low detection',
)

rep(
    '''        if (leaderMotionWakeDisabledForStuckLow) {\n            leaderMotionWakeDisabledForStuckLow = false;\n            gpio_wakeup_enable(motionPin, GPIO_INTR_LOW_LEVEL);\n            LOG_INFO("TAK leader: GPIO%d recovered HIGH; light-sleep motion wake restored", VEHICLE_MOTION_WAKE_PIN);\n        }\n''',
    '''        if (leaderMotionWakeDisabledForStuckLow) {\n            leaderMotionWakeDisabledForStuckLow = false;\n            LOG_INFO("TAK leader: GPIO%d recovered HIGH; light-sleep motion wake available", VEHICLE_MOTION_WAKE_PIN);\n        }\n''',
    'restore TAK wake only during sleep preparation',
)

rep(
    '''        const uint32_t pendingBleActivity = leaderPendingBleActivityMs;\n        if (pendingBleActivity != 0) {\n            leaderPendingBleActivityMs = 0;\n            if (leaderServiceActive)\n                leaderServiceLastActivityMs = now;\n        }\n\n        if (leaderServiceActive) {\n''',
    '''        // Same policy as the V3 service: only a burst of meaningful GATT\n        // payload traffic counts as active app use. Passive connections, empty\n        // polling reads, duplicate writes and isolated heartbeat packets do not\n        // keep the 120 s service window alive.\n        const uint32_t trafficNow = takLeaderBleMeaningfulTrafficCount();\n        if (trafficNow < leaderBleTrafficLast) {\n            leaderBleTrafficLast = trafficNow;\n            leaderBleActivityWindowStartedMs = 0;\n            leaderBleActivityWindowCount = 0;\n        } else if (trafficNow > leaderBleTrafficLast) {\n            uint32_t delta = trafficNow - leaderBleTrafficLast;\n            leaderBleTrafficLast = trafficNow;\n\n            if (leaderBleActivityWindowStartedMs == 0 ||\n                (uint32_t)(now - leaderBleActivityWindowStartedMs) > TAK_LEADER_SERVICE_ACTIVITY_WINDOW_MS) {\n                leaderBleActivityWindowStartedMs = now ? now : 1;\n                leaderBleActivityWindowCount = 0;\n            }\n            if (delta > (uint32_t)TAK_LEADER_SERVICE_ACTIVITY_THRESHOLD)\n                delta = (uint32_t)TAK_LEADER_SERVICE_ACTIVITY_THRESHOLD;\n            const uint32_t count = (uint32_t)leaderBleActivityWindowCount + delta;\n            leaderBleActivityWindowCount = count > (uint32_t)TAK_LEADER_SERVICE_ACTIVITY_THRESHOLD\n                                               ? (uint8_t)TAK_LEADER_SERVICE_ACTIVITY_THRESHOLD\n                                               : (uint8_t)count;\n\n            if (leaderServiceActive &&\n                leaderBleActivityWindowCount >= (uint8_t)TAK_LEADER_SERVICE_ACTIVITY_THRESHOLD) {\n                leaderServiceLastActivityMs = now;\n                LOG_DEBUG("TAK leader: active BLE burst detected; 120s idle timer reset");\n                leaderBleActivityWindowStartedMs = now ? now : 1;\n                leaderBleActivityWindowCount = 0;\n            }\n        }\n\n        if (leaderServiceActive) {\n''',
    'TAK 3-in-10s meaningful BLE detector',
)

# Safe GPIO7 ownership around light sleep. gpio_wakeup_enable() changes the
# normal interrupt type, so detach FALLING before arming level wake and restore
# FALLING immediately after wake.
insert_anchor = '''class TakLeaderSleepVeto : public Observer<void *>\n{\n'''
insert_code = '''class TakLeaderMotionLightSleepBeginObserver : public Observer<void *>\n{\n  protected:\n    int onNotify(void *) override\n    {\n        if (!takLeaderEnabled())\n            return 0;\n\n        const gpio_num_t pin = (gpio_num_t)VEHICLE_MOTION_WAKE_PIN;\n        detachInterrupt(digitalPinToInterrupt(VEHICLE_MOTION_WAKE_PIN));\n        leaderMotionLightSleepPrepared = true;\n        leaderMotionLightSleepWakeArmed = false;\n        gpio_wakeup_disable(pin);\n        pinMode(VEHICLE_MOTION_WAKE_PIN, INPUT_PULLUP);\n\n        if (!leaderMotionWakeDisabledForStuckLow && digitalRead(VEHICLE_MOTION_WAKE_PIN) != LOW) {\n            const esp_err_t err = gpio_wakeup_enable(pin, GPIO_INTR_LOW_LEVEL);\n            if (err == ESP_OK)\n                leaderMotionLightSleepWakeArmed = true;\n            else\n                LOG_ERROR("TAK leader: failed to arm GPIO%d light-sleep motion wake: %d",\n                          VEHICLE_MOTION_WAKE_PIN, (int)err);\n        }\n        return 0;\n    }\n};\n\nclass TakLeaderMotionLightSleepEndObserver : public Observer<esp_sleep_wakeup_cause_t>\n{\n  protected:\n    int onNotify(esp_sleep_wakeup_cause_t cause) override\n    {\n        if (!leaderMotionLightSleepPrepared)\n            return 0;\n\n        const gpio_num_t pin = (gpio_num_t)VEHICLE_MOTION_WAKE_PIN;\n        if (leaderMotionLightSleepWakeArmed)\n            gpio_wakeup_disable(pin);\n        pinMode(VEHICLE_MOTION_WAKE_PIN, INPUT_PULLUP);\n\n        if (cause == ESP_SLEEP_WAKEUP_GPIO && leaderMotionLightSleepWakeArmed &&\n            digitalRead(VEHICLE_MOTION_WAKE_PIN) == LOW)\n            leaderMotionEdgeSequence++;\n\n        attachInterrupt(digitalPinToInterrupt(VEHICLE_MOTION_WAKE_PIN), takLeaderMotionISR, FALLING);\n        leaderMotionLightSleepPrepared = false;\n        leaderMotionLightSleepWakeArmed = false;\n        return 0;\n    }\n};\n\nstatic TakLeaderMotionLightSleepBeginObserver takLeaderMotionLightSleepBeginObserver;\nstatic TakLeaderMotionLightSleepEndObserver takLeaderMotionLightSleepEndObserver;\n\nclass TakLeaderSleepVeto : public Observer<void *>\n{\n'''
rep(insert_anchor, insert_code, 'safe TAK GPIO7 light-sleep observers')

rep(
    '''    pinMode(VEHICLE_MOTION_WAKE_PIN, INPUT_PULLUP);\n    leaderProcessedMotionEdgeSequence = leaderMotionEdgeSequence;\n    leaderMotionLevelWasLow = digitalRead(VEHICLE_MOTION_WAKE_PIN) == LOW;\n    attachInterrupt(digitalPinToInterrupt(VEHICLE_MOTION_WAKE_PIN), takLeaderMotionISR, FALLING);\n    gpio_wakeup_enable((gpio_num_t)VEHICLE_MOTION_WAKE_PIN, GPIO_INTR_LOW_LEVEL);\n\n    takLeaderSleepVeto = new TakLeaderSleepVeto();\n''',
    '''    pinMode(VEHICLE_MOTION_WAKE_PIN, INPUT_PULLUP);\n    leaderProcessedMotionEdgeSequence = leaderMotionEdgeSequence;\n    leaderMotionLevelWasLow = digitalRead(VEHICLE_MOTION_WAKE_PIN) == LOW;\n    attachInterrupt(digitalPinToInterrupt(VEHICLE_MOTION_WAKE_PIN), takLeaderMotionISR, FALLING);\n\n    if (!leaderMotionLightSleepObserversInstalled) {\n        takLeaderMotionLightSleepBeginObserver.observe(&notifyLightSleep);\n        takLeaderMotionLightSleepEndObserver.observe(&notifyLightSleepEnd);\n        leaderMotionLightSleepObserversInstalled = true;\n    }\n\n    takLeaderSleepVeto = new TakLeaderSleepVeto();\n''',
    'install TAK motion light-sleep observers',
)

P.write_text(s)
