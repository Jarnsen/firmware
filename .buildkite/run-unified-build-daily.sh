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

# Keep Meshtastic's globally-applied APP_VERSION compiler define stable across
# normal Unified Core development commits. Otherwise the git SHA embedded in
# APP_VERSION changes on every commit and forces hundreds of otherwise
# unchanged translation units to rebuild. Exact JARNSEN identity remains
# per-build through JARNSEN_BUILD_SHA / JARNSEN_BUILD_NUMBER and package
# source_sha metadata.
export JARNSEN_STABLE_APP_VERSION="${JARNSEN_STABLE_APP_VERSION:-1}"
printf 'Stable Unified Core APP_VERSION cache identity: %s\n' "$JARNSEN_STABLE_APP_VERSION"

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

# The primary Tracker Full-Lock transform is applied by the workflow before
# entering this build wrapper. Apply Tracker UI follow-ups first, then shared
# Unified Core menu, Full Lock, and Bluetooth security transforms used by every
# supported board.
if [[ -f tools/patch_jarnsen_tracker_full_lock_button_v2.py ]]; then
  python3 tools/patch_jarnsen_tracker_full_lock_button_v2.py
  git diff --check
fi
if [[ -f tools/patch_jarnsen_tracker_full_lock_common_v5.py ]]; then
  python3 tools/patch_jarnsen_tracker_full_lock_common_v5.py
  git diff --check
fi
if [[ -f tools/patch_jarnsen_tracker_menu_pin_auth.py ]]; then
  python3 -m py_compile tools/patch_jarnsen_tracker_menu_pin_auth.py
  python3 tools/patch_jarnsen_tracker_menu_pin_auth.py
  git diff --check
fi
if [[ -f tools/patch_jarnsen_shared_menu_security.py ]]; then
  python3 -m py_compile tools/patch_jarnsen_shared_menu_security.py
  python3 tools/patch_jarnsen_shared_menu_security.py
  git diff --check
fi
if [[ -f tools/patch_jarnsen_tbeam_supreme_wlan.py ]]; then
  python3 -m py_compile tools/patch_jarnsen_tbeam_supreme_wlan.py
  python3 tools/patch_jarnsen_tbeam_supreme_wlan.py
  git diff --check
fi
if [[ -f tools/patch_jarnsen_unified_full_lock_ui.py ]]; then
  python3 -m py_compile tools/patch_jarnsen_unified_full_lock_ui.py
  python3 tools/patch_jarnsen_unified_full_lock_ui.py
  git diff --check
fi
if [[ -f tools/patch_jarnsen_hide_bt_pairing_pin.py ]]; then
  python3 -m py_compile tools/patch_jarnsen_hide_bt_pairing_pin.py
  python3 tools/patch_jarnsen_hide_bt_pairing_pin.py
  git diff --check
fi

# Persistent Unified-Core cache for the dedicated self-hosted runner.
# Toolchains/frameworks are shared across boards; mutable PlatformIO workspaces
# and object caches stay isolated per board/environment. This avoids downloading
# the complete ESP32 toolchain and rebuilding unchanged dependencies on every
# job while preventing one board's .pio state from contaminating another.
if [[ "${GITHUB_ACTIONS:-}" == "true" ]]; then
  JARNSEN_CACHE_ROOT="${JARNSEN_CACHE_ROOT:-$HOME/.cache/jarnsen-unified}"
  JARNSEN_CACHE_SCOPE="${GITHUB_REPOSITORY:-Jarnsen-firmware}-${GITHUB_REF_NAME:-local}"
  JARNSEN_CACHE_SCOPE="${JARNSEN_CACHE_SCOPE//\//_}"
  JARNSEN_BOARD_CACHE="${JARNSEN_PIO_ENV:-board}"

  export PLATFORMIO_CORE_DIR="$JARNSEN_CACHE_ROOT/platformio-core"
  export PLATFORMIO_WORKSPACE_DIR="$JARNSEN_CACHE_ROOT/workspaces/$JARNSEN_CACHE_SCOPE/$JARNSEN_BOARD_CACHE"
  export PLATFORMIO_BUILD_CACHE_DIR="$JARNSEN_CACHE_ROOT/build-cache/$JARNSEN_CACHE_SCOPE/$JARNSEN_BOARD_CACHE"

  # Targeted recovery switches. Normal jobs keep all caches.
  if [[ "${JARNSEN_CACHE_RESET:-0}" == "1" ]]; then
    rm -rf "$PLATFORMIO_WORKSPACE_DIR" "$PLATFORMIO_BUILD_CACHE_DIR"
    printf 'Reset board cache for %s\n' "$JARNSEN_BOARD_CACHE"
  fi
  if [[ "${JARNSEN_PLATFORMIO_CORE_RESET:-0}" == "1" ]]; then
    rm -rf "$PLATFORMIO_CORE_DIR"
    printf 'Reset shared PlatformIO package/toolchain cache\n'
  fi

  mkdir -p "$PLATFORMIO_CORE_DIR" "$PLATFORMIO_WORKSPACE_DIR" "$PLATFORMIO_BUILD_CACHE_DIR"

  # Keep the repository-visible .pio path for the existing packaging steps,
  # but store its contents outside the checkout so actions/checkout clean does
  # not destroy the previous board build state.
  rm -rf "$PWD/.pio"
  ln -s "$PLATFORMIO_WORKSPACE_DIR" "$PWD/.pio"

  printf 'Persistent PlatformIO core: %s\n' "$PLATFORMIO_CORE_DIR"
  printf 'Persistent board workspace: %s (linked as %s/.pio)\n' "$PLATFORMIO_WORKSPACE_DIR" "$PWD"
  printf 'Persistent build cache: %s\n' "$PLATFORMIO_BUILD_CACHE_DIR"
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
# GitHub/archive endpoints. Retry only clearly transient network/DNS failures
# and PIOArduino's known first-provision penv bootstrap failure. On a cold core
# cache pioarduino can create penv successfully, then fail its first dependency
# install with exit code 2; rerunning the same build completes provisioning.
# Real compiler, linker and contract failures must remain immediately red.
LOG_FILE="unified-${JARNSEN_PIO_ENV}.log"
is_transient_network_failure() {
  [[ -f "$LOG_FILE" ]] || return 1
  grep -Eiq \
    'Temporary failure in name resolution|NameResolutionError|Failed to resolve|Could not resolve host|ConnectionError|Connection reset by peer|Read timed out|ConnectTimeout|Remote end closed connection|TLS.*timed out|Failed to install Python dependencies into penv|Failed to install Python dependencies \(exit code: 2\)' \
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
