# SciPlot

SciPlot is a local, script-first plotting workbench for polymer and materials
science. It turns raw experiment tables into processed data, reviewable
publication-style figures, QA artifacts, and repeatable request files.

This repository is the source of truth for the SciPlot workflow. The goal is to
make plotting faster than manual figure preparation while staying auditable,
repeatable, and useful without requiring Codex for the normal plotting path.

## Ultimate Goal

Build a practical research plotting system where:

- SciPlot handles data recognition, cleanup, units, axis labels, metrics,
  journal-style defaults, rendering, and QA.
- SciPlot Studio is the daily plotting surface for importing data, creating
  project packages, editing figures, and exporting results through embedded
  GPL Veusz.
- The local Web app remains a compatibility surface for browser-based
  confirmation and older project workflows.
- Optional assisted cleanup can use Codex to patch rules, recipes, fixtures, and
  tests when messy data does not fit the current system.
- The human reviewer confirms sample names, legend order, figure size, export
  options, and final scientific meaning.

The long-term target is not to automate a closed-source drawing program. The
target is a small local plotting system that can beat manual figure software for
polymer science because every plot is reproducible and every correction can
become a reusable rule.

## Daily Workflow

Prefer the project wrapper:

```bash
skill/scripts/sciplot doctor --json
```

```bash
skill/scripts/sciplot studio PATH --out outputs/intake_projects
```

`doctor` must report `status=ready` before alpha use. See
`docs/ALPHA_USER_GUIDE.md` for the current PhD-student daily-use contract.

For a blank desktop editor:

```bash
skill/scripts/sciplot studio --new
```

For the older browser confirmation flow:

```bash
skill/scripts/sciplot quick PATH
skill/scripts/sciplot app --out outputs/intake_projects
```

For a high-confidence supported experiment path that should generate a complete
auditable package in one step:

```bash
skill/scripts/sciplot autoplot PATH --out outputs/autoplot_projects --json
skill/scripts/sciplot one-step PATH --out outputs/one_step_projects --json
```

`autoplot` is the stable daily script entrypoint. It uses the same local
one-step workflow underneath, then writes `autoplot_summary.json` with the
delivery folder, readiness state, structured QA, and optional assistant policy:
Codex is only a cleanup/repair provider for QA failures, low-confidence
semantics, messy inputs, or explicit user requests.
See `docs/STABLE_AUTOPLOT_CONTRACT.md` for the stable script contract.

For development acceptance against the representative 3D PA real-data folder:

```bash
skill/scripts/sciplot acceptance 3dpa PATH --out outputs/acceptance --json
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

One-step loop:

```text
source -> semantic confidence gate -> render package -> structured QA -> ready / needs human confirmation / needs rule repair
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
    "palette_preset": "spectrum_journal_8"
  }
}
```

`sciplot run` writes a reviewable export package containing `manifest.json`,
`analysis_report.md`, `tables/analysis_metrics.csv`, `raw/`, `review.html`,
`revision_brief.md`, PDF figures, and 300 DPI TIFF figures. It also writes a
minimal user-facing `delivery/` folder:

- `{project}.sciplot`
- `{project}.xlsx`
- `figures/{figure}.pdf`
- `figures/{figure}_300dpi.tiff`
- `_sciplot_internal/` for QA, manifests, raw/archive files, and audit trails

If recognition or rendering cannot continue deterministically, SciPlot writes
`intervention_request.json` and `assisted_cleanup_request.json`, marks
`needs_ai_intervention`, and records `operation_mode=assisted_cleanup`. Codex
can be used as the optional assistant provider, but manual cleanup is still a
valid route. After a human or assistant reshapes the data, record the
reviewable result with:

```bash
skill/scripts/sciplot cleanup result RUN_OUTPUT_DIR \
  --cleaned-data cleaned.csv \
  --mapping '{"x":"Time","y":"Signal"}' \
  --confidence 0.82 \
  --confirm \
  --json
