---
name: sciplot-materials-analysis
description: External AI control of deterministic scientific plotting, saved native Veusz projects, reviewed edits, QA, delivery and project continuation.
---

# SciPlot Materials Analysis

Use the repository CLI and shared contracts. Do not create one-off plotting
scripts, copy style constants, or introduce another renderer, document model,
or editor.

## Authority

- `README.md` owns product behavior and the user workflow.
- This skill owns agent routing and verification.
- `docs/ARCHITECTURE.md` owns code, module, and dependency boundaries.
- `DEVELOPMENT_ROADMAP.md` contains unfinished priorities only.
- `AGENTS.md` is a thin local overlay; it must not redefine this workflow.
- `DEVELOPMENT_LOG.md` and Git are history/evidence, not current instructions.

When prose conflicts, verify the live CLI and source-controlled contracts, then
repair the stale document. Never revive an older route from historical notes.

## Product boundary

External AI is the task interface and the sole direction for further product
development. Use the public local CLI and existing shared services; SciPlot
does not need to host the caller's model or start an internal AI provider.
`studio/document.vsz` is the saved visual authority. Headless edits use the
native Veusz API, never a second renderer, document model or GUI selection.

Veusz `MainWindow`, Project/selected-object AI docks and browser Intake remain
compatible tools. Their retention does not make GUI workflows the development
priority. Do not delete these surfaces as part of ordinary external-control work.

The browser `app` is limited to initial source, grouping, naming, order, size,
and export confirmation plus read-only result review. Post-render edits use
native document operations through the external control services or the
compatible Veusz editor. Do not automate Veusz with mouse clicks or patch VSZ text.

Internal provider absence must not disable deterministic recognition, plotting,
native editing, QA, export, or delivery. The external AI may use only the current
advertised native editing capabilities. The retained in-app assistant remains
limited to the selected object; that GUI-specific restriction does not apply to
the explicit saved-figure/object references in the external API.

## Primary workflow

1. Check readiness:

   ```bash
   skill/scripts/sciplot doctor --json
   ```

   Require `status=ready`.

2. Read the external-control contract. Follow
   [references/external-control.md](references/external-control.md) for the
   complete public CLI loop, examples and recovery behavior:

   ```bash
   skill/scripts/sciplot project capabilities --json
   ```

   Prefer the complete local `task` route for supported create/edit/export work:
   `task capabilities → task start --request REQUEST_JSON → task inspect/resume`.
   The local runner owns recognition, fresh source-bound planning, creation,
   reviewed native edits and publication; it never invokes a model. Use
   `needs_input` only for the actual exposed rule-selection question, and
   inspect the candidate image before accepting a `needs_review` preview with
   `{"accept_preview":true}`. Existing user intent authorizes that change;
   preview acceptance is not an additional mandatory user permission step.
   Reuse the returned task directory in a new session. A completed receipt is
   historical; check current source/QA/delivery before later handoff. Source
   changes, unsupported mappings and uncertain interrupted creation fail closed.
   If only the original source path is known, use `task find SOURCE --json`
   to recover creation receipts from its adjacent history, or provide
   `--tasks-root` for a custom history directory. Inspect the chosen task/project;
   incomplete searches and multiple matches do not establish a unique project.
   `task inspect` includes current figure IDs, saved document hashes and sample
   labels under `current_project`; reuse those for the next supported task.
   Query native object settings only when the requested operation needs them.
   The MCP stdio adapter exposes the same services and schemas; read full JSON
   and PNG resources only as needed. See the operation guide for exact fields.

   For successive edits use `export:false` on the task edit request. After
   accepting the preview, use the returned saved document SHA for the next edit;
   export once when requested. A completed saved edit is not a ready delivery.
   Exact unique labels in `figures[].sample_styles` support `set_sample_style`
   batches for ordinary curve color/width; ambiguity requires explicit object
   selection. The local service binds current settings and preserves the same
   native preview, science audit and revision guards.

   For consistent sample styling across experiments, capture a saved ordinary
   curve figure with `project style-capture` or MCP `sample_style_capture`.
   Use the returned preset path/hash in `apply_sample_style_preset`; default
   matching requires coverage of all ordinary target samples, or pass an exact
   subset. Names are matched explicitly, never by curve position. Read the new
   preview before applying; no axes, measurements or annotations are copied.
   Sample color includes visible markers and bound generated sample labels;
   free annotations keep their styles.

   For several experiments, use `task group start --request EXPERIMENTS_JSON
   --group-dir NEW_DIRECTORY --json` and its MCP group tools. The explicit list
   contains ordinary task requests; do not scan a mixed folder and silently pick
   datasets. The optional shared sample preset applies to newly created figures.
   Inspect the local `overview` and returned PNGs, then pass item/task-bound
   responses through `task group resume`. One pending item does not stop the
   others. Omit responses to continue interrupted work; this never accepts
   previews or chooses scientific answers. Same-project figure edits remain
   sequential under the existing document transaction. Group completion is task
   progress; inspect each project's current source/QA/delivery for handoff.

   Refine a pending preview with `revise_operations` and its current
   `expected_operation_id`; the replacement is the complete batch against the
   same saved baseline. Accept or reject revised previews with that current ID
   so an old response cannot apply new intent. An identical revision retry is
   idempotent. Native-validated pure style requests already satisfied return
   `unchanged` without another review or document write; requested export still
   runs. See the operation guide for recovery and completion scope.
   A malformed operation is rejected before a new task or replacement is saved;
   correct the reported field while retaining the existing pending preview ID.
   For a `blocked/previewing` failure that needs corrected operations, use its
   current `preview_revision` as `expected_preview_revision` with the complete
   replacement. Read and accept the newly generated preview by operation ID.
   This correction path never replaces accepted or uncertain applied work.

   Public annotation operations now include reference lines, text/arrows and
   source-bound observed peak labels, plus update/removal. Query annotations
   and exact units first; use `project operations-preview` or a task `edit`
   request, and apply through the existing native transaction. Do not replace
   rejected operations with arbitrary Python or VSZ text changes. Remove
   annotations before source revision until rebinding has its own reviewed
   contract. The lower-level routes below remain available for diagnostics.

