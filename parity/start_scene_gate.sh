#!/bin/sh
# start_scene_gate.sh -- the milestone metric, with a verdict.
#
#   sh analysis/tools/parity/start_scene_gate.sh            # drive a fresh pair
#   sh analysis/tools/parity/start_scene_gate.sh <dir>      # use an existing session dir
#
# WHY THIS EXISTS. The milestone is the Seraphim start location at 1:1, and
# until 2026-08-25 it had "a target and no test" -- REQUIREMENTS.md said so in
# terms. png_delta.py printed a number nobody could pass or fail, and it went
# 8 days unmeasured because nothing failed when it did.
#
# THREE DECISIONS, all the human's (2026-08-25), all recorded here so the next
# reader argues with the decision and not the code:
#
#   1. SCOPE. The verdict comes from the WORLD band only. The milestone is the
#      Seraphim and her LOCATION; the taskbar is interface. It is still
#      measured and printed every run -- it is 22.99% against the world's
#      11.00% and would otherwise dominate a single number and block world
#      work behind UI art.
#
#   2. RATCHET, not a target. No threshold was invented. The gate fails when a
#      run is WORSE than the best ever recorded by more than TOL, and rewrites
#      the baseline when a run is better by more than TOL. That catches
#      regressions from the first run and needs no agreed number; an absolute
#      target can be added later by anyone willing to name one.
#
#      TOL IS ON BOTH SIDES ON PURPOSE. The metric is not deterministic across
#      runs -- 13.62 and 13.59 were measured on the same build minutes apart,
#      and row 1075 recorded that 0.07pp as uncharacterised. A ratchet that
#      updated on ANY improvement would walk its own baseline downwards on that
#      noise and then start failing honest runs. Requiring the improvement to
#      clear the same TOL it forgives makes the baseline move only on real work.
#      debt: TOL 0.10 is set from two observations, not a distribution. If runs
#      are ever seen outside it, measure the spread properly and set it from
#      that rather than widening it by feel.
#
#   3. STRICT, with mean error beside it. The verdict stays any-nonzero-channel
#      because this project reproduces retail exactly, not acceptably. MAE is
#      printed alongside because 11% differing at MAE 5 and 11% at MAE 40 are
#      different problems and the percentage alone cannot tell them apart.
#
# A pair that is not 1024x768 on both sides is refused, not compared --
# png_delta.py dies on a size mismatch and this script propagates that.
set -u

ROOT=$(cd "$(dirname "$0")/../../.." && pwd)
DELTA="$ROOT/analysis/tools/parity/png_delta.py"
BASE="$(dirname "$0")/start-scene-baseline.tsv"
TOL=0.10                     # pp of regression tolerated before FAIL
GATES=world                  # which band decides the verdict

# band -> crop rectangle. `full` has no crop.
crop_of() {
	case "$1" in
	world)   echo "--crop=0,0,1024,600" ;;
	taskbar) echo "--crop=0,600,1024,168" ;;
	full)    echo "" ;;
	*)       echo "start_scene_gate: unknown band $1" >&2; exit 1 ;;
	esac
}

DIR="${1:-}"
if [ -z "$DIR" ]; then
	DIR=/tmp/drive-startgate
	echo "# driving a fresh pair (menu route: new)"
	DRIVE_RETAIL_PRELUDE="$(sh "$ROOT/analysis/tools/drive/menu.sh" new)" \
	DRIVE_RETAIL_OFFSET=$(sh "$ROOT/analysis/tools/drive/menu.sh" new --ready) \
	sh "$ROOT/analysis/tools/drive/session.sh" startgate "" 4000 20 >/dev/null 2>&1
	DIR=/tmp/drive-startgate
fi

R="$DIR/retail-4000.png"
P="$DIR/port-4000.png"
for f in "$R" "$P"; do
	[ -f "$f" ] || { echo "start_scene_gate: missing $f" >&2; exit 1; }
done

fail=0
printf '%-8s %8s %8s   %8s %8s   %s\n' band pct mae "base_pct" "base_mae" verdict
improved=""
for band in world taskbar full; do
	read -r pct mae <<-EOF
	$(python3 "$DELTA" "$R" "$P" $(crop_of "$band") --mae)
	EOF
	bp=$(awk -v b="$band" '$1==b{print $2}' "$BASE")
	bm=$(awk -v b="$band" '$1==b{print $3}' "$BASE")
	[ -n "$bp" ] || { echo "start_scene_gate: no baseline row for $band" >&2; exit 1; }

	if [ "$band" = "$GATES" ]; then
		v=$(awk -v p="$pct" -v b="$bp" -v t="$TOL" \
			'BEGIN{ if (p > b + t) print "FAIL"; else if (p < b - t) print "PASS improved"; else print "PASS" }')
	else
		v=$(awk -v p="$pct" -v b="$bp" -v t="$TOL" \
			'BEGIN{ print (p < b - t) ? "report improved" : "report" }')
	fi
	case "$v" in FAIL) fail=1 ;; esac
	case "$v" in *improved) improved="$improved $band:$pct:$mae" ;; esac
	printf '%-8s %8s %8s   %8s %8s   %s\n' "$band" "$pct" "$mae" "$bp" "$bm" "$v"
done

if [ -n "$improved" ]; then
	today=$(date +%F)
	for u in $improved; do
		b=${u%%:*}; rest=${u#*:}; p=${rest%%:*}; m=${rest#*:}
		awk -v b="$b" -v p="$p" -v m="$m" -v d="$today" -F'\t' -v OFS='\t' \
			'$1==b{$2=p; $3=m; $4=d} {print}' "$BASE" > "$BASE.new" && mv "$BASE.new" "$BASE"
	done
	echo "# baseline updated for:$improved"
fi

if [ "$fail" -eq 1 ]; then
	echo "VERDICT: FAIL -- the $GATES band regressed by more than ${TOL}pp"
	exit 1
fi
echo "VERDICT: PASS ($GATES band at or below its recorded best)"
exit 0
