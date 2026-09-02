#!/usr/bin/env bash
set -euo pipefail

# Keep the self-hosted runner's system Git config from affecting ESP-IDF dependency fetches.
if [[ "${GITHUB_ACTIONS:-}" == "true" ]]; then
  export GIT_CONFIG_SYSTEM=/dev/null
fi

resolve_version() {
  if command -v node >/dev/null 2>&1; then
    node tools/jarnsen_version.mjs
  elif command -v python3 >/dev/null 2>&1; then
    python3 tools/jarnsen_version.py
  else
    echo "Neither node nor python3 is available for version resolution" >&2
    return 1
  fi
}

if [[ -z "${JARNSEN_VERSION:-}" ]]; then
  JARNSEN_VERSION="$(resolve_version)"
  export JARNSEN_VERSION
fi

EXPECTED_VERSION="$(resolve_version)"
if [[ "$EXPECTED_VERSION" != "$JARNSEN_VERSION" ]]; then
  echo "Version mismatch: pipeline=$JARNSEN_VERSION source=$EXPECTED_VERSION" >&2
  exit 1
fi

printf 'Resolved JARN-MESH version for %s: %s\n' "${JARNSEN_BOARD_NAME:-board}" "$JARNSEN_VERSION"

if command -v node >/dev/null 2>&1; then
  node - "$JARNSEN_VERSION" <<'NODE'
const fs = require("node:fs");
const version = process.argv[2];
const path = "src/jarnsen/core/build/JarnsenBuildInfo.h";
const text = fs.readFileSync(path, "utf8");
const pattern = /#define JARNSEN_FIRMWARE_SEMVER "[^"]+"/;
if (!pattern.test(text)) {
  console.error("Could not inject resolved version into JarnsenBuildInfo.h");
  process.exit(1);
}
fs.writeFileSync(path, text.replace(pattern, `#define JARNSEN_FIRMWARE_SEMVER "${version}"`));
NODE
else
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
fi

exec bash .buildkite/run-unified-build.sh
