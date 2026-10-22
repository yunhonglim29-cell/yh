#!/usr/bin/env sh
set -eu
cd "$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
if ! command -v python3 >/dev/null 2>&1; then
  printf 'Install Python 3.13, then run this file again.\n' >&2
  exit 1
fi
if [ ! -f .venv/bin/python ]; then python3 -m venv .venv; fi
.venv/bin/python -m pip install -r requirements.txt
printf '\nOpen http://localhost:8000 in your browser.\nOrganiser dashboard: http://localhost:8000/admin\nSave the first-run password printed below.\nKeep this terminal open while playing. Ctrl+C stops the server.\n\n'
exec .venv/bin/python run.py
