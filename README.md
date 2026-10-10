# Music Library Scripts

Python utilities for keeping the Music Library organised: converting audio, cleaning up file names and genre tags, and building playlists.

All scripts need **Python 3.10+** and use only the standard library. Some also need **FFmpeg/FFprobe** on your `PATH` (`brew install ffmpeg` on macOS). Run any script with `--help` to see all its options.

| Script | Purpose | Changes files? | Needs |
|---|---|---|---|
| [`convert_flac_to_mp3.py`](#convert_flac_to_mp3py) | Convert FLAC to MP3, keeping tags and cover art | Creates MP3s | FFmpeg |
| [`rename_mp3_by_metadata.py`](#rename_mp3_by_metadatapy) | Rename MP3/FLAC files to `Artist - NN Title` from their tags | Renames files, may write tags | — |
| [`normalize_genres.py`](#normalize_genrespy) | Turn multi-genre tags like `Rock / Pop` into `Rock,Pop` | Rewrites tags (asks first) | FFmpeg + FFprobe |
| [`set_genre_from_list.py`](#set_genre_from_listpy) | Set one genre on every MP3 in a list | Rewrites tags | FFmpeg + FFprobe |
| [`make_playlist.py`](#make_playlistpy) | Genre mix, Last.fm chart mix, "songs like this" smart mix, all songs by an artist, or one `.m3u` per album/folder | Creates playlists | Last.fm API key (optional) |
| [`find_duplicate_songs.py`](#find_duplicate_songspy) | List songs that appear more than once in the library | No (report only) | — |

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

Renames the MP3 and FLAC files in a folder **and all its subfolders** (each file stays where it is) using their Artist, Title and track-number tags:

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
| `directory` | Folder containing the files to rename, searched recursively (required). |
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

## `make_playlist.py`

Builds playlists from the library. Modes 1–4 create a new `.m3u8` playlist and saves it in `Playlists/`, numbered after the playlists already there (e.g. `11 Smart Mix — Songs Like Nirvana - Come As You Are.m3u8`). Entries use paths relative to the playlist, and duplicate copies of a song across compilations are collapsed.

When run without `--input-path`, it uses the whole Music Library (the folder above `scripts/`). Relative `--input-path` / `--output-path` values are relative to the library folder.

It has five modes:

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

### 4. Artist list: every song by one artist (`--artist NAME`)

Builds a playlist with all the songs by `NAME` in the library, named e.g. `25 Counting Crows — All Songs.m3u8`. Albums come first in track order, followed by the compilations.

- Matching uses the `Artist - Title` file names and ignores case, accents and spacing (`linkin park` finds `Linkin Park`, `Linkin park` and `LinkinPark`); small typos are tolerated.
- Files whose name has no artist (e.g. `01. Mr. Blue Sky.mp3` in a compilation) are matched using their Artist and Title tags instead.
- A leading `The`, `Los`, `Las`, `El`, `La` or `Les` is ignored when comparing artists (`The Kinks` finds `Kinks`, `Ramones` finds `Los Ramones`), and version notes such as `(Live)`, `(Remaster)` or `(Edit)` are ignored in titles.
- Collaborations are included (`Artist & Other`, `Artist feat. Other`).
- The same song in several folders is added only once.
- No Last.fm key is needed, and `--count` is ignored: every song is included.
- If nothing matches, the closest artist names in the library are suggested.

```bash
python3 make_playlist.py --artist "Counting Crows"
python3 make_playlist.py --artist "Bon Jovi" --input-path "000 Albums"
```

### 5. One playlist per folder (`--by-folder-structure`)

Walks the library (or `--input-path`) recursively and creates one `.m3u` playlist for every folder that directly contains MP3 or FLAC files. Each playlist is named after its folder, lists the files in alphabetical order and uses relative paths. Existing playlists with the same name are overwritten (reported as `UPDATE`). This mode replaces the old `create_m3u_playlists.py`.

All playlists are saved in the folder given with `--output-path`, which is **required** in this mode (the script stops with an error without it). Entries point back to the music with relative paths.

```bash
python3 make_playlist.py --by-folder-structure --output-path "Playlists/Folders"                            # whole library
python3 make_playlist.py --by-folder-structure --output-path "Playlists/Folders" --input-path "000 Albums"  # only the albums
python3 make_playlist.py --by-folder-structure --output-path "Playlists/Folders" --dryrun                  # preview, writes nothing
```

### Songs Last.fm suggests that you don't have

Both Last.fm modes print a summary of the songs Last.fm returned that aren't in your library, ranked by their position in the Last.fm results (the top 20 on screen). The full list is saved in the library folder so you can use it as a shopping list:

- `--smart-list` saves one file per seed song, e.g. `lastfm_not_found - Nirvana - Come As You Are.log`. Reports for different songs are kept side by side; running the same song again replaces its report.
- `--lastfm` saves `lastfm_not_found.log`, replaced on each run.

- `--smart-list` checks **every** similar song Last.fm returns (up to 250).
- `--lastfm` checks chart positions only until the playlist is full, so the list covers the chart down to the last song used.

```text
Last.fm songs similar to 'Nirvana - Come As You Are': 250 songs checked, 31 in your library, 219 not found.
Songs not in your library (Last.fm rank):
   2. Bush - Glycerine
   5. Mudhoney - Touch Me I'm Sick
   ...
Full list saved to: /…/Music Library/lastfm_not_found - Nirvana - Come As You Are.log
```

### Options

| Option | Description |
|---|---|
| `--input-path FOLDER` | Use only this part of the library. |
| `--output-path FOLDER` | Save the playlist here instead of `Playlists/`. Required with `--by-folder-structure`. |
| `--lastfm` | Last.fm global chart mode. |
| `--smart-list SONG` | Similar-songs mode. Cannot be combined with `--lastfm`. |
| `--artist NAME` | All songs by one artist. |
| `--by-folder-structure` | One `.m3u` per folder with MP3/FLAC files, all saved in `--output-path`. |
| `--dryrun` | With `--by-folder-structure` only: list the playlists and tracks that would be written, without writing. |
| `--count N` | Number of tracks for `--lastfm` and `--smart-list` (default 25). |

`--lastfm`, `--smart-list`, `--artist` and `--by-folder-structure` can't be combined with each other.

### Notes

- **Last.fm API key:** create a free one at <https://www.last.fm/api/account/create> and pass it in the `LASTFM_API_KEY` environment variable. To avoid typing it each time, add `export LASTFM_API_KEY=your_key` to `~/.zshrc`.
- **File naming:** Last.fm results are matched to local files by name, so files should follow the `Artist - Title` pattern. Leading numbers such as `001. Artist - Title` work in both Last.fm modes. Album-style names (`Artist - 02 Title`) are currently matched only by `--smart-list`. Run `rename_mp3_by_metadata.py` first on badly named folders.
- **Genres:** MP3 genre tags are read without extra packages. Installing Mutagen (`pip3 install mutagen`) also enables genre reading for other formats.

---

## `find_duplicate_songs.py`

Scans the whole library (skipping `Playlists`, `scripts` and `tmp`) and lists every song that appears more than once. The report goes to **stdout**, so you can save it with `>`; progress messages go to stderr and stay out of the file. Nothing in the library is changed.

```bash
python3 find_duplicate_songs.py                       # show the report
python3 find_duplicate_songs.py > duplicates.log      # save it
python3 find_duplicate_songs.py --ignore-versions     # also merge live / remix / acoustic versions
```

Songs are matched by **artist + title**, read from the file name (`Artist - Title`, `Artist - 01 Title`, `001. Artist - Title`, `01 - Artist - Title`) or, when the name has no artist, from the tags. Matching ignores case, accents, punctuation, track numbers, a leading "The", artist order (`A & B` = `B & A`) and release notes such as `(2011 Remaster)`, `(Radio Edit)`, `(Single Version)` or `(Bonus Track)`. Featured artists count as artists, so `A - Song (feat. B)` matches `A & B - Song`.

Live, remix, acoustic, demo and instrumental versions are kept apart from the studio version. Tracks inside a live album folder (`MTV Unplugged`, `Live On Ten Legs`) count as live even when the file name doesn't say so.

For each duplicated song the report lists every copy with its size, and marks copies that are byte-for-byte **identical**. The header shows how many extra copies there are and how much space they use. Two extra sections come at the end:

- **Same name twice in one album**: usually different tracks whose names and tags are incomplete (e.g. three `Another Brick in the Wall Part` files with no part number). Worth fixing the names.
- **Files not checked**: files with no `Artist - Title` in either the name or the tags.

| Option | Description |
|---|---|
| `library` | Folder to scan (default: the library containing `scripts`). |
| `--exclude FOLDER` | Top-level folder to skip; repeat for several. Replaces the default list. |
| `--ignore-versions` | Treat live, remix, acoustic, demo… versions as the same song. |
| `--no-hash` | Skip the byte-identical check (faster). |
