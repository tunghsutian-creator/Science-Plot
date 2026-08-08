# SciPlot Architecture

Status: current module-ownership and dependency reference.

`README.md` owns product behavior, `skill/SKILL.md` owns agent routing,
and `DEVELOPMENT_ROADMAP.md` owns unfinished priorities. Historical
implementation narratives belong to `DEVELOPMENT_LOG.md` and Git, not here.

## Authority chain

```text
raw files + hashes
  -> confirmed scientific mapping
  -> resolved selected-figure plan
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
      figure_plan/             selected tasks, stable IDs, outcomes, gates
      presentation_identity.py selected rule/template identity contract
      plot_data/               source/spec conversion and CSV export
      policy/                  visual, axis, layout, export, plot contract
      render/                  renderer-independent orchestration
      studio.py                stable Studio facade
      studio_render/           pure series, axis, layout, spec transforms
      studio_core/             VSZ lifecycle, export, publish, Qt ports
        presentation_evidence.py selected plan/spec consistency gate
        rule_readiness.py      canonical request/current-rule publish evidence
      workflow/                confirmed-request orchestration
        route_intent.py        immutable auto/recipe/render request route
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

study model + current source facts
  -> resolved figure plan

studio_core + workflow
  -> resolved figure plan + render

studio_core
  -> studio_render + policy + Veusz runtime boundary

Veusz worker
  -> named studio_core runtime/export ports

QA / readiness / delivery
  -> saved artifacts + resolved outcomes + public evidence contracts
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
| Scoped static typing | `[tool.mypy]` in `pyproject.toml` | Strict Python 3.11 baseline for `foundation/`, `json_contract.py`, `figure_plan/`, the delivery plan-object validator `delivery/plan_binding.py`, the typed delivery manifest-gate consumers `delivery/package_builder.py` and `delivery/package_validation.py`, the persisted output-package owner `study_model/package_contract.py`, and the pure publication-state projection `publish_state.py` only. Imports outside that list provide type information but are not part of the current diagnostic claim. |
| Intake project manifest | `project_manifest.py` | `intake_manifest.json` is canonical; compatibility `*.sciplot.json` mirrors, read-modify-write updates, and ZIP snapshots share one rollback-capable cross-process project lock. |
| Raw-source Studio composition | `studio_core/studio_prepare.py` | Pass final source options into Intake, inject and capture exactly one generated preparation, then terminate source dispatch. `intake/project/` separately owns raw copies, the canonical request and in-memory manifest draft, blocked failure projection, and initial ZIP. |
| Workflow route intent | `workflow/route_intent.py` | Resolve strict optional recipe/template fields once after confirmed mapping/cleanup and before semantic or presentation enrichment. Intervention and rendering consume the same immutable auto/recipe/render decision; readiness keeps only a lazy compatibility projection. |
| Workflow render-family dispatch | `workflow/auto_split.py` | Validate the canonical request rule once and select exactly one of performance, impact, mechanical, DSC, DMA temperature, rheology, or generic execution. Without a selected plan, one specialized adapter may decline only to the generic renderer; with a selected plan, adapter decline fails closed. Workflow never probes another family. |
| Figure-task metric identity | `figure_plan/metric_binding.py`, `figure_plan/task.py` | Preserve the closed v1 Cartesian wire contract and add explicit v2 `cartesian_xy` or `ordered_metrics` bindings without fake axes. Child-task version is independent from the enclosing v1 plan. |
| Selected figure execution | `figure_plan/` | Resolve stable ordered tasks from Study Model plus current source facts; own plan identity, per-task outcomes, stale-state rejection, and publish/delivery gates. Impact, frequency, performance, rheology temperature, DMA temperature, and publication-digitized DSC are enabled runtime rules. Performance, rheology-temperature, DMA-temperature, and DSC resolution remain lazy leaf imports so worker startup cannot create a materials-rule initialization cycle. Render adapters execute tasks but do not select them. |
| Publication-digitized DSC single-curve plan | `figure_plan/dsc_resolution.py`, `figure_plan/dsc_provenance.py` | Validate the registered DSC CSV plus its adjacent provenance, or an exact content copy plus the registered provenance, as one role-and-hash-bound inventory. Resolve exactly one v2 temperature/heat-flow `curve` task with the canonical three-series order. Studio and Workflow consume the same plan and source identity; cycle workbooks fail closed and cannot imply phase, raw-instrument, transition, enthalpy, or crystallinity claims. |
| DMA temperature single-task plan | `dma_temperature_contract.py`, `figure_plan/dma_temperature_resolution.py`, `semantic_sources/dma_sources.py`, `studio_core/source_bound_prepare.py`, `workflow/dma_temperature_plan.py`, `workflow/dma_temperature_bundle.py` | Own one independent temperature/storage-modulus task, explicit source-to-Pa-to-MPa conversion, complete source-derived sample/point evidence, typed semantic-preparation attestation, and a sealed terminal table. Tan-delta evidence cannot select it. Studio and Workflow consume the same one-task plan without entering the rheology-temperature two-task resolver. |
| DMA named-recipe plan seam | `workflow/dma_named_recipe.py`, `workflow/request_rendering.py`, `workflow/dma_execution_evidence.py` | Admit only `rheology_dma` paired with the exact selected `dma_temperature_sweep` plan. Preflight rejects recipe, rule, task, source, sample, metric, unit, encoding-claim, or clipping-bound conflicts before semantic preparation. Auto and recipe then share preparation and task execution while preserving distinct route identity; a route-neutral evidence digest covers terminal data, units, encodings, and axis visibility. Other named recipes remain fail-closed with selected plans. |
| Workflow task-artifact installation | `workflow/task_artifacts.py`, `workflow/single_task_bundle.py` | Install task-owned editable worker trees and remap QA evidence for selected-task bundles. Performance has its own multi-task loop; DSC and DMA share the single-task mechanical lifecycle. These owners never select figures, templates, metrics, or scientific identities. |
| Terminal FigureTask evidence | `terminal_request.py`, `figure_plan/terminal_binding.py`, `workflow/request_rendering.py` | Preserve the exact unversioned legacy request when no task is selected. Task-aware terminal requests use a closed v2 envelope containing the exact v1/v2 task and only its metric binding. Workflow parses the selected plan before rendering, then binds ordered unique terminal tasks before reports or publication; the binding leaf is not a FigurePlan-facade export. |
| Studio FigureTask evidence | `studio_figure_set_contract.py`, `studio_core/figure_task_evidence.py`, `studio_core/figure_set_registry.py`, `studio_core/figure_set_storage.py` | Project exact tasks into queue, registry, and spec evidence once. Cartesian tasks alone expose compatibility x/y; ordered tasks expose only ordered metrics. Legacy registry v1 stays readable without task authority, while task-aware registry v2 binds the exact ordered plan, canonical task-owned paths, specs, and editable outcomes before the first replacement. |
| Selected presentation identity | `presentation_identity.py`, `studio_core/presentation_evidence.py` | Resolve one closed versioned `rule_id`/template value from the canonical request plus the already-resolved current rule. It binds only the plan's declared primary task and primary spec; each secondary spec verifies its own task template without minting another identity. Exact-current VSZ stays hash-bound visual authority; recognition never selects presentation. |
| Global visual contract | `policy/plot_contract.json`, `policy/`, `style_contract/` | Single hard-style and option authority. |
| Request validation | `request_contract.py` | Reject unsupported templates/options before rendering. |
| Ordinary XY series encoding | `studio_render/series_option_context.py`, `studio_render/series_options.py`, `studio_core/series_encoding_contract.py`, `studio_core/veusz_primitives.py`, `veusz_worker/spec_audit/series_encoding.py` | Resolve request provenance, palette, final-series order, per-series overrides, line style, marker, fill, and provenance once. Persist a closed versioned encoding per series; the writer consumes it without re-resolution, and exact-current audit enforces only fields owned by explicit/direct request intent. Performance scatter/radar and scalar fields retain separate semantic contracts. |
| Ordinary XY axis-data visibility | `studio_core/axis_data_visibility.py`, `veusz_worker/spec_audit/series.py` | Recompute finite data extents against both configured render-option bounds and final effective axes. Persist potential below/above-bound counts separately from coordinates actually clipped by the final spec; reject stale or forged visibility evidence during exact-current audit. |
| Pure plot construction | `studio_render/` | Convert confirmed data and policy into render specs. |
| Veusz lifecycle | `studio_core/`, `studio.py` | Core owns implementation; `studio.py` exposes the stable GUI/CLI integration API. |
| Rule contract certification | `readiness/rule_contract.py`, `readiness/rule_certification.py` | Build the canonical rule payload once, derive full/semantic hashes, and compare one already-resolved rule with exactly one validated-envelope registry entry. No Studio policy or I/O belongs here. |
| Studio prepare-time rule binding | `studio_core/rule_contract_binding.py` | Own the closed versioned binding persisted in canonical `plot_request.json`. Only successful generated preparation mints or refreshes it; exact-current reuse preserves it. |
| Studio publication rule readiness | `studio_core/rule_readiness.py` | Leaf owner combines canonical request identity, strict persisted review evidence, exactly one current catalog lookup, current certification, and prepare-time binding into one immutable publication snapshot. Inventory, semantics, finalization, registry, and native status project that snapshot; they do not resolve competing rule identities. |
| Managed rule-readiness display evidence | `sciplot_gui/studio_project_status/rule_readiness_evidence.py` | Strictly parses untrusted v1/v2 managed receipts before native status may display a specific rule or contract repair reason. Standalone and secondary receipts remain isolated. |
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

The rule semantic payload retains the certified default template. A Studio run
separately owns one versioned `SelectedPresentationIdentity`: an explicit
supported request choice wins over recognition history, while an omitted
choice materializes the current rule default. Request, Study Model, FigurePlan,
present VSZ spec, publication payloads, and registry must agree with that
identity; they may not independently reselect it. A spec-less manual VSZ stays
valid exact-current visual authority, with its hash bound beside the selected
identity rather than serving as a source for reverse template inference.

Workflow route is a separate fact from presentation and figure selection.
`WorkflowRouteIntent` captures auto, named recipe, or direct render before a
default template can be materialized. Later semantic preparation, FigurePlan
resolution, intervention, and rendering may consume that route but may not
recompute it from an enriched request.

`SelectedPresentationIdentity` remains atomic. A bundle may derive several
ordered `FigureTask` values, including different terminal templates; those
tasks belong to `figure_plan/` and are not additional selected-presentation
identities. Bundle-kind strings are orchestration metadata, never templates.

Global typography, strokes, ticks, markers, ordinary frame geometry, exports,
and plot options belong to `policy/`. Templates may own semantic geometry;
heatmap scalar colors are the explicit color-policy exception.

Ordinary-series palette authority is resolved once in
`policy/palette_authority.py`: explicit request options outrank the shared
project default, and inherited semantic/template values have no selection
authority. The resolved id, colors, and source are projected into publication
intent and every Veusz spec. `style_contract/` fails Doctor when the Python,
serialized contract, style, template, or ready-rule defaults drift.

Ordinary generic XY request provenance is normalized by
`studio_render/series_option_context.py`; visual channels are then bound once
by `studio_render/series_options.py` after final series selection and order.
`studio_core/series_encoding_contract.py` freezes the result and its authority
source into the spec. `studio_core/veusz_primitives.py` is a consumer, not a
second selector; `veusz_worker/spec_audit/series_encoding.py` compares
request-bound fields with the loaded exact-current VSZ. Manual Veusz edits
remain valid for channels that the request did not claim. Performance
comparison and scalar field builders remain independent semantic renderers.

Visible units use product notation with Unicode negative exponents. Unit
normalization belongs to material rules and is enforced by style/VSZ QA.

## Delivery boundary

User plotting output is source-adjacent: omit `--out` for `SOURCE_SciPlot/`, or
choose a dedicated directory beside the original data. Repository `outputs/`
must not be used for normal user deliveries. Internal evidence belongs to the
sibling hidden `.sciplot/`; development gates use ignored `.tmp_verify/`.

The visible package contains only plotting data, PDF/TIFF figures, editable
VSZ projects, and the Veusz launcher. It is not a runtime workspace.

For a supported resolved plan, every selected task has one stable logical ID,
the plan records a relocation-stable source-content fingerprint, and each task
must bind exactly one run-local VSZ, one PDF, and one 300-dpi TIFF. A generated
rebuild may refresh a plan only within the same rule; exact-current reuse and
publication require the persisted plan to match current source bytes. The live
source and archived raw copy must both match the prepare-time fingerprint.
Manifest, result, Study Model, visible figure records, and editable-project
records must project the same ordered outcomes. Missing tasks, reused paths,
cross-ID PDF/TIFF pairs, stale source selection, or mismatched VSZ snapshots
fail closed before a package can be complete.

Intake session and project names are reserved by exclusive filesystem
creation. ZIP refreshes are staged, verified, and atomically replaced so a
failed or concurrent refresh cannot destroy the last complete package.
For a new raw-source project, Intake commits the canonical manifest and mirror
after the one Studio preparation, then writes the initial ZIP. A Studio
preparation exception is deliberately projected as a blocked manifest and ZIP
before the same exception returns to the caller. A later manifest-projection
or ZIP failure instead aborts project construction and removes the reserved
project directory.

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
16. `figure_plan/` owns task selection and outcome identity. Studio, Workflow,
    QA, and delivery may project or verify that plan but may not independently
    choose a different figure set.
17. `figure_plan/payload_types.py` owns the exact canonical output and gate
    shapes. Producers return total typed payloads; parsers continue to accept
    untrusted `object` values, reject unknown keys, and preserve the existing
    valid/invalid gate field differences.
18. Compatibility facades may expose cross-owner APIs but may not require a
    partially initialized peer facade. Study-model run/package projections
    import FigurePlan leaf owners; frequency-plan resolution loads Study Model
    normalization only when that resolution path executes.
19. Studio publication derives rule identity only from the canonical request.
    Every non-empty rule is resolved exactly once before figure collection or
    run allocation, then compared with one registry entry and the strictly
    parsed prepare-time binding. Generated preparation writes that binding only
    through the rollback-capable request/VSZ/spec/figure-set transaction;
    exact-current reuse never recertifies it. A missing, stale, or mismatched
    binding/certification blocks handoff without changing `pending_rule_review`.
    Matching recognition may explain history but cannot replace canonical
    identity, current rule fields, or contract evidence; mismatched recognition
    is discarded. Semantic, result, manifest, final payload, registry, and
    managed native status carry the same v2 snapshot. Finalization rejects
    split structured or redundant projections before its first write. Project
    status maps an exact managed rule/contract gate to `needs_fix` with the
    canonical reason while leaving artifact QA and the separate
    automation-state vocabulary unchanged.
20. Studio preparation transactions are rollback-capable file replacement
    sets, not claims of process- or machine-crash atomicity. For raw files and
    source directories, Intake resolves the final rule, selected template,
    project identity, delivery root, pending-review marker, effective
    experiment, Study Model, canonical request, and in-memory manifest draft
    before invoking its injected Studio callback. That callback calls
    `generate_studio_document` exactly once with no second override and carries
    the configured figure-set replacement seam. Source dispatch returns the
    captured payload only after the finalized project reports a matching ready
    request and document; it never falls through to general regeneration.
    A generation exception may leave raw/source copies plus a blocked canonical
    manifest, mirror, and diagnostic ZIP, after which the same exception is
    re-raised. Post-generation projection, manifest, or ZIP failures abort the
    new project instead of returning a captured ready payload. The Studio
    rollback set covers its staged request, VSZ/spec, and figure-set state; it
    does not cover launchers, Intake manifests, or ZIP. Manifest/mirror commit
    is rollback-capable under the project lock, while ZIP staging, validation,
    and replacement are a later snapshot phase; these phases do not form one
    crash-atomic transaction.
21. Studio resolves one versioned `SelectedPresentationIdentity` before
    FigurePlan or publication-inventory work. A supported explicit choice beats
    recognition history; an omitted choice materializes the current rule
    default. The selected identity agrees with the plan rule, declared primary
    task, and primary VSZ spec. Secondary tasks may use different terminal
    templates and verify against their own specs without creating additional
    presentation identities. Exported semantic, result, manifest, final payload,
    and project registry carry the same closed primary identity. Finalization
    rejects split projections before its first write. The semantic rule template
    remains the certified rule default.
22. During first multi-figure preparation, only canonical document/spec targets
    backed by already-hashed staged replacements may count as transaction-ready
    FigurePlan artifacts. The plan persists final target paths, never temporary
    staging paths. Task, metric binding, task-owned template, canonical path,
    staged or exact-current spec, and editable outcome are checked before the
    first replacement; the figure-set registry is installed after its artifact
    replacements so rollback cannot leave an editable claim pointing to a
    missing file.
23. Workflow resolves `WorkflowRouteIntent` exactly once after confirmed
    mapping/cleanup and before classification or default-template enrichment.
    Intervention and rendering receive that immutable object; they never infer
    auto, recipe, or direct render again from a later request projection.
24. Workflow render-family dispatch is independent from route and presentation
    selection. A canonical non-empty `rule_id` is catalog-validated before any
    family adapter parses, validates a template, writes files, or renders, then
    maps to exactly one specialized family or the generic renderer. Ruleless
    direct rendering remains generic; malformed and unknown rules fail before
    side effects. Performance and impact retain their raw-source boundary,
    while mechanical, DSC, DMA temperature, rheology, and generic rendering
    retain the prepared source boundary. If no FigurePlan is selected and the specialized adapter
    legitimately returns no bundle, Workflow may invoke only generic rendering
    and never probes a second specialized family. Once a plan is selected,
    adapter decline fails closed before generic rendering.
25. `FigureTask` v1 remains the exact closed top-level `x_metric`/`y_metric`
    payload and re-emits byte-for-byte canonical JSON, preserving existing plan
    hashes and IDs. An explicit v2 task instead contains one closed
    `metric_binding`: `cartesian_xy` has one real x/y pair and
    `ordered_metrics` has a non-empty ordered unique metric list. V2 never
    serializes fake top-level axes. The enclosing `ResolvedFigurePlan` remains
    v1 because its structure and hash algorithm are unchanged and each nested
    task owns its own version.
26. `figure_plan/performance_resolution.py` is the enabled
    `performance_comparison` plan owner. It fingerprints before and after one
    validated comparison load and rejects source drift. Default selection is
    scatter then polar with scatter primary; only the literal external
    explicit-selection marker produces one task. Scatter metrics come from the
    declared source axes, polar order comes from
    `PerformanceComparison.radar_metrics`, and both tasks preserve the exact
    material order. Global resolution imports this leaf lazily because worker
    startup may still be inside materials-rule initialization.
27. An ordinary terminal render request remains the exact unversioned legacy
    payload, including its compatibility metric fallback. If
    `resolved_figure_task` is present, the request is instead closed v2 evidence:
    it re-parses and re-emits the exact nested v1/v2 task, requires the task
    template, projects Cartesian x/y or ordered metrics exclusively, and never
    consults the first Study Model queue item. Before Workflow returns
    `RequestRenderResult`, each terminal task must match the selected plan's
    rule and complete task payload, be unique, and follow plan order. A selected
    task may lack terminal evidence only when its ordered outcome is explicitly
    unavailable under the current source-unavailable reason allowlist. Invalid
    plans fail before rendering; result-side task splits fail before render
    reports and publication. Named recipes with a FigurePlan remain fail-closed
    until the planned prepare/task seam exists. A terminal worker executes its
    exact incoming task as a single render and never expands it back into the
    enclosing performance plan; legacy taskless low-level renders likewise
    retain their one-template behavior.
28. Studio queue items and task-aware figure-set entries re-parse and re-emit
    the exact nested v1/v2 `FigureTask`. V1 and v2 Cartesian tasks may expose
    matching compatibility x/y fields; ordered tasks expose only `metric_ids`
    and never serialize null or stringified `None` axes. A present malformed
    nested task never downgrades to legacy. Registry v1 remains a readable
    compatibility record without task authority; registry v2 requires exactly
    one same-order entry per selected task and binds the plan primary, current
    task document stem, final VSZ/spec paths, spec source request, and editable
    outcome before transaction replacement. The GUI consumes the validated
    canonical registry path projection rather than rebuilding filenames from
    figure IDs.
29. The performance Studio and Workflow adapters consume the same selected
    tasks. Studio writes a v2 registry even for an explicit one-task selection;
    default preparation stages scatter plus polar in one rollback-capable
    replacement set. Workflow renders into a private task transaction, installs
    task-stem exports and worker trees only after every render succeeds, and
    namespaces transform-step IDs by figure ID. Prepared payload template,
    Cartesian or ordered metrics, material order, task, plan, terminal request,
    outcome, manifest, and delivery record must agree. Source drift, partial
    rendering, missing registry, mixed legacy/task evidence, or planned adapter
    decline fails before a ready manifest or delivery.
30. Temperature-rheology semantic preparation owns one typed source
    attestation: the source-tree hashes before and after preparation must match,
    the exact parser-selected file paths and hashes must remain inside that
    source root, and the prepared workbook path and hash are fixed in the same
    record. Workflow passes this object out of band to the temperature adapter;
    the adapter never rediscovers raw files. It materializes exactly storage
    modulus and loss factor task tables and gives only those two tasks the
    private terminal-source binding. Frequency and ordinary rendering reject
    that capability. The wire encoding is consumed only by render target launch
    and terminal-worker entry modules, never by public JSON. Both temperature
    renders must return complete export, VSZ, spec, QA, and terminal-request
    evidence before one rollback-capable figure-directory replacement; returned
    export paths refer only to installed persistent files.
31. `figure_plan/temperature_resolution.py` is the enabled
    `rheology_temperature_sweep` plan owner. It fingerprints before and after
    one raw source-facts load, rejects drift, and selects exactly two v2
    Cartesian tasks in order: `storage_modulus_vs_temperature` followed by
    stable figure identity `tan_delta_vs_temperature` with canonical metric
    `loss_factor`. Both tasks bind the same source-derived sample order and
    replicate counts. Studio performs semantic preparation once, reuses its
    typed attestation for the primary and secondary documents, and installs one
    v2 registry transaction. Workflow requires the plan before task-source
    materialization and binds each terminal request to its exact task. Publish
    and delivery accept only the completed two-task plan and exact membership
    of two editable VSZ documents, two PDFs, and two 300-dpi TIFFs; source,
    task, render, or second-artifact failure rolls back the whole set.
32. `figure_plan/dsc_resolution.py` is the enabled `dsc_curve` plan owner for
    the registered publication-digitized source only. It fingerprints the
    selected CSV and its provenance before and after one parse, validates their
    content hashes, exact `UDC 2`, `UDC 3`, `UDC 4` order, canonical
    temperature and heat-flow units, point coverage, publication identity,
    digitization evidence, and passed peak-error gate, then selects exactly one
    v2 Cartesian `curve` task, `dsc_heat_flow_vs_temperature`. An exact CSV
    content copy may move or change filename and still resolve against the
    registered provenance; an altered or unregistered copy without adjacent
    provenance fails closed. Studio writes the task-aware v2 registry/spec and
    Workflow binds the same task in its terminal/result evidence. Publication
    and delivery complete only with exact membership of one editable VSZ, one
    PDF, and one 300-dpi TIFF; preparation/render failure and source drift use
    the enclosing Studio or Workflow rollback transaction. Workbook intake,
    phase expansion, implicit `stacked_curve`, and generic fallback are
    rejected under this rule. The plan makes no cycle-phase, raw-instrument,
    transition identity, enthalpy, or crystallinity claim; a future instrument
    cycle contract requires an independent authorized and registered
    `dsc_cycle` rule.
33. `dma_temperature_contract.py` is the shared identity and unit owner for
    `dma_temperature_sweep`; its parser accepts only explicit Celsius/Kelvin
    temperature units and Pa-family modulus units, canonicalizes modulus to Pa,
    and materializes MPa without dropping finite negative acquisition values.
    `figure_plan/dma_temperature_resolution.py` fingerprints around one raw
    facts load and selects exactly one v2 Cartesian `point_line` task,
    `storage_modulus_vs_temperature`, with the source-derived four-sample order.
    Studio reuses one typed semantic-preparation attestation. Workflow seals the
    prepared CSV, raw-source inventory, exact sample order, and per-sample point
    counts into a private terminal binding so the worker cannot repeat semantic
    preparation or substitute another metric. Completion requires exactly one
    task-owned VSZ, PDF, and 300-dpi TIFF.
34. Every ordinary-series Veusz spec contains a closed
    `axis_data_visibility` record. For each axis it separates coordinates below
    or above configured render-option bounds from coordinates outside the final
    effective axis. Automatic relaxation is explicit; a potential default-bound
    count is never treated as proof of actual clipping. The worker recomputes
    the record from final spec series and axes and rejects any mismatch.
35. A named Workflow recipe may consume a selected FigurePlan only through an
    explicitly bounded seam. The current sole seam is `rheology_dma` with
    `dma_temperature_sweep`: route identity remains `recipe`, while plan and
    source validation happen before semantic preparation and the execution then
    reuses auto's preparation, sealed terminal source, and single-task bundle.
    The recipe contributes no template, metric, sample, unit, encoding, or axis
    authority. Its route-neutral DMA execution evidence must equal the auto
    route for the same source and request options. All other named recipe/plan
    combinations fail before recipe execution.

Verification requirements are defined once in `skill/SKILL.md`.