3. For new raw data, inspect the source and ready rule invocation, then preserve
   a successful source-bound plan before execution:

   ```bash
   skill/scripts/sciplot inspect INPUT --json
   skill/scripts/sciplot rules show RULE_ID --json
   skill/scripts/sciplot plan INPUT --rule RULE_ID --template TEMPLATE_ID --json > PLAN_JSON
   skill/scripts/sciplot project create INPUT --expected-plan PLAN_JSON --json
   ```

   Create consumes the exact plan's rule/template and current source bytes,
   then runs ordinary Studio preparation/export once to produce a resumable
   canonical project. Both visible output and hidden workspace must be new;
   inspect an existing managed project instead of overwriting it. Report real scientific
   ambiguity; do not remove `--expected-plan` to bypass a mismatch. Put plan
   evidence outside raw-input directories, managed projects and visible deliveries.

4. For existing work, resume the returned canonical project and inspect its
   actual figure/object identities. Do not prepare the raw source again:

   ```bash
   skill/scripts/sciplot project inspect PROJECT --json
   skill/scripts/sciplot project inspect PROJECT --figure FIGURE_ID --json
   ```

   Take FIGURE_ID from the query, including its `primary_figure_id`; do not use
   the literal word `primary`. Bind operations to `document_sha256` and exact
   absolute native paths/expected values from `editable_fields`. Use a new
   dedicated directory for each current/candidate PNG preview.

   Project inspection and edit-preview CLI results are compact by default,
   matching MCP. Use `--full` only for complete native settings or signed state;
   apply the persisted complete file at `review_path`, never compact stdout.

5. Preview and apply only the authorized advertised style edits. Read the
   candidate image, actual changes and scientific audit before apply:

   ```bash
   skill/scripts/sciplot project edit-preview PROJECT --figure FIGURE_ID \
     --expected-document DOCUMENT_SHA256 --changes CHANGES_JSON --out NEW_EDIT_DIR --json
   skill/scripts/sciplot project edit-apply PROJECT --preview NEW_EDIT_DIR/edit-preview.json --json
   skill/scripts/sciplot project operation PROJECT --operation-id OPERATION_ID --json
   ```

   Close all writable native windows for the project, even clean ones, before
   external apply. Existing user intent authorizes concrete style changes; ask
   only for unresolved meaning or scope. Keep the preview unchanged. On a lost
   reply, read the durable operation and use the bounded same-preview retry;
   never assume an uncertain outcome succeeded.

