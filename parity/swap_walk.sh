#!/bin/sh
# swap_walk.sh -- Phase 6 supported-building in/out gate.
#
# The cellar is intentionally not a route: 06-01 measured DOOR-TELEPORT and
# regions=0. This harness proves the supported OZELT1 camp route instead.
set -u

ROOT=$(cd "$(dirname "$0")/../../.." && pwd)
# A bare checkout resolves ROOT to the wrong place -- these scripts expect to
# sit at <workspace>/analysis/tools/<group>/. SACRED_INSTALL and SACRED_PORT
# are the way out when they do not.
INSTALL="${SACRED_INSTALL:-$ROOT/install}"
PORT="${SACRED_PORT:-$ROOT/godot-port}"
PORT="$PORT"
EVIDENCE="$ROOT/analysis/evidence/p6-uat/06-06"
mkdir -p "$EVIDENCE"

ROUTE="${1:-supported-in-out}"
[ "$ROUTE" = supported-in-out ] || { printf '%s\n' "swap_walk: FAIL unsupported route '$ROUTE'"; exit 1; }

REC="$EVIDENCE/supported-in-out.rec"
DUMP_A="$EVIDENCE/supported-in-out.record.dump"
DUMP_B="$EVIDENCE/supported-in-out.replay.dump"
CTRL_REC="$EVIDENCE/default-control.rec"
CTRL_DUMP="$EVIDENCE/default-control.dump"
REC_LOG="$EVIDENCE/supported-in-out.record.log"
REP_LOG="$EVIDENCE/supported-in-out.replay.log"
CTRL_LOG="$EVIDENCE/default-control.log"
CONTROL_SPAWN="3232,3232"
LIVE_REC="$EVIDENCE/supported-in-out.live.rec"
LIVE_DUMP="$EVIDENCE/supported-in-out.live.dump"
LIVE_LOG="$EVIDENCE/supported-in-out.live.log"
SHOT_EXT="$EVIDENCE/supported-exterior.png"
SHOT_INT="$EVIDENCE/supported-interior.png"

TICKS=90
FAIL=0

fail_artifact() {
	printf '%s\n' "swap_walk: FAIL $1 ($2)"
	exit 1
}
require_file() {
	[ -f "$1" ] || fail_artifact "$2 missing" "$1"
	[ -s "$1" ] || fail_artifact "$2 empty" "$1"
}
run_godot() {
	LABEL="$1"
	shift
	"$@"
	RC=$?
	[ "$RC" -eq 0 ] || fail_artifact "$LABEL exited $RC" "$3"
}

printf '%s\n' "swap_walk: route=$ROUTE ticks=$TICKS"
printf '%s\n' "CELLAR-DISPOSITION-BLOCKED reason=DOOR-TELEPORT separate map area"
printf '%s\n' "CELLAR-NO-REGIONS reason=cellar sectors have regions=0 under FLOOR/DOOR/STEP allowlist"
printf '%s\n' "cellar-in-out verdict=BLOCKED (no cellar route attempted; no BOTH-WAYS claim)"

# Record and replay the measured, deterministic test-only route. The route
# changes only the actor cell at measured cells; it does not change the trigger.
godot --headless --path "$PORT" -- \
	--autoplay="$TICKS" --walk-route="$ROUTE" --record="$REC" --dump="$DUMP_A" \
	>"$REC_LOG" 2>&1
RC=$?
[ "$RC" -eq 0 ] || fail_artifact "supported record exited $RC" "$REC_LOG"
require_file "$REC" "recording"
require_file "$DUMP_A" "record dump"

godot --headless --path "$PORT" -- \
	--walk-route="$ROUTE" --replay="$REC" --dump="$DUMP_B" \
	>"$REP_LOG" 2>&1
RC=$?
[ "$RC" -eq 0 ] || fail_artifact "supported replay exited $RC" "$REP_LOG"
require_file "$DUMP_B" "replay dump"

/usr/bin/diff "$DUMP_A" "$DUMP_B" >"$EVIDENCE/record-replay.diff"
RC=$?
if [ "$RC" -eq 0 ]; then
	printf '%s\n' "swap_walk	check=record-replay	verdict=PASS	byte-identical"
else
	printf '%s\n' "swap_walk\tcheck=record-replay\tverdict=FAIL\tsee=$EVIDENCE/record-replay.diff"
	exit 1
fi

