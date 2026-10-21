# Saved ordinary figures: edit or export

Use the existing saved project for authorized labels/annotations, colors, widths,
axes and other advertised presentation edits. For a prepared rheology suite use
the prepared-rheology route instead. Ordinary editing needs no source-code,
architecture, development-log or test reading.

For a saved ordinary original-table categorical figure, use
[categorical display edits](categorical-presentation-edit.md) for category aliases,
condition/metric colors, given-value marker styles or its represented native key.
That route reads the current source selectors and legal fields in one edit context.

## Preferred: one semantic transaction

Choose the first read from authority already established for this figure:

- **Known ManagedPlot:** call `skill/scripts/sciplot plot open TARGET --scope
  summary --json`, or `sciplot_project_open` with `{"target":"/absolute/target",
  "description":{"scope":"summary"}}`. This returns `plot`, `plot_id`,
  `revision`, hashes, currentness/authority warnings and `edit_targets` with
  stable IDs, kind, label and advertised property names, without the full
  template and schema payload. Reuse it for the current session.
- **Unknown authority or known LegacyPlot:** call `plot open TARGET --json`, or
  `sciplot_project_open` without `description`, once. Inspect `plot_type` and
  `coverage`. Reuse that full result even if it reveals a ManagedPlot; do not
  immediately read it again as a summary. A LegacyPlot stays under its full
  description and explicit `legacy_shadow` coverage; scoped edit and typed
  intent are unavailable. Do not convert it merely to use the compact route.

Before a new edit, check `status`, `changed_inputs`, `artifact_status`,
`pending` and `next_step` in the current result. Follow a stale, dirty, changed
native, or pending continuation first; neither a compact read nor an
`intent_class` bypasses those guards. Do not query native paths or hashes just
to repeat current evidence.

For a current ManagedPlot summary, select an exact ID/property from
`edit_targets`. For edits except the FigureSpec v2 text shortcut below, read
the chosen current value and schema with `skill/scripts/sciplot plot describe PLOT --scope
edit --target-id ID --property NAME --json`, or `sciplot_plot_describe` with
`{"plot":"/absolute/plot","description":{"scope":"edit","target":"ID",
"property":"NAME"}}`. Scale domains and axis ticks include scientific
unit/scale context; `scale.domain` has scientific risk. Use the returned
contract and revision for the existing `plot.patch`; never guess a property,
target ID, value type or scientific meaning. Request full `plot describe`
only when the compact result lacks information needed for the authorized edit.
If the first open was full, use its returned object values and edit contract
instead of requesting the same information again.

For an exact ManagedPlot FigureSpec v2 `axis.label` or `annotation.text` change,
use the [typed `plot.intent` route](../../docs/plot_typed_intent.md) after the
current summary or full description. Its read-only plan supplies the current text, risk, unit/anchor context
and the exact patch request; a separate scoped edit read is unnecessary. Apply
with the same identity/revision/key after reviewing the plan. This compiles to
the same semantic patch transaction below, not a new editing authority.

Send `sciplot_plot_patch` with `plot` and this request, substituting the returned
plot identity, current revision and exact authorized targets:

```json
{"plot_id":"returned-id","base_revision":0,"idempotency_key":"width-edit-1","intent_class":"presentation","changes":[{"op":"set","target":["series:E2","series:E4"],"property":"style.line.width","value":"0.7pt"}]}
```

The CLI equivalent is `plot patch PLOT --request REQUEST.json --json`. Use one
stable key per user intent; retransmit the identical request after an uncertain
connection. New intent uses a new key and current revision. A supported managed
title uses `title.visible=false` with its returned title ID. Never guess IDs for
an opaque or unsupported object. The engine computes risk; `intent_class` cannot
authorize a scientific change.

For `status=complete` and `ready_to_use=true`, the native numerical audit and
publication checks already passed. View the final TIFF and deliver the returned
files; no extra candidate screenshot/audit/export loop is needed. A `needs_review`
reply contains the one candidate and a bound `plot.decide` request. Review it and
submit the requested decision under the existing user authorization.

Source/native changes return a conflict with relevant paths. Do not regenerate
from the old spec. For a native-only manual save, `plot.describe` may return a
frozen reimport request. Submit it, inspect its single audited preview, then accept
the bound decision; the engine preserves native bytes and stable IDs. Changed
science/specification or object membership is not eligible for this shortcut.
`export_pending` retains the committed revision; repeat the
same request or use `plot export PLOT --json`, never create another edit to retry
an export. Failed unapplied previews may advertise a bound discard request before
correcting the intent. Unknown or uncertain applied work cannot be discarded.
`plot rollback` appends a revision using target_revision/base_revision and a new
idempotency key. Full diagnostics/history stay at returned local references.

