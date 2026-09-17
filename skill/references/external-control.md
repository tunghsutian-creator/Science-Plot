# External AI control of SciPlot

This is the public CLI operating guide for an external AI. Use SciPlot for local,
deterministic scientific preparation, native Veusz operations, validation and
delivery. The AI owns the user's task and interpretation; SciPlot does not need
an internal model provider, GUI selection, or a running browser.

Run commands from the checkout with `skill/scripts/sciplot`. Use absolute data,
project and evidence paths. The uppercase names below are placeholders to replace
with values read from the current command results, not literal arguments.

## Start or resume

For a standard task, prefer the local runner described below. The lower-level
commands later in this guide remain available for exact control and diagnostics.

```bash
skill/scripts/sciplot doctor --json
skill/scripts/sciplot task capabilities --json
```

Require Doctor `status=ready`. For an existing managed Studio project, start at
**Read the saved project** below; do not rerun its raw source to make an edit. Before applying an
external edit, close every writable native Veusz window for that project,
including a clean window with no unsaved changes. Save any intended native
changes first. A blocked session is a conflict to resolve, not a lock to delete.

## Complete local tasks and MCP

Read `task capabilities --json` for the small capability index (version 2).
Fetch just the required schema with `task capabilities --section request --name
create --expected-contract CURRENT_SHA --json`. Sections are `request`, `response`,
`operations` and `table_region`; names come from the index. The fingerprint binds
each schema read to the same contract. `--full` returns all task schemas with local
`$defs` references; each schema is independently valid JSON Schema. Task request
version remains 1, and server validation and document/question/review guards are
unchanged. MCP offers the same query as `sciplot_task_capabilities`; tool input
schemas factor repeated definitions at their own root. Returned `next_step`
guidance identifies the current question/review bindings or the recovery boundary.
A create request is:

```json
{"version":1,"action":"create","source":"/absolute/path/UVvis.csv"}
```

```bash
skill/scripts/sciplot task start --request REQUEST_JSON --json
skill/scripts/sciplot task inspect TASK_DIRECTORY --json
skill/scripts/sciplot task resume TASK_DIRECTORY --response RESPONSE_JSON --json
```

The runner selects an authoritative recognized rule, builds and verifies a fresh
plan, prepares the managed project and exports it. Specify `rule_id`/`template`
only when the user's scientific intent establishes that choice. `out` is an
optional new visible delivery beside the raw source. `task_dir` is an optional
new evidence location outside raw data, projects and visible delivery packages.
Reusing a task directory with the same request returns its receipt, never a
second creation; a different request is rejected.

### Fast ordinary route

Reuse capability schemas within the same contract revision. `task start` already
owns recognition, source-bound planning, native creation, export and validation;
do not precede it with the lower-level inspect/rule/plan/create/export sequence.
Completed `start` and `resume` responses include a fresh `current_project` query.
If `next_step.action` is `review_exports_and_deliver`, view its exported TIFF
`images` and hand off; the unchanged result needs no extra inspect, native PNG
generation or export. Existing receipts still get a fresh query when returned;
saved historical evidence is never substituted for it. A later source, document
or delivery change requires another query. `task inspect` remains the entrypoint
for a new session or an existing task.

Task `start`, `resume` and `inspect` use the same compact response in CLI and MCP.
Successful responses omit duplicate artifact inventories and healthy-check detail;
they retain current figure IDs, document hashes, sample labels, source/QA/delivery
currentness and exported review image paths. Pending scientific questions,
conflicts, preview images/audits and revision guards are not suppressed. Read
`--full` or MCP `full:true` for the detailed response; MCP also offers an immutable
full-result resource. The complete hashed task history remains in `task.json`.
Full task responses are response projections, not copies of the entire history.

`local_timing` reports the number and cumulative duration of active local calls,
and the latest call; its phase breakdown is in the full response. It excludes external model inference, transport
and user waiting; `external_model_seconds` and token counts remain unknown.
Repeating an already finished task does not rewrite its timing or rerun creation.

### Already-reviewed original data: one mapping submission

Keep the external AI's original-data interpretation. When it has already inspected
the cells, it may submit those explicit choices in `create.mapping` instead of
waiting for individual table/metadata/column questions. Provide the original
single-file byte SHA-256 (not the source-tree hash), a known `rule_id`, and:

```json
{
  "source_sha256": "CURRENT_ORIGINAL_FILE_SHA256",
  "table_selection": {
    "sheet": "Measured", "header_rows": [0], "unit_row": 1,
    "sample_row": 2, "data_start_row": 3, "data_end_row": 103
  },
  "column_mapping": {"pairs": [{"x_column": 0, "y_column": 1}]}
}
```

This object belongs under `mapping` in the ordinary create request with `version`,
`action`, `source` and `rule_id`. `sheet:null` selects a CSV/TSV. Bounds remain
zero-based/end-exclusive; each pair may specify its own complete selection.
Optional `metadata_confirmations` uses the same original-cell, cited-excerpt or
attributed-user evidence as interactive answers. No data arrays, inferred missing
units, source rewriting, unit conversion or visual-preview acceptance is added.
Do not combine this with a saved profile. `choose_columns:true` remains optional
and backward compatible; `mapping` already explicitly selects the column route.

Every choice runs through the existing mapping owners and durable confirmation.
Wrong SHA blocks creation; invalid region, unit or sample pairing returns the
current `needs_input` question with `mapping_error`. Correct it using ordinary
source-bound `resume` answers; the failed original batch is not reapplied. An
interrupted incomplete batch can retry its original intent before native creation.
Capability schemas may be larger for this optional input; fetch them once per
contract revision, and do not reread them for every figure.

