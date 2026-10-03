#!/usr/bin/env python3
"""
Create M3U playlists for folders containing MP3 or FLAC files.

The script walks recursively through the provided music collection path.
For each folder that contains MP3 or FLAC files, it creates an M3U file in
that same folder. The playlist file is named after the folder.

Use --dryrun to preview the actions without creating or updating files.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.dont_write_bytecode = True

MUSIC_EXTENSIONS = {".mp3", ".flac"}


def is_music_file(path: Path) -> bool:
    """Return whether a path is a regular MP3 or FLAC file."""
    return path.is_file() and not path.is_symlink() and path.suffix.lower() in MUSIC_EXTENSIONS


def playlist_path_for_folder(folder: Path) -> Path:
    """Return the playlist path for a folder."""
    return folder / f"{folder.name}.m3u"


def music_files_in_folder(folder: Path) -> list[Path]:
    """Return sorted music files stored directly in a folder."""
    return sorted(path for path in folder.iterdir() if is_music_file(path))


def write_playlist(playlist_path: Path, music_files: list[Path]) -> None:
    """Write an M3U playlist using paths relative to the playlist folder."""
    lines = [os.path.relpath(path, playlist_path.parent) for path in music_files]
    playlist_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def create_playlists(collection_path: Path, dryrun: bool, output_path: Path | None = None) -> None:
    if not collection_path.exists():
        raise FileNotFoundError(f"Path does not exist: {collection_path}")
    if not collection_path.is_dir():
        raise NotADirectoryError(f"Path is not a directory: {collection_path}")

    folders = [collection_path, *sorted(path for path in collection_path.rglob("*") if path.is_dir())]
    actions = 0

    for folder in folders:
        music_files = music_files_in_folder(folder)
        if not music_files:
            continue

        playlist_path = (
            output_path / f"{folder.name}.m3u"
            if output_path is not None
            else playlist_path_for_folder(folder)
        )
        action = "UPDATE" if playlist_path.exists() else "CREATE"
        actions += 1

        if dryrun:
            print(f"DRYRUN {action}: {playlist_path}")
            for music_file in music_files:
                print(f"  ADD: {music_file.name}")
        else:
            playlist_path.parent.mkdir(parents=True, exist_ok=True)
            write_playlist(playlist_path, music_files)
            print(f"{action}D: {playlist_path} ({len(music_files)} files)")

    if actions == 0:
        print(f"No folders with MP3 or FLAC files found in {collection_path}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create M3U playlists for folders containing MP3 or FLAC files."
    )
    parser.add_argument(
        "path",
        type=Path,
        help="Path containing folders with your music collection.",
    )
    parser.add_argument(
        "--output-path",
        type=Path,
        help="Optional directory where all playlists will be created.",
    )
    parser.add_argument(
        "--dryrun",
        action="store_true",
        help="Show the playlists that would be created or updated without writing files.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    output_path = args.output_path.expanduser().resolve() if args.output_path else None
    create_playlists(args.path.expanduser().resolve(), args.dryrun, output_path)


if __name__ == "__main__":
    main()
