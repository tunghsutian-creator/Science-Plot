# SciPlot Operation Flow and Visual System

Status: active frontend source of truth, 2026-07-17. M1 is complete; M2 is in
progress. The adaptive visual foundation and bounded contextual editing kernel
and non-exported review/promotion kernel are implemented. The real-session
retirement gate and default `studio` migration remain active work.

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
   Advanced Editor and infrequent commands belong in an overflow menu.
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
- [Apple accessibility](https://developer.apple.com/design/human-interface-guidelines/accessibility/):
  use system colors, support contrast and text scaling, and never communicate
  state with color alone.
- [GNOME utility panes](https://developer.gnome.org/hig/patterns/containers/utility-panes.html):
  subordinate controls belong in a trailing utility pane that can become
  transient or overlay the main view when width is limited.
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

M3 adds an optional assistant drawer. It must show:

- what the assistant understood;
- affected stable object IDs;
- proposed `DataMappingProposal` or `CanvasOperationBatch`;
- live operation progress;
- pause, accept, reject, undo, and whole-turn rollback;
- verification and journal outcome.

AI is a participant in the document, not a separate hidden renderer.

### Compose

M4 uses a dedicated task workspace on an exact 183 mm canvas. Standalone
figures are imported as immutable source modules and compiled into native
Veusz page/grid/graph objects. Final raster-panel stitching is prohibited.

### Export

Export always means the exact current saved VSZ. A successful project export
requires:

- PDF and 300 dpi TIFF pairing;
- structured and artifact QA;
- matching current/exported/delivery VSZ hashes;
- complete delivery;
- provenance and transform evidence where the project contract requires them.

## Window anatomy

### Main toolbar

Keep visible:

- document title and explicit state;
- Save, Undo, Redo;
- page navigation;
- zoom out, zoom in, Fit, and 100%;
- Export + QA;
- More.

`More` contains the inspector toggle, Advanced Editor recovery, and future
infrequent document commands. Every toolbar action must also have a shortcut
or menu route so the toolbar can adapt or be hidden.

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
  in `CanvasSession` version 3, with safe version-1 and version-2 migration;
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
2. Only then migrate the normal `studio` entrypoint from Veusz MainWindow to
   SciPlot Canvas.

## Design acceptance

M2 is not visually complete because a screenshot looks polished. It must prove:

- common edits are easier to discover and execute than in the Veusz frontend;
- the canvas remains usable at supported window sizes;
- keyboard-only editing covers the primary flow;
- state and errors remain understandable without color;
- review marks never leak into publication export unless promoted;
- no accepted document change is lost;
- Advanced Editor is visibly a recovery route, not the expected workflow.
