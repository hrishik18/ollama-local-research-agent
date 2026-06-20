#!/usr/bin/env bash
# Linux/macOS launcher for the traceability dashboard.
#
# Usage:
#   ./dashboard/run.sh                  # default 127.0.0.1:5050
#   ./dashboard/run.sh --port 8080
#   ./dashboard/run.sh --host 0.0.0.0   # expose on LAN
#
# Honours DASHBOARD_HOST / DASHBOARD_PORT env vars too.

set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$DIR"

# Use venv python if it exists, otherwise system python3
if [[ -x ".venv/bin/python" ]]; then
  PY=".venv/bin/python"
elif [[ -x "venv/bin/python" ]]; then
  PY="venv/bin/python"
else
  PY="$(command -v python3 || command -v python)"
fi

# Make sure flask is importable; if not, hint at installing
if ! "$PY" -c "import flask" >/dev/null 2>&1; then
  echo "Flask is not installed for $PY."
  echo "Install requirements first:"
  echo "  pip install -r requirements.txt"
  exit 1
fi

exec "$PY" dashboard/app.py "$@"
