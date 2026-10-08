# Scientific Figure Grammar v2

Design before implementation, 2026-10-08. This is a scoped contract; runtime and
native acceptance evidence will be recorded separately. Existing canonical
ManagedPlot authority, transactions, hashes and executor provenance are retained.

## Design decisions

Figure -> View -> Layer -> typed Mark is the canonical composition hierarchy.
Scales are independent scientific mappings with stable identity, dimension,
quantity, unit, domain, transform and direction. Axes are visual guides referencing
a scale; layers bind scales, never axes. Native widget paths are backend-private.

Initial compositions: single, horizontal/vertical concatenation and weighted grid.
Each View contains arbitrary supported layers. Explicit resolution groups name a
subset of view IDs, so A/B can share frequency X while C/D use independent scales.
Sharing requires declared equivalent scientific quantity, units, domain, direction
and transformation. Names are not evidence of scientific compatibility.

Initial typed marks: line, point, bar, errorbar, band, rule and fixed text. Geometry
parameters such as bar baseline/width and error bounds are explicit. Geometry
lowering is by mark, never by named scientific plot type. Image/area, general
faceting/repetition, polar/3D and arbitrary native widgets are not this slice.
Linear/log are initial native capabilities; unsupported transforms such as symlog
must fail capability negotiation before native compilation.

## Source and identity boundary

FigureSpec v2 has closed versioned schemas. Its scientific projection contains
scale identities/mappings, view/layer/mark identities, dataset/channel references,
semantic quantities and data-space annotation anchors. Presentation contains
layout, styles, guide text/order, z-order and non-data annotation placement.
The projection is stored within existing SciPlotDocument domains, not a parallel
document authority. Scientific datasets and TransformNode execution remain owned
by the existing immutable data DAG; layout never computes fitting/TTS statistics.

The public semantic create endpoint accepts a reusable figure template with
explicit original-source Binding; named scientific templates expand to the same
FigureSpec. Existing v1 templates/documents and IR remain readable without silent
rewriting or hash changes. New figures compile to resolved PlotIR schema_version=2.
Version-specific validation is explicit and unknown versions fail closed.

## Compiler and layout

A pure SemanticCompiler resolves bindings, typed channels, styles and guides.
Style precedence: documented grammar defaults -> project -> figure -> view ->
layer -> mark. Defaults are schema/compiler-owned and fully expanded before the
backend sees IR; no backend-specific secondary default policy is allowed.

LayoutSolver consumes physical mm constraints: figure width/fixed or automatic
height, weighted rows/columns, gaps, outer margins, panel minimum size, reserved
panel-label area and measured/conservative decoration extents. It produces cell
and plot rectangles and shared-axis decoration suppression. All IR physical
rectangles use mm with a top-left origin. The backend cannot choose panel sizes.

Legends are semantic guides built from layer membership, explicit ordering/labels,
visibility, columns, scope and location. Data, view and figure annotation spaces
are distinct. Data-space positions continue to use the same scale mapping when
the physical panel layout or domain changes.

## QA and capabilities

Hard QA rejects invalid/missing channels, empty visible geometry, illegal domains,
unit/quantity conflicts, nonpositive/overlapping/out-of-canvas plot rectangles,
out-of-bounds annotations/legends, and measured rendered text outside its allowed
canvas/view decoration area. Native rendered-text bounds must be measured before
clipping; absence of clipped text in PDF extraction is not proof of success.

Soft QA reports geometric text/data/guide collision heuristics, unusually large
whitespace and alignment concerns separately. A soft warning is not a hard
scientific failure; QA is deterministic and remains attached to export evidence.
Core preflight consumes a backend-neutral capability profile, then the backend
rechecks capabilities before writing. Unsupported input never becomes hidden
native-only state or a silent lower-fidelity fallback.

## Acceptance

A: real-domain dual-Y rheology (Gprime/Gdoubleprime and tan-delta, one frequency X).
B: weighted 2x2 Figure with A/B shared X, independent Y and unequal text lengths.
C: mechanical bar + errorbar + individual points through generic marks.
D: spectrum + peak rules + data-anchored text; changed range preserves anchors.
E: paper/presentation theme switch preserves scientific identity.
F: delete backend tree and IR caches; recreate canonical IDs, datasets/mappings,
resolved styles/layout and IR hash, audited native state and PDF/TIFF exports.

Examples use explicitly identified research-domain data and preserve its source
provenance; generated demonstration measurements must never be labeled real
experimental evidence. Actual exported files, QA records and limitations are
required before claiming this design implemented.

## Primary references consulted

