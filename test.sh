#!/usr/bin/env bash
# Runs the tests. They never open a socket: the upstream is served in-process
# by an httpx MockTransport, so the suite passes with no network at all and
# ignores whatever $FX_UPSTREAM_BASE points at.
set -euo pipefail
cd "$(dirname "$0")"

PYTHON_BIN="${PYTHON:-python3}"
VENV=".venv"

if [ ! -d "$VENV" ]; then
  "$PYTHON_BIN" -m venv "$VENV"
fi

"$VENV/bin/pip" install --quiet --disable-pip-version-check -r requirements-dev.txt || true

if ! "$VENV/bin/python" -c "import fastapi, httpx, pytest" >/dev/null 2>&1; then
  echo "Dependencies are missing and could not be installed. Run: pip install -r requirements-dev.txt" >&2
  exit 1
fi

exec "$VENV/bin/python" -m pytest -q
