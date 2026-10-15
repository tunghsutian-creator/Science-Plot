#!/bin/bash
set -euo pipefail
project_dir="$(cd "$(dirname "$0")/.." && pwd)"
cd "$project_dir"
evidence_dir="${NATIVE_EVIDENCE_DIR:-$project_dir/../../.tmp_verify/pdf-desktop}"
mkdir -p "$evidence_dir/module-cache" "$evidence_dir/native-ui"
sources=()
for source in native/*.swift; do
  [[ "$source" == native/main.swift ]] || sources+=("$source")
done
xcrun swiftc -swift-version 6 -warnings-as-errors -parse-as-library \
  -target "$(uname -m)-apple-macosx13.0" -module-cache-path "$evidence_dir/module-cache" \
  "${sources[@]}" tests/native-ui.swift -framework AppKit -framework WebKit \
  -framework ImageIO -framework UniformTypeIdentifiers -o "$evidence_dir/native-ui-runner"
resources_path="${NATIVE_WEB_ROOT:-$project_dir/release/Figure Assembly.app/Contents/Resources/web}"
if [[ ! -f "$resources_path/index.html" ]]; then
  echo 'Build the standalone app first with npm run build:mac.' >&2
  exit 1
fi
"$evidence_dir/native-ui-runner" "$resources_path" "$evidence_dir/native-ui" | tee "$evidence_dir/native-ui.log"
