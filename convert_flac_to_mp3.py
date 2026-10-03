#!/usr/bin/env python3
"""Convert FLAC files to MP3 with FFmpeg while retaining embedded metadata.

FFmpeg must be installed and available on your PATH.  By default the script
searches the supplied folder recursively and writes each MP3 beside its FLAC
source. Existing MP3 files are never replaced unless --overwrite is supplied.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

sys.dont_write_bytecode = True


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Convert FLAC files to MP3 and copy their tags and cover art."
    )
    parser.add_argument("path", type=Path, help="Folder containing FLAC files.")
    quality = parser.add_mutually_exclusive_group()
    quality.add_argument(
        "--bitrate",
        default="320k",
        help="Constant MP3 bitrate passed to FFmpeg (default: 320k).",
    )
    quality.add_argument(
        "--quality",
        type=int,
        choices=range(0, 10),
        metavar="0-9",
        help="Use LAME variable bitrate quality, from 0 (best) to 9 (smallest).",
    )
    parser.add_argument(
        "--sample-rate", type=int, metavar="HZ", help="Output sample rate, for example 44100."
    )
    parser.add_argument(
        "--channels", type=int, choices=range(1, 9), help="Output channel count."
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        help="Write to this folder, preserving the source folder structure.",
    )
    parser.add_argument("--no-recursive", action="store_true", help="Only convert FLACs in PATH.")
    parser.add_argument("--overwrite", action="store_true", help="Replace existing MP3 files.")
    parser.add_argument("--dry-run", action="store_true", help="Show conversions without writing files.")
    return parser.parse_args()


def flac_files(folder: Path, recursive: bool) -> list[Path]:
    candidates = folder.rglob("*") if recursive else folder.iterdir()
    return sorted(
        path for path in candidates if path.is_file() and not path.is_symlink() and path.suffix.lower() == ".flac"
    )


def output_path(source: Path, source_root: Path, output_root: Path | None) -> Path:
    if output_root is None:
        return source.with_suffix(".mp3")
    return output_root / source.relative_to(source_root).with_suffix(".mp3")


def ffmpeg_command(source: Path, destination: Path, args: argparse.Namespace) -> list[str]:
    command = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-y" if args.overwrite else "-n",
        "-i",
        str(source),
        # Map the audio, optional embedded cover art, all tags, and chapters.
        "-map",
        "0:a:0",
        "-map",
        "0:v?",
        "-map_metadata",
        "0",
        "-map_chapters",
        "0",
        "-c:a",
        "libmp3lame",
    ]
    if args.quality is None:
        command.extend(["-b:a", args.bitrate])
    else:
        command.extend(["-q:a", str(args.quality)])
    if args.sample_rate is not None:
        command.extend(["-ar", str(args.sample_rate)])
    if args.channels is not None:
        command.extend(["-ac", str(args.channels)])
    command.extend(
        [
            "-c:v",
            "copy",
            "-disposition:v",
            "attached_pic",
            "-id3v2_version",
            "3",
            "-write_id3v1",
            "1",
            str(destination),
        ]
    )
    return command


def convert(args: argparse.Namespace) -> int:
    source_root = args.path.expanduser().resolve()
    if not source_root.is_dir():
        print(f"Error: not a folder: {source_root}", file=sys.stderr)
        return 2
    if shutil.which("ffmpeg") is None:
        print("Error: FFmpeg is required but was not found on PATH.", file=sys.stderr)
        return 2

    destination_root = args.output_dir.expanduser().resolve() if args.output_dir else None
    sources = flac_files(source_root, recursive=not args.no_recursive)
    if not sources:
        print(f"No FLAC files found in {source_root}")
        return 0

    converted = skipped = failed = 0
    for source in sources:
        destination = output_path(source, source_root, destination_root)
        if destination.exists() and not args.overwrite:
            print(f"SKIP (already exists): {destination}")
            skipped += 1
            continue
        print(f"{'DRY RUN: ' if args.dry_run else ''}CONVERT: {source} -> {destination}")
        if args.dry_run:
            continue
        destination.parent.mkdir(parents=True, exist_ok=True)
        result = subprocess.run(ffmpeg_command(source, destination, args), check=False)
        if result.returncode:
            print(f"FAILED: {source}", file=sys.stderr)
            failed += 1
        else:
            converted += 1

    print(f"Finished: {converted} converted, {skipped} skipped, {failed} failed.")
    return 1 if failed else 0


def main() -> None:
    args = parse_args()
    raise SystemExit(convert(args))


if __name__ == "__main__":
    main()
