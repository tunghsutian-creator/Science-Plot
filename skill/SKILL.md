---
name: sciplot-materials-analysis
description: Use this when working with polymer/materials science experimental data for SciPlot-style analysis, Data Studio-style cleanup, fitting, recipe-based processing, and publication-ready figures using the self-contained SciPlot repo.
---

# SciPlot Materials Analysis

## Purpose

Use this skill to turn materials-science data into SciPlot-style processed tables, figures, and reports. The implementation source of truth is the self-contained repo at `/Users/dongxutian/Documents/research-plots`.

Do not hand-copy SciPlot style constants, legacy Matplotlib rcParams, legend-placement heuristics, tick policies, or Data Studio parsing rules into ad-hoc code. Call the repo CLI so figures go through the contract-driven Veusz renderer, layout policy, and QA. Keep cross-cutting defaults in `src/sciplot_core/policy.py` and renderer QA thresholds in `src/sciplot_core/_vendor/src/plot_contract.json`.

## Workflow

1. Inspect inputs first:
   ```bash
   /Users/dongxutian/.codex/skills/sciplot-materials-analysis/scripts/sciplot doctor --json
   ```
   ```bash
   /Users/dongxutian/.codex/skills/sciplot-materials-analysis/scripts/sciplot inspect INPUT --json
   ```
2. Inspect local materials rules before inventing extraction logic:
   ```bash
   /Users/dongxutian/.codex/skills/sciplot-materials-analysis/scripts/sciplot rules list --json
   /Users/dongxutian/.codex/skills/sciplot-materials-analysis/scripts/sciplot rules show RULE_ID --json
   ```
   `rules list` shows only ready rules by default; use `--all` only for internal rule repair.
3. Choose the route:
   - User-supplied raw data path or folder: prefer the Qt-first route `sciplot studio PATH --out outputs/intake_projects`. It creates a SciPlot project package, writes `studio/document.vsz`, and opens the embedded Veusz editor. SciPlot decides the initial figure using data recognition, sample/legend names, template choice, and plotting policy; Veusz handles interactive edits after that generated figure appears. Use the Web UI confirmation flow only when the user explicitly wants browser confirmation. The shortest prefilled Web path remains `sciplot quick PATH`. The equivalent explicit Web route is `sciplot prepare PATH --out outputs/intake_projects --json`, then `sciplot intake PATH --out outputs/intake_projects`; `sciplot app` is the blank browser entrypoint, and `sciplot workbench` is an alias for the same GUI. For Studio exports, run `sciplot studio PATH --export pdf,tiff_300 --json`, then inspect the generated Studio run `manifest.json`, `review.html`, `revision_brief.md`, `delivery/`, and QA before reporting. Source, Inspect, and Samples are data-confirmation stages, not plot-preview stages. Result Review appears only after Export or assisted repair produces rendered artifacts.
   - Stable script-driven package request: if the user explicitly wants a supported high-confidence experiment path rendered without stopping for UI confirmation, prefer `sciplot autoplot PATH --out outputs/autoplot_projects --json`. It runs the local one-step workflow and writes `autoplot_summary.json` with delivery state, structured QA, and optional assistant handoff policy. Use `sciplot one-step PATH --out outputs/one_step_projects --json` only when you need the lower-level one-step result directly. Inspect `autoplot_summary.json`, `one_step_status.json`, `manifest.json`, `delivery/`, and QA. The state must be `ready`, `needs_human_confirmation`, or `needs_rule_repair`; `needs_rule_repair` means optional assisted repair should patch rules/fixtures/tests and rerun instead of asking the user to edit code.
   - Repeatable figure request from an already-confirmed request file: use `sciplot run REQUEST.json`.
   - Unknown mixed experiment request: use `sciplot run` with `"recipe": "auto"`.
   - Torque-rheometer curation: use `sciplot curate torque PATH --name PROJECT_NAME --out outputs/curation_projects --json`, review `curation/torque_review.html`, then open the Web UI when the user wants to choose output directory, figure size, or export formats.
   - Folder acceptance/smoke test: use `sciplot batch INPUT_DIR --out OUTDIR --mode smoke`.
   - Full-folder acceptance: use `sciplot batch INPUT_DIR --out OUTDIR --mode all`; pass repeatable `--tensile-root PATH` when only selected tensile folders should be processed.
   - Representative 3D PA real-data acceptance after rule/layout changes: use `sciplot acceptance 3dpa PATH --out outputs/acceptance --json`, then inspect `acceptance_summary.json`, each run `manifest.json`, QA, and `delivery/`.
   - Rheology sweep sample folders, such as frequency or temperature scans: pass the folder to `sciplot run` with `"recipe": "auto"` so SciPlot aggregates same-metric columns across samples before plotting.
   - Plot-ready table: use `sciplot render`; it defaults to Veusz and records `render_engine=veusz`.
   - Experiment-family data: use `sciplot recipe NAME`; it defaults to Veusz via `render_to_dir`.
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
6. Before returning any Web UI, workbench, curation, or multi-project output package, leave a clickable launcher inside the delivered folder. On macOS, prefer an executable `Open_in_SciPlot.command` or `Open_<PROJECT>_in_SciPlot.command` that starts the correct `sciplot app`/`sciplot workbench` command with the right `--out` and `--project`; for multiple related projects, also include an HTML or Markdown index of the available project links. Do not rely on a transient localhost URL in the chat as the only way back into the project.
7. For `sciplot run`, inspect the minimal `delivery/` package before handoff:
   `{project}.sciplot`, `{project}.xlsx`, `figures/*.pdf`, `figures/*_300dpi.tiff`,
   and `_sciplot_internal/` for manifests, QA, raw data, and audit files.
