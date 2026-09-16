#!/usr/bin/env bash

set -e

VERSION=`bin/buildinfo.py long`
SHORT_VERSION=`bin/buildinfo.py short`

BUILDDIR=.pio/build/$1
OUTDIR=release

rm -f $OUTDIR/firmware*
rm -r $OUTDIR/* || true

# platform-espressif32 55.03.39 creates a child PENV for the hybrid
# ESP-IDF -> Arduino build and requests pioarduino>=6.1.19 there.  Keep that
# child on the known-good core: pioarduino 6.2.0 switches tool-scons to 4.11.1
# and breaks the nested Arduino pass with SCons.Tool.FortranCommon missing.
if [[ "${GITHUB_ACTIONS:-}" == "true" && -z "${UV_CONSTRAINT:-}" ]]; then
    PIOARDUINO_CONSTRAINT=/tmp/jarnsen-pioarduino-constraints.txt
    printf 'pioarduino==6.1.19\n' > "$PIOARDUINO_CONSTRAINT"
    export UV_CONSTRAINT="$PIOARDUINO_CONSTRAINT"
fi

# Important to pull latest version of libs into all device flavors, otherwise some devices might be stale
platformio pkg install -e $1

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
