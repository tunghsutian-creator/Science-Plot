# Local panel assembly workbench

Approved scope: select existing figures across projects, add images/diagrams,
arrange whole panels in a physical grid, and export a reproducible figure.
The base is `41f3f88f94f2a76f0ce3d74eb9a3f40f19e4f36b`.
Its original Mac full passed 4,598 tests; its Ubuntu performance font gate and
incomplete access capture remain separate open issues.

## Owners and authority

`panel_assembly/model.py` and `history.py` own a closed versioned layout document,
local operations and undo/redo. All save callers delegate to `storage.py` for
revision checks and publication under one kernel-held directory-inode lease.
They call the existing `plot_layout` physical solver. Spans and empty cells are
an explicit additive capability; existing figure contracts retain their defaults.
The layout stores source references/bindings, never another copy of plot science.

The lease closes on success, exception or process death. Stage creation, actual
JSON writes, publication and cleanup use held directory descriptors; exchanging
the parent pathname refuses publication and cannot write staged layout bytes to
the replacement directory. Layouts in one directory intentionally serialize.
A persistent versioned `.assembly-lock` fence excludes old O_EXCL writers; it
does not own the lease and is not deleted on PID/age guesses. Unknown historical
markers remain refused with explicit Save As available. This replaces the old
stale-lock lifecycle, while retaining previous-file and revision-conflict guards.

`panel_assembly/sources.py`, `native.py` and `export.py` own current source
capture, native physical reflow and mixed vector/raster delivery. Legacy panels
retain exact saved VSZ authority. Managed panels retain semantic document,
source and transform authority. Export refuses stale bindings and unsupported
reflow instead of stretching a scientific PDF. Cropping belongs to image panels
and never rewrites original image bytes. Scientific text remains native text at
its prescribed point size; the composite places native PDFs at physical 1:1.
Original and reflowed editable native sources accompany the editable layout.

`panel_assembly/desktop*.py` owns the local Qt selection/layout/export surface.
It uses the same model/operations and export owner as the compact CLI intent.
Dragging or spacing invokes no model service. No statistical toolkit, template
system, arbitrary SVG-element editor or second plotting backend is introduced.

## Shared Python port

All payloads are JSON-compatible dictionaries; functions raise a bounded
`AssemblyError` with a `code` attribute for invalid or stale state.

- `model.new_document(*, rows=2, columns=2, width_mm=180, height_mm=140)`
- `model.validate_document(document)` returns a validated deep copy.
- `model.resolve_document(document)` returns physical `width_mm`, `height_mm`
  and `panels`, each with `id`, `cell_mm`, `content_mm`, `label`, `label_mm`.
- `model.apply_operations(document, operations)` validates the entire batch
  before returning a new revision. Operations are closed `op` records:
  `add_panel` (`panel`), `remove_panel` (`id`), `move_panel`
  (`id`, `row`, `column`, optional `swap`), `set_span`
  (`id`, `row_span`, `column_span`), `set_grid` (`rows`, `columns`),
  `set_spacing` (`gap_x_mm`, `gap_y_mm`), `set_page`
  (`width_mm`, `height_mm`), `set_label` (`id`, `label`, null means automatic),
  `set_crop` (`id`, `crop`, normalized `[left,top,right,bottom]`),
  `replace_panel` (`id`, `source`). A panel has stable `id`, `source`,
  zero-based `row`/`column`, positive `row_span`/`column_span`, `label`
  (null for automatic) and `crop` (null or normalized image rectangle).
- A document has `kind="sciplot_panel_assembly"`, `version=1`, `revision`,
  `layout` (rows, columns, width_mm, height_mm, gap_x_mm, gap_y_mm), `panels`.
  Automatic labels follow row/column reading order. Custom labels retain case.
- `history.AssemblyHistory(document)` exposes `.document`, `.apply(operations)`,
  `.undo()`, `.redo()`, `.can_undo` and `.can_redo`.
- `model.load_document(path)` / `save_document(document, path,
  expected_revision=None)` preserve an existing file on validation/write conflict.
- `sources.capture_source(reference)` returns a frozen bound source, and
  `assert_source_current(source)` refuses source/document/version drift.
  References: `{"kind":"project","project":...,"figure_id":...}`,
  `{"kind":"managed","project":...,"plot_id":...}`,
  `{"kind":"image","path":...}`. The source owner supplies `binding`.
- `export.export_document(document, out, *, dpi=300)` returns paths/status and
  exact scientific/currentness/physical-size evidence. Output destination is
  new; export failure cannot replace an existing user package.
- `desktop.open_workbench(layout_path=None)` runs the native local window.

Native output and actual target-size QA decide support. A placement preview or
zero observed calls does not establish font portability, journal acceptance,
private-input completeness or external-client token/fee savings.

## Reference boundary

Interaction research uses polish-sci-figures at
`bc777f283b2e32d678fc93976ddf901fdf74383a`, especially panel selection, grid
movement and saved layouts. Its roughly 636 KB studio is not transplanted.
Any reused code must retain the upstream MIT and applicable third-party notices;
an independently implemented Qt surface will record conceptual attribution.

## Implementation and limits

`compose open [LAYOUT]` is the Qt entry. `compose capabilities/new/inspect/apply/
export` and the two MCP tools share `service.py`; complete layout batches validate
before save and bind the expected revision. Local layout changes do no native
rendering or AI work. Native previews are asynchronous and read-only; a bounded
cache uses frozen source versions and is invalidated by explicit replacement.

Default gaps are the existing composition contract's 6 mm. Outer letters are
7 pt bold, measured in the reserved band, with an explicit PDF Base14 Helvetica
Bold fallback. Custom letters are printable ASCII, maximum 16 characters; null
means automatic and empty hides the letter. Native scientific labels retain
their original font/text contract. Native PDF canvas rounding may underfill its
allocated box by less than one point; the manifest records actual mm and scale
1.0. No scientific page or glyph is rescaled to fill that rounding remainder.

Legacy layout-relative typography is outside the reflow contract: native settings
that would change prescribed physical font or stroke sizes on canvas resize
are rejected rather than rewritten.

Versioned source references need original roots for later layout re-export.
Copied original/reflowed native files and imports remain manually editable when
relocated. File leases and session-bound original bytes refuse stale writers;
there is no kernel CAS guarantee against an external editor writing after the
last source check. Runtime, scientific QA, cross-machine fonts, human usability,
journal acceptance and external-client cost remain independent claims.

Conceptual interaction attribution: polish-sci-figures, Copyright (c) 2026
Wenting Zhou, pinned commit above, MIT notice preserved in
[POLISH_SCI_FIGURES_MIT.txt](licenses/POLISH_SCI_FIGURES_MIT.txt). No upstream
studio code or its statistical/template toolkit was transplanted.
