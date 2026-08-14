#!/bin/sh
# Build the 32-bit shims from here into install/shim/, where play.sh's
# LD_LIBRARY_PATH picks them up.
#
# WHY THE SOURCES LIVE OUTSIDE install/: the root .gitignore denies that whole
# tree, because it holds ~16GB of non-redistributable game data. These .c files
# ship nothing of the game's -- they are our own code -- so keeping them beside
# the retail binary made them untrackable for no reason. The built .so files
# STAY in install/shim: they are runtime artefacts and rebuildable from here.
set -eu
ROOT=$(cd "$(dirname "$0")/.." && pwd)
OUT="$ROOT/install/shim"
CFLAGS="-m32 -shared -fPIC -O2"
cd "$(dirname "$0")"
gcc $CFLAGS -std=gnu99 -o "$OUT/autopilot.so"  autopilot.c
gcc $CFLAGS               -o "$OUT/xshim.so"    xshim.c
gcc $CFLAGS               -o "$OUT/filetrace.so" filetrace.c -ldl
gcc $CFLAGS               -o "$OUT/localetrace.so" localetrace.c -ldl
echo "built: autopilot xshim filetrace localetrace -> $OUT"
