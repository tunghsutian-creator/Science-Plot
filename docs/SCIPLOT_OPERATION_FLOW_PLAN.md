# SciPlot Operation Flow and Visual System

Status: active frontend source of truth, 2026-07-18. M1 is complete; M2 and M3
are in progress. M4's automated native-composition engineering baseline is
implemented. The adaptive visual, contextual editing, and non-exported
review/promotion kernels are implemented. The first provider-neutral M3
Assistant transaction kernel and deterministic M3 data-mapping executor are
also implemented. The provider-neutral request/progress/cancellation boundary,
production OpenAI Responses adapter, and visible request UI are implemented.
Confirmed data mappings now execute from the Canvas decision card into a
separate candidate Canvas. Live-model canonical-task evaluation, real-session
cutover, mixed-family composition acceptance, and the default `studio`
migration remain active work. M5 now provides source-controlled validated
envelopes for all 23 ready rules and binds recognition, semantic/render,
source/mapping, strict QA, delivery, and one-step/autoplot state before
`ready_to_use=true`; the learning/promotion loop remains active work.
The product has not restarted: it remains at M5 while the accepted-result to
reviewed-rule loop is being closed. G0 through G7 below are delivery-gate
labels nested across the existing M5 and M6 roadmap, not replacement product
milestones. G0 is closed; G1 is the current M5 gate; no M3 or M6 real session
has been counted. The active cutover sequence is evidence contract, promotion
infrastructure, canonical-task/capability closure, live-model truth, five-lane
discovery, evidence-backed gap closure, release-candidate freeze, fifteen
qualifying frozen-build completions, and an explicit owner-approved
default-entrypoint change. Distribution remains outside this personal-product
objective.

This document owns the product flow and visual direction for the native
SciPlot workbench. `DEVELOPMENT_ROADMAP.md` owns milestone scope and exit
gates. When they differ, preserve the roadmap's safety and evidence contracts,
then update both documents explicitly.

## Product promise

SciPlot is a scientific-figure workbench, not a wrapper around the Veusz
application. The primary surface is the exact-current figure canvas. Data
confirmation, editing, review, AI assistance, QA, export, and composition
support that canvas without displacing it.

The user should be able to:

1. open raw data, an existing project, or a standalone VSZ;
2. see the real figure as soon as a deterministic document exists;
3. select what is visible and change it through bounded controls;
4. leave review marks without contaminating publication output;
5. ask AI for help and watch typed operations arrive on the same canvas;
6. undo or roll back accepted work;
7. export the exact current VSZ to QA-checked PDF/TIFF and delivery artifacts.

There is no user-facing independent/AI mode switch. AI appears only when the
user invokes it or the deterministic pipeline stops honestly.

## First-principles visual decisions

1. **The figure is the hero.** The canvas receives the largest stable region.
   Tool chrome stays quiet and subordinate.
2. **Frequent actions are visible; recovery actions are available.** Save,
   undo, redo, navigation, zoom, and export belong in the main toolbar.
   Advanced Editor and infrequent or not-yet-supported commands belong in an
   overflow menu.
3. **Selection drives the inspector.** The trailing pane changes with the
   selected page, graph, axis, series, legend, or annotation. It is not a
   permanent reproduction of Veusz's full object tree.
4. **Spatial work stays spatial.** Move, align, resize, annotate, and compose
   on the canvas. Do not make the user describe coordinates repeatedly.
5. **State must be readable without color.** Every state uses text and, where
   useful, an icon or shape in addition to color: `ready`, `editing`,
   `needs_human_confirmation`, `needs_rule_repair`, and `conflict`.
6. **The exact-current VSZ remains authoritative.** UI simplification must not
   introduce a second visual model or silently regenerate an edited document.
7. **The interface adapts before it shrinks.** The inspector collapses or
   overlays at narrow widths; the canvas is not squeezed into illegibility.
8. **Power grows progressively.** The default view is focused. More advanced
   controls appear in contextual sections, menus, and task workspaces.
