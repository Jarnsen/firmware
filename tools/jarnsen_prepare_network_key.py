#!/usr/bin/env python3
"""Build-time injection of the existing TAK Netz 26 master AES-256 key.

Requires the protected JARNSEN_TAK_NET_26_PSK_HEX GitHub Actions secret.
The value is never printed, placed in a command argument or committed.
A wrong/missing key MUST stop the firmware build, never silently create a
different network or fall back to the public Meshtastic channel.
"""

from __future__ import annotations

import hashlib
import os
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "src/jarnsen/core/mesh/JarnsenNetworkKey.generated.h"
ENV_NAME = "JARNSEN_TAK_NET_26_PSK_HEX"
EXPECTED_SHA256 = "03d48375a4553f77f274941033d745211abd7e88cfe3f03141a20747906eb6dc"


def main() -> int:
    # Never allow a stale generated key from an earlier run to be reused.
    OUTPUT.unlink(missing_ok=True)
    raw = os.environ.get(ENV_NAME, "")
    if not re.fullmatch(r"[0-9a-fA-F]{64}", raw):
        raise SystemExit(
            f"TAK Netz 26: {ENV_NAME} absent or invalid; supply exactly "
            "64 hexadecimal characters in the protected repository secret. "
            "Refusing to build an unconfigured firmware."
        )
    key = bytes.fromhex(raw)
    if hashlib.sha256(key).hexdigest() != EXPECTED_SHA256:
        raise SystemExit(
            "TAK Netz 26: protected master key does not match the approved "
            "existing channel. Refusing to create an incompatible firmware."
        )
    words = [f"0x{byte:02x}" for byte in key]
    lines = [", ".join(words[i : i + 8]) for i in range(0, 32, 8)]
    payload = (
        "#pragma once\n"
        "// Generated locally at build time from a protected GitHub secret.\n"
        "// Never commit this file, publish it as source, or log its contents.\n"
        "#include <stdint.h>\n"
        "namespace jarnsen {\n"
        "constexpr uint8_t TAK_NETWORK_PRIMARY_PSK[32] = {\n"
        + ",\n".join("    " + line for line in lines)
        + "\n};\n"
        "static_assert(sizeof(TAK_NETWORK_PRIMARY_PSK) == 32U, "
        "\"TAK Netz 26 requires an AES-256 primary key\");\n"
        "} // namespace jarnsen\n"
    )
    OUTPUT.write_text(payload, encoding="utf-8")
    try:
        OUTPUT.chmod(0o600)
    except OSError:
        pass
    print("TAK Netz 26 master key: valid fingerprint, generated protected build header")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
