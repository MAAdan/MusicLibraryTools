#!/usr/bin/env python3
"""
List the songs that appear more than once in the music library.

Two files are the same song when they have the same artist(s) and title,
after ignoring differences that don't change the recording you hear:

    Bryan Adams - Summer of 69.mp3
    Bryan Adams - 07 Summer Of '69 (2008 Remaster).mp3
    001. Bryan Adams - Summer of 69.flac

Artist and title come from the file name ('Artist - Title' or
'Artist - NN Title'); files whose name doesn't follow that pattern fall back
to their Artist/Title tags. Featured artists count as artists, so
'A - Song (feat. B)' and 'A & B - Song' match. Live, remix, acoustic, demo and
instrumental versions are kept apart unless --ignore-versions is used; tracks
in a live album folder ('MTV Unplugged', 'Live On Ten Legs') count as live even
when their file names don't say so. When two files in the same folder get the
same name, their tags decide whether they are really the same song.

The report goes to stdout so it can be saved with '>':

    python3 find_duplicate_songs.py > duplicates.log

Progress and warnings go to stderr, so they stay out of the saved report.
Nothing in the library is changed.
"""

from __future__ import annotations

import argparse
import hashlib
import re
import sys
import unicodedata
from collections import defaultdict
from datetime import datetime
from pathlib import Path

sys.dont_write_bytecode = True

SCRIPT_DIR = Path(__file__).resolve().parent
# The script lives in "<library>/scripts"; the library itself is one level up.
DEFAULT_LIBRARY = SCRIPT_DIR.parent if SCRIPT_DIR.name.casefold() == "scripts" else SCRIPT_DIR
DEFAULT_EXCLUDES = ["Playlists", "scripts", "tmp"]

AUDIO_EXTENSIONS = {
    ".mp3", ".flac", ".m4a", ".mp4", ".ogg", ".opus", ".oga",
    ".aiff", ".aif", ".wav", ".wma", ".ape", ".wv",
}

LEADING_TRACK_NUMBER = re.compile(r"^\s*\d{1,3}(?:\s*[.)_-]\s*|\s+)(?=\S)")
SPLIT_ARTIST_TITLE = re.compile(r"\s[-–—]\s")
# '(feat. X)', '[ft X]', '(with X)' and a trailing 'feat. X' with no brackets.
FEATURING_BRACKET = re.compile(r"\s*[(\[]\s*(?:feat\.?|ft\.?|featuring|with)\s+([^)\]]+)[)\]]", re.I)
FEATURING_TRAILING = re.compile(r"\s+(?:feat\.?|ft\.?|featuring)\s+(.+)$", re.I)
ARTIST_SEPARATORS = re.compile(
    r"\s*(?:&|,|\+|/|\band\b|\bvs\.?|\bx\b|\bwith\b|\bfeat\.?|\bft\.?|\bfeaturing\b)\s*", re.I
)
LEADING_ARTICLE = re.compile(r"^\s*(?:the|los|las|el|la|les)\s+(?=\S)", re.I)

# Release notes that don't change the song: remasters, edits, explicit/clean...
NOISE_WORDS = (
    r"remaster(?:ed)?|\d{4}\s+(?:remaster(?:ed)?|version|mix)|radio\s+edit|single\s+edit|edit"
    r"|single\s+version|album\s+version|original\s+version|lp\s+version|explicit|clean"
    r"|mono|stereo|bonus\s+track|hq|hd|official\s+(?:audio|video)"
)
# Notes that make it a different recording; ignored only with --ignore-versions.
VERSION_WORDS = (
    r"live|remix|mix|acoustic|unplugged|demo|instrumental|karaoke|extended|reprise"
    r"|orchestral|piano\s+version|session|cover|rework|re-?recorded|taylor'?s\s+version"
)