Imports currently retain `legacy_shadow` coverage. Their represented widths,
colors, fonts, managed titles/annotations and advertised axis/legend properties use this path;
other changes use the compatibility route below. Scientific mapping/normalization/
fitting need their explicit scientific owner and cannot be presentation patches.

For a new original table in the same existing Managed XY figure, use the
advertised [`source.append` scientific contract](source-append.md).
Its metadata-only clarification supplies original table facts before the same
revision/idempotency/preview/accept transaction; it does not recreate the figure.

## Common palette, typography and legend edits

For an authorized common edit, call the bounded entry directly:

```bash
skill/scripts/sciplot task edit TARGET --intent '换配色 tol_bright；统一字号 9pt；图例字号 7pt' --task-dir STABLE_EDIT_DIRECTORY --json
```

English exact clauses (`palette tol_bright; font size 9pt; legend font size 7pt; legend columns 2`)
and explicit `--palette`, `--font-size`, `--font-family`, `--legend-font-size`,
`--hide-legend`/`--show-legend`, `--legend-columns 2` or `--legend-position X,Y` are also supported.
Read `task capabilities --section common_edit --json` only when the exact syntax
or authority coverage is missing. Unknown clauses reject the whole intent;
do not silently omit them or infer scientific changes. Palette capacity must
cover all selected series without cycling colors.

Managed FigureSpec v2 typography covers its represented theme, axes, legends,
annotations and text marks; an exact font family must be installed. Other
authority types expose their existing coverage. A LegacyPlot retains the complete
current VSZ; unsupported font or legend properties fail closed. Non-target
presentation and scientific state remain intact.

`legend.columns` is the typed equivalent of `--legend-columns`, with integer
values from 1 to 32. It changes the represented Managed legend or the advertised
Legacy native key; the existing location remains explicit. A layout/publication
conflict remains a returned review or error and never silently moves the legend.
The Legacy key advertises its native catalog's narrower range when applicable
(currently 1–12); use its returned capability.

Supply a stable `--task-dir` on the first call, and retain the returned
`edit_replay` arguments and idempotency key. Without that first stable path, a
lost reply cannot identify the unique original edit entry. Identical replay uses
the frozen original request and revision; pending work retains its original
continuation. Review a returned preview and follow its exact `next_step`.
Export retry resumes export without applying the edit again. The entry makes no
model calls; output bytes and local timing do not measure external AI tokens or fees.

## Display aliases and existing source members

For explicitly authorized display changes, use stable semantic IDs from the
current `edit_targets` (or an exact unique current/source label):

```bash
skill/scripts/sciplot task edit TARGET --rename-series 'series:A' 'Control A' --hide-series 'series:B' --task-dir STABLE_EDIT_DIRECTORY --json
skill/scripts/sciplot task edit TARGET --show-series 'series:B' --task-dir NEW_EDIT_DIRECTORY --json
```

Repeat these flags to batch changes; they may accompany explicit palette/font/
legend flags. `--rename-series SOURCE ALIAS` changes displayed text, preserving
the source sample identity. `--hide-series` removes only its visible membership;
`--show-series` restores a member already retained by that plot. At least one
member must remain visible. Arrays, independent lengths, duplicate points,
original order, units and source hashes remain bound, including hidden curves.
Adding an unbound source is a scientific source revision, separate from this edit.

For figures with auto/fixed endpoint rules, auto endpoints follow visible plotted
geometry; fixed endpoints keep the user's limits. Hiding and showing a retained curve can
therefore change an automatic window without changing its scientific identity.
An explicit numeric domain fixes both endpoints. The advertised rule object can
restore auto for either endpoint; automatic ticks follow the resulting window.
Manual ticks remain exact and an incompatible candidate is rejected atomically.
Older saved numeric windows remain fixed until an explicitly supported scientific
operation changes them. The scoped edit context includes the current numeric
domain and ticks alongside the editable rules.

For an authorized refresh of a changed original file, select its advertised
`source.sha256` target through the same summary/edit route. Read the complete
value and schema: the request must cover every binding of that physical file,
with fresh metadata declarations and retained coordinate/condition facts bound
to its new SHA. A bare digest is accepted only for the advertised safe legacy
case. Never copy an old declaration to a new SHA without checking its original
evidence, and never withdraw coordinates to bypass a mismatch. The engine reads
the selected original table and checks those facts before reserving a transaction.
Use the existing scientific patch, preview/decision and identical-key recovery;
this operation retains historical requests and does not replace original data.

The same typed patch properties are `series.display_label` and `series.visible`.
Managed FigureSpec v2 targets a layer ID; Legacy ordinary native curves target a
series ID under their advertised `legacy_shadow` coverage. Discover the exact
current value/schema through the normal `plot describe` route. Other legacy
objects retain their original native authority and opaque settings. Review a
returned candidate and follow its bound decision; reuse the original task
directory and identical flags for lost-reply recovery. Cold reopen, export retry
and `plot rollback` use the existing revision transaction.

