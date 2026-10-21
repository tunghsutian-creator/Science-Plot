---
name: sciplot-materials-analysis
description: Create, edit, export and continue source-bound scientific figures through the local SciPlot CLI; also guides changes to the SciPlot project.
---

# SciPlot Materials Analysis
External AI interprets original data and user intent; SciPlot validates and plots locally without calling a model. Use `skill/scripts/sciplot` and its public contracts.
Keep ordinary plotting work within that interface.

## Select one route

Read the matching self-contained route once per session while its contract is unchanged.
For routine plotting do not load other routes, source code, history or architecture.

| User intent | Route |
| --- | --- |
| Change or export an existing ordinary saved figure | [Saved figure](references/saved-figure-edit.md) |
| Find and continue an original after source/project movement or copying | [Saved work](references/saved-work-continuation.md) |
| Package selected final figures across projects in manuscript order | [Paper figures](references/paper-figures.md) |
| Package selected ManagedPlot native snapshots with guarded local continuation | [Managed delivery](references/managed-delivery.md) |
| Arrange saved figures and images on one physical page | [Panel assembly](references/panel-assembly.md) |
| Read performance radar units, normalization and direction | [Radar interpretation](references/performance-radar.md) |
| Plot original data as a new ordinary task | [Create](references/ordinary-create.md) |
| Add an original table to an existing Managed XY figure | [Source append](references/source-append.md) |
| Explicit AI-prepared HDPE/LDPE UDC rheology/TTS suite | [Prepared rheology](references/rheology-prepared.md) |
| Change or debug this project's implementation | [Development](references/development.md) |

For source revisions, groups/comparisons or legacy diagnostics, read only the relevant section of [advanced workflows](references/advanced-workflows.md).
[External control](references/external-control.md) supplies operation examples
and recovery detail only when the live response and chosen route leave a specific gap.

## Minimize the agent loop
- Reuse current session results, readiness, capability schemas and bindings until
  the runtime, contract, source or saved document changes. A later session needs
  current state, not a replay of the earlier investigation.
- Follow the returned `next_step`. Use existing evidence first, then a named
  capability section for a missing field, then a relevant reference section.
  Do not repeat discovery merely to reconfirm a successful response.
- On failure, use `reason_code` and the returned `repair.issues`/`issues`, then
  follow the stated continuation. Do not change valid operations for a worker
  timeout. Long diagnostics stay local; open their reference only when the short
  response cannot explain the failure. Local preview timeout recovery is bounded.
- Reuse creation `plot_objects`: inspect capabilities/current values and send legal deltas.
  Export selected prepared figures independently with native authority; do not resend arrays, repeat analysis or recreate optional figures.
- Batch the complete authorized change. Let the local transaction own source,
  native document, scientific audit, QA and publication validation.
- For a known ManagedPlot, start with a compact summary, then read only the
  chosen edit contract or plan an exact text intent. Reuse its plot ID/revision
  and batch other edits in one patch. For unknown or LegacyPlot authority, open
  full; never convert legacy state for this route. `task style` uses this engine.
- Use `task create` for raw-data plotting. Repeated `--source` with small coordinate/stage/display flags keeps composed table work in that same task; the program expands source facts and Managed contracts. Carry explicit unshifted display/statistics requirements with `--curve-display raw_overlay` and `--summary-statistic raw_only|median_iqr|mean_sample_sd|mean_sample_sd_n`; read the Create route's scientific-presentation boundary and check its fixed template method. Confirm the returned source plan and scientific choices, and correct a rejected draft with `revise_intent` in the same task. Never transcribe a FigureTemplate to reproduce ordinary or multiple-axis defaults.
- `task style` binds explicit sample width/color edits locally; no discovery or JSON file is needed.
  Review a pending preview and use its returned continuation.
- Use `task edit` for a closed common palette/typography/supported legend intent.
  Keep a stable first-call `--task-dir` for reply-loss recovery; retain pending intents.
  Current semantic/native coverage determines supported edits.
- Let a local task command finish within the tool's normal initial wait. For
  `exec_command`, use 10–30 seconds instead of routinely yielding after one second;
  premature backgrounding adds an AI round just to wait for a short native call.
- At successful completion, view the returned final TIFF and deliver. Stop there:
  no extra inspect/audit/export, ad hoc hash or data reconstruction script, test,
  smoke or acceptance run for ordinary plotting. Investigate a reported failure,
  stale binding, missing evidence or visible defect only as far as needed.
- Existing concrete user intent authorizes the matching preview acceptance.
  Inspect its candidate image and scientific audit; bind acceptance to its current
  operation/revision. This is not an additional mandatory human permission step.
  Retry an export in the same task without applying the edit again.

## Shared scientific and delivery boundaries

Preserve raw cells, per-curve order/counts, identities, units and provenance.
Never invent measurements, average silently, pad/truncate ragged curves or interpolate
missing references. Unit conversion requires its scientific contract.
Merged metadata expansion is explicit and applies only above data; scientific ambiguity
cannot become an automatic mapping or a different experiment.

For legacy figures, the saved `studio/document.vsz` remains the complete visual
baseline. An imported SciPlotDocument owns only its explicitly covered semantic
properties; its `legacy_shadow` coverage preserves opaque native state. New edits use that versioned document and the Veusz adapter, with both scientific hashes and
actual native audits. External native saves invalidate the binding. Never patch
VSZ text, automate Veusz clicks, replace raw files, create a one-off plotting script,
or silently promote an incomplete import to full semantic authority.

Managed Template/Binding/Theme creation uses document authority. FigureTemplate v2 composes Views/Scales/Layers/Marks in physical mm; `plot.describe` returns its typed edit contract. Retain raw inputs and `.sciplot_documents`; rebuild disposable artifacts with `plot.export`. Source/transform/executor or scale-domain edits need scientific intent. Reject unknown native state; source-only `task create` remains compatible; its semantic attachment route compiles into this same Managed authority.

For raw-input plotting, omit `--out` by default. Deliveries belong beside the original source in `SOURCE_SciPlot/`; hidden `.sciplot/` holds internal evidence.
Do not put user plotting deliveries inside the SciPlot repository or its `outputs/`.
Development evidence belongs under ignored `.tmp_verify/`.
Require Doctor `status=ready` before artifact handoff; reuse current readiness. Deliver plotting CSVs, PDF/TIFF, editable VSZ and the returned manual-edit launcher.

## Authority

- Live CLI and source-controlled contracts are executable truth.
- `README.md` owns product behavior and the user workflow.
- This skill owns agent routing and verification.
- `docs/ARCHITECTURE.md` owns module and dependency boundaries.
- `DEVELOPMENT_ROADMAP.md` lists unfinished priorities.
- Development logs and Git are historical evidence, not current instructions.

Runtime readiness, native fidelity, real-client efficiency, human usability and journal acceptance are separate claims. Local timings and output bytes do not measure external AI tokens or end-to-end waiting.
