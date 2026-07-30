# SciPlot Development Roadmap

Status: unfinished product and maintenance priorities only.

Current behavior belongs to `README.md`, agent execution to `skill/SKILL.md`,
and code and module boundaries to `docs/ARCHITECTURE.md`. Completed work and
superseded designs belong to the compact `DEVELOPMENT_LOG.md` summary and Git
history.

## P0 — Runtime and packaging reliability

- Validate clean-wheel installation without source-path leakage, then define
  the remaining signing, notarization, and clean-machine distribution work.
- Establish a scoped static type-check baseline without weakening types,
  suppressing existing errors broadly, or confusing `compileall` with type
  checking.
- Decide the retirement window for compatibility facades only after their
  public imports and monkeypatch seams have no supported callers.

## Deferred

- broader platform support;
- additional selected-object AI operations;
- cloud collaboration;
- generalized multi-figure composition beyond current deterministic metadata.

These items must not displace runtime and packaging reliability.

## Completion discipline

Use the verification gate in `skill/SKILL.md`. Update `DEVELOPMENT_LOG.md` with
the actual change, current state, and evidence; do not copy completed work back
into this roadmap.
