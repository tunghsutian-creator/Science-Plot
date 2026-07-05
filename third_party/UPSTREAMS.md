# Upstream Source Manifest

SciPlot intentionally vendors GPL plotting-editor source so the desktop Studio
can become a real object editor instead of a thin export handoff.

## Veusz

- Path: `third_party/veusz`
- Upstream: https://github.com/veusz/veusz
- Commit copied: `264084b06eb306d860c7757c637f37b78bb2333f`
- License: GPL-2.0-or-later
- Role: first-class embedded plotting editor runtime for SciPlot Studio.
- Local policy: keep upstream source intact; put SciPlot integration in
  `src/sciplot_core/studio.py` and small launch/packaging adapters.

## LabPlot

- Path: `third_party/labplot_reference`
- Upstream mirror copied: https://github.com/KDE/labplot
- Primary upstream: https://invent.kde.org/education/labplot
- Commit copied: `bc8635032d8b0c71e5b8fabc38a84694129bb334`
- License: GPL-2.0-or-later plus compatible notices in `LICENSES/`
- Role: full source reference for feature mining, algorithms, import/export
  behavior, and scientific plotting UX.
- Local policy: not imported by the default Python runtime in the first Studio
  slice.
