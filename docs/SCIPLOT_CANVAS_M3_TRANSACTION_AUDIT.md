# SciPlot Canvas M3 Transaction Audit

Status: first M3 increment implemented and verified, 2026-07-17. This is an
engineering audit of the provider-neutral visual-operation transaction kernel.
It is not evidence that a real model is connected or that M3 is complete.

## Decision

The Assistant is a third tab in SciPlot's existing adaptive Inspector utility
pane. It is not a second sidebar, a modal wizard, a detached chat window, or a
hidden renderer.

This keeps the exact-current figure as the primary surface and gives the user
one bounded place to inspect:

- the provider and rationale;
- the transaction and document revisions;
- selection, object inventory, review, and QA context;
- the complete typed Before/After proposal;
- pause, accept, reject, latest-batch undo, commit, and whole-turn rollback.

The UI intentionally has no prompt box or provider selector yet. Presenting a
fake conversation before provider and data-mapping contracts exist would make
the interface promise more than the software can execute.

## Authority boundary

The transaction never becomes a second document model.

| State or artifact | Authority |
| --- | --- |
| raw inputs | immutable source truth |
| `studio/document.vsz` | canonical saved visual authority |
| live Veusz `Document` | exact-current in-memory visual state |
| `CanvasSession` v4 | revision, transaction, recovery, and UI state |
| transaction `baseline.vsz` | hashed exact start-of-turn recovery state |
| transaction review snapshot | hashed start-of-turn review sidecar |
| `operation_journal.jsonl` | append-only audit |
| journal outbox | durable retry state, not a second audit history |

The model/provider may submit only a validated `CanvasOperationBatch`.
`DocumentController` resolves targets, validates expected values, applies the
operation, redraws, snapshots, advances the revision, and records the event.

## Transaction state

```text
active
  -> paused
  -> active
  -> committed
  -> rolled_back
  -> rejected
  -> conflict

active + pending proposal
  -> applying marker persisted
  -> accepted and revision advanced
  -> paused with proposal preserved if apply fails or is interrupted
```

Persisted transaction state includes:

- canonical UUID, provider, rationale, and timestamps;
- base and current revisions;
- hashed VSZ and review baselines;
- baseline saved/exported/document/QA state;
- baseline page and viewport;
- exact pending batch and identity-bound preview;
- applying batch ID;
- accepted batch IDs and revisions;
- undone and rejected batch IDs.

Terminal transactions cannot retain pending or applying work.

## Required invariants

1. Proposal preview is zero mutation.
2. The preview and accepted batch have the same batch ID, provider, base
   revision, rationale, operation count, and target/change structure.
3. Only the active transaction can mutate the document while it owns it.
4. Manual and Assistant changes use the same `apply_batch` gateway.
5. Applying starts only after its marker and journal event are durable.
6. Accepted state is persisted before journal outbox flush.
7. Journal retries deduplicate by event ID.
8. Latest-batch undo is available only within the same recoverable Veusz undo
   boundary.
9. Cross-process recovery uses the hashed transaction baseline, not an
   assumed undo stack.
10. Whole-turn rollback restores the document, review sidecar, page, viewport,
    saved/exported semantics, QA summaries, and a new monotonic revision.
11. Raw source and project `raw/` trees remain byte-identical.
12. Save, export, review promotion, direct visual editing, and Advanced Editor
    launch remain locked until commit or rollback.

## Failure cases found during review

### View navigation caused false rollback failure

The live render fingerprint depends on the displayed page and zoom. The first
implementation restored the VSZ while preserving the *current* viewport, then
compared it with a fingerprint captured at the *starting* viewport. A user
could therefore make rollback fail merely by zooming.

Correction:

- persist baseline page and viewport in `CanvasTransaction`;
- restore them before render verification;
- restore the pre-rollback page and viewport if rollback itself fails.

The regression starts at approximately `3.6715x`, navigates to `4.0215x`,
closes/reopens, and verifies exact rollback to the starting viewport and render.

### Pending preview could be swapped independently

The first persistence contract required `pending_batch` and `pending_preview`
to coexist, but did not prove they described the same proposal.

Correction:

- close the preview schema;
- bind it to batch ID, provider, revision, rationale, operation count, target
  IDs, changes, and pre-apply render;
- reject a missing, malformed, or identity-mismatched preview at load time and
  proposal time.

### Applying conflict could deadlock rollback

A conflict could retain `applying_batch_id`. The UI correctly disabled
rollback while applying, leaving no legal recovery action.

Correction:

- conflict transition clears only the applying marker;
- preserve the pending typed proposal for inspection;
- enable exact whole-turn rollback.

### Screenshot observation changed the tested viewport

The visual probe initially called Fit Page before capture. That made an
observation helper alter transaction state and exposed the same viewport
dependency described above.

Correction:

- force redraw and drain the Qt event queue without changing page or zoom;
- sample screenshot pixels and require a plausible non-empty frame.

### Narrow diff table hid the meaningful suffix

A three-column table forced horizontal scrolling, then a two-column tree still
elided the changed suffix.

Correction:

- use wrapping per-operation cards;
- show complete selectable Before and After values;
- use semantic surface contrast without relying on color alone.

### Journal flush failure left rollback history cleanup late

Rollback cleanup originally happened after outbox flush. If the document state
was already committed but journal flushing failed, stale in-memory history
could remain.

Correction:

- finalize snapshot cleanup and history reset immediately after session
  persistence;
- flush the idempotent outbox afterward;
- report pending journal flush without undoing accepted document state.

## Automated evidence

- Pure Canvas contract: `30/30`.
- Assistant lifecycle: `20/20`.
- The lifecycle covers provider-disabled startup, bounded context, baseline
  integrity, zero-mutation preview, editor lock, pause, live apply,
  latest-batch undo, rejection, stale/invalid/bypass rejection, close/reopen,
  viewport-aware exact rollback, commit, save/reopen, export/QA, interrupted
  apply, recoverable applying conflict, audit uniqueness, raw immutability, and
  stable screenshots.
- Independent task-family runs pass for:
  - FTIR;
  - rheology temperature sweep;
  - flexural curve;
  - TGA;
  - impact metric.
- Runtime smoke version 12 passes `28/28` and includes the Assistant
  transaction as a required release gate.

Primary local evidence:

- `.tmp_verify/m3_canvas_contract_final/`
- `.tmp_verify/m3_assistant_final_binding/canvas_assistant_probe_q1_con7b/`
- `.tmp_verify/m3_final_matrix/`
- `.tmp_verify/m3_final_smoke/runtime_smoke_pwyxxeam/`

These outputs are ignored development artifacts. Their role is repeatable
engineering evidence, not source-controlled test data or real-data acceptance.

## Honest limitations and next M3 increments

This increment does not:

- call OpenAI, Codex, Luna, or another model;
- provide a user-facing natural-language prompt workflow;
- execute a `DataMappingProposal`;
- prove scientific interpretation quality;
- complete the six canonical natural-language acceptance tasks;
- count toward M2's required human daily-use sessions;
- authorize the default `studio` cutover;
- implement the M4 native composition board.

Next M3 work:

1. define the provider request/response boundary without coupling it to one
   model vendor;
2. implement deterministic, source-hash-verified `DataMappingProposal`
   execution and transform-ledger output;
3. expose natural-language request and cancellation only after the provider
   lifecycle is real;
4. run the canonical axis, series, legend, review-promotion, QA-repair, and
   stop/rollback tasks;
5. promote repeated accepted mappings and visual decisions into deterministic
   rules and tests.
