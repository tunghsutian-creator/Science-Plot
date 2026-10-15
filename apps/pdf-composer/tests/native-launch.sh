#!/bin/bash
set -euo pipefail
project_dir="$(cd "$(dirname "$0")/.." && pwd)"
cd "$project_dir"
evidence_dir="${NATIVE_EVIDENCE_DIR:-$project_dir/../../.tmp_verify/pdf-desktop}"
mkdir -p "$evidence_dir/module-cache"
xcrun swiftc -swift-version 6 -warnings-as-errors -parse-as-library \
  -target "$(uname -m)-apple-macosx13.0" -module-cache-path "$evidence_dir/module-cache" \
  native/NativeTypes.swift tests/native-launch.swift -framework AppKit -o "$evidence_dir/native-launch"
"$evidence_dir/native-launch" "$project_dir/release/Figure Assembly.app" "$evidence_dir/native-launch-report.json" \
  | tee "$evidence_dir/native-launch.log"
