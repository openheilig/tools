#!/bin/sh
# Run the game under gdb and sample its stacks.
#
# Needed because yama ptrace_scope=1 on this box: only an ancestor may ptrace,
# so `gdb -p <pid>` on a running game is refused.  gdb has to launch it.
# Replicates play.sh's environment (it `exec`s, so we can't just wrap it).
#
#   sh analysis/tools/gdb_run.sh "<SACRED_AUTO>" <sample-after-sec> [nsamples]
#
# ponytail: no symbols in the binary -- the useful output is the raw
# `0x08xxxxxx in ?? ()` addresses, which objdump then resolves.

set -u
ROOT=$(cd "$(dirname "$0")/../.." && pwd)
cd "$ROOT/install"

SCRIPT=${1:-}
AFTER=${2:-50}
N=${3:-4}

export LC_ALL=C
export GTK_RC_FILES="$PWD/conf/gtkrc"
export LD_LIBRARY_PATH="$PWD/shim"
export LD_PRELOAD="xshim.so:libGL.so.1:autopilot.so"
export SACRED_AUTO="$SCRIPT"
mkdir -p "$HOME/.lgp/sacred"
cp -f lgp-state/saveindex "$HOME/.lgp/sacred/.saveindex"
rm -f "$HOME/.lgp/sacred/debug.log"

cat >/tmp/gdbcmds <<EOF
set pagination off
set confirm off
handle SIGSEGV nostop noprint pass
run --withgl /usr/lib32 --nosound &
shell sleep $AFTER
EOF
i=0
while [ "$i" -lt "$N" ]; do
    printf 'interrupt\nshell sleep 1\necho \\n===== SAMPLE %s =====\\n\nthread apply all bt 15\ncontinue &\nshell sleep 6\n' "$i" >>/tmp/gdbcmds
    i=$((i + 1))
done
echo 'kill' >>/tmp/gdbcmds
echo 'quit' >>/tmp/gdbcmds

gdb -batch -x /tmp/gdbcmds ./sacred 2>&1
