# Ordinary plotting: one task

Use this route for new ordinary plots from original data. The local task owns
recognition, planning, native creation, QA and export. Separate inspect/rules/plan/
project-create/Studio commands, repository reading and tests are not prerequisites.

Ordinary creation stays on the existing production renderer and its shared house
policy, family templates and supported explicit overrides. Do not translate raw
input into a FigureTemplate merely to recreate defaults in an AI request.
Instrument directories are validated by their scientific owner; missing metrics
remain a source error, not a request for AI to select the same rule again.

Ordinary numeric XY intents can state `x.scale` and `y.scale` as `linear` or
`log`, or use `--x-scale`/`--y-scale` in `task create`. A logarithmic coordinate
requires every mapped original observation to be finite and positive; the
program never deletes or shifts observations to make it valid. Scientific
instrument adapters retain their own scale contracts; the ordinary scale flags
cannot silently replace an adapter's coordinate derivation.

1. Start directly with the original source:

   ```bash
   skill/scripts/sciplot task create /absolute/original --json
   ```

   This checks Doctor readiness and constructs the ordinary create request locally.
   Do not precede it with Doctor/capability/schema calls or a request JSON file.
   `--rule RULE_ID` and `--template TEMPLATE` require known scientific intent;
   do not select a different experiment to force recognition. `--profile PATH`
   reuses an existing mapping profile through current-source validation.
   Use `--out` only for a requested source-adjacent destination, and `--task-dir`
   for a task-evidence location. Output conflicts
   return an `out` question: choose a new path in the same task or inspect the
   existing project; never move old deliveries.

2. For an advanced structured request, use `task start --request REQUEST.json`.
   Read only the missing named request/response schema from task capabilities.
   If the original table is already understood, include `create.mapping` with
   its original file SHA, row selections, metadata evidence and XY pairs rather
   than rediscovering the same table. The typed entry does not invent mappings.

   For an already-understood set, one `task group start --request GROUP.json
   --group-dir NEW_DIRECTORY --json` carries independent create requests with
   their explicit mappings and linear/log choices. Each create item can include
   `presentation:{"operations":[...]}` using the existing typed edit operations
   for sample display text, legend and line styles. Include `figure_id` for a
   multi-figure project. This reuses native preparation, previews the complete
   per-figure batch before its first export, and retains scientific validation.
   Review all returned candidates and audits, then submit the current
   `next_step.responses_template` together through `task group resume --responses`.
   Keep later user intents, such as a subsequent label rename, in a later edit
   group; do not claim fewer calls by removing a separate review or intent.

3. For `needs_input`, use the returned original cells, dimensions, extents and
   rejection reasons. The program repairs a single explicit axis/unit/sample-row
   layout through ordinary validation. Numeric extents are not selected data;
   do not remove missing rows, infer units from magnitudes or choose between
   different sample conditions.

   With `mapping_candidates`, review the original note, rows, columns, units and
   samples, then reply with `expected_question_id` and `mapping_candidate_id`.
   Optional `pair_indices` selects/orders listed samples. The program expands
   source-bound declarations; do not transcribe them again. The candidate is an
   AI-reviewed suggestion, not an automatic scientific choice.

   Otherwise send one complete answer: `expected_question_id` plus `mapping`
   containing `source_sha256`, `table_selection`, optional
   `metadata_confirmations`, and
   `column_mapping:{"pairs":[{"x_column":0,"y_column":1,"label":"sample A"}]}`.
   Add `rule_id`/`template` if experiment identity remains a question. Each pair
   may have its own rows, worksheet and metadata declarations. Indices are
   zero-based; `data_end_row` is exclusive. Labels are display names; original
   sample/column evidence remains recorded. Distinct confirmed physical views
   may share an original sample name; they remain independent curves and are
   not pooled by assigning display names. Overlapping observations still require
   their existing scientific permission. Slashes and literal factor separators
   in display text do not create another sample, condition or file path.

   ```bash
   skill/scripts/sciplot task resume TASK_DIRECTORY --response ANSWER.json --json
   ```

   Correct `mapping_error` in the same task. An interrupted pending answer accepts
   `task resume TASK --retry --json`. Wire errors return `repair.issues` field paths/constraints;
   response errors include `repair.question` and `repair.next_step`. Correct those
   fields using the returned current bindings, without another inspect/help call.
   `repair.question_unchanged=true` reuses previously returned evidence and sends
   only the question reference. Stale/missing bindings return current evidence.
   Stepwise answers remain supported, but do not split a complete known answer.

   If the evidence lacks scientific meaning, ask only for that missing fact.
   Do not split files, try unrelated commands, inspect source code or recreate a
   project to work around a table question. `task table-region` reads more original
   cells when needed; do not send thousands of measurements through AI context.
   Original-cell declarations may cite another sheet in the same original workbook.
   Keep external excerpts, user statements and inferences separately attributed.

