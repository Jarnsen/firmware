#!/usr/bin/env bash

set -e

VERSION=`bin/buildinfo.py long`
SHORT_VERSION=`bin/buildinfo.py short`

BUILDDIR=.pio/build/$1
OUTDIR=release

rm -f $OUTDIR/firmware*
rm -r $OUTDIR/* || true

# Important to pull latest version of libs into all device flavors, otherwise some devices might be stale
platformio pkg install -e $1

# platform-espressif32 55.03.39 creates a child PENV under PLATFORMIO_CORE_DIR
# for the hybrid ESP-IDF -> Arduino build.  Its dependency is pioarduino>=6.1.19,
# so a pre-populated PENV with 6.2.0 is considered valid and is not constrained by
# a later resolver constraint.  Pin the actual child executable back to the
# known-good core before the nested Arduino pass.  This is CI-only and does not
# change firmware contents or local developer environments.
if [[ "${GITHUB_ACTIONS:-}" == "true" ]]; then
    PIOARDUINO_PENV="${PLATFORMIO_CORE_DIR:-$HOME/.platformio}/penv"
    PIOARDUINO_PYTHON="$PIOARDUINO_PENV/bin/python"
    PIOARDUINO_UV="$PIOARDUINO_PENV/bin/uv"
    PIOARDUINO_PIO="$PIOARDUINO_PENV/bin/pio"

    if [[ ! -x "$PIOARDUINO_PYTHON" || ! -x "$PIOARDUINO_UV" ]]; then
        echo "ERROR: pioarduino child PENV was not created at $PIOARDUINO_PENV" >&2
        exit 1
    fi

    "$PIOARDUINO_UV" pip install --python "$PIOARDUINO_PYTHON" --quiet 'pioarduino==6.1.19'

    if [[ ! -x "$PIOARDUINO_PIO" ]]; then
        echo "ERROR: pioarduino child PIO executable is missing at $PIOARDUINO_PIO" >&2
        exit 1
    fi

    PIOARDUINO_CHILD_VERSION="$($PIOARDUINO_PIO --version)"
    echo "Pinned nested ESP32 build core: $PIOARDUINO_CHILD_VERSION"
    if [[ "$PIOARDUINO_CHILD_VERSION" != *"6.1.19"* ]]; then
        echo "ERROR: expected nested pioarduino core 6.1.19, got: $PIOARDUINO_CHILD_VERSION" >&2
        exit 1
    fi
fi

echo "Building for $1 with $PLATFORMIO_BUILD_FLAGS"
rm -f $BUILDDIR/firmware*

# The shell vars the build tool expects to find
export APP_VERSION=$VERSION

basename=firmware-$1-$VERSION

pio run --environment $1 -t mtjson # -v

cp $BUILDDIR/$basename.elf $OUTDIR/$basename.elf

echo "Copying ESP32 bin file"
cp $BUILDDIR/$basename.factory.bin $OUTDIR/$basename.factory.bin

echo "Copying ESP32 update bin file"
cp $BUILDDIR/$basename.bin $OUTDIR/$basename.bin

echo "Copying Filesystem for ESP32 targets"
cp $BUILDDIR/littlefs-$1-$VERSION.bin $OUTDIR/littlefs-$1-$VERSION.bin
cp bin/device-install.* $OUTDIR/
cp bin/device-update.* $OUTDIR/

echo "Copying manifest"
cp $BUILDDIR/$basename.mt.json $OUTDIR/$basename.mt.json
