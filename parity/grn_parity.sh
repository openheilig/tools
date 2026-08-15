#!/bin/sh
# grn_parity.sh -- cross-checks the two INDEPENDENTLY WRITTEN .GRN tag
# walkers at corpus level:
#
#   godot-port/parity/grnwalk.gd --corpus       (GDScript, written first)
#   analysis/tools/formats/grn_tagwalk.py --corpus  (Python, written from
#                                             direct byte evidence
#                                             alone, never from the GDScript
#                                             source)
#
# The value of this comparison is precisely that the two implementations
# never read each other -- the Python file's own header states it was
# built from a written specification and direct byte reads of
# install/pak/models.pak, never by opening or translating grnwalk.gd. If a
# mismatch is ever found here, DO NOT resolve it by editing either walker to
# imitate the other; trace it to install/pak/models.pak's actual bytes and
# fix the implementation that reads them wrong. A green result obtained by
# copying one side onto the other measures nothing.
#
# Compares named numbers extracted from each sweep's report, not raw text --
# the two reports use a different field order for the tagcount line, so a
# byte diff would report false mismatches on
# formatting alone. Every extraction that comes back empty is a hard
# failure: two empty extractions would otherwise compare equal and this
# script would certify agreement while comparing nothing.
#
#   sh analysis/tools/parity/grn_parity.sh
#   SACRED_INSTALL=/path/to/install sh analysis/tools/parity/grn_parity.sh
#
# RTK shell hazard (CLAUDE.md): a Claude Code hook rewrites bare
# git/grep/wc/diff into a "rtk" wrapper with different output -- it once
# produced a false "PARITY OK" on this exact harness. Every tool
# invocation below uses an absolute path for that reason, not style.

set -u

ROOT=$(cd "$(dirname "$0")/../../.." && pwd)
PORT="$ROOT/godot-port"
INSTALL="${SACRED_INSTALL:-$ROOT/install}"

GD_OUT=/tmp/grn_parity_gd.txt
PY_OUT=/tmp/grn_parity_py.txt

OVERALL_FAIL=0

fail_missing() {
	# $1 = human label of what could not be read, $2 = source file
	echo "grn_parity: FAIL could not read $1 (see $2)"
	exit 1
}

require_field() {
	# $1 = extracted value, $2 = key name, $3 = source label
	if [ -z "$1" ]; then
		fail_missing "'$2' from $3" "$3"
	fi
}

compare() {
	# $1 = key label, $2 = gd value, $3 = py value
	if [ "$2" = "$3" ]; then
		echo "compare	$1	gd=$2	py=$3	verdict=MATCH"
	else
		echo "compare	$1	gd=$2	py=$3	verdict=MISMATCH"
		OVERALL_FAIL=1
	fi
}

echo "grn_parity: sweeping GDScript walker (grnwalk.gd --corpus)..."
timeout 900 godot --headless --path "$PORT" --script res://parity/grnwalk.gd -- --corpus --install="$INSTALL" \
	>"$GD_OUT" 2>&1
GD_RC=$?

echo "grn_parity: sweeping Python walker (grn_tagwalk.py --corpus)..."
SACRED_INSTALL="$INSTALL" python3 "$ROOT/analysis/tools/formats/grn_tagwalk.py" --corpus >"$PY_OUT" 2>&1
PY_RC=$?

if [ "$GD_RC" -ne 0 ]; then
	echo "grn_parity: FAIL godot sweep exited $GD_RC -- see $GD_OUT"
	OVERALL_FAIL=1
fi
if [ "$PY_RC" -ne 0 ]; then
	echo "grn_parity: FAIL python sweep exited $PY_RC -- see $PY_OUT"
	OVERALL_FAIL=1
fi
if [ "$OVERALL_FAIL" -eq 1 ]; then
	echo "grn_parity: overall verdict=FAIL (a sweep did not complete -- see the file(s) named above)"
	exit 1
fi

GD_CORPUS_LINE=$(/usr/bin/grep '^corpus' "$GD_OUT" | /usr/bin/sed -n '1p')
PY_CORPUS_LINE=$(/usr/bin/grep '^corpus' "$PY_OUT" | /usr/bin/sed -n '1p')
require_field "$GD_CORPUS_LINE" "corpus line" "$GD_OUT"
require_field "$PY_CORPUS_LINE" "corpus line" "$PY_OUT"

# names= is a digest over every entry's "<index>:<name>", added 2026-08-15:
# both walkers printed names and neither compared them, so truncating the name
# field passed this gate.
for KEY in entries walkable skipped; do
	GD_VAL=$(printf '%s' "$GD_CORPUS_LINE" | /usr/bin/grep -o "${KEY}=[0-9]*" | /usr/bin/cut -d= -f2)
	PY_VAL=$(printf '%s' "$PY_CORPUS_LINE" | /usr/bin/grep -o "${KEY}=[0-9]*" | /usr/bin/cut -d= -f2)
	require_field "$GD_VAL" "$KEY (godot corpus line)" "$GD_OUT"
	require_field "$PY_VAL" "$KEY (python corpus line)" "$PY_OUT"
	compare "$KEY" "$GD_VAL" "$PY_VAL"
done

GD_NAMES=$(printf '%s' "$GD_CORPUS_LINE" | /usr/bin/grep -o 'names=[0-9a-f]*' | /usr/bin/cut -d= -f2)
PY_NAMES=$(printf '%s' "$PY_CORPUS_LINE" | /usr/bin/grep -o 'names=[0-9a-f]*' | /usr/bin/cut -d= -f2)
require_field "$GD_NAMES" "names digest (godot corpus line)" "$GD_OUT"
require_field "$PY_NAMES" "names digest (python corpus line)" "$PY_OUT"
compare "names" "$GD_NAMES" "$PY_NAMES"


# The four documented tags only (root/copyright/object/final) -- the leaf
# tag families and the terminator are out of this comparison's scope: the
# two sides count the terminator tag differently, a known and separately
# documented difference (findings log row 397).
for TAG in 0xca5e0000 0xca5e0101 0xca5e0102 0xca5e0103; do
	GD_LINE=$(/usr/bin/grep -E "^tagcount[[:space:]]+${TAG}[[:space:]]" "$GD_OUT" | /usr/bin/sed -n '1p')
	PY_LINE=$(/usr/bin/grep -E "^tagcount[[:space:]]+${TAG}[[:space:]]" "$PY_OUT" | /usr/bin/sed -n '1p')
	require_field "$GD_LINE" "tagcount line for $TAG" "$GD_OUT"
	require_field "$PY_LINE" "tagcount line for $TAG" "$PY_OUT"
	for KEY in files total; do
		GD_VAL=$(printf '%s' "$GD_LINE" | /usr/bin/grep -o "${KEY}=[0-9]*" | /usr/bin/cut -d= -f2)
		PY_VAL=$(printf '%s' "$PY_LINE" | /usr/bin/grep -o "${KEY}=[0-9]*" | /usr/bin/cut -d= -f2)
		require_field "$GD_VAL" "$KEY for $TAG (godot tagcount line)" "$GD_OUT"
		require_field "$PY_VAL" "$KEY for $TAG (python tagcount line)" "$PY_OUT"
		compare "${TAG}.${KEY}" "$GD_VAL" "$PY_VAL"
	done
done

if [ "$OVERALL_FAIL" -eq 1 ]; then
	echo "grn_parity: overall verdict=FAIL (see MISMATCH line(s) above)"
	exit 1
fi
echo "grn_parity: overall verdict=PASS -- entries/walkable/skipped and the 4 documented tags' files=/total= agree between grnwalk.gd and grn_tagwalk.py"