NOISE_RE = re.compile(rf"\b(?:{NOISE_WORDS})\b", re.I)
VERSION_RE = re.compile(rf"\b(?:{VERSION_WORDS})\b", re.I)
# '(... note ...)', '[... note ...]' anywhere, or ' - 2011 Remaster' at the end.
TITLE_NOTE = re.compile(r"\s*[(\[][^)\]]*[)\]]|\s+[-–—]\s+[^-–—]+$")
# Folders such as 'Live On Ten Legs (2011)' or 'MTV Unplugged (2019)' hold live
# recordings even when the file names don't say so.
# Mixed collections such as '001 VA - Pop Songs' are not albums.
VARIOUS_ARTISTS_FOLDER = re.compile(r"\b(?:VA|various artists)\b", re.I)
DISC_FOLDER = re.compile(r"\b(?:cd|disc|disk)\s*0*\d+\b", re.I)
LIVE_FOLDER = re.compile(r"\b(?:live|unplugged|in\s+concert)\b", re.I)


def clean_title(title: str, ignore_versions: bool) -> str:
    """Drop release notes that don't change the recording ('2011 Remaster', 'Radio Edit').
    Notes naming a different version ('Live', 'Remix', 'Remix Radio Edit') are kept,
    unless ignore_versions is set."""

    def replace(match: re.Match[str]) -> str:
        note = match.group(0)
        if VERSION_RE.search(note):
            return "" if ignore_versions else note
        return "" if NOISE_RE.search(note) else note

    previous = None
    while previous != title:  # notes can be stacked: 'Song (Live) [2011 Remaster]'
        previous = title
        title = TITLE_NOTE.sub(replace, title).strip() or previous
    return title


def album_folder(path: Path) -> Path | None:
    """The album a file belongs to: its folder, or the folder above 'CD 1' / 'Disc 2'.
    None for various-artists collections ('001 VA - Pop Songs')."""
    folder = path.parent
    if DISC_FOLDER.search(folder.name):
        folder = folder.parent
    return None if VARIOUS_ARTISTS_FOLDER.search(folder.name) else folder


def live_album(path: Path, library: Path) -> str | None:
    """Name of the live album folder the file is in, if any (artist prefix removed,
    so the band 'Live' or 'Live - Throwing Copper' doesn't count)."""
    for folder in path.parent.relative_to(library).parts:
        album = SPLIT_ARTIST_TITLE.split(folder)[-1]
        if LIVE_FOLDER.search(album):
            return plain_text(album)
    return None


def plain_text(value: str) -> str:
    """Lowercase letters and digits only, without accents ('Rosé' -> 'rose')."""
    value = unicodedata.normalize("NFKD", value)
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    value = value.replace("&", " and ")
    return re.sub(r"[^a-z0-9]+", "", value.casefold())


def artist_title_from_name(path: Path) -> tuple[str, str] | None:
    """Parse 'Artist - Title', '001. Artist - Title' or '01 - Artist - Title'."""
    stem = path.stem
    for candidate in (LEADING_TRACK_NUMBER.sub("", stem), stem):
        parts = SPLIT_ARTIST_TITLE.split(candidate, maxsplit=1)
        if len(parts) == 2 and parts[0].strip() and parts[1].strip():
            artist = parts[0].strip()
            # 'Artist - 01 - Title' -> keep only the title
            title = re.sub(r"^\s*\d{1,3}\s*[-–—]\s*", "", parts[1]).strip()
            return artist, title
    return None


def artist_title_from_tags(path: Path) -> tuple[str, str] | None:
    """Artist/Title tags (MP3 and FLAC via rename_mp3_by_metadata.py, others via Mutagen if installed)."""
    tags: dict[str, str] = {}
    try:
        sys.path.insert(0, str(SCRIPT_DIR))
        from rename_mp3_by_metadata import audio_metadata

        tags = audio_metadata(path)
    except Exception:
        tags = {}
    if not (tags.get("artist") and tags.get("title")):
        try:
            from mutagen import File as MutagenFile

            audio = MutagenFile(path, easy=True)
            if audio and audio.tags:
                for field in ("artist", "title"):
                    values = audio.tags.get(field)
                    if values and not tags.get(field):
                        tags[field] = str(values[0])
        except Exception:
            pass
    artist = (tags.get("artist") or "").strip()
    title = (tags.get("title") or "").strip()
    return (artist, title) if artist and title else None


