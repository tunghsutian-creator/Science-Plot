#!/bin/bash
set -euo pipefail
project_dir="$(cd "$(dirname "$0")/.." && pwd)"
cd "$project_dir"
output_dir="${BROWSER_LAUNCHER_OUTPUT_DIR:-$project_dir/release}"
web_head="${BROWSER_WEB_SOURCE_HEAD:-$(git rev-parse HEAD)}"
mkdir -p "$output_dir"
build_dir="$(mktemp -d "$output_dir/.browser-build.XXXXXX")"
app="$build_dir/Figure Assembly Browser.app"
mkdir -p "$app/Contents/MacOS" "$app/Contents/Resources/web" "$build_dir/module-cache"
cp browser-native/Info.plist "$app/Contents/Info.plist"
python3 - "$project_dir/dist" "$app/Contents/Resources" "$web_head" <<'PY'
from pathlib import Path
import hashlib,json,re,shutil,sys
dist,resources=map(Path,sys.argv[1:3]);head=sys.argv[3]
if not re.fullmatch(r'[0-9a-f]{40}',head): raise SystemExit('BROWSER_WEB_SOURCE_HEAD must be a full commit SHA')
html=(dist/'index.html').read_text()
assets=re.findall(r'(?:src|href)="\./(assets/[^\"]+)"',html)
if not assets: raise SystemExit('Build the public browser assets first')
names=['index.html',*assets,'THIRD_PARTY_NOTICES.txt']
names.extend(p.name for p in sorted(dist.glob('Figure-Assembly-Browser-*.zip')))
files=[]
for name in sorted(set(names)):
 if name.startswith('/') or '..' in Path(name).parts: raise SystemExit('Unsafe asset path')
 source=dist/name
 if not source.is_file() or source.is_symlink(): raise SystemExit('Missing/unsafe asset: '+name)
 data=source.read_bytes();target=resources/'web'/name;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(data)
 files.append({'path':name,'bytes':len(data),'sha256':hashlib.sha256(data).hexdigest()})
identity=''.join(item['path']+'\t'+item['sha256']+'\n' for item in files)
manifest={'build':{'applicationID':'org.sciplot.figureassembly.browser','sourceHead':head,'contentHash':hashlib.sha256(identity.encode()).hexdigest()},'files':files}
(resources/'BrowserBuild.json').write_text(json.dumps(manifest,indent=2)+'\n')
PY
xcrun swiftc -swift-version 6 -warnings-as-errors -O \
  -target "$(uname -m)-apple-macosx13.0" -module-cache-path "$build_dir/module-cache" \
  browser-native/LocalWebServer.swift browser-native/BrowserLauncher.swift browser-native/main.swift \
  -framework AppKit -framework Network -framework CryptoKit -o "$app/Contents/MacOS/FigureAssemblyBrowser"
plutil -lint "$app/Contents/Info.plist"
codesign --force --sign - "$app"
target="$output_dir/Figure Assembly Browser.app"
if [[ -e "$target" || -L "$target" ]]; then
  echo "Output exists; choose a new BROWSER_LAUNCHER_OUTPUT_DIR: $target" >&2
  exit 1
fi
mv "$app" "$target"
printf '%s\n' "$target"
