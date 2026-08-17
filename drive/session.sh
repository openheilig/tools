#!/bin/sh
# session.sh -- run ONE input script against BOTH engines and report what each
# one drew at the same milliseconds.
#
#   sh analysis/tools/drive/session.sh <label> "<script>" "<ms,ms,...>" [seconds] [port-args...]
#
#   sh analysis/tools/drive/session.sh chapel "1000 key iso_right 1500" 0,2000,4000
#   sh analysis/tools/drive/session.sh hero   ""                        0,3000 25 --sector=25,19
#
# The script grammar is autopilot.so's (`ms verb args`, semicolon-separated):
# move/click/hold/release/wheel/key. See ../shim/autopilot.c for the retail
# side and ../../../godot-port/drive.gd for the port side and its two
# additions (`key NAME MS` holds a key; `text` is refused).
#
# Everything lands in /tmp/drive-<label>:
#
#   port-<ms>.png     the port's frame at that ms
#   retail-<ms>.png   retail's frame at that ms
#   port.log          the port's FULL stderr -- errors and warnings included
#   retail.log        retail's own debug.log
#   report.md         per-ms table, pixel delta, and the error lines
#
# ⚠️ BOTH ENGINES CAPTURE AT 1024x768 AND NOTHING ELSE. Retail's grab is
# hard-coded to that size (autopilot.c shot_w/shot_h); the port is launched
# with --resolution 1024x768 and drive.gd refuses --shots= at any other size.
# Every pair is re-checked here before it is compared, because a delta between
# two differently-sized or differently-framed pictures is a number that means
# nothing and gets quoted anyway.
#
# ⚠️ THE TWO CLOCKS DO NOT SHARE AN ORIGIN. The port's t=0 is the first
# SETTLED frame; retail's t=0 is process start, which is minutes of menu
# before any world exists. DRIVE_RETAIL_OFFSET (default 8000) is added to
# every retail timestamp for exactly that reason. The comparison this script
# supports is "the same script, the same elapsed time"; it is NOT a claim that
# both engines are in the same game state, and no delta here should be read as
# a parity verdict. The pixel gates in ../parity/ are what return verdicts.
#
# ⚠️ NEVER passes a rendering-driver override. The project ships Forward+ /
# Vulkan; forcing the other backend silently invalidated a whole session of
# captures once (see look.sh's header).
#
# ponytail: no video, no alignment search, no retry. A missing retail half is
# reported and the port half still lands -- half a session beats none when the
# question is "what is the port drawing".

set -u
ROOT=$(cd "$(dirname "$0")/../../.." && pwd)
INSTALL="${SACRED_INSTALL:-$ROOT/install}"
PORT="${SACRED_PORT:-$ROOT/godot-port}"

W=1024
H=768