def song_key(artist: str, title: str, ignore_versions: bool) -> tuple[str, str] | None:
    """Matching key: (sorted artist names incl. featured artists, cleaned title)."""
    featured: list[str] = []

    def take_featured(match: re.Match[str]) -> str:
        featured.append(match.group(1))
        return ""

    title = LEADING_TRACK_NUMBER.sub("", title)
    title = FEATURING_BRACKET.sub(take_featured, title)
    title = FEATURING_TRAILING.sub(take_featured, title)
    artist = FEATURING_BRACKET.sub(take_featured, artist)
    artist = FEATURING_TRAILING.sub(take_featured, artist)

    title = clean_title(title, ignore_versions)

    names = set()
    for chunk in [artist, *featured]:
        for name in ARTIST_SEPARATORS.split(chunk):
            key = plain_text(LEADING_ARTICLE.sub("", name)) or plain_text(name)
            if key:
                names.add(key)
    title_key = plain_text(title)
    if not names or not title_key:
        return None
    return "+".join(sorted(names)), title_key


def library_audio_files(library: Path, excludes: set[str]) -> list[Path]:
    """All audio files under the library, skipping hidden and excluded top-level folders."""
    files = []
    for path in library.rglob("*"):
        relative = path.relative_to(library)
        if any(part.startswith(".") for part in relative.parts):
            continue
        if relative.parts and relative.parts[0].casefold() in excludes:
            continue
        if path.suffix.casefold() in AUDIO_EXTENSIONS and path.is_file() and not path.is_symlink():
            files.append(path)
    return sorted(files)


def file_digest(path: Path) -> str | None:
    digest = hashlib.md5()
    try:
        with path.open("rb") as handle:
            for block in iter(lambda: handle.read(1 << 20), b""):
                digest.update(block)
    except OSError:
        return None
    return digest.hexdigest()


def identical_copies(paths: list[Path]) -> dict[Path, int]:
    """Map each byte-identical file to the 1-based position of its first identical copy."""
    sizes: dict[int, list[Path]] = defaultdict(list)
    for path in paths:
        sizes[path.stat().st_size].append(path)
    first_seen: dict[str, Path] = {}
    result: dict[Path, int] = {}
    for path in paths:
        if len(sizes[path.stat().st_size]) < 2:
            continue
        digest = file_digest(path)
        if digest is None:
            continue
        if digest in first_seen:
            result[path] = paths.index(first_seen[digest]) + 1
        else:
            first_seen[digest] = path
    return result


