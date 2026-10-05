#!/usr/bin/env python3
"""Create a fresh playlist from all audio files in a library folder.

Run from anywhere with: python3 make_playlist.py [--input-path FOLDER]
Without --input-path, the script uses the full library containing this script.

Modes:
  (default)            random tracks from one genre family
  --lastfm             Last.fm global chart tracks found in the library
  --smart-list SONG    tracks similar to SONG (Last.fm track/artist similarity)
"""

from __future__ import annotations

import random
import re
import argparse
import json
import os
import difflib
import urllib.error
import urllib.parse
import urllib.request
import unicodedata
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
# The script lives in "<library>/scripts"; the library itself is one level up.
ROOT = SCRIPT_DIR.parent if SCRIPT_DIR.name.casefold() == "scripts" else SCRIPT_DIR
OUTPUT_DIR = ROOT / "Playlists"
UNREADABLE_TAG_LOG = ROOT / "no_readable_tag_error.log"
NOT_FOUND_LOG = ROOT / "lastfm_not_found.log"  # --lastfm chart mode
# --smart-list writes one report per seed song: "lastfm_not_found - Artist - Title.log"
NOT_FOUND_SHOWN = 20  # songs listed on screen; the log file has all of them
MIN_TRACKS = 18
MAX_TRACKS = 25
LASTFM_API_URL = "https://ws.audioscrobbler.com/2.0/"
SMART_MAX_PER_ARTIST = 3  # cap per artist when filling from similar artists

SUPPORTED_AUDIO = {".mp3", ".m4a", ".flac", ".ogg", ".wav", ".aiff"}

TITLE_STARTS = [
    "Afterglow",
    "Electric Sundown",
    "Midnight Radio",
    "Neon Daydream",
    "Golden Hour",
    "The Long Way Home",
    "Velvet Thunder",
    "Starlight Drive",
    "Weekend Fever",
    "The Memory Lane Mixtape",
    "Skyline Signals",
    "Wildheart FM",
]
TITLE_ENDS = [
    "— Songs for the Open Road",
    "— Big Hooks, No Skips",
    "— A Mixtape for Right Now",
    "— Anthems After Dark",
    "— The Feel-Good Frequency",
    "— Familiar, Never Boring",
    "— Turn It Up and Stay Awhile",
    "— Deep Cuts & Bright Lights",
    "— Hits with a Little History",
    "— Your New Favorite Detour",
]

# Common ID3 numeric genre identifiers, used when an MP3 stores a TCON value
# such as "(13)" instead of the genre name.
ID3_GENRES = {
    0: "Blues", 1: "Classic Rock", 2: "Country", 3: "Dance", 4: "Disco",
    5: "Funk", 6: "Grunge", 7: "Hip-Hop", 8: "Jazz", 9: "Metal",
    10: "New Age", 11: "Oldies", 12: "Other", 13: "Pop", 14: "R&B",
    15: "Rap", 16: "Reggae", 17: "Rock", 18: "Techno", 19: "Industrial",
    20: "Alternative", 21: "Ska", 22: "Death Metal", 23: "Pranks",
    24: "Soundtrack", 25: "Euro-Techno", 26: "Ambient", 27: "Trip-Hop",
    28: "Vocal", 29: "Jazz+Funk", 30: "Fusion", 31: "Trance",
    32: "Classical", 33: "Instrumental", 34: "Acid", 35: "House",
    36: "Game", 37: "Sound Clip", 38: "Gospel", 39: "Noise",
    40: "AlternRock", 41: "Bass", 42: "Soul", 43: "Punk", 44: "Space",
    45: "Meditative", 46: "Instrumental Pop", 47: "Instrumental Rock",
    48: "Ethnic", 49: "Gothic", 50: "Darkwave", 51: "Techno-Industrial",
    52: "Electronic", 53: "Pop-Folk", 54: "Eurodance", 55: "Dream",
    56: "Southern Rock", 57: "Comedy", 58: "Cult", 59: "Gangsta",
    60: "Top 40", 61: "Christian Rap", 62: "Pop/Funk", 63: "Jungle",
    64: "Native American", 65: "Cabaret", 66: "New Wave", 67: "Psychedelic",
    68: "Rave", 69: "Showtunes", 70: "Trailer", 71: "Lo-Fi", 72: "Tribal",
    73: "Acid Punk", 74: "Acid Jazz", 75: "Polka", 76: "Retro",
    77: "Musical", 78: "Rock & Roll", 79: "Hard Rock", 80: "Folk",
    81: "Folk-Rock", 82: "National Folk", 83: "Swing", 84: "Fast Fusion",
    85: "Bebob", 86: "Latin", 87: "Revival", 88: "Celtic", 89: "Bluegrass",
    90: "Avantgarde", 91: "Gothic Rock", 92: "Progressive Rock",
    93: "Psychedelic Rock", 94: "Symphonic Rock", 95: "Slow Rock",
    96: "Big Band", 97: "Chorus", 98: "Easy Listening", 99: "Freestyle",
    100: "Acoustic", 101: "Humour", 102: "Speech", 103: "Chanson",
    104: "Opera", 105: "Chamber Music", 106: "Sonata", 107: "Symphony",
    108: "Booty Bass", 109: "Primus", 110: "Porn Groove", 111: "Satire",
    112: "Slow Jam", 113: "Club", 114: "Tango", 115: "Samba",
    116: "Folklore", 117: "Ballad", 118: "Power Ballad", 119: "Rhythmic Soul",
    120: "Freestyle", 121: "Duet", 122: "Punk Rock", 123: "Drum Solo",
    124: "A Cappella", 125: "Euro-House", 126: "Dance Hall", 127: "Goa",
    128: "Drum & Bass", 129: "Club-House", 130: "Hardcore", 131: "Terror",
    132: "Indie", 133: "BritPop", 134: "Negerpunk", 135: "Polsk Punk",
    136: "Beat", 137: "Christian Gangsta Rap", 138: "Heavy Metal",
    139: "Black Metal", 140: "Crossover", 141: "Contemporary Christian",
    142: "Christian Rock", 143: "Merengue", 144: "Salsa", 145: "Thrash Metal",
    146: "Anime", 147: "JPop", 148: "Synthpop",
}