9. **System conventions beat decorative novelty.** Use the platform font,
   palette, focus indication, shortcuts, menus, and accessible names before
   inventing custom chrome.

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
  -> Canvas
       -> select and edit
       -> review and annotate
       -> optional AI transaction
       -> optional native composition
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
should proceed directly to the generated Canvas.

### Canvas

The Canvas is the normal document surface:

- embedded Veusz `PlotWindow`;
- exact-current page and zoom;
- persistent SciPlot selection;
- typed user and AI operations through `DocumentController`;
- visible dirty, exported, QA, recovery, and conflict state;
- no Veusz `MainWindow`.

### Review

M2 provides a non-exported review layer. `Ctrl+Shift+R` opens the Review
workspace with Select, Note, Arrow, Box, Oval, and Pen tools. Marks bind to the
page, normalized page, graph, data coordinates, or a selected stable object.

Review-only marks persist in `.sciplot_canvas/review_annotations.json`; they
do not advance the publication revision, mutate VSZ, or appear in PDF/TIFF.
Text, arrow, rectangle, and ellipse marks can be promoted through one typed,
undoable Canvas transaction into native Veusz objects. Freehand remains
review-only because no equivalent bounded native Veusz object exists.

### AI transaction

M3 uses a third tab in the existing adaptive Inspector utility pane. This
keeps the figure dominant and avoids a second sidebar. The panel shows:

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

AI is a participant in the document, not a separate hidden renderer.
Deterministic `DataMappingProposal` execution is available from the Assistant
decision card. SciPlot first shows a zero-write, raw-value-free preview; a
separate user click creates a hash-bound receipt and starts background atomic
execution. Ambiguous source roots stop at a source chooser. Success opens an
isolated mapped project in a new Canvas while the current Canvas and VSZ remain
unchanged.

When an API key is available, the production OpenAI Responses adapter appears
through this same provider-neutral panel without a mode switch. Context version
3 gives the model only the selected object's exact bounded Inspector operation
catalog; the model cannot invent another target or setting path. SciPlot owns
IDs, expected old values, revision binding, validation, preview, acceptance,
application, and rollback. With no key, every deterministic Canvas workflow
remains available and the Assistant shows its honest optional state.

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

## Active personal cutover protocol

The remaining frontend work is evidence-driven rather than feature-count
driven. The numbered list below maps to delivery gates G0 through G7 while
preserving the M0 through M6 product roadmap:

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
   candidate, then freeze one exact release candidate that already contains
   the final Canvas-default entrypoint and obsolete normal-path cleanup;
7. collect at least fifteen qualifying real completions on that unchanged
   candidate, at least three per lane. The M2 ten-session gate is an
   intermediate subset and never authorizes cutover;
8. present the evidence to the owner and promote that identical commit/package
   to the normal workspace/install only after explicit approval; run a
   reversible entrypoint canary and make no post-canary source/package cleanup.

A qualifying session is owner-operated, real-project work that ends with a
saved and reopened exact-current VSZ, QA-checked PDF/TIFF, complete delivery,
and an explicit outcome. Automated probes, synthetic fixtures, injected
providers, copied outputs, agent-only review, failed attempts, and sessions
that require Veusz MainWindow for an ordinary task do not count. Failed
attempts and Advanced Editor fallbacks stay in the ledger with concrete
reasons so they can drive the next smallest shared-code fix. Discovery
attempts are not part of the final fifteen. Any runtime, rule, policy, adapter,
renderer, package, or runtime-identity change after freeze creates a new
candidate and restarts the formal count.

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
  -> owner actually closes and reopens Canvas/Composition Board
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

The normal Canvas owns high-frequency scientific editing. The Advanced Editor
remains the low-frequency, unsupported-property, and recovery surface. A gap
in that boundary is not permission to build a second general Veusz property
editor or renderer.

## Window anatomy

### Main toolbar

