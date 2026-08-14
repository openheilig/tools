#!/bin/sh
# replay_diff.sh -- the record/replay harness's single determinism gate.
#
# Runs a record pass (godot --record=... --dump=A) and a plain replay pass
# (godot --replay=... --dump=B) and compares A and B with /usr/bin/diff.
# The comparison is between the two RUNS' dumps, never against the
# recording file itself and never against a stored golden dump: the
# recording carries movement intent only (D-01), so comparing against it
# would prove nothing about whether replay reproduced the simulation, and
# a golden file would go stale the moment collision, spawn derivation, or
# the scripted intent schedule changed.
#
# --control additionally replays the same recording three times more, each
# time with one of world/replay.gd's three perturbation flags (a cell
# nudge, a skipped input line, and a window-origin
# offset that couples PathWindow's origin to something outside the actor's
# own cell, all off by default, all selected by flag only -- never by a
# source edit) and asserts the OPPOSITE of the clean comparison: the diff
# must go non-empty, and its first differing hunk must name the exact tick
# the perturbation was injected at. A harness that has never been seen to
# fail has not been tested.
#
# Every Godot run below is captured to its own file rather than piped into
# another program -- a run killed mid-flight loses block-buffered stdout
# under a pipe, and this project has already been burned by that
# (AGENTS.md). A missing or empty dump is a hard failure, never silently
# compared as equal to another missing/empty file, and every tool
# invocation below uses an absolute path: the RTK shell hook has been
# observed reporting two files "identical" when they were not
# (CLAUDE.md).
#
#   sh analysis/tools/parity/replay_diff.sh
#   sh analysis/tools/parity/replay_diff.sh --control

set -u

ROOT=$(cd "$(dirname "$0")/../../.." && pwd)
PORT="$ROOT/godot-port"

MODE="${1:-}"
TICKS=600

# Tick 5 sits inside the scripted intent's first, straight-x phase, where
# the actor is confirmed moving on every single tick in this window
# (measured) -- never a tick where the actor is already stopped
# against a wall, which would let a skipped-intent perturbation coincide
# with the unperturbed outcome by accident and certify nothing.
PERTURB_TICK=5

# Tick 100 sits well before the recording's own goal request (tick 250) and
# well before either of the recording's natural window recentres (measured
# at tick 251 and tick 536 for the 600-tick session run below) -- chosen so
# the origin perturbation's own recentre-and-snap-back is not confused with
# a recentre the actor's real movement would have produced anyway.
ORIGIN_PERTURB_TICK=100

REC=/tmp/replay_diff_a.rec
DUMP_A=/tmp/replay_diff_a.dump
DUMP_B=/tmp/replay_diff_b.dump
REC_LOG=/tmp/replay_diff_rec.log
REP_LOG=/tmp/replay_diff_rep.log

OVERALL_FAIL=0

fail_missing() {
	# $1 = human label of what could not be produced, $2 = file it lives in
	echo "replay_diff: FAIL could not read $1 (see $2)"
	exit 1
}

require_dump() {
	# $1 = path, $2 = human label
	if [ ! -f "$1" ]; then
		fail_missing "$2 (missing)" "$1"
	fi
	if [ ! -s "$1" ]; then
		fail_missing "$2 (empty)" "$1"
	fi
}

run_record() {
	# $1 = recording path, $2 = dump path, $3 = log path
	godot --headless --path "$PORT" -- --autoplay="$TICKS" --record="$1" --dump="$2" >"$3" 2>&1
	RC=$?
	if [ "$RC" -ne 0 ]; then
		echo "replay_diff: FAIL record pass exited $RC -- see $3"
		exit 1
	fi
	require_dump "$2" "record dump"
}

# Replays $2 (recording path) -> $3 (dump path), logging to $4, with an
# optional falsify tick ($5) and mode ($6). Prints the run's exit code on
# stdout -- POSIX sh functions cannot return arbitrary values, so callers
# capture this line with a command substitution.
run_replay() {
	REC_PATH="$1"
	DUMP_PATH="$2"
	LOG_PATH="$3"
	FALSIFY_TICK="${4:-}"
	FALSIFY_MODE="${5:-}"
	if [ -n "$FALSIFY_TICK" ]; then
		godot --headless --path "$PORT" -- --replay="$REC_PATH" --dump="$DUMP_PATH" \
			--falsify="$FALSIFY_TICK" --falsify-mode="$FALSIFY_MODE" >"$LOG_PATH" 2>&1
	else
		godot --headless --path "$PORT" -- --replay="$REC_PATH" --dump="$DUMP_PATH" >"$LOG_PATH" 2>&1
	fi
	echo $?
}