def normalized_track_key(track: Path) -> str:
    """Normalize a filename so duplicate copies across compilations are caught."""
    name = unicodedata.normalize("NFKD", track.stem)
    name = "".join(ch for ch in name if not unicodedata.combining(ch))
    name = re.sub(r"^\s*\d+[.\s_-]+", "", name)
    name = name.casefold()
    return re.sub(r"[^a-z0-9]+", "", name)


def playlist_tracks(playlist: Path) -> list[Path]:
    tracks: list[Path] = []
    try:
        lines = playlist.read_text(encoding="utf-8-sig", errors="replace").splitlines()
    except OSError:
        return tracks
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        candidate = Path(line)
        if not candidate.is_absolute():
            candidate = playlist.parent / candidate
        candidate = candidate.resolve()
        if candidate.is_file() and candidate.suffix.casefold() in {".mp3", ".m4a", ".flac", ".ogg", ".wav", ".aiff"}:
            tracks.append(candidate)
    return tracks


def library_tracks(folder: Path) -> list[Path]:
    """Return unique audio files beneath folder, including nested folders."""
    unique: dict[str, Path] = {}
    for track in folder.rglob("*"):
        if track.is_file() and track.suffix.casefold() in SUPPORTED_AUDIO:
            unique.setdefault(normalized_track_key(track), track.resolve())
    return list(unique.values())


def id3_text(payload: bytes) -> str:
    if not payload:
        return ""
    encoding = payload[0]
    body = payload[1:]
    try:
        if encoding == 0:
            return body.decode("latin-1", errors="replace").strip("\x00 ")
        if encoding == 1:
            return body.decode("utf-16", errors="replace").strip("\x00 ")
        if encoding == 2:
            return body.decode("utf-16-be", errors="replace").strip("\x00 ")
        return body.decode("utf-8", errors="replace").strip("\x00 ")
    except (LookupError, UnicodeError):
        return ""


def mp3_genre(track: Path) -> str | None:
    """Read TCON from ID3v2 or the genre byte from an ID3v1 footer."""
    try:
        with track.open("rb") as audio:
            header = audio.read(10)
            if len(header) == 10 and header[:3] == b"ID3":
                major = header[3]
                tag_size = ((header[6] & 0x7F) << 21) | ((header[7] & 0x7F) << 14) | ((header[8] & 0x7F) << 7) | (header[9] & 0x7F)
                tag = audio.read(tag_size)
                offset = 0
                frame_header_size = 6 if major == 2 else 10
                wanted_frame = b"TCO" if major == 2 else b"TCON"
                while offset + frame_header_size <= len(tag):
                    if major == 2:
                        frame_id = tag[offset:offset + 3]
                        frame_size = int.from_bytes(tag[offset + 3:offset + 6], "big")
                    else:
                        frame_id = tag[offset:offset + 4]
                        raw_size = tag[offset + 4:offset + 8]
                        if major >= 4:
                            frame_size = ((raw_size[0] & 0x7F) << 21) | ((raw_size[1] & 0x7F) << 14) | ((raw_size[2] & 0x7F) << 7) | (raw_size[3] & 0x7F)
                        else:
                            frame_size = int.from_bytes(raw_size, "big")
                    if not frame_id.strip(b"\x00"):
                        break
                    start = offset + frame_header_size
                    end = start + frame_size
                    if frame_id == wanted_frame and end <= len(tag):
                        genre = id3_text(tag[start:end])
                        if genre:
                            match = re.match(r"^\((\d+)\)\s*(.*)$", genre)
                            if match:
                                name = ID3_GENRES.get(int(match.group(1)))
                                if name:
                                    return name
                                genre = match.group(2)
                            return genre
                    if frame_size <= 0:
                        break
                    offset = end

            audio.seek(-128, os.SEEK_END)
            footer = audio.read(128)
            if len(footer) == 128 and footer[:3] == b"TAG":
                genre_number = footer[127]
                return ID3_GENRES.get(genre_number)
    except (OSError, ValueError):
        return None
    return None


