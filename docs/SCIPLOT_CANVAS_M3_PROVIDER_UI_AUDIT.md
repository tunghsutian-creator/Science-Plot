# SciPlot Canvas M3 Provider Lifecycle and UI Audit

Status: provider-neutral operation and data-mapping decision loops plus the
production OpenAI Responses adapter are implemented, 2026-07-17. Deterministic
and in-memory wire fixtures verify integration, authority, recovery, protocol,
and the visible Canvas lifecycle. No live API key was available, so this audit
does not prove endpoint availability, production-model scientific quality, or
complete M3.

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

For a `DataMappingProposal`, the same pane now continues through source
location, zero-write semantic preview, explicit path-bound confirmation,
background deterministic execution, and a verified separate-Canvas handoff.
The provider proposes meaning; only deterministic code reads or writes data.

The production adapter connects this operation path to the OpenAI Responses
API. It streams a strict structured draft, but SciPlot remains the authority:
the host creates IDs, binds the exact base revision and expected old values,
validates every target/path/value against the selected object's local catalog,
and requires an explicit preview decision before mutation.

## Interaction decision

The action hierarchy is state-driven:

| State | Primary action | Secondary actions |
| --- | --- | --- |
| no active turn | Ask Assistant | none |
| provider running | none | Stop |
| operation proposal ready | Accept and Apply | Reject Proposal |
| accepted change | Commit Turn | Undo Batch, Roll Back Turn |
| mapping source missing | Choose Source Folder | Reject Proposal, Roll Back Entire Turn |
| mapping preview ready | Confirm and Build Project | Reject Proposal, Roll Back Entire Turn |
| mapping confirmed after interruption | Resume Build | Roll Back Entire Turn |
| mapping executed | Open Mapped Canvas | Roll Back Entire Turn |

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
- `AssistantRequestRecord` version 2 for durable provider and mapping state
  inside `CanvasTransaction` and `CanvasSession` version 6;
- `DataMappingConfirmation` version 2 for immutable proposal, request, source,
  normalized source-root, request-path, and output-root authority.

Only `CanvasOperationBatch` and `DataMappingProposal` are valid proposal
payloads. Responses must match the exact request ID, transaction, provider,
base revision, and request SHA-256.

Provider context is a closed, bounded, zero-trust payload. Version 3 may contain
the current selection, aggregate document inventory, bounded review summaries,
sanitized QA state, and the selected object's exact editable Inspector catalog.
Each allowed operation names one stable target ID, setting path, editor type,
current value, choices, and numeric bounds. Read-only data mapping fields are
excluded. The schema rejects unknown nested keys, inconsistent selection,
declared or embedded raw arrays, and payloads above 256 KB. Absolute document
paths, host request IDs, and raw dataset arrays are not sent. Version-2 context
remains readable for persisted audit but is not provider-executable.

## Runtime and persistence

Every provider runs in a dedicated Qt thread. The GUI thread owns the
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

Mapping preview and execution use a separate Qt worker. A persisted
`executing` marker reopens as `confirmed` with the same receipt; a candidate
created before completion is replay-verified and reused idempotently. Before
handoff SciPlot rechecks the execution manifest, mapped VSZ, normalized paths,
and original exact-current VSZ. A change during structural QA is checked again
at commit and enters a recoverable conflict instead of closing the turn.

Path-unbound version-1 confirmation receipts remain parseable for audit only.
They cannot execute, render, or hand off. A fresh explicit version-2
confirmation into a new output root is required to restore authority.

## Production Responses adapter

