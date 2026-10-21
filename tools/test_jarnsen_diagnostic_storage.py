#!/usr/bin/env python3
"""Exercise the shared production budget/rotation with full and failing filesystems."""

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def definition(text, signature):
    start = text.index(signature)
    opening = text.index("{", start)
    depth, end = 1, opening + 1
    while depth:
        depth += (text[end] == "{") - (text[end] == "}")
        end += 1
    return text[start:end]


class DiagnosticStorageTest(unittest.TestCase):
    def compile_run(self, body):
        compiler = shutil.which("g++") or shutil.which("clang++")
        if not compiler:
            self.skipTest("Host C++ compiler unavailable")
        with tempfile.TemporaryDirectory() as directory:
            temp = Path(directory)
            (temp / "Arduino.h").write_text(
                "#pragma once\n#include <cstdint>\nuint32_t millis();\n"
            )
            cpp = temp / "storage.cpp"
            cpp.write_text(body)
            binary = temp / "storage"
            subprocess.run(
                [
                    compiler,
                    "-std=c++17",
                    "-Wall",
                    "-Wextra",
                    "-Werror",
                    "-pthread",
                    "-fsanitize=undefined",
                    "-I" + str(temp),
                    "-I" + str(ROOT / "src"),
                    str(cpp),
                    "-o",
                    str(binary),
                ],
                check=True,
            )
            subprocess.run([str(binary)], check=True, timeout=15)

    def test_measured_limits_rotation_and_pinned_exports(self):
        self.compile_run(r"""
#include <cassert>
#include <cstdint>
#include <cstring>
#include <map>
#include <string>
uint32_t nowMs=1;
uint32_t millis(){return nowMs;}
#include "jarnsen/core/service/JarnsenDiagnosticStorage.h"
bool Throttle::isWithinTimespanMs(uint32_t at,uint32_t span){return uint32_t(nowMs-at)<span;}
constexpr size_t K=1024;
struct FakeFS {
 size_t total=1532*K, other=128*K;
 std::map<std::string,size_t> files;
 bool removeFails=false,renameFails=false;
 size_t totalBytes(){return total;}
 size_t usedBytes(){size_t used=other;for(auto &f:files)used+=f.second;return used;}
 bool exists(const char *p){return files.count(p);}
 bool remove(const char *p){if(removeFails)return false;return files.erase(p);}
 bool rename(const char *a,const char *b){
  if(renameFails || !exists(a) || exists(b))return false;
  files[b]=files[a];files.erase(a);return true;
 }
} fs;
size_t fileSize(const char *p){return fs.exists(p)?fs.files[p]:0;}
bool append(jarnsen::DiagnosticLogStorage &storage,size_t bytes,bool pinned=false){
 if(!storage.prepare(fs,"cur","old",fileSize,bytes,pinned))return false;
 fs.files["cur"]+=bytes;storage.noteWritten(bytes,true);return true;
}
int main(){
 using namespace jarnsen;
 const auto empty=diagnosticStorageLimits(1532*K,128*K,0);
 const auto occupied=diagnosticStorageLimits(1532*K,428*K,300*K);
 assert(empty.measured && empty.budget==occupied.budget);
 assert(empty.reserve==383*K && empty.budget==1016*K && empty.perFile==508*K);
 assert(diagnosticStorageLimits(256*K,32*K,0).budget < empty.budget);
 assert(diagnosticStorageLimits(16*1024*K,0,0).budget==DIAGNOSTIC_STORAGE_MAX_BYTES);
 assert(!diagnosticStorageLimits(0,0,0).measured);
 assert(!diagnosticStorageLimits(1024,2048,0).measured);
 assert(diagnosticStorageLimits(8*K,0,0).budget==0);
 assert(diagnosticStorageLimits(SIZE_MAX,SIZE_MAX,0).budget==0);
 DiagnosticLogStorage storage;
 assert(append(storage,200));
 const auto budget=storage.limits().budget;
 const auto perFile=storage.limits().perFile;
 fs.files["cur"]=perFile;fs.files["old"]=perFile;
 storage.invalidate();
 const auto frozen=fs.files;
 assert(!append(storage,200,true));assert(fs.files==frozen); // Snapshot immutable at cap.
 assert(storage.skipped()==1);
 assert(append(storage,200));assert(storage.rotated() && storage.discarded()==perFile);
 assert(fs.files["old"]==perFile && fs.files["cur"]==200);
 for(unsigned i=0;i<10000;++i)assert(append(storage,320));
 assert(fileSize("cur")+fileSize("old")<=budget);
 // Other application data can force the log budget to shrink.
 fs.other=fs.total-fileSize("cur")-fileSize("old")-128*K;nowMs+=30000;
 assert(append(storage,200));
 assert(storage.limits().budget<budget && fileSize("cur")+fileSize("old")<=storage.limits().budget);
 assert(fs.totalBytes()-fs.usedBytes()>=storage.limits().reserve);
 // I/O failure must stop appending instead of defeating the limit.
 fs=FakeFS{};storage=DiagnosticLogStorage{};storage.measure(fs,0,0,true);
 fs.files["cur"]=storage.limits().perFile;fs.files["old"]=4096;fs.removeFails=true;
 const auto beforeRemove=fs.files;
 assert(!append(storage,100) && storage.ioError());assert(fs.files==beforeRemove);
 fs.removeFails=false;fs.renameFails=true;fs.files.erase("old");storage.invalidate();
 assert(!append(storage,100) && storage.ioError());assert(fs.files["cur"]>0);
 // Reserve / corrupt measurements / unsupported adapters fail closed.
 fs=FakeFS{};fs.other=fs.total;storage=DiagnosticLogStorage{};
 assert(!append(storage,100));assert(fs.files.empty());
 struct UnknownFS {bool exists(const char*){return false;}bool remove(const char*){return false;}
 bool rename(const char*,const char*){return false;}} unknown;
 DiagnosticLogStorage unsupported;
 assert(!unsupported.prepare(unknown,"cur","old",fileSize,100,false));
 fs=FakeFS{};fs.files["prefs"]=4096;fs.files["cur"]=100*K;fs.other=1400*K;
 storage=DiagnosticLogStorage{};assert(!append(storage,100));
 assert(fs.files.count("prefs") && !fs.files.count("cur"));
 fs=FakeFS{};storage=DiagnosticLogStorage{};
 assert(!append(storage,SIZE_MAX)); // Length can't wrap into a small write.
 char text[224]{};storage.format(text,sizeof(text));assert(strstr(text,"budget="));
 fs=FakeFS{};storage=DiagnosticLogStorage{};storage.measure(fs,0,0,true);
 storage.format(text,sizeof(text));
 assert(!strcmp(text,"measured=1 total=1568768 used=131072 free=1437696 reserve=392192 budget=1040384 per_file=520192 skipped=0"));
 fs.total=SIZE_MAX;fs.other=0;storage.measure(fs,0,0,true);storage.format(text,sizeof(text));
 assert(!strstr(text,"=lu") && strstr(text,"skipped=0"));
 char tiny[5];storage.format(tiny,sizeof(tiny));assert(tiny[4]=='\0');
 // Idle timeout and total lifetime are wrap-safe, independent of progress.
 nowMs=UINT32_MAX-100;uint32_t started=nowMs,progress=nowMs;
 nowMs=50;assert(!diagnosticExportExpired(started,progress));
 nowMs=started+DIAGNOSTIC_EXPORT_IDLE_MS;assert(diagnosticExportExpired(started,progress));
 nowMs=started+DIAGNOSTIC_EXPORT_MAX_MS;progress=nowMs;
 assert(diagnosticExportExpired(started,progress));
}
""")

    def test_export_waits_for_writer_without_false_eof(self):
        policy = (
            ROOT / "src/jarnsen/core/service/JarnsenDiagnosticPolicy.cpp"
        ).read_text()
        harness = r"""
#include <atomic>
#include <cassert>
#include <thread>
#include <cstdint>
#include "jarnsen/core/service/JarnsenDiagnosticPolicy.h"
std::atomic<unsigned> waits{0};
uint32_t millis(){return 1;}
void delay(unsigned){++waits;std::this_thread::yield();}
namespace jarnsen {
std::atomic<bool> ready{true};std::atomic<unsigned> dropped{0};
std::atomic_flag writeBusy=ATOMIC_FLAG_INIT;
bool isr=false;bool inInterrupt(){return isr;}
"""
        for signature in (
            "bool diagnosticTryWrite()",
            "void diagnosticEndWrite()",
            "bool diagnosticWaitForWrite()",
        ):
            harness += definition(policy, signature) + "\n"
        harness += r"""
}
int main(){
 using namespace jarnsen;
 assert(diagnosticTryWrite());
 std::atomic<bool> acquired{false};
 std::thread exportReader([&]{DiagnosticWriteScope scope(true);assert(scope);acquired=true;});
 while(!waits.load())std::this_thread::yield();
 assert(!acquired.load());diagnosticEndWrite();exportReader.join();assert(acquired.load());
 assert(diagnosticTryWrite());diagnosticEndWrite();
 isr=true;assert(!diagnosticWaitForWrite());isr=false;
 ready=false;assert(!diagnosticWaitForWrite());
}
"""
        self.compile_run(harness)


if __name__ == "__main__":
    unittest.main()
