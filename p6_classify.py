#!/usr/bin/env python3
"""p6_classify.py -- TRANSLATION vs CONTENT verdict for a pair of frames.

Usage: p6_classify.py A.png B.png

Prints one line: `TRANSLATION <raw%> <collapsed%> <dx,dy>` or
`CONTENT <raw%> <best-residual%> <dx,dy>`.

The swap-hunt hazard: on this scene a camera hop changes 90-98% of pixels,
but the change COLLAPSES to <5% when one frame is shifted by the camera
motion; the roof swap is a content change that no shift can explain away.
Search window +/-60 px, border crop 64 px on the shifted comparison so the
compared region is the true intersection of the two frames (narrow borders
gave false CONTENT from newly-exposed edge strips -- measured 2026-08-11).

Verdict: TRANSLATION if the best shifted residual < 5.0%, else CONTENT.
Long-gap pairs accumulate ambient animation (grass/tree sway) -- only
consecutive ~250ms pairs are clean; the caller owns cadence.

ponytail: brute-force 121x121 shift search over a cropped pair is ~1 MP x
14k shifts in numpy -- vectorized per-shift, a few seconds per pair.
"""

import sys

import numpy as np
from PIL import Image

SEARCH = 60
BORDER = 64
COLLAPSE_THRESHOLD = 5.0


def arr(path):
    return np.asarray(Image.open(path).convert("L"), dtype=np.int16)


def shifted_residual(a, b, dx, dy):
    """Percent of pixels differing after shifting b by (dx,dy), compared on
    the intersection minus BORDER."""
    h, w = a.shape
    x0 = BORDER + max(0, -dx)
    x1 = w - BORDER - max(0, dx)
    y0 = BORDER + max(0, -dy)
    y1 = h - BORDER - max(0, dy)
    if x1 <= x0 or y1 <= y0:
        return 100.0
    ca = a[y0:y1, x0:x1]
    cb = b[y0 + dy:y1 + dy, x0 + dx:x1 + dx]
    return float((ca != cb).sum()) * 100.0 / ca.size


def main():
    a, b = arr(sys.argv[1]), arr(sys.argv[2])
    if a.shape != b.shape:
        print("p6_classify: size mismatch", file=sys.stderr)
        sys.exit(1)
    raw = float((a != b).sum()) * 100.0 / a.size
    best = (100.0, 0, 0)
    for dy in range(-SEARCH, SEARCH + 1, 2):
        for dx in range(-SEARCH, SEARCH + 1, 2):
            r = shifted_residual(a, b, dx, dy)
            if r < best[0]:
                best = (r, dx, dy)
    # refine around the coarse best
    r0, bx, by = best
    for dy in range(by - 2, by + 3):
        for dx in range(bx - 2, bx + 3):
            r = shifted_residual(a, b, dx, dy)
            if r < r0:
                r0, bx, by = r, dx, dy
    verdict = "TRANSLATION" if r0 < COLLAPSE_THRESHOLD else "CONTENT"
    print(f"{verdict} raw={raw:.2f} residual={r0:.2f} shift={bx},{by}")


if __name__ == "__main__":
    main()
