---
name: sciplot-materials-analysis
description: Use this when working with polymer/materials science experimental data for SciPlot-style analysis, Data Studio-style cleanup, fitting, recipe-based processing, and publication-ready figures using the self-contained SciPlot Codex Core repo.
---

# SciPlot Materials Analysis

## Purpose

Use this skill to turn materials-science data into SciPlot-style processed tables, figures, and reports. The implementation source of truth is the self-contained repo at `/Users/dongxutian/Documents/research-plots`.

Do not hand-copy SciPlot style constants, Matplotlib rcParams, legend-placement heuristics, tick policies, or Data Studio parsing rules into ad-hoc code. Call the repo CLI so figures go through the contract-driven renderer, layout policy, and QA.

## Workflow

1. Inspect inputs first:
   ```bash
   /Users/dongxutian/.codex/skills/sciplot-materials-analysis/scripts/sciplot inspect INPUT --json
   ```
2. Inspect local materials rules before inventing extraction logic:
   ```bash
   /Users/dongxutian/.codex/skills/sciplot-materials-analysis/scripts/sciplot rules list --json
   /Users/dongxutian/.codex/skills/sciplot-materials-analysis/scripts/sciplot rules show RULE_ID --json
   ```
3. Choose the route:
   - User-supplied raw data path or folder: the Web UI confirmation flow is mandatory unless the user explicitly asks to bypass it. Use `sciplot prepare PATH --out outputs/intake_projects --json`, then `sciplot intake PATH --out outputs/intake_projects` to open a prefilled UI; `sciplot workbench` is an alias for the same GUI. Let the user operate the page to confirm sample groups, sample/legend names, legend order, output directory, figure size, and export formats. The UI export action writes the request and renders figures.
   - Repeatable figure request from an already-confirmed request file: use `sciplot run REQUEST.json`.
   - Unknown mixed experiment request: use `sciplot run` with `"recipe": "auto"`.
   - Torque-rheometer curation: use `sciplot curate torque PATH --name PROJECT_NAME --out outputs/curation_projects --json`, review `curation/torque_review.html`, then open the Web UI when the user wants to choose output directory, figure size, or export formats.
   - Folder acceptance/smoke test: use `sciplot batch INPUT_DIR --out OUTDIR --mode smoke`.
   - Full-folder acceptance: use `sciplot batch INPUT_DIR --out OUTDIR --mode all`; pass repeatable `--tensile-root PATH` when only selected tensile folders should be processed.
   - Rheology sweep sample folders, such as frequency or temperature scans: pass the folder to `sciplot run` with `"recipe": "auto"` so SciPlot aggregates same-metric columns across samples before plotting.
   - Plot-ready table: use `sciplot render`.
   - Experiment-family data: use `sciplot recipe NAME`.
   - Ambiguous data: inspect `sciplot_semantics`, `rule_id`, `axis_plan`, and `missing_requirements` before patching rules.
4. Use the v1 recipe names:
   - `tensile`
   - `stress_relaxation`
   - `rheology_dma`
   - `thermal`
   - `spectroscopy`
   - `scattering`
   - `chromatography`
   - `metrics_swelling`
5. Verify every output folder:
   ```bash
   /Users/dongxutian/.codex/skills/sciplot-materials-analysis/scripts/sciplot qa OUTDIR \
     --goldens /Users/dongxutian/Documents/research-plots/tests/goldens
   ```
6. Return the output folder, generated figures/tables, `tables/analysis_metrics.csv`, QA status, and scientific assumptions/caveats.

## Commands

```bash
# Inspect and recommendation payload
sciplot inspect INPUT --sheet 0 --json

# Inspect low-token materials plotting rules
sciplot rules list --json
sciplot rules show rheology_temperature_sweep --json

# Render a specific public template
sciplot render INPUT --template curve --out OUTDIR
sciplot render INPUT --template heatmap --options '{"style_preset":"acs"}' --out OUTDIR

# Run an experiment-family recipe
sciplot recipe rheology_dma INPUT --out OUTDIR
sciplot recipe tensile INPUT --options '{"template":"curve"}' --out OUTDIR

# Run a request or batch acceptance workflow
sciplot prepare INPUT_PATH --out outputs/intake_projects --json
sciplot curate torque INPUT_PATH --name PROJECT_NAME --out outputs/curation_projects --json
sciplot run plot_request.json
sciplot batch INPUT_DIR --out OUTDIR --mode smoke
sciplot batch INPUT_DIR --out OUTDIR --mode all --tensile-root PATH

# Open the local file-grouping and export-options Web UI
sciplot intake INPUT_PATH --out outputs/intake_projects
sciplot workbench INPUT_PATH --out outputs/intake_projects

# Validate generated PDFs and golden metrics
sciplot qa OUTDIR --goldens /Users/dongxutian/Documents/research-plots/tests/goldens
```

## Core Rules

- The new repo is the long-term truth source. Do not import from `/Users/dongxutian/Documents/codegod`; that retired project may be deleted.
- Treat `src/sciplot_core/materials_rules.py` as the source of truth for material plot aliases, x/y axes, unit conversions, reverse axes, optional `y_metric` choices, and common deterministic analysis metrics.
- Do not re-infer temperature sweep, stress relaxation, tensile, DSC/TGA, FTIR, XRD/SAXS, GPC, swelling, or conductivity axes from scratch if `sciplot rules` already describes them.
- Treat torque-rheometer text exports with `Screw Torque` columns as `torque_curve`; the curation workflow defaults to the final feed-peak, mixing, and discharge-drop event segment, exports the plotting CSV, records file paths, and packages the project file.
- For plotting from user-supplied raw data paths, always open the Web UI and stop so the human can edit unless the user explicitly asks to bypass it. Do not click through the UI on behalf of the user. Use the UI's sample/legend names, legend order, output directory, figure size, and export format choices as request overrides instead of silently keeping rule defaults.
- Keep Web UI figure-size choices aligned with the full SciPlot contract size presets: `60x55`, `120x55`, `180x55`, `60x110`, `120x110`, and `180x110`.
- If the Web UI starts a Codex job, inspect `codex_jobs/*/sciplot_codex_handoff.json`, `status.json`, stdout/stderr logs, generated figures, and QA output before reporting the result.
- For rheology sweep folders with multiple sample exports, do not plot all metrics for one sample as the main comparison. Aggregate same metrics across samples first, then render separate cross-sample figures for the supported metrics.
- Use existing recipe modules before writing new analysis code.
- If a dataset produces `intervention_request.json`, `needs_ai_intervention`, or batch `interventions`, patch the semantic recognizer or corresponding recipe in `/Users/dongxutian/Documents/research-plots`, add/extend a simulated fixture, add/update a golden or QA assertion, and rerun tests.
- Recipes must write `processed/`, `figures/`, `tables/`, `manifest.json`, `analysis_report.md`, and request workflows should write `tables/analysis_metrics.csv` plus a `raw/` source archive.
- Request and batch outputs should use PDF plus 300 DPI TIFF by default.
- Figures must be produced through `sciplot_core.render_to_dir` or the `sciplot render` CLI. Avoid direct Matplotlib plotting unless you are extending the core renderer itself.
