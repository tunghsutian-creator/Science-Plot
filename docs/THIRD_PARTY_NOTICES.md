# Third-Party Notices

SciPlot is distributed under GPL-2.0-or-later for the GPL upstream Studio
integration.

## Veusz

Veusz is copied under `third_party/veusz` from
https://github.com/veusz/veusz at commit
`264084b06eb306d860c7757c637f37b78bb2333f`.

Veusz is GPL-2.0-or-later. Its original `COPYING`, `AUTHORS`, documentation,
examples, tests, icons, and source layout are preserved in the vendored tree.

SciPlot uses Veusz as the production renderer and full advanced editor for
`sciplot studio`.

## Local Integration Policy

- Do not rewrite upstream source for SciPlot branding.
- Keep SciPlot adapter code outside upstream trees unless a patch is explicitly
  recorded.
- Keep generated project documents and launchers in SciPlot project packages so
  edited figures remain reopenable.
