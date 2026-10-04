# Saved ordinary figures: edit or export

Use the existing saved project for authorized labels/annotations, colors, widths,
axes and other advertised presentation edits. For a prepared rheology suite use
the prepared-rheology route instead. Ordinary editing needs no source-code,
architecture, development-log or test reading.

## Edit: context, preview, accept

1. Reuse already returned current identity, native targets and operation schemas.
   If any are missing, get the complete edit context in one call:

   ```bash
   skill/scripts/sciplot task edit-context TARGET --operation OPERATION_NAME --figure FIGURE_ID --json
   ```

   `TARGET` may be a task directory/task.json, project, delivery or registered VSZ.
   Omit `--figure` when only one figure exists; repeat `--operation` for the batch's
   operation names, such as `set_sample_style`, `remove_annotation`,
   `update_annotation` or `set_style`. This returns Doctor readiness, the selected
   operation schemas, current project/figure, native targets and `request_template`.
   Do not run separate Doctor, capabilities and project-inspect commands afterward.
   If the target is an unfinished task, follow its returned continuation instead
   of starting another edit. Missing/ambiguous targets require the specific choice.

2. Fill `request_template.operations` with the complete authorized batch and save
   it as JSON. Keep its `project`, `figure_id` and `expected_document_sha256`.
   Exact source-bound `sample_styles` labels support sample color/width batches;
   use returned annotation IDs/native fields for other edits. Start the task:

   ```bash
   skill/scripts/sciplot task start --request EDIT_REQUEST.json --json
   ```

   Leave export enabled for a finished edit. Use `"export":false` only for intended
   successive saved edits, reuse each returned saved SHA, then export once at the end.

3. At `needs_review`, view `preview.image` and read actual changes and scientific
   audit. Save `next_step.response_template` as the acceptance JSON and resume:

   ```bash
   skill/scripts/sciplot task resume TASK_DIRECTORY --response ACCEPT.json --json
   ```

   The response is `{"accept_preview":true,"expected_operation_id":"CURRENT_ID"}`.
   Existing user intent authorizes acceptance after this review. The continuation
   applies and exports the accepted candidate. An `unchanged` edit may complete
   without a preview; follow its next step instead of forcing another edit.

At `review_exports_and_deliver`, view returned final TIFF `images`, require ready
export and current source/QA/delivery evidence, and deliver PDF/TIFF/editable VSZ
plus `next_step.manual_edit`. The normal route uses context/start/resume; visual
review remains required. Success needs no further query, audit, export or script.

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
detail is needed. Export failure resumes the same task with `{"retry":true}`;
never reapply the accepted edit for that retry. An uncertain apply follows its
recovery guidance before another mutation.

At `resolve_current_evidence`, read `evidence_gaps` and `current_project` already
returned. Another unchanged inspect cannot restore missing source bindings.
`result.figures` export paths still permit visual review, but unknown/stale evidence
must stay explicit until its specific cause is resolved. Do not recreate a project
or redraw/export simply to manufacture current evidence. A saved-only result is
not a publication receipt.
