# SciPlot M4 Native Composition Audit

Status: automated engineering baseline passed, 2026-07-17. This audit does
not replace mixed-family real-session acceptance or the user's final M6
decision to retire the Veusz frontend.

## Outcome

SciPlot now has a native Qt Composition Board for spatial figure assembly.
Users drag standalone modules between exact publication slots while the same
window refreshes a native Veusz composite. The final figure is one editable
VSZ with a page, grid, graphs, datasets, text, and panel labels. Raster images
are non-authoritative interaction previews only.

The authority boundary is explicit:

- `composition.json` owns exact figure-level geometry and relationships;
- immutable source VSZ snapshots own standalone module inputs;
- typed operations own user and future AI layout intent;
- Veusz document operations own native compilation;
- the exact-current composite VSZ owns final visual state;
- deterministic QA and delivery code owns readiness claims.

## Persisted workspace

```text
composition_project/
  composition.json
  source_manifest.json
  operation_journal.jsonl
  previews/                         # non-authoritative PNG thumbnails
  sources/module_a/document.vsz     # immutable hash-locked snapshot
  variants/default/
    studio/document.vsz             # exact-current visual authority
    compile_manifest.json
    archive/                         # byte-identical prior composites
    exports/
    delivery/
```

The closed schema rejects unknown keys, unsafe paths, invalid hashes,
duplicate identities, geometry drift, incomplete compiled authority, and
altered renderer or authority policy. Supported exact layouts are:

- `single_180`: `1.5 + 180 + 1.5`;
- `double_equal_90`: `90 + 3 + 90`;
- `double_120_60`: `120 + 3 + 60`;
- `double_60_120`: `60 + 3 + 120`;
- `triple_equal_60`: `60 + 1.5 + 60 + 1.5 + 60`.

Extra modules may remain in the module tray without entering a compiled
layout.

## Typed operation gateway

User drag/drop and future AI suggestions share these bounded operations:

- `composition_place_module`;
- `composition_reorder_modules`;
- `composition_set_layout`;
- `composition_set_canvas_height`;
- `composition_set_legend_policy`.

Each operation carries a base revision and expected prior value. Preview is
zero-write. Apply is atomic, snapshots the prior model, journals a receipt,
and increments one revision. Undo and redo use reciprocal typed operations;
they do not patch JSON arbitrarily.

Variants are explicit project lifecycle objects. Every variant owns an
independent model revision, native VSZ, archive, exports, and delivery. A
variant change does not mutate another variant or a source snapshot.

## Native compiler

The compiler verifies source hashes, selects one explicit or unambiguous graph,
materializes namespaced datasets, clones graphs through Veusz operations,
creates an exact 183 mm page and grid, and applies exact physical slots. It
aligns plot frames, Arial 7 pt typography, axis/tick strokes, series strokes,
and bold 8 pt panel labels. It also records shared-axis and visible-legend
eligibility.

The saved document is reopened, painted, and audited. Compilation rejects
ambiguous graphs, unresolved datasets, nonphysical margins, insufficient plot
area, incomplete layouts, and edited authority unless regeneration is
explicit. Unchanged fingerprints are idempotent; every real regeneration
archives the prior VSZ byte-for-byte.

## Composition Board

The left `QGraphicsView` provides millimetre rulers, publication paper, slot
outlines, draggable source cards, panel badges, and a module tray. Dropping on
an occupied slot swaps modules. Arrow keys move the selected module between
adjacent slots; Delete or Backspace returns it to the tray.

The right side embeds a resize-aware Veusz `PlotWindow` without constructing
Veusz `MainWindow`. Layout, exact page height, legend policy, variants,
duplicate variant, undo, redo, rebuild, exact-current editing, and
`Export + QA` remain in the SciPlot shell.

`Edit Composite` opens the same VSZ in SciPlot Canvas. If a user manually
saves it, later layout operations detect the hash divergence and stop. The
user must explicitly choose archival regeneration. Export does not regenerate;
it uses the exact current document.

## QA and delivery

Composition delivery requires PDF and 300 dpi TIFF together. It verifies:

- immutable source hashes;
- one page, one grid, and one native graph per occupied slot;
- absence of raster panel composition;
- page and slot geometry within 0.02 mm native tolerance;
- panel-label, typography, axis/tick, and series-stroke alignment;
- shared-legend resolution as `passed` or honest `not_applicable`;
- PDF size within 0.25 mm;
- TIFF size within 0.35 mm and recorded 300 dpi;
- PDF/TIFF physical pairing within 0.35 mm;
- text preservation and artifact QA;
- exact-current VSZ hash parity in delivery;
- byte-identical source and metadata copies.

Claims stay separate: native lifecycle, exact-current artifact QA, and broader
journal compliance are distinct fields. The last remains false unless proven
elsewhere.

## Automated evidence

Run:

```bash
skill/scripts/sciplot composition-probe SOURCE.vsz \
  --out .tmp_verify/composition_probe --json
```

The current probe passes `11/11` gates:

1. five exact layout contracts and schema round-trips;
2. physical-contract tamper rejection;
3. typed zero-write preview;
4. native compilation of every layout;
5. real Qt mouse drag, typed receipt, and live preview;
6. typed undo/redo;
7. manual-edit silent-overwrite rejection;
8. explicit byte-identical archive and regeneration;
9. independent variants;
10. exact-current PDF/TIFF QA and delivery;
11. original and snapshotted source VSZ immutability.

Runtime smoke version 17 passes `33/33`, including this probe as its native
composition gate.

## Remaining before frontend retirement

M4's automated engineering contract is implemented. The broader M6 cutover
still requires repeated sessions across genuinely different figure families,
owner evaluation of drag ergonomics and correction speed, evidence that common
assembly no longer needs Veusz `MainWindow`, zero lost accepted edits across
the planned daily sessions, and explicit user approval to retire the Veusz
frontend from normal use.