def genre_name(value: str) -> str:
    """Convert numeric ID3 genre values to names where possible."""
    value = value.strip()
    match = re.match(r"^\(?([0-9]{1,3})\)?\s*(.*)$", value)
    if match:
        name = ID3_GENRES.get(int(match.group(1)))
        if name:
            return name
        return match.group(2).strip()
    return value


def embedded_genre(track: Path) -> str | None:
    """Read genre metadata, using Mutagen when available and an MP3 fallback."""
    try:
        from mutagen import File as MutagenFile

        audio = MutagenFile(track, easy=True)
        if audio and audio.tags:
            values = audio.tags.get("genre")
            if values:
                if isinstance(values, str):
                    values = [values]
                return ",".join(genre_name(str(value)) for value in values)
    except ImportError:
        pass
    except Exception:
        pass
    if track.suffix.casefold() == ".mp3":
        return mp3_genre(track)
    return None


def genre_family(genre: str) -> str:
    """Map detailed metadata genres to broad, playlist-compatible families."""
    value = unicodedata.normalize("NFKD", genre).encode("ascii", "ignore").decode().casefold()
    value = re.sub(r"[^a-z0-9]+", " ", value).strip()
    words = set(value.split())
    if words & {"metal", "metalcore", "deathcore", "djent"}:
        return "Heavy Metal"
    if words & {"rock", "punk", "grunge", "emo", "indie"} or "alternative" in value:
        return "Rock"
    if words & {"pop", "synthpop", "electropop"}:
        return "Pop"
    if words & {"hiphop", "rap", "hip"}:
        return "Hip-Hop & Rap"
    if words & {"rnb", "soul", "funk"} or "r b" in value or "rhythm and blues" in value:
        return "R&B, Soul & Funk"
    if words & {"electronic", "techno", "house", "trance", "ambient", "dubstep", "edm", "disco", "dance"}:
        return "Electronic & Dance"
    if words & {"country", "bluegrass"}:
        return "Country"
    if words & {"jazz", "bebop", "swing"}:
        return "Jazz"
    if words & {"classical", "opera", "symphony"}:
        return "Classical"
    if words & {"reggae", "ska", "dancehall"}:
        return "Reggae & Ska"
    if words & {"folk", "acoustic", "bluegrass"}:
        return "Folk & Acoustic"
    if words & {"latin", "salsa", "samba", "merengue"}:
        return "Latin"
    return genre.strip().title()


def genre_groups(tracks: list[Path]) -> tuple[dict[str, list[Path]], int]:
    groups: dict[str, list[Path]] = {}
    missing = 0
    unreadable: list[Path] = []
    for track in tracks:
        genre = embedded_genre(track)
        if not genre:
            missing += 1
            unreadable.append(track)
            continue
        # Genre tags may contain several comma-separated candidates. Add the
        # track to every matching family, but only once per family.
        families = {
            genre_family(genre_name(candidate.strip()))
            for candidate in genre.split(",")
            if candidate.strip()
        }
        if not families:
            missing += 1
            unreadable.append(track)
            continue
        for family in families:
            groups.setdefault(family, []).append(track)
    if unreadable:
        UNREADABLE_TAG_LOG.write_text(
            "\n".join(str(track) for track in unreadable) + "\n",
            encoding="utf-8",
        )
        print(f"Files with no readable genre tag logged to: {UNREADABLE_TAG_LOG}")
    else:
        UNREADABLE_TAG_LOG.unlink(missing_ok=True)
    return groups, missing


def create_genre_playlist(candidates: list[Path], output_dir: Path) -> None:
    groups, missing = genre_groups(candidates)
    groups = {family: tracks for family, tracks in groups.items() if len(tracks) >= 2}
    if not groups:
        raise SystemExit(
            "No genre family with at least two tagged tracks was found. Add genre tags to your audio files; "
            "MP3 ID3 genre tags are read without extra packages, and Mutagen enables other formats."
        )
    large_groups = {family: tracks for family, tracks in groups.items() if len(tracks) >= MIN_TRACKS}
    if large_groups:
        groups = large_groups
    else:
        family, tracks = max(groups.items(), key=lambda item: len(item[1]))
        groups = {family: tracks}
    family = random.choice(list(groups))
    tracks = groups[family]
    count = min(random.randint(MIN_TRACKS, MAX_TRACKS), len(tracks))
    chosen = random.sample(tracks, count)
    title = f"{family} — {random.choice(TITLE_STARTS)} {random.choice(TITLE_ENDS)}"
    output = write_playlist(title, chosen, output_dir)
    print(f"Created: {output}")
    print(f"Genre family: {family}; tracks: {len(chosen)}")
    if missing:
        print(f"Skipped {missing} files with no readable genre tag.")


