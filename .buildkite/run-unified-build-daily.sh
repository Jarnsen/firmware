#!/usr/bin/env bash
set -euo pipefail

# Keep the self-hosted runner's system Git config from affecting ESP-IDF dependency fetches.
if [[ "${GITHUB_ACTIONS:-}" == "true" ]]; then
  export GIT_CONFIG_SYSTEM=/dev/null
fi

# ESP-IDF Component Manager creates bare repositories outside the checked-out
# workspace, so the repository-local auth header installed by actions/checkout
# is not visible to those git processes.  The runner currently receives an
# authentication challenge even for this public Espressif repository.  Verify
# anonymous Smart HTTP first; if that fails, reuse the already-masked checkout
# header through environment-scoped Git configuration so nested/bare fetches
# inherit the same GitHub authentication without writing credentials to disk.
if [[ "${GITHUB_ACTIONS:-}" == "true" && "${JARNSEN_PIO_ENV:-}" != "seeed_wio_tracker_L1" ]]; then
  ESPRESSIF_GIT_REMOTE="https://github.com/espressif/esp32-arduino-lib-builder.git"
  printf 'GitHub Smart HTTP preflight: %s\n' "$ESPRESSIF_GIT_REMOTE"

  set +e
  git ls-remote "$ESPRESSIF_GIT_REMOTE" HEAD >/dev/null 2>&1
  ANON_GIT_STATUS=$?
  set -e

  if (( ANON_GIT_STATUS != 0 )); then
    CHECKOUT_AUTH_HEADER="$(git config --local --get http.https://github.com/.extraheader 2>/dev/null || true)"
    if [[ -z "$CHECKOUT_AUTH_HEADER" ]]; then
      echo "Anonymous GitHub Smart HTTP failed and checkout auth header is unavailable" >&2
      exit "$ANON_GIT_STATUS"
    fi

    export GIT_CONFIG_COUNT=1
    export GIT_CONFIG_KEY_0='http.https://github.com/.extraheader'
    export GIT_CONFIG_VALUE_0="$CHECKOUT_AUTH_HEADER"

    set +e
    git ls-remote "$ESPRESSIF_GIT_REMOTE" HEAD >/dev/null 2>&1
    AUTH_GIT_STATUS=$?
    set -e

    if (( AUTH_GIT_STATUS != 0 )); then
      echo "GitHub Smart HTTP also failed with the actions/checkout authentication header" >&2
      exit "$AUTH_GIT_STATUS"
    fi

    echo "Anonymous GitHub Smart HTTP failed; authenticated checkout-header fallback succeeded"
  else
    echo "Anonymous GitHub Smart HTTP succeeded"
  fi
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
