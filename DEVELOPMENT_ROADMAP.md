# SciPlot Development Roadmap

Status: maintenance mode; no active implementation stage.

Current behavior belongs to `README.md`, agent execution to `skill/SKILL.md`,
and code and module boundaries to `docs/ARCHITECTURE.md`. Completed work and
superseded designs belong to the compact `DEVELOPMENT_LOG.md` summary and Git
history.

## No active development target

The current AI-callable plotting-kernel goal is closed. New inputs continue to
use the documented `rules` -> `plan` -> `studio` / `autoplot` workflow, while
native Veusz remains the editable visual authority. Unknown scientific meaning,
missing unit evidence, and unsupported source layouts must still fail closed;
completion is not permission to guess arbitrary file semantics.

Future work starts only from an explicit user request or a reproduced defect in
the current workflow. A new figure family must remain a thin addition to the
existing rule, typed-source, FigurePlan, Studio, QA, and exact-current delivery
spine. It must not introduce another capability catalog, request schema,
renderer, editor, cache, receipt, or hash ledger.

The existing local browser `app` is an optional initial-intake compatibility
surface, not a separately developed website product. Do not expand or redesign
it unless the user explicitly reopens that scope.

## Deferred

- instrument-cycle DSC onboarding is evidence-triggered, not current unfinished
  implementation work. Reopen it only when an authorized, registered real
  workbook and protocol metadata exist; then define a separate `dsc_cycle`
  rule, source-facts owner, phase-neutral task identities, and full real-data
  acceptance. Synthetic workbooks alone cannot establish readiness;
- no installer or distribution artifact is planned in these architecture
  rounds. Clean-wheel installation, signing, notarization, and clean-machine
  distribution remain temporarily deferred and do not redefine the long-term
  product boundary;
- broader platform support;
- additional selected-object AI operations;
- cloud collaboration;
- generalized multi-figure composition beyond current deterministic metadata.

These items must not displace contract truth, type safety, and runtime
reliability.

## Completion discipline

Use the verification gate in `skill/SKILL.md`. Update `DEVELOPMENT_LOG.md` with
the actual change, current state, and evidence; do not copy completed work back
into this roadmap.
