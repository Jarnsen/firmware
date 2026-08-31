#!/usr/bin/env bash
set -euo pipefail

: "${JARNSEN_BOARD_NAME:?JARNSEN_BOARD_NAME is required}"
: "${JARNSEN_PIO_ENV:?JARNSEN_PIO_ENV is required}"
: "${JARNSEN_BOOT_HARDWARE:?JARNSEN_BOOT_HARDWARE is required}"

TEST_ARTIFACT="${JARNSEN_TEST_ARTIFACT:-0}"
ARTIFACT_LABEL="${JARNSEN_ARTIFACT_LABEL:-}"
DEVICE_ID="${JARNSEN_DEVICE_ID:-}"
VERSION="v2.0.0-alpha.1"
SOURCE_SHA="$(git rev-parse HEAD)"
SHORT_SHA="${SOURCE_SHA:0:8}"
BUILD_NUMBER="${BUILDKITE_BUILD_NUMBER:-0}"
LOG_FILE="unified-${JARNSEN_PIO_ENV}.log"

printf '\n=== JARNSEN-MESH Buildkite runner ===\n'
printf 'Board: %s\n' "$JARNSEN_BOARD_NAME"
printf 'Environment: %s\n' "$JARNSEN_PIO_ENV"
printf 'Commit: %s\n' "$SOURCE_SHA"
printf 'Buildkite build: %s\n' "$BUILD_NUMBER"
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

# Self-heal any persisted PlatformIO package metadata if a Buildkite cache volume
# is enabled later. On fully ephemeral hosted agents this is normally a no-op.
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
grep -q 'v2.0.0-alpha.1' src/jarnsen/core/build/JarnsenBuildInfo.h
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
"$PIO" run -e "$JARNSEN_PIO_ENV" 2>&1 | tee "$LOG_FILE"
BUILD_STATUS=${PIPESTATUS[0]}
set -e

if (( BUILD_STATUS != 0 )); then
  {
    echo '=== Compiler / build error matches ==='
    grep -n -E '(^|[[:space:]])(error:|fatal error:|fatal:)|CMake Error|undefined reference|collect2: error|FAILED:|\*\*\* .*Error' "$LOG_FILE" || true
    echo
    echo '=== Last 350 build lines ==='
    tail -n 350 "$LOG_FILE" || true
  } > "unified-${JARNSEN_PIO_ENV}-compiler-errors.txt"
  buildkite-agent artifact upload "$LOG_FILE" "unified-${JARNSEN_PIO_ENV}-compiler-errors.txt" || true
  exit "$BUILD_STATUS"
fi

if [[ "$TEST_ARTIFACT" == "1" ]]; then
  printf '\n=== Validate and collect flashable firmware ===\n'
  : "${ARTIFACT_LABEL:?JARNSEN_ARTIFACT_LABEL is required for test artifacts}"
  : "${DEVICE_ID:?JARNSEN_DEVICE_ID is required for test artifacts}"

  BUILD_DIR=".pio/build/${JARNSEN_PIO_ENV}"
  APP_BIN=$(find "$BUILD_DIR" -maxdepth 1 -type f -name "firmware-${JARNSEN_PIO_ENV}-*.bin" ! -name '*.factory.bin' -print -quit)
  FACTORY_BIN=$(find "$BUILD_DIR" -maxdepth 1 -type f -name "firmware-${JARNSEN_PIO_ENV}-*.factory.bin" -print -quit)
  test -n "$APP_BIN"
  test -n "$FACTORY_BIN"

  "$PYTHON" - "$APP_BIN" "$FACTORY_BIN" <<'PY'
from pathlib import Path
import sys

app_path = Path(sys.argv[1])
factory_path = Path(sys.argv[2])
app = app_path.read_bytes()
factory = factory_path.read_bytes()

if not app or app[0] != 0xE9:
    raise SystemExit(f"Invalid update image header in {app_path}: expected 0xE9")
if not factory or factory[0] != 0xE9:
    raise SystemExit(f"Invalid factory bootloader header in {factory_path}: expected 0xE9")
if len(factory) <= 0x10000:
    raise SystemExit(f"Factory image too small to contain app0: {len(factory)} bytes")
if factory[0x8000:0x8002] != b"\xaa\x50":
    raise SystemExit(f"Factory partition-table magic invalid: {factory[0x8000:0x8002].hex()}")
if factory[0x10000] != 0xE9:
    raise SystemExit(f"Factory app0 header invalid at 0x10000: 0x{factory[0x10000]:02x}")
if factory[0x10000:0x10000 + len(app)] != app:
    raise SystemExit("Factory app0 payload does not exactly match update image")

print(f"Validated flash images: app={len(app)} bytes, factory={len(factory)} bytes, app0 payload identical")
PY

  PREFIX="JARNSEN-MESH-${VERSION}-${ARTIFACT_LABEL}"
  rm -rf firmware-artifact
  mkdir -p firmware-artifact
  cp "$FACTORY_BIN" "firmware-artifact/${PREFIX}.factory.bin"
  cp "$APP_BIN" "firmware-artifact/${PREFIX}.update.bin"

  "$PYTHON" - "$APP_BIN" "firmware-artifact/${PREFIX}.webflasher.bin" <<'PY'
from pathlib import Path
import sys

app = Path(sys.argv[1]).read_bytes()
out_path = Path(sys.argv[2])
APP0_OFFSET = 0x10000
APP1_OFFSET = 0x340000
SPIFFS_OFFSET = 0x670000
SLOT_SIZE = APP1_OFFSET - APP0_OFFSET

if len(app) > SLOT_SIZE:
    raise SystemExit(f"Application image is {len(app)} bytes, larger than OTA slot {SLOT_SIZE} bytes")

payload = app + (b"\xff" * (SLOT_SIZE - len(app))) + app
if APP0_OFFSET + len(payload) > SPIFFS_OFFSET:
    raise SystemExit("Dual-slot Web Flasher image would overlap SPIFFS")

out_path.write_bytes(payload)
print(f"Web Flasher image: {len(payload)} bytes; app0=0x{APP0_OFFSET:x}, app1=0x{APP1_OFFSET:x}, end=0x{APP0_OFFSET + len(payload):x}")
PY

  cat > firmware-artifact/README-FLASH.txt <<EOF
JARNSEN-MESH ${VERSION}
Board: ${JARNSEN_BOARD_NAME}
Device: ${DEVICE_ID}
Source SHA: ${SOURCE_SHA}
Buildkite build: ${BUILD_NUMBER}

USB-Erstinstallation / kompletter Flash:
  ${PREFIX}.factory.bin

JARNSEN Service Tool / echtes OTA-Update:
  ${PREFIX}.update.bin

Meshtastic Web Flasher -> lokale Datei -> Update:
  ${PREFIX}.webflasher.bin

Die webflasher.bin enthaelt das gleiche JARNSEN-MESH-App-Image fuer app0
und app1. NVS, Einstellungen, Kanaele und SPIFFS bleiben erhalten.

Entwicklungsstand: Alpha. Die bisherige stabile Firmware zum
Zurueckflashen bereithalten.
EOF

  (
    cd firmware-artifact
    sha256sum "${PREFIX}.factory.bin" "${PREFIX}.update.bin" "${PREFIX}.webflasher.bin" > SHA256SUMS.txt
  )
  buildkite-agent artifact upload 'firmware-artifact/*'
fi

printf '\n=== Build successful: %s ===\n' "$JARNSEN_BOARD_NAME"
