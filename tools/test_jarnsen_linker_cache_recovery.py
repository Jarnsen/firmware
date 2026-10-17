#!/usr/bin/env python3
"""Verify shell recovery classification for corrupted Xtensa SCons cache.

Extract only the standalone classifier function from the runner script,
so this test does not invoke PlatformIO or clean any real cache.
"""

from pathlib import Path
from shutil import which
from subprocess import run
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / ".buildkite" / "run-unified-build-daily.sh"


def classifier() -> str:
    source = SCRIPT.read_text(encoding="utf-8")
    prefix = "is_stale_linker_cache_failure() {"
    suffix = "\n}\n\nrecover_stale_linker_cache()"
    start = source.index(prefix)
    finish = source.index(suffix, start) + len("\n}")
    return source[start:finish]


def classify(log: str) -> bool:
    with TemporaryDirectory() as tmp:
        file = Path(tmp) / "compiler.log"
        file.write_text(log, encoding="utf-8")
        code = (
            'set -e\nLOG_FILE="$1"\n'
            + classifier()
            + "\nis_stale_linker_cache_failure\n"
        )
        bash = which("bash")
        if not bash:
            raise RuntimeError("bash is required for the shell classifier test")
        result = run(
            [bash, "-c", code, "bash", str(file)],
            check=False,
            capture_output=True,
            text=True,
        )
        return result.returncode == 0


def main() -> None:
    corrupted_cache = (
        "Generating project linker script sections.ld\n"
        "xtensa-esp-elf-objdump: cxx_exception_stubs.cpp.o: file format not recognized\n"
        "Traceback: ldgen.py failed\n"
    )
    assert classify(corrupted_cache), "corrupt libcxx.a archive must trigger retry"
    assert classify(
        "memory.ld:123: undefined symbol _heap_low_start referenced in expression\n"
    )
    assert not classify("src/main.cpp:13: error: invalid conversion\n")
    assert not classify(
        "xtensa-esp-elf-objdump: some.o: file format not recognized\n"
    ), "objdump errors outside ldgen linker stage must not trigger cache recovery"
    print("JARNSEN linker-cache recovery tests OK")


if __name__ == "__main__":
    main()
