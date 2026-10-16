#!/usr/bin/env python3
"""Guard self-hosted Unified Core builds against exhausted runner storage.

Only disposable SCons object caches inside the CURRENT branch's scoped
JARNSEN build-cache are pruned. Keep PlatformIO core/toolchains, libdeps,
NVS, build outputs and all unrelated scopes intact.
"""

import argparse
import re
import shutil
import sys
from pathlib import Path


def free_bytes(path: Path) -> int:
    return shutil.disk_usage(path).free


def check(
    cache_root: Path, scope: str, min_free_gib: int, resume_free_gib: int
) -> bool:
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", scope) or scope in (".", ".."):
        raise ValueError("invalid current build-cache scope")
    if not cache_root.is_dir() or cache_root.is_symlink():
        raise ValueError("cache root must exist and not be a symlink")
    scoped_cache = cache_root / "build-cache" / scope
    min_free = min_free_gib * 1024**3
    resume_free = resume_free_gib * 1024**3
    before = free_bytes(cache_root)
    print(
        f"JARNSEN_DISK: available_before={before // (1024**2)}MiB "
        f"cleanup_threshold={min_free_gib}GiB minimum_compile={resume_free_gib}GiB",
        flush=True,
    )
    if before < min_free:
        # On this branch jobs are serialized: Tracker and then V3.
        # SCons' restored .o archive cache can be recreated by compilation.
        # DO NOT delete PlatformIO installed packages or board libdeps.
        if scoped_cache.is_dir() and not scoped_cache.is_symlink():
            print(
                f"JARNSEN_DISK: removing disposable current-scope object cache {scoped_cache}",
                flush=True,
            )
            shutil.rmtree(scoped_cache)
        elif scoped_cache.is_symlink():
            raise ValueError("refusing to prune symlinked object cache")
    after = free_bytes(cache_root)
    print(
        f"JARNSEN_DISK: available_after={after // (1024**2)}MiB "
        f"reclaimed={(after - before) // (1024**2)}MiB",
        flush=True,
    )
    if after < resume_free:
        print(
            "JARNSEN_DISK: FAIL: not enough free space for ESP32 link. "
            "Increase Linux VM disk or inspect remaining filesystem use; "
            "PlatformIO core and libdeps were preserved.",
            file=sys.stderr,
            flush=True,
        )
        return False
    return True


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cache-root", type=Path, required=True)
    parser.add_argument("--scope", required=True)
    parser.add_argument("--min-free-gib", type=int, default=8)
    parser.add_argument("--resume-free-gib", type=int, default=5)
    args = parser.parse_args()
    if args.min_free_gib < args.resume_free_gib or args.resume_free_gib < 1:
        parser.error("require min-free-gib >= resume-free-gib >= 1")
    try:
        return (
            0
            if check(
                args.cache_root, args.scope, args.min_free_gib, args.resume_free_gib
            )
            else 73
        )
    except (OSError, ValueError) as exc:
        print(f"JARNSEN_DISK: ERROR: {exc}", file=sys.stderr)
        return 73


if __name__ == "__main__":
    sys.exit(main())
