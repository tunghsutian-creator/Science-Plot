---
name: sciplot-materials-analysis
description: Create, edit, export and continue source-bound scientific figures through the local SciPlot CLI; also guides changes to the SciPlot project.
---

# SciPlot Materials Analysis

External AI interprets original data and user intent; SciPlot validates and plots
locally without calling a model. Use `skill/scripts/sciplot` and its public
contracts. Keep ordinary plotting work within that interface.

## Select one route

Read only the matching route below, once per session while its contract is
unchanged. Each ordinary route is self-contained; do not load the other routes,
source code, development history or architecture for a routine plotting request.

| User intent | Route |
| --- | --- |
| Change or export an existing ordinary saved figure | [Saved figure](references/saved-figure-edit.md) |
| Plot original data as a new ordinary task | [Create](references/ordinary-create.md) |
| Explicit AI-prepared HDPE/LDPE UDC rheology/TTS suite | [Prepared rheology](references/rheology-prepared.md) |
| Change or debug this project's implementation | [Development](references/development.md) |

For source revisions, groups/comparisons or legacy diagnostics, read only the
relevant section of [advanced workflows](references/advanced-workflows.md).
[External control](references/external-control.md) supplies operation examples
and recovery detail when the live response and chosen route leave a specific gap;
it is not another prerequisite for ordinary work.

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
- Batch the complete authorized change. Let the local transaction own source,
  native document, scientific audit, QA and publication validation.
- Use `task create` for ordinary raw-data plotting and `task style` for explicit
  sample width/color changes. These entries construct requests and bind current
  state locally; do not precede them with schema/context discovery or JSON files.
  Use the returned continuation arguments after reviewing a pending preview.
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
Never invent measurements, average silently, pad/truncate ragged curves or
interpolate missing references. Unit conversion requires its scientific contract.
Merged metadata expansion is explicit and applies only above data. Do not turn
scientific ambiguity into an automatic mapping or a different experiment.

The saved `studio/document.vsz` is visual authority. Use native operations; never
patch VSZ text, automate Veusz clicks, replace raw files, create a one-off plotting
script, or introduce another renderer or document model.

For raw-input plotting, omit `--out` by default. Deliveries belong beside the
original source in `SOURCE_SciPlot/`; hidden `.sciplot/` holds internal evidence.
Do not put user plotting deliveries inside the SciPlot repository or its
`outputs/`. Development evidence belongs under ignored `.tmp_verify/`.
Require Doctor `status=ready` before artifact handoff; reuse current readiness.
Deliver plotting CSVs, PDF/TIFF, editable VSZ and the returned manual-edit launcher.

## Authority

- Live CLI and source-controlled contracts are executable truth.
- `README.md` owns product behavior and the user workflow.
- This skill owns agent routing and verification.
- `docs/ARCHITECTURE.md` owns module and dependency boundaries.
- `DEVELOPMENT_ROADMAP.md` lists unfinished priorities.
- Development logs and Git are historical evidence, not current instructions.

Runtime readiness, native fidelity, real-client efficiency, human usability and
journal acceptance are separate claims. Local timings and output bytes do not
measure external AI tokens or end-to-end waiting.
