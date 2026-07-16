---
name: sciplot-materials-analysis
description: Deterministic materials-science plotting with Veusz VSZ editing, artifact QA, delivery, and optional assisted rule/data repair.
---

# SciPlot Materials Analysis

Use the repository CLI. Do not make one-off Matplotlib figures or copy style,
axis, legend, unit or extraction constants into ad-hoc scripts. Veusz is the
only production renderer; `studio/document.vsz` is the advanced-editing truth.

## Active development direction

For product-development work, read `DEVELOPMENT_ROADMAP.md` and
`docs/SCIPLOT_OPERATION_FLOW_PLAN.md` before changing the GUI, AI integration,
annotations, composition, or Studio ownership. The current Veusz MainWindow
and browser Result Review are protected transition baselines, not the final
frontend.

The target is a focused native SciPlot Canvas that embeds Veusz `Document` and
`PlotWindow`, sends both user and AI edits through typed operations, and keeps
the current VSZ as visual authority. Do not rebuild every arbitrary Veusz
property, add a second renderer, automate the Veusz GUI with mouse clicks, or
remove the Advanced Editor recovery route before the roadmap's real-use
retirement gate passes.

## Daily route

1. Check readiness:

   ```bash
   skill/scripts/sciplot doctor --json
   ```

   Stop unless `status=ready`.

2. Run the single normal path:

   ```bash
   skill/scripts/sciplot studio INPUT_PATH \
     --out outputs/projects \
     --export pdf,tiff_300 \
     --json
   ```

   When the user or Luna/Codex already knows the experiment and presentation,
   pass explicit intent instead of forcing recognition:

   ```bash
   skill/scripts/sciplot studio INPUT_PATH \
     --rule RULE_ID \
     --template TEMPLATE_ID \
     --out outputs/projects \
     --export pdf,tiff_300 \
     --json
   ```

   `--rule` bypasses automatic recognition and must name a ready rule.
   `--template` remains optional and independently user-selectable.

3. If advanced correction is needed, open `PROJECT/Open_in_Veusz.command`,
   save the VSZ, then export the exact current document:

   ```bash
   skill/scripts/sciplot studio PROJECT --export pdf,tiff_300 --json
   ```

   For a standalone Veusz master without a SciPlot request, use:

   ```bash
   skill/scripts/sciplot studio FIGURE.vsz \
     --out outputs/standalone_export \
     --export pdf,tiff_300 \
     --json
   ```

   Require `standalone_export.status=passed` and `export_ready=true`. Read
   `standalone_export_receipt.json` and `qa_report.json`. A missing optional
   `.spec.json` must be reported as absent, not treated as an export failure.
   This route proves exact-current export only; it does not establish source
   provenance, transform lineage, or a complete SciPlot project delivery.

   For the experimental M1 native editor, use:

   ```bash
   skill/scripts/sciplot canvas PROJECT_OR_VSZ
   ```

   It embeds the exact-current Veusz PlotWindow in the SciPlot Qt shell and
   provides selection, bounded visible-text editing, Save/Undo/Redo,
   Export + QA, explicit recovery, and an `F9` inspector toggle. Advanced
   Editor is under `More` as a recovery route. Do not describe this M1 shell as
   the complete M2 daily editor or switch the normal `studio` entrypoint yet.

4. Before reporting success, read the returned state, current VSZ hash,
   `manifest.json`, `review.html`, figures, `tables/analysis_metrics.csv`, QA and
   `delivery/`. Require `state=ready`, `qa.status=passed` and
   `delivery.complete=true`.

Generated `.command` launchers support `--check` for a non-interactive real
Veusz load check. They resolve SciPlot through `SCIPLOT_REPO`, an enclosing
checkout, the generation-time fallback, or an installed `sciplot` command.
For an isolated development worktree, keep `SCIPLOT_REPO`/`SCIPLOT_SOURCE_ROOT`
on the development source and set `SCIPLOT_RUNTIME_REPO` to the trusted
checkout that owns the compiled Veusz helpers and virtual environment.

