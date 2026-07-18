# SciPlot Operation Flow and Visual System

Status: active frontend source of truth, revised 2026-07-18. The default and
daily frontend is the original Veusz `MainWindow`. Its object tree, property
editor, Datasets pane, menus, shortcuts, Undo/Redo, `Document`, and VSZ
authority remain intact. SciPlot additions enter only through a dedicated
menu, optional closable docks, and lightweight status integration.

M1 is complete; the M2/M3 Canvas, Review, typed-operation, Assistant,
data-mapping, provider, and QA implementations remain valid engineering
assets and probe history. The earlier plan to promote the standalone Canvas
to the default frontend is **superseded**. Canvas is now an experimental
entrypoint and a source of reusable components; it is not a replacement shell.
M4's automated native-composition baseline and M5's source-controlled
validated envelopes remain historical and technical facts. G0 through G7
continue to describe evidence and promotion gates where useful, but no gate
authorizes a Canvas-default cutover. Distribution remains outside this
personal-product objective.

This document owns the product flow and visual direction for SciPlot's Veusz
integration. `DEVELOPMENT_ROADMAP.md` owns milestone scope and exit gates.
When older roadmap text still describes a Canvas-default future, this
2026-07-18 Veusz-first decision supersedes only that frontend choice; preserve
the roadmap's safety, evidence, exact-current, and lifecycle contracts.

## Product promise

SciPlot is a scientific-figure workflow integrated into Veusz, not a second
general-purpose editor layered beside it. The primary surface is the original
Veusz `MainWindow` and its exact-current figure. SciPlot's data confirmation,
AI assistance, QA, export, provenance, and delivery support that surface
without displacing its established interaction model.

The user should be able to:

1. open raw data, an existing project, or a standalone VSZ;
2. see the real figure in the original Veusz window as soon as a deterministic
   document exists;
3. use the familiar object tree, property editor, Datasets pane, menus,
   shortcuts, and canvas interactions without relearning the application;
4. leave review marks without contaminating publication output;
5. ask AI for help from an optional dock and watch typed operations arrive in
   the same Veusz `Document`;
6. undo or roll back accepted work;
7. export the exact current VSZ to QA-checked PDF/TIFF and delivery artifacts.

There is no user-facing independent/AI mode switch. AI appears only when the
user invokes it or the deterministic pipeline stops honestly.

## First-principles visual decisions

1. **Veusz interaction is the baseline.** Preserve the original object tree,
   property editor, Datasets pane, menu organization, shortcuts, canvas
   behavior, and Undo/Redo semantics.
2. **Add; do not replace.** SciPlot owns one top-level menu, optional closable
   docks, and lightweight status messages. It does not reorder or hide Veusz
   controls to make itself look like a new application.
3. **One document authority.** Manual and AI actions address the same active
   Veusz `Document`, share its Undo/Redo history, and save to the same
   exact-current VSZ. No parallel visual model or shadow document is allowed.
4. **Spatial work stays in Veusz.** Selection, alignment, property edits, and
   other direct manipulation continue to use the original canvas and panels.
5. **State must be readable without color.** Every state uses text and, where
   useful, an icon or shape in addition to color: `ready`, `editing`,
   `needs_human_confirmation`, `needs_rule_repair`, and `conflict`.
6. **The exact-current VSZ remains authoritative.** UI simplification must not
   introduce a second visual model or silently regenerate an edited document.
7. **Optional additions stay optional.** SciPlot docks open only on request or
   when a deterministic path must surface a decision, and can always be
   closed without changing the document.
8. **Power grows progressively.** Keep ordinary Veusz operation unchanged;
   expose SciPlot-specific detail within its own menu and docks.
9. **Micro-adjust before restyling.** Use Veusz and platform fonts, palette,
   focus indication, shortcuts, menus, and accessible names. Limit visual
   changes to spacing, labels, status clarity, and SciPlot-owned surfaces.

## Reference principles

The direction is informed by official platform and open-source guidance:

- [Apple toolbars](https://developer.apple.com/design/human-interface-guidelines/toolbars):
  choose items carefully, group them logically, and move lower-frequency
  actions out of the primary toolbar as width decreases.
- [Apple split views](https://developer.apple.com/design/human-interface-guidelines/split-views):
  a canvas and contextual inspector are a natural split-view relationship,
  with resizable panes and persistent selection.
- [Apple sidebars](https://developer.apple.com/design/human-interface-guidelines/sidebars):
  utility navigation should be showable, hideable, hierarchical only where
  needed, and subordinate to the primary content.
- [Apple undo and redo](https://developer.apple.com/design/human-interface-guidelines/undo-and-redo):
  reversible actions need predictable outcomes and visible confirmation of
  what changed.
- [Apple progress indicators](https://developer.apple.com/design/human-interface-guidelines/progress-indicators):
  progress belongs next to the work it describes and cancellation should be
  explicit when interruption is supported.
- [Apple accessibility](https://developer.apple.com/design/human-interface-guidelines/accessibility/):
  use system colors, support contrast and text scaling, and never communicate
  state with color alone.
- [GNOME utility panes](https://developer.gnome.org/hig/patterns/containers/utility-panes.html):
  subordinate controls belong in a trailing utility pane that can become
  transient or overlay the main view when width is limited.
- [GNOME libadwaita adaptive layouts](https://gnome.pages.gitlab.gnome.org/libadwaita/doc/main/adaptive-layouts.html):
  split views and utility panes should adapt structurally instead of merely
  shrinking their contents.
- [VS Code views](https://code.visualstudio.com/api/ux-guidelines/views) and
  [notifications](https://code.visualstudio.com/api/ux-guidelines/notifications):
  keep contextual actions with their view, limit permanent view count, show
  progress in context, and reserve modal interruption for decisions that
  truly require it.
- [Zed Agent Panel](https://zed.dev/docs/ai/agent-panel): keep model-assisted
  work in a bounded utility surface while preserving the primary editor as the
  place where accepted changes become visible.
- [KDE layout and navigation](https://develop.kde.org/hig/layout_and_nav/):
  group related actions through spacing, keep toolbars contextual, and adapt
  side panes and status bars to window size.
- [Krita canvas-only mode](https://docs.krita.org/en/reference_manual/preferences/canvas_only_mode.html):
  experts need a one-command way to remove chrome and devote the window to the
  artifact.
- [Krita workspaces](https://docs.krita.org/en/reference_manual/resource_management/resource_workspace.html)
  and [Blender workspaces](https://docs.blender.org/manual/en/latest/interface/window_system/workspaces.html):
  task-oriented arrangements can preserve panel layouts without turning every
  control into permanent chrome.

These are inspirations, not licenses to copy platform-specific decoration or
to replace Qt with another toolkit.

## Canonical application flow

```text
Open
  -> deterministic inspect and semantic mapping
  -> confirm only unresolved sample/data meaning
  -> create or load exact-current VSZ
  -> original Veusz MainWindow
       -> select and edit with native object/property/data controls
       -> optional SciPlot Review dock
       -> optional SciPlot AI transaction dock
  -> structural QA
  -> exact-current PDF/TIFF export
  -> artifact QA and delivery
```

### Open

Accepted entry targets:

- raw file or folder;
- SciPlot project;
- `plot_request.json`;
- standalone `.vsz`.

Raw inputs remain immutable. A standalone VSZ can prove exact-current export
and artifact QA, but does not claim project provenance or transform lineage.

### Inspect and Samples

These are data-confirmation stages, not empty plot-preview stages. Show them
only when scientific meaning is unresolved. A high-confidence ready rule
should proceed directly to the generated VSZ in Veusz.

### Veusz document surface

The original Veusz `MainWindow` is the normal document surface:

- native object tree, property editor, Datasets pane, menus, and shortcuts;
- native `PlotWindow`, page navigation, zoom, selection, and editing;
- native Undo/Redo actions and history;
- exact-current page and zoom;
- optional SciPlot selection context where a typed feature needs it;
- typed AI operations applied to the same active `Document`;
- visible dirty, exported, QA, recovery, and conflict state;
- exactly one active `Document`/VSZ authority per editing window.

### Review

M2 provides a non-exported review layer. Its existing implementation is a
reusable capability; when integrated into Veusz it opens as an optional,
closable SciPlot dock rather than replacing the object/property panels. Marks
bind to the page, normalized page, graph, data coordinates, or a selected
stable object.

Review-only marks persist in `.sciplot_canvas/review_annotations.json`; they
do not advance the publication revision, mutate VSZ, or appear in PDF/TIFF.
Text, arrow, rectangle, and ellipse marks can be promoted through one typed,
undoable Canvas transaction into native Veusz objects. Freehand remains
review-only because no equivalent bounded native Veusz object exists.

### AI transaction

M3's standalone Canvas implementation used a third Inspector tab. That is
historical implementation detail. In the current direction, the same
transaction UI becomes an optional, closable SciPlot dock in `MainWindow`
without moving the native Veusz panels. It shows:

- what the assistant understood;
- affected stable object IDs;
- proposed `DataMappingProposal` or `CanvasOperationBatch`;
- live operation progress;
- pause, accept, reject, undo, and whole-turn rollback;
- verification and journal outcome.

The first transaction increment is provider-neutral. With no provider, the
panel states that AI is optional and every M2 workflow remains available.
When a typed provider submits a `CanvasOperationBatch`, the panel presents a
complete wrapping Before/After card before mutation. Save, export, Advanced
Editor, direct manipulation, and review promotion remain locked until the
turn is committed or rolled back.

Each turn persists a hashed exact-current VSZ baseline, review-sidecar
baseline, starting page and viewport, base revision, pending preview, apply
marker, accepted/undone/rejected batch IDs, and a durable journal outbox.
Interrupted apply markers reopen paused. Conflicts clear the apply marker and
preserve whole-turn rollback. Cross-process rollback reloads the verified
baseline into the existing `Document` and `PlotWindow`, restores the baseline
page and zoom, and verifies the exact render before closing the transaction.

AI is a participant in the Veusz document, not a separate hidden renderer or
shadow editor.
Deterministic `DataMappingProposal` execution is available from the Assistant
decision card. SciPlot first shows a zero-write, raw-value-free preview; a
separate user click creates a hash-bound receipt and starts background atomic
execution. Ambiguous source roots stop at a source chooser. Success opens an
isolated mapped project through the standard Veusz entry while the current
window and VSZ remain unchanged.

When an API key is available, the production OpenAI Responses adapter appears
through this same provider-neutral dock without a mode switch. Context version
3 gives the model only the selected object's exact bounded Inspector operation
catalog; the model cannot invent another target or setting path. SciPlot owns
IDs, expected old values, revision binding, validation, preview, acceptance,
application, and rollback. With no key, ordinary Veusz editing and every
deterministic SciPlot workflow remain available; the Assistant dock stays
absent or shows its honest optional state.

### Compose

M4 uses a dedicated task workspace on an exact 183 mm canvas. Standalone
figures are imported as immutable source modules and compiled into native
Veusz page/grid/graph objects. Final raster-panel stitching is prohibited.

The implemented workspace keeps the same authority split as the main Canvas:

- `composition.json` is the exact figure-level layout model;
- source VSZ snapshots are immutable and hash verified;
- users and future AI issue the same typed placement, reorder, layout, height,
  and legend-policy operations;
- the left board provides millimetre rulers, drag/swap slots, module tray,
  keyboard movement, and typed undo/redo;
- the right side embeds and resize-fits the exact-current native composite;
- variants own independent VSZ, archive, export, and delivery lifecycles;
- manual edits block regeneration until explicit archival approval;
- `Export + QA` delivers the exact-current VSZ, PDF, 300 dpi TIFF, physical
  QA, source snapshots, manifests, and hashes.

Compilation aligns graph frames, Arial 7 pt typography, axis/tick and series
strokes, and bold 8 pt panel labels. Shared-axis and visible-legend
eligibility are recorded; absent legends are `not_applicable`, not falsely
reported as shared. The source-controlled M4 probe passes `11/11`. This is
automated contract evidence, not the owner's mixed-family daily-use
acceptance. Runtime smoke version 17 passes `33/33`, including this native
composition lifecycle gate. The current version-18 smoke passes `34/34` after
adding the deterministic-readiness gate.

### Export

Export always means the exact current saved VSZ. A successful project export
requires:

- PDF and 300 dpi TIFF pairing;
- structured and artifact QA;
- matching current/exported/delivery VSZ hashes;
- complete delivery;
- provenance and transform evidence where the project contract requires them.

### Deterministic Ready

Ready is evaluated after the current input has been recognized, mapped,
rendered, checked, and delivered. It is not a provider response or a UI badge
that can be copied from an older project.

The source-controlled registry binds every accepted rule's recognition
conditions, semantic/render contract, and versioned runtime-request policy to
authorized-real-data lifecycle evidence. High-confidence supported input can
proceed directly; a supported medium-confidence match pauses for explicit
confirmation. Pure presentation overrides can remain automatic, but changed
templates, direct recipes, axis semantics, data selection/transforms, fits,
scientific annotations, or split policies leave the certified request
envelope. Missing, stale, low-confidence, mismatched, tampered, or failed-QA
cases stop at repair.

The persisted one-step evaluation is the authority consumed by autoplot.
Autoplot additionally requires matching reported/persisted states, a complete
evaluation kind/version, `contract_current=true`, strict QA `passed`, and
complete delivery. Legacy artifacts without this envelope remain inspectable
but cannot retain `ready_to_use=true`.

This default path requires no AI provider and no routine AI image inspection.
AI remains available for novel meaning, explicit refinement, or rule repair;
it cannot override a failed deterministic gate.

## Evidence protocol and superseded Canvas cutover

The earlier protocol used G0 through G7 to decide whether a standalone Canvas
could replace Veusz as the default frontend. That cutover objective is
superseded. Its session ledger, frozen-build, rollback, scientific-quality,
QA, export, and delivery controls remain useful evidence; they no longer
authorize changing the default away from Veusz.

The former Canvas-default sequence is retained below as historical milestone
context:

1. establish the local, hash-chained session ledger and counting contract
   before any live-model or owner-session result can count;
2. close the hash-bound M5a promotion mechanism without granting a candidate
   runtime authority or allowing AI to promote itself;
3. map all six M3 canonical tasks to the typed capability catalog. The current
   production adapter is selected-object `set_setting` only, so multi-target,
   spatial-legend, annotation-promotion, and diagnostic-repair tasks need
   explicit minimal host capabilities before model quality is judged;
4. run exactly two preregistered scored attempts per canonical task against a
   real production endpoint and preserve first responses and retries.
   Additional diagnostics do not alter the score. Require 12/12 safe
   authority, 2/2 exact cancellation rollback, at least one end-to-end success
   per planning task, at least 9/10 semantically correct first proposals, and
   100% complete lifecycle for accepted work; wire fixtures remain protocol
   tests only;
5. run one real discovery attempt in each of five lanes: rheology/DMA/torque,
   spectroscopy/scattering/chromatography, thermal,
   mechanical/categorical/swelling, and scalar-field/review/composition;
6. fix every authority, data-loss, rollback, stale-export/QA, false-Ready, or
   ordinary/high-frequency Canvas gap, process any naturally eligible M5
   candidate, then freeze one exact release candidate. Its former requirement
   to contain a Canvas-default entrypoint is superseded;
7. collect at least fifteen qualifying real completions on that unchanged
   candidate, at least three per lane. The M2 ten-session gate is an
   intermediate evidence subset and does not authorize a frontend cutover;
8. present the evidence to the owner and promote that identical commit/package
   only after explicit approval. In the current direction, any canary tests
   additive Veusz integration, not a replacement entrypoint.

A qualifying session is owner-operated, real-project work that ends with a
saved and reopened exact-current VSZ, QA-checked PDF/TIFF, complete delivery,
and an explicit outcome. Automated probes, synthetic fixtures, injected
providers, copied outputs, agent-only review, failed attempts, and sessions
do not count. Ordinary use of Veusz `MainWindow` is expected, not a fallback.
Sessions that reveal a SciPlot dock disrupting native selection, object
editing, datasets, shortcuts, or Undo/Redo must fail and drive the next
smallest shared-code fix. Discovery attempts are not part of the final
fifteen. Any runtime, rule, policy, adapter, renderer, package, or
runtime-identity change after freeze creates a new candidate and restarts the
formal count.

The final fifteen also cover the workflows orthogonally: one provider-disabled
completion in every lane; at least three accepted real-AI completions across
three lanes; one confirmed real data-mapping handoff; review sidecar
save/reopen/export isolation and native promotion; and one native composition
create/edit/reopen/export lifecycle. The ledger binds
`review_annotations.json`, mapping execution/ledger evidence, or
`composition.json` whenever that state is authoritative.

The delivery-gate G0 implementation is the `sciplot sessions` command family. Every formal
M3 or M6 run uses one explicit shared ledger and one `round_id`; separate
rounds, provider/model identities, or frozen build identities are reported
independently and cannot be combined into a pass. The sequence is:

```text
sessions preregister
  -> owner performs the declared natural task
  -> exact-current save + PDF/TIFF + QA + delivery
  -> owner actually closes and reopens the declared Veusz/experimental surface
  -> sessions witness
  -> sessions complete
  -> sessions status
```

Before a formal round, `sessions freeze-build` creates a wheel from one clean
commit and verifies that its `RECORD` and package bytes exactly equal the
active runtime. Automated promotion uses `sessions status --require m3|m6`,
not top-level ledger integrity. A pending append blocks every claim until
`sessions recover` proves and completes one unambiguous transaction state.
An installed CLI receives explicit `--repo` and `--veusz-root` paths; it never
infers either authority from the wheel's `site-packages` location.
The release-candidate check uses the non-counting `formal_contract_probe`
scope: it enforces that same clean frozen-build contract from an ordinary
wheel installation while allowing only a declared synthetic fixture. It can
prove the installed lifecycle but can never enter the M3 or M6 cohorts.

The program replays journal prefixes/suffixes, accepted/not-undone AI
transactions, exact rollback evidence, Canvas or composition state, review
promotion, confirmed mapping, source hashes, build/package identity, QA,
exports, and delivery. The owner supplies the semantic first-proposal score and
the physical reopen attestation. Top-level `sessions status=passed` means only
that ledger integrity passed; the quantitative claims remain separately at
`m3.gate_passed` and `m6.gate_passed`. Closed values, full commands, failure
recording, and the local trust boundary are specified in
`docs/SESSION_EVIDENCE.md`.

Confirmed mappings use the complete preregistered source-root directory as
their initial authority. Their final ledger must retain the byte-identical
confirmed mapping step as its prefix and the plotted table as its terminal
snapshot; a proposal ID without this causal chain is not evidence.

The normal Veusz `MainWindow` owns high-frequency and low-frequency document
editing. SciPlot owns only capabilities Veusz does not provide: deterministic
data preparation, AI transaction review, provenance, QA, export orchestration,
and delivery. A gap in those additions is not permission to build a second
general Veusz property editor, canvas, document model, or renderer.

## Window anatomy

### Native Veusz chrome

Keep the existing `MainWindow` structure and interaction positions:

- menu bar and native actions;
- document/object tree;
- property editor;
- Datasets pane;
- native toolbars, page navigation, zoom, selection, and canvas;
- native Save, Undo, Redo, keyboard shortcuts, and status behavior.

SciPlot must not rename, reorder, hide, or duplicate these controls as part of
ordinary launch. Any upstream Veusz layout reset remains available.

### SciPlot menu

Add one clearly named top-level menu for SciPlot-owned actions such as AI
Assist, Review, QA, exact-current export/delivery, provenance, and diagnostics.
Actions use ordinary Qt shortcuts only where they do not conflict with Veusz.
Closing every SciPlot dock must return the window to normal Veusz interaction.

### Optional SciPlot docks

AI, Review, QA, and provenance surfaces are independent, resizable, closable
docks. They open only when invoked or when the deterministic workflow must
surface a blocking decision. They do not replace the object tree, property
editor, or Datasets pane and do not automatically move those panels.

Each dock starts with:

- a clear task/status label;
- only the current task's bounded context;
- complete preview and explicit commit/rollback where a document mutation is
  proposed;
- a direct close action that does not mutate the document.

The standalone M2 prototype covered page, graph, axis, XY series, box plot,
legend, image, contour, colorbar, and native label. That remains a capability
inventory, not a plan to reproduce those property editors inside SciPlot
docks. Native Veusz continues to own ordinary object and dataset editing.
Extracted AI/Review components may use the bounded catalog for context and
typed previews, but a proposed mutation stays staged until explicit acceptance
and then enters the native document history.

Do not lead with absolute filesystem paths or expose every arbitrary Veusz
property. Full paths and technical IDs belong in disclosure, tooltips, or
developer diagnostics.

### Status and messages

- local operation completion uses the status bar or a lightweight inline
  message;
- recovery, stale export, rule repair, and conflict use persistent inline
  messages near the affected surface;
- foreground work does not generate system notifications;
- warning and error states include text and icon/shape, not color alone.

## Adaptive behavior

- Never change the native Veusz panel arrangement solely because the window
  crosses a SciPlot width breakpoint.
- SciPlot docks remember their own size and visibility, respect Qt's native
  docking behavior, and may be closed when space is limited.
- Long SciPlot labels elide or wrap within their dock; they do not force the
  native object/property/data panes to move.
- Existing Veusz full-screen, toolbar, panel, and shortcut behaviors remain
  authoritative. The standalone Canvas `Tab`/`F9` behavior is experimental
  history and is not installed over Veusz shortcuts.

Test full screen, half-screen, two-thirds, and minimum supported window sizes.

## Visual tokens for SciPlot-owned surfaces

The existing M2 palette-backed token layer can be reused inside SciPlot menus,
docks, and messages:

- system UI font; ordinary interface text at or above the platform minimum;
- spacing scale: 4, 8, 12, 16, and 24 px;
- corner radii used sparingly: 6 or 8 px;
- semantic colors derived from `QPalette` with light, dark, and increased
  contrast variants;
- positive, neutral, warning, negative, and selection roles;
- dock and menu icons from the platform or a coherent theme;
- visible keyboard focus for every interactive control;
- accessible names for symbol-only page and zoom actions.

The scientific figure's own colors remain governed by SciPlot publication and
accessibility QA, not by application chrome tokens. These tokens must not
apply a wholesale restyle to Veusz.

## Historical M2 visual and editing kernel delivered

The facts below describe the standalone Canvas implementation and its probes.
They remain useful regression evidence and component inventory, but do not
define the default frontend or justify replacing Veusz interaction.

- application chrome is generated from the active `QPalette`, including real
  dark-palette and increased-contrast variants;
- the inspector is a native dock that floats below 980 px and returns to its
  dock on wider windows;
- inspector visibility, bounded width, contrast preference, active inspector,
  stable-object selection, XY point selection, and structural-QA state persist
  in `CanvasSession` version 6, with safe version-1 through version-5
  migration;
- `Tab`, `Esc`, `F9`, menus, shortcuts, focus indication, and accessible
  control names are covered by the native application probe;
- the selection-driven inspector exposes only the ten bounded scientific
  object types and keeps dataset mappings read-only;
- immediate and staged edits share the typed operation gateway; Apply/Revert,
  navigation, Save, Export + QA, and close preserve an explicit commit
  boundary;
- plot clicks resolve to the nearest supported object, XY point selections
  persist across redraw/reopen, and native label drag becomes one typed,
  journaled operation batch;
- debounced structural QA reports live-document safety while artifact QA stays
  tied to explicit exact-current export;
- normal, dark, increased-contrast, and recovery screenshots are generated
  from the actual Qt workbench;
- the pure Canvas contract passes `21/21`, the representative native app gate
  passes `26/26`, and the six-document contextual-inspector matrix passes
  `8/8` across 87 objects and all ten bounded object types;
- runtime smoke v10 passes `26/26` with 50 accepted live edits, clean reopen,
  exact-current PDF/TIFF, structural and artifact QA, recovery, hash-matched
  delivery, and the theme-render invariance gate.
- the Review workspace supplies five tools and five anchor spaces through a
  display-only overlay backed by a versioned sidecar;
- review-only edits remain outside the publication revision, VSZ, and exports;
- text, arrow, rectangle, and ellipse promotion creates native Veusz objects
  through the same typed, recoverable, journaled operation gateway as other
  Canvas edits; freehand stays honestly review-only;
- promoted defaults use publication-scale text, line, and translucent fill
  values rather than application-UI sizing;
- the pure Canvas contract now passes `26/26`; runtime smoke v11 passes
  `27/27`, including the review lifecycle `20/20`;
- FTIR, rheology, tensile, impact, torque, and TEMP3 scalar-field review
  lifecycles pass `120/120` aggregate checks without mutating their source
  projects or transferring stable IDs away from existing objects.

## Historical M3 reversible Assistant transaction kernel delivered

- the Assistant is a compact third Inspector tab with an explicit
  provider-optional empty state, current-turn summary, bounded context,
  complete wrapping Before/After cards, and pause, accept, reject, undo,
  commit, and whole-turn rollback actions;
- `CanvasSession` version 6 persists a closed transaction state machine,
  verified baseline artifacts, baseline page/viewport, durable journal
  outbox, apply marker, and complete batch history;
- pending previews are identity-bound to the exact typed batch and cannot be
  swapped independently of the operation that acceptance will execute;
- proposals validate without document mutation; accepted batches redraw the
  live Canvas through the same controller gateway used by manual edits;
- ordinary visual edits, review promotion, save, exact export, and Advanced
  Editor launch are blocked while a transaction owns the document;
- same-process latest-batch undo and cross-process exact whole-turn rollback
  are distinct, explicit recovery paths;
- interrupted apply and conflict markers reopen in a reviewable state and
  cannot deadlock rollback;
- pure contracts pass `30/30`; the Assistant lifecycle passes `20/20`; five
  task families pass independently; runtime smoke version 12 passes `28/28`;
- automated probes use a typed provider stub and do not count as human
  sessions or prove real model quality.

## Historical M3 deterministic data-mapping executor delivered

- `DataMappingProposal` version 2 declares exact source hashes, relative
  paths, workbook sheet/header choices, source-column indices, expected
  headers, output roles, sample labels, units, request routing, and only a
  closed set of deterministic transformations;
- proposal payloads cannot authorize themselves. A separate confirmation
  receipt binds the exact proposal, request, and sources before execution;
- preview is zero-write and excludes raw values; execution is atomic,
  idempotent, source-hash verified, and leaves raw files unchanged;
- consumption deterministically reproduces the confirmed outputs and rejects
  changed request patches, effective-input redirection, output metadata or
  bytes, and active or archived lineage tampering;
- every execution creates an isolated standard SciPlot project with
  `plot_request.json`, the exact confirmed base-request snapshot, immutable
  request seed, mapped tables, proposal, confirmation, preview, execution
  manifest, and transform ledger;
- old branch lineage remains available as hash-verified superseded evidence,
  while active lineage starts `confirmed mapping -> regenerated semantic
  preparation`;
- Studio blocks VSZ creation if a confirmed mapped sample would silently
  disappear. Numeric sample IDs remain legend labels and unit/sample metadata
  rows are excluded from curve values;
- external transformations require stable IDs; declared comma-decimal numeric
  roles are normalized deterministically, and numeric sort columns use numeric
  rather than lexicographic order;
- text fields reject boolean/number coercion, while the confirmed request
  snapshot anchors raw authority and lineage even if an adjacent manifest hash
  is changed together with the artifact;
- mapping confirmation is blocked when a source becomes category-only, empty,
  nonnumeric, or lacks finite values in an explicit x/y/z/value role;
- registered headerless FTIR and two-workbook Agilent GPC/SEC sources complete
  VSZ, PDF/TIFF, artifact QA, publication QA, and delivery with
  `ready_to_use=true`;
- the adversarial mapping probe passes `55/55`, including normalized path
  rebinding rejection and legacy-v1 inspection-only migration; runtime smoke
  version 15 passes `30/30`, including the
  mapped-project Studio lifecycle;
- these non-interactive engineering receipts do not count as user confirmation
  or human daily-use sessions.

## Historical M3 provider lifecycle and visible request UI delivered

- closed provider descriptors advertise typed proposal and cancellation
  capabilities without coupling SciPlot to a model vendor;
- every request carries an exact transaction and base revision, a bounded
  intent, a closed context payload, and an allowed proposal-kind set; every
  response is bound to the canonical request SHA-256;
- the context disclosure includes selection, aggregate object inventory,
  bounded review summaries, and sanitized QA only. It excludes raw dataset
  arrays and rejects unknown nested keys or inconsistent selection state;
- the provider runs on a Qt worker thread. Ordered progress is shown in place,
  Stop is cooperative, and a result arriving after cancellation is discarded;
- the Assistant pane now has a real request composer, keyboard submit,
  progress/cancel state, provider understanding and warnings, complete
  Before/After proposal cards, and explicit Accept/Reject decisions;
- action hierarchy follows the transaction state: Ask before a turn, Stop
  while generating, Accept or Reject for a proposal, then Commit, Undo, or
  exact whole-turn rollback after accepted changes;
- only one primary action is shown at a time; proposal content wraps without
  horizontal scrolling, provider/model diagnostics are secondary, and the
  proposal displaces repeated context while the decision is pending;
- request lifecycle persistence is atomic with pending proposal state and
  survives close/reopen without pretending an abandoned provider call is
  still running;
- window close remains bounded when a provider does not expose Stop, and the
  persisted cancellation state prevents a late result from being accepted;
- the provider-disabled Canvas remains fully usable;
- `DataMappingProposal` uses the same Assistant workspace for source discovery,
  zero-write preview, explicit confirmation, progress, retry, rejection, and
  verified handoff;
- source ambiguity requires a visible folder choice; source or request changes
  invalidate confirmation before a write;
- confirmed mapping runs outside the GUI thread, reuses one immutable receipt
  after interruption, writes only an isolated candidate, and opens the result
  in a separate Canvas without changing the original Canvas or VSZ;
- the receipt binds normalized source, request, and output paths. Reopen
  reconciles a persisted `executing` state to the same confirmed receipt, and
  a completed candidate is replay-verified before idempotent reuse;
- an executed handoff rechecks the manifest, mapped VSZ, and original VSZ. A
  concurrent original-VSZ change during structural QA is checked again before
  commit and becomes a recoverable conflict;
- path-unbound v1 receipts remain inspectable but cannot execute, render, or
  hand off; only an explicit fresh v2 confirmation into a new output root
  restores authority;

## Historical M3 production OpenAI Responses adapter delivered

- Assistant context version 3 advertises only the selected object's exact
  editable setting paths, current values, editor types, choices, and bounds;
  version-2 persisted requests remain readable but cannot be sent without the
  new capability catalog;
- the production adapter uses the Responses API with `store=false`, streaming
  SSE, strict JSON-schema Structured Outputs, cooperative cancellation, closed
  local validation, bounded payloads/events, HTTPS, and redacted credentials;
- a provider is resolved automatically only when a configured API key exists.
  There is still no independent/AI mode switch and no-key Canvas behavior is
  unchanged. Invalid provider configuration warns and falls back to the
  independent Canvas rather than blocking launch;
- the host creates all operation/batch IDs, binds the document revision and
  exact expected old value, and rejects unknown paths, duplicate fields,
  malformed JSON, wrong types, out-of-range values, refusals, and incomplete
  output without changing the document;
- protocol evidence passes `12/12`; the visible Canvas lifecycle passes `8/8`
  from natural-language composer input through production-adapter streaming,
  typed preview, accepted live redraw, and exact whole-turn rollback;
- the six-document Inspector matrix remains `8/8` across 87 objects and now
  verifies that every one of the ten bounded object types produces an exact,
  raw-array-free context-v3 capability catalog;
- runtime smoke version 21 passes `37/37`, including Canvas contract `37/37`,
  deterministic mapping `58/58`, session evidence `14/14`, Assistant
  lifecycle `41/41`, and reviewed promotion `28/28`;
- the protocol and UI gates use an in-memory Responses/SSE wire fixture. No API
  key was available, so they do not claim a live API call or production-model
  scientific quality.

Live-endpoint execution, live-model scientific-quality evaluation, and the six
canonical natural-language acceptance tasks remain M3 work.

## Historical M2 implementation order

Completed M2 increments:

1. Extract palette, typography, spacing, focus, and semantic-state tokens.
2. Add adaptive inspector docking/floating and Canvas-only mode.
3. Persist interface state and verify keyboard/accessibility parity.
4. Replace the visible-text prototype with selection-driven page, graph, axis,
   series, legend, appearance, scalar-field, and annotation inspectors.
5. Add structural breadcrumbs, stable selection highlighting, and XY
   data-point selection.
6. Add immediate/staged Apply/Revert semantics, save/navigation protection,
   native label drag, and debounced structural QA.
7. Add the non-exported review overlay and persistent page, graph, data, and
   object coordinate anchors.
8. Add typed review-to-native promotion, undo/redo sidecar recovery, reopen,
   export-isolation, and audit gates.

The former remaining item was to run representative sessions and then migrate
the normal `studio` entrypoint to Canvas. That migration is superseded. The
current work is to inventory these delivered components, extract only the
valuable AI/Review/QA pieces, and prove that their Veusz docks preserve native
interaction and exact-current authority.

## Design acceptance

The Veusz integration is not acceptable because a screenshot looks polished.
It must prove:

- original object-tree, property, Datasets, menu, shortcut, and canvas
  interactions remain available in their familiar locations;
- ordinary Veusz editing works with every SciPlot dock closed;
- AI and manual edits mutate the same `Document` and participate in one
  coherent Undo/Redo history;
- optional docks remain usable at supported window sizes without silently
  moving native panels;
- keyboard-only operation preserves Veusz shortcuts and covers SciPlot-owned
  actions without conflicts;
- state and errors remain understandable without color;
- review marks never leak into publication export unless promoted;
- no accepted document change is lost;
- exact-current VSZ remains the sole visual authority;
- no user-facing independent/AI mode switch is introduced.