4. At `review_exports_and_deliver`, view returned TIFF images and hand off using
   fresh source/QA/delivery evidence, figure IDs and document hashes already in the
   response. An unchanged result needs no extra query, preview or export. Include
   `next_step.manual_edit`: the default human surface is `Open_in_SciPlot.command`.
   Its canvas Save updates the managed VSZ; Save and update delivery also refreshes
   VSZ/PDF/TIFF through existing QA. Veusz remains the advanced/portable fallback.
   Opening an old delivery must not rewrite it; its next export adds the launcher.

In a later session, query current state for the returned task/project once.
`task find SOURCE --json` helps when only the original path is known; multiple
matches or incomplete searches do not identify a unique project. Historical
receipts are not current readiness. Source changes or uncertain interrupted
creation must not silently overwrite or trigger a second creation.

Shared XY recovery supports ordinary paired curves and FTIR. Specialized scientific
adapters retain their own contracts; never convert their data into another
experiment to pass validation. Preserve raw rows, units and provenance throughout.

## Preserve the requested scientific presentation

Carry the user's explicit display or replicate-statistics requirement in the
first create call. `--curve-display raw_overlay` requires unshifted response
values; `--curve-display stacked_offset` requires explicit offsets. These are
constraints on an existing route, not permission to choose another display.
Source-only FTIR currently uses `stacked_curve` with offsets, so it cannot satisfy
`raw_overlay`. The existing semantic numeric-XY attachment route can bind
unshifted original values when its coordinate, unit and source-layout contracts
are met. Express a decreasing wavenumber axis with `--x-direction descending`;
`--y-direction` likewise declares left-axis direction. Both use existing scale
direction without reversing the measurements or changing their order. Never claim that
an unchanged plotted CSV proves native curves were not shifted.

Use `--summary-statistic mean_sample_sd_n` when the user requests mean ± sample
SD with delivered valid n. Original wide `impact_metric` tables with metric,
unit and sample rows support this requirement with `--template bar`. The visible
`data/*_replicate_summary.csv` contains original sample/condition, arithmetic
mean, sample SD, valid n and the missing policy, bound to the source and saved
spec hashes. It projects the audited bar contract without recalculating statistics.
The original file must remain available for later source replay: the sealed
`original_source` and its hash retain the original cells even when the native
renderer uses a prepared table. Missing or changed originals block disclosure;
source relocation needs the existing validated rebinding workflow.
Valid n counts finite numeric observations, never padded rows or inserted zeroes.
Fewer than two valid observations in any original group blocks sample SD.

Missing replicate cells return a source-bound `missing_values` question. After
the user explicitly chooses exclusion, resume with the returned
`question.response_template` (`expected_question_id` and `missing_values:"exclude"`).
If that scientific instruction is already explicit, advanced `task start`
requests may include top-level `missing_values:"exclude"` with
`summary_statistic:"mean_sample_sd_n"`; no second confirmation is needed.
No missing cells is disclosed as `none_present`, an observed source fact.
Nonnumeric/nonfinite values require resolution rather than an assumed exclusion.
Other templates/layouts retain their stated boundaries; internal analysis counts
alone never satisfy delivered n. Raw-only requests produce no summary CSV.

