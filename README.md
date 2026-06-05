# SciPlot Codex Core

Self-contained, headless SciPlot core for Codex-driven scientific plotting,
materials-data cleanup, and publication-style figure generation.

This repository is the long-term source of truth for the local SciPlot workflow.
It replaces the retired `codegod` app checkout and must remain usable without
Xcode, the macOS app, a sidecar server, or any external application process.

## What This Project Does

SciPlot Codex Core turns tabular scientific data into checked plotting
artifacts. It is designed for materials-science workflows where a Codex agent or
local script needs to inspect raw experiment tables, choose an appropriate plot
template, render figures, and verify that the generated PDFs are structurally
valid.

The project provides:

- A Python CLI named `sciplot` with `inspect`, `rules`, `render`, `recipe`,
  `run`, `curate`, `batch`, `intake`, and `qa` commands.
- A lightweight local Web intake UI for building repeatable plotting project
  packages from dragged files and named sample groups.
- A thin public wrapper around the migrated SciPlot renderer under
  `src/sciplot_core`.
- Generic v1 materials recipes under `src/sciplot_recipes` for tensile,
  rheology/DMA, thermal, spectroscopy, scattering, chromatography, stress
  relaxation, and swelling/metrics workflows.
- A contract-driven plotting core with templates, journal-style presets,
  palettes, size presets, layout policy, tick policy, and render QA.
- A materials-science rules registry that records experiment aliases, default
  axes, unit conversion/display policy, and common analysis metrics.
- A Codex skill wrapper in `skill/` so agents can call the same local CLI
  instead of reimplementing plot styling or parsing rules.

In plain terms: give it a CSV, TSV, TXT, XLS, or XLSX table; it can inspect the
shape of the data, recommend a plotting template, render a publication-style PDF,
and run basic QA checks on the output.

The public wrapper also adds SciPlot-specific semantic recognition for common
materials workflows. It is driven by `src/sciplot_core/materials_rules.py`, where
high-polymer/materials plot families define their aliases, axes, units,
preferred curves, and deterministic summary metrics. This layer lives outside
`_vendor/` so Codex can patch recognizers, preprocessors, and rules without
touching the migrated renderer black box.

## Operating Model

This project is meant to be script-first and agent-assisted. The Python modules
and CLI are the main workers. Codex should use them to do repetitive scientific
plotting work, inspect generated artifacts, and make small recipe changes when a
dataset does not fit the existing workflow. Human review remains the final gate
for scientific meaning, visual clarity, and publication fit.

Default loop:

```text
inspect -> recipe/render -> qa -> human review -> revised request/script -> rerun
```

For repeatable figure revisions, keep each run's choices in a request file and
run it through the workflow command:

```bash
sciplot run plot_request.json
```

Example `plot_request.json`:

```json
{
  "recipe": "auto",
  "input": "data/frequency_sweep.xlsx",
  "output": "outputs/run_001",
  "exports": ["pdf", "tiff_300"],
  "render_options": {
    "style_preset": "nature",
    "palette_preset": "colorblind_safe"
  },
  "review_notes": [
    "Use a log-scaled frequency axis",
    "Move the legend outside the plotting area"
  ]
}
```

`sciplot run` writes a reviewable export package containing a vector PDF, a 300
DPI TIFF bitmap, `request_snapshot.json`, `manifest.json`, `analysis_report.md`,
`tables/analysis_metrics.csv`, `raw/`, and `review.html`. Write revised outputs
to a new directory, for example `outputs/run_001` and `outputs/run_002`, and use
those artifacts to compare what changed.

If auto-recognition cannot map a file to a supported semantic family, SciPlot
writes `intervention_request.json`. Codex should treat that file as the handoff:
inspect the failing input, patch the semantic recognizer or recipe preprocessor,
add a simulated fixture, run tests, and rerun the request. The user should not
need to modify project code during normal plotting.

## Quick Start

The fastest path uses the bundled `Makefile`:

```bash
make setup     # create .venv and install the package + dev tools
make demo      # render the bundled example and run QA on it
make workbench # open the drag-and-drop workbench in a browser
```

Run `make` on its own to list every target (`setup`, `demo`, `test`, `lint`,
`fix`, `workbench`, `clean`).

The equivalent manual steps:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'

.venv/bin/python -m sciplot_core.cli inspect examples/curve_table.csv --json
.venv/bin/python -m sciplot_core.cli render examples/curve_table.csv \
  --template curve \
  --out .tmp_verify/render
.venv/bin/python -m sciplot_core.cli qa .tmp_verify/render \
  --goldens tests/goldens
