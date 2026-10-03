#!/usr/bin/env python3
"""Set the Genre metadata on MP3 files listed in a text file.

Requires FFmpeg and FFprobe on PATH; does not require Mutagen.
Each nonblank line in the input file is an MP3 path. Relative paths are
resolved relative to the input list file's folder. Lines beginning with '#'
are ignored.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.dont_write_bytecode = True


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Set the Genre tag on each MP3 path listed in a text file."
    )
    parser.add_argument("--input-file", required=True, type=Path,
                        help="Text file containing one MP3 path per line.")
    parser.add_argument("--genre", required=True,
                        help="Genre value to write to every listed MP3.")
    return parser.parse_args()


def listed_files(list_file: Path) -> list[Path]:
    paths: list[Path] = []
    for raw_line in list_file.read_text(encoding="utf-8-sig").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        path = Path(line).expanduser()
        if not path.is_absolute():
            path = list_file.parent / path
        paths.append(path.resolve())
    return paths


def set_genre(path: Path, genre: str) -> None:
    """Update genre by stream-copying the MP3 into a temporary file."""
    # Probe first to catch unreadable or non-MP3 input before replacing anything.
    subprocess.run(
        ["ffprobe", "-v", "error", "-show_format", "-of", "json", str(path)],
        check=True, capture_output=True, text=True,
    )
    with tempfile.NamedTemporaryFile(
        prefix=f".{path.stem}.", suffix=".mp3", dir=path.parent, delete=False
    ) as temp_file:
        temp_path = Path(temp_file.name)
    try:
        subprocess.run(
            ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(path),
             "-map", "0", "-c", "copy", "-map_metadata", "0", "-metadata", f"genre={genre}",
             "-id3v2_version", "3", "-write_id3v1", "1", str(temp_path)],
            check=True, capture_output=True, text=True,
        )
        os.replace(temp_path, path)
    finally:
        temp_path.unlink(missing_ok=True)


def main() -> int:
    args = parse_args()
    list_file = args.input_file.expanduser().resolve()
    if not list_file.is_file():
        print(f"Error: input file not found: {list_file}", file=sys.stderr)
        return 2
    if not args.genre.strip():
        print("Error: genre must not be empty.", file=sys.stderr)
        return 2
    if shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None:
        print("Error: this script requires FFmpeg and FFprobe on PATH.", file=sys.stderr)
        return 2

    try:
        files = listed_files(list_file)
    except OSError as exc:
        print(f"Could not read input file {list_file}: {exc}", file=sys.stderr)
        return 2

    updated = failed = 0
    for path in files:
        if path.suffix.casefold() != ".mp3":
            print(f"SKIP (not an MP3): {path}")
            continue
        if not path.is_file():
            print(f"SKIP (file not found): {path}")
            continue
        try:
            set_genre(path, args.genre.strip())
            print(f"UPDATED: {path}")
            updated += 1
        except subprocess.CalledProcessError as exc:
            details = (exc.stderr or exc.stdout or "").strip()
            print(f"FAILED: {path}" + (f"\n{details}" if details else ""), file=sys.stderr)
            failed += 1
        except OSError as exc:
            print(f"FAILED: {path}: {exc}", file=sys.stderr)
            failed += 1

    print(f"Finished: {updated} updated, {failed} failed.")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
