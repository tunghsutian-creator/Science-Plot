#!/bin/bash
set -euo pipefail
project_dir="$(cd "$(dirname "$0")/.." && pwd)"
web_head="${BROWSER_WEB_SOURCE_HEAD:-$(git -C "$project_dir" rev-parse HEAD)}"
web_dist="${BROWSER_PREVIEW_WEB_DIST:-$project_dir/dist}"
output_dir="${BROWSER_PREVIEW_OUTPUT_DIR:-$project_dir/release/preview}"
mkdir -p "$output_dir"
output_dir="$(cd "$output_dir" && pwd)"
staging="$(mktemp -d "$output_dir/.preview-package.XXXXXX")"
trap 'rm -rf "$staging"' EXIT
mkdir -p "$staging/browser-native" "$staging/scripts"
# Reuse the verified launcher without changing the stable launcher's defaults.
# Every replacement is confined to a fresh, owned packaging directory.
python3 - "$project_dir" "$staging" "$web_dist" <<'PY'
from pathlib import Path
import sys
source, target, dist = map(Path, sys.argv[1:])
if not (dist / 'index.html').is_file():
    raise SystemExit('Build the preview web assets first')
replacements = {
    'Figure Assembly Browser': 'Figure Assembly Preview',
    'org.sciplot.figureassembly.browser': 'org.sciplot.figureassembly.browser.preview',
    '5178': '5210',
}
paths = [*sorted((source / 'browser-native').glob('*')), source / 'scripts/build-browser-macos.sh']
for path in paths:
    relative = path.relative_to(source)
    text = path.read_text()
    for before, after in replacements.items():
        text = text.replace(before, after)
    if relative.name == 'BrowserLauncher.swift':
        text = text.replace('button?.title = "FA"', 'button?.title = "FAP"')
    (target / relative).write_text(text)
(target / 'dist').symlink_to(dist.resolve(), target_is_directory=True)
PY
BROWSER_WEB_SOURCE_HEAD="$web_head" BROWSER_LAUNCHER_OUTPUT_DIR="$output_dir" \
  bash "$staging/scripts/build-browser-macos.sh"
