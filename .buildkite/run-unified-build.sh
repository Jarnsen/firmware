#!/usr/bin/env bash
set -euo pipefail

: "${JARNSEN_BOARD_NAME:?JARNSEN_BOARD_NAME is required}"
: "${JARNSEN_PIO_ENV:?JARNSEN_PIO_ENV is required}"
: "${JARNSEN_BOOT_HARDWARE:?JARNSEN_BOOT_HARDWARE is required}"

VERSION="${JARNSEN_VERSION:-v2.0.0-alpha.1}"
SOURCE_SHA="$(git rev-parse HEAD)"
SHORT_SHA="${SOURCE_SHA:0:8}"
BUILD_NUMBER="${JARNSEN_BUILD_NUMBER:-${GITHUB_RUN_NUMBER:-0}}"
LOG_FILE="unified-${JARNSEN_PIO_ENV}.log"

printf '\n=== JARNSEN-MESH Unified Core runner ===\n'
printf 'Version: %s\n' "$VERSION"
printf 'Board: %s\n' "$JARNSEN_BOARD_NAME"
printf 'Environment: %s\n' "$JARNSEN_PIO_ENV"
printf 'Commit: %s\n' "$SOURCE_SHA"
printf 'Build: %s\n' "$BUILD_NUMBER"
uname -a || true
printf 'CPUs: %s\n' "$(getconf _NPROCESSORS_ONLN 2>/dev/null || nproc 2>/dev/null || echo unknown)"
free -h 2>/dev/null || true

ensure_python_venv() {
  if ! command -v python3 >/dev/null 2>&1; then
    if command -v sudo >/dev/null 2>&1; then
      sudo apt-get update
      sudo apt-get install -y python3 python3-venv python3-pip
    else
      apt-get update
      apt-get install -y python3 python3-venv python3-pip
    fi
  fi

  rm -rf .buildkite-venv
  if ! python3 -m venv .buildkite-venv; then
    if command -v sudo >/dev/null 2>&1; then
      sudo apt-get update
      sudo apt-get install -y python3-venv
    else
      apt-get update
      apt-get install -y python3-venv
    fi
    python3 -m venv .buildkite-venv
  fi
}

ensure_python_venv
PYTHON="$PWD/.buildkite-venv/bin/python"
PIP="$PWD/.buildkite-venv/bin/pip"
PIO="$PWD/.buildkite-venv/bin/pio"

"$PIP" install --disable-pip-version-check -U pip platformio
"$PIO" --version

"$PYTHON" - <<'PY'
import json
import pathlib
import shutil

root = pathlib.Path.home() / ".platformio" / "packages"
removed = []
if root.exists():
    for marker in root.glob("*/.piopm"):
        try:
            with marker.open("r", encoding="utf-8") as handle:
                json.load(handle)
        except Exception as exc:
            package_dir = marker.parent
            removed.append(f"{package_dir.name}: {exc}")
            shutil.rmtree(package_dir, ignore_errors=True)

if removed:
    print("Removed broken PlatformIO package cache entries:")
    for item in removed:
        print(f"- {item}")
else:
    print("PlatformIO package metadata cache is healthy")
PY

printf '\n=== Verify Unified Core architecture contracts ===\n'
test -f src/jarnsen/core/capabilities/JarnsenCapabilities.h
test -f src/jarnsen/core/roles/JarnsenDeviceRole.h
test -f src/jarnsen/core/features/JarnsenFeatureManager.h
test -f src/jarnsen/core/status/JarnsenNodeStatus.h
test -f src/jarnsen/core/status/JarnsenStatusProvider.h
test -f src/jarnsen/core/service/JarnsenServiceModel.h
test -f src/jarnsen/core/service/JarnsenServicePlatform.h
test -f src/jarnsen/core/service/JarnsenServiceDiagnostics.h
test -f src/jarnsen/core/build/JarnsenBuildInfo.h
test -f src/jarnsen/core/display/JarnsenBootSplash.h
test -f src/jarnsen/hardware/JarnsenHardwareProfiles.h
test -f src/jarnsen/core/JarnsenArchitecture.cpp
grep -q 'struct BoardCapabilities' src/jarnsen/core/capabilities/JarnsenCapabilities.h
grep -q 'struct PeripheralCapabilities' src/jarnsen/core/capabilities/JarnsenCapabilities.h
grep -q 'struct EffectiveCapabilities' src/jarnsen/core/capabilities/JarnsenCapabilities.h
grep -q 'struct DisplayCapabilities' src/jarnsen/core/capabilities/JarnsenCapabilities.h
grep -q 'struct NodeStatusSnapshot' src/jarnsen/core/status/JarnsenNodeStatus.h
grep -q 'struct NodeServiceDescriptor' src/jarnsen/core/service/JarnsenServiceModel.h
grep -q 'JARNSEN-MESH' src/jarnsen/core/build/JarnsenBuildInfo.h
grep -q "#define JARNSEN_FIRMWARE_SEMVER \"${VERSION}\"" src/jarnsen/core/build/JarnsenBuildInfo.h
grep -q 'drawBootSplash' src/jarnsen/core/display/JarnsenBootSplash.h
grep -q 'DeviceRole::TAK' src/jarnsen/core/JarnsenArchitecture.cpp
grep -q 'heltecV4Profile' src/jarnsen/hardware/JarnsenHardwareProfiles.h
grep -q 'seeedWioTrackerL1Profile' src/jarnsen/hardware/JarnsenHardwareProfiles.h
grep -q 'lilygoTBeamProfile' src/jarnsen/hardware/JarnsenHardwareProfiles.h
grep -q 'lilygoTBeamSupremeProfile' src/jarnsen/hardware/JarnsenHardwareProfiles.h
grep -q 'BOARD_LILYGO_TBEAM' src/jarnsen/core/capabilities/JarnsenCapabilities.h
grep -q 'BOARD_LILYGO_TBEAM_SUPREME' src/jarnsen/core/capabilities/JarnsenCapabilities.h
grep -q 'External GPS must not accidentally unlock Drone Repeater on V3' src/jarnsen/core/JarnsenArchitecture.cpp