Pending table questions retain column diagnostics and question bindings while
omitting repeated whole-workbook snapshots. Initial previews show up to eight
rows per sheet; `preview_truncated` marks the limit. Use `task table-region` for
more original cells or read `question.full_evidence_path` for the full saved
question. This compact projection does not change the question hash or validation.

For XLSX/XLSM merged metadata, original region queries include `merged_cells`
with zero-based bounds and exclusive ends. An explicit selection with
`expand_merged_metadata:true` associates selected metadata with the declared
anchor, preserves original blanks under `raw_metadata` and `cell_evidence`, and
returns `merged_metadata` associations. A merge crossing into measurements is
rejected. Numeric sample IDs selected from original cells are represented by a
versioned explicit JSON sample row in derived mapping data; original identities
and point counts are preserved. This does not infer numeric metadata in raw data.

For new source-update transactions, retry can restore a proven old baseline from
an interrupted replacement. All project, archive and preserved candidate parts
must match the recorded bytes before any recovery mutation. Candidate bytes and
a rollback receipt remain alongside the original archive. Recovery itself can
be retried after another interruption. Altered or unknown parts and legacy mixed
installations still block; a restored baseline does not bypass fresh scientific,
source, delivery or reviewed-candidate checks.

`task inspect` queries current saved project evidence once and returns it under
`current_project`, including `primary_figure_id`, `figures[].document_sha256`
and `figures[].sample_styles`. Use these current identities to continue a
supported sample-style or annotation task without another project query.
The task's `result` stays historical; a failed current query exposes no edit
targets. This is saved-file state, not live GUI state or readiness certification.
Explicit object/setting edits still require `project inspect --figure FIGURE_ID`
for their current native settings and allowed fields.

When a new session knows only the original source path, recover a creation task
and its recorded project with:

```bash
skill/scripts/sciplot task find SOURCE --json
skill/scripts/sciplot task find SOURCE --tasks-root HISTORY_DIRECTORY --limit 20 --json
```

MCP exposes the same service as `sciplot_task_find`. The default history is
`SOURCE_PARENT/.sciplot/tasks`; pass the actual task root for custom task/output
locations. The search reads that root and its direct task directories, validates
existing receipt hashes, matches the exact recorded source path and fingerprints
the current source once. It does not use filenames/content similarity to infer
origin or create another project. Only creation receipts provide this original
source relationship; low-level projects without them need their explicit saved
project or delivery path.

Results list newest recorded tasks first and retain pending questions or blocked
tasks as well as completed ones. Inspect the selected `task_dir` or historical
`project` reference before continuing. `source_current:false` means the original
source differs or is missing; unknown evidence stays null. Multiple candidates
or an incomplete scan require selection or a narrower lookup. Read `match_count`,
`has_more_matches`, `scan_complete` and `issues`: the search scans at most 1,000
receipts, skips unreadable/oversized/symlinked records and returns at most 100
matches (20 by default). A zero result only describes the reported search scope.

`needs_input` exposes an actual rule-selection or source-column question and evidence.
For a rule question, resume with `{"rule_id":"uvvis_spectrum"}` and optional
`template`; source bytes are rechecked. Invalid choices remain correctable.

For one x/y column pair, use a create request with `choose_columns:true` and the
actual experiment rule. A supported single-x/multiple-response table also pauses
automatically. The first supported layouts are CSV/TSV with unit-bearing column
headers and numeric rows, or the canonical name/unit/sample three-row header.
Read `question.evidence`: its cells and indices refer to the original file,
including repeated headers and blank separator columns. Reply with:

```json
{"expected_question_id":"CURRENT_QUESTION_SHA256","column_mapping":{"x_column":0,"y_column":3}}
```

Indices are zero-based. Only these two columns enter this figure; the original
file remains intact. Samples and units must be present in the source, and the
registered scientific rule still validates the mapped table. The persisted
DataMapping confirmation is reused on interruption, and the plan/project retain
both original and effective source identities. Changed sources reject old answers.
The selection is not saved as a reusable profile. The table route below can confirm
missing metadata with explicit evidence; arbitrary scientific repairs remain unsupported.
The column-choice route rejects missing/nonfinite selected values,
blank data records and sample labels that cannot survive the mapped filename
unchanged. It never drops such records or silently renames the selected sample.

Excel and other row layouts use `table_selection` first. Inspect each worksheet's
original preview, then select its exact name (null for text), header rows, optional
unit/sample rows and a contiguous data range. All indices are zero-based and the
end row is exclusive. For example:

```json
{"expected_question_id":"CURRENT_QUESTION_SHA256","table_selection":{"sheet":"Measured","header_rows":[1],"unit_row":2,"sample_row":3,"data_start_row":4,"data_end_row":104}}
```

The next question separates `raw_metadata`, `metadata_confirmations`,
`x_rejection_reasons`, `y_rejection_reasons`, and `sample_rejection_reasons` per
column. Numeric diagnostics include point count and up to 16 failing original row
indices. Pair identity is checked when choosing pairs; a missing X sample may be
valid for a shared axis. Choose explicit pairs when the science is resolved:

```json
{"expected_question_id":"CURRENT_QUESTION_SHA256","column_mapping":{"pairs":[{"x_column":0,"y_column":1},{"x_column":0,"y_column":3},{"x_column":4,"y_column":5}]}}
```

