# SciPlot

SciPlot is a local, script-first plotting workbench for polymer and materials
science. It turns raw experiment tables into processed data, reviewable
publication-style figures, QA artifacts, and repeatable request files.

This repository is the source of truth for the SciPlot workflow. The goal is to
make plotting faster than manual Origin/Prism-style work while staying
auditable, repeatable, and easy to revise with Codex.

## Ultimate Goal

Build a practical research plotting system where:

- SciPlot handles data recognition, cleanup, units, axis labels, metrics,
  journal-style defaults, rendering, and QA.
- The local Web app is the daily plotting surface for importing data, confirming
  scientific intent, exporting figures, and reviewing results.
- Codex patches rules, recipes, fixtures, and tests when a dataset does not fit
  the current system.
- The human reviewer confirms sample names, legend order, figure size, export
  options, and final scientific meaning.

The long-term target is not to automate a closed-source drawing program. The
target is a small local plotting system that can beat manual figure software for
polymer science because every plot is reproducible and every correction can
become a reusable rule.

## Daily Workflow

Prefer the project wrapper:

```bash
skill/scripts/sciplot app --out outputs/intake_projects
```

For a raw user-supplied file or folder, use the Web UI confirmation flow:

```bash
skill/scripts/sciplot quick PATH
```

The explicit version is:

```bash
skill/scripts/sciplot prepare PATH --out outputs/intake_projects --json
skill/scripts/sciplot intake PATH --out outputs/intake_projects
```

The clickable macOS launcher is also available:

```bash
./Launch_SciPlot_App.command
```

For a confirmed request file:

```bash
skill/scripts/sciplot run plot_request.json
```

Default exports should stay:

```json
["pdf", "tiff_300"]
```

## Operating Model

Default loop:

```text
inspect -> recipe/render -> qa -> human review -> revised request/script -> rerun
```

Example request:

```json
{
  "recipe": "auto",
  "input": "data/frequency_sweep.xlsx",
  "output": "outputs/run_001",
  "exports": ["pdf", "tiff_300"],
  "render_options": {
    "style_preset": "nature",
    "palette_preset": "colorblind_safe"
  }
}
```

`sciplot run` writes a reviewable export package containing `manifest.json`,
`analysis_report.md`, `tables/analysis_metrics.csv`, `raw/`, `review.html`,
`revision_brief.md`, PDF figures, and 300 DPI TIFF figures. If recognition or
rendering needs Codex, SciPlot writes `intervention_request.json` or marks
`needs_ai_intervention`.

## Web App Contract

The Web app is the local SciPlot plotting app. `sciplot app`, `sciplot
workbench`, and `sciplot intake` open the same browser workflow.

Workflow:

```text
Source -> Inspect -> Samples -> Export -> Result Review
```

Stage rules:

- Source, Inspect, and Samples are data-confirmation stages, not plot-preview stages.
- Result Review appears only after Export or Codex produces rendered artifacts.
- Do not use an empty plot preview as a placeholder during import, inspection, or grouping.
- Read Result Review artifacts (`review.html`, figures, manifest, metrics, and QA) before reporting output.
- Use `revision_brief.md` as the short handoff for Codex-driven rule/style revisions.

The UI lets the user confirm source binding, detected rules/templates, sample
groups, sample/legend names, legend order, output directory, figure size, and
export formats. Figure-size choices must stay aligned with the SciPlot contract
presets: `60x55`, `120x55`, `180x55`, `60x110`, `120x110`, and `180x110`.

## Commands

Setup and checks:

```bash
make setup
make test
make lint
make clean
```

