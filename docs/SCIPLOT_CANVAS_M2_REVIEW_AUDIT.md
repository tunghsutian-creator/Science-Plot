# SciPlot Canvas M2 Review and Promotion Audit

Date: 2026-07-17

## Audit conclusion

The non-exported review and typed-promotion kernel is ready for controlled
daily use through `sciplot canvas`. Review work is now spatial, persistent,
reversible, and visibly separate from the exact-current publication document.

This is not approval to retire the Veusz frontend. Automated probes prove the
engineering contract, but they do not replace the remaining requirement for
at least ten real editing/review sessions with zero accepted-change loss or
the user-approved default `studio` cutover.

## Review contract

- Shapes: text, arrow, rectangle, ellipse, and freehand.
- Anchors: page pixels, normalized page, graph, data coordinates, and selected
  stable object.
- Storage: `.sciplot_canvas/review_annotations.json`, version 2.
- Publication isolation: review-only changes do not increment the document
  revision, mutate VSZ, or enter PDF/TIFF exports.
- Promotion: text, arrow, rectangle, and ellipse compile to native Veusz
  label, line, rect, and ellipse widgets.
- Honest limit: freehand stays review-only because the bounded native contract
  has no equivalent editable Veusz object.
- History: promotion, undo, and redo transition the Veusz document and review
  sidecar together.
- Authority: promoted objects become part of the exact-current VSZ and
  therefore appear in reopen, QA, PDF/TIFF, and delivery.

## Interaction surface

`Ctrl+Shift+R` opens the Review workspace. It exposes Select, Note, Arrow, Box,
Oval, and Pen tools; an anchor selector; a persistent mark list; text, color,
line-width, and font-size controls; and Apply, Revert, Promote, and Remove
actions.

Review marks are `QGraphicsScene` overlays above the embedded Veusz
`PlotWindow`. The overlay is display-only: it converts scene gestures into the
sidecar coordinate contract and never paints into the renderer document.

## Typed promotion boundary

Promotion is a closed `CanvasOperation.add_widget` transaction:

- only label, line, rect, and ellipse widget types are accepted;
- widget names and initial settings use bounded schemas;
- insertion index is limited to append or front;
- the controller resolves a stable page/graph target before mutation;
- Veusz applies one undoable operation;
- SciPlot records a recovery snapshot, revision, promoted stable object ID,
  render fingerprints, sidecar transition, and journal entry.

Page-level native annotations use insertion index `0`. Veusz draws page
children in reverse order, so this preserves page-coordinate semantics while
placing labels and arrows above the graph.

## Adversarial defects found and corrected

- Page labels and arrows were present in VSZ but invisible because the graph
  painted over later page children. Page promotion now inserts at index `0`.
- Raw PDF SHA-256 changed between visually identical exports because generated
  metadata changed. The isolation gate now compares rendered PDF page pixels
  while retaining byte equality for TIFF.
- Initial review defaults used application-scale `12 pt` text and `2 pt`
  lines, which were too dominant on `60x55 mm` figures. Promotion defaults are
  now `7 pt`, `1 pt`, with translucent shape fills.
- Page anchors initially stored zoomed scene pixels, so they stayed at a
  screen position instead of following page zoom. They now store page-local
  absolute coordinates and resolve through the current renderer scale; the
  lifecycle gate requires all five anchor spaces to move correctly on zoom.
- Data anchors initially considered only XY and box-plot objects. The same
  axis-resolved contract now supports image and contour objects for scalar
  fields.
- A promotion must update both native document history and sidecar state.
  Controller history side effects now restore the review mark on undo and
  re-promote it on redo.
- Same-type sibling insertion could previously transfer a structural-index ID
  from an existing label to a newly promoted label. Full-tree identity
  reconciliation now preserves exact paths first and uses structural position
  only as the rename fallback.
- Cancelling a staged-state-protected switch to Review could still arm a
  drawing tool. Workspace activation now reports success explicitly, and a
  cancelled switch leaves both the inspector and overlay in Select mode.

## Evidence

- Pure Canvas contract:
  `.tmp_verify/m2_review_contract_v3/` — `26/26`.
- Final focused review lifecycle:
  `.tmp_verify/m2_review_temp3_final/canvas_review_probe_cn836k6f/` —
  `20/20`, including all five zoom anchors and all 45 pre-existing TEMP3
  object IDs.
- Runtime smoke v11:
  `.tmp_verify/m2_review_release_smoke/runtime_smoke_jywdc_5g/` — `27/27`,
  including the pure contract `26/26`, native application `26/26`, and nested
  review lifecycle `20/20`.
- Final six-document review matrix:
  `.tmp_verify/m2_review_release_matrix/` — FTIR, rheology frequency sweep,
  tensile, impact, torque, and TEMP3 scalar field each pass `20/20`, for
  `120/120` aggregate checks.
- Final contextual-inspector matrix:
  `.tmp_verify/m2_review_inspector_release/canvas_inspector_matrix_0ncyz3_0/`
  — `8/8`, 87 objects, and all ten bounded object types.
- Every probe copies its input and verifies source immutability.
- Visual screenshots exist for review-only and promoted states in every
  lifecycle run.
- No source under `third_party/veusz` or `src/sciplot_core/_vendor` changed.
- Final wheel:
  `/private/tmp/sciplot-m2-review-wheel-20260717/sciplot_core-0.1.0-py3-none-any.whl`,
  SHA-256
  `c56c262dd0e26d915793e85e3d00d86c50ab974e80d6ddacda4d81ccc94b1cd6`.
  Its dependency-free Canvas contract import and dependency-backed Qt-free GUI
  boundary import load neither PyQt nor Veusz.

The five-family matrix is representative engineering evidence. Its acceptance
projects retain their existing evidence tiers; this audit does not relabel
fixtures as authorized real data and does not count automated runs as human
daily-use sessions.

## Remaining M2 gates

1. Complete at least ten real editing/review sessions across at least five task
   families with zero accepted-change loss.
2. Record any fallback to Advanced Editor with a concrete missing capability.
3. Review the evidence with the user.
4. Only then move the normal `studio` frontend to SciPlot Canvas and present
   Advanced Editor as explicit recovery.