Existing `impact_metric` methods depend on their actual executor: `box` and
`box_strip` use median/IQR; `bar` uses arithmetic mean ± sample SD (`ddof=1`).
`point_line` also uses mean ± sample SD, but requires at least two compatible,
independently named workbook conditions. It cannot convert a CSV into that source
contract. `--summary-statistic mean_sample_sd` requests these existing mean/SD
presentations without claiming delivered n; fewer than two valid observations
in any group blocks this requirement. The legacy singleton zero-error fallback
is not an estimate of sample SD. Do not infer the method from point/line
appearance or from the rule's default box-summary render option; read the
template-specific scientific contract.
`--summary-statistic raw_only` requires no summary layers: raw points underneath
a box or summary line do not meet it. For existing `impact_metric` original
replicate tables, `box`/`box_strip` with `raw_only` selects the existing raw point
renderer and skips summary calculations, boxplots and summary analysis metrics.
The template name is retained as layout lineage; the returned categorical
presentation is `raw_points`, with no median/IQR or mean/SD summary. Original
sample order and every valid repeated observation remain; missing observations
are not filled. `bar` and `point_line` keep their fixed mean/SD methods and cannot
satisfy `raw_only`. `--summary-statistic median_iqr` requires
the actual existing median/IQR summary and rejects mean/SD bar or point-line
execution. Report `scientific_presentation` and the
returned unsupported issue accurately; do not remove the requirement merely to
make the task execute. A different scientific meaning needs explicit user intent.

For original categorical tables, use the separate
[categorical task binding](ordinary-categorical.md). Its `given_values` mode
displays supplied results without added error bars; explicit long-form replicate
groups use the existing mean/sample-SD bar owner, with optional delivered n.
The program reads source-bound rows and columns, validates sample/condition/value
roles and units, and keeps selection, order and display aliases separate.
The numeric-XY adapter still rejects semantic X quantities `sample`, `category`,
`categorical` or `metric`; numbering categories by hand is not a supported bridge.
Arbitrary pivoting, external statistics and changing experiments to force a
different importer remain unsupported. A missing Unit cell needs real evidence.
A column-level unit declaration cannot give different Metric rows different
units. For tidy performance scatter tables, use the
[source-bound Metric selection route](performance-selection.md), which accepts
an explicit original-user declaration for each selected missing Metric unit.
Neither route invents derived ratios or rewrites the original table.

The ordinary mechanical rule route currently requires its complete curve and
summary figure set. It has no separate raw-curve-only figure-set contract.
Missing reported break/elongation/toughness facts cannot be supplied by a curve
endpoint, column selection or a template change. Preserve the raw curve and
report the scope limitation; do not fabricate fracture or new derived metrics.

## Multiple attachments, coordinate choices and stages

Use this same task entry when the goal names coordinates, multiple attachments,
a right axis, segmented acquisition or display interpolation. Supply only the
scientific/view intent; the program expands source SHA, original headers, units,
row/column IDs, Binding and FigureSpec locally. Experiment identity (`--rule`)
and coordinate choice are separate. Do not switch experiments merely to obtain a
time axis, write a low-level FigureTemplate, or create a one-off plotting script.
When no experiment rule is declared, explicit numeric coordinates with verified
original units use ordinary original-value XY context (`ordinary_xy`), without
selecting a registered experiment or its analysis. Temperature/heat-flow cooling
records can therefore retain their original signs, order and missing values
without declaring a heating experiment. Without a declared rule or stage intent,
time resets and gaps remain original rows; they do not request cumulative stage
assembly. Missing units, unknown coordinate
meaning or ambiguous original columns still require clarification. An optional
JSON intent `source_context` archives the user's acquisition statement verbatim
in the source-bound provenance; it does not request a scientific calculation.
For example, save the caller-confirmed coordinates and acquisition statement in
`INTENT.json`:

```json
{"x":{"quantity":"temperature"},"y":{"quantity":"heat_flow"},"source_context":"Original cooling acquisition, not a heating scan; preserve original values without baseline correction, normalization or integration."}
```

Pass that file through the same public create entry:

```bash
skill/scripts/sciplot task create /absolute/original.csv --intent INTENT.json --curve-display raw_overlay --summary-statistic raw_only --json
```

Use this example only when those meanings and the original coordinate units are
established. Source context does not fill an absent unit or choose a column.

For example, replace the paths and choices with the user's actual intent:

```bash
skill/scripts/sciplot task create --source /absolute/first.xlsx --source /absolute/second.xlsx --x time --x-unit min --y mass --y-min 95 --secondary-y temperature --stages concatenate --marker-every 120 --interpolation pchip --task-dir /absolute/new-task --json
```