LABEL=${1:?usage: session.sh <label> "<script>" "<ms,ms,...>" [seconds] [port-args...]}
SCRIPT=${2:-}
SHOTS=${3:-0}
DUR=${4:-30}
[ $# -gt 4 ] && shift 4 || shift $#

OUT=/tmp/drive-$LABEL
RETAIL_OFFSET=${DRIVE_RETAIL_OFFSET:-8000}

# Absolute paths for grep/diff/sed/md5sum: a Claude Code hook rewrites the bare
# names into an "rtk" wrapper with different output, and two parity scripts in
# this repo were burned by it before (see parity/follow_parity.sh's header).
GREP=/usr/bin/grep

die() { printf '%s\n' "$*" >&2; exit 1; }
have() { command -v "$1" >/dev/null 2>&1; }

have godot     || die "session.sh: godot not on PATH"
have xvfb-run  || die "session.sh: xvfb-run not installed (package xorg-server-xvfb)"
have magick    || die "session.sh: ImageMagick 'magick' missing"

rm -rf "$OUT"
mkdir -p "$OUT"

# ---- port ------------------------------------------------------------------
# stderr is kept WHOLE. look.sh filters WARNING and stack-trace lines to keep
# its output readable; this harness exists to find out what is broken, and
# those are the lines that say so.
printf 'port: driving\n' >&2
xvfb-run -a -s "-screen 0 ${W}x${H}x24" \
	godot --resolution "${W}x${H}" --path "$PORT" -- \
	--drive="$SCRIPT" --shots="$SHOTS" --drive-out="$OUT" "$@" \
	>"$OUT/port.log" 2>&1
port_rc=$?

# ---- retail ----------------------------------------------------------------
# Same script, timestamps shifted past the menu. shot.sh owns the retail
# capture (autopilot.so preload, SACRED_AUTO, SACRED_SHOT, PPM->PNG); look.sh
# owns running it inside Xvfb so it does not steal a real display.
#
# `printf '%s\n'`, not `printf '%s'`: a final line with no newline is read into
# the variable AND returns non-zero, so `while read` exits before running the
# body on it. That silently dropped the last timestamp of every list -- the
# first smoke run scheduled one retail shot out of two and looked like retail
# had simply failed to capture.
retail_shots=$(printf '%s\n' "$SHOTS" | tr ',' '\n' |
	while read -r ms; do [ -n "$ms" ] && printf '%s,' "$((ms + RETAIL_OFFSET))"; done)
retail_shots=${retail_shots%,}
retail_script=$(printf '%s\n' "$SCRIPT" | tr ';' '\n' |
	while read -r st; do
		st=$(printf '%s' "$st" | sed 's/^ *//')
		[ -z "$st" ] && continue
		ms=${st%% *}
		printf '%s %s;' "$((ms + RETAIL_OFFSET))" "${st#* }"
	done)
retail_script=${retail_script%;}

# DRIVE_RETAIL_PRELUDE is prepended VERBATIM (never shifted): it is the menu
# walk that gets retail into a world before the shared script's t=0, and its
# timestamps are already absolute from process start. `drive/menu.sh <route>`
# writes one, and `menu.sh <route> --ready` gives the matching offset:
#
#   DRIVE_RETAIL_PRELUDE="$(sh .../menu.sh new)" \
#   DRIVE_RETAIL_OFFSET=$(sh .../menu.sh new --ready) sh session.sh ...
#
# Without it retail is still sitting on the main menu at t=0, the delta is
# ~100%, and it means nothing.
PRELUDE=${DRIVE_RETAIL_PRELUDE:-}
[ -n "$PRELUDE" ] && retail_script="$PRELUDE${retail_script:+; $retail_script}"

retail_ok=1
if [ -x "$INSTALL/play.sh" ]; then
	printf 'retail: driving (offset +%sms)\n' "$RETAIL_OFFSET" >&2
	sh "$ROOT/analysis/tools/drive/look.sh" retail \
		"$LABEL" "$retail_script" "$retail_shots" \
		"$((DUR + RETAIL_OFFSET / 1000))" >"$OUT/retail-run.log" 2>&1 || retail_ok=0
	cp -f "/tmp/shot-$LABEL/debug.log" "$OUT/retail.log" 2>/dev/null
	# autopilot.so's own trace -- how many shots it scheduled, when it fired
	# them, and the engine's fps. shot.sh keeps it apart from the game's log.
	cp -f "/tmp/shot-$LABEL/stdout.txt" "$OUT/retail-autopilot.log" 2>/dev/null
	for ms in $(printf '%s' "$SHOTS" | tr ',' ' '); do
		src="/tmp/shot-$LABEL/sacred-$((ms + RETAIL_OFFSET)).png"
		[ -f "$src" ] && cp -f "$src" "$OUT/retail-$ms.png"
	done
else
	retail_ok=0
	printf 'retail: SKIPPED (no %s/play.sh)\n' "$INSTALL" >&2
fi

# ---- report ----------------------------------------------------------------
# dims: "WxH", or "missing". Printed rather than assumed -- a pair that is not
# 1024x768 on both sides is refused below instead of being compared.
dims() { [ -f "$1" ] && magick identify -format '%wx%h' "$1" 2>/dev/null || printf 'missing'; }

{
	printf '# drive session: %s\n\n' "$LABEL"
	printf -- '- script: `%s`\n' "${SCRIPT:-<none>}"
	printf -- '- shots (ms): %s\n' "$SHOTS"
	printf -- '- port exit: %s\n' "$port_rc"
	printf -- '- retail: %s (offset +%sms)\n\n' \
		"$([ "$retail_ok" = 1 ] && echo captured || echo 'NOT captured')" "$RETAIL_OFFSET"

	printf '## Frames\n\n'
	printf '| ms | port | retail | delta%% |\n|---|---|---|---|\n'
	for ms in $(printf '%s' "$SHOTS" | tr ',' ' '); do
		p="$OUT/port-$ms.png"
		r="$OUT/retail-$ms.png"
		pd=$(dims "$p"); rd=$(dims "$r")
		delta='-'
		if [ "$pd" = "${W}x${H}" ] && [ "$rd" = "${W}x${H}" ]; then
			delta=$(python3 "$ROOT/analysis/tools/parity/png_delta.py" "$p" "$r" 2>/dev/null || echo 'refused')
		elif [ "$pd" != "${W}x${H}" ] && [ "$pd" != missing ]; then
			delta="port is $pd, not ${W}x${H} -- NOT COMPARED"
		elif [ "$rd" != "${W}x${H}" ] && [ "$rd" != missing ]; then
			delta="retail is $rd, not ${W}x${H} -- NOT COMPARED"
		fi
		printf '| %s | %s | %s | %s |\n' "$ms" \
			"$([ -f "$p" ] && echo "$p" || echo 'missing')" \
			"$([ -f "$r" ] && echo "$r" || echo 'missing')" "$delta"
	done

	printf '\n## Port errors and warnings\n\n'
	# Godot anchors its own diagnostics at the start of the line: "ERROR:",
	# "SCRIPT ERROR:", "WARNING:", and the USER_ variants from push_error /
	# push_warning. Anchoring is the whole point -- an unanchored match on
	# "refus"/"missing"/"Failed" pulled in `hud pieces=37 missing=[]` and
	# `dress ... worn_refused=2`, which are this engine REPORTING ITS STATE,
	# not failing. `refus` and `unbound` survive unanchored because the port
	# uses those words only where it declined to do something.
	if $GREP -nE '^(SCRIPT |USER )?(ERROR|WARNING):|refus|unbound' "$OUT/port.log" >/dev/null 2>&1; then
		printf '```\n'
		$GREP -nE '^(SCRIPT |USER )?(ERROR|WARNING):|refus|unbound' "$OUT/port.log" |
			head -80
		printf '```\n'
	else
		printf 'none\n'
	fi

	printf '\n## Port timeline\n\n```\n'
	$GREP -E '^(drive|shot)\b' "$OUT/port.log" 2>/dev/null | head -60
	printf '```\n'

	if [ -f "$OUT/retail.log" ]; then
		failed=$($GREP -c 'CalcResults () type=0 FAILED' "$OUT/retail.log" 2>/dev/null)
		[ -n "$failed" ] || failed=0
		printf '\n## Retail log\n\n- lines: %s\n- CalcResults FAILED: %s\n' \
			"$(awk 'END{print NR}' "$OUT/retail.log")" "$failed"
	fi
} >"$OUT/report.md"

cat "$OUT/report.md"
printf '\n-> %s/report.md\n' "$OUT"
