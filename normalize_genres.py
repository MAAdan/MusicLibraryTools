#!/usr/bin/env python3
"""Normalize multiple genre tags to comma-separated values, with confirmation.

Scans supported audio files recursively beneath PATH. Genre values containing
punctuation other than commas are shown alongside a proposed comma-separated
value. Press Enter or type ``y`` to save it; type ``n`` to enter a replacement
genre (or leave that prompt blank to skip the file).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.dont_write_bytecode = True

AUDIO_EXTENSIONS = {
    ".mp3", ".flac", ".m4a", ".mp4", ".ogg", ".opus", ".oga",
    ".aiff", ".aif", ".wav", ".wma", ".ape", ".wv",
}
# Common separators used between genres. Other punctuation is treated as a
# separator too, so tags such as "Rock & Pop" become "Rock, Pop".
SEPARATOR_RE = re.compile(r"[^\w\s,]+", flags=re.UNICODE)
WHITESPACE_RE = re.compile(r"\s*,\s*")


def normalize_genre(value: str) -> str:
    """Convert punctuation-separated genre names to a comma-separated string."""
    value = SEPARATOR_RE.sub(",", value)
    parts = [part.strip() for part in WHITESPACE_RE.split(value) if part.strip()]
    return ",".join(parts)


def has_special_characters(value: str) -> bool:
    """Return true when the value contains punctuation besides commas."""
    return bool(SEPARATOR_RE.search(value))


def update_file(path: Path) -> str:
    """Inspect and, if approved, update one file. Return updated/skipped/clean."""
    operation = "read metadata"
    try:
        probe = subprocess.run(
            ["ffprobe", "-v", "error", "-show_format", "-show_streams", "-of", "json", str(path)],
            check=True, capture_output=True, text=True,
        )
        metadata = json.loads(probe.stdout)
        tag_maps = [metadata.get("format", {}).get("tags", {})]
        tag_maps.extend(stream.get("tags", {}) for stream in metadata.get("streams", []))
        values = []
        for tags in tag_maps:
            for key, value in tags.items():
                if key.casefold() == "genre":
                    if isinstance(value, list):
                        values.extend(str(item).strip() for item in value if str(item).strip())
                    elif str(value).strip():
                        values.append(str(value).strip())
        current = ",".join(values)
        # Ampersand is part of the canonical genre name R&B, not a separator.
        if not current or current.strip().casefold() == "r&b" or not has_special_characters(current):
            return "clean"
        proposed = normalize_genre(current)
        if proposed == current:
            return "clean"

        print(f"\nFile: {path}\nCurrent genre: {current}\nNew genre:     {proposed}")
        try:
            answer = input("Replace genre? [Y/n] ").strip().casefold()
        except EOFError:
            answer = ""
        if answer not in {"", "y", "yes"}:
            try:
                replacement = input("Enter a new genre (leave blank to skip): ").strip()
            except EOFError:
                replacement = ""
            if not replacement:
                return "skipped"
            proposed = WHITESPACE_RE.sub(",", replacement)

        # Remux without re-encoding, preserving streams and other metadata.
        with tempfile.NamedTemporaryFile(
            prefix=f".{path.stem}.", suffix=path.suffix, dir=path.parent, delete=False
        ) as temp_file:
            temp_path = Path(temp_file.name)
        try:
            operation = "write metadata"
            subprocess.run(
                ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(path),
                 "-map", "0", "-c", "copy", "-map_metadata", "0", "-metadata", f"genre={proposed}",
                 str(temp_path)],
                check=True, capture_output=True, text=True,
            )
            os.replace(temp_path, path)
        finally:
            temp_path.unlink(missing_ok=True)
        return "updated"
    except Exception as exc:
        details = ""
        if isinstance(exc, subprocess.CalledProcessError):
            details = (exc.stderr or exc.stdout or "").strip()
        message = f"Could not {operation} for {path}: {exc}"
        if details:
            message += f"\n{details}"
        print(message, file=sys.stderr)
        return "failed"


def main() -> int:
    parser = argparse.ArgumentParser(description="Normalize audio genre metadata recursively.")
    parser.add_argument("path", type=Path, help="Folder to scan recursively.")
    args = parser.parse_args()
    root = args.path.expanduser().resolve()
    if not root.is_dir():
        print(f"Error: not a folder: {root}", file=sys.stderr)
        return 2
    if shutil.which("ffprobe") is None or shutil.which("ffmpeg") is None:
        print("Error: this script requires FFmpeg and FFprobe on PATH.", file=sys.stderr)
        return 2

    files = sorted(
        p for p in root.rglob("*")
        if p.is_file() and not p.is_symlink() and p.suffix.casefold() in AUDIO_EXTENSIONS
    )
    updated = skipped = clean = failed = 0
    for path in files:
        result = update_file(path)
        if result == "updated":
            updated += 1
        elif result == "skipped":
            skipped += 1
        elif result == "failed":
            failed += 1
        else:
            clean += 1
    print(f"Finished: {updated} updated, {skipped} skipped, {clean} already consistent, {failed} failed.")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
