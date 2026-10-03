# Music Library Scripts

Python utilities for keeping the Music Library organised: converting audio, cleaning up file names and genre tags, and building playlists.

All scripts need **Python 3.10+** and use only the standard library. Some also need **FFmpeg/FFprobe** on your `PATH` (`brew install ffmpeg` on macOS). Run any script with `--help` to see all its options.

| Script | Purpose | Changes files? | Needs |
|---|---|---|---|
| [`convert_flac_to_mp3.py`](#convert_flac_to_mp3py) | Convert FLAC to MP3, keeping tags and cover art | Creates MP3s | FFmpeg |
| [`rename_mp3_by_metadata.py`](#rename_mp3_by_metadatapy) | Rename MP3/FLAC files to `Artist - NN Title` from their tags | Renames files, may write tags | — |
| [`normalize_genres.py`](#normalize_genrespy) | Turn multi-genre tags like `Rock / Pop` into `Rock,Pop` | Rewrites tags (asks first) | FFmpeg + FFprobe |
| [`set_genre_from_list.py`](#set_genre_from_listpy) | Set one genre on every MP3 in a list | Rewrites tags | FFmpeg + FFprobe |
| [`create_m3u_playlists.py`](#create_m3u_playlistspy) | One `.m3u` playlist per album/folder | Creates playlists | — |
| [`make_playlist.py`](#make_playlistpy) | Genre mix, Last.fm chart mix, or "songs like this" smart mix | Creates playlists | Last.fm API key (optional) |

A typical workflow for new music: **convert** FLACs → **rename** files from their tags → **normalise / set genres** → **build playlists**.

---

## `convert_flac_to_mp3.py`

Converts FLAC files to MP3 with FFmpeg (LAME encoder), copying all tags, embedded cover art and chapters. Tags are written as ID3v2.3 plus an ID3v1 footer for maximum player compatibility.

By default it searches the folder recursively and writes each MP3 next to its FLAC. The FLAC files are left untouched and existing MP3s are skipped unless you pass `--overwrite`.

```bash
python3 convert_flac_to_mp3.py "/path/to/album"                      # 320 kbps CBR
python3 convert_flac_to_mp3.py "/path/to/album" --quality 0          # best-quality VBR
python3 convert_flac_to_mp3.py "/path/to/music" --output-dir "/path/to/mp3s"
python3 convert_flac_to_mp3.py "/path/to/music" --dry-run            # preview only
```

| Option | Description |
|---|---|
| `path` | Folder containing FLAC files (required). |
| `--bitrate RATE` | Constant bitrate, e.g. `256k` (default `320k`). |
| `--quality 0-9` | LAME VBR quality instead of a fixed bitrate (0 = best, 9 = smallest). Cannot be combined with `--bitrate`. |
| `--sample-rate HZ` | Output sample rate, e.g. `44100`. |
| `--channels N` | Output channel count (1–8). |
| `--output-dir DIR` | Write MP3s here, mirroring the source folder structure. |
| `--no-recursive` | Only convert FLACs directly inside `path`. |
| `--overwrite` | Replace MP3s that already exist. |
| `--dry-run` | Show what would be converted without writing anything. |

Prints a summary (`converted / skipped / failed`) and exits with code 1 if any conversion failed.

---

## `rename_mp3_by_metadata.py`

Renames the MP3 and FLAC files in **one folder** (not recursive) using their Artist, Title and track-number tags:

```text
Artist Name - 01 Song name.mp3      # when a track number is present
Artist Name - Song name.flac        # when it is not
```

Tags are read directly from the file (ID3v2.2/2.3/2.4 with ID3v1 fallback for MP3, Vorbis comments for FLAC); no extra packages are needed. Single-digit track numbers are zero-padded, `/` and `\` in names are replaced with `_`, and name clashes get a `_1`, `_2`… suffix. Other file types are ignored.

```bash
python3 rename_mp3_by_metadata.py "/path/to/album" --dryrun   # preview
python3 rename_mp3_by_metadata.py "/path/to/album"            # rename
```

| Option | Description |
|---|---|
| `directory` | Folder containing the files to rename (required). |
| `--dryrun` | Show the new names (and any tag updates) without changing files. |

**Missing tags:** if a file has no Artist or Title, the script asks you to type the correct file name (press Enter to keep the current one). If you type a name like `Alex Warren - Ordinary`, the Artist and Song are also written back into the file's tags.

Only Artist and Title are changed. All other tags are kept exactly as they were, including album, genre, track number, year, lyrics and cover art. For MP3s the ID3v2 version (2.2, 2.3 or 2.4) is kept, an existing ID3v1 tag is updated too, and the file is written to a temporary copy before replacing the original. If a file's ID3 tag is damaged and can't be read safely, its tags are left untouched and the problem is reported (`METADATA NOT UPDATED`).

---

## `normalize_genres.py`

Recursively scans audio files (`mp3, flac, m4a, mp4, ogg, opus, oga, aiff, aif, wav, wma, ape, wv`) and finds Genre tags that contain punctuation separating several genres, such as `Rock / Pop` or `Rock; Alternative`. For each one it shows the current and proposed value, with genres joined by commas and no spaces (`Rock,Pop`):

- Press **Enter** or type **`y`** to save the proposed value.
- Type **`n`** to enter your own genre instead; leave it blank to skip the file. Spaces after commas in your entry are removed.

`R&B` is recognised as a single genre and left alone. Tags are updated by remuxing with FFmpeg (stream copy), so the audio is not re-encoded and other tags are preserved.

```bash
python3 normalize_genres.py "/path/to/music"
```

| Option | Description |
|---|---|
| `path` | Folder to scan recursively (required). |

Prints a summary (`updated / skipped / already consistent / failed`) and exits with code 1 if any file failed.

---

## `set_genre_from_list.py`

Writes the same Genre value to every MP3 listed in a text file. Useful together with `make_playlist.py`, which logs files without a readable genre to `no_readable_tag_error.log`.

The list file has one path per line. Relative paths are resolved from the list file's folder, and blank lines or lines starting with `#` are ignored. Non-MP3 and missing files are skipped and reported.

```bash
python3 set_genre_from_list.py --input-file "/path/to/mp3-files.txt" --genre "Rock,Pop"
```

| Option | Description |
|---|---|
| `--input-file FILE` | Text file with one MP3 path per line (required). |
| `--genre GENRE` | Genre to write to every listed MP3 (required). |

Each file is probed with FFprobe and then stream-copied with FFmpeg (no re-encoding, other tags kept; written as ID3v2.3 + ID3v1).

---

## `create_m3u_playlists.py`

Walks a music collection recursively and creates one `.m3u` playlist for every folder that directly contains MP3 or FLAC files. Each playlist is named after its folder, lists the files in alphabetical order and uses relative paths. Existing playlists with the same name are overwritten (reported as `UPDATE`).

```text
/Music/Album/Album.m3u
```

```bash
python3 create_m3u_playlists.py "/path/to/music"                                   # playlist inside each folder
python3 create_m3u_playlists.py "/path/to/music" --output-path "/path/to/playlists" # all playlists in one folder
python3 create_m3u_playlists.py "/path/to/music" --dryrun                          # preview
```

| Option | Description |
|---|---|
| `path` | Root of the music collection (required). |
| `--output-path DIR` | Put all playlists in this folder; entries then point back to the music with relative paths. |
| `--dryrun` | List the playlists and tracks that would be written without creating files. |

---

## `make_playlist.py`

Creates a new `.m3u8` playlist from the library and saves it in `Playlists/`, numbered after the playlists already there (e.g. `11 Smart Mix — Songs Like Nirvana - Come As You Are.m3u8`). Entries use paths relative to the playlist, and duplicate copies of a song across compilations are collapsed.

When run without `--input-path`, it uses the whole Music Library (the folder above `scripts/`). Relative `--input-path` / `--output-path` values are relative to the library folder.

It has three modes:

### 1. Genre mix (default)

Picks 18–25 random tracks from one genre family, for example Rock, Pop, Heavy Metal or Electronic & Dance, and gives the playlist a random title. Genres are read from the files' tags, and detailed genres are grouped into broad families. Files with no readable genre are listed in `no_readable_tag_error.log` in the library folder.

```bash
python3 make_playlist.py
python3 make_playlist.py --input-path "000 Albums"
```

### 2. Last.fm global chart (`--lastfm`)

Downloads Last.fm's current global top tracks and builds a playlist from those songs found in the library, in chart order (default 25).

```bash
LASTFM_API_KEY=your_key python3 make_playlist.py --lastfm
LASTFM_API_KEY=your_key python3 make_playlist.py --lastfm --count 40 --input-path "001 VA - Pop Songs"
```

### 3. Smart list: songs similar to a song (`--smart-list SONG`)

Builds a playlist that starts with `SONG` and continues with similar songs from the library (default 25 tracks):

1. **Last.fm similar tracks** for that song, most similar first.
2. If more are needed, **songs by Last.fm similar artists**, plus a few more by the same artist.
3. If there's still room, or no API key is set, **songs from the same genre family** (offline, from tags).

No artist gets more than 3 tracks in steps 2 and 3. `SONG` can be given as:

- `"Artist - Title"`, e.g. `"Nirvana - Come As You Are"` (small typos are fine);
- just a title, e.g. `"one more time"`;
- a path to the file, e.g. `"002 VA - Rock Songs/ACDC - Highway to Hell.mp3"`.

When the script picks a close match it prints which file it used.

```bash
LASTFM_API_KEY=your_key python3 make_playlist.py --smart-list "Nirvana - Come As You Are"
LASTFM_API_KEY=your_key python3 make_playlist.py --smart-list "Radiohead - Creep" --count 40
python3 make_playlist.py --smart-list "Daft Punk - One More Time"   # no key: genre-based fallback
```

### Options

| Option | Description |
|---|---|
| `--input-path FOLDER` | Use only this part of the library. |
| `--output-path FOLDER` | Save the playlist here instead of `Playlists/`. |
| `--lastfm` | Last.fm global chart mode. |
| `--smart-list SONG` | Similar-songs mode. Cannot be combined with `--lastfm`. |
| `--count N` | Number of tracks for `--lastfm` and `--smart-list` (default 25). |

### Notes

- **Last.fm API key:** create a free one at <https://www.last.fm/api/account/create> and pass it in the `LASTFM_API_KEY` environment variable. To avoid typing it each time, add `export LASTFM_API_KEY=your_key` to `~/.zshrc`.
- **File naming:** Last.fm results are matched to local files by name, so files should follow the `Artist - Title` pattern. Leading numbers such as `001. Artist - Title` work in both Last.fm modes. Album-style names (`Artist - 02 Title`) are currently matched only by `--smart-list`. Run `rename_mp3_by_metadata.py` first on badly named folders.
- **Genres:** MP3 genre tags are read without extra packages. Installing Mutagen (`pip3 install mutagen`) also enables genre reading for other formats.
