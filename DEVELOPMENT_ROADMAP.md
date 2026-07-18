# SciPlot Veusz-First Development Roadmap

Status: active product roadmap, 2026-07-18.

The original Veusz `MainWindow` is the final daily frontend. SciPlot adds
deterministic scientific preparation, optional selected-object AI, project
status, exact-current QA, export, and delivery to the same live Veusz
`Document`. It does not replace Veusz's object tree, property editor,
Datasets, plot interaction, menus, shortcuts, or native Undo/Redo.

## Current baseline

M6 Veusz-first integration closed at `352049d`.

The certified baseline provides:

- one normal `studio` route into Veusz `MainWindow`;
- one exact-current `studio/document.vsz` visual authority;
- default-hidden, closable Project and AI docks;
- AI visual context from the exact-current rendered page;
- a selected-object, typed `set_setting` capability boundary;
- one native Veusz Undo step for each accepted AI batch;
- exact-current Save, close/reopen, PDF/TIFF, QA, and delivery;
- all 23 ready rules certified through authorized real-data lifecycles;
- `doctor=ready`, runtime smoke, packaged-wheel, and isolated-install gates;
- one coherent `main` worktree with redundant branches removed.

The former Canvas-default cutover, Veusz-retirement plan, fifteen-session
quota, and required Composition round are cancelled. Their code and version-1
evidence contracts may remain readable as compatibility/regression history,
but they do not govern the active product.

## North-star objective

Build a personal daily scientific plotting workbench that:

1. turns raw experimental data into an editable Veusz document;
2. keeps ordinary geometry and low-frequency arbitrary edits fast by hand;
3. uses AI only for ambiguity or bounded high-frequency micro-edits;
4. moves repeated, verified decisions into deterministic rules and QA;
5. preserves raw inputs, explicit transformations, exact-current VSZ
   authority, PDF/TIFF, provenance, and delivery;
6. reports lifecycle success, artifact QA, provenance completeness, human
   validation, and journal-specific compliance as separate claims.

## First-principles decisions

1. **Veusz interaction is the baseline.** Do not rebuild its general editor.
2. **Geometry stays spatial.** Alignment, movement, sizing, and arbitrary
   property work remain native Veusz operations.
3. **Scientific meaning is explicit.** Prefer user-selected rules and
   conservative confirmation over broad keyword guessing.
4. **Execution is deterministic.** Parsing, transformation, rendering, QA,
   export, and delivery remain software contracts.
5. **There is one visual authority.** Manual and AI edits address the same
   exact-current VSZ.
6. **AI shares the native undo boundary.** It does not click the GUI, patch VSZ
   text, execute arbitrary code, or modify raw values.
7. **AI remains optional.** Provider absence never disables supported
   deterministic work.
8. **Evidence is proportional.** A local UI fix does not require inventing
   fifteen sessions; a shared scientific contract change does require affected
   real-data lifecycle evidence.

## M6.1 — Daily-use convergence

Purpose: prove that the completed Veusz-first baseline saves time on real work
without expanding the editor.

### D0 — Product truth and distribution hygiene

- mark M6 complete everywhere;
- make `frontend_default=veusz_mainwindow` explicit and keep the assistant
  independent and hidden by default;
- remove local-only historical audit documents from the GitHub distribution
  index while keeping local copies and Git history;
- keep only explicitly allowed legal/compatibility documents in the minimal
  repository;
- mark the version-1 Canvas session ledger as a legacy compatibility gate;
- remove native composition from required `doctor` readiness;
- keep historical commands callable but hide them from normal CLI help.

Exit:

- `git ls-files -ci --exclude-standard` is empty;
- the minimal-repository CI policy accepts a clean checkout;
- ordinary help emphasizes `studio`;
- `doctor` reports Veusz `MainWindow`, optional hidden AI, and
  `status=ready`;
- old ledgers remain readable without controlling M6.1.

### D1 — Daily result clarity

The Project dock has one result state machine:

```text
editing -> exporting -> ready
                    \-> needs_fix
```

Deep audit state is independent:

```text
current | pending | stale | failed | not_applicable
```

`pending` means a deep source audit has not been recomputed. It must not be
presented as stale when exact-current PDF/TIFF and delivery are valid.

Deliver:

- export-time control locking and visible status;
- no contradictory success dialog and stale project text;
- current PDF, delivery, and VSZ reveal actions constrained to verified local
  evidence paths;
- result actions disabled for old artifacts after a new document edit;
- tampered or missing artifacts produce `needs_fix`.

### D2 — Bounded AI audit

The first daily AI surface remains selected-object-only.

Deliver:

- wording that clearly distinguishes rendered-page context from edit scope;
- proposal confirmation by default rather than implicit auto-apply;
- durable `assistant_history.jsonl` containing only whitelisted metadata,
  request/operation hashes, revisions, and before/after render hashes;
- no PNG/base64, API key, endpoint, absolute path, natural-language intent,
  model understanding, warnings, rationale, or hidden reasoning in history;
- `apply_started` fsynced before document mutation;
- distinct `applied` and `applied_unverified` outcomes;
- immediate release of in-memory base64 request data after terminal states.

