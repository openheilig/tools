#!/bin/sh
# menu.sh -- emit the autopilot script that walks RETAIL's main menu into a world.
#
#   sh analysis/tools/drive/menu.sh <route>            # prints the script
#   sh analysis/tools/drive/menu.sh <route> --ready     # prints the ms the world is up
#
#   new    Ancaria Campaign -> Gladiator -> Start Game, then dismiss both tips
#          dialogs (the second one with "Stop Tutorial", which clears it for good).
#   load   Load Game -> first save-list slot -> Load -> OK.  Fastest route, and
#          it lands in whatever ./SAVE/GAME01.PAK holds (Valor's Fortress here).
#
# Retail has NO command line or Settings.cfg way into a savegame -- the argv
# parser at 0x809302A accepts exactly -h/-v/-w/-f/-s/-n/-d/-g and REFUSES to
# start on anything else, and no key in the Settings.cfg table names a save or
# a map.  Clicking the menu is the only route in; that is what this file is.
#
# Feeding it to the harnesses:
#
#   sh analysis/tools/drive/shot.sh w "$(sh .../menu.sh load)" 20000,60000 90
#
#   DRIVE_RETAIL_PRELUDE="$(sh .../menu.sh load)" \
#   DRIVE_RETAIL_OFFSET=$(sh .../menu.sh load --ready) \
#   sh analysis/tools/drive/session.sh w "<script>" 0,2000
#
# ⚠️ Every timestamp here is wall-clock from process start, and the engine's
# menu is only ready ~5 s in.  A click that fires early is simply lost -- it is
# not queued -- which is what made three earlier runs look like dead input.
#
# ⚠️ The confirmation dialog after Load is NOT optional.  Omit the OK and the
# run sits on the dialog forever at ~242 log lines, reading exactly like a load
# hang.  Two investigations were lost to that.
#
# ponytail: two routes, no Underworld, no character picker, no arguments beyond
# the route name.  Add a route when a measurement needs one.

set -u

ROUTE=${1:?usage: menu.sh new|load [--ready]}
WANT=${2:-}

# In-game clicks need the cursor pinned first: the in-game UI tracks its own
# cursor by accumulating motion deltas, so a bare absolute click lands at an
# unknown offset.  `move 0 0` drives it into the top-left clamp; the next
# absolute move then has a known origin.  Menu clicks need none of this --
# the menu reads SDL_GetMouseState directly.
CLK() { printf '%s move 0 0; %s move %s %s; %s click %s %s' \
	"$1" "$(($1 + 1200))" "$2" "$3" "$(($1 + 2400))" "$2" "$3"; }

case $ROUTE in
new)
	# 512,287 Ancaria Campaign | 228,400 Seraphim | 605,715 Start Game
	# The Seraphim is the winged figure second from the left; clicking her
	# fills the name field ("Seraphim_", armour "Bronze") -- measured, not
	# assumed, /tmp/shot-seraphim/sacred-14000.png.
	S="6000 click 512 287; 12000 click 228 400; 16000 click 605 715"
	# She wakes in Silver Creek's cathedral with ONE dialog, "The Dream...",
	# up by t=25 s.  The Gladiator's extra "Welcome to Ancaria!" box is his
	# arena tutorial and never appears here.  608,635 is "Skip Tutorial",
	# which clears the tutorial for good; OK (370,635) only advances it.
	S="$S; $(CLK 28000 608 635)"
	READY=34000
	;;
load)
	# 512,414 Load Game | 455,353 first slot | 866,300 Load | 422,440 OK
	S="6000 click 512 414; 10000 click 455 353; 14000 click 866 300; 18000 click 422 440"
	READY=60000
	;;
*)
	printf 'menu.sh: unknown route "%s" (new|load)\n' "$ROUTE" >&2
	exit 2
	;;
esac

case $WANT in
--ready) printf '%s\n' "$READY" ;;
'')      printf '%s\n' "$S" ;;
*)       printf 'menu.sh: unknown flag "%s"\n' "$WANT" >&2; exit 2 ;;
esac
