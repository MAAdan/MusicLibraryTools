#!/usr/bin/env python3
"""
Rename MP3 and FLAC files using Artist, Song, and track-number metadata.

Filename format when a track number is available:
    Artist Name - 01 Song name.mp3
    Artist Name - 01 Song name.flac

Files without a track number use: Artist Name - Song name.ext

Files that are not MP3 or FLAC files are ignored.
When there is not enough metadata, the script asks for the right file name.
Only manually provided names are used to write Artist and Song metadata.
Use --dryrun to preview the new file names without changing anything.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
import tempfile
from pathlib import Path

sys.dont_write_bytecode = True

ID3V2_TEXT_FRAMES = {
    "TPE1": "artist",
    "TIT2": "title",
    "TRCK": "track_number",
    "TP1": "artist",
    "TT2": "title",
    "TRK": "track_number",
}
AUDIO_EXTENSIONS = {".mp3", ".flac"}
FLAC_VORBIS_COMMENT_BLOCK_TYPE = 4


def is_mp3_file(path: Path) -> bool:
    """Return whether a path is a regular MP3 file."""
    return path.is_file() and not path.is_symlink() and path.suffix.lower() == ".mp3"


def is_audio_file(path: Path) -> bool:
    """Return whether a path is a regular supported audio file."""
    return (
        path.is_file()
        and not path.is_symlink()
        and path.suffix.lower() in AUDIO_EXTENSIONS
    )


def synchsafe_to_int(data: bytes) -> int:
    """Convert a 4-byte synchsafe integer to a normal integer."""
    value = 0
    for byte in data:
        value = (value << 7) | (byte & 0x7F)
    return value


def int_to_synchsafe(value: int) -> bytes:
    """Convert a normal integer to a 4-byte synchsafe integer."""
    return bytes(
        [
            (value >> 21) & 0x7F,
            (value >> 14) & 0x7F,
            (value >> 7) & 0x7F,
            value & 0x7F,
        ]
    )


def decode_text_frame(data: bytes) -> str:
    """Decode an ID3 text frame."""
    if not data:
        return ""

    encoding_byte = data[0]
    text_data = data[1:]

    if encoding_byte == 0:
        encoding = "latin-1"
    elif encoding_byte == 1:
        encoding = "utf-16"
    elif encoding_byte == 2:
        encoding = "utf-16-be"
    elif encoding_byte == 3:
        encoding = "utf-8"
    else:
        encoding = "latin-1"

    return text_data.decode(encoding, errors="replace").replace("\x00", "").strip()


def encode_text_frame(frame_id: str, text: str, version: int = 3) -> bytes:
    """Build an ID3v2 text frame for the given tag version (2, 3 or 4).

    ID3v2.2/2.3 only allow Latin-1 or UTF-16, so UTF-16 with BOM is used there;
    ID3v2.4 uses UTF-8.
    """
    if version == 4:
        frame_data = b"\x03" + text.encode("utf-8")
    else:
        frame_data = b"\x01" + text.encode("utf-16")  # includes the BOM
    if version == 2:
        return frame_id.encode("latin-1") + len(frame_data).to_bytes(3, "big") + frame_data
    size = int_to_synchsafe(len(frame_data)) if version == 4 else len(frame_data).to_bytes(4, "big")
    return frame_id.encode("latin-1") + size + b"\x00\x00" + frame_data


def read_id3v2_metadata(path: Path) -> dict[str, str]:
    """Read Artist, Title, and track number from ID3v2 metadata when available."""
    metadata: dict[str, str] = {}

    with path.open("rb") as file:
        header = file.read(10)
        if len(header) < 10 or header[:3] != b"ID3":
            return metadata

        major_version = header[3]
        tag_size = synchsafe_to_int(header[6:10])
        tag_data = file.read(tag_size)

    offset = 0
    while offset < len(tag_data):
        if major_version == 2:
            frame_header = tag_data[offset : offset + 6]
            if len(frame_header) < 6:
                break

            frame_id = frame_header[:3].decode("latin-1", errors="ignore")
            frame_size = int.from_bytes(frame_header[3:6], byteorder="big")
            frame_header_size = 6
        else:
            frame_header = tag_data[offset : offset + 10]
            if len(frame_header) < 10:
                break

            frame_id = frame_header[:4].decode("latin-1", errors="ignore")
            if major_version == 4:
                frame_size = synchsafe_to_int(frame_header[4:8])
            else:
                frame_size = int.from_bytes(frame_header[4:8], byteorder="big")
            frame_header_size = 10

        if not frame_id.strip("\x00") or frame_size <= 0:
            break

        frame_start = offset + frame_header_size
        frame_end = frame_start + frame_size
        frame_data = tag_data[frame_start:frame_end]

        field = ID3V2_TEXT_FRAMES.get(frame_id)
        if field:
            value = decode_text_frame(frame_data)
            if value:
                metadata[field] = value

        if all(metadata.get(field) for field in ("artist", "title", "track_number")):
            break

        offset = frame_end

    return metadata


def read_id3v1_metadata(path: Path) -> dict[str, str]:
    """Read Artist, Title, and track number from ID3v1 metadata when available."""
    metadata: dict[str, str] = {}

    with path.open("rb") as file:
        try:
            file.seek(-128, 2)
        except OSError:
            return metadata

        tag = file.read(128)

    if len(tag) != 128 or tag[:3] != b"TAG":
        return metadata

    title = tag[3:33].decode("latin-1", errors="replace").rstrip("\x00 ").strip()
    artist = tag[33:63].decode("latin-1", errors="replace").rstrip("\x00 ").strip()

    if title:
        metadata["title"] = title
    if artist:
        metadata["artist"] = artist

    # ID3v1.1 stores the track number in the final byte when byte 125 is zero.
    if tag[125] == 0 and tag[126]:
        metadata["track_number"] = str(tag[126])

    return metadata


def mp3_metadata(path: Path) -> dict[str, str]:
    """Return available MP3 Artist, Title, and track-number metadata."""
    metadata = read_id3v2_metadata(path)

    if not all(metadata.get(field) for field in ("artist", "title", "track_number")):
        fallback_metadata = read_id3v1_metadata(path)
        metadata = {**fallback_metadata, **metadata}

    return metadata


def flac_metadata_blocks(data: bytes) -> list[dict[str, int | bool]]:
    """Return FLAC metadata block positions."""
    if not data.startswith(b"fLaC"):
        return []

    blocks: list[dict[str, int | bool]] = []
    offset = 4

    while offset + 4 <= len(data):
        header_start = offset
        header = data[offset]
        block_type = header & 0x7F
        is_last = bool(header & 0x80)
        length = int.from_bytes(data[offset + 1 : offset + 4], byteorder="big")
        data_start = offset + 4
        data_end = data_start + length

        if data_end > len(data):
            break

        blocks.append(
            {
                "header_start": header_start,
                "data_start": data_start,
                "data_end": data_end,
                "type": block_type,
                "is_last": is_last,
                "length": length,
            }
        )

        offset = data_end
        if is_last:
            break

    return blocks


def parse_vorbis_comment_block(block_data: bytes) -> dict[str, str]:
    """Read Artist, Title, and track number from a FLAC Vorbis comment block."""
    metadata: dict[str, str] = {}
    offset = 0

    if len(block_data) < 8:
        return metadata

    vendor_length = int.from_bytes(block_data[offset : offset + 4], byteorder="little")
    offset += 4 + vendor_length

    if offset + 4 > len(block_data):
        return metadata

    comment_count = int.from_bytes(block_data[offset : offset + 4], byteorder="little")
    offset += 4

    for _ in range(comment_count):
        if offset + 4 > len(block_data):
            break

        comment_length = int.from_bytes(block_data[offset : offset + 4], byteorder="little")
        offset += 4
        comment_data = block_data[offset : offset + comment_length]
        offset += comment_length

        comment = comment_data.decode("utf-8", errors="replace")
        if "=" not in comment:
            continue

        key, value = comment.split("=", 1)
        key = key.strip().lower()
        value = value.strip()

        if key == "artist" and value:
            metadata["artist"] = value
        elif key == "title" and value:
            metadata["title"] = value
        elif key == "tracknumber" and value:
            metadata["track_number"] = value

    return metadata


def flac_metadata(path: Path) -> dict[str, str]:
    """Return available FLAC Artist, Title, and track-number metadata."""
    data = path.read_bytes()
    for block in flac_metadata_blocks(data):
        if block["type"] != FLAC_VORBIS_COMMENT_BLOCK_TYPE:
            continue

        block_data = data[int(block["data_start"]) : int(block["data_end"])]
        return parse_vorbis_comment_block(block_data)

    return {}


def audio_metadata(path: Path) -> dict[str, str]:
    """Return Artist, Title, and track-number metadata for supported audio."""
    if path.suffix.lower() == ".mp3":
        return mp3_metadata(path)
    if path.suffix.lower() == ".flac":
        return flac_metadata(path)
    return {}


FRAME_ID_RE = re.compile(rb"^[A-Z0-9]+$")


class TagError(Exception):
    """Raised when an existing tag cannot be parsed safely."""


def remove_unsynchronisation(data: bytes) -> bytes:
    """Undo ID3 unsynchronisation (every 0xFF 0x00 pair becomes 0xFF)."""
    return data.replace(b"\xff\x00", b"\xff")


def split_id3v2(data: bytes) -> tuple[int, list[tuple[bytes, bytes]], bytes]:
    """Split MP3 data into (tag version, raw frames, audio data).

    Each raw frame is (frame_id, complete frame bytes including its header),
    so frames are written back exactly as they were. Returns version 0 and no
    frames when the file has no ID3v2 tag.
    """
    if len(data) < 10 or data[:3] != b"ID3":
        return 0, [], data

    version = data[3]
    flags = data[5]
    if version not in (2, 3, 4):
        raise TagError(f"unsupported ID3v2.{version} tag")
    tag_size = synchsafe_to_int(data[6:10])
    footer_size = 10 if version == 4 and flags & 0x10 else 0
    tag_end = 10 + tag_size
    if tag_end > len(data):
        raise TagError("ID3v2 tag is larger than the file")
    tag = data[10:tag_end]
    audio = data[tag_end + footer_size:]

    if version == 2 and flags & 0x40:
        raise TagError("compressed ID3v2.2 tags are not supported")
    # ID3v2.2/2.3 apply unsynchronisation to the whole tag; v2.4 marks it per
    # frame, so v2.4 frames are copied untouched with their own flags.
    if version in (2, 3) and flags & 0x80:
        tag = remove_unsynchronisation(tag)

    offset = 0
    if version in (3, 4) and flags & 0x40:  # extended header: skipped, not kept
        if len(tag) < 4:
            raise TagError("truncated extended header")
        ext_size = synchsafe_to_int(tag[:4]) if version == 4 else int.from_bytes(tag[:4], "big") + 4
        offset = ext_size

    header_size = 6 if version == 2 else 10
    id_size = 3 if version == 2 else 4
    frames: list[tuple[bytes, bytes]] = []
    while offset + header_size <= len(tag):
        frame_id = tag[offset:offset + id_size]
        if frame_id.strip(b"\x00") == b"":
            break  # padding reached
        if not FRAME_ID_RE.match(frame_id):
            raise TagError(f"invalid frame id {frame_id!r} at byte {offset}")
        if version == 2:
            frame_size = int.from_bytes(tag[offset + 3:offset + 6], "big")
        elif version == 4:
            frame_size = synchsafe_to_int(tag[offset + 4:offset + 8])
        else:
            frame_size = int.from_bytes(tag[offset + 4:offset + 8], "big")
        frame_end = offset + header_size + frame_size
        if frame_end > len(tag):
            raise TagError(f"frame {frame_id.decode('latin-1')} runs past the end of the tag")
        frames.append((frame_id, tag[offset:frame_end]))
        offset = frame_end
    return version, frames, audio


def update_id3v1(audio: bytes, artist: str, title: str) -> bytes:
    """Update Artist/Title in an existing ID3v1 footer, leaving other fields."""
    if len(audio) < 128 or audio[-128:-125] != b"TAG":
        return audio

    def field(text: str) -> bytes:
        return text.encode("latin-1", errors="replace")[:30].ljust(30, b"\x00")

    footer = bytearray(audio[-128:])
    footer[3:33] = field(title)
    footer[33:63] = field(artist)
    return audio[:-128] + bytes(footer)


def write_mp3_artist_title_metadata(path: Path, artist: str, title: str) -> None:
    """Set Artist and Title in the MP3's tags, keeping every other tag.

    All existing ID3v2 frames (album, genre, track, year, cover art, lyrics,
    ...) are copied unchanged; only the artist and title frames are replaced.
    The tag keeps its ID3v2 version (a new ID3v2.3 tag is created when the file
    has none) and an existing ID3v1 footer is updated as well. The file is
    written to a temporary copy first and then swapped in.
    """
    original_data = path.read_bytes()
    try:
        version, frames, audio_data = split_id3v2(original_data)
    except TagError as error:
        raise ValueError(f"Not changing tags of {path.name}: {error}") from error

    if version == 0:
        version = 3
    artist_id, title_id = (b"TP1", b"TT2") if version == 2 else (b"TPE1", b"TIT2")
    kept = [raw for frame_id, raw in frames if frame_id not in (artist_id, title_id)]
    new_frames = [
        encode_text_frame(artist_id.decode(), artist, version),
        encode_text_frame(title_id.decode(), title, version),
    ]
    body = b"".join(new_frames + kept)
    # Unsynchronisation, extended header and footer flags are all cleared:
    # frames are written in plain form (v2.4 frames carry their own flags).
    header = b"ID3" + bytes([version, 0, 0]) + int_to_synchsafe(len(body))
    new_data = header + body + update_id3v1(audio_data, artist, title)

    with tempfile.NamedTemporaryFile(
        prefix=f".{path.stem}.", suffix=path.suffix, dir=path.parent, delete=False
    ) as temp_file:
        temp_file.write(new_data)
        temp_path = Path(temp_file.name)
    try:
        os.replace(temp_path, path)
    finally:
        temp_path.unlink(missing_ok=True)


def build_vorbis_comment_block(existing_block_data: bytes | None, artist: str, title: str) -> bytes:
    """Build a FLAC Vorbis comment block, preserving non-artist/title comments."""
    vendor = b"Python metadata script"
    comments: list[str] = []

    if existing_block_data:
        offset = 0
        if len(existing_block_data) >= 8:
            vendor_length = int.from_bytes(existing_block_data[offset : offset + 4], "little")
            offset += 4
            vendor = existing_block_data[offset : offset + vendor_length]
            offset += vendor_length

            if offset + 4 <= len(existing_block_data):
                comment_count = int.from_bytes(existing_block_data[offset : offset + 4], "little")
                offset += 4

                for _ in range(comment_count):
                    if offset + 4 > len(existing_block_data):
                        break
                    comment_length = int.from_bytes(existing_block_data[offset : offset + 4], "little")
                    offset += 4
                    comment_data = existing_block_data[offset : offset + comment_length]
                    offset += comment_length
                    comment = comment_data.decode("utf-8", errors="replace")
                    key = comment.split("=", 1)[0].strip().lower()
                    if key not in {"artist", "title"}:
                        comments.append(comment)

    comments.extend([f"ARTIST={artist}", f"TITLE={title}"])

    block = len(vendor).to_bytes(4, "little") + vendor
    block += len(comments).to_bytes(4, "little")
    for comment in comments:
        encoded_comment = comment.encode("utf-8")
        block += len(encoded_comment).to_bytes(4, "little") + encoded_comment

    return block


def flac_block_header(block_type: int, is_last: bool, length: int) -> bytes:
    """Build a FLAC metadata block header."""
    return bytes([(0x80 if is_last else 0) | block_type]) + length.to_bytes(3, "big")


def write_flac_artist_title_metadata(path: Path, artist: str, title: str) -> None:
    """Write Artist and Title to the FLAC Vorbis comment metadata block."""
    data = path.read_bytes()
    blocks = flac_metadata_blocks(data)
    if not blocks:
        raise ValueError(f"Not a valid FLAC file: {path}")

    for block in blocks:
        if block["type"] != FLAC_VORBIS_COMMENT_BLOCK_TYPE:
            continue

        existing_block_data = data[int(block["data_start"]) : int(block["data_end"])]
        new_block_data = build_vorbis_comment_block(existing_block_data, artist, title)
        header = flac_block_header(
            FLAC_VORBIS_COMMENT_BLOCK_TYPE,
            bool(block["is_last"]),
            len(new_block_data),
        )
        path.write_bytes(
            data[: int(block["header_start"])]
            + header
            + new_block_data
            + data[int(block["data_end"]) :]
        )
        return

    first_block = blocks[0]
    new_block_data = build_vorbis_comment_block(None, artist, title)
    new_block = flac_block_header(
        FLAC_VORBIS_COMMENT_BLOCK_TYPE,
        False,
        len(new_block_data),
    ) + new_block_data

    if bool(first_block["is_last"]):
        adjusted_first_header = flac_block_header(
            int(first_block["type"]),
            False,
            int(first_block["length"]),
        )
        path.write_bytes(
            data[: int(first_block["header_start"])]
            + adjusted_first_header
            + data[int(first_block["data_start"]) : int(first_block["data_end"])]
            + flac_block_header(FLAC_VORBIS_COMMENT_BLOCK_TYPE, True, len(new_block_data))
            + new_block_data
            + data[int(first_block["data_end"]) :]
        )
    else:
        path.write_bytes(
            data[: int(first_block["data_end"])]
            + new_block
            + data[int(first_block["data_end"]) :]
        )


def write_artist_title_metadata(path: Path, artist: str, title: str) -> None:
    """Write Artist and Title metadata to a supported audio file."""
    if path.suffix.lower() == ".mp3":
        write_mp3_artist_title_metadata(path, artist, title)
    elif path.suffix.lower() == ".flac":
        write_flac_artist_title_metadata(path, artist, title)
    else:
        raise ValueError(f"Unsupported file type: {path}")


def clean_filename(name: str) -> str:
    """Remove path separators and unsafe control characters from a filename."""
    cleaned = "".join(
        "_" if character in {"/", "\\"} or ord(character) < 32 else character
        for character in name
    ).strip()
    return cleaned


def artist_title_from_filename(filename: str) -> tuple[str, str] | None:
    """Extract artist and title from 'Artist - Song.ext' style names."""
    stem = Path(filename).stem
    separator = " - " if " - " in stem else "-"

    if separator not in stem:
        return None

    artist, title = stem.split(separator, 1)
    artist = artist.strip()
    title = title.strip()

    if not artist or not title:
        return None

    return artist, title


def formatted_track_number(track_number: str) -> str | None:
    """Return a filename-safe track number, padding single digits with a zero."""
    first_value = track_number.strip().split("/", 1)[0].strip()
    if not first_value.isdecimal():
        return None

    number = int(first_value)
    if number < 1:
        return None
    return f"{number:02d}" if number < 10 else str(number)


def target_name_and_manual_metadata(path: Path) -> tuple[str, tuple[str, str] | None]:
    """Build the target filename and optional metadata from manual input only."""
    metadata = audio_metadata(path)
    artist = metadata.get("artist", "").strip()
    title = metadata.get("title", "").strip()
    track_number = formatted_track_number(metadata.get("track_number", ""))

    if artist and title:
        track_prefix = f"{track_number} " if track_number else ""
        return clean_filename(f"{artist} - {track_prefix}{title}{path.suffix.lower()}"), None

    provided_name = input(
        f'It is not possible to get enough metadata for the file "{path.name}". '
        "Please provide the right file name: "
    ).strip()

    if not provided_name:
        provided_name = path.stem

    provided_name = clean_filename(provided_name)
    if Path(provided_name).suffix.lower() not in AUDIO_EXTENSIONS:
        provided_name = f"{provided_name}{path.suffix.lower()}"

    return provided_name, artist_title_from_filename(provided_name)


def unique_target(path: Path, target_name: str, used_targets: set[Path]) -> Path:
    """Build a non-conflicting target path."""
    target = path.parent / target_name
    original_target = target

    counter = 1
    while (target.exists() and target.resolve() != path.resolve()) or target in used_targets:
        target = path.parent / f"{original_target.stem}_{counter}{original_target.suffix}"
        counter += 1

    used_targets.add(target)
    return target


def rename_audio_files(directory: Path, dryrun: bool) -> None:
    if not directory.exists():
        raise FileNotFoundError(f"Directory does not exist: {directory}")
    if not directory.is_dir():
        raise NotADirectoryError(f"Path is not a directory: {directory}")

    files = sorted(path for path in directory.iterdir() if is_audio_file(path))

    if not files:
        print(f"No MP3 or FLAC files found in {directory}")
        return

    used_targets: set[Path] = set()

    for path in files:
        target_name, manual_metadata_to_write = target_name_and_manual_metadata(path)
        target = unique_target(path, target_name, used_targets)

        if manual_metadata_to_write:
            artist, title = manual_metadata_to_write
            if dryrun:
                print(f"DRYRUN METADATA: {path.name} -> Artist: {artist}, Song: {title}")
            else:
                try:
                    write_artist_title_metadata(path, artist, title)
                    print(f"UPDATED METADATA: {path.name} -> Artist: {artist}, Song: {title}")
                except (OSError, ValueError) as error:
                    print(f"METADATA NOT UPDATED: {error}", file=sys.stderr)

        if path.resolve() == target.resolve():
            print(f"UNCHANGED: {path}")
            continue

        if dryrun:
            print(f"DRYRUN: {path.name} -> {target.name}")
        else:
            path.rename(target)
            print(f"RENAMED: {path} -> {target.name}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Rename MP3 and FLAC files using Artist, Song, and track metadata."
    )
    parser.add_argument(
        "directory",
        type=Path,
        help="Directory containing the MP3 or FLAC files to rename.",
    )
    parser.add_argument(
        "--dryrun",
        action="store_true",
        help="Show the new file names without renaming any files.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    rename_audio_files(args.directory.expanduser().resolve(), args.dryrun)


if __name__ == "__main__":
    main()
