---
name: sciplot-materials-analysis
description: External AI control of deterministic scientific plotting, saved native Veusz projects, reviewed edits, QA, delivery and project continuation.
---

# SciPlot Materials Analysis

Use the public local CLI and shared contracts. External AI interprets the original
data and the user's intent; SciPlot validates and plots locally without calling a
model. Do not create one-off plotting scripts, replacement raw files, another
renderer or a second document model. Never patch VSZ text or automate Veusz clicks.

## Authority and routing

- Live CLI and source-controlled contracts are executable truth.
- `README.md` owns product behavior and the user workflow.
- This skill owns agent routing and verification.
- `docs/ARCHITECTURE.md` owns module and dependency boundaries.
- `DEVELOPMENT_ROADMAP.md` lists unfinished priorities.
- Development logs and Git are history, not current instructions.

For an explicit AI-prepared rheology suite, go directly to the rheology route in
Scientific and delivery boundaries below. Start that route with `doctor --json`
and `rheology capabilities --json`; its request and continuation use that contract.

For ordinary plotting, use the short loop below. Do not pre-read architecture,
development history, all rule definitions or the entire advanced guide.
For exact fields, request only the current capability section needed.
Read [external-control.md](references/external-control.md) for a particular
operation or recovery detail. Read [advanced-workflows.md](references/advanced-workflows.md)
only for edits, source updates, groups/comparisons, legacy diagnostics, or development.

## Ordinary plotting: one task

1. Run `skill/scripts/sciplot doctor --json`; require `status=ready`.
   Check readiness and `task capabilities --json` together at session start.
   Keep successful readiness output compact; inspect failed checks if any.
   Reuse capabilities until their contract fingerprint changes. Fetch schemas
   with `--section`, `--name`, and `--expected-contract`; avoid `--full`
   unless the current decision needs it.

2. Write the create request to a JSON **file**, then run:

   ```bash
   skill/scripts/sciplot task start --request REQUEST_JSON_FILE --json
   ```

   Request shape: `{"version":1,"action":"create","source":"/absolute/original"}`.
   `out` is a request field; prefer CLI `--task-dir` for the task location.
   A misplaced JSON `task_dir` is automatically relocated unless it conflicts.
   Output conflicts return an `out` question before planning; choose a new path
   in the same task or inspect the existing project. Never move old deliveries.
   Specify `rule_id` and `template` only from known scientific intent.
   The task owns recognition, planning, native creation, QA and export. Separate
   inspect/rules/plan/project-create/studio calls are not prerequisites.
   If the original table is already understood, include `create.mapping`
   with its original file SHA, row selections, metadata evidence and XY pairs.

3. When the response needs input, use its bounded original cells, dimensions,
   numeric extents and rejection reasons. The program automatically repairs
   a single explicit axis/unit/sample-row layout through ordinary validation.
   Numeric extents alone are not selected data; do not remove missing rows,
   infer units from magnitudes or choose between different sample conditions.

   If `mapping_candidates` is present, review its original note, rows, columns,
   units and samples. Reply with `expected_question_id` and `mapping_candidate_id`;
   optional `pair_indices` selects/orders the listed samples. The program expands
   the source-bound declarations. Do not transcribe those declarations again.
   This is an AI-reviewed suggestion, not an automatic choice of sample conditions.

   When no candidate fits, send **one complete answer** to a rule/table/column question:
   `expected_question_id` plus `mapping` containing `source_sha256`,
   `table_selection`, optional `metadata_confirmations`, and
   `column_mapping:{"pairs":[{"x_column":0,"y_column":1,"label":"sample A"}]}`.
   Include `rule_id`/`template` if the experiment is still a question.
   Each pair can have its own rows, worksheet, and metadata declarations.
   Indices are zero-based; `data_end_row` is exclusive.
   Labels are display names; original sample/column evidence remains recorded.

   ```bash
   skill/scripts/sciplot task resume TASK_DIR --response ANSWER_JSON_FILE --json
   ```

   A wrong choice returns the current question and `mapping_error`; correct it
   in the same task. An interrupted pending answer supports `{"retry":true}`.
   Wire errors return `repair.issues` with field paths and constraints; response
   errors include `repair.question` and `repair.next_step`. Correct those fields
   and use the returned current bindings directly; no extra inspect/help call.
   `repair.question_unchanged=true` reuses the already returned evidence and sends
   only the question reference; stale/missing bindings return current evidence.
   Stepwise table/metadata/column answers remain compatible. Do not split files,
   try unrelated plotting commands, inspect source code, or recreate projects
   to work around a table question. If original evidence is insufficient, ask
   only for the missing scientific meaning. The program cannot settle that fact.

   Original-cell declarations can cite another sheet in the same original
   workbook. External excerpts and actual user statements remain attributed.
   Never claim that an inference was an original cell or a user statement.
   `task table-region` reads more original cells when needed. Do not send
   thousands of measurement values into AI context or transcribe them back.

4. At `next_step.action=review_exports_and_deliver`, view the returned TIFF
   images and hand off. The completed response already has fresh source/QA/
   delivery evidence, figure IDs and document hashes. An unchanged result
   needs no extra query, preview, or export. Read `--full` only for a specific
   missing detail. No tests, smoke, or acceptance runs during ordinary plotting.
   Include the returned `next_step.manual_edit` entry when handing off: the
   default human adjustment surface is `Open_in_SciPlot.command`. In its canvas,
   Save updates the managed VSZ; Save and update delivery also refreshes the
   delivered VSZ/PDF/TIFF through existing QA. Retain Veusz as the advanced and
   portable-copy fallback. Opening an old delivery must not rewrite its package;
   its next normal export adds the new launcher.

