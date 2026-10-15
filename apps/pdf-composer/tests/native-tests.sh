#!/bin/bash
set -euo pipefail
project_dir="$(cd "$(dirname "$0")/.." && pwd)"
cd "$project_dir"
evidence_dir="${NATIVE_EVIDENCE_DIR:-$project_dir/../../.tmp_verify/pdf-desktop}"
mkdir -p "$evidence_dir/module-cache"
sources=()
for source in native/*.swift; do
  [[ "$source" == native/main.swift ]] || sources+=("$source")
done
xcrun swiftc -swift-version 6 -warnings-as-errors -parse-as-library \
  -target "$(uname -m)-apple-macosx13.0" -module-cache-path "$evidence_dir/module-cache" \
  "${sources[@]}" tests/native-tests.swift -framework AppKit -framework WebKit \
  -framework ImageIO -framework UniformTypeIdentifiers -o "$evidence_dir/native-tests"
"$evidence_dir/native-tests"
