---
name: sciplot-materials-analysis
description: Deterministic materials-science plotting through editable Veusz VSZ projects, artifact QA, delivery, and optional selected-object AI.
---

# SciPlot Materials Analysis

Use the repository CLI and shared contracts. Do not create one-off plotting
scripts, copy style constants, or introduce another renderer, document model,
or editor.

## Authority and documentation

- `README.md` owns the product boundary and user workflow.
- This skill owns agent command routing and required checks.
- `docs/ARCHITECTURE.md` owns module and dependency boundaries.
- `DEVELOPMENT_ROADMAP.md` contains active work only.
- `AGENTS.md` is a thin local overlay; it must not redefine this workflow.
- `DEVELOPMENT_LOG.md` and Git are history/evidence, not current instructions.

When prose conflicts, verify the live CLI and source-controlled contracts, then
repair the stale document. Never revive an older frontend or route from history.

## Product boundary

Veusz `MainWindow` is the only daily plotting frontend and
`studio/document.vsz` is the visual authority. SciPlot-owned Qt modules attach
Project and optional selected-object AI docks to that same live `Document`;
they are not another frontend. Keep object selection, alignment, arbitrary
properties, Datasets, Save, and Undo/Redo in Veusz.

The browser `app` is limited to first-time source, grouping, naming, order,
size, and export-format confirmation plus read-only result review. Do not use
or extend it for post-render style, axis, legend, or series editing. All visual
refinement belongs in Veusz.

AI is optional and may only propose validated `set_setting` operations for the
currently selected supported object. Provider absence must not disable
deterministic plotting, manual editing, QA, export, or delivery.

Do not recreate or reference removed Canvas, Composition, session-evidence, or
promotion workflows. Do not automate Veusz with mouse clicks or patch VSZ text.

## Primary Studio workflow

1. Check readiness:

   ```bash
   skill/scripts/sciplot doctor --json
   ```

   Require `status=ready`.

2. Inspect new input and local rules when needed:

   ```bash
   skill/scripts/sciplot inspect INPUT --json
   skill/scripts/sciplot rules list --json
   skill/scripts/sciplot rules show RULE_ID --json
   ```

3. For interactive daily work, prepare the project and open native Veusz:

   ```bash
   skill/scripts/sciplot studio INPUT --out /path/to/Visible_Figure_Project
   ```

   When scientific or presentation intent is already known:

   ```bash
   skill/scripts/sciplot studio INPUT \
     --rule RULE_ID \
     --template TEMPLATE_ID \
     --out /path/to/Visible_Figure_Project
   ```

   `--rule` must name a ready rule. `--template` must be implemented by the
   production Veusz builder.

4. For headless preparation and export, use the same command family:

   ```bash
   skill/scripts/sciplot studio INPUT \
     --out /path/to/Visible_Figure_Project \
     --export pdf,tiff_300 \
     --json
   ```

   `--json` does not open Veusz. Interactive and headless Studio are two modes
   of one lifecycle, not separate plotting entrypoints.

5. Open an existing master directly and export its exact current state:

   ```bash
   skill/scripts/sciplot studio FIGURE.vsz
   skill/scripts/sciplot studio PROJECT --export pdf,tiff_300 --json
   ```

   For a standalone exact-current export:

   ```bash
   skill/scripts/sciplot studio FIGURE.vsz \
     --out outputs/standalone_export \
     --export pdf,tiff_300 \
     --json
   ```

   A standalone receipt proves exact-current export and artifact QA only. It
   does not establish source provenance or complete project delivery.

6. Before handoff, inspect state, current VSZ hash, `manifest.json`,
   `review.html`, figures, `tables/analysis_metrics.csv`, QA, and `delivery/`.
   Require ready state, passed QA, and complete delivery.

## Command routing

- `studio`: the primary interactive and exact-current project command family.
- `app`: opt-in first-time confirmation and read-only result review only. Keep
  it loopback-only and never bypass its session/output-root source-path boundary.
- `autoplot`: the only public fully automated raw-path project route. It wraps the
  internal one-step/`run_request` lifecycle and owns the stable summary, QA,
  and delivery result. It is orchestration over the same renderer, not another
  plotting implementation.
- `run`: replay an already-confirmed `plot_request.json`.
- `render` and `recipe`: low-level development/testing primitives.
- `one-step`: internal manifest/readiness contract; never recommend it as a
  user command.

Do not recommend the retired `quick`, `prepare`, `intake`, or `workbench`
names. They are no longer CLI commands; only explicit migration checks for old
generated launchers may remain.

## States and repair

