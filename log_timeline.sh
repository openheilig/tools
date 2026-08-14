#!/bin/sh
# Diagnostic: launch the game once and sample its debug log every 2s, so we can
# see WHEN lines and `CalcResults FAILED` bursts actually appear.
#
# Exists because the settle-based metric in race_sweep.sh assumes the log stops
# growing once the run has shown its true colours.  That assumption has already
# been wrong twice (AGENTS.md "CURRENT BLOCKER").  This script measures the
# real timeline instead of assuming one.
#
#   sh analysis/tools/log_timeline.sh [seconds] [play.sh flags...]

set -u
ROOT=$(cd "$(dirname "$0")/../.." && pwd)
LOG="$HOME/.lgp/sacred/debug.log"
DUR=${1:-150}
[ $# -gt 0 ] && shift

rm -f "$LOG"
"$ROOT/install/play.sh" "$@" >/tmp/log_timeline.out 2>&1 &
pid=$!

printf '%5s %7s %8s %6s\n' t lines failed menu
t=0
prev_lines=-1
while [ "$t" -lt "$DUR" ]; do
    if kill -0 "$pid" 2>/dev/null; then alive=yes; else alive=no; fi
    if [ -f "$LOG" ]; then
        lines=$(wc -l <"$LOG")
        failed=$(grep -c 'CalcResults () type=0 FAILED' "$LOG" 2>/dev/null); [ -n "$failed" ] || failed=0
        menu=$(grep -c 'starting menu thread' "$LOG" 2>/dev/null); [ -n "$menu" ] || menu=0
    else
        lines=0; failed=0; menu=0
    fi
    # only print when something changed, plus every 10th sample as a heartbeat
    if [ "$lines" != "$prev_lines" ] || [ $((t % 20)) -eq 0 ]; then
        printf '%5s %7s %8s %6s  %s\n' "$t" "$lines" "$failed" "$menu" "$alive"
    fi
    prev_lines=$lines
    [ "$alive" = no ] && { echo "process exited at t=${t}s"; break; }
    t=$((t + 2))
    sleep 2
done

kill "$pid" 2>/dev/null
sleep 2
kill -0 "$pid" 2>/dev/null && kill -9 "$pid" 2>/dev/null
wait "$pid" 2>/dev/null
echo "final: lines=$(wc -l <"$LOG" 2>/dev/null) failed=$(grep -c 'CalcResults () type=0 FAILED' "$LOG" 2>/dev/null)"