def next_playlist_number(output_dir: Path) -> int:
    numbers = []
    for path in output_dir.glob("*.m3u8"):
        match = re.match(r"(\d+)", path.name)
        if match:
            numbers.append(int(match.group(1)))
    return max(numbers, default=0) + 1


def clean_match_text(value: str) -> str:
    """Normalize artist/title text and discard common release-version notes."""
    value = unicodedata.normalize("NFKD", value)
    value = "".join(char for char in value if not unicodedata.combining(char))
    value = re.sub(r"\s*\((?:[^)]*(?:remaster|remastered|radio edit|single version|album version|live|explicit|clean)[^)]*)\)\s*$", "", value, flags=re.I)
    value = re.sub(r"\s*\[(?:[^]]*(?:remaster|remastered|radio edit|single version|album version|live|explicit|clean)[^]]*)\]\s*$", "", value, flags=re.I)
    return re.sub(r"[^a-z0-9]+", "", value.casefold())


def split_local_artist_title(track: Path) -> tuple[str, str] | None:
    """Read the common 'Artist - Title' naming pattern from a local filename."""
    stem = re.sub(r"^\s*\d+[.\s_-]+", "", track.stem)
    parts = re.split(r"\s[-–—]\s", stem, maxsplit=1)
    if len(parts) != 2:
        return None
    artist, title = (clean_match_text(part) for part in parts)
    return (artist, title) if artist and title else None


def match_chart_track(artist: str, title: str, candidates: list[Path]) -> Path | None:
    """Match a chart entry by artist and title; keep fuzzy matches conservative."""
    wanted_artist = clean_match_text(artist)
    wanted_title = clean_match_text(title)
    if not wanted_artist or not wanted_title:
        return None

    best_track: Path | None = None
    best_score = 0.0
    for track in candidates:
        local = split_local_artist_title(track)
        if not local:
            continue
        local_artist, local_title = local
        title_score = difflib.SequenceMatcher(None, wanted_title, local_title).ratio()
        artist_score = difflib.SequenceMatcher(None, wanted_artist, local_artist).ratio()
        # Exact/near-exact titles are required to avoid matching unrelated songs.
        if title_score < 0.88 or artist_score < 0.70:
            continue
        score = 0.68 * title_score + 0.32 * artist_score
        if score > best_score:
            best_track, best_score = track, score
    return best_track


def lastfm_global_tracks(api_key: str, desired_matches: int) -> list[dict[str, str]]:
    """Fetch global top tracks in chart order, paging until enough results arrive."""
    tracks: list[dict[str, str]] = []
    page = 1
    while len(tracks) < desired_matches * 4 and page <= 10:
        query = urllib.parse.urlencode({
            "method": "chart.getTopTracks",
            "api_key": api_key,
            "format": "json",
            "limit": 200,
            "page": page,
        })
        request = urllib.request.Request(
            f"{LASTFM_API_URL}?{query}",
            headers={"User-Agent": "MusicLibraryPlaylistMaker/1.0"},
        )
        try:
            with urllib.request.urlopen(request, timeout=25) as response:
                payload = json.load(response)
        except Exception as error:
            raise SystemExit(f"Could not retrieve Last.fm charts: {error}") from error

        page_tracks = payload.get("tracks", {}).get("track", [])
        if isinstance(page_tracks, dict):
            page_tracks = [page_tracks]
        if not page_tracks:
            break
        for entry in page_tracks:
            artist = entry.get("artist", {})
            if isinstance(artist, dict):
                artist = artist.get("name", "")
            if entry.get("name") and artist:
                tracks.append({"artist": str(artist), "title": str(entry["name"])})
        page += 1
    return tracks


def write_playlist(title: str, tracks: list[Path], output_dir: Path) -> Path:
    """Write an M3U8 playlist that points to the selected local files."""
    number = next_playlist_number(output_dir)
    output = output_dir / f"{number:02d} {title}.m3u8"
    lines = ["#EXTM3U", f"#PLAYLIST:{title}"]
    for track in tracks:
        relative_path = Path(os.path.relpath(track, output_dir))
        lines.extend([f"#EXTINF:-1,{track.stem}", relative_path.as_posix()])
    output.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return output