These are small closed flags, not a natural-language parser. `--y mass` explicitly
declares the response meaning; `%` alone does not prove mass. Known original
quantity/units remain source evidence. `--label` may be repeated once per
retained curve for authorized display names; it does not rewrite scientific samples.
`--y-min 95` sets only the displayed lower bound in its axis unit. The omitted
upper bound fits actual observations, including values above 100. Standard house
fonts, colors and layout remain local. Multiple-axis figures use an explicit
bottom-right legend and the first house width that passes deterministic layout;
this is not a guarantee against every possible native collision.

When there are unresolved scientific choices, the first response returns one
`semantic_plan` question with original file names,
SHA, exact table candidates, columns/units, per-stage row bounds, counts and
observed time/temperature endpoints. Ambiguous worksheets first produce a table
choice. After that answer, the same task returns any remaining choices for the
selected tables, with a new bound question ID; retain its accumulated answers.
Those choices include the original temperature role (for example Ts versus Tr),
right-axis source, stage order and elapsed-time boundary. An unchosen worksheet
cannot determine the builder or block coordinates in a chosen table.
Equal Ts/Tr values do not establish the
same scientific role. Source order is not automatically acquisition chronology.
A temperature-continuity suggestion is source-evidenced and still needs explicit
confirmation. A completely explicit intent with unambiguous original evidence executes directly;
there is no additional mechanical approval round. Review a returned question, then use its exact
`next_step.response_template` in one small answer file:

```bash
skill/scripts/sciplot task resume TASK --response ANSWER.json --json
```

Do not invent IDs: choose only advertised values from that receipt. Original
point arrays never travel through this answer. When the original sources or
request already establish a choice, the corresponding explicit flag
`--temperature-header`, zero-based `--temperature-source`, `--stage-order`, or
`--time-boundary` can include it in the first request. Its plan still shows the
bound actual attachment and SHA. Ask the user only about unresolved scientific
meaning; never silently choose a role or drop a stage to finish a figure.

For a JSON semantic intent, `secondary_y.header` and `secondary_y.column_id`
identify the actual original temperature column. They intersect when both are
given; legacy `temperature_header` must agree with an explicit secondary header.
Source-order stage concatenation without a secondary temperature axis does not
require an otherwise unused temperature column.

`preserve_endpoint` keeps both adjacent stage boundary measurements at the same
cumulative time. `next_sample` also keeps both measurements, advancing by the
entering stage's first measured positive sampling interval. Neither policy adds
measurements or forces a reference-image duration. Unit conversion uses a formal
registered transform. Original, derived and display data remain distinct.
Multiple coordinate candidates are answered by advertised original headers.
`--x-header`/`--y-header` or small intent coordinate `header`/`column_id` selectors
can state a known choice. A JSON coordinate's `headers` list can name differently
spelled original fields across sample blocks; every retained block still needs
exactly one match. Incompatible selectors return exact source-block evidence and
a same-task intent revision; they do not select by column position or redirect
to an incompatible scientific adapter.

Quantity/sample/unit rows retain each literal sample's independent numeric
grid, including unshifted spectral overlays from a single CSV. `selection.blocks`
keeps its existing original block order and records all exclusions. In a
multi-sample table, repeated `--label` values follow retained block order and
remain separate from original sample identity. Independent samples are never
concatenated as stages; an explicit stage request requires time acquisitions.
Closed machine headers such as `temperature_C` and `heat_flow_W_g` carry
explicit units. If an original unit is absent, select the exact original field
and put a confirmed user fact in `source_unit`; `unit` remains the output unit.
For example, a small JSON intent may contain
`"y":{"quantity":"viscosity","headers":["response_red","response_blue"],"source_unit":"mPa s","unit":"Pa s"}`.
This declaration is archived as user-statement evidence against the source SHA;
it cannot overwrite an observed unit or turn a recorded viscosity component
into complex-viscosity magnitude. Preserve the original CSV rather than adding
units to its cells.

For multiple original response quantities on one ordinary Y axis, a JSON intent
can declare `y.quantity_members` and one `curve_bindings` entry for each member
in every selected block. Each entry names the returned `source_id`, `table_id`,
`block_id`, `x_column_id`, `y_column_id` and `y_quantity`. Use original IDs from
the source-plan response. Each pair retains its own X grid and original unit;
the shared axis retains all declared member quantities. The supported grouping
is the existing modulus family (storage/loss modulus) or neutral response
quantities with compatible units. It does not calculate a new magnitude.
This original-value route cannot combine a scientific rule, acquisition stages
or a secondary axis with these bindings. Unknown or conflicting quantities
remain a correctable scientific question.