For an explicit request to make dense glyphs reveal a connecting line, inspect
the current Managed point mark's `style` schema and preserve its other fields
while setting `marker_thin_factor` (an integer >=1), or `marker_opacity=0` for a
requested line-only display. These change marker presentation; all measurements
and line vertices remain intact. For a Legacy ordinary curve, `task edit-context
TARGET --operation set_style --json` advertises the native `marker` choice;
`none` is available only when a visible connecting line remains. Use that exact
current setting binding and the returned native edit transaction. Do not thin
datasets, line vertices or statistical points to satisfy a display request.

## Compatibility: sample width or color

For explicit width/color changes, call the typed entry directly:

```bash
skill/scripts/sciplot task style TARGET --all-samples --width 0.7pt --json
```

Use `--all-samples` only when all curves are requested. Otherwise use one or more
`--sample 'Exact label'` options; labels must match exactly. `--color '#336699'`
may replace or accompany `--width`. `--figure FIGURE_ID` selects a known figure.
The program checks runtime readiness, resolves current targets and document SHA,
constructs the existing operation and returns its audited native preview.
For already-imported figures this same command delegates to the semantic engine
and can return the final exported result immediately; follow that result directly.
No preliminary Doctor, capability, edit-context or request-file call is needed.
Empty or ambiguous targets remain errors; do not guess a sample or skip it.

View `preview.image` and read the actual changes/scientific audit, then use the
returned `next_step.cli_argv` with the normal SciPlot executable:

```bash
skill/scripts/sciplot task resume TASK_DIRECTORY --accept-preview --expected-operation-id CURRENT_ID --json
```

The ID must identify the preview just reviewed. The program constructs the bound
acceptance response; no acceptance JSON file is needed. Finish with the final
TIFF and returned current evidence as described below. This route normally needs
two plotting commands, plus candidate and final-image review.

## Compatibility: other native edits

Reuse current context, or fetch only the needed operations:

```bash
skill/scripts/sciplot task edit-context TARGET --operation OPERATION_NAME --figure FIGURE_ID --json
```

Both edit entries accept a task, project, delivery or registered VSZ. Omit
`--figure` for a single-figure target. Repeat `--operation` for a mixed batch
(`remove_annotation`, `update_annotation`, `set_style`, etc.). The context returns
readiness, schemas, targets and `request_template`; do not repeat discovery.
Unfinished tasks return their original continuation; continue them instead.

Fill `request_template.operations`, preserving project/figure/SHA and exact
annotation/native bindings. Save it and run `task start --request EDIT_REQUEST.json
--json`. Review the candidate/audit and use the same bound resume command above.
`--response FILE` remains available. An audited `unchanged` edit may complete
without a preview; follow its next step. Use `"export":false` only for intended
successive saved edits, reuse each returned SHA, then export once at the end.

At `review_exports_and_deliver`, view returned final TIFF `images`, require ready
export and current source/QA/delivery evidence, and deliver PDF/TIFF/editable VSZ
plus `next_step.manual_edit`. Visual review remains required. Success needs no
further query, audit, export or script. Read command output directly; do not save
and reopen receipts merely to build the next request. The task saves its own
durable records; extra client report files are unnecessary for ordinary plotting.

## Export only

For a known saved ordinary project, reuse current Doctor readiness or run Doctor
once if missing. Submit `{"version":1,"action":"export","project":"/absolute/project"}`
through `task start --request EXPORT_REQUEST.json --json`, then review and deliver
its final TIFF and evidence. `task edit-context` is unnecessary without an edit.
If only an old task is known, use `task inspect TASK --json` once to obtain its
current project and continuation. If only the source is known, `task find SOURCE
--json` can locate it; multiple matches do not establish a unique project.

## Bounded recovery

Use returned repair fields and current bindings directly. Correct only the
reported failure; read the external-control edit-recovery section only when its
detail is needed. A stable explicit `--task-dir` replays the same typed style
intent without applying it again; changed intent conflicts instead of reusing
the old preview. Do not invent a new task key to recover the same request.
The local task retries one terminated preview worker automatically, preserving
both attempts. A remaining timeout requires runtime recovery, not new operations.
For stale preview responses, view the newly returned candidate and audit before
accepting its current operation ID. Export failure resumes the same task with `task resume TASK
--retry --json` after resolving the reported cause;
never reapply the accepted edit for that retry. An uncertain apply follows its
recovery guidance before another mutation.

At `resolve_current_evidence`, read `evidence_gaps` and `current_project` already
returned. Another unchanged inspect cannot restore missing source bindings.
`result.figures` export paths still permit visual review, but unknown/stale evidence
must stay explicit until its specific cause is resolved. Do not recreate a project
or redraw/export simply to manufacture current evidence. A saved-only result is
not a publication receipt.