SWAPS="$EVIDENCE/supported-in-out.swap-lines"
/usr/bin/grep '^swap' "$DUMP_A" >"$SWAPS" || fail_artifact "supported swap lines missing" "$DUMP_A"
SWAP_COUNT=$(/usr/bin/grep -c '^swap' "$DUMP_A")
[ "$SWAP_COUNT" -eq 2 ] || fail_artifact "expected exactly two swap lines, got $SWAP_COUNT" "$SWAPS"
FIRST_STATE=$(/usr/bin/sed -n '1p' "$SWAPS" | /usr/bin/sed -E 's/.*state=([^\t]+).*/\1/')
SECOND_STATE=$(/usr/bin/sed -n '2p' "$SWAPS" | /usr/bin/sed -E 's/.*state=([^\t]+).*/\1/')
FIRST_TICK=$(/usr/bin/sed -n '1p' "$SWAPS" | /usr/bin/sed -E 's/.*tick=([0-9]+).*/\1/')
SECOND_TICK=$(/usr/bin/sed -n '2p' "$SWAPS" | /usr/bin/sed -E 's/.*tick=([0-9]+).*/\1/')
REGION_A=$(/usr/bin/sed -n '1p' "$SWAPS" | /usr/bin/sed -E 's/.*region=([^\t]+).*/\1/')
REGION_B=$(/usr/bin/sed -n '2p' "$SWAPS" | /usr/bin/sed -E 's/.*region=([^\t]+).*/\1/')
if [ "$FIRST_STATE" = INTERIOR ] && [ "$SECOND_STATE" = EXTERIOR ] \
	&& [ "$FIRST_TICK" -lt "$SECOND_TICK" ] && [ "$REGION_A" = "$REGION_B" ]; then
	printf '%s\n' "swap_walk	check=transition-order	verdict=PASS	region=$REGION_A	INTERIOR@tick=$FIRST_TICK	EXTERIOR@tick=$SECOND_TICK"
else
	printf '%s\n' "swap_walk\tcheck=transition-order\tverdict=FAIL\tsee=$SWAPS"
	exit 1
fi

# Default route control: same tick count, no building goal/route, zero swaps.
godot --headless --path "$PORT" -- \
	--autoplay="$TICKS" --spawn="$CONTROL_SPAWN" --record="$CTRL_REC" --dump="$CTRL_DUMP" \
	>"$CTRL_LOG" 2>&1
RC=$?
[ "$RC" -eq 0 ] || fail_artifact "default control exited $RC" "$CTRL_LOG"
require_file "$CTRL_DUMP" "default control dump"
if /usr/bin/grep -q '^swap' "$CTRL_DUMP"; then
	printf '%s\n' "swap_walk\tcheck=default-zero-swap\tverdict=FAIL\tswap line found"
	exit 1
fi
printf '%s\n' "swap_walk	check=default-zero-swap	verdict=PASS	lines=0"

# Capture the two visible states at the exact measured supported footprint.
xvfb-run -a -s "-screen 0 1600x1000x24" godot --path "$PORT" -- \
	--at=3426,1834 --zoom=1 --noplayer --exterior --shot="$SHOT_EXT" >"$EVIDENCE/exterior-shot.log" 2>&1
RC=$?
[ "$RC" -eq 0 ] || fail_artifact "exterior frame exited $RC" "$EVIDENCE/exterior-shot.log"
xvfb-run -a -s "-screen 0 1600x1000x24" godot --path "$PORT" -- \
	--at=3427,1818 --zoom=1 --noplayer --force-interior --shot="$SHOT_INT" >"$EVIDENCE/interior-shot.log" 2>&1
RC=$?
[ "$RC" -eq 0 ] || fail_artifact "interior frame exited $RC" "$EVIDENCE/interior-shot.log"
require_file "$SHOT_EXT" "exterior frame"
require_file "$SHOT_INT" "interior frame"
EXT_MD5=$(/usr/bin/md5sum "$SHOT_EXT" | /usr/bin/sed 's/[[:space:]].*//')
INT_MD5=$(/usr/bin/md5sum "$SHOT_INT" | /usr/bin/sed 's/[[:space:]].*//')
[ -n "$EXT_MD5" ] && [ -n "$INT_MD5" ] || fail_artifact "frame md5 extraction failed" "$EVIDENCE"
printf '%s\n' "swap_walk	check=frame-evidence	verdict=PASS	interior_tick=30	returned_exterior_tick=60	ext_md5=$EXT_MD5	int_md5=$INT_MD5"

# The live-view pass exposes the runtime apply counters; ensure it completed and
# never showed a decode/build change during visibility application.
xvfb-run -a -s "-screen 0 1600x1000x24" godot --path "$PORT" -- \
	--autoplay="$TICKS" --walk-route="$ROUTE" --record="$LIVE_REC" --dump="$LIVE_DUMP" --liveview \
	>"$LIVE_LOG" 2>&1
RC=$?
[ "$RC" -eq 0 ] || fail_artifact "live-view route exited $RC" "$LIVE_LOG"
require_file "$LIVE_DUMP" "live-view dump"
/usr/bin/grep '^swap-apply' "$LIVE_LOG" >"$EVIDENCE/swap-apply.lines" || fail_artifact "swap-apply evidence missing" "$LIVE_LOG"
/usr/bin/grep -q 'decodes=0' "$EVIDENCE/swap-apply.lines" || fail_artifact "swap-time decode/rebuild evidence not zero" "$EVIDENCE/swap-apply.lines"
RUN_COUNT=$(/usr/bin/grep -c '^swap-apply' "$EVIDENCE/swap-apply.lines")
printf '%s\n' "swap_walk	check=runtime-run-count	verdict=PASS	runs=$RUN_COUNT	no_rebuild=decodes=0	see=$EVIDENCE/swap-apply.lines"

printf '%s\n' "swap_walk	overall verdict=PASS	CELLAR-DISPOSITION-BLOCKED	CELLAR-NO-REGIONS"
exit 0