This example selects two responses sharing X and one separate XY pair. Each Y
needs a unique sample label from the selected X or Y sample cell. If both are
present they must match; shared X may have an empty sample cell. One pair without
a sample row uses the original filename.
Answer `table_selection` again with the current question ID to correct metadata
or data bounds, including from a legacy single-pair question. No file rewrite is
needed. Each pair may supply its own complete `table_selection`, including a
different sheet in the same original workbook. Omission inherits the current
selection. For example, a shorter second pair can use:

```json
{"x_column":2,"y_column":3,"table_selection":{"sheet":"Measured","header_rows":[0],"unit_row":1,"sample_row":2,"data_start_row":3,"data_end_row":103}}
```

Same-sheet metadata confirmations are inherited unless the pair supplies a full
replacement `metadata_confirmations` list. A different sheet inherits no declarations;
supply its own source/sheet/column-bound evidence when needed. Every selected pair
must be finite throughout its own range. Overlapping response rows cannot identify
different samples; disjoint vertical blocks can. Up to 32 pairs and 256 columns per
table are supported. Values and order remain exact, and the scientific plan checks
each sample's point count. The rectangular derived CSV pads completed pairs with
empty cells only; these are never measurements. Source update requires fresh ranges
and evidence, then the ordinary annotation and image review. Numeric-only sample
names and merged metadata cells needing expansion remain unsupported.

Read beyond the initial preview without changing the question:

```bash
skill/scripts/sciplot task table-region TASK --query region.json --json
```

```json
{"expected_question_id":"CURRENT_QUESTION_SHA256","sheet":"Measured","row_start":120,"row_end":125,"column_start":0,"column_end":6}
```

The equivalent MCP tool is `sciplot_task_table_region` with `task` and `query`.
Bounds are zero-based and end-exclusive, at most 128 rows × 64 columns. The
result preserves original indices, blank cells and decoded cell values. It is
not a formula/style or merged-cell interpretation. Source or question changes
invalidate a query.

For missing scientific information, answer with a complete declaration list:

```json
{"expected_question_id":"CURRENT_QUESTION_SHA256","metadata_confirmations":[
  {"source_sha256":"ORIGINAL_FILE_SHA256","sheet":"Measured","column_index":1,"field":"sample","value":"A","evidence":{"kind":"source_cell","sheet":"Measured","row_index":1,"column_index":1,"text":"A"}},
  {"source_sha256":"ORIGINAL_FILE_SHA256","sheet":"Measured","column_index":1,"field":"quantity","value":"Absorbance","evidence":{"kind":"external_reference","uri":"https://example.org/instrument-record","locator":"Measurement A, axis description","excerpt":"Absorbance (a.u.)"}},
  {"source_sha256":"ORIGINAL_FILE_SHA256","sheet":"Measured","column_index":1,"field":"unit","value":"a.u.","evidence":{"kind":"user_statement","asserted_by":"DATA_OWNER","statement":"ACTUAL_USER_STATEMENT_ABOUT_THIS_COLUMN"}}
]}
```

Replace placeholders with inspected evidence, never invented statements. Each item
binds original file SHA, worksheet, column and exactly one `quantity`, `unit` or
`sample`. Evidence is either a byte-verified source cell, an external URI with a
locator and excerpt, or an attributed user statement. The caller must read and
judge external materials; the deterministic service does not fetch the citation
or certify its truth. Frozen excerpts and declarations are included in the signed
DataMapping proposal, alongside the separately retained original cell facts.

Inspect the returned question before selecting pairs. A non-axis header can be
identified explicitly as a sample before supplementing its missing quantity.
Existing axis names, explicit units and sample cells cannot be overwritten by a
contradictory declaration. Multiple different declarations of a field also block
that column. Units still use the existing scientific rule validator; confirmation
does not convert measurements or make a different quantity equivalent.

To correct a pending statement, submit the entire replacement list with the new
question ID. `[]` withdraws all declarations; table re-selection also clears them.
Accepted answers and superseded questions remain in the task history. Errors in
shape, source binding or cell text leave the current question unchanged; scientific
conflicts stay visible and prevent the affected pair from proceeding. Once creation
has begun, this pending-answer correction route cannot mutate the saved mapping.

To revise an existing project's data, start:

```json
{"version":1,"action":"update_source","project":"/absolute/saved/project","source":"/absolute/new/source.csv"}
```

The optional `worksheet` names an explicit worksheet supported by the existing
source-update owner. The result retains every original/candidate PNG under
`previews` and a complete saved review at `preview.review_path`; MCP provides
corresponding `preview_resources`. Inspect all figures and the recorded changes,
then resume with:

```json
{"accept_source_update":true,"expected_revision_id":"CURRENT_REVISION_SHA256"}
```

False cancels without applying. Source, saved project, visible delivery and PNG
changes invalidate the review. The existing transaction archives the old project,
applies the reviewed revision, and the task exports the exact saved result.
An export failure resumes export only. A lost apply reply is recoverable only
when the durable operation and current bytes prove the same completed result;
an interrupted partial installation remains blocked with its archive retained.
Projects with confirmed mappings pause for fresh table/column selection before
preparation; old column positions are never reused on new bytes. Compatible fixed
annotations retain coordinates. Peaks are matched only to the exact sample and
original search window. `needs_input` / `annotation_rebinding` returns factual
statuses and provisional before/candidate PNGs. Short P markers match the
candidate records' `preview_marker`, sample and numerical coordinates. Review moved, unchanged, missing,
ambiguous or incompatible anchors, then answer:

```json
{"expected_revision_id":"CURRENT_REVISION_SHA256","annotation_choices":[{"figure_id":"CURRENT_FIGURE","id":"peakA","action":"rebind","candidate_id":"CURRENT_CANDIDATE_SHA256","text":"460 nm"}]}
```

Each decision uses `rebind` with explicit final text, `remove`, `keep` for a compatible
fixed annotation, or `replace` with a same-ID fixed annotation operation. A missing
peak cannot be rebound. Optional rebind `position` uses the ordinary coordinate
contract; otherwise existing arrow-label placement is retained and unoffset labels
follow the selected point. Unanswered anchors remain pending; subsequent replies
retain prior decisions and replace only the annotation identities answered again.
Inspect the resulting
final PNGs and then accept their **new** revision ID. Old responses cannot approve
new choices. Provisional candidate markers cannot be installed. These questions do
not authorize arbitrary scientific facts.
The task interface does not accept arbitrary DataMapping answers beyond its
advertised source-column choice schema.

An edit request contains `version:1`, `action:"edit"`, `project`, optional
`figure_id`, `expected_document_sha256`, and `operations` from the shared
annotation operation schema. It returns `needs_review` with `preview.image`,
`preview.review_path`, actual changes and audit. Read the image and audit, then
resume with `{"accept_preview":true}` to apply and export in one local continuation.
Use `false` to discard the proposed change without changing the document. The
user's existing concrete instruction authorizes the edit; no redundant user
permission is required for each mechanical step.

To refine a pending preview in the same task, resume with a replacement batch:

```json
{"expected_operation_id":"CURRENT_PREVIEW_OPERATION_ID","revise_operations":[{"op":"set_sample_style","samples":["E0","E3"],"style":{"width":"2pt"}}]}
```

Use the returned `operation_id`, and replace the whole batch: the replacement
uses the same saved document, figure and revision, not the prior candidate.
Original requests and previous candidate files remain available. The summary's
`preview_revision` counts requested versions; an identical latest revision
submission returns its current receipt without rendering again. A failed build
keeps the replacement intent and resumes with `{"retry":true}`.

If the task is `blocked` in `previewing` and the operation itself needs correction,
replace it in place using the returned `preview_revision`:

```json
{"expected_preview_revision":2,"revise_operations":[{"op":"set_sample_style","samples":["E0"],"style":{"width":"2pt"}}]}
```

Use the actual current integer, not the example value. This binding is only for
failed previews, which may have no image or operation ID. A `needs_review` task
still requires `expected_operation_id`; the two bindings cannot be combined.
The corrected batch uses the original saved baseline and keeps the original
request, failed attempts and failure reasons in its receipt. Repeated identical
corrections are idempotent. Read the new image and bind acceptance to its new
operation ID. Applying/exporting, accepted or completed work cannot be replaced
through this recovery path; a changed saved baseline still requires a new task.

Accept or reject the new preview with
`{"accept_preview":true,"expected_operation_id":"CURRENT_PREVIEW_OPERATION_ID"}`.
Always bind responses this way; unbound responses remain compatible only for
an initial preview. Stale responses leave the current task unchanged. A task
already applying, exporting or complete requires a new edit task for new intent;
an uncertain apply must first be recovered, not replaced.

Malformed operations (missing/unknown fields, wrong JSON types or nonfinite
values) are rejected before task creation or replacement of a pending preview.
The error identifies the operation/field; correct that request and keep using
the existing preview ID. The CLI and MCP enforce the shared public operation
schema. Passing this shape check does not establish valid units, sample mapping,
native settings or source evidence: those checks still run against the project.
Historical blocked tasks remain inspectable even if their old request is malformed.

Pure style requests that already match after native normalization and science
validation finish automatically with an `unchanged` edit outcome. They require
no preview acceptance and do not rewrite the saved document. With `export:false`,
the result reports `document_changed:false`, the same saved document SHA and
`export_required:null`: existing delivery currentness is a separate query. When
export is requested (the default), it still runs and `edit_outcome.status` records
`unchanged` alongside the export receipt. Annotation operations and mixed batches
always retain review; this shortcut does not infer semantic equivalence.

For successive edits, add `"export":false` to the edit request. Accepting its
preview saves the current document and completes that edit without exporting.
The `sciplot_task_edit_result` has `status:"saved"`, `document_sha256`,
`figure_id`, `export_performed:false` and `export_required:true`; use that saved
revision for the next edit. Completed summaries omit the old preview image;
its evidence remains in the task directory. Omitting `export` retains apply-and-export
behavior. Finish with an export task when the figure is ready for publication.

To edit multiple ordinary sample curves, read `figures[].sample_styles` from
`project inspect`. These are exact source-bound labels in the selected figure,
not aliases, fuzzy matches or native widget names. A batch can include:

```json
{"op":"set_sample_style","samples":["E0","E3"],"style":{"width":"1.5pt"}}
```

`style` supports `color` and `width`; mix several operations for different colors.
Sample color also updates visible markers and uniquely bound generated sample
direct labels. Free annotations keep their color; line width affects only curves.
The local service resolves the unique curves and current setting values, then
previews the expanded `set_style` operations in the existing native transaction.
The inspected document and sample-mapping spec must still match. Unknown,
duplicate or ambiguous labels are rejected; for ambiguous labels inspect the
curves and choose explicit `set_style` paths. Semantic color encodings remain
protected, and a batch may expand to at most 100 native operations.

