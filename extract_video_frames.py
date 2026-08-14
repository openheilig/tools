#!/usr/bin/env python3
from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def duration(path: Path) -> float:
    result = subprocess.run(
        ["/usr/bin/ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
        check=True, capture_output=True, text=True,
    )
    return float(result.stdout.strip())


def main() -> int:
    if len(sys.argv) != 3:
        print(f"usage: {sys.argv[0]} VIDEO OUTPUT_DIR", file=sys.stderr)
        return 2
    video = Path(sys.argv[1]).resolve()
    output = Path(sys.argv[2]).resolve()
    output.mkdir(parents=True, exist_ok=True)
    stem = video.stem.replace(" ", "_")
    total = duration(video)
    step = 1.0
    times = [i * step for i in range(int(total // step) + 1)]
    manifest = output / f"{stem}.tsv"
    with manifest.open("w", encoding="utf-8") as handle:
        handle.write("index\ttime\tpath\n")
        for index, timestamp in enumerate(times):
            frame = output / f"{stem}-{index:04d}.png"
            subprocess.run([
                "/usr/bin/ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                "-ss", f"{timestamp:.3f}", "-i", str(video), "-frames:v", "1",
                "-vf", "scale=1020:767", str(frame),
            ], check=True)
            handle.write(f"{index}\t{timestamp:.3f}\t{frame}\n")
    print(f"video={video}")
    print(f"duration={total:.3f}")
    print(f"frames={len(times)}")
    print(f"manifest={manifest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