8. Return the output folder, generated figures/tables, launcher path, `tables/analysis_metrics.csv`, QA status, and scientific assumptions/caveats.

## Commands

```bash
# Inspect and recommendation payload
sciplot doctor --json
sciplot inspect INPUT --sheet 0 --json

# Inspect low-token materials plotting rules
sciplot rules list --json
sciplot rules list --json --all
sciplot rules show rheology_temperature_sweep --json

# Render a specific public template
sciplot render INPUT --template curve --out OUTDIR
sciplot render INPUT --template heatmap --options '{"style_preset":"acs"}' --out OUTDIR

# Run an experiment-family recipe
sciplot recipe rheology_dma INPUT --out OUTDIR
sciplot recipe tensile INPUT --options '{"template":"curve"}' --out OUTDIR

# Run a request or batch acceptance workflow
sciplot prepare INPUT_PATH --out outputs/intake_projects --json
sciplot autoplot INPUT_PATH --out outputs/autoplot_projects --json
sciplot one-step INPUT_PATH --out outputs/one_step_projects --json
sciplot acceptance 3dpa INPUT_PATH --out outputs/acceptance --json
sciplot curate torque INPUT_PATH --name PROJECT_NAME --out outputs/curation_projects --json
sciplot run plot_request.json
sciplot batch INPUT_DIR --out OUTDIR --mode smoke
sciplot batch INPUT_DIR --out OUTDIR --mode all --tensile-root PATH
sciplot cleanup result RUN_OUTPUT_DIR --cleaned-data cleaned.csv --confidence 0.82 --confirm --json
sciplot cleanup show RUN_OUTPUT_DIR --json

# Open the Qt Studio desktop editor
sciplot studio INPUT_PATH --out outputs/intake_projects
sciplot studio --new

# Open the compatibility file-grouping and export-options Web UI
sciplot app --out outputs/intake_projects
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
- For plotting from user-supplied raw data paths, prefer the Qt Studio route and stop so the human can edit in the embedded Veusz editor unless the user explicitly asks for headless delivery. Use the Studio/Web sample names, legend order, output directory, figure size, and export format choices as request overrides instead of silently keeping rule defaults.
- Do not use an empty plot preview as a placeholder during import, inspection, or grouping.
- Read Result Review artifacts (`review.html`, figures, manifest, metrics, and QA) before reporting output.
- Keep Web UI figure-size choices aligned with the full SciPlot contract size presets: `60x55`, `120x55`, `180x55`, `60x110`, `120x110`, and `180x110`.
- Default to `60x55` unless the user explicitly selects a wider preset or a centralized rule documents the need.
- If the Web UI starts an assisted repair job, inspect `codex_jobs/*/sciplot_codex_handoff.json`, `status.json`, stdout/stderr logs, generated figures, and QA output before reporting the result.
- Every delivered SciPlot Web UI/workbench output package must be reopenable from the filesystem before the final reply. Create and verify a clickable launcher in the output folder, and mention it in the handoff. This applies even when the browser is already open during the current turn.
- For rheology sweep folders with multiple sample exports, do not plot all metrics for one sample as the main comparison. Aggregate same metrics across samples first, then render separate cross-sample figures for the supported metrics.
- Use existing recipe modules before writing new analysis code.
- If a dataset produces `intervention_request.json`, `assisted_cleanup_request.json`, `needs_ai_intervention`, or batch `interventions`, patch the semantic recognizer or corresponding recipe in `/Users/dongxutian/Documents/research-plots`, add/extend a simulated fixture, add/update a golden or QA assertion, write or inspect `cleanup_result.json` when data was reshaped, and rerun tests.
- If a one-step run returns `needs_rule_repair`, treat it the same way: inspect the structured status and intervention package first, then improve the rule system rather than making a one-off figure.
- Recipes must write `processed/`, `figures/`, `tables/`, `manifest.json`, `analysis_report.md`, and request workflows should write `tables/analysis_metrics.csv` plus a `raw/` source archive.
- Request and batch outputs should use PDF plus 300 DPI TIFF by default, with run outputs also producing the minimal `delivery/` package.
- Figures must be produced through `sciplot_core.render_to_dir` or the `sciplot render` CLI. Avoid direct Matplotlib plotting and do not add a second production renderer path.
