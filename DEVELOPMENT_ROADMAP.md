# SciPlot Development Roadmap

Status: unfinished product and maintenance priorities only.

Current behavior belongs to `README.md`, agent execution to `skill/SKILL.md`,
and code and module boundaries to `docs/ARCHITECTURE.md`. Completed work and
superseded designs belong to the compact `DEVELOPMENT_LOG.md` summary and Git
history.

## P0 — Reconcile mechanical summary science, then migrate it to FigurePlan

- Resolve the current contract split with fixture evidence before coding:
  Study Model describes `box_strip` with median/IQR/raw points, while the
  mechanical bundle currently emits `bar` summaries using mean/sample-SD.
  Choose and document one scientifically supported summary per mechanical
  metric; do not infer the answer from legacy filenames.
- Add direct value/statistic tests for tensile, compression, and flexural
  summaries, then express the curve and each accepted summary as ordered
  `FigureTask` entries with task-bound terminal evidence.
- Keep the selected presentation identity atomic: derived `bar` or `box_strip`
  tasks must never be represented as unsupported rule/template identities.

## P1 — Complete cross-rule plan persistence

- Make `RequestRenderResult`, result, one-step state, manifest, Autoplot
  summary, delivery evidence, and Intake `last_run` carry and verify the same
  completed plan. Reject a task/result/spec split before manifest, package,
  delivery, registry, or ZIP writes.
- Add forged terminal/result/spec/plan/manifest tests plus real performance,
  impact, rheology, DSC, and mechanical lifecycle controls. Compatibility
  template strings may remain readable but have no selection authority.
- Do not change figure geometry/style, renderer, QA criteria, or delivery
  formats in this persistence round.

## P2 — Type and harden the persisted Autoplot publish verifier

- Audit and add only `autoplot/publish_integrity.py` as the 39th strict
  diagnostic root. Do not add `autoplot/summary.py` or the whole package.
- Resolve its two current strict diagnostics at the one-step state and output
  package reads by reading each mutable manifest value once before narrowing;
  do not cast, ignore, or weaken the exact recorded-versus-recomputed report.
- Add direct owner tests for canonical valid evidence, each independently
  forged recorded projection, malformed nested records, non-boolean ready
  state, absent/complete/malformed FigurePlan, exact checks/reasons, and input
  purity. Do not change Studio, Workflow, GUI, renderer, scientific, or
  distribution behavior in this typing round.

## P3 — Type later read-only summaries one owner at a time

- Continue from evidence about actual persisted-field use, admitting one
  summary owner per round rather than typing a package by import reachability.
- Defer project-manifest, Workflow, GUI, and renderer typing until those direct
  gate consumers are covered and the owned file count remains explicit.

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
