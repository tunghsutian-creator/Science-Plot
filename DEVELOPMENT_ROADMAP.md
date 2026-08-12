# SciPlot Development Roadmap

Status: unfinished product and maintenance priorities only.

Current behavior belongs to `README.md`, agent execution to `skill/SKILL.md`,
and code and module boundaries to `docs/ARCHITECTURE.md`. Completed work and
superseded designs belong to the compact `DEVELOPMENT_LOG.md` summary and Git
history.

## Active big goal — one AI-callable plotting kernel

Make SciPlot callable by an ordinary external AI through one small, explicit,
machine-readable workflow while keeping native Veusz as the editable visual
authority. DSC, DMA, rheology, mechanics, spectra, and future figure families
must be thin domain additions to the same pipeline, not parallel applications.

The common pipeline is:

```text
discover rule -> inspect source -> resolve scientific source -> FigurePlan
-> shared StudioSeries/spec -> native Veusz document -> exact-current export
```

One existing authority owns each layer: `materials_rules` describes public
capability, `plot_request.json` carries invocation, the typed scientific-source
result owns source transformation, `ResolvedFigurePlan` owns selected tasks,
`studio_render` owns reusable plot construction, and the existing Studio
figure-set/export path owns editable delivery. Do not add another capability
catalog, request schema, renderer, editor, cache, receipt, or hash ledger.

Stages 13–42 are complete and recorded in `DEVELOPMENT_LOG.md`. DSC, TGA, DTG,
UV-Vis, XRD, SAXS, GPC/SEC, and FTIR now exercise the same typed-source,
single-task FigurePlan, semantic-materialization, generic Veusz/QA, and
exact-current delivery spine. The first six share the registered paired-table
reader; GPC and FTIR contribute only source readers and transform-contract
leaves before joining the same single-curve binder. Rheology-temperature and
raw-export-directory frequency planning/preparation share one typed multi-metric
source domain rather than reparsing or pretending it is a single-y transform.
Scoped real-data acceptance can update the existing validated-envelope registry
without rerunning unrelated rules.

## Active Stage 43 — repair the shared paired-curve seam, then add DMA frequency

Before activating another rule, close three shared boundaries. Registered
paired curves must derive machine metric ids from canonical quantity labels,
not from presentation aliases such as `ω` or `G′`. Their selected numeric
columns must share the existing decimal-separator evidence and preserve NA and
nonfinite lexemes, so comma decimals are not silently multiplied and invalid
values cannot disappear during table loading. A request that already owns a
FigurePlan must also fail before writes when a named legacy recipe is supplied;
the existing bounded DMA-temperature recipe remains the sole explicit
exception.

Then register `dma_frequency_sweep` as another thin
`registered_paired_curve` / `registered_single_curve` rule. Its initial public
claim is only the source-declared storage modulus versus angular frequency;
sample identity, units, values, order, and point counts come from the selected
table. The same transform must bind one generic FigurePlan task, preparation,
Workflow, Studio, and analysis without a DMA-frequency parser, plan, bundle,
renderer, catalog, cache, receipt, or hash ledger.

Close the stage with discriminating shared tests for canonical metric ids,
comma-decimal and ambiguous-number handling, NA/nonfinite evidence, and the
pre-write recipe gate, plus one real-fixture DMA-frequency snapshot that
traverses plan, preparation, Workflow, and Studio. Do not encode the fixture's
sample label, point count, frequency, or modulus values in production code.

Stage verification follows changed ownership: one focused invocation while
iterating, one final cross-boundary smoke only when a stage genuinely crosses the
runtime, and Doctor once at handoff. Acceptance and full pytest remain release
gates. Real measured values, sample labels, onset coordinates, repeats, and order
must always come from the current source or explicit user request; they are never
framework defaults.

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
