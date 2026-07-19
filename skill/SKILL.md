---
name: sciplot-materials-analysis
description: Deterministic materials-science plotting through editable Veusz VSZ projects, artifact QA, delivery, and optional selected-object AI.
---

# SciPlot Materials Analysis

Use the repository CLI and shared contracts. Do not create one-off plotting
scripts, copy style constants, or introduce another renderer or editor.

## Product boundary

Veusz `MainWindow` is the only daily plotting frontend and
`studio/document.vsz` is the visual authority. Keep object selection,
alignment, arbitrary properties, Datasets, Save, and Undo/Redo in Veusz.

SciPlot may add default-hidden Project and AI docks to the same live
`Document`. AI is optional and may only propose validated `set_setting`
operations for the currently selected supported object. Provider absence must
not disable deterministic plotting, manual editing, QA, export, or delivery.

Do not recreate or reference removed Canvas, Composition, session-evidence, or
promotion workflows. Do not automate Veusz with mouse clicks or patch VSZ text.

## Standard workflow

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

3. Prefer the VSZ-first daily route:

   ```bash
   skill/scripts/sciplot studio INPUT \
     --out outputs/projects \
     --export pdf,tiff_300 \
     --json
   ```

   When scientific or presentation intent is already known, pass it:

   ```bash
   skill/scripts/sciplot studio INPUT \
     --rule RULE_ID \
     --template TEMPLATE_ID \
     --out outputs/projects \
     --export pdf,tiff_300 \
     --json
   ```

   `--rule` must name a ready rule. `--template` must be implemented by the
   production Veusz builder.

4. For advanced changes, edit in Veusz and export the exact current document:

   ```bash
   skill/scripts/sciplot studio PROJECT/studio/document.vsz --advanced-editor
   skill/scripts/sciplot studio PROJECT --export pdf,tiff_300 --json
   ```

   For a standalone master:

   ```bash
   skill/scripts/sciplot studio FIGURE.vsz \
     --out outputs/standalone_export \
     --export pdf,tiff_300 \
     --json
   ```

   A standalone receipt proves exact-current export and artifact QA only. It
   does not establish source provenance or a complete project delivery.

5. Before handoff, inspect state, current VSZ hash, `manifest.json`,
   `review.html`, figures, `tables/analysis_metrics.csv`, QA, and `delivery/`.
   Require ready state, passed QA, and complete delivery.

## Supported template boundary

The production builder implements exactly:

```text
curve
point_line
stacked_curve
box
box_strip
heatmap
```

Unknown or reference-only templates must fail at request validation; never
silently render them as curves.

`src/sciplot_core/policy.py` owns global typography, stroke, tick, marker,
ordinary frame, size, export, and delivery defaults. The vendored
`plot_contract.json` and `src/sciplot_core/style_contract.py` enforce agreement
across templates, ready rules, figure profiles, and render defaults.
Templates and recipes must not own private font, line-width, tick, marker, or
ordinary-margin constants.

## States and repair

- `ready`: inspect and hand off the reviewed delivery.
- `needs_human_confirmation`: ask only for unresolved scientific meaning.
- `needs_rule_repair`: repair the shared semantic rule, recipe, policy, or QA;
  add a fixture/test and rerun the same request.

Never turn empty or unreadable data into a placeholder series. Never let
pending rules, skipped QA, or incomplete delivery appear ready. Preserve raw
inputs and scientific meaning.

When cleanup is necessary:

1. preserve raw inputs;
2. write and inspect `cleanup_result.json` when data is reshaped;
3. patch the central owner rather than create a one-off plot;
4. add representative fixture/test coverage;
5. rerun Studio export and inspect the final delivery.

Use existing recipe families before adding code: `tensile`,
`stress_relaxation`, `rheology_dma`, `thermal`, `spectroscopy`, `scattering`,
`chromatography`, and `metrics_swelling`.

## Delivery contract

The user-facing package is intentionally limited to:

```text
delivery/
  data/*.csv
  pdf/*.pdf
  tiff/*_300dpi.tiff
  project/*.vsz
  Open_in_Veusz.command
```

Raw archives, manifests, analysis tables, QA, publication evidence, and
transform lineage remain in the run output.

## Other supported routes

```bash
# Repeat a confirmed request
skill/scripts/sciplot run plot_request.json

# Stable supported package
skill/scripts/sciplot autoplot INPUT --out outputs/autoplot_projects --json

# Folder and rule acceptance
skill/scripts/sciplot batch INPUT_DIR --out OUTDIR --mode smoke
skill/scripts/sciplot acceptance rules --out outputs/acceptance --json

# Torque event curation
skill/scripts/sciplot curate torque INPUT --name PROJECT_NAME \
  --out outputs/curation_projects --json

# Browser data-confirmation compatibility surface, only when requested
skill/scripts/sciplot app --out outputs/intake_projects

# Independent artifact QA
skill/scripts/sciplot qa OUTDIR --strict-publication
```

The browser route is not a drawing frontend. Source, Inspect, and Samples are
data-confirmation stages; Result Review appears only after rendered artifacts
exist.

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

Inspect each evidence tier. Synthetic smoke is a runtime change gate, not
real-data evidence. Passing automation does not prove sustained human daily
use or blanket journal compliance.

For every non-trivial development turn, update `DEVELOPMENT_LOG.md` with the
change, current project state, and verification before reporting.
