---
name: sciplot-materials-analysis
description: Deterministic materials-science plotting through editable Veusz VSZ projects, artifact QA, delivery, and optional selected-object AI.
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

Veusz `MainWindow` is the only daily plotting frontend and
`studio/document.vsz` is the visual authority. SciPlot-owned Qt modules attach
Project and optional selected-object AI docks to the same live `Document`;
they are not another frontend.

The browser `app` is limited to initial source, grouping, naming, order, size,
and export confirmation plus read-only result review. All post-render editing
belongs in native Veusz. Do not automate Veusz with mouse clicks or patch VSZ
text.

AI is optional. Provider absence must not disable deterministic recognition,
plotting, manual editing, QA, export, or delivery. AI may propose only validated
operations for the currently selected supported object.

## Primary workflow

1. Check readiness:

   ```bash
   skill/scripts/sciplot doctor --json
   ```

   Require `status=ready`.

2. Inspect unfamiliar input or rules when needed:

   ```bash
   skill/scripts/sciplot inspect INPUT --json
   skill/scripts/sciplot rules list --json
   skill/scripts/sciplot rules show RULE_ID --json
   ```

3. Prepare raw input and open native Veusz:

   ```bash
   skill/scripts/sciplot studio INPUT
   ```

   When intent is already known:

   ```bash
   skill/scripts/sciplot studio INPUT \
     --rule RULE_ID \
     --template TEMPLATE_ID
   ```

4. Use the same lifecycle for headless export:

   ```bash
   skill/scripts/sciplot studio INPUT \
     --export pdf,tiff_300 \
     --json
   ```

   `--json` does not open Veusz.

5. Open or export the exact current document without regeneration:

   ```bash
   skill/scripts/sciplot studio FIGURE.vsz
   skill/scripts/sciplot studio PROJECT --export pdf,tiff_300 --json
   ```

6. Before handoff, inspect current VSZ identity, manifest, QA, figures, plotting
   data, and delivery completeness. Require ready state, passed QA, and matching
   current/exported/delivered VSZ hashes.

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

- `studio`: primary interactive and exact-current command family.
- `autoplot`: only public fully automated raw-path project/QA/delivery route;
  it orchestrates the same renderer and is not another plotting system.
- `run`: replay a confirmed `plot_request.json`.
- `app`: optional first-time confirmation and read-only result review.
- `render` and `recipe`: low-level development/testing primitives.
- `curate torque`: scientific selection and Studio preparation, not final
  rendering or delivery.
- `readiness`, `cleanup`, `mapping`, and `publication`: maintenance or metadata
  commands, not plotting entrypoints.
- `batch`, `smoke`, and `acceptance`: development evidence routes.
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

Use the smallest discriminating test while iterating:

```bash
.venv/bin/python -m pytest -q tests/test_module.py::test_changed_behavior
```

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

Do not run the full suite after every intermediate edit. Run it before handoff
when production code, a public interface, shared contract, test
classification/configuration, broad refactor, release/merge state, or an
uncertain impact radius changed. A documentation-only or isolated fixture
change may close with its directly related tests when no executable contract
changed.

A gate is invalid if it passes only because coverage was deleted, types or
assertions were weakened, checks were disabled, errors were ignored, or broad
suppressions were added.

Run `doctor` for command/runtime contract changes. Run runtime smoke when the
change crosses Studio, renderer, worker, export, QA, delivery, launcher, or
runtime-environment boundaries:

```bash
skill/scripts/sciplot doctor --json
skill/scripts/sciplot smoke --out .tmp_verify/runtime_smoke --json
git diff --check
```

For shared style, renderer, rule, QA, or delivery changes, also run:

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
