# Tavotto UI source attribution

SciPlot's review workspace and live native editor adapt a bounded set of UI
components and design tokens from [Tavotto](https://github.com/Tavotto/Tavotto). This is an independently
modified SciPlot interface, not an official Tavotto release or an endorsement.

- Upstream commit: `4cf5b8c658b06dbd6e1fc8a569fee85ef5d62186`.
- Original file: [`web/src/index.css`](https://github.com/Tavotto/Tavotto/blob/4cf5b8c658b06dbd6e1fc8a569fee85ef5d62186/web/src/index.css).
- Upstream authors: Tavotto project and contributors, as identified by the pinned
  repository. Existing upstream authorship and copyright claims are retained.
- Upstream source-file SHA-256: `a501e460633365eedd3ea93462540bb47f20d5bf6fc9e05c35484dd91247cffd`.
- Upstream license: **AGPL-3.0-only**. [LICENSE](LICENSE) is a byte-for-byte copy of
  the [pinned upstream license](https://github.com/Tavotto/Tavotto/blob/4cf5b8c658b06dbd6e1fc8a569fee85ef5d62186/LICENSE).
- License-file SHA-256: `0d96a4ff68ad6d4b6f1f30f713b18d5184912ba8dd389f86aa7710db079abcb0`.
- Modified by the SciPlot project on 2026-09-20. Local destination:
  `src/sciplot_core/task_review_assets/review.css`, the separately marked
  `Enhanced review workspace` section.

## Review-workspace token subset

| Upstream lines / tokens | SciPlot adaptation |
| --- | --- |
| 31–34: background, canvas, surface and subtle surface | Same color values, renamed to `--review-app`, `--review-canvas`, `--review-surface`, `--review-subtle` |
| 38: surface hover; 43: border | Same ink-alpha composition expressed as `rgba(27,27,24,.05)` and `.12`, without Tailwind `color-mix` dependencies |
| 57–58: field and field-hover | Same values with `--review-` names |
| 60, 62, 67: ink, secondary and tertiary text | Same values with `--review-` names |
| 73–74: accent and subtle accent; 94: selection | Same values with `--review-` names |
| 87–88: warning colors; 92–93: success colors | Same values with `--review-` names |
| 103, 105–106: 6 / 10 / 14 px radii | Control, panel and dialog radii |
| 112, 118: dialog and card shadows | Same shadow values for the matching SciPlot surfaces |
| 138–140: sans-serif system-font stack | Same font stack; no fonts are bundled or downloaded |

The review layout, selectors, gallery interactions, records and comparison
behavior are SciPlot-specific. This section describes its CSS subset only.

## Live-editor UI component subset

The live-editor source is in `web/editor`. The following files are directly
copied or excerpted under `web/editor/src/vendor/tavotto/`; each carries a
source/license header. All upstream paths below are relative to `web/src/` at
the pinned commit. Modifications were made by the SciPlot project on 2026-09-20.

| Upstream file and lines | Local vendor file | Modifications |
| --- | --- | --- |
| `components/ui/Input.tsx` 28–89, 431–497 | `Input.tsx` | Retain TextInput and ColorField; trim unused imports/components, point to local utilities, replace two translated labels with local Chinese strings |
| `components/ui/fieldBox.ts` 1–30 | `fieldBox.ts` | Full component constants; local utility import and attribution header |
| `components/ui/Badge.tsx` 1–40 | `Badge.tsx` | Full Badge component; local utility import and attribution header |
| `lib/utils.ts` 1–6 | `utils.ts` | Retain cn class-name utility and its imports |
| `components/ui/TreeRow.tsx` 15–18 | `tree.ts` | Retain TREE_INDENT and treeIndent only |
| `index.css` 30–175 | `tokens.css` | Retain selected Tailwind theme block, add closing brace and attribution header |

The original whole-file SHA-256 values are:

| Upstream file | SHA-256 |
| --- | --- |
| `components/ui/Input.tsx` | `b4b9a9cc8fcd4e467f5829302863f58bf31e450545afffa5ad8a09ea8852c157` |
| `components/ui/fieldBox.ts` | `b24ffb069ad1f8cbb3d5f895c0e0e4c1043af23cd5e931aee8c623c66cd1df27` |
| `components/ui/Badge.tsx` | `0b81db606c85f9e4587e9475f8899410c6f4c9822c6276bb5186a963c152dfa4` |
| `components/ui/TreeRow.tsx` | `cf87aadae660e8d79074d9b346ea7ba9cfc7ba6ea7eeb2f8c16bb7b06d8ea87e` |
| `lib/utils.ts` | `b0298e5702ef84266cbd6b77a85b14b7f4bb9bf470b3df095c95f6309cc88f19` |
| `index.css` | `a501e460633365eedd3ea93462540bb47f20d5bf6fc9e05c35484dd91247cffd` |

The session protocol, scheduling, native object selection and editing,
application composition, save/export integration and scientific checks are
SciPlot-specific. These features are not claimed to be copied Tavotto business
logic or to provide every upstream feature. No Tavotto renderer, Matplotlib
artist-editing engine, project model, script execution, persistence, export, AI
integration or telemetry code is included. Tavotto logos, icons, product-name
presentation and other brand assets are not incorporated. The upstream name is
used for source attribution only;
see the [pinned trademark policy](https://github.com/Tavotto/Tavotto/blob/4cf5b8c658b06dbd6e1fc8a569fee85ef5d62186/TRADEMARKS.md).

## License scope and distribution

The adapted Tavotto portion retains **AGPL-3.0-only**. The existing SciPlot and
Veusz portions retain their own notices and licenses. This addition does not
replace the repository's main `LICENSE`, relicense third-party files, or convert
AGPL-covered material into GPL-only material.

SciPlot's existing third-party notice identifies the Studio integration as
GPL-2.0-or-later. For a combined distribution, the intended compatibility path
uses the GPLv3 option available for those GPL-2.0-or-later portions together with
AGPLv3's combination provision, while preserving each portion's license. The
AGPL portion and applicable source-availability requirements remain in effect.
This records the basis for this limited adoption; it is not a project-wide legal
certification. See [AGPLv3 section 13](https://www.gnu.org/licenses/agpl-3.0.en.html#section13)
and the [GNU license compatibility FAQ](https://www.gnu.org/licenses/gpl-faq.en.html#AllCompatibility).

The complete AGPL text is also copied to
`src/sciplot_core/task_review_assets/tavotto-LICENSE.txt`, included by the existing
`task_review_assets/*` package-data rule. Generated review HTML embeds the
unminified interface CSS and JavaScript, upstream attribution and full license
text, so its local interface source and notices remain available offline. The
HTML is a read-only report, not the source of the scientific renderer. Network
redistribution must preserve the notices and provide the corresponding source
required for the actual distributed combination; an upstream link alone is not
a substitute for source for local modifications.

The live-editor build copies `web/editor/public/tavotto-LICENSE.txt` into
`src/sciplot_core/live_editor_assets/tavotto-LICENSE.txt` through Vite's public
asset handling, so a clean build retains the license text. The editable frontend
source and build configuration remain under `web/editor`; the copied-source
manifest is also summarized in `web/editor/THIRD_PARTY.md`. A distributed editor
must provide the corresponding source for its actual modified version and
applicable combination, including the required build material. A compiled bundle,
source map, license link or upstream link alone is not a blanket substitute for
that obligation.

## Updating this subset

Keep the source URL, pinned commit, imported ranges, modification description and
license copies synchronized when expanding or updating the subset. A visual
match is not evidence that additional code was copied; list newly incorporated
source explicitly rather than attributing all SciPlot code to Tavotto.
