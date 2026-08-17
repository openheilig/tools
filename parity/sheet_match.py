#!/usr/bin/env python3
"""sheet_match.py -- find which UI sheet rect a piece of a retail frame came from.

    python3 sheet_match.py <frame.png> <x> <y> <w> <h> <sheet.png> [sheet.png ...]

Takes a rectangle of a RETAIL capture and searches every sheet for the source
rect that reproduces it, ranked by mean per-channel error over the sheet's
opaque pixels.

WHY THIS EXISTS. The taskbar's gfx table gives ids and rects for the elements
it names, but not every element on screen is reachable that way -- the
portrait window is not in it, and the potion belt's table entry turns out to
describe the slot rather than its contents. Reading more disassembly to find
them is slow; asking "which 95x107 block of which sheet IS this" is one pass
over six 256x256 images.

READ THE ERROR, NOT THE RANK. This always returns a best match, and a best
match means nothing on its own. Measured on this project's own frames:

    under ~1.0   this IS the art. All five potion-belt slots scored 0.77-1.00
                 and are exact to the pixel.
    over ~35     the art is NOT in these sheets, or -- just as often -- the
                 region is not a flat blit at all. The two FILLED art slots
                 bottom out at 56 across all six sheets, which is how we know
                 they live somewhere else.

There is no useful middle. A score of 20 is not "close" -- it is a different
picture.

A HIGH SCORE DOES NOT ACQUIT THE SHEETS, and this one is worth knowing before
you trust a negative. The method only works on a FLAT OPAQUE BLIT. It fails,
loudly and with a confident wrong answer, on:

  - a region with live content in it. The portrait ring surrounds a render of
    the hero's bust, so the whole 95x107 block scores 64 and reports "not in
    these sheets" -- while the frame it is asking about IS GUI_MAIN_02's
    (0,0,95,107), exact to the pixel. The interior outvoted the frame.
  - anything semi-transparent. Retail's console shows the wall through it, and
    a soft-edged ring's own border pixels are blends. The 0.85-opaque filter
    then rejects the very rect you want and answers with a different one.

Trying to score a narrow band of the portrait ring that misses the bust does
NOT rescue it -- measured, it still returns 62 and the wrong rect, because a
curved frame's bounding band is mostly transparent.

So the workflow that actually found both pieces is: DUMP THE SHEETS AND LOOK
AT THEM FIRST (six 256x256 PNGs; the portrait frame is plainly the top-left
corner of GUI_MAIN_02), then use this to confirm identity on a rect that is
pure art, and the render to pin position. This tool settles "is this the
art"; it does not replace opening the sheet.

ALIGNMENT IS SEPARATE FROM IDENTITY, and conflating them cost an hour. The
search reports where the art is IN THE SHEET, not where it goes on screen; a
region whose interior differs (a frame around a live render, say) biases the
on-screen position badly. Place the piece, render, then measure the offset
between the port's and retail's own bounding boxes for some distinctive
colour, and correct by that. The portrait frame landed 4px left and 2px down
from the search's suggestion and only the render said so.

Sheets are decoded out of texture.pak by the engine; see the dump loop in
`checks/` or run a small SceneTree script over `Sacred.decode_texture`.

ponytail: brute force, no pyramid, no early exit. Six 256x256 sheets against
one rect is a couple of seconds, and every clever version of this would need
its own correctness argument.
"""
import sys

import numpy as np
from PIL import Image


def main(argv: list[str]) -> int:
    if len(argv) < 7:
        print(__doc__.strip().splitlines()[2], file=sys.stderr)
        return 2
    frame, x, y, w, h = argv[1], *map(int, argv[2:6])
    scr = np.asarray(Image.open(frame).convert("RGB")).astype(float)
    if x < 0 or y < 0 or x >= scr.shape[1] or y >= scr.shape[0]:
        print(f"sheet_match: {x},{y} is outside {frame}", file=sys.stderr)
        return 1
    # CLIP RATHER THAN REFUSE. Retail clips its own elements at the screen
    # edge -- the portrait frame is 95 wide at x 932 on a 1024 canvas, so
    # three columns of it are simply not drawn. Refusing that rect means
    # refusing to identify a piece precisely because retail did the normal
    # thing with it. Match the visible part against the same top-left corner
    # of each candidate.
    vw, vh = min(w, scr.shape[1] - x), min(h, scr.shape[0] - y)
    if (vw, vh) != (w, h):
        print(f"sheet_match: rect clipped by the frame edge to {vw}x{vh}", file=sys.stderr)
    w, h = vw, vh
    target = scr[y:y + h, x:x + w]

    out = []
    for path in argv[6:]:
        sheet = np.asarray(Image.open(path).convert("RGBA")).astype(float)
        sh, sw = sheet.shape[:2]
        for sy in range(0, sh - h + 1):
            for sx in range(0, sw - w + 1):
                tile = sheet[sy:sy + h, sx:sx + w]
                opaque = tile[:, :, 3] > 128
                # A mostly-transparent block can score well on its few opaque
                # pixels and mean nothing; require the rect to be real art.
                if opaque.mean() < 0.85:
                    continue
                err = (np.abs(tile[:, :, :3] - target).mean(axis=2) * opaque).sum()
                out.append((err / opaque.sum(), path, sx, sy))
    if not out:
        print("sheet_match: no sufficiently opaque rect of that size in any sheet")
        return 1
    out.sort()
    for err, path, sx, sy in out[:5]:
        verdict = "IS the art" if err < 1.0 else ("not in these sheets" if err > 35 else "inconclusive")
        print(f"{err:7.2f}  {path}  rect({sx},{sy},{w},{h})   {verdict}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