```

This writes `cleanup_result.json`. Only a confirmed result with non-low
confidence is marked `ready_for_normal_mode`; use the recorded
`cleaned_data.path` as the next normal SciPlot input.
One-step runs also write `one_step_status.json`, so every output has an
explicit state: `ready`, `needs_human_confirmation`, or `needs_rule_repair`.

Cross-cutting defaults live in `src/sciplot_core/policy.py`: default exports
are PDF plus 300 DPI TIFF, and the default figure size is `60x55`. Wider
presets such as `120x55` remain available when selected by the user or required
by a documented rule. The default production renderer is Veusz: SciPlot turns
its request/options contract into a Veusz document, exports the actual Veusz
PDF/TIFF output, and runs QA on those exported artifacts. The old Matplotlib
production fallback has been removed from the public CLI/API; any remaining
Matplotlib code is retained only inside legacy contract tests and reference
helpers while the Veusz bridge absorbs those rules. Renderer quality thresholds
such as legend footprint, legend canvas bounds, axis usable area, tick overlap,
FTIR bounds, and stacked spacing live in
`src/sciplot_core/_vendor/src/plot_contract.json`. Export QA also rasterizes
PDFs to record visible ink fraction and content bounds, so non-empty files are
not treated as publication-ready unless they contain real visible figure
content.

## Qt Studio And Web Compatibility

SciPlot Studio is the primary local plotting frontend. `sciplot studio PATH`
accepts a raw data file/folder, an existing SciPlot project, a
`plot_request.json`, or a Veusz `.vsz` document. For raw paths it creates a
project package under `outputs/intake_projects`, writes `studio/document.vsz`,
and opens the embedded Veusz editor. SciPlot decides how the figure is drawn:
it uses its data recognition, sample/legend names, template choice, and plotting
contract to generate the official Veusz object tree and datasets. The matching
`studio/spec.json` records the SciPlot-to-Veusz drawing instructions. Veusz then
provides the native object tree, property editor, legend controls, undo/redo,
and export UI for interactive edits after the SciPlot-generated figure appears.

The Web app remains available for compatibility. `sciplot app`, `sciplot
workbench`, and `sciplot intake` open the same browser workflow.

Workflow:

```text
Source -> Inspect -> Samples -> Export -> Result Review
```

Stage rules:

- Source, Inspect, and Samples are data-confirmation stages, not plot-preview stages.
- Result Review appears only after Export or assisted repair produces rendered artifacts.
- Do not use an empty plot preview as a placeholder during import, inspection, or grouping.
- Read Result Review artifacts (`review.html`, figures, manifest, metrics, and QA) before reporting output.
- Read the `delivery/` package before handing off final files.
- Use `revision_brief.md` as the short handoff for optional assisted rule/style revisions.

The UI lets the user confirm source binding, detected rules/templates, sample
groups, sample/legend names, legend order, output directory, figure size, and
export formats. Figure-size choices must stay aligned with the SciPlot contract
presets: `60x55`, `120x55`, `180x55`, `60x110`, `120x110`, and `180x110`.
The interactive plotting roadmap lives in
`docs/INTERACTIVE_PLOT_WORKBENCH_PLAN.md`.

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

`rules list` shows only fixture-backed ready rules by default. Use
`skill/scripts/sciplot rules list --json --all` only for internal rule
development.

Rendering:

```bash
skill/scripts/sciplot run plot_request.json
skill/scripts/sciplot one-step INPUT --out outputs/one_step_projects --json
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
  optional intervention handoff.
- `src/sciplot_core/intake.py`: Web app project/session workflow.
- `src/sciplot_core/intake_static/index.html`: browser UI.
- `src/sciplot_recipes/`: public recipe modules for known experiment families.
- `skill/scripts/sciplot`: preferred wrapper for local use and assisted repair.
- `AGENTS.md`: operating rules for assistant-driven repository work.
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
- For a user-supplied raw data path, prefer `sciplot studio PATH --out
  outputs/intake_projects`; use the Web UI only when the user explicitly asks
  for browser confirmation or Qt Studio lacks a needed confirmation control.
