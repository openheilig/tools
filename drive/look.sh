#!/bin/sh
# look.sh -- see what either engine is drawing, without stealing your display.
#
#   sh analysis/tools/drive/look.sh port   [openheilig args...]
#   sh analysis/tools/drive/look.sh retail [label] [SACRED_AUTO] [shot-ms] [seconds]
#   sh analysis/tools/drive/look.sh both   [openheilig args...]
#
# Both subcommands end by printing the PNG paths, one per line, so an agent can
# read the last lines of output and open them directly.
#
# Why this exists: an agent has no screen. Every visual claim in this project
# has to come from a file it can open, and the two engines are captured in
# completely different ways -- Godot renders offscreen under Xvfb, while the
# retail binary can only be seen through autopilot.so's glReadPixels hook
# (no XTEST, GNOME denies screenshots, SDL_VIDEODRIVER=x11 stalls the engine).
#
# ⚠️ port mode never passes --rendering-driver. The project ships Forward+ /
# Vulkan, the two backends disagree about whether ALBEDO is linear, and a whole
# session of "verified" screenshots was taken on the wrong one before that
# surfaced. Vulkan works fine under Xvfb; there is no reason to force GL.

set -u
ROOT=$(cd "$(dirname "$0")/../../.." && pwd)
# A bare checkout resolves ROOT to the wrong place -- these scripts expect to
# sit at <workspace>/analysis/tools/<group>/. SACRED_INSTALL and SACRED_PORT
# are the way out when they do not.
INSTALL="${SACRED_INSTALL:-$ROOT/install}"
PORT="${SACRED_PORT:-$ROOT/godot-port}"
OUT=/tmp/look
SCREEN=${LOOK_SCREEN:-1600x1000x24}
MODE=${1:-port}
[ $# -gt 0 ] && shift

mkdir -p "$OUT"

die() { printf '%s\n' "$*" >&2; exit 1; }

have() { command -v "$1" >/dev/null 2>&1; }

shot_port() {
    have godot || die "look.sh: godot not on PATH"
    have xvfb-run || die "look.sh: xvfb-run not installed (package xorg-server-xvfb)"
    png=$OUT/port-$(date +%H%M%S).png
    # --shot renders one *settled* frame (main.gd waits for the streamer to
    # finish) and exits, so this is a picture of a finished view, not of
    # whatever one frame of loading happened to produce.
    xvfb-run -a -s "-screen 0 $SCREEN" \
        godot --path "$PORT" -- --shot="$png" "$@" 2>&1 |
        /usr/bin/grep -vE '^$|^Godot Engine|WARNING|^ +at: '
    [ -f "$png" ] || die "look.sh: no PNG written -- see the output above"
    printf '%s\n' "$png"
}

shot_retail() {
    label=${1:-look}
    auto=${2:-}
    shots=${3:-8000,20000}
    dur=${4:-30}
    have magick || die "look.sh: ImageMagick 'magick' missing; shot.sh needs it for PPM->PNG"
    [ -x "$INSTALL/play.sh" ] || die "look.sh: $INSTALL/play.sh not found"
    # shot.sh owns the retail capture: it preloads autopilot.so, drives the game
    # from SACRED_AUTO, grabs the back buffer at each SACRED_SHOT timestamp, and
    # converts the PPMs. One run per invocation -- the game grabs the display.
    #
    # Run it inside Xvfb. The 2005 binary starts, reaches the main menu and
    # renders correctly on a virtual display (verified 2026-08-07), so an agent
    # can use the retail game as an oracle without taking over a real desktop
    # for 30 seconds. LOOK_DISPLAY=real opts out, for when a human wants to
    # watch it live.
    if [ "${LOOK_DISPLAY:-xvfb}" = real ]; then
        sh "$ROOT/analysis/tools/drive/shot.sh" "$label" "$auto" "$shots" "$dur"
    else
        have xvfb-run || die "look.sh: xvfb-run not installed"
        xvfb-run -a -s "-screen 0 ${LOOK_RETAIL_SCREEN:-1024x768x24}" \
            sh "$ROOT/analysis/tools/drive/shot.sh" "$label" "$auto" "$shots" "$dur"
    fi
}

case "$MODE" in
    port)   shot_port "$@" ;;
    retail) shot_retail "$@" ;;
    both)
        shot_port "$@"
        shot_retail look "" "8000,20000" 30
        ;;
    *) die "usage: look.sh port|retail|both [args...]" ;;
esac
