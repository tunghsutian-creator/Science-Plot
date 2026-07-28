# SciPlot Development Roadmap

Status: unfinished product and maintenance priorities only.

Current behavior belongs to `README.md`, agent execution to `skill/SKILL.md`,
and module ownership to `docs/ARCHITECTURE.md`. Completed work and superseded
designs belong to the compact `DEVELOPMENT_LOG.md` summary and Git history.

## P0 — Daily-use evidence

- Complete repeated owner-operated projects across rheology, spectroscopy or
  diffraction, thermal analysis, mechanical/categorical data, and scalar-field
  or another advanced plot.
- Record confirmation count, manual Veusz edits, close/reopen preservation,
  exact-current export, QA/delivery success, and any recurring friction.
- Complete fixture-backed real-data acceptance for
  `performance_comparison`; until then keep it explicit-Studio-only and do not
  promote automatic recognition.
- Treat machine lifecycle, real-data provenance, uncalibrated preview review,
  calibrated final-size readability, and journal compliance as separate
  evidence.

## P1 — Runtime and packaging reliability

- Keep deterministic plotting fully usable without a provider, network access,
  or an open AI dock.
- Make hidden workspace/project allocation and ZIP refresh atomic under
  concurrent runs; cover same-name source slugs and failure injection.
- Validate clean-wheel installation without source-path leakage, then define
  the remaining signing, notarization, and clean-machine distribution work.
- Establish a scoped static type-check baseline without weakening types,
  suppressing existing errors broadly, or confusing `compileall` with type
  checking.
- Decide the retirement window for compatibility facades only after their
  public imports and monkeypatch seams have no supported callers.

## P2 — Ongoing maintainability

- Keep ordinary source files below 400 lines, the first-party import graph
  acyclic, Core independent of GUI presentation, and catch-all module names
  absent.
- Keep the removed `_vendor`, `_bootstrap.py`, retired renderer dependencies,
  and first-party `src.*` namespace from returning.
- Delete modules, commands, probes, and documentation once neither the normal
  Studio route nor a tested compatibility contract references them.
- Keep global visual policy, request validation, source parsing, semantic
  rules, Studio construction, QA, and delivery in their documented owners.
- Add focused characterization tests before changing a public facade or
  extracting another responsibility.

## Deferred

- broader platform support;
- additional selected-object AI operations;
- cloud collaboration;
- generalized multi-figure composition beyond current deterministic metadata.

These items must not displace daily-use reliability, source-adjacent delivery,
or maintainability.

## Completion discipline

Use the verification gate in `skill/SKILL.md`. Update `DEVELOPMENT_LOG.md` with
the actual change, current state, and evidence; do not copy completed work back
into this roadmap.
