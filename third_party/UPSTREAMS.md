# Upstream Source Manifest

SciPlot vendors the GPL Veusz plotting-editor source so the desktop Studio can
become a real object editor instead of a thin export handoff. Other plotting
systems are tracked as external references unless they become runtime code.

## Veusz

- Path: `third_party/veusz`
- Upstream: https://github.com/veusz/veusz
- Commit copied: `264084b06eb306d860c7757c637f37b78bb2333f`
- License: GPL-2.0-or-later
- Role: first-class embedded plotting editor runtime for SciPlot Studio.
- Local policy: keep upstream source intact; put SciPlot integration in
  `src/sciplot_core/studio.py` and small launch/packaging adapters.

## LabPlot

- Path: not vendored; see `docs/LABPLOT_ABSORPTION_MATRIX.md`
- Upstream mirror: https://github.com/KDE/labplot
- Primary upstream: https://invent.kde.org/education/labplot
- Reference commit reviewed: `bc8635032d8b0c71e5b8fabc38a84694129bb334`
- License: GPL-2.0-or-later plus compatible notices upstream.
- Role: external feature-mining reference for algorithms, import/export
  behavior, and scientific plotting UX.
- Local policy: do not vendor or import LabPlot unless a future milestone
  explicitly promotes a small audited piece into SciPlot.
