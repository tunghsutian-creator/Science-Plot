# SciPlot Canvas M3 Provider Lifecycle and UI Audit

Status: implemented and verified with an injected deterministic provider,
2026-07-17. This audit proves the provider-neutral integration boundary and
visible Canvas lifecycle. It does not prove production-model scientific
quality or complete M3.

## Outcome

For a `CanvasOperationBatch`, SciPlot now has one provider-neutral Assistant
path from user intent to a visible, reversible proposal:

```text
intent + bounded Canvas context
  -> hash-bound AssistantRequest
  -> off-GUI-thread provider progress
  -> typed AssistantResponse
  -> zero-mutation proposal preview
  -> Accept or Reject
  -> live Canvas operation through DocumentController
  -> Commit, latest-batch Undo, or exact whole-turn rollback
```

The Canvas remains the primary surface. Assistant work stays in the existing
trailing utility pane and never becomes a detached chat window or a second
document model.

## Interaction decision

The action hierarchy is state-driven:

| State | Primary action | Secondary actions |
| --- | --- | --- |
| no active turn | Ask Assistant | none |
| provider running | none | Stop |
| proposal ready | Accept & Apply | Reject |
| accepted change | Commit Turn | Undo Batch, Roll Back Turn |

Only one visually primary action is present in each state. While a proposal is
pending, the pane prioritizes provider understanding, warnings, and complete
Before/After values; repeated shared-context detail is collapsed out of the
vertical decision path. Long values wrap instead of creating horizontal
scrolling.

The design follows current platform and open-source principles:

- [Apple undo and redo](https://developer.apple.com/design/human-interface-guidelines/undo-and-redo)
  for predictable reversal and explicit change consequences;
- [Apple progress indicators](https://developer.apple.com/design/human-interface-guidelines/progress-indicators)
  for progress adjacent to the active work and cancellability;
- [Apple split views](https://developer.apple.com/design/human-interface-guidelines/split-views)
  for a primary canvas with a subordinate utility pane;
- [Apple color](https://developer.apple.com/design/human-interface-guidelines/color)
  for semantic state that does not rely on color alone;
- [Zed Agent Panel](https://zed.dev/docs/ai/agent-panel) for bounded assistant
  work beside, not on top of, the artifact;
- [VS Code notifications](https://code.visualstudio.com/api/ux-guidelines/notifications)
  for non-modal, contextual progress and failure feedback;
- [GNOME adaptive layouts](https://gnome.pages.gitlab.gnome.org/libadwaita/doc/main/adaptive-layouts.html)
  for structural adaptation rather than squeezing pane contents.

These sources inform behavior and hierarchy. The implementation retains
SciPlot's existing Qt palette, typography, spacing, controls, and adaptive
Inspector instead of importing another product's decoration.

## Provider and data boundary

The frozen contracts are:

- `AssistantProviderDescriptor` for stable provider identity and typed
  capabilities;
- `AssistantRequest` for transaction ID, base revision, intent, allowed output
  types, structured context, and canonical payload hash;
- `AssistantProgressEvent` for contiguous, identity-bound progress;
- `AssistantResponse` for one typed proposal or an explicit confirmation,
  repair, or cancellation state;
- `AssistantRequestRecord` for durable lifecycle state inside
  `CanvasTransaction` and `CanvasSession` version 5.

Only `CanvasOperationBatch` and `DataMappingProposal` are valid proposal
payloads. Responses must match the exact request ID, transaction, provider,
base revision, and request SHA-256.

Provider context is a closed, bounded, zero-trust payload. It may contain the
current selection, aggregate document inventory, bounded review summaries,
and sanitized QA state. It rejects unknown nested keys, inconsistent
selection state, declared or embedded raw arrays, and payloads above 256 KB.
Absolute document paths and raw dataset arrays are not sent.

## Runtime and persistence

An injected provider runs in a dedicated Qt thread. The GUI thread owns the
document and receives only typed queued events. Progress sequence, request
identity, provider identity, response hash, and base revision are checked
before the event reaches transaction state.

Cancellation is cooperative. If the provider returns a proposal after the
token is cancelled, SciPlot converts the result to a typed cancelled response
and records that the late proposal was discarded. Late queued progress cannot
turn a cancelled request into a failure.

Request start, progress, cancellation, completion, preview persistence, and
failure are atomic at the Canvas session boundary. If any validation or save
step fails, the previous session snapshot is restored. On reopen, an abandoned
running request becomes interrupted and the transaction pauses for explicit
recovery rather than pretending the remote computation still exists.

## Visual audit

Fresh same-turn evidence was captured from the real Qt workbench. The initial
state exposed four concrete problems: horizontal scrolling, a clipped state
chip, a clipped Ask button, and two simultaneous blue primary actions. The
current state removes all four and keeps the full semantic proposal visible.

Evidence paths:

- baseline:
  `.tmp_verify/m3_provider_ui_baseline/canvas_assistant_probe_3hz4d8bi/assistant_proposal.png`;
- corrected proposal:
  `.tmp_verify/runtime_smoke_provider_ui_final3/runtime_smoke_rmv4swxy/canvas_assistant/canvas_assistant_probe_9gb5shcl/assistant_provider_proposal.png`;
- focused final proposal:
  `.tmp_verify/m3_provider_ui_loop_v6_wrapper/canvas_assistant_probe_l0wqed6g/assistant_provider_proposal.png`;
- same-size baseline/current comparison:
  `.tmp_verify/m3_provider_ui_final_comparison.png`.

The ignored screenshot paths are repeatable engineering evidence, not shipped
product assets.

## Adversarial evidence

The focused provider lifecycle probe passes `29/29`. It covers:

- real composer submission through the injected provider thread;
- contiguous progress and visible working state;
- request/response hash and revision binding;
- zero-mutation proposal preview;
- live accepted redraw and exact whole-turn rollback;
- cooperative cancellation and rejection of a deliberately late result;
- bounded window shutdown when a provider does not expose a Stop action;
- provider-disabled operation;
- nested raw-array and raw-array-declaration rejection;
- detached request/session serialization so an exposed copy cannot alter the
  canonical request hash or persisted transaction;
- request-record, request-hash, base-revision, progress-sequence, and untyped
  output fault injection.

The cumulative pure Canvas contract passes `32/32`. Runtime smoke version 14
passes `30/30`, including the Assistant `29/29`, deterministic mapping
`50/50`, exact-current save/reopen and PDF/TIFF export, QA, delivery, source
immutability, relocated launchers, and delivery-hash failure rejection.

No independent subagent tool was callable for this increment. The review used
a separate adversarial pass, fault injection, fresh screenshot comparison, and
the full runtime gate; this is not represented as independent review.

## Honest remaining work

- add a production model-provider adapter behind the frozen boundary;
- execute a user-confirmed `DataMappingProposal` from its Canvas decision card
  through the existing deterministic executor and receipt workflow;
- run the six canonical natural-language tasks with a production provider;
- accumulate real user sessions for M2/M6 cutover evidence;
- keep Veusz `MainWindow` as a recovery surface until the user accepts the
  retirement gate;
- implement native M4 composition without raster panel assembly.