History is observational. Veusz native Undo/Redo remains the only user-facing
edit rollback model.

### D3 — Five real daily-use projects

Run five owner-used projects:

1. multi-sample rheology;
2. FTIR or XRD;
3. thermal analysis;
4. mechanical or categorical metrics;
5. scalar field or another advanced figure.

For each:

```text
raw data
  -> deterministic inspect
  -> confirm only unresolved meaning
  -> Veusz manual micro-adjustment
  -> optional selected-object AI
  -> save and close/reopen
  -> exact-current PDF/TIFF
  -> QA and delivery
```

Record only:

- whether completion required a code change;
- recognition/grouping/axis/legend friction;
- whether manual and AI edits survived reopen;
- whether export and delivery completed once;
- whether AI was faster than hand editing.

Exit:

- 5/5 raw inputs unchanged;
- 5/5 final edits retained after close/reopen;
- 5/5 VSZ/PDF/TIFF/delivery exact-current bindings pass;
- zero lost edits, false-ready states, or contradictory status;
- ambiguous tasks require at most one scientific confirmation;
- at least three real AI micro-edits are usable and natively undoable, or AI is
  honestly retained as non-beneficial for that task class.

### D4 — Real-failure-driven repair

Classify repeated problems by owner:

- scientific meaning -> `materials_rules.py` / `semantic.py`;
- common plot behavior -> `policy.py`, Veusz spec, or QA;
- AI gap -> one additional closed typed field or operation;
- UI state -> Project/Assistant bridge, not renderer code.

Fix only P0 integrity failures and high-frequency P1 friction. Promote a
decision into a shared rule only after it repeats naturally. Zero promotion is
correct when no decision repeats.

Verification:

- focused probe for the changed behavior;
- `doctor`;
- runtime smoke;
- affected authorized real-data lifecycle for scientific/rule changes;
- full 23-rule acceptance only when a shared scientific or rendering contract
  changes.

## M6.2 — Use-driven maintenance

Begin only after the five-project pilot.

Potential work:

1. move source audit/export work to immutable snapshots and background workers
   if real projects show blocking latency;
2. split `studio.py` around project/document lifecycle, Qt integration, and
   export publication;
3. split `semantic.py` by experiment-family preparation;
4. split `intake.py` only when the browser compatibility route creates real
   maintenance pain;
5. narrow remaining migrated compatibility imports.

Each extraction changes one owner, preserves public CLI behavior, and passes
smoke plus an affected real project before the next extraction. No big-bang
rewrite is allowed.

## M7 — Future distribution

Only after personal daily use is stable:

- runtime bundling;
- signed/notarized macOS application;
- clean-machine installation;
- update and rollback;
- broader platform support.

Distribution does not preempt daily-use convergence.

## Explicit non-goals

- a second frontend or Canvas-default revival;
- productizing Composition Board or arbitrary figure puzzle assembly;
- duplicating Veusz object/property/Datasets editors;
- general-purpose Illustrator behavior;
- broad autonomous whole-document AI;
- AI modification of raw scientific values;
- AI image review for every already validated deterministic input;
- broad keyword recognition without repeated real evidence;
- public cloud storage or collaboration;
- blanket journal-compliance claims;
- cross-platform distribution before the personal product is stable.

## Engineering gates

For every non-trivial implementation turn:

1. preserve unrelated user changes;
2. update local `DEVELOPMENT_LOG.md`;
3. add or extend a source-controlled probe for changed public behavior;
4. keep one `Document`/VSZ owner and native Undo/Redo;
5. run:

   ```bash
   python -m compileall -q src/sciplot_core src/sciplot_recipes
   skill/scripts/sciplot doctor --json
   skill/scripts/sciplot smoke --out .tmp_verify/runtime_smoke --json
   git diff --check
   ```

6. exercise save, close/reopen, Undo/Redo, and exact export for GUI/document
   changes;
7. test provider-disabled, invalid, stale, interrupted, and rollback paths for
   AI changes;
8. run affected authorized real-data lifecycles for scientific contract
   changes;
9. keep generated outputs under ignored directories;
10. do not claim journal compliance or human daily-use validation from
    synthetic probes.

## Reliability targets

- ordinary local setting-to-redraw p95 below 250 ms, excluding model time;
- 100% native Undo recovery for accepted AI test scenarios;
- zero silent raw-data mutation;
- zero silent replacement of an edited VSZ;
- zero accepted stale AI responses;
- zero ready state for missing, changed, or hash-mismatched current artifacts;
- supported deterministic work remains available without an AI provider.

## Completion definition

M6.1 is complete only when:

1. public and local active documents describe one Veusz-first product;
2. a clean checkout passes repository, doctor, smoke, and focused GUI gates;
3. Project status never confuses audit pending with stale delivery;
4. selected-object AI changes are accurately described, auditable, safe, and
   natively undoable;
5. five real projects finish the full raw-to-delivery lifecycle with no lost
   edits or source mutation;
6. unresolved issues are classified and the next work is selected from real
   friction rather than speculative frontend expansion.