Manual equivalents:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'
.venv/bin/python -m pytest -q
.venv/bin/python -m ruff check .
```

Inspection:

```bash
skill/scripts/sciplot inspect INPUT --json
skill/scripts/sciplot rules list --json
skill/scripts/sciplot rules show rheology_temperature_sweep --json
```

Rendering:

```bash
skill/scripts/sciplot run plot_request.json
skill/scripts/sciplot qa OUTPUT_DIR
```

Batch and acceptance:

```bash
skill/scripts/sciplot batch INPUT_DIR --out OUTDIR --mode smoke
skill/scripts/sciplot batch INPUT_DIR --out OUTDIR --mode all
skill/scripts/sciplot batch INPUT_DIR --out OUTDIR --mode all --tensile-root PATH
```

Torque-rheometer curation:

```bash
skill/scripts/sciplot curate torque PATH --name PROJECT_NAME --out outputs/curation_projects --json
```

Torque text exports with `Screw Torque` columns should map to `torque_curve`.

## Source Of Truth

- `src/sciplot_core/materials_rules.py`: experiment-family aliases, axis
  aliases, unit rules, common metrics, and deterministic rule metadata.
- `src/sciplot_core/semantic.py`: source classification and semantic source
  preparation.
- `src/sciplot_core/workflow.py`: request execution, review artifacts, QA, and
  intervention handoff.
- `src/sciplot_core/intake.py`: Web app project/session workflow.
- `src/sciplot_core/intake_static/index.html`: browser UI.
- `src/sciplot_recipes/`: public recipe modules for known experiment families.
- `skill/scripts/sciplot`: preferred wrapper for Codex and local use.
- `AGENTS.md`: operating rules for Codex in this repository.
- `skill/SKILL.md`: SciPlot Materials Analysis Skill instructions.
- `DEVELOPMENT_LOG.md`: development log, project board, decisions, and next
  steps.

`_vendor/` is the migrated renderer black box. Do not inspect or modify it by
default. Patch the public wrapper, semantic layer, recipes, fixtures, and tests
first. Use `rule_id` or `y_metric` only when the user explicitly needs a local
materials rule override.

## Current Scope

The first-class materials workflows are:

- Rheology and DMA sweeps, including frequency and temperature comparisons.
- Impact metrics and replicate summary plots.
- Tensile export folders.
- Thermal analysis.
- Spectroscopy, scattering, and chromatography.
- Stress relaxation and swelling/metric tables.
- Torque-rheometer curation and event-segment plotting.

Use `"recipe": "auto"` when SciPlot should choose the semantic family,
preprocessor, recipe, and template automatically.

Rheology sweep folders such as frequency or temperature scans that contain
multiple sample exports should be treated as comparison groups: aggregate
same-metric columns across samples, then plot each supported metric as a
separate cross-sample figure.

## Development Contract

- Do not create one-off plotting scripts unless they call the public recipe or
  render APIs.
- Do not copy Matplotlib style constants into ad hoc scripts.
- Keep experiment recognition, axis aliases, unit conversion, and analysis
  metrics in the public SciPlot layer.
- Keep generated outputs under ignored folders such as `outputs/` or
  `.tmp_verify/`.
- Add or update fixtures and tests for every new rule, recipe, or semantic
  behavior.
- For a user-supplied raw data path, open the Web UI confirmation flow unless
  the user explicitly asks to bypass it.
- If `intervention_request.json`, `needs_ai_intervention`, or batch
  `interventions` appears, patch code and tests, then rerun the request.

## Roadmap

Phase 1: Make the Web app the daily plotting surface.

- Keep the redesigned intake UI polished and fast.
- Improve project/session browsing under `outputs/intake_projects`.
- Make output directory selection obvious and visible.
- Keep Result Review as the quality gate for PDF/TIFF outputs.

Phase 2: Strengthen polymer-science rules.

- Finish rheology and impact as the first reliable real-data tracks.
- Expand FTIR, XRD, tensile, thermal, and DMA fixtures from real examples.
- Improve unit normalization, axis naming, legend ordering, and metrics.
- Add more deterministic failure handoffs for Codex.

Phase 3: Add interactive figure refinement.

- Build a SciPlot-native visual refine panel for axes, ticks, legend, line
  width, marker size, labels, and export presets.
- Keep SciPlot's rendered PDF/TIFF as the QA baseline.
- Save refinements back into request options or reusable style presets.

Phase 4: Make Codex intervention routine.

- Use structured Codex jobs only after user confirmation.
- Inspect `codex_jobs/*/sciplot_codex_handoff.json`, logs, status, and outputs
  before reporting.
- Convert repeated human corrections into tests, rules, recipes, or presets.

Phase 5: Support manuscript workflows.

- Add panel assembly, figure registry, journal presets, and PPT/manuscript
  handoff exports.
- Keep raw data, processed tables, request files, and QA artifacts connected to
  every final figure.

## Next Development Suggestions

1. Add a Web app project browser for previous runs and ZIP packages.
2. Add a data-table preview with column type controls before export.
3. Add visual controls for ticks, axis range, legend position, line width, and
   marker size, then write them back into `plot_request.json`.
4. Add screenshot-based UI regression tests for desktop and mobile layouts.
5. Add real rheology and impact fixtures from the current polymer dataset.
6. Add a prepared-data export/import route for users who still need optional
   downstream tools such as Origin.
7. Keep Origin or other GUI software as optional downstream polish, not the core
   dependency.

## Cleanup Policy

The project should stay small and legible:

- Keep root documentation in `README.md`, `AGENTS.md`, `DEVELOPMENT_LOG.md`,
  and `skill/SKILL.md`.
- Keep generated outputs in ignored directories only.
- Delete stale mockups, scratch servers, copied app experiments, and old
  one-off prototypes once their useful ideas are folded into the Web app.
- Do not commit local caches such as `.pytest_cache/`, `.ruff_cache/`,
  `__pycache__/`, `.DS_Store`, `.tmp_verify/`, or `outputs/`.
- Run `make clean` when generated output or cache directories start to clutter
  the workspace.
- Update `DEVELOPMENT_LOG.md` during every non-trivial development turn.