```

Installing the package also exposes the console script:

```bash
.venv/bin/sciplot inspect examples/curve_table.csv --json
```

## Intake UI

Use `intake` when a human wants to sort files into named sample groups before
Codex renders figures. `workbench` is an alias for the same local GUI:

```bash
sciplot intake --out outputs/intake_projects
sciplot workbench --out outputs/intake_projects
```

For the Codex-first workflow, pass the data path directly. SciPlot prepares a
session, pre-fills the recommended data type, plot type, and sample groups, then
opens the same local UI:

```bash
sciplot prepare PATH --out outputs/intake_projects --json
sciplot intake PATH --out outputs/intake_projects
```

The local page is a Codex-aware Plot Canvas workbench:

```text
Source -> Inspect -> Samples -> Export -> Codex Runs
```

Workbench stage rules:

- Source, Inspect, and Samples are data-confirmation stages, not plot-preview stages.
- Use them to confirm source binding, detected rules/templates, grouping, sample names, and legend order.
- Do not use an empty plot preview as a placeholder during import, inspection, or grouping.

The export step lets the reviewer choose the run output directory, figure size,
and export formats before a request is written. Figure-size choices follow the
SciPlot contract presets: `60x55`, `120x55`, `180x55`, `60x110`, `120x110`, and
`180x110`, so panel frames keep their shared physical alignment in assembled
figures. The Web UI writes a project folder and ZIP package containing `raw/`,
`intake_manifest.json`, a `.sciplot.json` project file, `plot_request.json`, and
rendered figures from the selected request options. The request can also be
rerun through the normal script-first route:

```bash
sciplot run outputs/intake_projects/PROJECT/plot_request.json
```

Result review rules:

- Result Review appears only after Export or Codex produces rendered artifacts.
- Read Result Review artifacts (`review.html`, figures, manifest, metrics, and QA) before reporting output.

Known experiment types are backed by the local materials rule registry. Unknown
entries are allowed as intentional handoff points for Codex intervention and
future rule coverage.

If a render writes `intervention_request.json`, reports `needs_ai_intervention`,
or fails during render/QA, the GUI exposes a `Run Codex` handoff. That button
writes `codex_jobs/JOB/sciplot_codex_handoff.json` inside the intake project and
starts `codex exec` with workspace-write sandboxing. Codex jobs record JSONL
stdout, stderr, status, and the final message; no background Codex work starts
until the user presses the button.

The first prepared workflows include tensile export folders such as
`.is_tens_Exports` and torque-rheometer text exports with `Screw Torque` columns.
Torque files can use the reviewable curation route:

```bash
sciplot curate torque PATH \
  --name PROJECT_NAME \
  --out outputs/curation_projects \
  --json
```

The torque curation command writes a named project package with source files,
absolute source paths, `curation/torque_selection.json`,
`processed/torque_curated_plot_data.csv`, `curation/torque_review.html`,
`plot_request.json`, a `.sciplot.json` project file, and a ZIP archive. The
default event detector selects the final feed-peak, mixing, and discharge-drop
segment rather than a fixed-duration tail. Codex can run the generated request
directly, then the same project package records the generated PDF, 300 DPI TIFF,
metrics, and QA state.

## CLI Workflow

### Inspect Data

Use `inspect` when you have a table and want SciPlot to classify it and rank
plot templates.

```bash
sciplot inspect examples/curve_table.csv --json
```

The inspection payload includes the detected model, role hints, ranked template
recommendations, default render overrides, a short explanation, and
`sciplot_semantics` with the project-level experiment family when available. The
semantic payload includes `rule_id`, `axis_plan`, `unit_plan`, `analysis_plan`,
`available_metrics`, and `missing_requirements` so Codex can choose curves and
labels by reading local rules instead of re-deriving them.

### Inspect Materials Rules

Use `rules` when Codex needs to know how this project handles a materials plot
family before rendering.

```bash
sciplot rules list --json
sciplot rules show rheology_temperature_sweep --json
```

Rules cover rheology/DMA, mechanical tests, thermal analysis, spectroscopy,
scattering/diffraction, GPC/SEC, conductivity, swelling/gel metrics, DLS, and
BET-style curve data. A rule records the default x/y axes, display labels,
supported unit conversions, reverse-axis policy, optional `y_metric` choices,
and common analysis outputs such as tensile modulus/strength, normalized stress
relaxation `t50`, creep final compliance, TGA `T5/T10`, and spectral peak
summaries.

### Render a Plot

Use `render` when the source table is already plot-ready.

```bash
sciplot render examples/curve_table.csv \
  --template curve \
  --options '{"style_preset":"nature","palette_preset":"colorblind_safe"}' \
  --out outputs/curve
