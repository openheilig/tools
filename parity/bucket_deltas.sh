#!/bin/sh
# bucket_deltas.sh -- masked per-bucket deltas for one session capture dir.
#
#   sh analysis/tools/parity/bucket_deltas.sh <session-dir>
#
# The world band and taskbar are start_scene_gate.sh's crops; the hero and NPC
# boxes are the measured figure extents in the settled start framing (hero
# 460,240 130x170 -- her body plus weapon; novizin 380,330 110,190 -- robe and
# blob). Each bucket answers one question: the world band is the milestone
# verdict, the hero box is the character pipeline, the NPC box is the quest
# cast, the taskbar is interface. Compare SCORES between runs, never pixels
# between engines (the noise floor is per bucket -- row 1104's 1.31pp retail
# run-to-run spread concentrates on the figure boxes).
set -u
ROOT=$(cd "$(dirname "$0")/../../.." && pwd)
DELTA="$ROOT/analysis/tools/parity/png_delta.py"
DIR="${1:?usage: bucket_deltas.sh <session-dir>}"

R="$DIR/retail-4000.png"
P="$DIR/port-4000.png"
for f in "$R" "$P"; do
	[ -f "$f" ] || { echo "bucket_deltas: missing $f" >&2; exit 1; }
done

bucket() {
	printf '%-8s %8s %8s\n' "$1" \
		"$(python3 "$DELTA" "$P" "$R" --crop="$2" 2>/dev/null)" \
		"$(python3 "$DELTA" "$P" "$R" --crop="$2" --mae 2>/dev/null | awk '{print $NF}')"
}
printf '%-8s %8s %8s\n' bucket pct mae
bucket world   0,0,1024,600
bucket taskbar 0,600,1024,168
bucket hero    460,240,130,170
bucket npc     380,330,110,190
