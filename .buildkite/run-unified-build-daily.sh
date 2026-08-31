#!/usr/bin/env bash
set -euo pipefail

: "${JARNSEN_VERSION:?JARNSEN_VERSION is required}"

EXPECTED_VERSION="$(python3 tools/jarnsen_version.py)"
if [[ "$EXPECTED_VERSION" != "$JARNSEN_VERSION" ]]; then
  echo "Version mismatch: pipeline=$JARNSEN_VERSION source=$EXPECTED_VERSION" >&2
  exit 1
fi

python3 - "$JARNSEN_VERSION" <<'PY'
from pathlib import Path
import re
import sys

version = sys.argv[1]
path = Path("src/jarnsen/core/build/JarnsenBuildInfo.h")
text = path.read_text(encoding="utf-8")
updated, count = re.subn(
    r'#define JARNSEN_FIRMWARE_SEMVER "[^"]+"',
    f'#define JARNSEN_FIRMWARE_SEMVER "{version}"',
    text,
    count=1,
)
if count != 1:
    raise SystemExit("Could not inject resolved version into JarnsenBuildInfo.h")
path.write_text(updated, encoding="utf-8")
PY

exec bash .buildkite/run-unified-build.sh
