# SciPlot Architecture

Status: current module-ownership and dependency reference.

`README.md` owns product behavior, `skill/SKILL.md` owns agent routing,
and `DEVELOPMENT_ROADMAP.md` owns unfinished priorities. Historical
implementation narratives belong to `DEVELOPMENT_LOG.md` and Git, not here.

## Authority chain

```text
raw files + hashes
  -> confirmed scientific mapping
  -> prepared data + transform ledger
  -> exact-current studio/document.vsz
  -> Veusz PDF/TIFF export
  -> artifact QA
  -> source-adjacent visible delivery
  -> sibling hidden .sciplot/ evidence
```

- raw files are data truth;
- the confirmed request/study model is semantic truth;
- the saved VSZ is visual truth;
- versioned policy and request contracts define constraints;
- QA reports only checks it actually performs.

Lifecycle success, provenance, artifact QA, human review, and journal
compliance are separate evidence claims.

## Frontend boundary

Veusz `MainWindow` is the only daily drawing frontend. It owns the object tree,
property editor, Datasets, canvas, menus, Save, and Undo/Redo.

`src/sciplot_gui/` attaches Project and optional selected-object AI docks to the
same Veusz `Document`; it does not own a second document model or renderer.

The browser `app` is a loopback-only confirmation adapter. It may collect
initial data choices and show results read-only, but it must not own
post-render visual editing.

## Repository map

```text
research-plots/
  README.md                    product and user workflow
  AGENTS.md                    thin local agent entrypoint
  DEVELOPMENT_ROADMAP.md       unfinished priorities
  skill/
    SKILL.md                   agent routing and verification
    scripts/sciplot            source-checkout CLI wrapper
  src/
    sciplot_core/
      cli/                     parser registration and dispatch
      foundation/              hashing, JSON, text decoding, timestamps, paths
      automation_states.py     closed automation-state vocabulary
      materials_rules/         experiment families, aliases, units, metrics
      semantic.py              stable recognition/preparation facade
      semantic_sources/        experiment-specific preparation
      source_tables/           raw table decoding and typed parsing
      source_inspection/       source-shape recognition and proposals
      mapping_contract/        mapping models and validation
      data_mapping/            mapping execution and state
      study_model/             study and experiment plans
      plot_data/               source/spec conversion and CSV export
      policy/                  visual, axis, layout, export, plot contract
      render/                  renderer-independent orchestration
      studio.py                stable Studio facade
      studio_render/           pure series, axis, layout, spec transforms
      studio_core/             VSZ lifecycle, export, publish, Qt ports
      workflow/                confirmed-request orchestration
      autoplot/                typed persisted-evidence adapter and summary
      one_step/                internal preparation/readiness lifecycle
      qa/ readiness/           artifact checks and rule evidence
      delivery/ evidence/      handoff and evidence contracts
      source_coverage/         source and provenance coverage
      visual_review/           explicit visual-decision records
      acceptance/ smoke/       lifecycle and runtime gates
      veusz_worker/            worker protocol and spec audit
      veusz_audit/             exact-current VSZ audit
      intake/                  headless confirmation domain and static UI
      intake_server/           loopback HTTP adapter
      assistant_provider/      provider-neutral assistant contract
      openai_provider/         OpenAI transport adapter
      *_probe.py               linear black-box evidence
    sciplot_gui/
      main_window_menu.py      Veusz menu and dock composition
      window_context.py       live document-path resolution
      studio_project/          Project dock bridge
      studio_project_status/   pure project-state aggregation
      studio_assistant/        selected-object AI bridge
      studio_assistant_history/ typed history and persistence
    sciplot_recipes/
      material_recipe.py      material recipe execution
      registry.py             recipe discovery
  third_party/veusz/          pinned upstream renderer/editor
```

Generated projects, acceptance artifacts, caches, authorized local data, and
the local development log are not package source.

## Dependency direction

```text
CLI composition root
  -> GUI presentation installer
  -> Core public facades

GUI presentation
  -> studio.py public integration API + pure status/evidence values

autoplot / workflow / one_step
  -> semantic + mapping + render + studio

semantic + mapping
  -> materials rules + study model + source tables + foundation

studio_core
  -> studio_render + policy + Veusz runtime boundary

Veusz worker
  -> named studio_core runtime/export ports

QA / readiness / delivery
  -> saved artifacts + public evidence contracts
```

The CLI may assemble GUI presentation. Core business, data, rendering, QA, and
delivery modules must not import `sciplot_gui`. GUI code may call Core service
contracts but may not duplicate scientific calculations.

## Ownership table

