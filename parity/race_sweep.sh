#!/bin/sh
# Measure how reliably the game loads a world, and count `CalcResults FAILED`.
#
#   sh analysis/tools/parity/race_sweep.sh [runs] [extra play.sh flags...]
#   sh analysis/tools/parity/race_sweep.sh 10 --nosound
#
# ---------------------------------------------------------------------------
# Read this before trusting a number out of this script.
#
# The previous version launched play.sh with no input and waited for the log
# to settle.  That could never work: with no mouse input the engine idles at
# the main menu at ~222 log lines forever and never loads a world, so every
# run scored 0 FAILED whatever the engine did.  It measured the harness.
# (The version before that counted at `setLoading (0)`, which measured grep
# timing.  This metric has now been invalidated twice -- stay suspicious.)
#
# So: drive the game to actual gameplay with autopilot.so, then count.  A run
# only counts as a sample if it reaches a gameplay marker; a run that hangs
# during load is reported separately, never folded in as "0 FAILED".
# ---------------------------------------------------------------------------

set -u
ROOT=$(cd "$(dirname "$0")/../../.." && pwd)
# A bare checkout resolves ROOT to the wrong place -- these scripts expect to
# sit at <workspace>/analysis/tools/<group>/. SACRED_INSTALL and SACRED_PORT
# are the way out when they do not.
INSTALL="${SACRED_INSTALL:-$ROOT/install}"
PORT="${SACRED_PORT:-$ROOT/godot-port}"
LOG="$HOME/.lgp/sacred/debug.log"
CAP=${SWEEP_CAP:-150}          # seconds per run; a good run reaches gameplay by ~65s
PLAY_SECS=${SWEEP_PLAY:-70}    # seconds to keep playing AFTER the world appears

# Ancaria campaign -> Gladiator -> Start Game -> clear both tips dialogs ->
# walk the arena.  Coordinates are for the 1024x768 window (see AGENTS.md
# "Driving and seeing the game"); they were read off captured frames.
#
# In-game clicks MUST be pinned first: the engine tracks its cursor by
# accumulating SDL_MOUSEMOTION deltas, not by absolute position, so a bare
# `click x y` lands at an unknown offset once the world is up.  `move 0 0`
# drives the cursor into the top-left clamp; the next absolute move then has a
# known origin.  Menu clicks need none of this -- the menu reads absolute
# SDL_GetMouseState.
#
# Menu clicks fire on wall-clock from process start, so they must land AFTER
# the main menu exists.  The menu is ready somewhere between t=5s and t=15s
# depending on disk cache and compositor luck; the original 6s/12s/16s
# schedule therefore threw its clicks away on any slow start, and the run then
# sat at the menu until the harness SIGTERMed it.  That is what the 3/5
# "NO-WORLD lines=241" runs of 2026-08-06 were -- not a load hang: the log
# tail is a clean `cCommand_exitGame() WM_CLOSE` (SDL 1.2 turns our SIGTERM
# into SDL_QUIT), with the menu thread up and idle above it.  Clicking at 20s
# costs 14s a run and removes the race entirely.
CLK() { echo "$1 move 0 0; $(($1 + 1200)) move $2 $3; $(($1 + 2400)) click $2 $3"; }
SCRIPT=${SWEEP_SCRIPT:-"20000 click 512 287; 26000 click 110 420; 30000 click 605 715\
; $(CLK 64000 348 499)\
; $(CLK 70000 608 623)\
; $(CLK 86000 700 300)\
; $(CLK 96000 300 550)\
; $(CLK 106000 800 400)\
; $(CLK 116000 500 250)"}

# Only emitted once the world is live and the hero is walking sectors.
#
# Do NOT add `cCreature::receive_event` here.  It looked like a gameplay
# marker and is not: it is emitted at log line ~264 while the engine equips
# the hero, ~1600 lines before the world exists.  With it in the alternation
# this script scored a build that hung at `Reading Questbinary` (line 293) as
# GAMEPLAY / FAILED=0.  That was the third time this project's metric turned
# out to be measuring the harness -- check any new marker against a known-good
# log (`grep -n` it) before trusting it.
# ponytail: overridable because this marker is scenario-specific -- it fires
# when the hero WALKS into a sector, which a save-load never does (the hero is
# placed, not moved).  A save-load run therefore scores NO-WORLD on the default
# marker even though it reaches full gameplay.  To sweep the save-load path:
#
#   SWEEP_MARKER='cUI_Manager::tooltipCreate' \
#   SWEEP_SCRIPT='20000 click 514 414; 26000 click 455 353; 30000 click 866 300; 34000 click 422 440' \
#     sh analysis/tools/parity/race_sweep.sh 3 --nosound
#
# (that loads install/save/game01.pak from the main menu; the 34s click is the
# "Load game!" confirmation OK, and omitting it leaves the run sitting on the
# dialog at 242 log lines -- which reads exactly like a load hang and is not).
MARKER=${SWEEP_MARKER:-'cInterpretSQW::enterSector'}
MINLINES=${SWEEP_MINLINES:-1000}   # belt and braces: a real world load is ~2300 lines