An export request is `{"version":1,"action":"export","project":"/managed/project"}`.
Export failures preserve the current project. Resolve the reported cause and
resume with `{"retry":true}`. An interrupted creation before a project identity
was checkpointed reports uncertainty if output exists; it never overwrites it.
Applied edits use the original preview and durable operation for bounded retry.

`status=complete` is historical completion of the requested scope. A saved edit
with deferred export is not a publication receipt. For create/export or an edit
that requested export, require `result.studio_run.ready_to_use=true` at handoff;
later query the current project evidence.
Top-level `ready_to_use=null` deliberately avoids certifying old results.
`model_calls_by_sciplot=0` describes the deterministic runner, not the external
client's model use. External token usage remains null when no telemetry is available.

When reliable source headers allow it, `profile` points to reusable rule/template
configuration. Pass that path as `profile` in a new create request, without
overriding rule/template. Headers, units and current data are read again; old
samples, numerical values and confirmation receipts are never reused. A missing
or incompatible profile does not justify forcing the saved rule. Unsupported
profile saving is explicitly reported as `profile_unavailable`.

The optional `sciplot mcp` stdio server exposes these services directly. Install
the `mcp` extra in a source environment; the macOS bundle includes it. Tools are
discoverable via MCP, with shared JSON schemas. Normal operations need no repository
inspection, internal imports, model key or Python code generation. Results are
compact; read returned `sciplot://result/…` JSON/PNG resources on demand. Resource
URIs are scoped to the current connection; retain project/task paths for a new one.

CLI `project inspect`, `project edit-preview` and `project operations-preview`
use the same compact projection as MCP: current editable values, display context,
revision identity, actual changes and audit remain present. Use `--full` for
complete native settings or signed preview state. Always apply the complete
saved JSON at `review_path`; the compact stdout is a summary, not an apply file.
MCP additionally returns an immutable full-result resource when it compacts a result.

## Explicit low-level creation

For new raw data, read the source and the registered invocation:

```bash
skill/scripts/sciplot inspect SOURCE --json
skill/scripts/sciplot rules list --json
skill/scripts/sciplot rules show RULE_ID --json
skill/scripts/sciplot plan SOURCE --rule RULE_ID --template TEMPLATE_ID --json > PLAN_JSON
```

Choose `availability=ready` and use its exact rule/template values. Read the
whole plan, selected figures and any scientific transform. Preserve the original
plan JSON. When the user's scientific intent and the plan agree:

```bash
skill/scripts/sciplot project create SOURCE --expected-plan PLAN_JSON --json
```

`--expected-plan` checks the current source bytes and scientific choices before
creating a project. `project create` reads the rule and template from that exact
plan and reuses the ordinary native Studio prepare/export lifecycle. A changed
source or mismatched plan requires a fresh plan;
do not remove this argument to bypass a failure. `planned` or `not_applicable`
is a plan result, not a delivery claim. Require the execution result's
`studio_run.ready_to_use=true`, then retain its `project_dir`, `document` and
run/delivery references. The result has a canonical `studio/document.vsz` and
figure-set registry ready for the query/edit loop below. If the source needs clarification or repair, report
the structured reason; never guess units, sample identities or scientific values.

Create returns a compact `sciplot_project_creation_result` v1 object. On success
`status=created`; `project_dir`, `document` and `request` identify the managed
project. `figures` contains brief identity/document/export references, while
`studio_run` retains readiness/state, the full `manifest` resource path and
`delivery_package.path/complete`. Read that manifest only when detailed QA or
scientific evidence is needed; large scientific arrays and repeated internal
payloads are intentionally absent from stdout. A returned creation failure has
`status=blocked` with `studio_run.failure_stage/failure_reason` and a nonzero exit
code. Exceptions before a creation result use the normal CLI error envelope.

Omit `--out` to keep the visible `SOURCE_SciPlot/` package beside the source.
Creation requires both the visible output and its hidden workspace to be new.
If they already exist, inspect the existing managed project or deliberately
choose a new dedicated `--out`; creation never overwrites an existing project.
User evidence such as PLAN_JSON and CHANGES_JSON belongs outside raw-input
directories, the managed project and the visible package. Development evidence
belongs under `.tmp_verify/`.

`autoplot` remains a compatible one-time delivery route with its own ready
summary. Its historical `project_dir` can contain only run artifacts, without a
canonical Studio document; do not feed such a directory into this editing loop
or claim that it is resumable. Use `project create` for new work intended for
external-AI continuation. No automatic migration of old run-only projects is implied.

## Read the saved project

```bash
skill/scripts/sciplot project inspect PROJECT --json
skill/scripts/sciplot project inspect PROJECT --figure FIGURE_ID --json
```

Use `project` from the first result as the canonical project path. Obtain
FIGURE_ID from `figures[].figure_id`; for the primary figure use the returned
`primary_figure_id`, not the literal word `primary`. The summary is read-only
and does not load native objects or regenerate figures. It accepts a project
directory, `plot_request.json`, registered canonical VSZ, or a still-associated
delivery. A moved/copied portable delivery cannot silently select its old owner.

The explicit figure inspection returns `selected_figure.objects`, indexed by
absolute native object paths, with `settings`, `editable_fields` and `target`.
Read the particular field's `setting_path`, `current_value`, editor and bounds.
The target's `document_sha256` identifies the saved VSZ version. These are native
paths and saved-byte identities; do not invent UUIDs or use a GUI changeset.
To limit output after identifying an object:

