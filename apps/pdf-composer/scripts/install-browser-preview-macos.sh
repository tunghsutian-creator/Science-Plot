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
mkdir -p "$install_dir" "$desktop_dir"
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
