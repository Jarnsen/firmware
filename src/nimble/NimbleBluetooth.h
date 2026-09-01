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
