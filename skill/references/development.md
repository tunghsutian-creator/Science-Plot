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

Use `--base BASE_COMMIT` for committed changes, including after a clean commit;
add `--plan-only` to inspect the selection without executing checks. The result
reports resolved base/HEAD and unions committed, staged, unstaged and untracked
paths. Renames/deletions retain both owner endpoints. Tests execute the current
worktree, not a different staged-index image. A clean default comparison reports
`NO_TESTS`, zero executed checks and exit 2; a plan is not a test pass.

Unknown changed owners fail closed; do not compensate with a full-suite fallback.
Run the scoped static type gate when changing a file
declared under `[tool.mypy]` in `pyproject.toml`.
Its exact scope and strictness belong to `pyproject.toml`.
Do not weaken checks or remove coverage to pass a gate.

At handoff, run Doctor for command/runtime changes. Run smoke once at the final
milestone for changes crossing Studio, worker, export, QA, delivery or runtime.
Full pytest and ready-rule acceptance are release/merge gates, not every edit.

For bounded native feedback use `skill/scripts/sciplot smoke --profile quick
--out .tmp_verify/quick_smoke --json`. It performs one real source-bound native
creation/export/QA/delivery path and explicitly defers the complete lifecycle.
Default/full smoke retains the final milestone coverage. Actual native TTS
cases are comprehensive; pure input/request/compile/publication-fault checks
remain focused. Reclassification does not remove release coverage.

Checkpoint recording/reuse is opt-in: `verify --changed --base BASE_COMMIT
--record .tmp_verify/checkpoint --json` executes the selected checks;
`--reuse .tmp_verify/checkpoint` freshly validates per-check original evidence.
Missing, stale or mismatched evidence is `BLOCKED` with no automatic replay or
full-suite fallback. Receipts bind code/tests/resources/config/owner policy,
dependency/toolchain/native/font bytes, raw/golden/inventory membership and
aliases, exit, session finish and successful selected test bodies. Unknown
closure, drift, skips or interruption cannot mint a reusable pass. Evidence
is local and unsigned; keep all requests, logs and private inputs under ignored
storage. Environment values are hashed, not persisted as credentials.

An executable check can survive a documentation-only SHA change when its actual
inputs and scope match; documentation checks and Git whitespace/index checks
still validate their own changed inputs and may prevent a whole-plan reused
PASS. Declared fixture closure is not a fresh access audit or scientific
acceptance. Fingerprint time is separate from command time; directly rerun a
cheap leaf when identity validation costs more. For one frozen snapshot, full
already contains both tiers: do not mechanically run tier + tier + full again.

For a long final gate, `verify --start full --out .tmp_verify/final-full --json`
starts one durable original execution; `verify --status .tmp_verify/final-full
--json` reads its state after a lost transport reply. The directory must be new;
status does not rerun tests or prove evidence reuse. Focused/comprehensive are
also explicit start profiles. `--audit-plugin-dir` and `--audit-out` optionally
bind a frozen local observation plugin and a separate fresh private-audit output;
that observation still requires independent closure review.

Runtime readiness, native fidelity, real-client efficiency, human usability and
journal acceptance are separate claims. Read the advanced guide's test-tier
section only when the exact commands or owner boundary need clarification.

For local-only scientific fixture diagnostics in a source checkout, run
`PYTHONPATH=src:tests .venv/bin/python -m sciplot_core.verification.private_corpus --json`.
The preflight itself does not write fixture data. It uses the existing rule
fixture locations and checks each declared collected pytest parameter
independently. It checks the current pytest collection and returns nonzero
`BLOCKED` with exact relative fixture
paths when inputs are absent, malformed, unsafe, or unmapped. The checked-in
node dependency inventory is preliminary; even when all its declared inputs
exist, the tool remains `BLOCKED` until the inventory is audited as complete.
It does not run test bodies, deselect collected cases, inspect scientific
values, or establish private-corpus acceptance. Doctor's optional fixture
check remains separate from this developer preflight and is not an ordinary-use
prerequisite. The inventory is source-checkout-only and is not packaged in the
installed wheel; invoking the module from a wheel reports `BLOCKED` with a
source-checkout hint.
Pytest collection imports test modules and may execute their collection hooks.

For every non-trivial development turn, update `DEVELOPMENT_LOG.md` with the
change, current state, next steps and verification before reporting.

Retained GUI/editor/Intake compatibility is not permission to delete those
surfaces or replace the external-AI product direction.