def report_not_found(
    source: str, checked: int, missing: list[tuple[int, str, str]], log_path: Path = NOT_FOUND_LOG
) -> None:
    """Summarise Last.fm songs that are not in the library.

    missing holds (Last.fm rank, artist, title). The top songs are printed and
    the complete list is written to log_path (replaced on every run).
    """
    found = checked - len(missing)
    print(f"\nLast.fm {source}: {checked} songs checked, {found} in your library, {len(missing)} not found.")
    if not missing:
        log_path.unlink(missing_ok=True)
        return
    width = len(str(missing[-1][0]))
    lines = [f"{rank:>{width}}. {artist} - {title}" for rank, artist, title in missing]
    print(f"Songs not in your library (Last.fm rank):")
    for line in lines[:NOT_FOUND_SHOWN]:
        print(f"  {line}")
    if len(lines) > NOT_FOUND_SHOWN:
        print(f"  ... and {len(lines) - NOT_FOUND_SHOWN} more.")
    log_path.write_text(
        f"Last.fm {source}: songs not found in the library ({len(missing)} of {checked} checked)\n"
        "Rank is the song's position in the Last.fm results.\n\n" + "\n".join(lines) + "\n",
        encoding="utf-8",
    )
    print(f"Full list saved to: {log_path}")


def create_lastfm_playlist(candidates: list[Path], count: int, output_dir: Path) -> None:
    api_key = os.environ.get("LASTFM_API_KEY")
    if not api_key:
        raise SystemExit(
            "Set the LASTFM_API_KEY environment variable first. Get a key at https://www.last.fm/api/account/create"
        )

    chart = lastfm_global_tracks(api_key, count)
    matched: list[Path] = []
    missing: list[tuple[int, str, str]] = []
    checked = 0
    for rank, entry in enumerate(chart, start=1):
        checked = rank
        local = match_chart_track(entry["artist"], entry["title"], candidates)
        if local is None:
            missing.append((rank, entry["artist"], entry["title"]))
        elif local not in matched:
            matched.append(local)
        if len(matched) >= count:
            break

    # Only chart positions up to the last song needed are checked.
    report_not_found("global chart", checked, missing)
    print()
    if not matched:
        raise SystemExit(
            "No Last.fm global chart tracks matched local filenames. The matcher expects names like 'Artist - Title.mp3'."
        )

    title = f"Global Pulse — Last.fm Top {len(matched)}"
    output = write_playlist(title, matched, output_dir)
    print(f"Created: {output}")
    print(f"Matched {len(matched)} of the requested {count} tracks from Last.fm's global chart.")
    if len(matched) < count:
        print("Some chart songs were not found in the selected library folder.")


# ---------------------------------------------------------------------------
# Smart list: playlist of songs similar to a seed song
# ---------------------------------------------------------------------------

class LastfmError(Exception):
    pass


def lastfm_call(api_key: str, method: str, **params: object) -> dict:
    """Call a Last.fm API method and return the decoded JSON payload."""
    query = urllib.parse.urlencode({
        "method": method,
        "api_key": api_key,
        "format": "json",
        **params,
    })
    request = urllib.request.Request(
        f"{LASTFM_API_URL}?{query}",
        headers={"User-Agent": "MusicLibraryPlaylistMaker/1.0"},
    )
    try:
        with urllib.request.urlopen(request, timeout=25) as response:
            payload = json.load(response)
    except urllib.error.HTTPError as error:
        # Last.fm returns JSON error bodies with non-200 codes (e.g. bad key).
        try:
            payload = json.load(error)
        except Exception:
            raise LastfmError(f"{method}: HTTP {error.code}") from error
    except Exception as error:
        raise LastfmError(f"{method}: {error}") from error
    if isinstance(payload, dict) and "error" in payload:
        raise LastfmError(f"{method}: {payload.get('message', payload['error'])}")
    return payload


def as_list(value: object) -> list:
    if isinstance(value, list):
        return value
    return [value] if value else []


VERSION_SUFFIX = re.compile(
    r"\s+[-–—]\s+.*\b(?:remaster(?:ed)?|version|edit|live|mono|stereo|mix|demo|acoustic)\b.*$",
    re.I,
)
LEADING_TRACK_NUMBER = re.compile(r"^\s*\d{1,3}\s*[.\-_]\s*")
TITLE_TRACK_NUMBER = re.compile(r"^\s*\d{1,3}[.\s_-]+")
ARTIST_SEPARATORS = re.compile(r"\s*(?:&|,|\+|\band\b|\bfeat\.?|\bft\.?|\bfeaturing\b|\bvs\.?|\bx\b|\bwith\b)\s*", re.I)


def smart_clean(value: str) -> str:
    """clean_match_text plus removal of ' - 2011 Remaster' style suffixes."""
    return clean_match_text(VERSION_SUFFIX.sub("", value))


def display_title(title: str) -> str:
    """Strip version notes so Last.fm gets 'Song 2', not 'Song 2 (2012 Remaster)'."""
    title = VERSION_SUFFIX.sub("", title)
    title = re.sub(r"\s*[(\[][^)\]]*(?:remaster|radio edit|single version|album version|explicit|clean)[^)\]]*[)\]]\s*$", "", title, flags=re.I)
    return title.strip()