```bash
skill/scripts/sciplot project inspect PROJECT --figure FIGURE_ID --object OBJECT_PATH --json
```

Inspect and visually review the exact saved figure when needed:

```bash
skill/scripts/sciplot project preview PROJECT --figure FIGURE_ID --out NEW_PREVIEW_DIRECTORY --json
```

Read the returned PNG. Each preview `--out` must be a **new**, dedicated directory
outside the source, project and visible delivery; do not reuse an old preview
directory. A preview is not a PDF/TIFF publication or a new ready result.

## Preview an authorized style edit

Write CHANGES_JSON as a JSON list. Use the exact paths and expected values from
the most recent figure inspection. For example, **only if inspection actually
advertises these paths and the current value is `8pt`**, a change to `9pt` is:

```json
[
  {
    "object_path": "/page1/graph1/x",
    "setting_path": "/page1/graph1/x/Label/size",
    "expected_value": "8pt",
    "value": "9pt"
  }
]
```

```bash
skill/scripts/sciplot project edit-preview PROJECT --figure FIGURE_ID \
  --expected-document DOCUMENT_SHA256 --changes CHANGES_JSON \
  --out NEW_EDIT_DIRECTORY --json
```

This stages native edits and a PNG, then audits the candidate's scientific
contents against the current spec. It does not replace the saved document.
Review the returned `actual_changes`, scientific audit and preview image.
Current capability scope covers the advertised axis typography, ordinary sample
line/marker/direct-label color, line width, and legend typography/placement fields. It excludes data,
expressions, scientific labels/units, axis scales/bounds, sample identity and
semantic color encodings. An unadvertised field is unavailable, even if native
Veusz has such a setting. Do not substitute text patches, arbitrary Python or
GUI automation for rejected operations.

Existing user authorization for a concrete style change is sufficient. Ask only
when intent, scientific meaning or scope is unresolved. Keep the complete
`edit-preview.json` unchanged; it binds the request, source, project, delivery
and candidate evidence and is the input to apply.

## Native reference lines, arrows and observed peaks

Read the exact closed operation schema in `project capabilities` and current
annotation IDs, axes units and bounds:

```bash
skill/scripts/sciplot project annotations PROJECT --figure FIGURE_ID --json
```

For example, only when the actual x-axis unit is `nm`, OPERATIONS_JSON may contain:

```json
[
  {"op":"add_reference_line","id":"reference450","parent_path":"/page1/graph1",
   "axis":"x","value":450,"unit":"nm"},
  {"op":"add_annotation","id":"note1","parent_path":"/page1/graph1",
   "text":"Observed feature","position":{"mode":"relative","x":0.75,"y":0.8},
   "arrow_to":{"mode":"axes","x":450,"y":4,"x_unit":"nm","y_unit":"a.u."}}
]
```

Coordinates above are examples, not inferred measurements; use current inspected
units and a real requested target. Positions are axis data coordinates or graph
fractions; no arbitrary expressions or pixels. Reference lines and text styles
use shared policy. This first operation set supports ordinary Cartesian curves,
including point_line/stacked_curve, and the native graph x/y axes. Schema-rejected
settings are unavailable even if the underlying Veusz widget supports them.

```bash
skill/scripts/sciplot project operations-preview PROJECT --figure FIGURE_ID \
  --expected-document SHA256 --operations OPERATIONS_JSON --out NEW_DIRECTORY --json
```

Use the returned preview with the same `project edit-apply` service, or place the
operations in a task edit request to have apply and export handled locally after
review. Document and annotation spec are replayed, audited, archived and committed
together; raw scientific arrays and unrequested settings remain unchanged.

For observed peaks, WINDOW_JSON is `{"min":400,"max":500,"unit":"nm"}`:

```bash
skill/scripts/sciplot project peaks PROJECT --figure FIGURE_ID --object OBJECT_PATH \
  --expected-document SHA256 --window WINDOW_JSON --polarity maximum --json
```

Use the returned complete `candidate` in `{"op":"add_peak_label","id":"peak1",
"candidate":CANDIDATE}`. Candidates are unsmoothed strict discrete interior
extrema; boundaries, plateaus, duplicate x coordinates, hidden curves and
out-of-axis points are excluded. Choose `minimum` only when the user's experiment
semantics calls for it. No candidate is a chemical/phase assignment. A changed
series or invalid candidate is rejected, never silently rebound.

To change/delete an existing annotation pass its inspected `id` and complete
`expected_annotation` to `update_annotation`/`remove_annotation`; an update takes
a schema-valid add operation as `replacement`. Source revisions use the reviewed
fixed-annotation and peak-rebinding task described above. Do not strip spec
metadata or bypass the source-update guard.

## Apply, recover a reply, and export

The following common apply also accepts the annotation operation previews below.

```bash
skill/scripts/sciplot project edit-apply PROJECT --preview NEW_EDIT_DIRECTORY/edit-preview.json --json
skill/scripts/sciplot project operation PROJECT --operation-id OPERATION_ID --json
```

Take OPERATION_ID from the edit preview/apply output. Apply recomputes the
allowed native operations, checks the preview against current state, archives
the previous VSZ, and replaces the selected canonical document with rollback
on ordinary failure. A stale request, source, figure, delivery or expected value
requires a new inspection and preview. Never modify the old preview to make it
pass. An unmerged visible VSZ remains a separate recovery concern.

