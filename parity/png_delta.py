#!/usr/bin/env python3
"""png_delta.py -- percentage of pixels that differ between two PNGs.

Usage: png_delta.py A.png B.png [--crop=x,y,w,h] [--mae]

A pixel differs if any channel differs. The percentage is taken over the
crop rectangle if given (x,y top-left, w,h size, pixels), else over the
whole frame. Prints exactly one line: the percentage with two decimals
(e.g. "0.00", "18.24").

`--mae` appends a second field, the MEAN ABSOLUTE ERROR over the same
rectangle -- the average per-pixel max-channel difference, 0..255, counting
the pixels that match as the zeroes they are. The two answer different
questions and the pair is what makes either readable: 11% differing at MAE
2.3 is a near-miss everywhere, 11% at MAE 40 is a real content gap. The
percentage alone cannot tell them apart, and it stays the gate's verdict
because this project reproduces retail exactly rather than acceptably.

The default output is UNCHANGED and remains a single field -- `drive/session.sh`
parses it.

Refuses loudly (message on stderr, exit 1, no percentage) on a missing
file, an unreadable/non-image input, a size mismatch, or a malformed /
out-of-bounds crop -- never prints a percentage computed from nothing.

ponytail: no alignment/translation search -- the caller owns framing
(camera motion is the standing hazard, see plan 06-02's threat register).
PIL is the project's measurement stack; if PIL is importable this runs.
"""

import sys

from PIL import Image, ImageChops


def die(msg: str) -> None:
    print(f"png_delta: {msg}", file=sys.stderr)
    sys.exit(1)


def load(path: str) -> Image.Image:
    try:
        im = Image.open(path)
        im.load()
    except FileNotFoundError:
        die(f"missing file: {path}")
    except Exception as e:
        die(f"not a readable image: {path} ({e})")
    return im.convert("RGB")


def parse_crop(arg: str, size: tuple[int, int]) -> tuple[int, int, int, int]:
    try:
        parts = [int(p) for p in arg.split(",")]
    except ValueError:
        die(f"malformed --crop (want x,y,w,h integers): {arg}")
    if len(parts) != 4:
        die(f"malformed --crop (want x,y,w,h): {arg}")
    x, y, w, h = parts
    if w <= 0 or h <= 0:
        die(f"--crop has non-positive size: {arg}")
    if x < 0 or y < 0 or x + w > size[0] or y + h > size[1]:
        die(f"--crop {arg} out of bounds for image size {size[0]}x{size[1]}")
    return x, y, w, h


def main(argv: list[str]) -> None:
    args = [a for a in argv[1:] if not a.startswith("--")]
    crop_arg = None
    want_mae = False
    for a in argv[1:]:
        if a.startswith("--crop="):
            crop_arg = a[len("--crop="):]
        elif a == "--mae":
            want_mae = True
        elif a.startswith("--"):
            die(f"unknown flag: {a}")
    if len(args) != 2:
        die("usage: png_delta.py A.png B.png [--crop=x,y,w,h] [--mae]")

    a = load(args[0])
    b = load(args[1])
    if a.size != b.size:
        die(f"size mismatch: {args[0]} is {a.size[0]}x{a.size[1]}, "
            f"{args[1]} is {b.size[0]}x{b.size[1]}")

    if crop_arg is not None:
        x, y, w, h = parse_crop(crop_arg, a.size)
        box = (x, y, x + w, y + h)
        a = a.crop(box)
        b = b.crop(box)

    # ponytail: NO getbbox() early-return here. On RGBA images Pillow's
    # getbbox(alpha_only=True) reads ONLY the alpha channel; two opaque
    # images have zero alpha difference, so it returns None even when every
    # RGB pixel differs -- this made the tool print 0.00 for visibly
    # different frames (measured 2026-08-11, plan 06-02). Count differing
    # pixels by histogramming the per-pixel max-channel difference -- one
    # pass, no per-pixel Python loop.
    diff = ImageChops.difference(a, b)
    r, g, bch = diff.split()
    band = ImageChops.lighter(ImageChops.lighter(r, g), bch)
    hist = band.histogram()
    total = band.size[0] * band.size[1]
    changed = total - hist[0]
    out = f"{100.0 * changed / total:.2f}"
    if want_mae:
        # histogram index IS the max-channel difference, so the mean is a
        # weighted sum over 256 buckets -- still one pass, no pixel loop.
        out += f" {sum(i * n for i, n in enumerate(hist)) / total:.2f}"
    print(out)


if __name__ == "__main__":
    main(sys.argv)