```

The renderer writes PDF outputs and returns JSON with output paths and QA
reports. Options may be passed inline as JSON or loaded from a file with
`--options @path/to/options.json`.

### Run a Materials Recipe

Use `recipe` when the input belongs to an experiment family and should produce a
standard artifact folder.

```bash
sciplot recipe tensile tests/fixtures/polymer_corpus/tensile/dowsil_sample_a_excerpt.csv \
  --out outputs/tensile
```

Available recipe names:

- `tensile`
- `stress_relaxation`
- `rheology_dma`
- `thermal`
- `spectroscopy`
- `scattering`
- `chromatography`
- `metrics_swelling`

Each v1 recipe currently uses the shared material-recipe path in
`src/sciplot_recipes/common.py`: it finds the first table source, copies it into
`processed/`, writes a table preview, inspects the processed data, renders a
figure through `sciplot_core.render_to_dir`, and writes a manifest plus report.

Recipe output layout:

```text
OUTDIR/
  processed/
  figures/
  tables/
  manifest.json
  analysis_report.md
```

### Run a Plot Request

Use `run` when you want Codex or a local script to replay the whole plotting
workflow from a saved JSON request.

```bash
sciplot run plot_request.json
```

The request can use the semantic auto route:

```json
{
  "recipe": "auto",
  "input": "data/creep_utf16.csv",
  "output": "outputs/run_001",
  "rule_id": "rheology_stress_relaxation",
  "y_metric": "normalized_stress",
  "exports": ["pdf", "tiff_300"],
  "review_notes": [
    "Let SciPlot choose the recipe and preprocessing path."
  ]
}
```

Omitting both `recipe` and `template` also enables auto detection. Auto mode
writes the detected `semantic_family`, `rule_id`, final recipe, processed
source, figures, analysis metrics, and QA result into `manifest.json`.

For rheology sweep folders that contain multiple single-sample exports, use the
folder itself as the input. Auto mode treats the folder as a sample-comparison
group: it extracts the same physical metrics from each sample, writes a
renderer-ready comparison workbook plus one sheet per sample, then exports
separate cross-sample figures. Frequency scans currently write
`processed/rheology_frequency_comparison.xlsx`; temperature scans write
`processed/rheology_temperature_comparison.xlsx`.

The request can also choose an explicit recipe route:

```json
{
  "recipe": "rheology_dma",
  "input": "examples/curve_table.csv",
  "output": "outputs/run_001",
  "template": "curve",
  "exports": ["pdf", "tiff_300"],
  "render_options": {
    "style_preset": "nature"
  },
  "review_notes": [
    "Use this package for manuscript and PPT review."
  ]
}
```

or a direct render route by omitting `recipe` and providing `template`.

If `exports` is omitted, SciPlot defaults to `["pdf", "tiff_300"]`.

### Run a Batch Smoke Test

Use `batch` to scan a data folder, pick representative recognizable tables, and
generate reviewable output packages.

```bash
sciplot batch INPUT_DIR --out outputs/vitrimer_acceptance --mode smoke
sciplot batch INPUT_DIR --out outputs/vitrimer_all --mode all \
  --tensile-root "INPUT_DIR/allowed/tensile/root"
```

The batch output writes `batch_manifest.json`, `review_index.html`, and per-run
folders under `runs/`. Smoke mode records skipped SEM/image metadata and tensile
instrument sidecar files, then plots representative table data by materials rule
priority and `semantic_family`. Failed recognitions are recorded under
`interventions` so Codex can patch the project and rerun without asking the user
to edit code.

Use `--mode all` for acceptance passes that should render every recognized table
or export directory instead of one representative per semantic family. Use
repeatable `--tensile-root` values when a folder contains old tensile exports but
only selected tensile subfolders should be processed. Each run archives the exact
source file or source export directory under `raw/` inside the project output.

### Validate Outputs

Use `qa` on a render or recipe output directory.

```bash
sciplot qa outputs/curve --goldens tests/goldens
```

QA checks that rendered PDFs exist, are non-empty, have at least one page, can be
rasterized, and optionally match golden PDF media-box expectations.

## Project Layout

```text
.
  examples/                  Small example input tables
  skill/                     Codex skill metadata and CLI wrapper
  src/sciplot_core/           Public headless core wrapper and CLI
  src/sciplot_core/_vendor/   Migrated SciPlot renderer and Data Studio core
  src/sciplot_recipes/        Materials experiment-family recipe entrypoints
  tests/                     CLI, contract, recipe, QA, and fixture tests
