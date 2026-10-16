#!/usr/bin/env python3
"""Regression tests: disk recovery may only remove current-scope SCons caches."""

import tempfile
from pathlib import Path
from unittest.mock import patch

import jarnsen_runner_disk_preflight as disk


def main():
    # Regression for Build 446: a double-escaped shell continuation caused
    # argparse to receive neither --cache-root nor --scope.
    runner = (
        Path(__file__).resolve().parent.parent
        / ".buildkite"
        / "run-unified-build-daily.sh"
    ).read_text(encoding="utf-8")
    expected = (
        "python3 tools/jarnsen_runner_disk_preflight.py "
        '--cache-root "$JARNSEN_CACHE_ROOT" --scope "$JARNSEN_CACHE_SCOPE"'
    )
    assert expected in runner, "disk preflight flags must be on the command line"
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "jarnsen-unified"
        target = root / "build-cache" / "Jarnsen_firmware-fix_branch"
        target.mkdir(parents=True)
        (target / "old.o").write_bytes(b"cache")
        unrelated = root / "build-cache" / "another_branch"
        unrelated.mkdir(parents=True)
        (unrelated / "keep.o").write_bytes(b"keep")
        toolchain = root / "platformio-core" / "packages"
        toolchain.mkdir(parents=True)
        (toolchain / "keep.txt").write_text("tools")
        board_libdeps = (
            root
            / "workspaces"
            / "Jarnsen_firmware-fix_branch"
            / "heltec-v3"
            / "libdeps"
        )
        board_libdeps.mkdir(parents=True)
        (board_libdeps / "keep.txt").write_text("deps")
        gib = 1024**3
        with patch.object(disk, "free_bytes", side_effect=[2 * gib, 6 * gib]):
            assert disk.check(root, "Jarnsen_firmware-fix_branch", 8, 5)
        assert not target.exists()
        assert (unrelated / "keep.o").exists()
        assert (toolchain / "keep.txt").exists()
        assert (board_libdeps / "keep.txt").exists()
        # Recovered free space still too small: abort before 20-minute link.
        target.mkdir()
        with patch.object(disk, "free_bytes", side_effect=[2 * gib, 3 * gib]):
            assert not disk.check(root, "Jarnsen_firmware-fix_branch", 8, 5)
        assert not target.exists()
        # Sufficient free disk must never prune any board caches.
        target.mkdir()
        with patch.object(disk, "free_bytes", side_effect=[9 * gib, 9 * gib]):
            assert disk.check(root, "Jarnsen_firmware-fix_branch", 8, 5)
        assert target.exists()
        try:
            disk.check(root, "../other_branch", 8, 5)
        except ValueError:
            pass
        else:
            raise AssertionError("unsafe scope was accepted")
    print("JARNSEN disk preflight tests OK")


if __name__ == "__main__":
    main()