def raw_artist_title(track: Path) -> tuple[str, str] | None:
    """Parse 'Artist - Title' from filenames such as:
    'Nirvana - Come As You Are', '001. Nirvana - Lithium',
    '01 - Linkin Park - Numb' and 'Daft Punk - 02 One More Time'.
    """
    stem = track.stem
    stripped = LEADING_TRACK_NUMBER.sub("", stem)
    for candidate in (stripped, stem):
        parts = re.split(r"\s[-–—]\s", candidate, maxsplit=1)
        if len(parts) == 2 and parts[0].strip() and parts[1].strip():
            return parts[0].strip(), parts[1].strip()
    return None


class LocalTrack:
    def __init__(self, path: Path, artist: str, title: str) -> None:
        self.path = path
        self.artist = artist
        # Album rips use 'Artist - 02 Title'; keep both variants so that
        # titles that really start with a number ('99 Luftballons') still match.
        no_number = TITLE_TRACK_NUMBER.sub("", title).strip() or title
        self.title = no_number
        self.title_keys = {key for key in (smart_clean(title), smart_clean(no_number)) if key}
        self.artist_key = smart_clean(artist)
        self.artist_keys = {self.artist_key} | {
            smart_clean(part) for part in ARTIST_SEPARATORS.split(artist) if smart_clean(part)
        }
        self.song_key = (self.artist_key, smart_clean(no_number))


class LibraryIndex:
    """Artist -> tracks index so Last.fm results can be matched quickly."""

    def __init__(self, tracks: list[Path]) -> None:
        self.tracks: list[LocalTrack] = []
        self.by_artist: dict[str, list[LocalTrack]] = {}
        for path in tracks:
            parsed = raw_artist_title(path)
            if not parsed:
                continue
            local = LocalTrack(path, *parsed)
            if not local.artist_key or not local.title_keys:
                continue
            self.tracks.append(local)
            for key in local.artist_keys:
                self.by_artist.setdefault(key, []).append(local)

    def artist_tracks(self, artist: str) -> list[LocalTrack]:
        wanted = smart_clean(artist)
        if not wanted:
            return []
        if wanted in self.by_artist:
            return list(self.by_artist[wanted])
        found: list[LocalTrack] = []
        for key in difflib.get_close_matches(wanted, list(self.by_artist), n=3, cutoff=0.85):
            found.extend(track for track in self.by_artist[key] if track not in found)
        return found

    def find(self, artist: str, title: str) -> LocalTrack | None:
        wanted_title = smart_clean(title)
        if not wanted_title:
            return None
        best: LocalTrack | None = None
        best_score = 0.0
        for track in self.artist_tracks(artist):
            score = max(difflib.SequenceMatcher(None, wanted_title, key).ratio() for key in track.title_keys)
            if score >= 0.88 and score > best_score:
                best, best_score = track, score
        return best

    def find_by_text(self, text: str) -> list[tuple[float, LocalTrack]]:
        """Rank library tracks against free text ('Artist - Title' or just 'Title')."""
        parts = re.split(r"\s[-–—]\s", text, maxsplit=1)
        ranked: list[tuple[float, LocalTrack]] = []
        if len(parts) == 2:
            exact = self.find(parts[0], parts[1])
            if exact:
                return [(1.0, exact)]
            wanted_artist, wanted_title = smart_clean(parts[0]), smart_clean(parts[1])
            for track in self.tracks:
                title_score = max(difflib.SequenceMatcher(None, wanted_title, key).ratio() for key in track.title_keys)
                if title_score < 0.6:
                    continue
                artist_score = max(difflib.SequenceMatcher(None, wanted_artist, key).ratio() for key in track.artist_keys)
                ranked.append((0.65 * title_score + 0.35 * artist_score, track))
        else:
            wanted = smart_clean(text)
            for track in self.tracks:
                title_score = max(difflib.SequenceMatcher(None, wanted, key).ratio() for key in track.title_keys)
                whole_score = difflib.SequenceMatcher(None, wanted, track.artist_key + min(track.title_keys, key=len)).ratio()
                ranked.append((max(title_score, whole_score), track))
        ranked.sort(key=lambda item: item[0], reverse=True)
        return ranked


