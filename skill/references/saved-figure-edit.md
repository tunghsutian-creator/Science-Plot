# Saved ordinary figures: edit or export

Use the existing saved project for authorized labels/annotations, colors, widths,
axes and other advertised presentation edits. For a prepared rheology suite use
the prepared-rheology route instead. Ordinary editing needs no source-code,
architecture, development-log or test reading.

## Sample width or color: direct preview, then accept

For explicit width/color changes, call the typed entry directly:

```bash
skill/scripts/sciplot task style TARGET --all-samples --width 0.7pt --json
```

Use `--all-samples` only when all curves are requested. Otherwise use one or more
`--sample 'Exact label'` options; labels must match exactly. `--color '#336699'`
may replace or accompany `--width`. `--figure FIGURE_ID` selects a known figure.
The program checks runtime readiness, resolves current targets and document SHA,
constructs the existing operation and returns its audited native preview.
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

## Other edits: context, preview, accept

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
