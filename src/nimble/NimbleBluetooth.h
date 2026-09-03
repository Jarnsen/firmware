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
// The Core selects the desired state, while this adapter preserves the proven
// Meshtastic bootstrap/resume behavior used before the Unified-Core migration.
// A stopped/inactive backend is started only through setBluetoothEnable(true);
// resume() is reserved for an already active backend. Calling both during one
// transition can race NimBLE setup and leave advertising unavailable at runtime.
inline jarnsen::bluetooth::Lifecycle applyNimbleBluetoothLifecycle(
    NimbleBluetooth *&backend, const jarnsen::EffectiveCapabilities &caps, bool serviceRequested)
{
    const auto desired = jarnsen::bluetooth::desiredLifecycle(caps, serviceRequested);

    switch (desired) {
    case jarnsen::bluetooth::Lifecycle::ACTIVE:
        if (!backend || !backend->isActive())
            setBluetoothEnable(true);
        else
            backend->resume();
        break;

    case jarnsen::bluetooth::Lifecycle::SUSPENDED:
        if (backend && backend->isActive())
            backend->suspend();
        break;

    case jarnsen::bluetooth::Lifecycle::UNAVAILABLE:
    default:
        if (backend)
            backend->deinit();
        else
            setBluetoothEnable(false);
        break;
    }

    return desired;
}
