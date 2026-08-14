#!/bin/sh
# Report every short read out of the engine's save/world stream.
#
#   sh analysis/tools/live/shortread_watch.sh [play.sh flags...]
#   SW_SECS=180 sh analysis/tools/live/shortread_watch.sh --nosound
#
# ---------------------------------------------------------------------------
# Why a breakpoint here and not a log grep.
#
# `cFile_ram::read(this, dst, len)` at 0x83c5aee (see AGENTS.md "ROOT CAUSE")
# clamps a read to whatever is left in the RAM buffer and returns the short
# count -- and every caller in the deserializer throws that return value away.
# Once the position runs past the end, every further read is a no-op that
# leaves the destination untouched, which is how a creature reaches
# CalcResults with its type still at the allocator's zero.
#
# The clamp is one instruction:
#
#     83c5b0a  cmp eax,ebx        ; eax = avail = size - pos, ebx = requested
#     83c5b0c  jae 83c5b10        ; enough left -> skip
#     83c5b0e  mov ebx,eax        ; *** SHORT READ ***
#
# So a breakpoint at 0x83c5b0e fires ONLY on the anomaly.  A healthy load
# never touches it and pays nothing; there is no need to filter thousands of
# normal reads.  That also makes this a *positive* signal: silence means the
# stream never ran dry, which no downstream log line can tell you (the
# sentinels only notice one object too late, and `CalcResults FAILED` needs
# the bad creature to actually reach combat maths).
#
# sacred is non-PIE (ET_EXEC, base 0x8048000) so the address is fixed.  If you
# rebuild or repatch the binary, re-derive it -- and do NOT read it out of a
# whole-binary objdump, which desyncs (AGENTS.md "Three traps that cost
# hours").  Disassemble from 0x83c5aee, which is a vtable entry and therefore
# a guaranteed instruction boundary.
# ---------------------------------------------------------------------------

set -u
ROOT=$(cd "$(dirname "$0")/../../.." && pwd)
LOG="$HOME/.lgp/sacred/debug.log"
OUT=${SW_OUT:-/tmp/shortread.txt}
SECS=${SW_SECS:-150}

CLK() { echo "$1 move 0 0; $(($1 + 1200)) move $2 $3; $(($1 + 2400)) click $2 $3"; }
# Same schedule as race_sweep.sh -- menu clicks at 20/26/30s (they fire on
# wall-clock from process start and the menu is not up before ~15s), then
# in-game clicks pinned with `move 0 0` because the in-game UI accumulates
# SDL_MOUSEMOTION deltas rather than reading absolute position.
SCRIPT=${SW_SCRIPT:-"20000 click 512 287; 26000 click 110 420; 30000 click 605 715\
; $(CLK 64000 348 499)\
; $(CLK 70000 608 623)\
; $(CLK 86000 700 300)\
; $(CLK 96000 300 550)"}

cat > /tmp/shortread.gdb <<'EOF'
set pagination off
set confirm off
set height 0
handle SIGPIPE nostop noprint pass
break *0x83c5b0e
commands
silent
printf "SHORTREAD want=%d avail=%d pos=%d size=%d base=%#x from=%#x\n", $ebx, $eax, *(int*)($esi+0xc), *(int*)($esi+4), *(int*)($esi+0x10), *(int*)($esp+4)
continue
end

# The clamp above is NOT reachable when the buffer is NULL -- cFile_ram::read
# takes its `cmp [esi+0x10],0 / je` early exit first.  That is exactly the
# state cFile_ram::open leaves behind on a truncated fread (REPORT.md 2.12):
# it deletes the buffer, zeroes +0x10, leaves +0x4 at 0, and still returns 1.
# 0x83c59d8 is the `got != size` branch, so it fires only on that failure.
break *0x83c59d8
commands
silent
printf "TRUNCATED got=%d want=%d\n", $eax, $edi
continue
end
run
EOF

pkill -9 -x sacred 2>/dev/null
rm -f "$LOG" "$OUT"

# gdb inherits play.sh's LD_PRELOAD/LD_LIBRARY_PATH, which is what we want --
# the shim must be loaded or the run behaves differently from a normal one.
SACRED_PRELOAD=autopilot.so SACRED_AUTO="$SCRIPT" \
SACRED_RUNNER="gdb --batch -x /tmp/shortread.gdb --args" \
    "$ROOT/install/play.sh" "$@" > "$OUT" 2>&1 &
pid=$!

waited=0
while [ "$waited" -lt "$SECS" ]; do
    kill -0 "$pid" 2>/dev/null || break
    waited=$((waited + 1)); sleep 1
done
kill "$pid" 2>/dev/null; sleep 2; kill -9 "$pid" 2>/dev/null
wait "$pid" 2>/dev/null
pkill -9 -x sacred 2>/dev/null

n=$(/usr/bin/grep -ca '^SHORTREAD' "$OUT" 2>/dev/null); [ -n "$n" ] || n=0
lines=$(awk 'END{print NR}' "$LOG" 2>/dev/null); [ -n "$lines" ] || lines=0
f=$(/usr/bin/grep -ca 'CalcResults () type=0 FAILED' "$LOG" 2>/dev/null); [ -n "$f" ] || f=0

echo "---"
echo "log lines=$lines  CalcResults FAILED=$f  SHORTREAD=$n   (full output: $OUT)"
[ "$n" -gt 0 ] && /usr/bin/grep -a '^SHORTREAD' "$OUT" | head -20
exit 0
