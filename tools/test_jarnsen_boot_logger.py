#!/usr/bin/env python3
"""Regress boot-time filesystem logging and non-recursive SPI lock reentry."""

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOGGER = (ROOT / "src/jarnsen/core/service/JarnsenDiagnosticLog.cpp").read_text()


class BootLoggerTest(unittest.TestCase):
    def test_persistent_logger_starts_after_filesystem(self):
        console = (ROOT / "src/SerialConsole.cpp").read_text()
        constructor = console.split("SerialConsole::SerialConsole()", 1)[1].split(
            "int32_t SerialConsole::runOnce()", 1
        )[0]
        self.assertNotIn("jarnsen::diagnosticLogInit();", constructor)
        main = (ROOT / "src/main.cpp").read_text().split("void setup()", 1)[1]
        self.assertLess(
            main.index("fsInit();"), main.index("jarnsen::diagnosticLogInit();")
        )

    def test_rotation_while_spi_lock_is_already_held(self):
        compiler = shutil.which("g++") or shutil.which("clang++")
        if not compiler:
            self.skipTest(
                "Host C++ compiler unavailable; firmware build still required"
            )
        rotation = LOGGER.split("bool rotateIfNeeded(", 1)[1].split(
            "void formatStorage(", 1
        )[0]
        harness = r"""
#include <cassert>
#include <cstddef>
#include <cstdint>
uint32_t millis(){return 100;}
#include "jarnsen/core/service/JarnsenDiagnosticStorage.h"
bool Throttle::isWithinTimespanMs(uint32_t,uint32_t){return true;}
constexpr const char *CURRENT_LOG="current", *PREVIOUS_LOG="previous";
constexpr size_t CAP=384*1024;
jarnsen::DiagnosticLogStorage logStorage;
bool snapshotLocked=false, previousExists=true;
bool spiLockHeld=true;
size_t currentBytes=CAP-1,previousBytes=50;
int lockAttempts=0, removes=0, renames=0;
void diagnosticNoteWrite(bool) {}
void diagnosticNoteRotation(size_t) {}
struct MockFS {
 size_t totalBytes(){return 1024*1024;}
 size_t usedBytes(){return currentBytes+(previousExists?previousBytes:0);}
 bool exists(const char *path) { return path==CURRENT_LOG ? currentBytes!=0 : previousExists; }
 bool remove(const char *path) { assert(path==PREVIOUS_LOG);++removes;previousExists=false;return true; }
 bool rename(const char *from,const char *to) {
  assert(from==CURRENT_LOG && to==PREVIOUS_LOG);++renames;
  previousBytes=currentBytes;previousExists=true;currentBytes=0;return true;
 }
} FSCom;
size_t fileSize(const char *path) {
 if(path==CURRENT_LOG)return currentBytes;
 assert(path==PREVIOUS_LOG);return previousExists ? previousBytes : 0;
}
size_t storageFileSize(const char *path) {return fileSize(path);}
bool renameFile(const char *from,const char *to) {
 ++lockAttempts;
 if(spiLockHeld) return false; // Real binary semaphore would wait forever here.
 return FSCom.rename(from,to);
}
"""
        harness += "\nbool rotateIfNeeded(" + rotation
        harness += r"""
int main() {
 rotateIfNeeded(2); // Full log while a filesystem/SPI caller owns the lock.
 assert(lockAttempts==0 && removes==1 && renames==1);
 removes=renames=0;
 snapshotLocked=true;currentBytes=CAP;logStorage.invalidate();rotateIfNeeded(2);
 assert(removes==0 && renames==0);
 snapshotLocked=false;currentBytes=90;logStorage.invalidate();rotateIfNeeded(10);
 assert(removes==0 && renames==0);
 currentBytes=CAP;previousExists=false;logStorage.invalidate();rotateIfNeeded(1);
 assert(lockAttempts==0 && removes==0 && renames==1);
}
"""
        with tempfile.TemporaryDirectory() as directory:
            (Path(directory) / "Arduino.h").write_text(
                "#pragma once\n#include <cstdint>\nuint32_t millis();\n"
            )
            cpp = Path(directory) / "rotation.cpp"
            binary = Path(directory) / "rotation"
            cpp.write_text(harness)
            subprocess.run(
                [
                    compiler,
                    "-std=c++17",
                    "-Wall",
                    "-Wextra",
                    "-Werror",
                    "-I" + directory,
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