- [Vega-Lite composition](https://vega.github.io/vega-lite/docs/composition.html)
  and [resolve](https://vega.github.io/vega-lite/docs/resolve.html): composition and
  separate resolution decisions; SciPlot additionally requires scientific meaning
  and unit compatibility instead of implicitly unioning unrelated domains.
- [ggplot2 components](https://ggplot2.tidyverse.org/articles/ggplot2.html): separates
  data, mapping, layers, scales, coordinates and theme; SciPlot retains externally
  owned scientific transformations instead of embedding statistical algorithms.
- [Plotly subplots](https://plotly.com/python/subplots/) and
  [multiple axes](https://plotly.com/python/multiple-axes/): trace composition and
  independently referenced axes; SciPlot chooses separate scale and guide IDs.
- [Origin template content](https://docs.originlab.com/origin-help/graph-template-elements/):
  reusable appearance and data relationships; SciPlot uses explicit bindings and
  provenance rather than guessed column matching.
- [Matplotlib constrained layout](https://matplotlib.org/stable/users/explain/axes/constrainedlayout_guide.html):
  aligned plot areas and decoration-aware sizing; SciPlot resolves physical layout
  before backend lowering and separately audits actual native text bounds.

## Implemented wire contracts and use

The existing `plot create --request REQUEST.json --json` / MCP `sciplot_plot_create`
accepts `template_definition.kind = sciplot_figure_template`, `schema_version = 2`,
`template_id`, and `figure_spec`. It reuses explicit `sciplot_binding` v1 and the
same transaction/revision/creation owner. Each bound `series_id` identifies a
Figure layer; its XY dataset, original column and unit must exactly match that
layer. Additional uncertainty channels are explicit dataset column IDs. No
scientific family name dispatches native drawing behavior.

Schema owners:

- `plot_grammar/schema.py:figure_spec_schema`: closed Figure/View/Scale/Axis,
  composition, Layer/Mark union, Guide and Annotation contracts.
- `plot_grammar/ir.py:ir_schema_v2`: resolved styles, axes/tick anchors, guide
  entries/symbols, data-bound marks and physical panel/annotation geometry.
- `plot_ir/figure_document.py:template_schema`: additive FigureTemplate request;
  `figure_spec` projections are losslessly sealed into existing document domains.
- `plot_engine/contracts.py:create_schema`: the single shared CLI/MCP request.
- `plot_engine/figure_updates.py:patch_capabilities`: exact value schemas by
  semantic target, returned as `figure_edit_contract` by `plot.describe`.

The complete minimal input is `tests/fixtures/figure_spec_v2.json`.
`tests/test_figure_document.py:request_for_figure` demonstrates an explicit original
CSV/row/unit Binding and the shared create request. Semantic patches use the same
`plot_id`, `base_revision`, `idempotency_key`, `intent_class` and `changes` contract.
Supported v2 properties are `theme`, `layout`, `style`, `scale.domain`,
`axis.ticks`, `axis.label`, and `annotation.text`; descriptors identify valid
stable target IDs and full replacement value schemas. Range changes require
scientific intent but reuse immutable datasets, without scientific execution.

Default precedence is `plot_grammar/styles.py:DEFAULTS` -> project -> figure ->
view -> layer -> mark. Partial overrides are resolved before IR. View-local guides
select only eligible local layers. Shared legend resolution requires one explicit
figure guide containing every eligible member of the declared view collection;
independent resolution rejects a guide combining those views. Equal labels never
cause semantic deduplication.

## Backend capability matrix

| Capability | Veusz managed v2 | Boundary |
| --- | --- | --- |
| line / point | Supported | Original paired arrays and missing breaks |
| bar | Supported | Explicit numeric X, baseline and width in data units |
| errorbar | Supported | Explicit absolute y_low/y_high; physical cap width |
| band | Supported | Ordered original rows, complete consecutive intervals; missing rows break polygons |
| rule / fixed text | Supported | Explicit layer scales and coordinates |
| independent/multiple Scale and Axis guides | Supported | Linear/log, ascending/descending; one visible guide per side |
| single/hconcat/vconcat/grid | Supported | Full rectangular grids, one view per cell, unequal weights |
| shared X/Y | Supported | Explicit compatible scale identity and view collection |
| local/figure legend | Supported | Membership/order/labels/columns; one visible figure-level guide |
| data/view/figure annotations | Supported | Distinct coordinate contracts; native text bounds checked |
| symlog, other transforms | Rejected | No numeric approximation or silent fallback |
| colorbar, image, area, polar/3D | Unsupported | Future typed capabilities required |
| facets/repeat, sparse grids, spanning cells | Unsupported | Explicit expansion/layout contract required |
| arbitrary native state | Rejected | Legacy compatibility retains opaque state separately |

`plot_backends/figure_plan.py:capability_profile` feeds semantic preflight;
`validate_figure_capabilities` checks resolved native precision/mark support before
any write. New backend mappings must remain private and deterministic. Legend point
symbols use the same Veusz marker glyph, color and physical size as plotted points.

## Version/migration guarantees and limitations

SciPlotDocument remains schema v1 with an explicitly versioned FigureSpec projection;
PlotIR is v2 for FigureTemplate v2, and stays v1 for existing Cartesian templates.
No automatic document rewrite, hash migration or LegacyPlot promotion occurs.
`ir_schema(version)`, `validate_ir` and `seal_ir` dispatch explicitly; unsupported
versions reject. Existing v1 exports and Legacy imports retain their old owners.

Native audit checks every numeric dataset, scale and lowered mark geometry, then
compares the complete generated/native state. Renderer timestamps and artifact
bytes are not scientific/IR identity. Font-file content is not pinned, so identical
pixels are established for the verified local renderer environment, not promised
across machines or font installations.

Layout estimates reserve conservative space; actual native text bounds are a
separate hard gate. A fixed width cannot accommodate arbitrarily large fonts or
labels: the program returns required/available dimensions, never silently clips,
shrinks text or expands width. Text/data collision heuristics use sampled points
and text rectangles; they do not establish continuous curve/fill clearance or
journal compliance. Explicit domains may crop some points with a warning, while
invalid/log-incompatible domains and wholly empty visible layers reject.

New grammar consumes numeric immutable datasets and existing TransformNode output.
Named scientific template catalogs, categorical/date scales, automatic scientific
peak assignment, general fitting and arbitrary text-column labels are not added.
