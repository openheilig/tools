#!/bin/sh
# verify_parity.sh -- run both reader implementations and return a VERDICT.
#
#   sh analysis/tools/parity/verify_parity.sh
#   SACRED_INSTALL=... SACRED_PORT=... sh .../verify_parity.sh
#
# WHY THIS EXISTS. verify_ref.py and verify.gd are the project's flagship
# "two independent decoders agree" gate -- pak indices, sectors, textures,
# models, motions, bones, walkability. Until 2026-08-15 they were compared by
# a human running diff by hand and deciding which lines were cosmetic. Every
# other gate in this project exits 0 or 1; this one, the one the format
# documents cite as their provenance, did not.
#
# EXACTLY TWO DIFFERENCES ARE NORMALISED, and both are stated so that a third
# one cannot be waved through:
#
#   1. verify.gd prints `install <absolute path>`. It is an environment fact,
#      not a decode fact, and the path differs per machine.
#   2. verify.gd's texture lines carry a trailing `<N> us` decode timing.
#      Nondeterministic by nature.
#
# Everything else must match BYTE FOR BYTE. A new fact line added to one side
# only is a MISMATCH, not an omission: the key census below fails on it rather
# than quietly comparing the intersection.
set -u

ROOT=$(cd "$(dirname "$0")/../../.." && pwd)
INSTALL="${SACRED_INSTALL:-$ROOT/install}"
PORT="${SACRED_PORT:-$ROOT/godot-port}"
PY_OUT=/tmp/verify_parity_py.txt
GD_OUT=/tmp/verify_parity_gd.txt
FAIL=0

[ -d "$INSTALL" ] || { echo "verify_parity: no install at $INSTALL (set SACRED_INSTALL)"; exit 1; }
[ -d "$PORT" ] || { echo "verify_parity: no engine at $PORT (set SACRED_PORT)"; exit 1; }

echo "verify_parity: running the Python reference..."
SACRED_INSTALL="$INSTALL" timeout 600 python3 "$(dirname "$0")/verify_ref.py" >"$PY_OUT" 2>/tmp/verify_parity_py.err
PY_RC=$?
echo "verify_parity: running the GDScript reader..."
# stdout only: Godot writes engine ERRORs to stderr, and verify.gd emits five
# of them for md5-of-empty on the deliberately empty samples. Merging them into
# the compared stream would make every run a mismatch.
timeout 600 godot --headless --path "$PORT" --script res://parity/verify.gd \
	>"$GD_OUT" 2>/tmp/verify_parity_gd.err
GD_RC=$?

[ "$PY_RC" -eq 0 ] || { echo "verify_parity: FAIL python exited $PY_RC -- see $PY_OUT"; FAIL=1; }
[ "$GD_RC" -eq 0 ] || { echo "verify_parity: FAIL godot exited $GD_RC -- see $GD_OUT"; FAIL=1; }
[ "$FAIL" -eq 1 ] && { echo "verify_parity: overall verdict=FAIL (a side did not complete)"; exit 1; }

# The two documented normalisations, and nothing else.
norm() {
	/usr/bin/grep -v '^Godot Engine' "$1" \
		| /usr/bin/grep -v '^install	' \
		| /usr/bin/sed 's/	[0-9][0-9]* us$//' \
		| /usr/bin/grep -v '^$'
}
norm "$PY_OUT" >/tmp/verify_parity_py.norm
norm "$GD_OUT" >/tmp/verify_parity_gd.norm

# A fact line present on one side only must fail, not be skipped.
PY_KEYS=$(/usr/bin/awk '{print $1}' /tmp/verify_parity_py.norm | /usr/bin/sort -u | /usr/bin/tr '\n' ' ')
GD_KEYS=$(/usr/bin/awk '{print $1}' /tmp/verify_parity_gd.norm | /usr/bin/sort -u | /usr/bin/tr '\n' ' ')
if [ "$PY_KEYS" != "$GD_KEYS" ]; then
	echo "verify_parity: MISMATCH fact kinds differ"
	echo "  python: $PY_KEYS"
	echo "  godot : $GD_KEYS"
	FAIL=1
fi

# NON-VACUITY. Four of the seven walkable samples carry regions=0, so their
# md5 is the md5 of nothing on both sides and they can only catch a reader
# INVENTING data, never one misreading it (measured 2026-08-15). The three
# that carry regions are the whole informative content of this fact kind, so
# the gate fails if that number ever drops -- a sample list quietly degrading
# to all-empty would otherwise still report PASS.
INFORMATIVE=$(/usr/bin/awk '$1=="walkable" && $0 !~ /regions=0\t/ {n++} END{print n+0}' /tmp/verify_parity_py.norm)
if [ "$INFORMATIVE" -lt 3 ]; then
	echo "verify_parity: FAIL only $INFORMATIVE walkable sample(s) carry any region -- the rest compare md5-of-nothing"
	FAIL=1
fi

PY_N=$(/usr/bin/awk 'END{print NR}' /tmp/verify_parity_py.norm)
GD_N=$(/usr/bin/awk 'END{print NR}' /tmp/verify_parity_gd.norm)
# A gate that would pass on two empty files is not a gate.
if [ "$PY_N" -lt 20 ]; then
	echo "verify_parity: FAIL only $PY_N fact lines -- too few to mean anything"
	FAIL=1
fi

if /usr/bin/diff -q /tmp/verify_parity_py.norm /tmp/verify_parity_gd.norm >/dev/null; then
	echo "verify_parity: $PY_N fact lines identical on both sides"
else
	echo "verify_parity: MISMATCH -- differing lines follow (< python, > godot)"
	/usr/bin/diff /tmp/verify_parity_py.norm /tmp/verify_parity_gd.norm | /usr/bin/head -40
	FAIL=1
fi

if [ "$FAIL" -eq 0 ]; then
	echo "verify_parity: overall verdict=PASS -- $PY_N lines, $PY_N/$GD_N, keys: $PY_KEYS, walkable samples with regions: $INFORMATIVE"
	exit 0
fi
echo "verify_parity: overall verdict=FAIL"
exit 1
