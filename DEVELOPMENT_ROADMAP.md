# SciPlot Development Roadmap

Status: unfinished product and maintenance priorities only.

Current behavior belongs to `README.md`, agent execution to `skill/SKILL.md`,
and code and module boundaries to `docs/ARCHITECTURE.md`. Completed work and
superseded designs belong to the compact `DEVELOPMENT_LOG.md` summary and Git
history.

## P0 — Activate only the source-bound single-curve DSC plan

- Scope the next round to the existing `dsc_curve` publication-digitized CSV;
  explicitly exclude instrument cycles, `dsc_cycle`, DMA, crystallinity, and
  installer/distribution work. Freeze one primary `curve` task,
  `dsc_heat_flow_vs_temperature`, backed by the current publication-digitized
  fixture and its provenance. Its three curves remain `UDC 2`, `UDC 3`, and
  `UDC 4`; do not infer cooling, heating order, raw-instrument status, Tg,
  melting/crystallization identity, enthalpy, or crystallinity.
- Add one DSC source-facts owner that validates the selected CSV and provenance
  hashes, canonical temperature/heat-flow units, exact three-series order, and
  before/after source drift. Resolve the plan from that single load; Studio and
  Workflow may project it but cannot independently select phase or template.
- Remove the current ambiguity in which `dsc_curve` can enter an implicit
  `stacked_curve` phase adapter. With a selected one-task plan, adapter decline,
  phase expansion, or generic fallback must fail before rendering or writes.
- Activate Studio and Workflow together. Both must emit the same task-aware
  VSZ/spec identity, complete the one-task plan, and deliver exactly one VSZ,
  one PDF, and one 300-dpi TIFF. Stale provenance, source drift, forged task or
  spec evidence, and any export/install failure must roll back the whole run.
- Start with failure-first resolver, route, terminal-evidence, publication,
  delivery-membership, and rollback tests. Re-run real-fixture acceptance and
  certify `dsc_curve` only after both entry points pass the same contract.

## P1 — Define the separate instrument-cycle DSC contract

- Give instrument cycle data a separate `dsc_cycle` rule whose presentation
  contract supports `stacked_curve`. Activate it only after an authorized,
  registered real workbook fixture exists. Its default tasks are
  `dsc_cooling` then `dsc_heating`, with identical source-derived sample order
  and cooling primary. Use “second heating” only when protocol evidence
  actually establishes the cycle number; keep the stable machine identity
  phase-neutral.
- Before activation, move phase projection out of the Workflow adapter into one
  shared DSC source-facts/task-source owner. Validate time units, unique
  continuous ramps, direction, duplicate samples, equal phase coverage, units,
  selected workbook/sheet hashes, and observed versus nominal rate. The current
  implicit `dsc_curve/curve` to `stacked_curve` bundle must not be certified as
  a ready plan or retain presentation-selection authority.
- Add ambiguous-ramp, phase/sample coverage, rule-scoped unavailable-reason,
  terminal-evidence, rollback, and exact-package tests only when the authorized
  fixture exists; no synthetic workbook alone may establish real-cycle
  readiness.

## P2 — Reconcile the separate DMA-temperature contract

- Unify the `dma_temperature_sweep` Pa/MPa authority, remove tan-delta aliases
  from storage modulus E-prime recognition, and replace the generic
  `primary_curve/x/y/curve` Study fallback with one exact
  `point_line` temperature x storage-modulus task.
- Preserve the measured negative E-prime point and record any visual
  `y_min=0` clipping explicitly. Register the real fixture and hash, then add a
  single-task source-bound plan only after rule, parser, Study Model, and
  presentation identity agree. Do not route DMA through the rheology
  temperature resolver.

## P3 — Give named recipes an explicit prepare/plan seam

- Named recipes need an explicit prepare/plan seam: rule defaults and
  source-inspection recommendations resolve before rendering, then the recipe
  consumes the plan and cannot independently reselect a template.

## P4 — Reconcile mechanical summary science, then migrate it to FigurePlan

- Resolve the current contract split with fixture evidence before coding:
  Study Model describes `box_strip` with median/IQR/raw points, while the
  mechanical bundle currently emits `bar` summaries using mean/sample-SD.
  Choose and document one scientifically supported summary per mechanical
  metric; do not infer the answer from legacy filenames.
- Add direct value/statistic tests for tensile, compression, and flexural
  summaries, then express the curve and each accepted summary as ordered
  `FigureTask` entries with task-bound terminal evidence.
- Keep the selected presentation identity atomic: derived `bar`, `box_strip`,
  or DSC `stacked_curve` tasks must never be represented as unsupported
  rule/template identities.

## P5 — Complete cross-rule plan persistence

- Make `RequestRenderResult`, result, one-step state, manifest, Autoplot
  summary, delivery evidence, and Intake `last_run` carry and verify the same
  completed plan. Reject a task/result/spec split before manifest, package,
  delivery, registry, or ZIP writes.
- Add forged terminal/result/spec/plan/manifest tests plus real performance,
  impact, rheology, DSC, and mechanical lifecycle controls. Compatibility
  template strings may remain readable but have no selection authority.
- Do not change figure geometry/style, renderer, QA criteria, or delivery
  formats in this persistence round.

## P6 — Type and harden the persisted Autoplot publish verifier

- Audit and add only `autoplot/publish_integrity.py` as the 36th strict
  diagnostic root. Do not add `autoplot/summary.py` or the whole package.
- Resolve its two current strict diagnostics at the one-step state and output
  package reads by reading each mutable manifest value once before narrowing;
  do not cast, ignore, or weaken the exact recorded-versus-recomputed report.
- Add direct owner tests for canonical valid evidence, each independently
  forged recorded projection, malformed nested records, non-boolean ready
  state, absent/complete/malformed FigurePlan, exact checks/reasons, and input
  purity. Do not change Studio, Workflow, GUI, renderer, scientific, or
  distribution behavior in this typing round.

## P7 — Type later read-only summaries one owner at a time

- Continue from evidence about actual persisted-field use, admitting one
  summary owner per round rather than typing a package by import reachability.
- Defer project-manifest, Workflow, GUI, and renderer typing until those direct
  gate consumers are covered and the owned file count remains explicit.

## Deferred

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
