# SciPlot Architecture

Status: current local developer reference.

This file defines module ownership and dependency boundaries only. `README.md`
owns product behavior, `skill/SKILL.md` owns agent command routing, and
`DEVELOPMENT_ROADMAP.md` owns active priorities. `DEVELOPMENT_LOG.md` and Git
hold history; historical implementation narratives are not architecture.

## Authority chain

```text
raw files + hashes
  -> confirmed scientific mapping
  -> prepared data + transform ledger
  -> exact-current studio/document.vsz
  -> Veusz PDF/TIFF export
  -> artifact QA
  -> visible SOURCE_SciPlot/ or --out handoff
  -> sibling hidden .sciplot/ runtime evidence
```

- raw files are data truth;
- the confirmed study/request model is semantic truth;
- the current saved VSZ is visual truth;
- versioned policy/profile data defines target constraints;
- QA reports only the checks it actually implements.

Lifecycle success, exact-current artifact QA, provenance completeness, human
daily-use validation, and journal-specific compliance are separate claims.

## Frontend topology

Veusz `MainWindow` is the only daily drawing frontend. Veusz owns the object
tree, property editor, Datasets, canvas, menus, shortcuts, Save, and Undo/Redo.

`src/sciplot_gui/` is an integration package, not a separate Qt application.
It attaches Project and optional selected-object AI docks to the same live
Veusz `Document`. SciPlot has no standalone Canvas, Composition Board, second
document model, or renderer fallback.

The browser `app` is an optional confirmation surface. It may collect the
initial source, grouping, naming, order, size, and export choices and show
rendered results read-only. It must not own post-render style, axis, legend, or
series editing; those operations belong to Veusz. The adapter is loopback-only,
accepts same-origin JSON requests, and may read local source paths only from the
active CLI-created session or the configured SciPlot output root.

## Command topology

| Command | Architectural role |
| --- | --- |
| `studio PATH` | Primary interactive lifecycle; prepares and opens native Veusz. |
| `studio PATH --export ... --json` | Headless mode of the same lifecycle. |
| `studio FIGURE.vsz` | Opens an existing visual authority in Veusz. |
| `app` | Optional first-time confirmation and read-only result review. |
| `autoplot` | Primary fully automated raw-path project/QA/delivery orchestration over internal one-step/`run_request`; no separate renderer. |
| `run` | Replays a confirmed request. |
| `curate torque` | Specialized scientific selection and Studio-project preparation; no final export/delivery authority. |
| `readiness`, `cleanup`, `mapping` | Maintenance/evidence contracts; no plotting lifecycle. |
| `publication` | Profile and layout metadata inspection only; no editor, assembler, or renderer. |
| `render`, `recipe` | Low-level development and testing primitives. |
| `one-step` | Internal manifest/readiness contract, not a user entrypoint. |

Retired `quick`, `prepare`, `intake`, and `workbench` names are not CLI
commands. Explicit legacy-launcher detection may remain so old generated
artifacts fail with a migration instruction instead of changing meaning.
`batch` is a help-hidden regression runner over `run_request`; `smoke` and
`acceptance` are validation/evidence commands. None is a user automation route.
`acceptance visual-review` is the sole recorder for the explicit uncalibrated
contact-sheet preview decision; it does not render or edit a figure and does
not prove final-physical-size readability. PDF size and TIFF DPI remain
machine checks; calibrated-display or print evidence is separate.
Ready-rule lifecycle acceptance exercises every template declared by a rule's
presentation contract, not only its default. The rule row passes only when all
declared alternatives complete native Studio prepare/reopen, exact-current
export, QA, delivery, and provenance checks.

## Repository map

```text
research-plots/
  README.md                    product and user workflow
  DEVELOPMENT_ROADMAP.md       active product/maintenance priorities
  skill/
    SKILL.md                   agent operating contract
    scripts/sciplot            source-checkout CLI wrapper
  src/
    sciplot_core/
      materials_rules.py       experiment families, axes, aliases, units
      semantic.py              recognition and deterministic preparation
      performance_comparison.py material-performance table/normalization contract
      performance_veusz.py     native scatter/radar Veusz object contract
      policy.py                global plotting and delivery defaults
      style_contract.py        template/style consistency audit
      request_contract.py      renderer-independent request validation
      studio.py                VSZ lifecycle and exact-current export
      workflow.py              confirmed-request orchestration and repair loop
      autoplot.py              automated project/QA/delivery summary adapter
      one_step.py              internal readiness/manifest model
      publish_state.py         shared fail-closed final publication gates
      managed_output.py        shared generator-owned output rollback
      intake.py                headless project preparation/domain logic
      intake_server.py         thin browser HTTP adapter
      qa.py                    artifact/publication QA
      output_contract.py       visible handoff and hidden workspace paths
      delivery.py              minimal handoff package
      smoke.py                 synthetic runtime change gate
      _vendor/                 migrated compatibility black box
    sciplot_gui/
      studio_project.py        Veusz Project dock bridge
      studio_project_status.py pure result/audit state logic
      studio_assistant.py      selected-object AI dock bridge
    sciplot_recipes/           stable experiment-family recipe facade
  third_party/veusz/           pinned upstream renderer/editor
```