```

Important modules:

- `src/sciplot_core/cli.py` defines the `sciplot` command.
- `src/sciplot_core/render.py` exposes `inspect_payload()` and
  `render_to_dir()`.
- `src/sciplot_core/materials_rules.py` defines the local materials-science rule
  registry for aliases, axes, unit conversion, and common analysis metrics.
- `src/sciplot_core/semantic.py` classifies experiment families and prepares
  supported instrument exports for rendering.
- `src/sciplot_core/workflow.py` runs request files, auto routing,
  preprocessing, exports, metrics, and intervention handoff.
- `src/sciplot_core/qa.py` validates generated PDF outputs.
- `src/sciplot_core/contract.py` re-exports the plot contract API.
- `src/sciplot_core/_bootstrap.py` adds the vendored renderer to `sys.path`.
- `src/sciplot_recipes/common.py` implements the shared v1 recipe artifact flow.
- `src/sciplot_core/_vendor/src/plot_contract.json` is the visual contract for
  templates, styles, palettes, sizes, and QA profiles.

## Plot Contract and Templates

The renderer is contract-driven. Public styles, palettes, size presets, template
defaults, and QA profiles live in the plot contract and should be treated as the
source of visual truth.

Current contract categories include:

- Journal/style presets such as `nature`, `acs`, `science`, `wiley`, and
  `elsevier`.
- Palette presets such as `colorblind_safe`, `okabe_ito`, `tol_muted`,
  `tableau_10`, and `viridis_discrete`.
- Templates for curve, point-line, area, scatter, statistical, heatmap, stacked,
  and related scientific plot families.
- Size presets such as `60x55`, `120x55`, `180x55`, `60x110`, `120x110`, and
  `180x110`.

Do not copy Matplotlib constants, layout heuristics, tick policy, or Data Studio
parsing rules into one-off scripts. Route figures through `sciplot render`,
`sciplot recipe`, or the Python APIs in `sciplot_core.render`.

## SciPlot Materials Analysis Skill

The SciPlot Materials Analysis Skill is part of this project's operating model,
not just external documentation. It binds Codex to this repository by telling the
agent to call the local CLI, reuse existing recipe modules, inspect outputs, and
avoid reimplementing plot styling or parsing rules in ad-hoc code.

The project-local skill wrapper lives at:

```bash
skill/scripts/sciplot
```

When installed into Codex, the same skill is usually called through:

```bash
/Users/dongxutian/.codex/skills/sciplot-materials-analysis/scripts/sciplot
```

That wrapper resolves the repo from `SCIPLOT_CODEX_REPO`, defaulting to:

```bash
/Users/dongxutian/Documents/research-plots
```

It then dispatches to the CLI with `.venv/bin/python` when available, otherwise
`python3`:

```bash
python3 -m sciplot_core.cli "$@"
```

This keeps agent-driven analysis on the same renderer, recipes, and QA checks as
manual local usage.

Agent rules for this repository live in `AGENTS.md`. In short: use
`skill/scripts/sciplot` or the `sciplot` CLI first, inspect `manifest.json` and
`analysis_report.md` before reading code, and treat `_vendor/` as a renderer
black box unless the public wrapper itself must be changed.

## Development

Run the test suite:

```bash
.venv/bin/python -m pytest
```

Run linting:

```bash
.venv/bin/python -m ruff check .
```

Before changing plotting behavior, inspect the related rules, contract, renderer,
and tests. For new dataset handling or an `intervention_request.json`:

1. Add or update a `SemanticRule`, unit policy, or analysis metric in
   `src/sciplot_core/materials_rules.py` when the requested plot family is a
   known materials workflow.
2. Add or update semantic recognition/preprocessing in `src/sciplot_core`.
3. Add a small simulated fixture under `tests/fixtures`.
4. Add or update a test or golden QA assertion.
5. Render through `sciplot run`, `sciplot_core.render_to_dir`, or `sciplot render`.
6. Run `pytest` and, when relevant, `sciplot qa`.

Generated outputs should go under ignored folders such as `.tmp_verify/`,
`outputs/`, or `figures/`.

## Design Notes

- `_vendor/` contains the migrated legacy SciPlot and Data Studio renderer. It is
  intentionally vendored so this repo can operate without the retired app.
- `src/sciplot_core` is the stable public wrapper layer. Prefer importing from
  this package rather than reaching into `_vendor` directly.
- The v1 recipes are intentionally conservative. They standardize artifact
  layout and rendering first; family-specific cleanup, fitting, axes, unit
  display, and derived metrics should start in the materials rules and move into
  recipe modules only when the workflow needs deeper preprocessing.
- The repo should never import from `/Users/dongxutian/Documents/codegod`.
