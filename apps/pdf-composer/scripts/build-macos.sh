#!/bin/bash
set -euo pipefail
project_dir="$(cd "$(dirname "$0")/.." && pwd)"
cd "$project_dir"
if [[ ! -f dist/index.html ]]; then
  echo 'Missing dist/index.html. Run npm run build first.' >&2
  exit 1
fi
if /usr/bin/grep -Eq 'type="module"|modulepreload|crossorigin' dist/index.html; then
  echo 'Web assets must be finalized as a bundled classic IIFE before packaging.' >&2
  exit 1
fi
app_path="$project_dir/release/Figure Assembly.app"
mkdir -p "$app_path/Contents/MacOS" "$app_path/Contents/Resources"
rm -rf "$app_path/Contents/Resources/web"
cp -R dist "$app_path/Contents/Resources/web"
cp native/Info.plist "$app_path/Contents/Info.plist"
cp ../../LICENSE "$app_path/Contents/Resources/LICENSE"
mkdir -p release/swift-module-cache
arch="$(uname -m)"
xcrun swiftc -swift-version 6 -warnings-as-errors -O -target "$arch-apple-macosx13.0" \
  -module-cache-path release/swift-module-cache native/*.swift \
  -framework AppKit -framework WebKit -framework ImageIO -framework UniformTypeIdentifiers \
  -o "$app_path/Contents/MacOS/FigureAssembly"
plutil -lint "$app_path/Contents/Info.plist"
echo "$app_path"