If the success reply was lost, query `project operation` and inspect
`status`, `result_is_current`, `document_sha256` and `result_sha256`.
Retrying the same unchanged preview may return `already_applied` when its saved
result and recovery evidence still match. If a later edit changed the document,
the old apply is rejected. This is bounded recovery of this edit, not a general
exactly-once task engine. A missing or pending outcome is not a success claim.

Apply does not export. Publish the exact-current complete project:

```bash
skill/scripts/sciplot studio PROJECT --export pdf,tiff_300 --json
skill/scripts/sciplot project inspect PROJECT --json
```

Require `studio_run.ready_to_use=true`, current QA, and the complete source-adjacent
package. Inspect the final PDF/TIFF appearance as part of handoff. All registered
figures are included by the managed export use case, even when only one figure
was styled.

## Comparing alternatives of the same saved figure

Use `task compare` to explore 2–8 explicit operation batches against one saved
figure. Start from [the comparison manifest](figure-comparison.json), replacing
its project, figure ID, SHA and sample names with values from `project inspect`.
Each candidate has a unique `id` and `label`, optional short `rationale`, and
ordinary advertised `operations`. These are alternatives for the same data and
saved figure; chart-type conversion and automatic scientific transformations
are not introduced. The external AI proposes and judges alternatives. SciPlot
does not invoke a model or independently invent a winning design.

```bash
skill/scripts/sciplot task compare capabilities --json
skill/scripts/sciplot task compare start --request CANDIDATES_JSON --comparison-dir NEW_DIRECTORY --json
skill/scripts/sciplot task compare inspect COMPARISON_DIRECTORY --json
skill/scripts/sciplot task compare resume COMPARISON_DIRECTORY --json
```

The comparison directory must be outside the source, managed project and
delivery. CLI project/preset paths resolve beside the manifest. MCP paths
resolve against the server working directory. One immutable request captures a
full project/delivery baseline and creates separate native edit tasks with
export disabled. Creating and inspecting candidates never applies them. A
failed candidate does not prevent viewing or choosing another valid one.

Read the original and candidate PNGs from `previews` or the local `overview`.
Each candidate reports its operation ID, science-audit status, change count and
the first 12 factual setting differences; `review_path` contains the full native
review. A `rationale` is caller-supplied intent, not a measured quality score.
`baseline_current`, `selectable` and `comparison_id` describe the current choice
context. Changed candidate artifacts are unavailable; changed project/data/
delivery state requires a new comparison. Inspections reuse the stored images
and never launch a renderer. `resume` retries pending/failed generation; already
generated candidates are retained and no candidate is chosen automatically.

The read-only page can enlarge an image and compare one candidate beside the
original, switching candidates locally. Expand a candidate's choice note to
copy its directory, candidate ID and expected comparison ID back to the AI
assistant. This is text handoff only: re-inspect the comparison, verify that the
copied ID and selectable state still match, then use the normal selection
service. A stale or already selected comparison offers no new choice note.
Current saved-project source/export/delivery indicators are distinct from the
comparison images. The timestamp is the last query time; browser refresh alone
does not inspect the project. Re-run `task compare inspect` to update the page.

After visually comparing, send one selection using the returned comparison ID:

```json
{"candidate_id":"strong","expected_comparison_id":"CURRENT_COMPARISON_SHA256"}
```

```bash
skill/scripts/sciplot task compare select COMPARISON_DIRECTORY --selection SELECTION_JSON --json
```

Use `candidate_id:"baseline"` to keep the original. Selection is frozen before
the native transaction begins; identical retries or `resume` recover that same
choice after an interrupted reply. A second, different selection is rejected.
Unchosen edit tasks are never accepted by the comparison owner. Their previews
remain historical evidence after application. An unchanged candidate requires
no document write. The default `export:false` saves the chosen edit for continued
work; `export:true` in the original manifest adds one ordinary export task after
selection, with recovery that does not reapply the edit. A saved choice does not
certify publication; inspect `current_evidence` and export for delivery.

MCP exposes `sciplot_comparison_start`, `sciplot_comparison_inspect`,
`sciplot_comparison_resume` and `sciplot_comparison_select`. Start takes `request`
and `comparison_dir`; subsequent calls take `comparison`, and select adds the
same `selection` object. Results include `preview_resources`, keyed by
`candidate_id` (`baseline` names the original). A new connection can inspect the
comparison and obtain fresh resource URIs without regenerating candidates.

## Experiment groups and collective previews

Use an explicit list of 1–32 independent experiments. Every item has a unique
`id`, a display `label` and an ordinary create/edit/export `request`. Grouping
does not infer that similar filenames identify the same sample or experiment.
Start from [the example manifest](experiment-group.json).
Copy that manifest into a working directory beside your data, then replace its
source/output paths with your confirmed input locations. Relative paths in the
CLI manifest resolve beside that file; MCP paths resolve against its server's
working directory, so prefer absolute paths over MCP.

```bash
skill/scripts/sciplot task group capabilities --json
skill/scripts/sciplot task group start --request EXPERIMENTS_JSON --group-dir NEW_GROUP_DIRECTORY --json
skill/scripts/sciplot task group inspect GROUP_DIRECTORY --json
skill/scripts/sciplot task group resume GROUP_DIRECTORY --json
```

The group directory must be outside every input, project and delivery. Each item
needs independent destinations; overlapping outputs and malformed requests are
rejected before the group is created. Each child uses the existing task owner.
An item with a question, failed task or pending preview leaves other items free
to finish. Running tasks recover through their existing bounded retry logic;
uncertain creation is never overwritten. Calling start again with the same
manifest/directory returns the existing group, and completed tasks do not rerun.