| Concern | Owner | Boundary |
| --- | --- | --- |
| Low-level text, timestamp, hash, JSON and path primitives | `foundation/` | Leaf package; never imports ingestion, workflow, GUI, or rendering. |
| Automation state vocabulary | `automation_states.py` | One closed owner for ready, confirmation, and repair states. Project editing/export states remain separate. |
| Autoplot persisted evidence | `autoplot/evidence.py` | Typed aggregate over reported result, persisted one-step state, and manifest; public JSON remains unchanged. |
| Scientific recognition, units, metrics | `materials_rules/`, `semantic.py`, `semantic_sources/` | Deterministic, fixture-backed, no GUI state. |
| Raw source parsing | `source_tables/` | Typed curve, replicate, and heatmap tables without rendering. |
| Generic source inspection | `source_inspection/` | Recommend only production-supported templates. |
| Mapping | `mapping_contract/`, `data_mapping/` | Closed contracts, explicit confirmation, immutable source evidence. |
| Global visual contract | `policy/plot_contract.json`, `policy/`, `style_contract/` | Single hard-style and option authority. |
| Request validation | `request_contract.py` | Reject unsupported templates/options before rendering. |
| Pure plot construction | `studio_render/` | Convert confirmed data and policy into render specs. |
| Veusz lifecycle | `studio_core/`, `studio.py` | Core owns implementation; `studio.py` exposes the stable GUI/CLI integration API. |
| Material performance data | `performance_comparison/` | Validate tidy values and declared bounds; never infer missing science. |
| Material performance objects | `performance_veusz/` | Native editable scatter/radar objects and index geometry. |
| Project state | `sciplot_gui/studio_project_status/` | Pure evidence-to-state logic; UI renders it. |
| Optional selected-object AI | setting catalogue, assistant provider/operations, GUI bridge | Validated current-object operations only. |
| QA and delivery | `qa/`, `readiness/`, `delivery/`, evidence packages | Inspect and package artifacts without changing content. |
| Runtime gates | `smoke/`, `acceptance/`, probes | Evidence only; never production rendering routes. |
| Upstream Veusz | `third_party/veusz/` | Preserve upstream identity; SciPlot integration stays outside. |

Compatibility facades may preserve a public import or documented monkeypatch
seam. They must not acquire business logic or become forwarding layers without
a real compatibility caller.

## Presentation and style boundary

The production builder accepts `curve`, `point_line`, `stacked_curve`, `bar`,
`box`, `box_strip`, `heatmap`, `scatter`, and `polar_curve`. Historical or
reference-only templates fail at request validation.

Scientific rules own recognition, units, replicates, and analysis.
Presentation contracts own permitted chart alternatives. Template-specific
geometry belongs to the relevant construction module and executable tests,
not to architecture prose.

Global typography, strokes, ticks, markers, ordinary frame geometry, exports,
and plot options belong to `policy/`. Templates may own semantic geometry;
heatmap scalar colors are the explicit color-policy exception.

Visible units use product notation with Unicode negative exponents. Unit
normalization belongs to material rules and is enforced by style/VSZ QA.

## Delivery boundary

User plotting output is source-adjacent: omit `--out` for `SOURCE_SciPlot/`, or
choose a dedicated directory beside the original data. Repository `outputs/`
must not be used for normal user deliveries. Internal evidence belongs to the
sibling hidden `.sciplot/`; development gates use ignored `.tmp_verify/`.

The visible package contains only plotting data, PDF/TIFF figures, editable
VSZ projects, and the Veusz launcher. It is not a runtime workspace.

Intake session and project names are reserved by exclusive filesystem
creation. ZIP refreshes are staged, verified, and atomically replaced so a
failed or concurrent refresh cannot destroy the last complete package.

## Dependency rules

1. Entry and presentation layers call domain/orchestration APIs; lower layers
   do not depend on browser or Qt state.
2. GUI presentation imports Studio lifecycle services through `studio.py`, not
   from `studio_core/` implementation modules.
3. The Veusz worker imports named `studio_core/` runtime/export ports and never
   depends on the high-level Studio compatibility facade.
4. `foundation/`, `policy/`, and `source_tables/` remain dependency leaves
   outside their own package.
5. Headless confirmation/domain code remains separable from its HTTP/static UI
   adapter.
6. SciPlot modules do not import upstream Veusz directly; runtime adapters own
   that boundary.
7. The removed `_vendor`, `_bootstrap.py`, and first-party `src.*` namespace
   must not return.
8. Importing `sciplot_core` must not initialize Qt, Veusz, browser, network, or
   provider clients.
9. Paths, atomic writes, canonical hashes, JSON parsing, style constants, and
   export names each have one owner.
10. Provider absence is normal; deterministic workflows do not initialize AI
   unnecessarily.
11. Ordinary source files stay under 400 lines unless an exact architecture
   test records a justified linear evidence harness.
12. Non-probe production functions do not repeat an exact implementation;
    first-party dependencies remain acyclic and Core remains independent of GUI
    presentation.
13. Files and modules keep one clear owner. Presentation, domain logic, source
    I/O and transformation, and state management remain separated by the
    repository map.
14. Extract abstractions only for genuinely shared semantics. Catch-all
    manager, service, utils, helpers, or common modules and one-hop wrappers are
    not architecture boundaries.
15. Structural refactors preserve supported interfaces, data formats, and
    user-visible behavior unless the task explicitly changes their contract.

Verification requirements are defined once in `skill/SKILL.md`.
