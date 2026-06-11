#!/usr/bin/env bash
set -euo pipefail

REPO="$(cd "$(dirname "$0")" && pwd)"
PYTHON="$REPO/.venv/bin/python"

if [[ ! -x "$PYTHON" ]]; then
  PYTHON="python3"
fi

cd "$REPO"
echo "Starting SciPlot Web App..."
echo "Open data in the browser window, then close this Terminal window to stop SciPlot."
exec "$PYTHON" -m sciplot_core.cli app --out outputs/intake_projects
