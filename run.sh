#!/usr/bin/env bash
# Starts the service on $PORT (default 8080).
#
# The upstream host is read from $FX_UPSTREAM_BASE (default
# https://api.frankfurter.dev) inside the application — nothing here or in the
# code hardcodes it.
set -euo pipefail
cd "$(dirname "$0")"

PYTHON_BIN="${PYTHON:-python3}"
VENV=".venv"

if [ ! -d "$VENV" ]; then
  "$PYTHON_BIN" -m venv "$VENV"
fi

# Best effort: if the machine is offline but the venv is already populated, we
# carry on rather than failing to start.
"$VENV/bin/pip" install --quiet --disable-pip-version-check -r requirements.txt || true

if ! "$VENV/bin/python" -c "import fastapi, uvicorn, httpx" >/dev/null 2>&1; then
  echo "Dependencies are missing and could not be installed. Run: pip install -r requirements.txt" >&2
  exit 1
fi

exec "$VENV/bin/uvicorn" app.main:app --host 0.0.0.0 --port "${PORT:-8080}"
