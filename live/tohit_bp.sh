#!/bin/sh
# Breakpoint the retail to-hit candidates and report their arguments.
#
# Candidates found structurally in install/sacred:
#   0x81FA5AA  AT getter   (fld [creature+0xE6])
#   0x81FA622  PA getter   (fld [creature+0xEA])
#   0x815D44C  curve       f(a2,a3,a4,a5) = a2 * (1 - 1/((a2/a3 + 1)^k)),
#                          k = -ln(1-a5)/ln(a4+1)
#   0x83A37CA  hit% pair   calls both getters, then the curve, x100, clamp 100
#
# yama ptrace_scope=1 on this box, so gdb has to LAUNCH the game (see
# tools/live/gdb_run.sh); we replicate play.sh's environment the same way.
#
#   sh tmp/tohit_bp.sh <seconds-to-run>
set -u
ROOT=$(cd "$(dirname "$0")/../../.." && pwd)
INSTALL="$ROOT/install"
cd "$INSTALL"

AFTER=${1:-70}
ROUTE=${ROUTE:-new}
PRELUDE=$(sh "$ROOT/analysis/tools/drive/menu.sh" "$ROUTE")
# EXTRA is appended to the menu prelude; times are absolute ms and the world
# is ready at the offset menu.sh --ready reports (34000).
PRELUDE="$PRELUDE${EXTRA:+;$EXTRA}"

export LC_ALL=C
export GTK_RC_FILES="$PWD/conf/gtkrc"
export LD_LIBRARY_PATH="$PWD/shim"
export LD_PRELOAD="xshim.so:libGL.so.1:autopilot.so"
export SACRED_AUTO="$PRELUDE"
mkdir -p "$HOME/.lgp/sacred"
cp -f lgp-state/saveindex "$HOME/.lgp/sacred/.saveindex"
rm -f "$HOME/.lgp/sacred/debug.log"

cat >/tmp/tohit.gdb <<'EOF'
set pagination off
set confirm off
set height 0
handle SIGSEGV nostop noprint pass

# cdecl: [esp] = return address, [esp+4] = first argument
break *0x815D44C
commands
silent
printf "CURVE  caller=%#x  a2=%f a3=%f a4=%f a5=%f\n", *(unsigned int*)$esp, *(float*)($esp+8), *(float*)($esp+12), *(float*)($esp+16), *(float*)($esp+20)
continue
end

break *0x83A37CA
commands
silent
printf "HITPAIR caller=%#x a1=%#x a2=%#x\n", *(unsigned int*)$esp, *(unsigned int*)($esp+4), *(unsigned int*)($esp+8)
continue
end

break *0x81FA5AA
commands
silent
printf "AT_GET caller=%#x creature=%#x\n", *(unsigned int*)$esp, *(unsigned int*)($esp+4)
continue
end

break *0x81FA622
commands
silent
printf "PA_GET caller=%#x creature=%#x\n", *(unsigned int*)$esp, *(unsigned int*)($esp+4)
continue
end
EOF
# Synchronous run: the breakpoint `commands` blocks resume it themselves.
# `run &` plus `interrupt` is what tools/live/gdb_run.sh does and it no longer
# works on this gdb ("Selected thread is running"), so do not copy it.
# The caller's `timeout` ends the session.
printf 'run --withgl /usr/lib32 --nosound\nquit\n' >>/tmp/tohit.gdb

exec gdb -batch -x /tmp/tohit.gdb ./sacred 2>&1
