# Tavotto UI attribution

This SciPlot editor adapts UI code from [Tavotto](https://github.com/Tavotto/Tavotto)
at commit `4cf5b8c658b06dbd6e1fc8a569fee85ef5d62186`. The Tavotto project and
contributors are the upstream authors. The incorporated portions retain
**AGPL-3.0-only**. SciPlot modified this subset on 2026-09-20; this is not an
official Tavotto release or an endorsement.

| Local path under `src/vendor/tavotto/` | Pinned upstream source under `web/src/` | Scope and changes |
| --- | --- | --- |
| `Input.tsx` | `components/ui/Input.tsx`, 28–89 and 431–497 | TextInput and ColorField; trim imports, local utility paths and two Chinese labels |
| `fieldBox.ts` | `components/ui/fieldBox.ts`, 1–30 | Complete constants, local utility path |
| `Badge.tsx` | `components/ui/Badge.tsx`, 1–40 | Complete component, local utility path |
| `utils.ts` | `lib/utils.ts`, 1–6 | cn helper and imports |
| `tree.ts` | `components/ui/TreeRow.tsx`, 15–18 | TREE_INDENT and treeIndent |
| `tokens.css` | `index.css`, 30–175 | Selected theme block plus a closing brace |

The full [license text](tavotto-LICENSE.txt) is copied unchanged by Vite to
the packaged live editor. The source distribution contains the inventory at
`third_party/tavotto-ui/README.md` and existing license boundaries at
`docs/THIRD_PARTY_NOTICES.md`. These are repository paths, not links to a promised
published release. The source URLs for the pinned upstream are obtained by
appending each listed upstream path to
`https://github.com/Tavotto/Tavotto/blob/4cf5b8c658b06dbd6e1fc8a569fee85ef5d62186/web/src/`.

SHA-256 hashes below identify the complete pinned upstream source files before
extraction and SciPlot-specific modifications:

| Upstream source under `web/src/` | SHA-256 |
| --- | --- |
| `components/ui/Input.tsx` | `b4b9a9cc8fcd4e467f5829302863f58bf31e450545afffa5ad8a09ea8852c157` |
| `components/ui/fieldBox.ts` | `b24ffb069ad1f8cbb3d5f895c0e0e4c1043af23cd5e931aee8c623c66cd1df27` |
| `components/ui/Badge.tsx` | `0b81db606c85f9e4587e9475f8899410c6f4c9822c6276bb5186a963c152dfa4` |
| `lib/utils.ts` | `b0298e5702ef84266cbd6b77a85b14b7f4bb9bf470b3df095c95f6309cc88f19` |
| `components/ui/TreeRow.tsx` | `cf87aadae660e8d79074d9b346ea7ba9cfc7ba6ea7eeb2f8c16bb7b06d8ea87e` |
| `index.css` | `a501e460633365eedd3ea93462540bb47f20d5bf6fc9e05c35484dd91247cffd` |

Native Veusz sessions, object/setting mappings, transaction history, preview,
save/export and source validation use SciPlot-specific integration. Tavotto's
Matplotlib engine, execution, export, AI/telemetry, project model and brand assets
are not included. Existing components retain their respective license notices;
this record does not relicense every project file. Distributors must preserve
notices and provide the corresponding source and build material for the actual
modified version as required by the applicable licenses; the upstream link alone
does not supply SciPlot's modifications.

Runtime dependency licenses and exact installed versions: [dependency-LICENSES.txt](dependency-LICENSES.txt).
