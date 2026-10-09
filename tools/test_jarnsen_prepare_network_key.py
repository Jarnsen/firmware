#!/usr/bin/env python3
"""No-real-secret tests for fail-closed master-key firmware generation."""

from __future__ import annotations

import contextlib
import hashlib
import importlib.util
import io
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

SOURCE = Path(__file__).resolve().parent / "jarnsen_prepare_network_key.py"
spec = importlib.util.spec_from_file_location("jarnsen_prepare_network_key", SOURCE)
assert spec is not None and spec.loader is not None
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


def expect_refused(value: str | None, generated: Path) -> None:
    generated.write_text("STALE KEY MUST BE REMOVED", encoding="utf-8")
    env = {mod.ENV_NAME: value} if value is not None else {}
    with patch.dict(os.environ, env, clear=True), contextlib.redirect_stdout(io.StringIO()):
        try:
            mod.main()
        except SystemExit:
            pass
        else:
            raise AssertionError("Missing/invalid TAK Netz 26 key was accepted")
    assert not generated.exists(), "Failed build left a reusable stale private header"


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="jarnsen-key-check-") as root:
        generated = Path(root) / "JarnsenNetworkKey.generated.h"
        mod.OUTPUT = generated
        expect_refused(None, generated)
        expect_refused("deadbeef", generated)
        expect_refused("z" * 64, generated)
        expect_refused("00" * 32, generated)

        # Exercise the successful generation path with a synthetic key ONLY.
        fixture_key = bytes(range(32))
        mod.EXPECTED_SHA256 = hashlib.sha256(fixture_key).hexdigest()
        capture = io.StringIO()
        with patch.dict(os.environ, {mod.ENV_NAME: fixture_key.hex()}, clear=True):
            with contextlib.redirect_stdout(capture):
                assert mod.main() == 0
        header = generated.read_text(encoding="utf-8")
        assert "TAK_NETWORK_PRIMARY_PSK[32]" in header
        assert all(f"0x{b:02x}" in header for b in fixture_key)
        assert fixture_key.hex() not in capture.getvalue(), "CI logs exposed the raw key"
        assert "0x00" not in capture.getvalue(), "CI logs exposed secret bytes"
        assert not (Path(__file__).resolve().parents[1] /
                    "src/jarnsen/core/mesh/JarnsenNetworkKey.generated.h").exists(), (
            "Secret fixture unexpectedly generated in tracked source directory"
        )
    print("TAK Netz 26 build-key regression: missing/wrong keys rejected, synthetic injection passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
