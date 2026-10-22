#!/usr/bin/env python3
"""Run the real shared diagnostic policy and position cache with host hardware stubs."""

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STUBS = {
    "memGet.h": r"""
#pragma once
struct MemGet { unsigned getFreeHeap() { return 23456; } };
inline MemGet memGet;
""",
    "Arduino.h": r"""
#pragma once
#include <cstddef>
#include <cstdint>
extern uint32_t testMs, testEpoch;
extern bool testIsr;
inline uint32_t millis() { return testMs; }
inline void delay(unsigned ms) { testMs += ms; }
inline long random(long, long) { return 12345; }
inline unsigned readResetReason() { return 4; }
inline int xPortInIsrContext() { return testIsr ? 1 : 0; }
inline size_t xPortGetFreeHeapSize() { return 23456; }
#define pdTRUE 1
#define RTC_DATA_ATTR
class Print {};
struct EspStub { uint32_t getFreeHeap() { return 23456; } };
inline EspStub ESP;
""",
    "configuration.h": r"""
#pragma once
struct TestConfig { struct { bool is_power_saving=true; unsigned ls_secs=300; unsigned device_battery_ina_address=0; } power; struct {unsigned role=12;} device; };
extern TestConfig config;
""",
    "PowerStatus.h": r"""
#pragma once
struct TestPower {
 int getHasUSBState() { return 0; }
 int getHasBatteryState() { return 1; }
 int getIsChargingState() { return 0; }
 const char *getBatteryVoltageSource() { return "adc"; }
 int getBatteryVoltageMv() { return 4000; }
 int getBatteryChargePercent() { return 75; }
};
extern TestPower *powerStatus;
""",
    "BluetoothStatus.h": r"""
#pragma once
struct TestBluetooth { unsigned getConnectionState() { return 0; } };
extern TestBluetooth *bluetoothStatus;
""",
    "GPSStatus.h": r"""
#pragma once
struct TestGps { bool getIsConnected() { return true; } bool getHasLock() { return true; } };
extern TestGps *gpsStatus;
""",
    "RadioLibInterface.h": r"""
#pragma once
struct RadioLibInterface {
 inline static RadioLibInterface *instance=nullptr;
 unsigned rxGood=0, txGood=0, txRelay=0;
};
""",
    "gps/RTC.h": r"""
#pragma once
#include "Arduino.h"
enum { RTCQualityDevice };
inline uint32_t getValidTime(int) { return testEpoch; }
""",
    "esp_sleep.h": r"""
#pragma once
#include <cstdint>
enum esp_sleep_wakeup_cause_t { ESP_SLEEP_WAKEUP_UNDEFINED, ESP_SLEEP_WAKEUP_EXT0,
 ESP_SLEEP_WAKEUP_EXT1, ESP_SLEEP_WAKEUP_TIMER, ESP_SLEEP_WAKEUP_TOUCHPAD, ESP_SLEEP_WAKEUP_GPIO };
extern esp_sleep_wakeup_cause_t testWake;
inline esp_sleep_wakeup_cause_t esp_sleep_get_wakeup_cause() { return testWake; }
inline uint64_t esp_sleep_get_ext1_wakeup_status() { return 0; }
""",
    "esp_system.h": r"""
#pragma once
enum { ESP_RST_POWERON=1, ESP_RST_PANIC=4, ESP_RST_DEEPSLEEP=8 };
extern int testReset;
inline int esp_reset_reason() { return testReset; }
inline unsigned esp_random() { return 0x12345678U; }
""",
    "jarnsen/core/status/JarnsenStatusProvider.h": r"""
#pragma once
#include "jarnsen/core/roles/JarnsenDeviceRole.h"
namespace jarnsen {
extern DeviceRole testRole;
inline DeviceRole activeDeviceRoleOr() { return testRole; }
}
""",
    "mesh/http/JarnsenServiceWeb.h": r"""
#pragma once
inline bool jarnsenServiceWebActive() { return false; }
""",
    "FSCommon.h": r"""
#pragma once
#include <algorithm>
#include <cstring>
#include <map>
#include <string>
struct File {
 std::string data;
 size_t offset=0;
 bool valid=false;
 explicit operator bool() const { return valid; }
 bool seek(size_t p) { if(p>data.size())return false;offset=p;return true; }
 size_t read(uint8_t *out,size_t n) {
  n=std::min(n,data.size()-offset);std::memcpy(out,data.data()+offset,n);offset+=n;return n;
 }
 void close() {}
};
struct TestFS {
 std::map<std::string,std::string> files;
 unsigned opens=0;
 File open(const char *path,int) {
  ++opens;
  auto i=files.find(path);if(i==files.end())return {};
  return {i->second,0,true};
 }
};
extern TestFS testFs;
#define FSCom testFs
#define FILE_O_READ 0
""",
}


class DiagnosticContractTest(unittest.TestCase):
    def test_real_policy_and_cache_on_esp_and_portable_paths(self):
        compiler = shutil.which("g++") or shutil.which("clang++")
        if not compiler:
            self.skipTest(
                "Host C++ compiler unavailable; board builds remain mandatory"
            )
        with tempfile.TemporaryDirectory() as directory:
            temp = Path(directory)
            for name, content in STUBS.items():
                target = temp / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(content)
            for arch in ("ARCH_ESP32", "ARCH_NRF52"):
                with self.subTest(arch=arch):
                    binary = temp / arch
                    subprocess.run(
                        [
                            compiler,
                            "-std=c++17",
                            "-Wall",
                            "-Wextra",
                            "-Werror",
                            "-D" + arch,
                            "-DHAS_FREE_RTOS",
                            "-I" + str(temp),
                            "-I" + str(ROOT / "src"),
                            "-I" + str(ROOT / "src/mesh"),
                            str(ROOT / "src/mesh/Throttle.cpp"),
                            str(
                                ROOT
                                / "src/jarnsen/core/service/JarnsenDiagnosticPolicy.cpp"
                            ),
                            str(
                                ROOT / "src/jarnsen/core/mesh/JarnsenNodeStateCache.cpp"
                            ),
                            str(ROOT / "tools/test_jarnsen_diagnostics.cpp"),
                            "-o",
                            str(binary),
                        ],
                        check=True,
                    )
                    subprocess.run([str(binary)], check=True)


if __name__ == "__main__":
    unittest.main()
