#pragma once
#include "BluetoothCommon.h"
#include "jarnsen/core/bluetooth/JarnsenBluetoothPolicy.h"

class NimbleBluetooth : BluetoothApi, public jarnsen::bluetooth::Backend
{
  public:
    void setup();
    void shutdown();
    void suspend() override;
    void resume() override;
    void deinit() override;
    void clearBonds();
    bool isActive() override;
    bool isConnected() override;
    uint32_t getMeaningfulTrafficCount();
    int getRssi();
    void sendLog(const uint8_t *logMessage, size_t length);
    void startAdvertising();
    bool isDeInit = false;

  private:
    void setupService();
};

void setBluetoothEnable(bool enable);

// ESP32/NimBLE adapter for the hardware-neutral Unified Core lifecycle.
// Callers only request a service window. This adapter owns the bootstrap
// distinction between "no NimBLE instance yet" and an already initialized
// backend, then delegates steady-state ACTIVE/SUSPENDED/UNAVAILABLE behavior
// to the Core policy.
inline jarnsen::bluetooth::Lifecycle applyNimbleBluetoothLifecycle(
    NimbleBluetooth *&backend, const jarnsen::EffectiveCapabilities &caps, bool serviceRequested)
{
    const auto desired = jarnsen::bluetooth::desiredLifecycle(caps, serviceRequested);

    if (desired == jarnsen::bluetooth::Lifecycle::ACTIVE && (!backend || !backend->isActive())) {
        setBluetoothEnable(true);
    }

    if (backend)
        return jarnsen::bluetooth::applyLifecycle(*backend, caps, serviceRequested);

    // No backend exists yet. For SUSPENDED/UNAVAILABLE there is nothing to
    // suspend or deinitialize; explicitly keep the platform radio disabled.
    if (desired != jarnsen::bluetooth::Lifecycle::ACTIVE)
        setBluetoothEnable(false);

    return desired;
}
