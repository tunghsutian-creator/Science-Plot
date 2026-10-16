#!/bin/bash
set -euo pipefail
project_dir="$(cd "$(dirname "$0")/.." && pwd)"
source_app="${BROWSER_PREVIEW_APP:-$project_dir/release/preview/Figure Assembly Preview.app}"
install_dir="${BROWSER_INSTALL_DIR:-$HOME/Applications}"
desktop_dir="${BROWSER_DESKTOP_DIR:-$HOME/Desktop}"
if [[ ! -f "$source_app/Contents/MacOS/FigureAssemblyBrowser" ]]; then
  echo "Build Figure Assembly Preview.app before installing." >&2
  exit 1
fi
codesign --verify --deep --strict "$source_app"
python3 - "$source_app" <<'PY'
from pathlib import Path
import json, plistlib, sys
app = Path(sys.argv[1])
info = plistlib.loads((app / 'Contents/Info.plist').read_bytes())
manifest = json.loads((app / 'Contents/Resources/BrowserBuild.json').read_text())
identity = 'org.sciplot.figureassembly.browser.preview'
if info.get('CFBundleIdentifier') != identity or manifest.get('build', {}).get('applicationID') != identity:
    raise SystemExit('Refusing to install a non-preview application as Figure Assembly Preview.')
if info.get('CFBundleExecutable') != 'FigureAssemblyBrowser':
    raise SystemExit('Unexpected preview application executable.')
PY
mkdir -p "$install_dir" "$desktop_dir"
install_dir="$(cd "$install_dir" && pwd)"
desktop_dir="$(cd "$desktop_dir" && pwd)"
number=1
destination="$install_dir/Figure Assembly Preview.app"
while [[ -e "$destination" || -L "$destination" ]]; do
  number=$((number + 1))
  destination="$install_dir/Figure Assembly Preview ($number).app"
done
# mkdir reserves a new destination; ditto never merges into a pre-existing app.
mkdir "$destination"
ditto "$source_app" "$destination"
codesign --verify --deep --strict "$destination"
desktop_entry="$desktop_dir/Figure Assembly Preview.app"
number=1
while [[ -e "$desktop_entry" || -L "$desktop_entry" ]]; do
  number=$((number + 1))
  desktop_entry="$desktop_dir/Figure Assembly Preview ($number).app"
done
ln -s "$destination" "$desktop_entry"
printf 'Installed app: %s\nDesktop entry: %s\n' "$destination" "$desktop_entry"
