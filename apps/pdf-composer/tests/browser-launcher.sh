#!/bin/bash
set -euo pipefail
project_dir="$(cd "$(dirname "$0")/.." && pwd)"
app_path="${1:-$project_dir/release/Figure Assembly Browser.app}"
evidence_dir="${2:-$project_dir/../../.tmp_verify/browser-launcher-$(date -u +%Y%m%dT%H%M%SZ)}"
mkdir -p "$evidence_dir/module-cache"
xcrun swiftc -swift-version 6 -warnings-as-errors -parse-as-library \
  -target "$(uname -m)-apple-macosx13.0" -module-cache-path "$evidence_dir/module-cache" \
  "$project_dir/tests/browser-launcher.swift" -framework AppKit -framework CryptoKit \
  -o "$evidence_dir/browser-launcher-tests"
"$evidence_dir/browser-launcher-tests" "$app_path" "$evidence_dir" | tee "$evidence_dir/browser-launcher.log"
