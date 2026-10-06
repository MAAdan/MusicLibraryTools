#!/usr/bin/env bash
#
# Usage: post_processing.sh SOURCE_DIR DEST_DIR
#
#   SOURCE_DIR  folder with completed downloads (FLACs get converted, MP3s get moved)
#   DEST_DIR    folder the MP3s are moved into and then renamed by metadata
 
set -euo pipefail
 
if [[ $# -ne 2 ]]; then
    echo "Usage: $(basename "$0") SOURCE_DIR DEST_DIR" >&2
    exit 1
fi
 
SOURCE_DIR="$1"
DEST_DIR="$2"
 
# Folder this script lives in, so the Python scripts are found from any working directory
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
 
if [[ ! -d "$SOURCE_DIR" ]]; then
    echo "Error: source directory not found: $SOURCE_DIR" >&2
    exit 1
fi
 
mkdir -p "$DEST_DIR"
 
python3 "$SCRIPT_DIR/convert_flac_to_mp3.py" "$SOURCE_DIR"
find "$SOURCE_DIR" -type f -name "*.mp3" -print0 | xargs -0 -J % mv % "$DEST_DIR"
if find "$DEST_DIR" -mindepth 1 -maxdepth 1 | read; then
   python3 "$SCRIPT_DIR/rename_mp3_by_metadata.py" "$DEST_DIR"
else
   echo "$DEST_DIR is empty. No files have been renamed."
fi
