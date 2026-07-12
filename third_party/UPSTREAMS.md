# Upstream Source Manifest

SciPlot vendors the GPL Veusz plotting-editor source as its production renderer
and advanced editor.

## Veusz

- Path: `third_party/veusz`
- Upstream: https://github.com/veusz/veusz
- Commit copied: `264084b06eb306d860c7757c637f37b78bb2333f`
- License: GPL-2.0-or-later
- Role: production renderer and full advanced editor for SciPlot Studio.
- Local policy: keep upstream source intact; put SciPlot integration in
  `src/sciplot_core/studio.py` and small launch/packaging adapters.
