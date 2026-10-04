# SciPlot development

Read `docs/ARCHITECTURE.md` before changing owners. Fix the central owner and add
discriminating coverage. After two unsuccessful attempts at one symptom, stop
guessing: record cause, replacement contract, verification and limitations.
Use `.venv/bin/python` and `skill/scripts/sciplot`. Development evidence belongs
under ignored `.tmp_verify/`; preserve user data and exact-current VSZ authority.

Run the smallest relevant tests while iterating, then:

```bash
skill/scripts/sciplot verify --changed --json
```

Unknown changed owners fail closed; do not compensate with a full-suite fallback.
Run the scoped static type gate when changing a file
declared under `[tool.mypy]` in `pyproject.toml`.
Its exact scope and strictness belong to `pyproject.toml`.
Do not weaken checks or remove coverage to pass a gate.

At handoff, run Doctor for command/runtime changes. Run smoke once at the final
milestone for changes crossing Studio, worker, export, QA, delivery or runtime.
Full pytest and ready-rule acceptance are release/merge gates, not every edit.
Runtime readiness, native fidelity, real-client efficiency, human usability and
journal acceptance are separate claims. Read the advanced guide's test-tier
section only when the exact commands or owner boundary need clarification.

For every non-trivial development turn, update `DEVELOPMENT_LOG.md` with the
change, current state, next steps and verification before reporting.

Retained GUI/editor/Intake compatibility is not permission to delete those
surfaces or replace the external-AI product direction.
