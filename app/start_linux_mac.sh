#!/usr/bin/env sh
set -eu
cd "$(dirname "$0")"
python3 ./kml_spiral_editor.py --port 7872