printf '\n=== Route shared source through Unified Core seams ===\n'
"$PYTHON" tools/refactor_jarnsen_service_web_to_core.py
grep -q 'JarnsenServiceDiagnostics.h' src/mesh/http/JarnsenServiceWeb.cpp
grep -q 'JarnsenServicePlatform.h' src/mesh/http/JarnsenServiceWeb.cpp
grep -q 'SERVICE_DESCRIPTOR = jarnsen::platformServiceDescriptor' src/mesh/http/JarnsenServiceWeb.cpp
grep -q 'jarnsen::serviceDiagStartExport' src/mesh/http/JarnsenServiceWeb.cpp
! grep -q 'HeltecV3DiagnosticLog.h' src/mesh/http/JarnsenServiceWeb.cpp
! grep -q 'TrackerDiagnosticLog.h' src/mesh/http/JarnsenServiceWeb.cpp
grep -q '<h2>Taktische Lage</h2>' src/mesh/http/JarnsenServiceWeb.cpp
grep -q "satellite:{name:'SATELLIT'" src/mesh/http/JarnsenServiceWeb.cpp
grep -q "hybrid:{name:'HYBRID'" src/mesh/http/JarnsenServiceWeb.cpp

"$PYTHON" tools/refactor_jarnsen_boot_splash_to_core.py
grep -q 'JarnsenBootSplash.h' src/graphics/Screen.cpp
grep -q 'jarnsen::drawBootSplash(display, x, y)' src/graphics/Screen.cpp

"$PYTHON" tools/refactor_jarnsen_tracker_page_indicator.py
grep -q 'drawPagePosition(display, x, y, currentPage)' src/vehicle/TrackerStatusModule.cpp
grep -q 'displayPageNumber(page)' src/vehicle/TrackerStatusModule.cpp
grep -q 'displayPageCount()' src/vehicle/TrackerStatusModule.cpp

printf '\n=== Generate JARNSEN-MESH build metadata ===\n'
mkdir -p src/jarnsen/core/build
cat > src/jarnsen/core/build/JarnsenBuildGenerated.h <<EOF
#pragma once
#define JARNSEN_FIRMWARE_PRODUCT "JARNSEN-MESH"
#define JARNSEN_FIRMWARE_SEMVER "${VERSION}"
#define JARNSEN_BOOT_HARDWARE "${JARNSEN_BOOT_HARDWARE}"
#define JARNSEN_BUILD_SHA "${SHORT_SHA}"
#define JARNSEN_BUILD_NUMBER ${BUILD_NUMBER}
EOF

cat > src/vehicle/JarnsenBuildGenerated.h <<EOF
#pragma once
#define JARNSEN_FIRMWARE_SEMVER "${VERSION}"
#define JARNSEN_FIRMWARE_VERSION "JARNSEN-MESH ${VERSION}"
#define JARNSEN_BUILD_SHA "${SHORT_SHA}"
#define JARNSEN_BUILD_NUMBER ${BUILD_NUMBER}
EOF

printf '\n=== Compile %s ===\n' "$JARNSEN_BOARD_NAME"
set +e
set -o pipefail
if [[ "$JARNSEN_PIO_ENV" == "seeed_wio_tracker_L1" ]]; then
  "$PIO" run -e "$JARNSEN_PIO_ENV" 2>&1 | tee "$LOG_FILE"
else
  printf 'Pinning ESP32 platform 55.03.39 -> 55.03.37 in project configs\n'
  while IFS= read -r config_file; do
    sed -i 's#/55\.03\.39/platform-espressif32\.zip#/55.03.37/platform-espressif32.zip#g' "$config_file"
  done < <(grep -rl --include='*.ini' '55\.03\.39/platform-espressif32\.zip' platformio.ini variants 2>/dev/null || true)
  "$PIO" run -e "$JARNSEN_PIO_ENV" 2>&1 | tee "$LOG_FILE"
fi
BUILD_STATUS=${PIPESTATUS[0]}
set -e

if (( BUILD_STATUS != 0 )); then
  {
    echo '=== Compiler / build error matches ==='
    grep -n -E '(^|[[:space:]])(error:|fatal error:|fatal:)|CMake Error|undefined reference|collect2: error|FAILED:|\*\*\* .*Error' "$LOG_FILE" || true
    echo
    echo '=== ESP-IDF Component Manager git remotes ==='
    COMPONENT_CACHE="$HOME/.cache/Espressif/ComponentManager"
    if [[ -d "$COMPONENT_CACHE" ]]; then
      while IFS= read -r git_dir; do
        echo "--- ${git_dir} ---"
        git --git-dir="$git_dir" remote -v 2>&1 || true
        git --git-dir="$git_dir" config --show-origin --get-regexp '^(remote\..*\.url|url\..*\.insteadof|credential\.|http\.)' 2>&1 || true
      done < <(find "$COMPONENT_CACHE" -maxdepth 1 -type d -name 'b_git_*' -print | sort)
    else
      echo "Component Manager cache not found: ${COMPONENT_CACHE}"
    fi
    echo
    echo '=== Last 350 build lines ==='
    tail -n 350 "$LOG_FILE" || true
  } > "unified-${JARNSEN_PIO_ENV}-compiler-errors.txt"
  exit "$BUILD_STATUS"
fi

printf '\n=== Build successful: %s ===\n' "$JARNSEN_BOARD_NAME"
