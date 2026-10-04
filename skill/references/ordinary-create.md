# Ordinary plotting: one task

Use this route for new ordinary plots from original data. The local task owns
recognition, planning, native creation, QA and export. Separate inspect/rules/plan/
project-create/Studio commands, repository reading and tests are not prerequisites.

1. Reuse Doctor readiness and the compact capability index for the current session.
   If missing, run `skill/scripts/sciplot doctor --json` and
   `skill/scripts/sciplot task capabilities --json` together; require `status=ready`.
   Inspect failed checks only. Fetch a missing schema with `--section`, `--name`
   and `--expected-contract`; avoid `--full` unless a specific decision needs it.

2. Save the create request as a JSON file and start one task:

   ```json
   {"version":1,"action":"create","source":"/absolute/original"}
   ```

   ```bash
   skill/scripts/sciplot task start --request REQUEST.json --json
   ```

   `out` is a request field; prefer CLI `--task-dir` for the task location.
   A misplaced JSON `task_dir` is relocated unless it conflicts. Output conflicts
   return an `out` question: choose a new path in the same task or inspect the
   existing project; never move old deliveries. Specify `rule_id` and `template`
   only from known scientific intent. If the original table is already understood,
   include `create.mapping` with its original file SHA, row selections, metadata
   evidence and XY pairs rather than rediscovering the same table.

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
   sample/column evidence remains recorded.

   ```bash
   skill/scripts/sciplot task resume TASK_DIRECTORY --response ANSWER.json --json
   ```

   Correct `mapping_error` in the same task. An interrupted pending answer accepts
   `{"retry":true}`. Wire errors return `repair.issues` field paths/constraints;
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