def resolve_seed(song: str, index: LibraryIndex, library: Path) -> LocalTrack:
    """Turn the --smart-list argument (a file path or 'Artist - Title') into a library track."""
    for base in (Path.cwd(), ROOT, library):
        candidate = Path(song).expanduser()
        candidate = candidate if candidate.is_absolute() else base / candidate
        if candidate.is_file() and candidate.suffix.casefold() in SUPPORTED_AUDIO:
            candidate = candidate.resolve()
            for track in index.tracks:
                if track.path == candidate:
                    return track
            parsed = raw_artist_title(candidate)
            if not parsed:
                raise SystemExit(f"Cannot read 'Artist - Title' from the filename: {candidate.name}")
            return LocalTrack(candidate, *parsed)

    ranked = index.find_by_text(Path(song).stem if Path(song).suffix.casefold() in SUPPORTED_AUDIO else song)
    if not ranked or ranked[0][0] < 0.75:
        hint = "\n".join(f"  {track.path.name}" for _, track in ranked[:5])
        raise SystemExit(
            f"Could not find '{song}' in the library."
            + (f" Closest matches:\n{hint}" if hint else "")
            + "\nUse 'Artist - Title' or a path to the audio file."
        )
    score, seed = ranked[0]
    if score < 1.0:
        print(f"Using closest match: {seed.path.name}")
    return seed


def lastfm_similar_tracks(api_key: str, artist: str, title: str) -> list[tuple[str, str]]:
    payload = lastfm_call(api_key, "track.getSimilar", artist=artist, track=title, autocorrect=1, limit=250)
    results = []
    for entry in as_list(payload.get("similartracks", {}).get("track")):
        similar_artist = entry.get("artist", {})
        if isinstance(similar_artist, dict):
            similar_artist = similar_artist.get("name", "")
        if entry.get("name") and similar_artist:
            results.append((str(similar_artist), str(entry["name"])))
    return results


def lastfm_similar_artists(api_key: str, artist: str) -> list[str]:
    payload = lastfm_call(api_key, "artist.getSimilar", artist=artist, autocorrect=1, limit=150)
    return [
        str(entry["name"])
        for entry in as_list(payload.get("similarartists", {}).get("artist"))
        if entry.get("name")
    ]


def genre_fallback(seed: LocalTrack, index: LibraryIndex) -> list[LocalTrack]:
    """Offline similarity: same artist first, then tracks sharing a genre family."""
    seed_genre = embedded_genre(seed.path)
    families = {
        genre_family(genre_name(part.strip())) for part in (seed_genre or "").split(",") if part.strip()
    }
    same_artist = [track for track in index.artist_tracks(seed.artist)]
    random.shuffle(same_artist)
    same_genre: list[LocalTrack] = []
    if families:
        for track in index.tracks:
            genre = embedded_genre(track.path)
            if genre and families & {genre_family(genre_name(part.strip())) for part in genre.split(",") if part.strip()}:
                same_genre.append(track)
        random.shuffle(same_genre)
    print(
        "Seed genre: " + (", ".join(sorted(families)) if families else "unknown (only same-artist tracks can be used)")
    )
    return same_artist[:SMART_MAX_PER_ARTIST] + same_genre