def human_size(size: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} GB"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="List duplicated songs in the music library (report on stdout).",
        epilog="Example: python3 find_duplicate_songs.py > duplicates.log",
    )
    parser.add_argument(
        "library", nargs="?", type=Path, default=DEFAULT_LIBRARY,
        help=f"Library folder to scan (default: {DEFAULT_LIBRARY}).",
    )
    parser.add_argument(
        "--exclude", action="append", default=None, metavar="FOLDER",
        help="Top-level folder to skip; repeat for several "
             f"(default: {', '.join(DEFAULT_EXCLUDES)}).",
    )
    parser.add_argument(
        "--ignore-versions", action="store_true",
        help="Treat live, remix, acoustic, demo... versions as the same song.",
    )
    parser.add_argument(
        "--no-hash", action="store_true",
        help="Don't check whether copies are byte-identical (faster).",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    library = args.library.expanduser().resolve()
    if not library.is_dir():
        print(f"Error: library folder not found: {library}", file=sys.stderr)
        return 1
    excludes = {name.casefold() for name in (args.exclude or DEFAULT_EXCLUDES)}

    print(f"Scanning {library} ...", file=sys.stderr)
    files = library_audio_files(library, excludes)

    groups: dict[tuple[str, ...], list[Path]] = defaultdict(list)
    display: dict[tuple[str, ...], str] = {}
    unidentified: list[Path] = []

    def add(path: Path, parsed: tuple[str, str]) -> bool:
        key = song_key(*parsed, args.ignore_versions)
        if key is None:
            return False
        album = None if args.ignore_versions else live_album(path, library)
        if album:
            key = (*key, f"live:{album}")
        groups[key].append(path)
        if key not in display:
            title = clean_title(LEADING_TRACK_NUMBER.sub("", parsed[1]), False)
            display[key] = f"{parsed[0]} - {title}" + (" (live)" if album else "")
        return True

    for path in files:
        parsed = artist_title_from_name(path) or artist_title_from_tags(path)
        if not (parsed and add(path, parsed)):
            unidentified.append(path)

    # Two files of one album with the same name are usually different tracks with
    # truncated names ('Another Brick in the Wall Part' 1, 2 and 3): let the tags decide.
    for key in list(groups):
        paths = groups[key]
        folders = [path.parent for path in paths]
        clashing = [path for path in paths if folders.count(path.parent) > 1]
        retagged = [(path, artist_title_from_tags(path)) for path in clashing]
        retagged = [(path, tags) for path, tags in retagged if tags]
        if len({song_key(*tags, args.ignore_versions) for _, tags in retagged}) < 2:
            continue
        for path, tags in retagged:
            paths.remove(path)
        if not paths:
            del groups[key]
            del display[key]
        for path, tags in retagged:
            add(path, tags)

    # Every copy in one album: almost always different tracks whose names
    # (and tags) lost a part number or a '?', so report them separately.
    same_album = []
    for key in list(groups):
        paths = groups[key]
        albums = {album_folder(path) for path in paths}
        if len(paths) > 1 and len(albums) == 1 and None not in albums:
            same_album.append((key, groups.pop(key)))
    same_album.sort(key=lambda item: (*item[0], str(item[1][0])))

    duplicates = [(key, paths) for key, paths in groups.items() if len(paths) > 1]
    duplicates.sort(key=lambda item: (*item[0], str(item[1][0])))

    extra_copies = sum(len(paths) - 1 for _, paths in duplicates)
    reclaimable = sum(sum(p.stat().st_size for p in paths[1:]) for _, paths in duplicates)

    out = sys.stdout
    print("DUPLICATE SONGS REPORT", file=out)
    print(f"Library:   {library}", file=out)
    print(f"Generated: {datetime.now():%Y-%m-%d %H:%M}", file=out)
    print(f"Matching:  artist + title"
          f"{', live/remix/acoustic versions merged' if args.ignore_versions else ', live/remix/acoustic versions kept apart'}",
          file=out)
    print(f"Skipped:   {', '.join(sorted(excludes))}", file=out)
    print(file=out)
    print(f"Audio files scanned:      {len(files)}", file=out)
    print(f"Songs with duplicates:    {len(duplicates)}", file=out)
    print(f"Same name in one album:   {len(same_album)}  (listed at the end)", file=out)
    print(f"Extra copies:             {extra_copies}", file=out)
    print(f"Space used by extra copies: {human_size(reclaimable)}", file=out)
    print("=" * 78, file=out)

    for number, (key, paths) in enumerate(duplicates, 1):
        if not args.no_hash and sys.stderr.isatty():
            print(f"Checking copies {number}/{len(duplicates)}", end="\r", file=sys.stderr)
        same = {} if args.no_hash else identical_copies(paths)
        print(file=out)
        print(f"[{number}] {display[key]}  ({len(paths)} copies)", file=out)
        for position, path in enumerate(paths, 1):
            note = f"  [identical to {same[path]}]" if path in same else ""
            size = human_size(path.stat().st_size)
            print(f"    {position}. {path.relative_to(library)}  ({size}){note}", file=out)

    if same_album:
        print(file=out)
        print("=" * 78, file=out)
        print(f"Same name twice in one album ({len(same_album)}) - probably different tracks", file=out)
        print("with incomplete names or tags (e.g. a missing 'Part 2'); worth checking:", file=out)
        for key, paths in same_album:
            print(file=out)
            print(f"    {display[key]}", file=out)
            for path in paths:
                print(f"        {path.relative_to(library)}", file=out)

    if unidentified:
        print(file=out)
        print("=" * 78, file=out)
        print(f"Files not checked: no 'Artist - Title' in the name or tags ({len(unidentified)})", file=out)
        for path in unidentified:
            print(f"    {path.relative_to(library)}", file=out)

    if sys.stderr.isatty():
        print(" " * 40, end="\r", file=sys.stderr)
    print(f"Done: {len(duplicates)} duplicated songs found in {len(files)} files.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
