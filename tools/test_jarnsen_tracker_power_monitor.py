#!/usr/bin/env python3
"""Exercise the production INA226 and sleep accounting with a register-level I2C fake."""

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class TrackerPowerMonitorTest(unittest.TestCase):
    def test_measurement_and_sleep_recovery(self):
        compiler = shutil.which("g++") or shutil.which("clang++")
        if not compiler:
            self.skipTest("Host C++ compiler unavailable")
        stubs = {
            "Arduino.h": """#pragma once
#include <cstdint>
#include <cstddef>
extern uint32_t nowMs;
inline uint32_t millis(){return nowMs;}
constexpr unsigned SDA=45,SCL=5;
""",
            "DebugConfiguration.h": """#pragma once
template<typename... T> void discardLog(T...) {}
#define LOG_INFO(...) discardLog(__VA_ARGS__)
#define LOG_WARN(...) discardLog(__VA_ARGS__)
""",
            "PowerStatus.h": """#pragma once
struct PowerStatus {
 bool battery=true,usb=false,charging=false;
 int voltage=3900; unsigned percent=70;
 bool getHasBattery(){return battery;}
 bool getHasUSB(){return usb;}
 bool getIsCharging(){return charging;}
 int getBatteryVoltageMv(){return voltage;}
 unsigned getBatteryChargePercent(){return percent;}
};
extern PowerStatus *powerStatus;
""",
            "Preferences.h": """#pragma once
#include <cstdint>
#include <cstring>
#include <map>
#include <string>
#include <vector>
struct Preferences {
 inline static std::map<std::string,uint32_t> legacy;
 inline static std::vector<uint8_t> blob;
 inline static bool failWrite=false;
 inline static unsigned writes=0;
 bool begin(const char*,bool){return true;}
 void end(){}
 uint8_t getUChar(const char*,uint8_t v){return v;}
 uint16_t getUShort(const char*,uint16_t v){return v;}
 uint32_t getULong(const char* k,uint32_t v){return legacy.count(k)?legacy[k]:v;}
 size_t getBytesLength(const char*){return blob.size();}
 size_t getBytes(const char*,void* out,size_t n){n=std::min(n,blob.size());memcpy(out,blob.data(),n);return n;}
 size_t putBytes(const char*,const void* in,size_t n){
  ++writes;if(failWrite)return 0;
  const auto *p=static_cast<const uint8_t*>(in);blob.assign(p,p+n);return n;
 }
 void putUChar(const char*,uint8_t){}
 void putUShort(const char*,uint16_t){}
 void putULong(const char*,uint32_t){}
};
""",
            "esp_attr.h": "#pragma once\n#define RTC_DATA_ATTR\n",
            "esp_sleep.h": """#pragma once
enum esp_sleep_wakeup_cause_t {
 ESP_SLEEP_WAKEUP_UNDEFINED,ESP_SLEEP_WAKEUP_TIMER,
 ESP_SLEEP_WAKEUP_EXT0,ESP_SLEEP_WAKEUP_EXT1,ESP_SLEEP_WAKEUP_GPIO
};
extern esp_sleep_wakeup_cause_t wakeStub;
inline auto esp_sleep_get_wakeup_cause(){return wakeStub;}
""",
            "esp_timer.h": """#pragma once
#include <cstdint>
extern int64_t nowUs;
inline int64_t esp_timer_get_time(){return nowUs;}
""",
            "gps/RTC.h": """#pragma once
#include <cstdint>
constexpr int RTCQualityDevice=1;
extern uint32_t epoch;
inline uint32_t getValidTime(int){return epoch;}
""",
            "vehicle/TrackerDiagnosticLog.h": """#pragma once
template<typename... T> void trackerDiagLog(T...) {}
""",
            "Wire.h": """#pragma once
#include <cstdint>
#include <vector>
struct FakeWire {
 uint16_t registers[256]{};
 std::vector<uint8_t> tx;
 uint8_t address=0,reg=0; unsigned readIndex=0;
 bool fail=false;
 void beginTransmission(uint8_t a){address=a;tx.clear();}
 void write(uint8_t value){tx.push_back(value);}
 int endTransmission(bool=true){
  if(fail || address!=0x44)return 2;
  if(!tx.empty())reg=tx[0];
  if(tx.size()==3)registers[reg]=(uint16_t(tx[1])<<8)|tx[2];
  return 0;
 }
 unsigned requestFrom(uint8_t a,uint8_t){readIndex=0;return !fail && a==0x44 ? 2:0;}
 int read(){return readIndex++==0 ? registers[reg]>>8 : registers[reg]&255;}
};
extern FakeWire Wire;
""",
        }
        harness = r"""
#include <cassert>
#include <cstring>
#include "Arduino.h"
#include "PowerStatus.h"
#include "Wire.h"
#include "esp_sleep.h"
uint32_t nowMs=100,epoch=1000;
int64_t nowUs=100000;
esp_sleep_wakeup_cause_t wakeStub=ESP_SLEEP_WAKEUP_TIMER;
PowerStatus status; PowerStatus *powerStatus=&status;
FakeWire Wire;
bool enabled=false;
bool trackerIna226Enabled(){return enabled;}
#include "mesh/Throttle.h"
bool Throttle::isWithinTimespanMs(uint32_t at,uint32_t span){return uint32_t(nowMs-at)<span;}
#include "vehicle/TrackerPowerMonitor.cpp"

void validRegisters(int16_t current=0,uint16_t bus=3120) {
 Wire.registers[0xFE]=0x5449;Wire.registers[0xFF]=0x2260;
 Wire.registers[5]=2048;Wire.registers[6]=8;
 Wire.registers[2]=bus;Wire.registers[4]=uint16_t(current);
}
int main() {
 trackerPowerMonitorInit();
 // Duration is independent of sensor configuration, availability and polarity.
 trackerPowerMonitorPrepareForLightSleep();
 nowUs+=123000000;trackerPowerMonitorCompleteLightSleep(123000);
 assert(lightSleepMs==123000 && inaSleepUaMs==0);
 trackerPowerMonitorCompleteLightSleep(123000);assert(lightSleepMs==123000);
 trackerPowerMonitorPrepareForLightSleep();
 nowUs+=10000000;trackerPowerMonitorCompleteLightSleep(0);
 assert(lightSleepMs==123000); // Rejected sleep must not count preparation time.
 enabled=true;validRegisters();inaAddress=0x44;inaPresent=true;inaProbeComplete=true;
 for(int16_t raw : {int16_t(0),int16_t(-20),int16_t(40)}) {
  validRegisters(raw,0);trackerPowerMonitorPrepareForLightSleep();
  nowUs+=1000000;trackerPowerMonitorCompleteLightSleep(1000);
 }
 assert(lightSleepMs==126000);
 assert(inaSleepUaMs==1000000 && inaSleepUwMs==0); // Current works without VBUS.
 // Stale conversion / wrong calibration / signed current / I2C failure.
 validRegisters(400);nowMs+=1000;assert(sampleIna(nowMs));
 assert(inaCurrentUa==10000 && inaBusVoltageMv==3900);
 nowMs+=1000;assert(sampleIna(nowMs));assert(inaDischargeUaMs==10000000);
 Wire.registers[6]=0;nowMs+=1000;assert(!sampleIna(nowMs));
 assert(inaPresent && !inaSampleValid);
 auto snapshot=trackerPowerMonitorStats();
 assert(!snapshot.inaValid && snapshot.currentMicroAmps==0 && snapshot.inaBusVoltageMv==0);
 validRegisters(-400);nowMs+=1000;assert(sampleIna(nowMs));assert(inaCurrentUa==-10000);
 assert(inaDischargeUaMs==10000000);
 Wire.registers[5]=0;nowMs+=1000;assert(!sampleIna(nowMs));
 assert(!inaPresent && inaLastCalibration==0);
 inaPresent=true;validRegisters();Wire.fail=true;nowMs+=1000;
 assert(!sampleIna(nowMs) && !inaPresent);Wire.fail=false;
 // Both deep-sleep timer and EXT1 button/motion wakes count without INA.
 enabled=false;
 trackerPowerMonitorPrepareForDeepSleep(3600);wakeStub=ESP_SLEEP_WAKEUP_TIMER;
 recoverDeepSleepShot();assert(deepSleepMs==3600000 && !deepSleepIntervalPending);
 trackerPowerMonitorPrepareForDeepSleep(3600);epoch+=90;wakeStub=ESP_SLEEP_WAKEUP_EXT1;
 recoverDeepSleepShot();assert(deepSleepMs==3690000);
 epoch=0;trackerPowerMonitorPrepareForDeepSleep(3600);epoch=100;wakeStub=ESP_SLEEP_WAKEUP_EXT1;
 recoverDeepSleepShot();assert(deepSleepMs==3690000); // Unknown duration isn't invented.
 epoch=1000;trackerPowerMonitorPrepareForDeepSleep(3600);wakeStub=ESP_SLEEP_WAKEUP_UNDEFINED;
 recoverDeepSleepShot();assert(deepSleepMs==3690000); // Power reset isn't timer wake.
 // Startup says WAIT until a probe has actually completed.
 enabled=true;inaProbeComplete=false;inaPresent=false;
 assert(!strcmp(trackerPowerInaState(trackerPowerMonitorStats()),"WAIT"));
 inaProbeComplete=true;assert(!strcmp(trackerPowerInaState(trackerPowerMonitorStats()),"MISSING"));
 // An old voltage-based estimate must not hide an unavailable INA current.
 dischargeRateMilliPercentPerHour=10000;
 assert(!trackerPowerMonitorStats().estimateReady);
 enabled=false;assert(trackerPowerMonitorStats().estimateReady);
 status.voltage=0;assert(!trackerPowerMonitorStats().batteryValid);
 // 32-bit millisecond wrap does not break INA sampling throttles.
 enabled=true;inaPresent=true;validRegisters(400);lastInaSampleMs=UINT32_MAX-100;
 nowMs=50;inaSampleValid=true;assert(sampleIna(nowMs));
 nowMs=149;assert(sampleIna(nowMs));assert(lastInaSampleMs==149);
 // Legacy migration, atomic save/readback, failed writes, and corrupt-record fallback.
 Preferences::blob.clear();Preferences::legacy["lightSlpS"]=321;
 checkpointKnown=false;loadPersistentTotals();assert(lightSleepMs==321000);
 lightSleepMs=9876000;inaSleepUaMs=3600000ULL*12345;
 savePersistentTotals();const auto good=Preferences::blob;
 assert(good.size()==sizeof(PowerCheckpoint));
 lightSleepMs=0;inaSleepUaMs=0;loadPersistentTotals();
 assert(lightSleepMs==9876000 && sleepEstimatedUah()==12345);
 auto writes=Preferences::writes;savePersistentTotals();assert(Preferences::writes==writes);
 Preferences::failWrite=true;lightSleepMs+=1000;savePersistentTotals();
 assert(Preferences::blob==good);Preferences::failWrite=false;
 lightSleepMs=0;loadPersistentTotals();assert(lightSleepMs==9876000);
 Preferences::blob[8]^=1;loadPersistentTotals();assert(lightSleepMs==321000);
 Preferences::blob=good;loadPersistentTotals();
 // Wall-clock checkpoints happen while moving and immediately after long light sleep.
 enabled=false;lastPersistMs=100;nowMs=100+PERSIST_INTERVAL_MS;
 lastTickMs=nowMs-1000;writes=Preferences::writes;
 trackerPowerMonitorTick(true,false,false,false,false);
 assert(Preferences::writes==writes+1);
 trackerPowerMonitorPrepareForLightSleep();writes=Preferences::writes;
 nowMs+=3600000;nowUs+=3600000000LL;
 trackerPowerMonitorCompleteLightSleep(3600000);
 assert(Preferences::writes==writes+1);
 auto savedLight=lightSleepMs;lightSleepMs=0;loadPersistentTotals();assert(lightSleepMs==savedLight);
 lastPersistMs=UINT32_MAX-100;nowMs=50;writes=Preferences::writes;
 maybePersistTotals();assert(Preferences::writes==writes);
}
"""
        with tempfile.TemporaryDirectory() as directory:
            temp = Path(directory)
            for name, content in stubs.items():
                target = temp / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(content)
            cpp = temp / "power.cpp"
            cpp.write_text(harness)
            binary = temp / "power"
            subprocess.run(
                [
                    compiler,
                    "-std=c++17",
                    "-Wall",
                    "-Wextra",
                    "-Werror",
                    "-fsanitize=undefined",
                    "-DHELTEC_TRACKER_V1_1",
                    "-I" + str(temp),
                    "-I" + str(ROOT / "src"),
                    str(cpp),
                    "-o",
                    str(binary),
                ],
                check=True,
            )
            subprocess.run([str(binary)], check=True)


if __name__ == "__main__":
    unittest.main()