RUNS=${1:-10}
[ $# -gt 0 ] && shift

played=0; hung=0; failsum=0; worst=0
echo "sweep: $RUNS runs, flags: ${*:-<none>}"

i=1
while [ "$i" -le "$RUNS" ]; do
    pkill -9 -x sacred 2>/dev/null      # a stale instance poisons the next run
    rm -f "$LOG"
    SACRED_PRELOAD=autopilot.so SACRED_AUTO="$SCRIPT" \
        "$INSTALL/play.sh" "$@" >/tmp/race_sweep_run.out 2>&1 &
    pid=$!                       # play.sh execs the game, so this is its pid

    # Reaching the marker is NOT the end of the run.  Every earlier version
    # broke here, which meant the counters below were read the instant the
    # world appeared -- the engine had not played a single frame of anything.
    # Keep going for PLAY_SECS so the FAILED count covers actual gameplay.
    waited=0; deadline=$CAP
    while [ "$waited" -lt "$deadline" ]; do
        kill -0 "$pid" 2>/dev/null || break
        if [ "$deadline" = "$CAP" ] && /usr/bin/grep -qa "$MARKER" "$LOG" 2>/dev/null; then
            deadline=$((waited + PLAY_SECS))
            [ "$deadline" -lt "$CAP" ] && deadline=$CAP
        fi
        waited=$((waited + 1))
        sleep 1
    done
    kill "$pid" 2>/dev/null; sleep 2; kill -9 "$pid" 2>/dev/null
    wait "$pid" 2>/dev/null
    pkill -9 -x sacred 2>/dev/null

    # `grep -c` prints a count AND exits 1 when that count is zero, so
    # `$(grep -c ... || echo 0)` yields the two-line string "0\n0", which then
    # fails `[ -eq ]` and misreports a clean run.  Take the output, drop the
    # exit status.
    n=$(/usr/bin/grep -ca 'CalcResults () type=0 FAILED' "$LOG" 2>/dev/null); [ -n "$n" ] || n=0
    lines=$(awk 'END{print NR}' "$LOG" 2>/dev/null); [ -n "$lines" ] || lines=0

    # OBJ counts cObjectManager::load() lines.  It was added as "DESYNC" on
    # the belief that this function only logs when the 0xBAADF00D sentinel
    # fails to match.  That is WRONG and the column was renamed on
    # 2026-08-06: it is an unconditional per-object trace.  A perfectly
    # healthy load of install/save/game01.pak emits 1554 of them -- one
    # header plus one per object, and `Fam[0]=INVALID` just means an empty
    # slot.  It reads 0 on new-game runs only because those never call
    # cObjectManager::load() at all.
    #
    # That is the fourth metric in this project that turned out to be
    # measuring the harness.  Keep it as a load-happened indicator; never
    # read it as an error count.
    d=$(/usr/bin/grep -ca 'cObjectManager::load()' "$LOG" 2>/dev/null); [ -n "$d" ] || d=0

    if /usr/bin/grep -qa "$MARKER" "$LOG" 2>/dev/null && [ "$lines" -ge "$MINLINES" ]; then
        played=$((played + 1)); failsum=$((failsum + n))
        [ "$n" -gt "$worst" ] && worst=$n
        printf '  run %-3s GAMEPLAY  lines=%-6s FAILED=%-4s OBJ=%s\n' \
            "$i" "$lines" "$n" "$d"
    else
        hung=$((hung + 1))
        printf '  run %-3s NO-WORLD  lines=%-6s (last: %s)\n' "$i" "$lines" \
            "$(tail -1 "$LOG" 2>/dev/null)"
    fi
    i=$((i + 1))
done

echo "---"
echo "reached gameplay: $played/$RUNS   never loaded: $hung/$RUNS"
[ "$played" -gt 0 ] && echo "FAILED across gameplay runs: total=$failsum worst=$worst"
