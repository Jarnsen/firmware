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
        rotation = LOGGER.split("void rotateIfNeeded(", 1)[1].split(
            "void appendLine(", 1
        )[0]
        harness = r"""
#include <cassert>
#include <cstddef>
constexpr const char *CURRENT_LOG="current", *PREVIOUS_LOG="previous";
constexpr size_t MAX_LOG_BYTES=100;
bool snapshotLocked=false, previousExists=true;
bool spiLockHeld=true;
size_t currentBytes=99;
int lockAttempts=0, removes=0, renames=0;
void diagnosticNoteWrite(bool) {}
void diagnosticNoteRotation(size_t) {}
struct MockFS {
 bool exists(const char *path) { return path==CURRENT_LOG || previousExists; }
 bool remove(const char *path) { assert(path==PREVIOUS_LOG);++removes;return true; }
 bool rename(const char *from,const char *to) {
  assert(from==CURRENT_LOG && to==PREVIOUS_LOG);++renames;return true;
 }
} FSCom;
size_t fileSize(const char *path) {
 if(path==CURRENT_LOG)return currentBytes;
 assert(path==PREVIOUS_LOG);return previousExists ? 50 : 0;
}
bool renameFile(const char *from,const char *to) {
 ++lockAttempts;
 if(spiLockHeld) return false; // Real binary semaphore would wait forever here.
 return FSCom.rename(from,to);
}
"""
        harness += "\nvoid rotateIfNeeded(" + rotation
        harness += r"""
int main() {
 rotateIfNeeded(2); // Full log while a filesystem/SPI caller owns the lock.
 assert(lockAttempts==0 && removes==1 && renames==1);
 removes=renames=0;
 snapshotLocked=true;rotateIfNeeded(2);
 assert(removes==0 && renames==0);
 snapshotLocked=false;currentBytes=90;rotateIfNeeded(10);
 assert(removes==0 && renames==0);
 currentBytes=100;previousExists=false;rotateIfNeeded(1);
 assert(lockAttempts==0 && removes==0 && renames==1);
}
"""
        with tempfile.TemporaryDirectory() as directory:
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
                    str(cpp),
                    "-o",
                    str(binary),
                ],
                check=True,
            )
            subprocess.run([str(binary)], check=True)


if __name__ == "__main__":
    unittest.main()