6. Export the exact current complete project without regeneration:

   ```bash
   skill/scripts/sciplot studio PROJECT --export pdf,tiff_300 --json
   skill/scripts/sciplot project inspect PROJECT --json
   ```

   `--json` does not open Veusz. Apply alone does not export. Before handoff,
   inspect current VSZ identity, manifest, QA, figures, plotting
   data, and delivery completeness. Require ready state, passed QA, and matching
   current/exported/delivered VSZ hashes. A new AI session resumes by inspecting
   PROJECT and uses the current saved SHA rather than remembered chat state.

## Output placement

For raw-input plotting, omit `--out` by default. SciPlot must create the visible
`SOURCE_SciPlot/` package beside the source and place internal evidence in the
sibling hidden `.sciplot/` workspace.

Do not put user plotting deliveries inside the SciPlot repository or its
`outputs/` directory. When a custom name is required, point `--out` to a
dedicated directory beside the original data. `.tmp_verify/` is reserved for
development gates.

The visible package is limited to:

```text
SOURCE_SciPlot/  # or a source-adjacent explicit --out
  data/*.csv
  figures/*.pdf
  figures/*_300dpi.tiff
  project/*.vsz
  Open_in_Veusz.command
```

Raw snapshots, manifests, analysis tables, QA, provenance, and transform
lineage remain in the hidden runtime workspace.

## Command routing

- `task`: complete local create/edit/export requests, persisted questions and
  preview review, bounded recovery and compact historical task receipts.
- `mcp`: optional stdio transport for the same domain services; no internal model.
- `project`: external-AI creation from an expected plan, saved-project inspection,
  native preview/edit and durable operation queries. Creation alone prepares
  the source through the existing Studio lifecycle; queries and edits do not.
- `studio`: exact-current export and compatible native interactive command family.
- `autoplot`: compatible one-time raw-path/QA/delivery route using the same
  renderer. Its run-only project layout is not a canonical Studio project and
  must not be advertised as directly resumable by `project inspect/edit`.
- `run`: replay a confirmed `plot_request.json`.
- `app`: optional first-time confirmation and read-only result review.
- `render` and `recipe`: low-level development/testing primitives.
- `curate torque`: scientific selection and Studio preparation, not final
  rendering or delivery.
- `readiness`, `cleanup`, `mapping`, and `publication`: maintenance or metadata
  commands, not plotting entrypoints.
- `batch`, `smoke`, and `acceptance`: development evidence routes.
- `verify --changed`: public changed-owner development verification; it does
  not render, open Veusz, or publish artifacts.
- `one-step`: internal manifest/readiness model, never a user recommendation.

Do not recommend retired command names. Legacy-launcher detection may remain
only so old generated artifacts fail with an explicit migration message.

## Scientific and presentation contracts

Preserve raw values and scientific meaning. Never turn empty or unreadable data
into a placeholder series, average repeated scientific rows silently, invent
missing measurements, interpolate absent reference values, or let a pending
rule appear ready.

The production Veusz builder implements:

```text
curve
point_line
stacked_curve
bar
box
box_strip
heatmap
scatter
polar_curve
```

Requests for other templates fail closed. A semantic rule owns recognition,
units, replicate preservation, and analysis; its presentation contract owns
the allowed chart alternatives. Use the current public contract and tests
rather than copying template behavior into a recipe or script.

`performance_comparison` requires its exact tidy long-table contract. Its ready
rule may be selected automatically only when that contract is recognized;
explicit Studio requests remain available for choosing `scatter` or
`polar_curve`.

Global typography, strokes, ticks, markers, ordinary frames, exports, and the
plot contract belong to `src/sciplot_core/policy/`. Heatmap scalar colors are
the explicit semantic exception. Display units use Unicode negative-exponent
products (`kJ m⁻²`, `W g⁻¹`, `Pa⁻¹`); mathematical ratios such as `σ/σ₀`
remain ratios.

Detailed reader-facing behavior belongs in `README.md`; implementation
ownership belongs in `docs/ARCHITECTURE.md`; executable truth belongs in the
request contract, policy data, and focused tests. Do not duplicate those
details here.

## States and repair

Project state (`editing`, `exporting`, `ready`, `needs_fix`) is distinct from
automation state (`ready`, `needs_human_confirmation`, `needs_rule_repair`) and
source-audit state.

`project inspect` returning `status=ok` proves only that the query succeeded.
It deliberately reports `ready_to_use=null`, `readiness_evaluated=false`, and
separates historical `last_run` evidence from source/QA/delivery byte-currentness.
An edit preview or applied operation also does not certify publication. A saved
document hash is its revision; a live GUI changeset is not a durable task version.

