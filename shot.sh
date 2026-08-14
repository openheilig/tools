#!/bin/sh
# Drive the game with an autopilot script and capture its framebuffer.
#
# This replaces blind clicking.  There is no external way to see the game
# (no XTEST, GNOME denies screenshots, SDL_VIDEODRIVER=x11 stalls the engine),
# so autopilot.so hooks SDL_GL_SwapBuffers and glReadPixels the back buffer
# itself.  Output is PPM (no libpng needed), converted to PNG for viewing.
#
#   sh analysis/tools/shot.sh "<label>" "<SACRED_AUTO>" "<ms,ms,...>" [seconds]
#
# ponytail: one run per invocation -- the game grabs the display.

set -u
ROOT=$(cd "$(dirname "$0")/../.." && pwd)
LOG="$HOME/.lgp/sacred/debug.log"
LABEL=$1
SCRIPT=$2
SHOTS=$3
DUR=${4:-25}
OUT=/tmp/shot-$LABEL

rm -f /tmp/sacred-*.ppm /tmp/sacred-*.png
mkdir -p "$OUT"
rm -f "$LOG"

# ponytail: sound ON by default.  `--nosound` is STICKY -- the engine writes it
# back as `SOUND : 0` in ~/.lgp/sacred/settings.cfg and the config then beats
# the command line on every later run, so a harness that passes it silently
# mutes every future launch (this cost a whole misdiagnosis, see REPORT 2.15).
# Set SHOT_NOSOUND=1 only if you accept re-poisoning the config.
SND=${SHOT_NOSOUND:+--nosound}
SACRED_PRELOAD=autopilot.so SACRED_AUTO="$SCRIPT" SACRED_SHOT="$SHOTS" \
    "$ROOT/install/play.sh" $SND >"$OUT/stdout.txt" 2>&1 &
pid=$!
sleep "$DUR"
kill "$pid" 2>/dev/null; sleep 2; kill -9 "$pid" 2>/dev/null; wait "$pid" 2>/dev/null
pkill -x sacred 2>/dev/null

for f in /tmp/sacred-*.ppm; do
    [ -e "$f" ] || continue
    b=$(basename "$f" .ppm)
    magick "$f" "$OUT/$b.png" 2>/dev/null && rm -f "$f"
done
cp -f "$LOG" "$OUT/debug.log" 2>/dev/null

lines=$(awk 'END{print NR}' "$OUT/debug.log" 2>/dev/null); [ -n "$lines" ] || lines=0
# `grep -c ... || echo 0` yields "0\n0" on no-match -- see AGENTS.md
failed=$(/usr/bin/grep -c 'CalcResults () type=0 FAILED' "$OUT/debug.log" 2>/dev/null); [ -n "$failed" ] || failed=0
printf '%-20s lines=%-6s failed=%-6s -> %s\n' "$LABEL" "$lines" "$failed" "$OUT"
ls "$OUT"/*.png 2>/dev/null