# Reads the first hunk's starting line number in the reference dump off
# its leading "NcM"/"NaM"/"NdM" range spec ($1 = a captured /usr/bin/diff
# output file), then reports the LAST "tick" header at or before that line
# in the reference dump ($2) -- the tick block the first divergence falls
# inside, whether the divergence itself lands on the header line or (as
# here, since the header carries only the tick number and the dropped
# count) an actor line beneath it.
extract_injected_tick() {
	DIFF_FILE="$1"
	REF_DUMP="$2"
	FIRST_LINE=$(/usr/bin/sed -n '1p' "$DIFF_FILE" | /usr/bin/sed -E 's/^([0-9]+).*/\1/')
	if [ -z "$FIRST_LINE" ]; then
		echo ""
		return
	fi
	/usr/bin/sed -n "1,${FIRST_LINE}p" "$REF_DUMP" | /usr/bin/grep '^tick	' | /usr/bin/sed -n '$p' \
		| /usr/bin/grep -oE 'tick=[0-9]+' | /usr/bin/sed -E 's/tick=//'
}

echo "replay_diff: recording ${TICKS} ticks..."
run_record "$REC" "$DUMP_A" "$REC_LOG"

echo "replay_diff: replaying (clean)..."
RC=$(run_replay "$REC" "$DUMP_B" "$REP_LOG")
if [ "$RC" -ne 0 ]; then
	echo "replay_diff	check=clean	verdict=FAIL	clean replay pass exited $RC -- see $REP_LOG"
	exit 1
fi
require_dump "$DUMP_B" "clean replay dump"

CLEAN_DIFF=$(/usr/bin/diff "$DUMP_A" "$DUMP_B")
if [ -z "$CLEAN_DIFF" ]; then
	echo "replay_diff	check=clean	verdict=PASS	$DUMP_A and $DUMP_B are byte-identical"
else
	echo "replay_diff	check=clean	verdict=FAIL	$DUMP_A and $DUMP_B differ -- see: /usr/bin/diff $DUMP_A $DUMP_B"
	OVERALL_FAIL=1
fi

if [ "$MODE" = "--control" ]; then
	for PMODE in nudge skip origin; do
		if [ "$PMODE" = "origin" ]; then
			TICK="$ORIGIN_PERTURB_TICK"
		else
			TICK="$PERTURB_TICK"
		fi
		PDUMP="/tmp/replay_diff_${PMODE}.dump"
		PLOG="/tmp/replay_diff_${PMODE}.log"
		PDIFF="/tmp/replay_diff_${PMODE}.diff"
		echo "replay_diff: replaying (perturbation mode=${PMODE}, tick=${TICK})..."
		RC=$(run_replay "$REC" "$PDUMP" "$PLOG" "$TICK" "$PMODE")
		if [ "$RC" -ne 0 ]; then
			echo "replay_diff	check=control-${PMODE}	verdict=FAIL	perturbation replay pass exited $RC -- see $PLOG"
			OVERALL_FAIL=1
			continue
		fi
		require_dump "$PDUMP" "perturbation (${PMODE}) replay dump"
		/usr/bin/diff "$DUMP_A" "$PDUMP" >"$PDIFF"
		if [ ! -s "$PDIFF" ]; then
			echo "replay_diff	check=control-${PMODE}	verdict=FAIL	comparison stayed empty -- the ${PMODE} perturbation did not change the outcome"
			OVERALL_FAIL=1
			continue
		fi
		GOT_TICK=$(extract_injected_tick "$PDIFF" "$DUMP_A")
		if [ -z "$GOT_TICK" ]; then
			echo "replay_diff	check=control-${PMODE}	verdict=FAIL	could not extract a tick from the first hunk of the perturbation comparison -- see $PDIFF"
			OVERALL_FAIL=1
			continue
		fi
		if [ "$GOT_TICK" = "$TICK" ]; then
			echo "replay_diff	check=control-${PMODE}	verdict=PASS	perturbation injected=${TICK}	first_diff_tick=${GOT_TICK}"
		else
			echo "replay_diff	check=control-${PMODE}	verdict=FAIL	perturbation injected=${TICK}	first_diff_tick=${GOT_TICK}	tick mismatch"
			OVERALL_FAIL=1
		fi
	done
fi

echo "replay_diff: checking a missing recording fails loudly..."
MISSING_LOG=/tmp/replay_diff_missing.log
MISSING_DUMP=/tmp/replay_diff_missing.dump
MISSING_REC=/tmp/replay_diff_does_not_exist.rec
rm -f "$MISSING_DUMP"
RC=$(run_replay "$MISSING_REC" "$MISSING_DUMP" "$MISSING_LOG")
if [ "$RC" -eq 0 ]; then
	echo "replay_diff	check=missing-recording	verdict=FAIL	replay against a nonexistent recording exited 0 -- should have failed"
	OVERALL_FAIL=1
elif /usr/bin/grep -q 'cannot open' "$MISSING_LOG"; then
	echo "replay_diff	check=missing-recording	verdict=PASS	exited $RC and named the unreadable file"
else
	echo "replay_diff	check=missing-recording	verdict=FAIL	exited $RC but did not name the unreadable file -- see $MISSING_LOG"
	OVERALL_FAIL=1
fi

if [ "$OVERALL_FAIL" -eq 1 ]; then
	echo "replay_diff: overall verdict=FAIL"
	exit 1
fi
echo "replay_diff: overall verdict=PASS"
