#!/usr/bin/env python3
"""Compile the real generic logger against a bounded in-memory filesystem.

Hardware/status/policy services are stubs; storage policy, file rotation, export
state machines and CRC generation are production code. No board is accessed.
"""

import re
import shutil
import subprocess
import tempfile
import unittest
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STUBS = {
    "Arduino.h": r"""
#pragma once
#include <cstddef>
#include <cstdint>
#include <string>
extern uint32_t testMs;
inline uint32_t millis() { return testMs; }
inline void delay(unsigned ms) { testMs += ms; }
inline void yield() {}
class Print {
public:
 std::string bytes;
 bool blocked=false;
 size_t write(const uint8_t *p,size_t n) {
  if(blocked)return 0;
  bytes.append(reinterpret_cast<const char *>(p),n);return n;
 }
};
""",
    "FSCommon.h": r"""
#pragma once
#include <algorithm>
#include <cstring>
#include <map>
#include <memory>
#include <string>
#define FILE_O_READ 0
#define FILE_O_WRITE 1
struct File {
 std::shared_ptr<std::string> bytes;
 size_t offset=0;
 explicit operator bool() const {return bool(bytes);}
 size_t size() const {return bytes ? bytes->size():0;}
 size_t read(uint8_t *out,size_t n) {
  if(!bytes)return 0;
  n=std::min(n,bytes->size()-std::min(offset,bytes->size()));
  std::memcpy(out,bytes->data()+offset,n);offset+=n;return n;
 }
 size_t write(const uint8_t *in,size_t n) {
  if(!bytes)return 0;
  bytes->append(reinterpret_cast<const char *>(in),n);return n;
 }
 bool seek(size_t p) {if(!bytes || p>bytes->size())return false;offset=p;return true;}
 void flush() {}
 void close() {bytes.reset();}
};
struct TestFS {
 std::map<std::string,std::shared_ptr<std::string>> files;
 unsigned removes=0,renames=0;
 size_t total=256*1024,other=0;
 size_t totalBytes() const {return total;}
 size_t usedBytes() const {size_t n=other;for(const auto &f:files)n+=f.second->size();return n;}
 bool exists(const char *p) const {return files.count(p);}
 File open(const char *p,int mode) {
  auto i=files.find(p);
  if(i==files.end()) {
   if(mode==FILE_O_READ)return {};
   i=files.emplace(p,std::make_shared<std::string>()).first;
  }
  return {i->second,mode==FILE_O_READ?0:i->second->size()};
 }
 File open(const char *p,const char *) {return open(p,FILE_O_WRITE);}
 bool remove(const char *p) {++removes;return files.erase(p)!=0;}
 bool rename(const char *a,const char *b) {
  ++renames;auto i=files.find(a);if(i==files.end() || exists(b))return false;
  files.emplace(b,i->second);files.erase(i);return true;
 }
 std::string data(const char *p) const {auto i=files.find(p);return i==files.end()?std::string():*i->second;}
};
extern TestFS testFs;
#define FSCom testFs
""",
    "NodeDB.h": r"""
#pragma once
#include <cstdint>
struct NodeDB {uint32_t getNodeNum() {return 0x12345678;}};
extern NodeDB *nodeDB;
struct Owner {char long_name[40]="Host node",short_name[8]="HN";};
extern Owner owner;
""",
    "PowerStatus.h": r"""
#pragma once
namespace meshtastic {enum OptionalBool {OptFalse,OptTrue,OptUnknown};}
struct TestPower {
 bool isInitialized() {return false;}
 meshtastic::OptionalBool getHasBatteryState() {return meshtastic::OptUnknown;}
 meshtastic::OptionalBool getHasUSBState() {return meshtastic::OptUnknown;}
 meshtastic::OptionalBool getIsChargingState() {return meshtastic::OptUnknown;}
 int getBatteryVoltageMv() {return 4000;}
 unsigned getBatteryChargePercent() {return 75;}
};
extern TestPower *powerStatus;
""",
    "configuration.h": r"""
#pragma once
struct TestConfig {bool has_lora=true;struct {unsigned region=3,hop_limit=3;float override_frequency=869.525;} lora;};
extern TestConfig config;
""",
}
HARNESS = r"""
#include "FSCommon.h"
#include "NodeDB.h"
#include "PowerStatus.h"
#include "configuration.h"
#include "jarnsen/core/service/JarnsenDiagnosticLog.h"
#include "jarnsen/core/service/JarnsenDiagnosticPolicy.h"
#include "jarnsen/core/service/JarnsenDiagnosticStorage.h"
#include "jarnsen/core/power/JarnsenBatteryLearning.h"
#include "jarnsen/core/runtime/JarnsenTakRepeaterPolicy.h"
#include <cassert>
#include <cstdio>
#include <iostream>
uint32_t testMs=100;
TestFS testFs;
NodeDB *nodeDB=nullptr;
Owner owner;
TestPower *powerStatus=nullptr;
TestConfig config;
bool writing=false;
bool Throttle::isWithinTimespanMs(uint32_t then,uint32_t interval) {return uint32_t(testMs-then)<interval;}
namespace jarnsen {
void diagnosticPolicyInit() {}
const char *diagnosticRoleKey() {return "tak_repeater";}
bool diagnosticConsoleLevelEnabled(const char *) {return true;}
bool diagnosticTryWrite() {if(writing)return false;writing=true;return true;}
bool diagnosticWaitForWrite() {return diagnosticTryWrite();}
void diagnosticEndWrite() {assert(writing);writing=false;}
bool diagnosticFormatLine(char *out,size_t n,const char *event,const char *detail) {
 const int bytes=snprintf(out,n,"%u | %s | %s",testMs,event,detail?detail:"");
 return bytes>0 && size_t(bytes)<n;
}
void diagnosticNoteWrite(bool) {}
void diagnosticNoteTruncation() {}
void diagnosticNoteRotation(size_t) {}
void diagnosticQueueEvent(const char *,const char *,...) {}
bool diagnosticSnapshotMetadata(char *out,size_t n,const char *,size_t,const char *,size_t) {
 return snprintf(out,n,"# snapshot=host\r\n")>0;
}
BatteryLearningStats batteryLearningStats() {return {};}
void batteryLearningFormatDuration(uint32_t,char *out,size_t n) {snprintf(out,n,"unknown");}
bool takRepeaterRoleActive() {return false;}
TakRepeaterStats takRepeaterStats() {return {};}
const char *takRepeaterPositionModeKey(TakRepeaterPositionMode) {return "none";}
}
using namespace jarnsen;
constexpr const char *CURRENT="/jarnsen_diag.log",*PREVIOUS="/jarnsen_diag.prev.log";
std::string allLogs() {return testFs.data(PREVIOUS)+testFs.data(CURRENT);}
void flood(unsigned n=2000) {
 const std::string payload(240,'x');
 for(unsigned i=0;i<n;++i)diagnosticLog("FILL","%u %s",i,payload.c_str());
}
std::string readHttp() {
 std::string output;
 uint8_t bytes[137];
 for(unsigned i=0;i<10000;++i) {
  size_t n=diagnosticLogReadWebExport(bytes,sizeof(bytes));
  if(!n)return output;
  output.append(reinterpret_cast<char *>(bytes),n);
 }
 assert(false);return {};
}
int main(int argc,char **argv) {
 assert(argc==2);
 std::string mode=argv[1];
 diagnosticLogInit();
 diagnosticLog("TEST","before snapshot");
 if(mode=="http") {
  flood();
  assert(testFs.renames>0);
  const auto expected=allLogs();
  const auto current=testFs.data(CURRENT),previous=testFs.data(PREVIOUS);
  assert(diagnosticLogStartWebExport());
  assert(!diagnosticLogStartWebExport());
  Print usb;diagnosticLogRequestUsbExport(usb);
  assert(!diagnosticLogUsbExportPending());
  diagnosticLogClear();assert(allLogs()==expected);
  const auto removes=testFs.removes,renames=testFs.renames;
  flood();
  assert(testFs.removes==removes && testFs.renames==renames);
  assert(testFs.data(PREVIOUS)==previous);
  assert(testFs.data(CURRENT).compare(0,current.size(),current)==0);
  auto cap=diagnosticStorageLimits(testFs.totalBytes(),testFs.usedBytes(),diagnosticLogSize());
  assert(diagnosticLogSize()<=cap.budget);
  assert(testFs.data(CURRENT).size()<=cap.perFile);
  assert(testFs.totalBytes()-testFs.usedBytes()>=cap.reserve);
  std::string output=readHttp();
  auto headerEnd=output.find("# bytes=");assert(headerEnd!=std::string::npos);
  auto payloadStart=output.find("\r\n",headerEnd)+2;
  assert(output.substr(payloadStart,expected.size())==expected);
  assert(output.find("# transfer_complete=1")!=std::string::npos);
  assert(diagnosticLogStartWebExport());diagnosticLogCancelWebExport();
  diagnosticLogClear();assert(diagnosticLogSize()==0);
  std::cout<<output;
 } else if(mode=="timeout") {
  assert(diagnosticLogStartWebExport());
  testMs+=DIAGNOSTIC_EXPORT_IDLE_MS+1;
  uint8_t byte;
  assert(diagnosticLogReadWebExport(&byte,1)==0);
  assert(diagnosticLogStartWebExport());
  testMs+=DIAGNOSTIC_EXPORT_IDLE_MS+1;
  diagnosticLogPumpUsbExport();
  assert(diagnosticLogStartWebExport());
  diagnosticLogCancelWebExport();
  // Progress prevents idle expiry, but cannot extend the absolute limit.
  flood();assert(diagnosticLogStartWebExport());
  for(unsigned i=0;i<23;++i) {
   testMs+=50000;
   assert(diagnosticLogReadWebExport(&byte,1)==1);
  }
  testMs+=50001;
  assert(diagnosticLogReadWebExport(&byte,1)==0);
  assert(diagnosticLogStartWebExport());diagnosticLogCancelWebExport();
  Print usb;diagnosticLogRequestUsbExport(usb);assert(diagnosticLogUsbExportPending());
  assert(!diagnosticLogStartWebExport());
  auto before=allLogs();diagnosticLogClear();assert(allLogs()==before);
  testMs+=DIAGNOSTIC_EXPORT_IDLE_MS+1;diagnosticLogPumpUsbExport();
  assert(!diagnosticLogUsbExportPending());
  assert(std::string(diagnosticLogUsbExportStatusText())=="FEHLER");
  diagnosticLogClear();assert(diagnosticLogSize()==0);
 } else if(mode=="usb") {
  flood();auto expected=allLogs();Print usb;
  diagnosticLogRequestUsbExport(usb);testMs+=751;
  for(unsigned i=0;i<10000 && diagnosticLogUsbExportPending();++i)diagnosticLogPumpUsbExport();
  assert(!diagnosticLogUsbExportPending());
  assert(std::string(diagnosticLogUsbExportStatusText())=="FERTIG");
  assert(diagnosticLogUsbExportProgress()==100);
  auto payloadStart=usb.bytes.find("\r\n",usb.bytes.find("# bytes="))+2;
  assert(usb.bytes.substr(payloadStart,expected.size())==expected);
  std::cout<<usb.bytes;
 } else if(mode=="pressure") {
  flood();
  testFs.other=64*1024;
  const auto removals=testFs.removes;
  testMs+=30001;
  flood();
  const auto cap=diagnosticStorageLimits(testFs.totalBytes(),testFs.usedBytes(),diagnosticLogSize());
  assert(testFs.removes>removals);
  assert(diagnosticLogSize()<=cap.budget);
  assert(testFs.totalBytes()-testFs.usedBytes()>=cap.reserve);
  assert(testFs.other==64*1024);
 } else if(mode=="blocked-usb") {
  Print usb;usb.blocked=true;diagnosticLogRequestUsbExport(usb);testMs+=751;
  diagnosticLogPumpUsbExport();
  assert(!diagnosticLogUsbExportPending());
  assert(std::string(diagnosticLogUsbExportStatusText())=="FEHLER");
  assert(usb.bytes.empty());
  assert(diagnosticLogStartWebExport());diagnosticLogCancelWebExport();
 } else if(mode=="missing-space") {
  diagnosticLogClear();testFs.total=0;
  diagnosticLog("TEST","must not write without measurement");
  assert(diagnosticLogSize()==0);
 } else {assert(false);}
}
"""


class RealLoggerStorageTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        compiler = shutil.which("g++") or shutil.which("clang++")
        if not compiler:
            raise unittest.SkipTest("Host C++ compiler unavailable")
        cls.directory = tempfile.TemporaryDirectory()
        temp = Path(cls.directory.name)
        for name, content in STUBS.items():
            target = temp / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content)
        harness = temp / "integration.cpp"
        harness.write_text(HARNESS)
        cls.binary = temp / "logger"
        subprocess.run(
            [
                compiler,
                "-std=c++17",
                "-Wall",
                "-Wextra",
                "-Werror",
                "-I" + str(temp),
                "-I" + str(ROOT / "src"),
                str(ROOT / "src/jarnsen/core/service/JarnsenDiagnosticLog.cpp"),
                str(harness),
                "-o",
                str(cls.binary),
            ],
            check=True,
        )

    @classmethod
    def tearDownClass(cls):
        cls.directory.cleanup()

    def run_case(self, mode):
        return subprocess.run(
            [str(self.binary), mode], check=True, capture_output=True
        ).stdout

    def assert_export_crc(self, data):
        count_match = re.search(rb"# bytes=(\d+)\r\n", data)
        self.assertIsNotNone(count_match)
        count = int(count_match.group(1))
        payload = data[count_match.end() : count_match.end() + count]
        self.assertEqual(len(payload), count)
        footer = data[count_match.end() + count :]
        self.assertIn(b"# transfer_complete=1", footer)
        self.assertIn(f"# payload_sent={count}\r\n".encode(), footer)
        self.assertIn(f"# crc32={zlib.crc32(payload):08x}\r\n".encode(), footer)

    def test_http_crc_rotation_pin_cap_and_clear_exclusion(self):
        self.assert_export_crc(self.run_case("http"))

    def test_usb_real_state_machine_and_crc(self):
        self.assert_export_crc(self.run_case("usb"))

    def test_idle_absolute_timeout_and_usb_http_exclusion(self):
        self.run_case("timeout")

    def test_budget_adapts_when_other_files_grow(self):
        self.run_case("pressure")

    def test_stalled_usb_writer_releases_snapshot(self):
        self.run_case("blocked-usb")

    def test_unknown_storage_does_not_write(self):
        self.run_case("missing-space")


if __name__ == "__main__":
    unittest.main()