- If `intervention_request.json`, `assisted_cleanup_request.json`,
  `needs_ai_intervention`, or batch `interventions` appears, treat it as
  assisted cleanup/repair: preserve raw data, patch code and tests when needed,
  write or inspect `cleanup_result.json`, then rerun the request.

## Roadmap

Current standalone-operation and cleanup direction:
`docs/INDEPENDENT_OPERATION_AND_CLEANUP_PLAN.md`.

Current alpha user guide:
`docs/ALPHA_USER_GUIDE.md`.

Phase 1: Make Qt Studio the daily plotting surface.

- Route raw files/folders through `sciplot studio PATH`.
- Use Veusz as the default production renderer for `render`, `run`, `recipe`,
  `one-step`, `autoplot`, and Studio exports. Do not add a parallel Matplotlib
  production fallback.
- Keep editing in Veusz's native GUI instead of rebuilding object/property
  panels in SciPlot.
- Keep SciPlot's layer focused on raw-data import, request generation, `.vsz`
  regeneration, QA, delivery, and manifest/ZIP registration.
- Keep the Web app as a compatibility fallback.
- Keep QA and delivery packages as the quality gate for PDF/TIFF outputs.

Phase 2: Strengthen polymer-science rules.

- Finish rheology and impact as the first reliable real-data tracks.
- Expand FTIR, XRD, tensile, thermal, and DMA fixtures from real examples.
- Improve unit normalization, axis naming, legend ordering, and metrics.
- Add more deterministic assisted-cleanup handoffs.

Phase 3: Add interactive figure refinement.

- Keep basic SciPlot controls for axes, ticks, legend, line width, marker size,
  labels, and export presets on the Qt setup side.
- Treat Veusz-exported PDF/TIFF as the QA baseline for Studio and CLI outputs.
- Keep advanced manual edits in the Veusz document unless a setting has a clear
  and safe SciPlot request mapping.

Phase 4: Make assisted cleanup routine.

- Use structured assistant jobs only after user confirmation.
- Inspect `codex_jobs/*/sciplot_codex_handoff.json`, logs, status, and outputs
  before reporting.
- Convert repeated human corrections into tests, rules, recipes, or presets.

Phase 5: Support manuscript workflows.

- Add panel assembly, figure registry, journal presets, and PPT/manuscript
  handoff exports.
- Keep raw data, processed tables, request files, and QA artifacts connected to
  every final figure.

## Next Development Suggestions

1. Broaden the `.vsz` bridge from generic curve tables to more
   recipe-processed material outputs.
2. Preserve Veusz as the native editor and keep SciPlot UI additions to small
   integration actions.
3. Roundtrip safe Veusz edits such as axis ranges, series names, colors, line
   width, and marker size back into project metadata.
4. Add real rheology and impact fixtures from the current polymer dataset.
5. Add a prepared-data export/import route for users who need external
   downstream analysis tools.
7. Keep SciPlot request files plus `studio/spec.json` as the reproducible
   automatic contract, while Veusz remains both renderer and editor.

## Cleanup Policy

The project should stay small and legible:

- Keep root documentation in `README.md`, `AGENTS.md`, `DEVELOPMENT_LOG.md`,
  and `skill/SKILL.md`.
- Keep generated outputs in ignored directories only.
- Delete stale mockups, scratch servers, copied app experiments, and old
  one-off prototypes once their useful ideas are folded into Qt Studio.
- Do not commit local caches such as `.pytest_cache/`, `.ruff_cache/`,
  `__pycache__/`, `.DS_Store`, `.tmp_verify/`, or `outputs/`.
- Run `make clean` when generated output or cache directories start to clutter
  the workspace.
- Update `DEVELOPMENT_LOG.md` during every non-trivial development turn.