- `ready`: inspect and hand off the reviewed delivery.
- `needs_human_confirmation`: ask only for unresolved scientific meaning.
- `needs_rule_repair`: repair the central semantic rule, recipe, policy, or QA;
  add representative coverage and rerun the same request.

When cleanup is required:

1. preserve raw inputs;
2. record any data reshaping and inspect `cleanup_result.json`;
3. patch the central owner, not a one-off plot;
4. add focused fixtures/tests;
5. rerun Studio export and inspect the final delivery.

## Repeated friction and environment

After the second occurrence of one symptom, or the second unsuccessful change
for one defect, stop guessing and record:

1. symptom and scope;
2. root cause;
3. stable replacement command or contract;
4. discriminating verification;
5. limitations.

Use the existing project environment:

```bash
.venv/bin/python -m pytest -q
.venv/bin/python -m pip --version
```

If `.venv/bin/python` is absent, probe `python3` once and follow the README
installation route. Do not repeatedly invoke a known unavailable executable.

## Specialized development routes

```bash
skill/scripts/sciplot curate torque INPUT \
  --name PROJECT_NAME \
  --out /原始数据所在目录/Torque_SciPlot \
  --json

skill/scripts/sciplot app INPUT \
  --out /原始数据所在目录/SOURCE_SciPlot

skill/scripts/sciplot qa OUTDIR --strict-publication
skill/scripts/sciplot batch INPUT_DIR --out .tmp_verify/batch --mode smoke
```

These routes do not replace Studio as final editor and visual authority.

## Test tiers and verification

Default to the source-controlled changed-owner route while iterating:

```bash
skill/scripts/sciplot verify --changed --json
```

It compares the current `HEAD` with staged, unstaged, and untracked paths in
one selection pass. It runs at most one Ruff command over existing changed
Python files, one focused pytest command over explicit owner targets, and one
mypy command only when the changed owner intersects the scope declared in
`pyproject.toml`, plus one tracked diff whitespace check. Unknown production or
configuration paths fail closed; they
never trigger a repository-wide focused, comprehensive, full, smoke, or
acceptance fallback. The command does not render, edit, hash-check, or export a
Veusz document.

For a single known behavior, the smallest discriminating test remains valid:

```bash
.venv/bin/python -m pytest -q tests/test_module.py::test_changed_behavior
```

Run the source-controlled scoped static type gate when changing a source file
declared under `[tool.mypy]` in `pyproject.toml`:

```bash
.venv/bin/python -m mypy
```

Its exact scope and strictness belong to `pyproject.toml`. It proves only the
files configured there; imported modules outside that owned scope are analyzed
for type information but do not enter the diagnostic baseline. A passing
result is not a claim of repository-wide type safety.

Pytest assigns every test to exactly one logical tier:

- `focused`: single-owner, in-process behavior. All tests without an explicit
  `comprehensive` marker enter this tier automatically.
- `comprehensive`: real Veusz worker/export, cross-process wrapper, or complete
  Studio lifecycle behavior.

Run the tier that matches the changed boundary:

```bash
.venv/bin/python -m pytest -q -m focused
.venv/bin/python -m pytest -q -m comprehensive
.venv/bin/python -m pytest -q
```

Do not run the full suite after intermediate edits or use it to compensate for
an unknown owner. Full pytest is a release/merge gate. A documentation-only or
isolated fixture change may close with its directly related owner tests when no
executable contract changed.

A gate is invalid if it passes only because coverage was deleted, types or
assertions were weakened, checks were disabled, errors were ignored, or broad
suppressions were added.

Run `doctor` once at handoff for command/runtime contract changes. Run runtime
smoke once at the final cross-boundary milestone when the completed change
crosses Studio, renderer, worker, export, QA, delivery, launcher, or runtime
environment:

```bash
skill/scripts/sciplot doctor --json
skill/scripts/sciplot smoke --out .tmp_verify/runtime_smoke --json
git diff --check
```

Acceptance and full pytest are release/merge gates. At that gate, shared style,
renderer, rule, QA, or delivery changes also run:

```bash
skill/scripts/sciplot acceptance rules \
  --out .tmp_verify/acceptance \
  --json
```

Synthetic smoke is a runtime gate, not real-data evidence. Acceptance contact
sheets are uncalibrated previews and do not prove final-size readability;
machine lifecycle, provenance, human review, and journal compliance remain
separate claims.

For every non-trivial development turn, update `DEVELOPMENT_LOG.md` with the
change, current state, and verification before reporting.
