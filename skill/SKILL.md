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
2. Choose the route:
   - Plot-ready table: use `sciplot render`.
   - Experiment-family data: use `sciplot recipe NAME`.
   - Ambiguous data: inspect columns/metadata, then choose the closest recipe and record assumptions in the report.
3. Use the v1 recipe names:
   - `tensile`
   - `stress_relaxation`
   - `rheology_dma`
   - `thermal`
   - `spectroscopy`
   - `scattering`
   - `chromatography`
   - `metrics_swelling`
4. Verify every output folder:
   ```bash
   /Users/dongxutian/.codex/skills/sciplot-materials-analysis/scripts/sciplot qa OUTDIR \
     --goldens /Users/dongxutian/Documents/research-plots/tests/goldens
   ```
5. Return the output folder, generated figures/tables, QA status, and scientific assumptions/caveats.

## Commands

```bash
# Inspect and recommendation payload
sciplot inspect INPUT --sheet 0 --json

# Render a specific public template
sciplot render INPUT --template curve --out OUTDIR
sciplot render INPUT --template heatmap --options '{"style_preset":"acs"}' --out OUTDIR

# Run an experiment-family recipe
sciplot recipe rheology_dma INPUT --out OUTDIR
sciplot recipe tensile INPUT --options '{"template":"curve"}' --out OUTDIR

# Validate generated PDFs and golden metrics
sciplot qa OUTDIR --goldens /Users/dongxutian/Documents/research-plots/tests/goldens
```

## Core Rules

- The new repo is the long-term truth source. Do not import from `/Users/dongxutian/Documents/codegod`; that retired project may be deleted.
- Use existing recipe modules before writing new analysis code.
- If a dataset does not fit a recipe, patch the corresponding recipe in `/Users/dongxutian/Documents/research-plots`, add/extend a fixture, add/update a golden or QA assertion, and rerun tests.
- Recipes must write `processed/`, `figures/`, `tables/`, `manifest.json`, and `analysis_report.md`.
- Figures must be produced through `sciplot_core.render_to_dir` or the `sciplot render` CLI. Avoid direct Matplotlib plotting unless you are extending the core renderer itself.
