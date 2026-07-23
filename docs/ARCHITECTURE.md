# SciPlot Architecture

Status: current local developer reference.

This file defines module ownership and dependency boundaries only. `README.md`
owns product behavior, `skill/SKILL.md` owns agent command routing, and
`DEVELOPMENT_ROADMAP.md` owns active priorities. `DEVELOPMENT_LOG.md` and Git
hold history; historical implementation narratives are not architecture.

## Authority chain

```text
raw files + hashes
  -> confirmed scientific mapping
  -> prepared data + transform ledger
  -> exact-current studio/document.vsz
  -> Veusz PDF/TIFF export
  -> artifact QA
  -> visible SOURCE_SciPlot/ or --out handoff
  -> sibling hidden .sciplot/ runtime evidence
```

- raw files are data truth;
- the confirmed study/request model is semantic truth;
- the current saved VSZ is visual truth;
- versioned policy/profile data defines target constraints;
- QA reports only the checks it actually implements.

Lifecycle success, exact-current artifact QA, provenance completeness, human
daily-use validation, and journal-specific compliance are separate claims.

## Frontend topology

Veusz `MainWindow` is the only daily drawing frontend. Veusz owns the object
tree, property editor, Datasets, canvas, menus, shortcuts, Save, and Undo/Redo.

`src/sciplot_gui/` is an integration package, not a separate Qt application.
It attaches Project and optional selected-object AI docks to the same live
Veusz `Document`. SciPlot has no standalone Canvas, Composition Board, second
document model, or renderer fallback.

The browser `app` is an optional confirmation surface. It may collect the
initial source, grouping, naming, order, size, and export choices and show
rendered results read-only. It must not own post-render style, axis, legend, or
series editing; those operations belong to Veusz. The adapter is loopback-only,
accepts same-origin JSON requests, and may read local source paths only from the
active CLI-created session or the configured SciPlot output root.

## Command topology

| Command | Architectural role |
| --- | --- |
| `studio PATH` | Primary interactive lifecycle; prepares and opens native Veusz. |
| `studio PATH --export ... --json` | Headless mode of the same lifecycle. |
| `studio FIGURE.vsz` | Opens an existing visual authority in Veusz. |
| `app` | Optional first-time confirmation and read-only result review. |
| `autoplot` | Primary fully automated raw-path project/QA/delivery orchestration over internal one-step/`run_request`; no separate renderer. |
| `run` | Replays a confirmed request. |
| `curate torque` | Specialized scientific selection and Studio-project preparation; no final export/delivery authority. |
| `readiness`, `cleanup`, `mapping` | Maintenance/evidence contracts; no plotting lifecycle. |
| `publication` | Profile and layout metadata inspection only; no editor, assembler, or renderer. |
| `render`, `recipe` | Low-level development and testing primitives. |
| `one-step` | Internal manifest/readiness contract, not a user entrypoint. |

Retired `quick`, `prepare`, `intake`, and `workbench` names are not CLI
commands. Explicit legacy-launcher detection may remain so old generated
artifacts fail with a migration instruction instead of changing meaning.
`batch` is a help-hidden regression runner over `run_request`; `smoke` and
`acceptance` are validation/evidence commands. None is a user automation route.
`acceptance visual-review` is the sole recorder for the explicit uncalibrated
contact-sheet preview decision; it does not render or edit a figure and does
not prove final-physical-size readability. PDF size and TIFF DPI remain
machine checks; calibrated-display or print evidence is separate.

## Repository map

