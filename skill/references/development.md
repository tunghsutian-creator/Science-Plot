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

For local-only scientific fixture diagnostics in a source checkout, run
`PYTHONPATH=src:tests .venv/bin/python -m sciplot_core.verification.private_corpus --json`.
This non-mutating fixture check uses the existing rule fixture locations and checks
each declared collected pytest parameter independently. It checks the current
pytest collection and returns nonzero `BLOCKED` with exact relative fixture
paths when inputs are absent, malformed, unsafe, or unmapped. The checked-in
node dependency inventory is preliminary; even when all its declared inputs
exist, the tool remains `BLOCKED` until the inventory is audited as complete.
It does not run test bodies, deselect collected cases, inspect scientific
values, or establish private-corpus acceptance. Doctor's optional fixture
check remains separate from this developer preflight and is not an ordinary-use
prerequisite. The inventory is source-checkout-only and is not packaged in the
installed wheel;
invoking the module from a wheel reports `BLOCKED` with a source-checkout hint.
Pytest collection imports test modules and may execute their collection hooks.

For every non-trivial development turn, update `DEVELOPMENT_LOG.md` with the
change, current state, next steps and verification before reporting.

Retained GUI/editor/Intake compatibility is not permission to delete those
surfaces or replace the external-AI product direction.