`--marker-every N` renders every Nth original point while keeping every source
measurement. Explicit PCHIP uses four display subdivisions per interval by default
(`--interpolation-subdivisions 2..32`). It is shape preserving, splits at missing
and duplicate-X boundaries without deleting or sorting points, and rejects
backwards time until the declared stage transform resolves it. These are display
samples, not additional measurements or denoised scientific estimates.

A rejected draft can be corrected in this same task using the returned
`draft_revision_template` (`expected_intent_revision` and the full small
`revise_intent`). The program retains the old attempt and assigns the next draft's
internal key. Do not invent or change a plot idempotency key. After commit or an
uncertain reply, `task resume TASK --retry --json` continues that frozen attempt
and its export; it cannot replace committed science or create another figure.
The task automatically packages its verified export through the existing
Managed native-snapshot delivery owner. Final delivery includes plotted CSV,
source copies, portable VSZ, PDF/TIFF, ZIP and the actual native launcher.
Hidden artifacts and final `--out` are distinct; an existing destination is never
overwritten. The package request is frozen before publication. A packaging
interruption resumes only that same delivery, never creation or scientific
transforms. Only its complete current byte inventory can produce
`review_exports_and_deliver`. View the
returned TIFF and keep the original sources and `.sciplot_documents` authority.
Managed saved edits use guarded task edit/plot patch; the ordinary browser canvas
does not currently open a Managed document root. Its returned VSZ can be opened
through the existing native `studio VSZ` route for advanced editing, preferably
as an independent copy. An external native save does not replace Managed
scientific authority; explicit reconciliation or semantic editing is required.

CLI `--intent`, `--request`, `--response` and `task table-region --query` take
**JSON file paths**, never inline JSON text. MCP takes the corresponding JSON
objects directly. Do not start an MCP process solely to discover a missing
ordinary option; use the returned task continuation, or one named capability
section if a contract detail is missing.

Explicit expert template/library construction remains available through `plot
create`. It shares the same Managed lifecycle and typed edit contract; it is not
an extra step for attachment plotting. Legacy projects retain their complete
saved VSZ authority and are never silently promoted by this route.

## Instrument frequency sweeps

For complex-viscosity magnitude from an original instrument frequency table:

```bash
skill/scripts/sciplot task create /absolute/raw.csv --rule rheology_frequency_sweep --x angular_frequency --y complex_viscosity --x-unit rad/s --y-unit 'Pa s' --task-dir /absolute/new-task --json
```

Explicit temperature-labelled `Result` intervals remain separate series with
their source identities, actual point counts and order; measured temperatures
are retained. `Im(Complex Viscosity)` and real viscosity are components, not
`|eta*|`. When no magnitude column exists, original G′, G″ and frequency with
supported unit evidence allow the program's formal magnitude derivation; the
source bindings and transform evidence remain recorded. An exact header selector
pointing to a component cannot declare it a magnitude. Correct that small intent
in the same task using the returned `draft_revision_template`, then resume through
the existing task entry. Preserve the original CSV and all scientific points.

For a mixed source, add `--test-name 'Exact observed Test value'` to this same
command. Repeat it for several literal Test values. `--source-block
source:0/table:0/block:1` selects an exact block advertised by the source plan;
repeat it for several blocks. Both selectors intersect when supplied. Test
names come from original Test cells, including case; filenames and display
labels do not establish them. Unknown references or an empty intersection
return a correctable draft error. Omission retains the all-block behavior.
The compact `source_plan.selection` records selected/excluded block identities,
original Test/Result rows, point counts and reasons. It does not contain numeric
arrays. Selection precedes coordinate decisions and the existing formal
magnitude/unit transforms, without rewriting the source CSV.

A successful semantic creation returns `plot_objects` with an exact plot target
and `next_step` for its current description. Use that existing object for a later
legend or annotation change. Read its advertised property/current-value contract,
then send a delta through `plot.patch`; do not repeat source coordinates or
create another figure for a supported presentation edit.