```text
research-plots/
  README.md                    product and user workflow
  DEVELOPMENT_ROADMAP.md       active product/maintenance priorities
  skill/
    SKILL.md                   agent operating contract
    scripts/sciplot            source-checkout CLI wrapper
  src/
    sciplot_core/
      materials_rules.py       experiment families, axes, aliases, units
      semantic.py              recognition and deterministic preparation
      policy.py                global plotting and delivery defaults
      style_contract.py        template/style consistency audit
      request_contract.py      renderer-independent request validation
      studio.py                VSZ lifecycle and exact-current export
      workflow.py              confirmed-request orchestration and repair loop
      autoplot.py              automated project/QA/delivery summary adapter
      one_step.py              internal readiness/manifest model
      publish_state.py         shared fail-closed final publication gates
      managed_output.py        shared generator-owned output rollback
      intake.py                headless project preparation/domain logic
      intake_server.py         thin browser HTTP adapter
      qa.py                    artifact/publication QA
      output_contract.py       visible handoff and hidden workspace paths
      delivery.py              minimal handoff package
      smoke.py                 synthetic runtime change gate
      _vendor/                 migrated compatibility black box
    sciplot_gui/
      studio_project.py        Veusz Project dock bridge
      studio_project_status.py pure result/audit state logic
      studio_assistant.py      selected-object AI dock bridge
    sciplot_recipes/           stable experiment-family recipe facade
  third_party/veusz/           pinned upstream renderer/editor
```

Generated projects, acceptance runs, caches, authorized local data, and
development logs are local workspace material, not package source.

## Ownership rules

| Concern | Owner | Boundary |
| --- | --- | --- |
| Scientific recognition, units, metrics | `materials_rules.py`, `semantic.py` | Deterministic and fixture-backed. |
| Global visual contract | `policy.py`, vendored `plot_contract.json`, `style_contract.py` | One source for hard style; fail on drift. |
| Request/template validation | `request_contract.py` | Reject unsupported template or option before rendering. |
| VSZ lifecycle | `studio.py`, Veusz runtime adapters | Preserve, reopen, audit, and export the current document. |
| Project state | `studio_project_status.py` | Pure evidence-to-state logic; UI only renders it. |
| Optional selected-object AI | setting catalogue, assistant operations/provider, GUI bridge | Current object and typed settings only. |
| Blocked data/rule repair | assisted-cleanup and Codex handoff modules | Out-of-band maintenance; no user-visible frontend mode. |
| QA and delivery | `qa.py`, `delivery.py`, evidence modules | Inspect artifacts without changing scientific content. |
| Runtime change gate | `smoke.py` | Synthetic lifecycle coverage, never real-data evidence. |
| Upstream Veusz | `third_party/veusz/` | Preserve upstream identity; integration remains outside. |
| Migrated core | `_vendor/` | Black box unless a public adapter cannot express the fix. |

## Template and style boundary

The production document builder implements exactly `curve`, `point_line`,
`stacked_curve`, `bar`, `box`, `box_strip`, and `heatmap`. The `bar` template
uses mean ± SD error bars for categorical replicate groups. Vendored reference
templates are not automatically production features; unsupported requests fail
closed.

Scientific semantics and presentation selection are separate contracts.
`SemanticRule` owns recognition, axes, units, replicate preservation, and
analysis. Its versioned `presentation_contract` owns the default template and
the explicit supported alternatives. The automated and Studio routes must
resolve that contract instead of rewriting a recognized metric back to a
single hard-coded chart. `impact_metric`, for example, supports `bar`, `box`,
and `box_strip` over the same categorical-replicate source.

Templates may define semantic behavior and editable options. They may not
privately override global typography, strokes, ticks, markers, or ordinary
frame margins. Heatmap scalar, contour, and colorbar colors are the explicit
semantic color exception. Nonstandard geometry is not a production template
capability and must not be introduced through a private profile lifecycle.

## Dependency rules

1. CLI and UI call orchestration/domain APIs; domain code does not depend on
   browser or Qt presentation state.
2. Headless intake/project preparation must be separable from the browser
   server and static UI so Studio does not depend on a second frontend.
3. SciPlot-owned modules do not import `third_party/veusz` directly; runtime
   adapters own that boundary.
4. New code must not deepen direct `src.*` or `_vendor` imports.
5. Importing `sciplot_core` must not initialize Qt, Veusz, browser, or network
   clients.
6. Paths, atomic writes, hashes, JSON parsing, style constants, and export
   names each have one shared owner.
7. Provider absence is normal; deterministic workflows cannot initialize AI
   unnecessarily.
8. Large modules are split one coherent owner at a time with characterization
   tests and unchanged public behavior.

Verification requirements are defined once in `skill/SKILL.md`; active
maintenance order is defined once in `DEVELOPMENT_ROADMAP.md`.
