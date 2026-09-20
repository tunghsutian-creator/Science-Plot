# Third-Party Notices

SciPlot is distributed under GPL-2.0-or-later for the GPL upstream Studio
integration.

## Veusz

Veusz is copied under `third_party/veusz` from
https://github.com/veusz/veusz at commit
`264084b06eb306d860c7757c637f37b78bb2333f`.

Veusz is GPL-2.0-or-later. Its original `COPYING`, `AUTHORS`, icons, and runtime
source layout identify the vendored code. SciPlot's minimal repository
intentionally omits upstream development tests, examples, support files, and
manuals; the complete source at the pinned commit remains available upstream.

SciPlot uses Veusz as the production renderer and full advanced editor for
`sciplot studio`.

## Tavotto UI components and tokens

The experiment/comparison review interface and live native editor adapt selected
UI components and design-token values from
[Tavotto's `web/src/index.css`](https://github.com/Tavotto/Tavotto/blob/4cf5b8c658b06dbd6e1fc8a569fee85ef5d62186/web/src/index.css),
at commit `4cf5b8c658b06dbd6e1fc8a569fee85ef5d62186`.
The Tavotto project and its contributors are the upstream authors. This is a
modified SciPlot interface, not an official Tavotto product or an endorsement.

The incorporated Tavotto portion is **AGPL-3.0-only**. The complete upstream
license is retained at [`third_party/tavotto-ui/LICENSE`](../third_party/tavotto-ui/LICENSE)
and in the packaged `task_review_assets/tavotto-LICENSE.txt` used by the offline
review page's license notice. The [source inventory and modification record](../third_party/tavotto-ui/README.md)
identify exact upstream ranges, local destinations and hashes.

The review adaptation covers selected colors, radii, shadows and a system-font
stack. The React live editor additionally incorporates excerpts of TextInput,
ColorField, fieldBox, Badge, cn and treeIndent, with a larger theme-token block.
Its [local component manifest](../web/editor/THIRD_PARTY.md) identifies these
copies; Vite copies `web/editor/public/tavotto-LICENSE.txt` into the packaged
live-editor assets. SciPlot supplies its session protocol and native editing
integration. No Tavotto renderer,
document model, execution, export, telemetry, logos or icons are incorporated.
Veusz remains the production renderer and editable-document authority.

Existing files retain their respective licenses; importing this subset does not
relicense every file under one new label. For combined distribution, the intended
compatibility path uses the GPLv3 option in the existing GPL-2.0-or-later notices
and AGPLv3's combination provision, retaining the AGPL terms for the adapted
portion and the applicable source-availability obligations. The main `LICENSE`
is unchanged. This notice records the scoped integration, not a blanket legal
certification of every distribution.

## Local Integration Policy

- Do not rewrite upstream source for SciPlot branding.
- Keep SciPlot adapter code outside upstream trees unless a patch is explicitly
  recorded.
- Keep generated project documents and launchers in SciPlot project packages so
  edited figures remain reopenable.
- Upstream source: https://github.com/veusz/veusz
- Pinned commit: `264084b06eb306d860c7757c637f37b78bb2333f`