5. In a later session, resume the returned task/project and query current state.
   Use `task find SOURCE --json` if only the original path is known; multiple
   matches or incomplete searches do not establish one unique project.
   Historical receipts are not current readiness. Source changes and uncertain
   interrupted creation must not trigger silent overwrite or a second creation.

The shared XY recovery supports ordinary paired curves and FTIR. Specialized
scientific adapters retain their own contracts; never convert their data into
another experiment just to pass validation. `local_timing` measures local active
calls only. Output bytes are not external AI token counts or end-to-end latency.

## Scientific and delivery boundaries

For the explicit HDPE/LDPE UDC TTS suite, use the specialized
`sciplot rheology plot --request REQUEST.json --json` route described in
`docs/RHEOLOGY_TTS.md`. Read `rheology capabilities --json` for its live contract.
AI owns data processing, calculations, scientific purposes and the source-bound
prepared numerical plan, including units, transforms and series roles. The local
program validates that plan and draws its supplied values with governed templates;
the `plot` entry point must not run analysis or refit the data. Its request contains
`version: 1`, an absolute `prepared_plan` JSON path, and optional `out` and
`expected_contract_sha256`. Use the advertised closed request/plan contracts.
Creation replies are compact by default; complete native evidence remains at
`full_evidence_path`. Read that file when needed instead of creating the suite
again. `rheology plot` and compatibility `rheology tts` accept `--full` for a
full creation reply. Preview/apply replies retain their existing revision bindings.
The older combined `rheology tts` utility remains for compatibility, not as the
recommended new-work route. Measured/derived traces use points with guide
lines, TTS observations use points, and regression predictions use lines.
Do not suppress measured-point markers or hardcode physical sizes just because
a generic curve example does so. Preserve intentional user encodings and the
distinction between observations, fits, reference lines and bars.
The separated plan creates independent documents and retains fit diagnostics;
legacy combined documents remain supported. Its launchers use the native Veusz
editor. For authorized style corrections, run `rheology style-preview WORKSPACE
--json`, inspect the returned current-document/source/spec-bound preview, then
`rheology style-apply WORKSPACE --preview PREVIEW_JSON --json`. An already
authorized correction needs no additional human confirmation. Stale bindings
require a fresh preview. Review the candidate native export images; apply publishes
those exact accepted candidates as a bounded template-style migration, without
arbitrary custom-style input. Do not regenerate data or reapply an accepted edit
for an export retry. Use `rheology export` for exact saved re-export: it reports style
deviations while preserving saved native edits. This route does not claim the
ordinary browser canvas or strict thermorheological simplicity.
For an interrupted new prepared creation, read the first failure’s `repair` guidance.
When its action is `resume_prepared_creation`, run its returned command using the
same request (`rheology plot --request REQUEST.json --resume --json`).
For `inspect_creation_evidence`, preserve the indicated request/workspace/checkpoint
and inspect the original error; do not issue a blind resume. Guidance validates
existing evidence without saving/exporting or attempting recovery itself.
Do not delete its workspace or recreate saved VSZ files. Resume rejects changed
bindings, uncertain native saves, and unknown older partial workspaces. Completed
or subsequently edited suites continue through exact saved `rheology export`.

Preserve raw cells, per-curve order/counts, identities, units and provenance.
Never invent measurements, average silently, pad/truncate ragged curves or
interpolate missing references. Unit conversion requires its own scientific
contract. Merged metadata expansion is explicit and applies only above data.
The saved `studio/document.vsz` is visual authority; use native Veusz operations.

For raw-input plotting, omit `--out` by default. Deliveries belong beside the
original source as `SOURCE_SciPlot/`; internal evidence belongs in the adjacent
hidden `.sciplot/` workspace. Do not put user plotting deliveries inside the SciPlot repository
or its `outputs/`. Development evidence belongs under ignored `.tmp_verify/`.
The visible package contains plotting CSVs, PDF/TIFF, editable VSZ and its launcher.

For native edits/source revisions, inspect candidate images and scientific audits
before accepting the current operation/revision ID. Existing user intent authorizes
those changes; preview review is not an extra mandatory user permission step.
An export retry must not reapply the change. Read the relevant advanced workflow.
Retained GUI/editor/Intake compatibility is not permission to delete those surfaces
or replace the external-AI product direction.

## Development verification

Read `docs/ARCHITECTURE.md` before changing owners. Fix the central owner and add
discriminating coverage. After two unsuccessful attempts at one symptom, stop
guessing: record cause, replacement contract, verification and limitations.
Use `.venv/bin/python` and `skill/scripts/sciplot`.

Run the smallest relevant tests while iterating, then:

```bash
skill/scripts/sciplot verify --changed --json
```

Unknown changed owners fail closed; do not compensate with a full-suite fallback.
Run the scoped static type gate when changing a file
declared under `[tool.mypy]` in `pyproject.toml`.
Its exact scope and strictness belong to `pyproject.toml`.
Do not weaken checks or remove coverage to pass a gate.

At handoff, run Doctor for command/runtime changes. Run smoke once at the final
milestone for changes crossing Studio, worker, export, QA, delivery or runtime.
Full pytest and ready-rule acceptance are release/merge gates, not every edit.
Runtime readiness, native fidelity, real-client efficiency, human usability and
journal acceptance are separate claims. See the advanced guide for exact commands.

For every non-trivial development turn, update `DEVELOPMENT_LOG.md` with the
change, current state, next steps and verification before reporting.
