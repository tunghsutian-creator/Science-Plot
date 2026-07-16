# SciPlot Canvas M2 Contextual Editing Audit

Date: 2026-07-17

Update: the review items that were open when this editing-kernel audit was
written are now implemented and verified. See
`docs/SCIPLOT_CANVAS_M2_REVIEW_AUDIT.md`. The real-session and default
`studio` cutover gates remain open.

## Audit conclusion

The bounded contextual editing kernel is ready for controlled daily use through
the experimental `sciplot canvas` route. It no longer depends on Veusz
MainWindow for the covered object edits, point inspection, label movement,
save/reopen, recovery, structural QA, or exact-current export.

This is not approval to retire the Veusz frontend. The review layer and typed
promotion now exist, but M2 still requires at least ten real editing/review
sessions with zero accepted-change loss and default `studio` migration.

## Product boundary

SciPlot owns the normal editing experience. Veusz remains the in-process
document and rendering kernel:

- SciPlot presents stable scientific objects and bounded fields;
- both user actions and future AI actions use typed Canvas operations;
- Veusz `Document` and `PlotWindow` remain the exact-current visual engine;
- arbitrary Veusz properties, raw VSZ text editing, and dataset remapping are
  not exposed through the visual inspector;
- datasets remain read-only in the visual inspector. Validated remapping now
  occurs through a separately confirmed `DataMappingProposal` transaction,
  never through arbitrary inspector edits.

## Bounded object matrix

| Object | Primary controls |
| --- | --- |
| page | background and publication-frame authority |
| graph | margins, aspect, background, and border |
| axis | label, range, log state, placement, ticks, and typography |
| XY series | legend name, line, markers, visibility, and read-only datasets |
| box plot | grouping, geometry, appearance, and read-only datasets |
| legend | placement, ordering behavior, typography, fill, and border |
| image | range, scaling, colormap, transparency, and read-only field data |
| contour | levels, line/label appearance, and read-only field data |
| colorbar | range linkage, geometry, typography, fill, and border |
| native label | text, position, alignment, typography, and direct drag |

Every editor is selected from a closed set: boolean, choice, color, dataset,
distance, float list, integer, number, number-or-auto, read-only, scalar list,
or text.

## Interaction contract

1. Plot clicks resolve to the nearest supported scientific ancestor instead of
   exposing arbitrary renderer auxiliaries.
2. Selection, breadcrumb, point details, and the selection boundary update as
   one state.
3. Safe boolean and closed-choice edits apply immediately through the typed
   gateway.
4. Other edits stage in the inspector and become document operations only on
   Apply.
5. Object/page navigation, Save, Export + QA, and close cannot silently discard
   staged fields.
6. XY point picks persist in `CanvasSession` and redraw their marker after
   zoom, page, and reopen changes.
7. A native label drag becomes one `user_direct_manipulation` batch, one
   revision increment, and one operation-journal entry.
8. Structural QA runs after the editing debounce. Artifact QA remains an
   explicit exact-current Export + QA boundary.

## Adversarial defects found and corrected

- Empty visible text was initially rejected even though blank labels are valid
  Veusz state. Text coercion now permits empty strings while colors and
  distances remain non-empty.
- A bare `P` point-picker shortcut could fire while typing. Point pick now uses
  `Ctrl+Shift+P`.
- Transparent figure surfaces could visually inherit dark application chrome.
  The Canvas now has a display-only white paper layer that does not mutate VSZ
  or export appearance.
- High-precision label coordinates were rounded by `QDoubleSpinBox` and then
  falsely reported as user-staged changes. Each editor now records its actual
  representable UI value as the local baseline, preserving the exact document
  value until the user makes a real edit.
- The first staged-state implementation could lose an uncommitted field during
  navigation. Navigation, save, export, and close now require an explicit
  apply/revert/cancel decision.
- Theme screenshots alone could not prove that application chrome left the
  scientific figure untouched. The application probe now compares fixed-100%
  Veusz pixmap fingerprints under light, dark, increased-contrast, and restored
  themes.

## Evidence

- Final full runtime gate:
  `.tmp_verify/m2_editing_final_smoke/runtime_smoke_zru7dikd/` — `26/26`,
  including the pure Canvas contract `21/21` and native application `26/26`.
- Latest real rheology native application probe:
  `.tmp_verify/m2_theme_invariance_v3/canvas_app_probe_z2gemb71/` — `26/26`.
- Six-document contextual matrix:
  `.tmp_verify/m2_inspector_matrix_final_v2/canvas_inspector_matrix_j4bpc784/`
  — `8/8`, 87 objects, all ten bounded object types.
- TEMP3 native label drag:
  revision `0 -> 1`, changed render and coordinates, zero staged fields after
  drag, and exactly one `user_direct_manipulation` journal entry.
- Representative sources:
  FTIR, rheology, tensile, impact, scalar field, and TEMP3 four-panel VSZ.
  Every matrix run operates on a copy and preserves the source hash.

## Visual review

- The figure remains the dominant surface.
- The inspector hierarchy is clear in light, dark, and increased-contrast
  palettes.
- Scientific paper stays white while the surrounding canvas well follows the
  application palette.
- Dataset authority is visually distinct and read-only.
- Apply/Revert and structural-QA state remain visible without overwhelming the
  figure.
- The current inspector is intentionally dense for power users; daily-session
  evidence should determine whether presets, search, or section collapsing are
  needed before the default `studio` migration.

## Remaining M2 gates

1. Complete at least ten real editing/review sessions across five task
   families with zero accepted-change loss.
2. Move `studio` to SciPlot Canvas only after those gates pass; keep Advanced
   Editor as explicit recovery until the user approves retirement.