The returned `overview` opens a local read-only gallery with one card per figure.
`previews` contains the exact native PNG paths, hashes and saved/candidate scope.
MCP `sciplot_group_start`, `sciplot_group_inspect` and `sciplot_group_resume`
return `preview_resources` indexed by item and figure. Read selected PNGs using
`sciplot_read_result`. Unchanged saved figures reuse cached previews; changing a
document or spec requires a new snapshot. The group reports current input and
project evidence separately from historical completion. It does not certify
aggregate readiness or imply that the gallery is a publication layout.

The gallery supports local search by experiment, figure or exact sample text,
attention filtering, image enlargement, and copying known source, saved VSZ and
delivery paths. "Needs attention" includes incomplete tasks, unavailable
previews and stale or unknown source/export/delivery evidence; a completed task
alone cannot clear that filter. Candidate images remain marked unsaved even
when the currently saved project's delivery is current. Re-run `task group
inspect` to refresh the query snapshot; browser interactions do not run tasks.

Optionally include a top-level `sample_style_preset` object with the `preset`
path and `expected_preset_sha256` from style capture. This applies to create
requests only and requires exact preset coverage of each figure's ordinary
samples. The runner creates reviewed per-figure edit tasks with `export:false`
and exports each changed project once after its style tasks finish. A project
with several figures progresses sequentially under existing revision guards;
it may need more than one round of preview responses. An already matching
style finishes without acceptance or another export.

Supply answers as a JSON array with each current item and child task bound:

```json
[{"item_id":"ftir","task_dir":"CURRENT_CHILD_TASK_DIRECTORY","response":{"accept_preview":true,"expected_operation_id":"CURRENT_OPERATION_ID"}}]
```

Pass it with `task group resume GROUP_DIRECTORY --responses RESPONSES_JSON
--json` or MCP `group_resume.responses`. Ordinary rule choices, retries and
preview revisions use the same response field. All group preview acceptance
or rejection responses require `expected_operation_id`. Inspect the actual
images before accepting; existing user intent provides authorization. Old
task-directory responses cannot advance a later figure. Resume without answers
continues pending work and never chooses rules or accepts previews automatically.
Individual child tasks can also be inspected through the existing task API.

## Reuse sample styles across figures

Capture the actual saved colors and line widths of ordinary curves:

```bash
skill/scripts/sciplot project style-capture PROJECT --figure FIGURE_ID --out NEW_PRESET_DIRECTORY --json
```

Optional repeated `--sample E0 --sample E2` captures a subset; the default captures
all unambiguous ordinary samples. The result returns `preset`, `preset_sha256`,
sample labels and captured values. MCP exposes `sciplot_sample_style_capture` with
the same `project`, optional `figure_id`/`samples`, and `output_dir` arguments.
Capture audits the saved source figure and does not edit or export it.

Use the returned file and fingerprint in a target figure's task edit or
`project operations-preview` batch:

```json
[{"op":"apply_sample_style_preset","preset":"/absolute/path/sample-styles.json","expected_preset_sha256":"PRESET_SHA256"}]
```

The target request still needs its current saved document hash. Matching uses
exact sample names, so reversed series order or a different experiment family
does not move the colors to other samples. The default requires preset coverage
for every ordinary target sample. Add `"samples":["E0","E2"]` for an explicit
subset; unselected curves retain their styles. Extra preset samples need not
exist in the target. Missing/ambiguous labels, semantic color encodings and
changed preset bytes are rejected. The ordinary 100-expanded-operation limit
still applies. Line width counts as one operation per sample; sample color counts
once for the line, twice more for visible markers, and once more for a bound direct
label when present. The preview lists these individual changes.

Presets contain only sample colors/line widths plus historical source metadata.
Applying color keeps each target sample's line, visible markers and uniquely bound
generated direct label consistent, including when the target uses a stacked curve.
They do not copy plotting values, units, axes, annotations or layout, and applying
a preset does not reopen its original project. Preview freezes the matched
values into the existing signed native operations. Later changes to the preset
cannot change an already reviewed application. Inspect the image/audit and use
the usual task acceptance; `export:false` supports continued editing. An already
matching audited style batch completes as unchanged.

## Resume in a new AI session

For a local task retain TASK_DIRECTORY and query `task inspect` first. Only
continue the pending operation; do not recreate its source or reuse old resource
URIs from another MCP connection.

Retain PROJECT, the user's task, and any relevant operation ID or preview path.
A new process or conversation repeats `project capabilities`, `project inspect`
and, when editing, the explicit figure inspection. It reads the saved document
and durable outcome; it does not need previous chat state, a GUI selection or
an in-app AI provider. Continue from the current returned SHA, not a remembered one.

Inspection `status=ok` means the query succeeded. Its `ready_to_use=null` and
`readiness_evaluated=false` are deliberate. `last_run.recorded_ready_to_use`
is historical; `source`, `qa` and `delivery` report separate current byte-binding
indicators and may be unknown or stale. They do not perform a new scientific
audit, certify a build, inspect unsaved native changes, or replace final visual
review. Edit and preview success likewise do not claim a deliverable is ready.

Read stdout JSON and the exit code together. Runtime errors use the public
JSON failure envelope; usage errors may still be argparse text. Stop on a
blocked/error result and report its actual cause instead of treating an output
path or an earlier successful run as evidence that the current task succeeded.