Generated projects, acceptance runs, caches, authorized local data, and
development logs are local workspace material, not package source.

## Ownership rules

| Concern | Owner | Boundary |
| --- | --- | --- |
| Scientific recognition, units, metrics | `materials_rules.py`, `semantic.py` | Deterministic and fixture-backed. |
| Material-performance values and derived geometry | `performance_comparison.py` | Validate the tidy table, declared radar bounds, and sample envelope; never infer or average missing scientific values. |
| Native performance document objects | `performance_veusz.py` | Own editable scatter/radar polygons, lines, markers, labels, and the reserved reference panel; reuse global style policy. |
| Global visual contract | `policy.py`, vendored `plot_contract.json`, `style_contract.py` | One source for hard style; fail on drift. |
| Request/template validation | `request_contract.py` | Reject unsupported template or option before rendering. |
| VSZ lifecycle | `studio.py`, Veusz runtime adapters | Preserve, reopen, audit, and export the current document. |
| Project state | `studio_project_status.py` | Pure evidence-to-state logic; UI only renders it. |
| Optional selected-object AI | setting catalogue, assistant operations/provider, GUI bridge | Current object and typed settings only. |
| Blocked data/rule repair | assisted-cleanup and Codex handoff modules | Out-of-band maintenance; no user-visible frontend mode. |
| QA and delivery | `qa.py`, `delivery.py`, evidence modules | Inspect artifacts without changing scientific content. |
| Runtime change gate | `smoke.py` | Synthetic lifecycle coverage, never real-data evidence. |
| Upstream Veusz | `third_party/veusz/` | Preserve upstream identity; integration remains outside. |
| Migrated core | `_vendor/` | Black box unless a public adapter cannot express the fix. |

## Template and style boundary

The production document builder implements exactly `curve`, `point_line`,
`stacked_curve`, `bar`, `box`, `box_strip`, `heatmap`, `scatter`, and
`polar_curve`. The `bar` template
uses mean ± SD error bars for categorical replicate groups and a separate
long-form `Sample`/`Component`/value contract for additive stacked composition.
The latter never reclassifies components as replicates: it binds sample roots
to the control-first ordinary categorical palette and component order to
opaque same-hue lightness. Its legend is a stack-ordered segmented swatch
covering every sample colour, not a single-sample native key.
Vendored reference templates are not automatically production features;
unsupported requests fail closed.

`scatter` and `polar_curve` share the explicit
`performance_comparison` material-metric table contract. The former creates
data-bound material markers plus a native editable observed-sample envelope;
the latter uses declared bounded directional normalization, filled polygons
only for complete own-sample records, and marker-only literature references.
Both reserve a 60 x 55 mm plot module and may use one or two 60 x 55 mm
reference/index columns, producing a 120 x 55 or 180 x 55 mm page. This is
template-owned geometry, not an outside legend and not a second renderer.
The index has grouped headings but no redundant overall title; each column
computes its own deterministic row step. Optional `LegendLabel`,
`LegendGroup`, `LegendIdentity`, `LegendColumn`, and `LegendItemsPerRow` fields
separate internal observation identity from reader-facing material identity
and allow one or two entries in each group row. Repeated
observations with one `LegendIdentity` share a marker and one XY series, while
different identities remain globally unique through the sixteen-symbol native
Veusz marker inventory. Scatter observations sharing one source density use a
source-hash-bound symmetric horizontal offset. Optional `ScatterMin` and
`ScatterMax` declare one-sided or two-sided visible bounds without permitting
data clipping. Optional `EnvelopeInclude` selects which sample observations
participate in each `Group` envelope without removing those observations from
the scatter or legend. Sample envelopes use a deterministic irregular smoothed
enclosure with no visible stroke; the source coordinates remain unchanged in
the delivered table. The rule remains pending
automatic promotion while its
only source-controlled evidence is an
`instrument_shaped_fixture`; an explicit Studio request is still the supported
development/user-review route.

### Grouped categorical bar fill geometry

An unambiguous long-form `Sample`/`Condition`/value table uses the grouped
mean ± SD presentation. Sample order owns the control-first categorical colour
roots. Condition order owns opaque same-hue tones: the first condition is the
lighter tone and the second is the darker root colour. The condition legend
uses one segmented swatch per condition so all sample colours remain visible.
No alpha transparency is used for the bar fill.

Visible grouped-bar fills do not use native Veusz `barfill` or `groupfill`.
Those settings combine dataset-count-dependent slotting with width semantics
that differ from the data-coordinate outline contract, so they cannot prove
that a fill terminates exactly at its keyline. Native bar objects remain in the
VSZ with `hide=True` to preserve editable dataset bindings. Each visible fill
is instead a native `rect` with:

- `positioning="axes"`, `clip=True`, `Fill/transparency=0`;
- `Border/hide=True`, because the keyline is a separate line object;
- data center `(x, mean/2)` and data geometry
  `[x-width/2, x+width/2] × [0, mean]`;
- Veusz rect width `width / (x_max-x_min)` and height
  `mean / (y_max-y_min)`, because axis-positioned rect centers use data
  coordinates while rect width and height remain graph fractions.

The grouped-bar contract requires a finite positive linear span and `y_min=0`;
otherwise preparation fails closed. The three visible keylines use the same
data geometry: left side, right side, and top. Error bars remain centered on
the bar and span `mean ± sample SD`. The exact-current VSZ audit verifies the
closed rect inventory, positioning mode, fill colour, zero transparency,
hidden rect borders, converted dimensions, clipping, and stored data bounds.
The style-contract test independently compares every fill's left, right, and
top bounds against all three keylines, preventing both underfill and overflow.

### Factorized curve legend geometry

A complete curve grid with labels in the form `Formula || Condition` uses a
closed two-factor presentation when it contains exactly two ordered conditions
and two to four formulas. Formula order owns the control-first categorical
colour root. Condition order owns the opaque light/dark tone. Every measured
trace remains a continuous, equal-width solid line with no point markers,
resampling, or thinning.

The compact legend has one `Weight reduction` heading. Its next row places the
abbreviated `33%` and `50%` conditions side by side. Each entry places a short,
moderately thick segmented native-rectangle swatch before its text and contains
every formula colour at that condition's lightness. A lower row contains the
formula-colour curve keys without a `Formula` heading. No native Veusz key is
created. The heading shares the formula row's left edge, while the condition
row spans the formula row's full outer width: the `33%` entry aligns left and
the `50%` entry aligns right. The exact-current audit closes the custom label,
line, and rectangle inventories.
Because this confirmed presentation intentionally uses colour and tone without
dash or marker redundancy, publication QA must retain any non-colour or
grayscale accessibility limitation for human review rather than silently
changing the line chart.

The tensile semantic adapter must also replay SciPlot's canonical structured
wide curve CSV directly. This keeps the three metadata rows, paired source
labels, every finite measured point, and the exact series order reusable
through `studio` without routing the file through a curated-workbook sheet
assumption.

Scientific semantics and presentation selection are separate contracts.
`SemanticRule` owns recognition, axes, units, replicate preservation, and
analysis. Its versioned `presentation_contract` owns the default template and
the explicit supported alternatives. The automated and Studio routes must
resolve that contract instead of rewriting a recognized metric back to a
single hard-coded chart. `impact_metric`, for example, supports `bar`, `box`,
`box_strip`, and `point_line` over the same categorical-replicate source. Its
point-line alternative compares compatible workbook conditions through
arithmetic-mean lines with the categorical-bar sample-SD error definition,
retains every raw replicate as a light condition-toned point, lays those
points out through the box-strip stable shuffled-slot policy around a small
condition-specific centre offset, and binds marker shape to sample position
rather than condition. For two conditions, the means, errors, and their raw
points use symmetric -0.05/+0.05 category offsets. Raw markers are 0.875 times
the mean-marker size at alpha 0.50; mean markers use a 0.70 pt white edge.
Four-sample impact overlays use the ordinary 60 x 55 mm frame.

Templates may define semantic behavior and editable options. They may not
privately override global typography, strokes, ticks, markers, or ordinary
frame margins. Heatmap scalar, contour, and colorbar colors are the explicit
semantic color exception. Nonstandard geometry is not a production template
capability and must not be introduced through a private profile lifecycle.

Scientific unit typography is also global. Source parsing accepts instrument
solidus forms, but every rendered or delivered display unit uses a
space-separated product with Unicode negative exponents (`kJ m⁻²`, `W g⁻¹`,
`Pa⁻¹`). Mathematical variable ratios such as `σ/σ₀` are not units and retain
their division operator. `materials_rules.py` owns normalization and
`style_contract.py` plus exact-current VSZ QA fail on visible unit-solidus
drift.

## Dependency rules

1. CLI and UI call orchestration/domain APIs; domain code does not depend on
   browser or Qt presentation state.
2. Headless intake/project preparation must be separable from the browser
   server and static UI so Studio does not depend on a second frontend.
3. SciPlot-owned modules do not import `third_party/veusz` directly; runtime
   adapters own that boundary.
4. New code must not deepen direct `src.*` or `_vendor` imports.
5. Importing `sciplot_core` must not initialize Qt, Veusz, browser, or network
   clients.
6. Paths, atomic writes, hashes, JSON parsing, style constants, and export
   names each have one shared owner.
7. Provider absence is normal; deterministic workflows cannot initialize AI
   unnecessarily.
8. Large modules are split one coherent owner at a time with characterization
   tests and unchanged public behavior.

Verification requirements are defined once in `skill/SKILL.md`; active
maintenance order is defined once in `DEVELOPMENT_ROADMAP.md`.