`OpenAIResponsesProvider` follows the official
[Responses API](https://developers.openai.com/api/reference/resources/responses/methods/create),
[Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs),
and [streaming](https://developers.openai.com/api/docs/guides/streaming-responses)
contracts. Requests use `store=false`, `stream=true`, and a strict JSON schema.
The standard-library transport enforces HTTPS outside loopback tests, validates
the API root, bounds SSE lines/events/output, handles refusal/incomplete/failure
terminal states, interrupts an active read on cancellation, and redacts the API
key from descriptors, exceptions, and persisted evidence.

The provider activates automatically when `SCIPLOT_OPENAI_API_KEY` or the
standard `OPENAI_API_KEY` exists. Model, base URL, reasoning effort, output-token
limit, and timeout have namespaced environment overrides. There is no GUI mode
switch. No key means no provider and no request; explicit `None` remains a
supported deterministic-test injection boundary. Invalid provider
configuration produces a runtime warning and resolves to no provider,
so an optional integration cannot prevent the deterministic Canvas from
opening.

The production provider intentionally advertises only selected-object
`CanvasOperationBatch` proposals and cancellation. It does not advertise data
mapping until SciPlot can give a model a bounded source/header capability
catalog. The already-confirmed deterministic mapping executor is unaffected.

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
  `.tmp_verify/m3_mapping_authority_assistant_probe_final/canvas_assistant_probe_xiurt4j9/assistant_provider_proposal.png`;
- final mapping confirmation:
  `.tmp_verify/m3_mapping_authority_assistant_probe_final/canvas_assistant_probe_xiurt4j9/assistant_mapping_confirmation.png`;
- final mapped Canvas:
  `.tmp_verify/m3_mapping_authority_assistant_probe_final/canvas_assistant_probe_xiurt4j9/assistant_mapping_canvas.png`;
- same-size provider/mapping comparison:
  `.tmp_verify/m3_mapping_authority_assistant_probe_final/canvas_assistant_probe_xiurt4j9/assistant_reference_mapping_comparison.png`;
- production-adapter proposal:
  `.tmp_verify/runtime_smoke_v16/runtime_smoke_obpj9veg/canvas_openai_provider/canvas_openai_probe_rtv6rq6k/openai_provider_proposal.png`;
- production-adapter applied state:
  `.tmp_verify/runtime_smoke_v16/runtime_smoke_obpj9veg/canvas_openai_provider/canvas_openai_probe_rtv6rq6k/openai_provider_applied.png`.

The ignored screenshot paths are repeatable engineering evidence, not shipped
product assets.

## Adversarial evidence

The focused Assistant lifecycle probe passes `41/41`. It covers:

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
  output fault injection;
- close/reopen without invented mapping consent;
- persisted `executing -> confirmed` recovery with the same receipt;
- idempotent reuse after candidate creation but before persisted completion;
- manifest and mapped-VSZ tamper rejection before handoff;
- the actual reopened `Open Mapped Canvas` button path;
- executed-candidate rejection lockout;
- original-VSZ conflict before handoff and during commit QA;
- exact rollback from both conflict boundaries.

The production-provider protocol probe passes `12/12`: environment activation,
HTTPS policy, Canvas auto-resolution, Responses request shape, bounded context,
host-owned typed operations, ordered progress, malformed/unauthorized output,
refusal/incomplete/no-op states, local selection gating, active cancellation,
and credential redaction. The visible production-adapter Canvas probe passes
`8/8` from Chinese natural-language composer input through threaded streaming,
zero-mutation preview, accepted redraw, and exact rollback. Both use an
in-memory HTTP/SSE fixture, not a live model.

The six-document Inspector matrix also passes `8/8` across 87 objects and all
ten bounded object types. Its existing contextual-model gate now constructs
and validates a context-v3 `AssistantRequest` for every selected object and
requires the advertised operations to match the editable manual Inspector
fields exactly; dataset/read-only fields never enter the catalog.

The cumulative pure Canvas contract passes `36/36`; deterministic mapping
passes `55/55`; runtime smoke version 16 passes `32/32`, including Assistant
`41/41`, the two production-provider gates, exact-current save/reopen and
PDF/TIFF export, QA, delivery, source immutability, relocated launchers, and
delivery-hash failure rejection.

An independent read-only reviewer ran twice. The first pass found receipt path
binding, handoff revalidation, original-VSZ authority, executed-state action,
and crash-recovery defects. The second pass found the actual Open-button guard,
a commit-time QA race, legacy-v1 compatibility, and a missing persisted
`executing` recovery test. All findings were corrected and fault-injected; the
same reviewer then reported all prior findings resolved with no remaining
actionable defect or new regression.

The final wheel is
`/private/tmp/sciplot-openai-provider-wheel-20260717-v2/sciplot_core-0.1.0-py3-none-any.whl`
with SHA-256
`bf5ef8a6eb6ddf994304985d13d3dc843fce245725752d5b9fcefa32f165cf76`.
Imports resolve from an isolated target outside the checkout, where this wheel
independently passes Canvas contract `36/36` and the production-provider
protocol probe `12/12` under the dependency-light system Python.

## Honest remaining work

- run a real endpoint/key smoke without weakening credential handling;
- run the six canonical natural-language tasks with a live production model;
- accumulate real user sessions for M2/M6 cutover evidence;
- keep Veusz `MainWindow` as a recovery surface until the user accepts the
  retirement gate;
- implement native M4 composition without raster panel assembly.
