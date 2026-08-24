#pragma once
#include "BluetoothCommon.h"

class NimbleBluetooth : BluetoothApi {
public:
  void setup();
  void shutdown();
  void deinit();
  void clearBonds();
  bool isActive();
  bool isConnected();
  uint32_t getMeaningfulTrafficCount();
  int getRssi();
  void sendLog(const uint8_t *logMessage, size_t length);
  void startAdvertising();
  void stopAdvertisingForService();
  bool isAdvertisingSuppressed();
  bool isAdvertisingActive();
  bool isDeInit = false;

private:
  void setupService();
};

void setBluetoothEnable(bool enable);