Keep visible:

- document title and explicit state;
- Save, Undo, Redo;
- page navigation;
- zoom out, zoom in, Fit, and 100%;
- Review and Assist workspace entry;
- Export + QA;
- More.

`More` contains the inspector toggle, the explicit Advanced Editor route for
infrequent/unsupported properties and recovery, and future infrequent document
commands. Every toolbar action must also have a shortcut or menu route so the
toolbar can adapt or be hidden.

### Canvas well

- neutral system-derived background;
- centered white page with a subtle boundary or shadow;
- smooth pan and zoom;
- visible stable-object selection and direct-manipulation affordances;
- XY data-point picking with a persistent redraw-safe marker;
- native label dragging routed through the typed operation gateway;
- no fake placeholder canvas during import;
- `Tab` Canvas-only mode with `Esc` recovery.

### Contextual inspector

The inspector is a trailing utility pane, resizable and toggled by `F9`.

It starts with:

- user-facing object name and type;
- compact structural breadcrumb;
- sections relevant to the selection;
- immediate preview where safe;
- Apply/Revert semantics where a commit boundary is needed.

The bounded M2 object set is page, graph, axis, XY series, box plot, legend,
image, contour, colorbar, and native label. Dataset mappings are visible but
read-only in this visual editor. Changing data authority belongs to the
validated mapping path, not to a color/style inspector.

Safe booleans and closed choices may apply immediately. Text, numbers,
distances, colors, ranges, and lists remain staged until Apply. A staged field
must be applied, reverted, or cancelled before changing object/page, saving,
exporting, or closing; no navigation path may silently discard it.

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

- **Wide, 1280 px and above:** canvas plus 320-380 px inspector.
- **Medium, 980-1279 px:** inspector remains available but can collapse; long
  titles elide in the middle; low-frequency toolbar actions overflow.
- **Narrow, below 980 px:** inspector becomes on-demand overlay or separate
  contextual view; status-bar details may move into a popover; the canvas
  remains the primary readable region.
- **Canvas only:** `Tab` hides toolbar, menu, status, and inspector without
  changing the exact-current figure; `Esc` restores chrome and `F9` toggles
  the inspector.

Test full screen, half-screen, two-thirds, and minimum supported window sizes.

## Visual tokens for M2

The M2 foundation now uses a palette-backed token layer:

- system UI font; ordinary interface text at or above the platform minimum;
- spacing scale: 4, 8, 12, 16, and 24 px;
- corner radii used sparingly: 6 or 8 px;
- semantic colors derived from `QPalette` with light, dark, and increased
  contrast variants;
- positive, neutral, warning, negative, and selection roles;
- toolbar and inspector icons from the platform or a coherent theme;
- visible keyboard focus for every interactive control;
- accessible names for symbol-only page and zoom actions.

The scientific figure's own colors remain governed by SciPlot publication and
accessibility QA, not by application chrome tokens.

## M2 visual and editing kernel delivered

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

## M3 reversible Assistant transaction kernel delivered

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

## M3 deterministic data-mapping executor delivered

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

## M3 provider lifecycle and visible request UI delivered

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

## M3 production OpenAI Responses adapter delivered

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

## M2 implementation order

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

Remaining M2 work:

1. Run at least ten representative real sessions across five figure families.
2. Treat those ten sessions only as an intermediate evidence checkpoint. The
   normal `studio` entrypoint can migrate only after the M6 frozen-candidate
   fifteen-session gate and explicit owner approval.

## Design acceptance

M2 is not visually complete because a screenshot looks polished. It must prove:

- common edits are easier to discover and execute than in the Veusz frontend;
- the canvas remains usable at supported window sizes;
- keyboard-only editing covers the primary flow;
- state and errors remain understandable without color;
- review marks never leak into publication export unless promoted;
- no accepted document change is lost;
- Advanced Editor is visibly a low-frequency/unsupported-property and recovery
  route, not the expected workflow.