## State handling

- `ready`: hand off the reviewed delivery.
- `needs_human_confirmation`: ask only for the unresolved scientific mapping.
- `needs_rule_repair`: inspect intervention/cleanup artifacts, repair the
  semantic rule or recipe, add a fixture/test, and rerun the same command.

The frontend opens in independent mode. There is no user-facing mode switch.
Do not ask the user to switch modes. Luna/Codex is optional and starts only
after an explicit request or a deterministic blocker.

Never turn empty/unreadable data into a placeholder series or fake workbook.
Never allow a pending rule, skipped QA or incomplete delivery to masquerade as
ready. Preserve raw inputs and scientific meaning.

## Before rule work

```bash
skill/scripts/sciplot inspect INPUT --json
skill/scripts/sciplot rules list --json
skill/scripts/sciplot rules show RULE_ID --json
```

`src/sciplot_core/materials_rules.py` owns experiment families, axes, aliases,
units and deterministic metrics. Automatic matching uses fixture-backed ready
rules only; new and pending rules require fixture coverage before production.
Do not expand keyword recognition when the user or Luna/Codex can supply
explicit `--rule` intent reliably.

Use existing recipe families before adding code: `tensile`,
`stress_relaxation`, `rheology_dma`, `thermal`, `spectroscopy`, `scattering`,
`chromatography`, and `metrics_swelling`.

## Expert routes

```bash
# Repeat a confirmed request
skill/scripts/sciplot run plot_request.json

# Stable supported script package
skill/scripts/sciplot autoplot INPUT_PATH --out outputs/autoplot_projects --json

# Folder/real-data acceptance
skill/scripts/sciplot batch INPUT_DIR --out OUTDIR --mode smoke
skill/scripts/sciplot batch INPUT_DIR --out OUTDIR --mode all --tensile-root PATH
skill/scripts/sciplot acceptance rules --out outputs/acceptance --json
skill/scripts/sciplot acceptance 3dpa INPUT_PATH --out outputs/acceptance --json

# Torque event curation
skill/scripts/sciplot curate torque INPUT_PATH --name PROJECT_NAME \
  --out outputs/curation_projects --json

# Browser compatibility confirmation, only when explicitly requested
skill/scripts/sciplot app --out outputs/intake_projects

# Publication contracts and independent QA
skill/scripts/sciplot publication layouts --json
skill/scripts/sciplot publication profile nature_flagship_research_2026_v1 --json
skill/scripts/sciplot qa OUTDIR --profile sciplot_composite_183_v1
```

`acceptance rules` runs the exact Studio/VSZ/export/delivery lifecycle for all
ready rules and writes JSON, CSV and Markdown evidence matrices. A passed
instrument-shaped fixture remains a real-data gap; inspect the evidence tier
before reporting breadth.

Source, Inspect, and Samples are data-confirmation stages, not plot-preview
stages. Result Review appears only after Export or assisted repair produces
rendered artifacts. Do not use an empty plot preview as a placeholder during
import, inspection, or grouping. Read Result Review artifacts (`review.html`,
figures, manifest, metrics, and QA) before reporting output.

## Assisted repair contract

When `intervention_request.json`, `assisted_cleanup_request.json`,
`needs_ai_intervention`, or `needs_rule_repair` appears:

1. preserve raw inputs;
2. write a reviewed `cleanup_result.json` when reshaping data;
3. patch the central rule/recipe rather than create a one-off plot;
4. add a representative fixture and test;
5. rerun deterministic Studio export and inspect delivery.

`publication_intent.json`, `transform_ledger.json`, `journal_profile.json` and
`publication_qa.json` are required review artifacts when present. Do not infer
statistics, omit data, select results for visual strength, or call partial QA
coverage journal compliance.

Default single-figure size is `60x55`. Use wider presets only when selected or
documented by a central rule. Explicit 183 mm composites use 180, 90+90,
120+60, 60+120 or 60+60+60 nominal tracks with recorded gutters; independent
figure queue entries are not implicit panels.