## Stress-relaxation paired wide tables

The stress owner recognizes the explicit compact pairs
`sample|t_s,sample|sigma_over_sigma0` (or a single `t_s,sigma_over_sigma0` pair).
Seconds and the already normalized response are declared by those exact headers;
G(t)/G0 and relaxation modulus remain different contracts. Each pair keeps its
own source order and actual length. Only structurally empty trailing paired cells
are outside that curve; interior holes, half pairs, nonnumeric values and mismatched
sample headers return the original source/column, expected/observed evidence and a
same-task mapping continuation. Never repair those errors by rewriting raw cells.

To review groups before plotting, use the ordinary entry:

```bash
skill/scripts/sciplot task create /absolute/original.csv --rule rheology_stress_relaxation --choose-columns --xscale linear --json
```

Review the returned candidate's original sample identities, per-pair row ranges,
counts and first points. `mapping_candidate_id` plus explicit `pair_indices`
selects/orders only the requested curves; use a new task/output for another group.
For an already understood multi-figure request, existing `task group` items may
carry complete `create.mapping` selections and `xscale`, so local validation,
FigurePlan, preparation, native QA and canonical delivery remain the same route.
Do not reconstruct a default FigureTemplate, split raw files, or send numeric
arrays through the AI request. Group item labels are distinct from the original
source-column identities; explicit pair `label` is a recorded display label.

`--xscale log|linear` is a closed stress-relaxation create option, bound into the
expected plan and canonical request. Other adapters keep their registered scales.
Normalization is determined from the complete source sequence before any display
projection: already normalized values are preserved point for point; unnormalized
stress uses its original first finite nonzero response. Log display then explicitly
selects positive time, recording source/pre-display/active counts and exclusions;
it does not renormalize the first visible point. Linear includes the original
zero-time pair. A supplied (0,1) therefore appears as (0,1) on linear but is not
visible on log. The original SHA-bound source still contains the complete arrays;
the active log table does not claim to contain its excluded zero row.

The ordinary stress template does not add a user-requested `1/e` reference or
sample annotation automatically. Continue the returned saved project through the
existing reviewed annotation task; no mathematical CSV is needed. Read the
selected figure once with `project inspect PROJECT --figure FIGURE_ID --json` to
obtain its current document SHA and exact displayed annotation axis unit. The
ratio-only stress y label has the dimensionless annotation unit `""`, which differs
from its source metric unit `sigma/sigma0`; always use the inspected value.
A single existing edit request can batch:

```json
{
  "version": 1,
  "action": "edit",
  "project": "RETURNED_PROJECT",
  "figure_id": "RETURNED_FIGURE_ID",
  "expected_document_sha256": "CURRENT_DOCUMENT_SHA256",
  "operations": [
    {"op":"add_reference_line","id":"one_over_e","parent_path":"/page1/graph1","axis":"y","value":0.36787944117144233,"unit":""},
    {"op":"add_annotation","id":"one_over_e_label","parent_path":"/page1/graph1","text":"1/e","position":{"mode":"relative","x":0.85,"y":0.4}},
    {"op":"add_annotation","id":"sample_display","parent_path":"/page1/graph1","text":"USER_CONFIRMED_NAME","position":{"mode":"relative","x":0.65,"y":0.7}}
  ]
}
```

Start it with `task start --request EDIT.json --task-dir NEW_EDIT_TASK --json`.
Reference lines are natively dashed. Inspect the returned actual preview and
scientific audit, then accept its exact operation ID using the returned resume
command. The relative text positions above are examples, not collision guarantees;
revise the same batch if the actual legend or data overlaps. The normal edit/export
owners update the saved VSZ and delivery; source columns are not renamed, native
VSZ text is not patched, and Legacy authority is not promoted to Managed authority.

A dense multi-series log figure may still fail the existing non-colour/grayscale
or native legend-clearance gate at the ordinary 60 mm size. That is a presentation
constraint, not evidence that normalization or source binding failed. Preserve the
project and scientific arrays; use advertised native series/legend style operations
in the same reviewed edit path, then follow `repair_export_then_retry`. Do not
weaken QA, regenerate a different experiment, or rename source columns. For a
requested upper-left sample label, inspect that actual location in the returned
preview instead of treating the example relative coordinates as a universal fit.
