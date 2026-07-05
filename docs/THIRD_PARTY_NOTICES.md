# Third-Party Notices

SciPlot is distributed under GPL-2.0-or-later for the GPL upstream Studio
integration.

## Veusz

Veusz is copied under `third_party/veusz` from
https://github.com/veusz/veusz at commit
`264084b06eb306d860c7757c637f37b78bb2333f`.

Veusz is GPL-2.0-or-later. Its original `COPYING`, `AUTHORS`, documentation,
examples, tests, icons, and source layout are preserved in the vendored tree.

SciPlot uses Veusz as the embedded PyQt plotting-editor runtime for
`sciplot studio`.

## LabPlot

LabPlot is copied under `third_party/labplot_reference` from the GitHub mirror
https://github.com/KDE/labplot at commit
`bc8635032d8b0c71e5b8fabc38a84694129bb334`. The primary upstream repository is
https://invent.kde.org/education/labplot.

LabPlot is kept as a full source reference in the first slice. Its `LICENSES/`,
`AUTHORS`, source, build files, and documentation are preserved for later
feature-by-feature absorption.

## Local Integration Policy

- Do not rewrite upstream source for SciPlot branding during the first
  takeover slice.
- Keep SciPlot adapter code outside upstream trees unless a patch is explicitly
  recorded.
- Keep generated project documents and launchers in SciPlot project packages so
  edited figures remain reopenable.