def create_smart_playlist(song: str, candidates: list[Path], library: Path, count: int, output_dir: Path) -> None:
    index = LibraryIndex(candidates)
    seed = resolve_seed(song, index, library)
    seed_artist, seed_title = seed.artist, display_title(seed.title)
    print(f"Seed song: {seed_artist} - {seed_title}")

    chosen: list[LocalTrack] = [seed]
    used_paths = {seed.path}
    used_songs = {seed.song_key}
    per_artist: dict[str, int] = {seed.artist_key: 1}
    sources = {"Last.fm similar tracks": 0, "Last.fm similar artists": 0, "Same genre (offline)": 0}

    def add(track: LocalTrack | None, source: str, cap: int | None = None) -> bool:
        if track is None or len(chosen) >= count:
            return False
        if track.path in used_paths or track.song_key in used_songs:
            return False
        if cap is not None and per_artist.get(track.artist_key, 0) >= cap:
            return False
        chosen.append(track)
        used_paths.add(track.path)
        used_songs.add(track.song_key)
        per_artist[track.artist_key] = per_artist.get(track.artist_key, 0) + 1
        sources[source] += 1
        return True

    api_key = os.environ.get("LASTFM_API_KEY")
    not_found: list[tuple[int, str, str]] = []
    similar: list[tuple[str, str]] = []
    if api_key:
        # 1) Songs Last.fm lists as similar to the seed, in similarity order.
        # Every returned song is checked (the index makes this fast), so the
        # not-found summary covers the full Last.fm list, not just the top.
        try:
            similar = lastfm_similar_tracks(api_key, seed_artist, seed_title)
        except LastfmError as error:
            print(f"Last.fm similar tracks unavailable ({error}).")
            similar = []
        for rank, (artist, title) in enumerate(similar, start=1):
            local = index.find(artist, title)
            if local is None:
                not_found.append((rank, artist, title))
            else:
                add(local, "Last.fm similar tracks")

        # 2) Fill up with songs by similar artists (and a few by the seed artist).
        if len(chosen) < count:
            try:
                artists = [seed_artist] + lastfm_similar_artists(api_key, seed_artist)
            except LastfmError as error:
                print(f"Last.fm similar artists unavailable ({error}).")
                artists = [seed_artist]
            for artist in artists:
                tracks = index.artist_tracks(artist)
                random.shuffle(tracks)
                for track in tracks:
                    add(track, "Last.fm similar artists", cap=SMART_MAX_PER_ARTIST)
                if len(chosen) >= count:
                    break
    else:
        print("LASTFM_API_KEY is not set: using offline genre similarity instead of Last.fm.")
        print("Get a key at https://www.last.fm/api/account/create for better results.")

    # 3) Last resort (no key, or Last.fm found too little): same genre family.
    if len(chosen) < count:
        for track in genre_fallback(seed, index):
            add(track, "Same genre (offline)", cap=SMART_MAX_PER_ARTIST)
            if len(chosen) >= count:
                break

    # Seed name made safe for file names (used by the report and the playlist).
    safe_name = re.sub(r'[\\/:*?"<>|]+', "-", f"{seed_artist} - {seed_title}")

    if api_key and similar:
        report_not_found(
            f"songs similar to '{seed_artist} - {seed_title}'",
            len(similar),
            not_found,
            ROOT / f"lastfm_not_found - {safe_name}.log",
        )
        print()

    if len(chosen) < 2:
        raise SystemExit("No similar songs were found in the selected library folder.")

    title = f"Smart Mix — Songs Like {safe_name}"
    output = write_playlist(title, [track.path for track in chosen], output_dir)
    print(f"Created: {output}")
    print(f"Tracks: {len(chosen)} (seed + {len(chosen) - 1} similar)")
    for source, total in sources.items():
        if total:
            print(f"  {source}: {total}")
    if len(chosen) < count:
        print(f"Only {len(chosen)} of the requested {count} tracks could be found in the library.")


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="make_playlist.py",
        description=(
            "Create an M3U8 playlist from your local music library. By default, "
            "the script randomly selects 18–25 tracks from one genre family using "
            "embedded genre tags. Add --lastfm to use Last.fm's global chart and "
            "include chart songs found in your files, or --smart-list SONG to build "
            "a playlist of songs similar to SONG."
        ),
        epilog=(
            "Examples:\n"
            "  python3 make_playlist.py\n"
            "  python3 make_playlist.py --input-path \"000 Albums\"\n"
            "  python3 make_playlist.py --output-path \"Playlists/road trip\"\n"
            "  LASTFM_API_KEY=your_key python3 make_playlist.py --lastfm\n"
            "  LASTFM_API_KEY=your_key python3 make_playlist.py --lastfm --count 40 --input-path \"001 VA - Pop Songs\"\n"
            "  LASTFM_API_KEY=your_key python3 make_playlist.py --smart-list \"Nirvana - Come As You Are\"\n"
            "  LASTFM_API_KEY=your_key python3 make_playlist.py --smart-list \"002 VA - Rock Songs/ACDC - Highway to Hell.mp3\" --count 30\n\n"
            "--smart-list accepts 'Artist - Title', just a title, or a path to the audio file. It uses "
            "Last.fm similar tracks first, then songs by similar artists; without an API key it "
            "falls back to songs from the same genre family.\n"
            "Last.fm mode requires an API key from https://www.last.fm/api/account/create. "
            "Set it in the LASTFM_API_KEY environment variable. By default playlists are saved in Playlists/.") ,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--input-path",
        type=Path,
        help="Optional library folder to use instead of the full library. Relative paths are from the library folder.",
    )
    parser.add_argument(
        "--output-path",
        type=Path,
        help="Folder where the playlist will be saved. Relative paths are from the library folder.",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--lastfm",
        action="store_true",
        help="Build a playlist from Last.fm's global top tracks, matched to local files.",
    )
    mode.add_argument(
        "--smart-list",
        metavar="SONG",
        help="Build a playlist of songs similar to SONG ('Artist - Title' or a path to a file in the library).",
    )
    parser.add_argument(
        "--count",
        type=int,
        default=25,
        help="Number of tracks for --lastfm and --smart-list (default: 25).",
    )
    args = parser.parse_args()

    library = args.input_path if args.input_path and args.input_path.is_absolute() else ROOT / args.input_path if args.input_path else ROOT
    library = library.expanduser().resolve()
    if not library.is_dir():
        raise SystemExit(f"Library path is not a folder: {library}")

    output_dir = args.output_path if args.output_path and args.output_path.is_absolute() else ROOT / args.output_path if args.output_path else OUTPUT_DIR
    output_dir = output_dir.expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    candidates = library_tracks(library)
    if not candidates:
        raise SystemExit(
            "No audio files were found in that folder."
        )

    if (args.lastfm or args.smart_list) and args.count < 1:
        raise SystemExit("--count must be at least 1.")
    if args.smart_list:
        create_smart_playlist(args.smart_list, candidates, library, args.count, output_dir)
        return
    if args.lastfm:
        create_lastfm_playlist(candidates, args.count, output_dir)
        return
    create_genre_playlist(candidates, output_dir)


if __name__ == "__main__":
    main()
