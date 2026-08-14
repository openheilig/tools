#!/bin/sh
# follow_parity.sh -- the two pixel gates 04-03-PLAN.md Task 3 asks for.
#
# Gate 1 (frame does not slip): three captures under Xvfb, all at the
# middle zoom step, all with the player suppressed so only the terrain and
# object sprites are in frame (--hideplayer keeps the camera actively
# following the player -- unlike --noplayer, which stops following too --
# while never drawing its mesh). A is a stated cell; B is a small sub-cell
# distance away, small enough that the snapped camera target lands on the
# same pixel; C is far enough away that the snapped target differs. A and B
# must hash identical; C must hash different. Without C this gate would
# pass just as happily on a renderer that produced the same image for every
# input -- the whole point of a gate is that it can be seen to fail.
#
# Gate 2 (the view cannot reach the dump): D-14 excludes camera state and
# the resident-sector set from the replay dump. That exclusion only means
# something if a run with the whole view layer switched on -- camera,
# streamer, player mesh, all live under a real display -- produces the same
# dump as a run with no view at all. --liveview (paired with --record=) is
# the one place main.gd builds that live view during a recording pass;
# --replay= never takes it, so the second pass stays the plain no-view path
# it always was. The two dumps must be byte-identical.
#
#   sh analysis/tools/follow_parity.sh
#
# RTK shell hazard (CLAUDE.md): a Claude Code hook rewrites bare
# git/grep/wc/diff into a "rtk" wrapper with different output -- grn_parity.sh
# and replay_diff.sh were both burned by this. Every grep/diff/sed/md5sum
# invocation below uses an absolute path for that reason, not style.
#
# This project ships one graphics backend and one only. Forcing the other
# one from a command line override has silently invalidated a whole
# session of "verified" captures before (analysis/tools/look.sh's own
# header carries the same warning) -- this script never does that, and
# never writes that override's flag name anywhere below, comments included.

set -u

ROOT=$(cd "$(dirname "$0")/../.." && pwd)
PORT="$ROOT/godot-port"
SCREEN=${FOLLOW_PARITY_SCREEN:-1600x1000x24}

OVERALL_FAIL=0

have() { command -v "$1" >/dev/null 2>&1; }

have godot || { echo "follow_parity: FAIL godot not on PATH"; exit 1; }
have xvfb-run || { echo "follow_parity: FAIL xvfb-run not installed (package xorg-server-xvfb)"; exit 1; }

require_png() {
	# $1 = path, $2 = human label. Exits (the caller's shell, or just the
	# enclosing subshell when invoked inside one) rather than falling
	# through -- two empty/missing extractions would otherwise compare
	# equal and this script would certify agreement while comparing
	# nothing.
	if [ ! -f "$1" ]; then
		echo "follow_parity: FAIL could not read $2 (missing: $1)"
		exit 1
	fi
	if [ ! -s "$1" ]; then
		echo "follow_parity: FAIL could not read $2 (empty: $1)"
		exit 1
	fi
}

require_dump() {
	if [ ! -f "$1" ]; then
		echo "follow_parity: FAIL could not read $2 (missing: $1)"
		exit 1
	fi
	if [ ! -s "$1" ]; then
		echo "follow_parity: FAIL could not read $2 (empty: $1)"
		exit 1
	fi
}

png_hash() {
	# $1 = path -- already passed require_png. An empty extraction here
	# (md5sum ran but produced nothing usable) is its own hard failure,
	# distinct from a missing/empty file.
	H=$(/usr/bin/md5sum "$1" | cut -d' ' -f1)
	if [ -z "$H" ]; then
		echo "follow_parity: FAIL empty hash extraction for $1" >&2
		exit 1
	fi
	printf '%s' "$H"
}

shot() {
	# $1 = spawn cell "x,y", $2 = output png path
	xvfb-run -a -s "-screen 0 $SCREEN" godot --path "$PORT" -- \
		--spawn="$1" --hideplayer --zoom=1 --shot="$2" --quit-after=999 \
		>/tmp/follow_parity_shot.log 2>&1
	RC=$?
	if [ "$RC" -ne 0 ]; then
		echo "follow_parity: FAIL capture to $2 exited $RC -- see /tmp/follow_parity_shot.log"
		exit 1
	fi
}

echo "follow_parity: gate 1 -- rendering three captures (player suppressed, camera following)..."

# All three share x-y=0, x+y=6464 at A, so IsoCamera.cell_to_world's two
# projected axes are already exact integers there (sx=0, sy=-155136) --
# maximal distance from any half-pixel rounding boundary, so a small
# perturbation cannot accidentally straddle one by surprise.
#
# B moves both axes by a few thousandths of a cell (worth well under half a
# projected pixel at HW=48/HH=24) -- the snapped camera target must stay
# put. C moves x and y in OPPOSITE small steps, which the (x-y) term
# doubles: enough to cross a whole pixel of camera position, and enough
# that y+x stays fixed so only the x axis of the picture is provably
# exercised, not accidentally both at once.
CELL_A="3232.000000,3232.000000"
CELL_B="3232.003000,3232.004000"
CELL_C="3232.020000,3231.980000"