Project result state (`editing`, `exporting`, `ready`, `needs_fix`) is distinct
from preparation/automation state (`ready`, `needs_human_confirmation`,
`needs_rule_repair`) and from source-audit state. Do not collapse them.

- `ready`: inspect and hand off the reviewed delivery.
- `needs_human_confirmation`: ask only for unresolved scientific meaning.
- `needs_rule_repair`: repair the shared semantic rule, recipe, policy, or QA;
  add a representative fixture/test and rerun the same request.

Never turn empty or unreadable data into a placeholder series. Never let
pending rules, skipped QA, or incomplete delivery appear ready. Preserve raw
inputs and scientific meaning.

When cleanup is necessary:

1. preserve raw inputs;
2. write and inspect `cleanup_result.json` when data is reshaped;
3. patch the central owner rather than create a one-off plot;
4. add representative fixture/test coverage;
5. rerun Studio export and inspect the final delivery.

## Template, style, and delivery contracts

The production builder implements exactly `curve`, `point_line`, `stacked_curve`,
`bar`, `box`, `box_strip`, and `heatmap`. The `bar` template uses mean ± SD
error bars for categorical replicate groups. Unknown or reference-only
templates must fail at request validation.

`src/sciplot_core/policy.py` owns global typography, stroke, tick, marker,
ordinary frame, size, export, and delivery defaults. Templates and recipes may
not own private hard-style constants. Heatmap scalar, contour, and colorbar
colors are the explicit semantic color exception.

For raw input, ``--out`` names the dedicated visible handoff directory.  When
omitted, create ``SOURCE_SciPlot/`` beside the source.  Put runtime evidence,
history, raw snapshots, manifests, and QA under the sibling hidden ``.sciplot/``
workspace; never make a normal user traverse ``outputs/.../runs/.../delivery``.

The user-facing package is limited to:

```text
SOURCE_SciPlot/  # or the explicit --out directory
  data/*.csv
  figures/*.pdf
  figures/*_300dpi.tiff
  project/*.vsz
  Open_in_Veusz.command
```

The VSZ files embed all plotted data and Veusz objects and remain the portable
editable authority. Raw archives, manifests, analysis tables, QA, publication
evidence, and transform lineage remain in the hidden runtime workspace.

## Specialized preparation and verification

```bash
# Scientific curation prepares a Studio project; Studio still owns final work
skill/scripts/sciplot curate torque INPUT --name PROJECT_NAME \
  --out outputs/curation_projects --json

# Optional browser confirmation surface, only when explicitly needed
skill/scripts/sciplot app INPUT --out outputs/intake_projects

# Independent artifact QA
skill/scripts/sciplot qa OUTDIR --strict-publication

# Development/acceptance only; batch is hidden from normal CLI help
skill/scripts/sciplot batch INPUT_DIR --out OUTDIR --mode smoke
skill/scripts/sciplot acceptance rules --out outputs/acceptance --json
```

`curate torque` does not own final rendering or delivery. `batch`, `smoke`, and
`acceptance` are regression/evidence routes, never alternatives to `autoplot`
for user automation.

`readiness`, `cleanup`, and `mapping` are maintenance/evidence commands.
`publication` exposes profile and deterministic layout metadata only; it does
not provide a Composition editor, assembler, or renderer. Never route plotting
through any of these commands.

## Verification and evidence

After every non-trivial code change:

```bash
python -m pytest -q
skill/scripts/sciplot doctor --json
skill/scripts/sciplot smoke --out .tmp_verify/runtime_smoke --json
git diff --check
```

For shared style, renderer, rule, QA, or delivery changes, also run:

```bash
skill/scripts/sciplot acceptance rules --out outputs/acceptance --json
```

`acceptance rules` machine-checks PDF physical dimensions, TIFF DPI, and
delivery-copy identity. Its contact sheets are uncalibrated overview previews
for clipping, occlusion, marker/line distinction, and blank or corrupt output;
they do not prove readability at final physical size. After inspecting every
preview, record the explicit result with:

```bash
skill/scripts/sciplot acceptance visual-review \
  OUTPUT/final_size_visual_review/final_size_visual_review.json \
  --decision passed --reviewer NAME --json
```

Until this record exists, report automated physical-size QA separately from
the still-pending preview review. Final-size readability requires separately
recorded inspection on a calibrated display or print; this command does not
provide that evidence.

Inspect each evidence tier. Synthetic smoke is a runtime change gate, not
real-data evidence. Passing automation does not prove sustained human daily
use or blanket journal compliance.

For every non-trivial development turn, update `DEVELOPMENT_LOG.md` with the
change, current project state, and verification before reporting.
