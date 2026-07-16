# SciPlot Canvas M1 Design Audit

Date: 2026-07-17

## Audit scope

Surface: native Qt SciPlot Canvas M1.

User goal: open an exact-current scientific figure, understand whether it is
safe to use, make a bounded edit, recover unsaved work, and export without
entering Veusz MainWindow.

Evidence captured in this run:

1. `.tmp_verify/m1_design_audit/01-ready-canvas.png`
2. `.tmp_verify/m1_design_audit/02-recovered-editing.png`
3. `.tmp_verify/m1_design_audit/03-multipanel-canvas.png`
4. refined multi-panel evidence:
   `.tmp_verify/m1_final_postdesign_v2_temp3/canvas_app_probe_ike5eo63/`

## Step health

### 1. Ready exact-current Canvas — healthy M1 foundation

Strengths:

- the figure clearly dominates the window;
- `ready` is explicit text as well as color;
- high-frequency Save/Undo/Redo/navigation/zoom/export actions are visible;
- the right inspector is visually subordinate;
- export readiness is present without opening a separate review page.

Risks:

- the M1 inspector edits only visible text and is not yet selection-complete;
- symbol-only page and zoom actions still need explicit accessibility names
  and keyboard-focus verification;
- the hard-coded light QSS is not yet a system palette with dark and
  increased-contrast variants.

### 2. Recovered unsaved editing — healthy and trustworthy

Strengths:

- the recovery banner explains exactly what happened and how to make the state
  canonical;
- `editing` is visibly distinct from `ready`;
- stale export status names both the passing and current revisions;
- Save is available, while cross-process Undo is honestly unavailable.

Risks:

- M2 should add a compact recovery-history disclosure so the new undo
  boundary is understandable without documentation;
- recovery and stale-QA messages need screen-reader announcements and
  keyboard-focus checks.

### 3. Wide four-panel scientific figure — acceptable, with M2 layout work

Strengths:

- the existing native four-panel VSZ renders without reconstruction;
- the page remains centered and the inspector remains usable;
- long document titles now elide instead of displacing core commands;
- Advanced Editor moved into `More`, clarifying that it is recovery;
- `F9` hides and restores the inspector.

Risks:

- wide, shallow pages create large neutral regions; M2 needs smarter fit,
  pan, and canvas-only behavior;
- the inspector is fixed rather than adaptive or overlaying at narrow widths;
- technical selection paths are useful but should move behind a disclosure in
  the ordinary editing view.

## Highest-impact opportunities

1. Build a palette-backed visual token layer with system font, light/dark,
   contrast, focus, spacing, and icon roles.
2. Make the inspector adaptive: resizable on wide windows, collapsible on
   medium windows, and on-demand overlay at narrow widths.
3. Replace the visible-text prototype with contextual page/axis/series/legend
   inspectors and clear preview/apply/revert behavior.
4. Add canvas-only mode and stronger fit behavior for wide or multi-panel
   figures.
5. Add explicit accessible names, menu parity, and keyboard testing for every
   toolbar and inspector action.

## Accessibility evidence limits

Screenshots establish hierarchy, visible labels, and the fact that state is
not communicated by color alone. They do not prove:

- keyboard traversal and focus order;
- screen-reader names or state announcements;
- contrast in dark mode or increased-contrast mode;
- text scaling and minimum-window reflow;
- motor target size under alternate platform styles.

These must become executable M2 checks rather than screenshot-only claims.