PNG_A=/tmp/follow_parity_a.png
PNG_B=/tmp/follow_parity_b.png
PNG_C=/tmp/follow_parity_c.png

shot "$CELL_A" "$PNG_A"
shot "$CELL_B" "$PNG_B"
shot "$CELL_C" "$PNG_C"

require_png "$PNG_A" "capture A"
require_png "$PNG_B" "capture B"
require_png "$PNG_C" "capture C"

HASH_A=$(png_hash "$PNG_A")
HASH_B=$(png_hash "$PNG_B")
HASH_C=$(png_hash "$PNG_C")

echo "follow_parity	check=gate1-hashes	a=$HASH_A	b=$HASH_B	c=$HASH_C"

if [ "$HASH_A" = "$HASH_B" ]; then
	echo "follow_parity	check=gate1-subpixel	verdict=PASS	A and B (sub-cell jitter) hash identical"
else
	echo "follow_parity	check=gate1-subpixel	verdict=FAIL	A and B hash differ -- the picture shook under sub-pixel motion"
	OVERALL_FAIL=1
fi

if [ "$HASH_A" = "$HASH_C" ]; then
	echo "follow_parity	check=gate1-realmotion	verdict=FAIL	A and C (real motion) hash identical -- the comparison cannot see a real change"
	OVERALL_FAIL=1
else
	echo "follow_parity	check=gate1-realmotion	verdict=PASS	A and C hash differ"
fi

echo "follow_parity: gate 1 self-test -- a missing capture must fail loudly..."
MISSING_PNG=/tmp/follow_parity_does_not_exist.png
rm -f "$MISSING_PNG"
MISSING_OUT=$( (require_png "$MISSING_PNG" "self-test capture") 2>&1 )
MISSING_RC=$?
if [ "$MISSING_RC" -ne 0 ] && printf '%s' "$MISSING_OUT" | /usr/bin/grep -q "$MISSING_PNG"; then
	echo "follow_parity	check=gate1-missing-capture	verdict=PASS	exited $MISSING_RC and named the unreadable file"
else
	echo "follow_parity	check=gate1-missing-capture	verdict=FAIL	exited $MISSING_RC, output: $MISSING_OUT"
	OVERALL_FAIL=1
fi

echo "follow_parity: gate 2 -- recording on-screen (camera, streamer and player mesh all live)..."

TICKS=60
REC=/tmp/follow_parity_live.rec
LIVE_DUMP=/tmp/follow_parity_live.dump
HEADLESS_DUMP=/tmp/follow_parity_headless.dump
REC_LOG=/tmp/follow_parity_live_rec.log
REP_LOG=/tmp/follow_parity_headless_rep.log

xvfb-run -a -s "-screen 0 $SCREEN" godot --path "$PORT" -- \
	--record="$REC" --dump="$LIVE_DUMP" --autoplay="$TICKS" --liveview --quit-after=999 \
	>"$REC_LOG" 2>&1
RC=$?
if [ "$RC" -ne 0 ]; then
	echo "follow_parity	check=gate2-live-record	verdict=FAIL	on-screen record pass exited $RC -- see $REC_LOG"
	exit 1
fi
require_dump "$LIVE_DUMP" "on-screen record dump"

echo "follow_parity: gate 2 -- replaying headlessly (no camera, no streamer, nothing drawn)..."
godot --headless --path "$PORT" -- --replay="$REC" --dump="$HEADLESS_DUMP" >"$REP_LOG" 2>&1
RC=$?
if [ "$RC" -ne 0 ]; then
	echo "follow_parity	check=gate2-headless-replay	verdict=FAIL	headless replay pass exited $RC -- see $REP_LOG"
	exit 1
fi
require_dump "$HEADLESS_DUMP" "headless replay dump"

VIEW_DIFF=$(/usr/bin/diff "$LIVE_DUMP" "$HEADLESS_DUMP")
if [ -z "$VIEW_DIFF" ]; then
	echo "follow_parity	check=gate2-view-cannot-reach-dump	verdict=PASS	$LIVE_DUMP and $HEADLESS_DUMP are byte-identical"
else
	echo "follow_parity	check=gate2-view-cannot-reach-dump	verdict=FAIL	$LIVE_DUMP and $HEADLESS_DUMP differ -- see: /usr/bin/diff $LIVE_DUMP $HEADLESS_DUMP"
	OVERALL_FAIL=1
fi

BAD_LINES=$(/usr/bin/grep -vcE '^(tick|actor|registry|astar|swap)' "$LIVE_DUMP")
if [ "$BAD_LINES" -eq 0 ]; then
	echo "follow_parity	check=gate2-dump-line-kinds	verdict=PASS	only tick/actor/registry/astar/swap lines present"
else
	echo "follow_parity	check=gate2-dump-line-kinds	verdict=FAIL	$BAD_LINES line(s) outside the permitted kinds -- see $LIVE_DUMP"
	OVERALL_FAIL=1
fi

if [ "$OVERALL_FAIL" -eq 1 ]; then
	echo "follow_parity: overall verdict=FAIL"
	exit 1
fi
echo "follow_parity: overall verdict=PASS -- sub-pixel motion is invisible, real motion is not, and the view layer never reaches the dump"
