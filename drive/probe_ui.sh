#!/bin/sh
# Probe the main menu blind: fire an autopilot script at the game and report
# whether debug.log grew past the idle baseline (222 lines).
#
# Exists because there is NO other feedback channel -- Xwayland has no XTEST,
# GNOME denies screenshots, and SDL_VIDEODRIVER=x11 stalls the engine (see
# AGENTS.md "Driving the game").  The log is the entire oracle: if a click or
# key does anything at all, the engine logs it.
#
#   sh analysis/tools/drive/probe_ui.sh "<label>" "<SACRED_AUTO script>" [seconds]
#
# ponytail: one run per invocation, no parallelism -- the game grabs the
# display and two copies would fight over it.

set -u
ROOT=$(cd "$(dirname "$0")/../../.." && pwd)
# A bare checkout resolves ROOT to the wrong place -- these scripts expect to
# sit at <workspace>/analysis/tools/<group>/. SACRED_INSTALL and SACRED_PORT
# are the way out when they do not.
INSTALL="${SACRED_INSTALL:-$ROOT/install}"
PORT="${SACRED_PORT:-$ROOT/godot-port}"
LOG="$HOME/.lgp/sacred/debug.log"
LABEL=$1
SCRIPT=$2
DUR=${3:-40}

rm -f "$LOG"
SACRED_PRELOAD=autopilot.so SACRED_AUTO="$SCRIPT" \
    "$INSTALL/play.sh" --nosound >"/tmp/probe_$$.out" 2>&1 &
pid=$!

# Sample every 500ms so a log jump can be attributed to the click that caused
# it: autopilot stamps each step to stderr as "[autopilot] t=NNNNms <act>".
prev=0
t=0
while [ "$t" -lt "${DUR}0" ]; do
    n=$(awk 'END{print NR}' "$LOG" 2>/dev/null); [ -n "$n" ] || n=0
    [ "$n" -ne "$prev" ] && printf '  t=%-7s lines=%s\n' "$((t * 100))ms" "$n"
    prev=$n
    t=$((t + 5))
    sleep 0.5
done
lines=$prev
# `grep -c ... || echo 0` yields "0\n0" on no-match -- see AGENTS.md
failed=$(/usr/bin/grep -c 'CalcResults () type=0 FAILED' "$LOG" 2>/dev/null); [ -n "$failed" ] || failed=0

kill "$pid" 2>/dev/null
sleep 2
kill -9 "$pid" 2>/dev/null
wait "$pid" 2>/dev/null

# 222 = idle-at-menu baseline; anything more means the UI reacted
verdict=idle
[ "${lines:-0}" -gt 222 ] && verdict=REACTED
printf '%-28s lines=%-6s failed=%-6s %s\n' "$LABEL" "$lines" "$failed" "$verdict"

if [ "$verdict" = REACTED ]; then
    cp -f "$LOG" "/tmp/probe-$LABEL.log" 2>/dev/null
    echo "  --- new lines past 222 ---"
    awk 'NR>222' "$LOG" | head -20 | sed 's/^/  /'
fi
