#!/usr/bin/env bash
set -euo pipefail

# Keep the self-hosted runner's system Git config from affecting ESP-IDF dependency fetches.
if [[ "${GITHUB_ACTIONS:-}" == "true" ]]; then
  export GIT_CONFIG_SYSTEM=/dev/null
  export GIT_TERMINAL_PROMPT=0
fi

# ESP-IDF Component Manager creates bare repositories outside the checked-out
# workspace. The auth header installed by actions/checkout is repository-local,
# so those nested git processes cannot see it by default. Move that same
# already-masked GitHub auth header from the checkout's local config into
# environment-scoped Git config for every ESP32 build. Removing the local copy
# first is important: otherwise Git sends two Authorization headers and GitHub
# rejects the request with HTTP 400 "Duplicate header: Authorization".
if [[ "${GITHUB_ACTIONS:-}" == "true" && "${JARNSEN_PIO_ENV:-}" != "seeed_wio_tracker_L1" ]]; then
  ESPRESSIF_GIT_REMOTE="https://github.com/espressif/esp32-arduino-lib-builder.git"
  CHECKOUT_AUTH_HEADER="$(git config --local --get http.https://github.com/.extraheader 2>/dev/null || true)"

  if [[ -z "$CHECKOUT_AUTH_HEADER" ]]; then
    echo "actions/checkout GitHub auth header is unavailable" >&2
    exit 1
  fi

  # The environment-scoped copy must be the only GitHub Authorization header.
  git config --local --unset-all http.https://github.com/.extraheader || true

  AUTH_INDEX="${GIT_CONFIG_COUNT:-0}"
  export GIT_CONFIG_COUNT=$((AUTH_INDEX + 1))
  export "GIT_CONFIG_KEY_${AUTH_INDEX}=http.https://github.com/.extraheader"
  export "GIT_CONFIG_VALUE_${AUTH_INDEX}=${CHECKOUT_AUTH_HEADER}"

  printf 'GitHub authentication moved to nested ESP-IDF git fetches\n'
  printf 'Authenticated GitHub Smart HTTP preflight: %s\n' "$ESPRESSIF_GIT_REMOTE"

  GIT_PREFLIGHT_OK=0
  for attempt in 1 2 3; do
    if git ls-remote "$ESPRESSIF_GIT_REMOTE" HEAD >/dev/null; then
      GIT_PREFLIGHT_OK=1
      break
    fi
    if (( attempt < 3 )); then
      delay=$((attempt * 10))
      printf 'GitHub preflight attempt %d/3 failed; retrying in %ds\n' "$attempt" "$delay" >&2
      sleep "$delay"
    fi
  done
  if (( GIT_PREFLIGHT_OK == 0 )); then
    echo "Authenticated GitHub Smart HTTP preflight failed after 3 attempts" >&2
    exit 1
  fi
  echo "Authenticated GitHub Smart HTTP succeeded"
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

# Self-hosted runners normally share ~/.platformio across repositories and
# jobs. A damaged/stale package there caused the intermittent SCons
# FortranCommon failures seen around Builds 140/141. Give every Unified matrix
# environment a clean private PlatformIO core directory. The environment name
# is part of the key so Tracker preflight and each board build are isolated even
# when the same physical runner executes them sequentially.
if [[ "${GITHUB_ACTIONS:-}" == "true" ]]; then
  PIO_TEMP_ROOT="${RUNNER_TEMP:-$PWD/.runner-temp}"
  PIO_TEMP_KEY="${GITHUB_RUN_ID:-run}-${GITHUB_RUN_ATTEMPT:-1}-${JARNSEN_PIO_ENV:-board}"
  export PLATFORMIO_CORE_DIR="$PIO_TEMP_ROOT/jarnsen-platformio-$PIO_TEMP_KEY"
  rm -rf "$PLATFORMIO_CORE_DIR"
  mkdir -p "$PLATFORMIO_CORE_DIR"
  printf 'Isolated PlatformIO core: %s\n' "$PLATFORMIO_CORE_DIR"
fi

# PlatformIO 6.2.0 currently pulls SCons 4.11.1 on the Linux runners. That
# combination aborts ESP32 builds before firmware compilation because the
# bundled SCons package cannot import SCons.Tool.FortranCommon. Keep Unified
# Core builds on the last stable 6.1.x release until that upstream regression
# is resolved. PIP_CONSTRAINT also applies to the nested pip invocation in
# run-unified-build.sh without duplicating its environment bootstrap.
PLATFORMIO_CONSTRAINTS="$(mktemp)"
trap 'rm -f "$PLATFORMIO_CONSTRAINTS"' EXIT
printf 'platformio==6.1.19\n' > "$PLATFORMIO_CONSTRAINTS"
export PIP_CONSTRAINT="$PLATFORMIO_CONSTRAINTS"

# Dependency installation on the self-hosted VM still depends on external
# GitHub/archive endpoints. Retry only clearly transient network/DNS failures;
# real compiler, linker and contract failures must remain immediately red.
LOG_FILE="unified-${JARNSEN_PIO_ENV}.log"
is_transient_network_failure() {
  [[ -f "$LOG_FILE" ]] || return 1
  grep -Eiq \
    'Temporary failure in name resolution|NameResolutionError|Failed to resolve|Could not resolve host|ConnectionError|Connection reset by peer|Read timed out|ConnectTimeout|Remote end closed connection|TLS.*timed out' \
    "$LOG_FILE"
}

BUILD_STATUS=1
for attempt in 1 2 3; do
  printf '\n=== Unified build attempt %d/3 ===\n' "$attempt"
  set +e
  bash .buildkite/run-unified-build.sh
  BUILD_STATUS=$?
  set -e

  if (( BUILD_STATUS == 0 )); then
    exit 0
  fi

  if (( attempt >= 3 )) || ! is_transient_network_failure; then
    exit "$BUILD_STATUS"
  fi

  delay=$((attempt * 10))
  printf 'Transient dependency/network failure detected; retrying build in %ds\n' "$delay" >&2
  sleep "$delay"
done

exit "$BUILD_STATUS"
