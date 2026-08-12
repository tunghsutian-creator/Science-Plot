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
| Autoplot user summary | `autoplot/summary.py` | One v2 result builder serves both the read-only projection of persisted evidence and a rule-repair preflight result. The normal projection reads publish integrity, delivery state, and the completed FigurePlan without reparsing or rehashing the plan; the preflight variant contains no invented run evidence and is never persisted. |
| AI-callable rule invocation | `materials_rules/models.py`, `materials_rules/catalog.py`, `readiness/rule_certification.py`, `readiness/registry_io.py`, `cli/dispatch/governance.py`, `cli/dispatch/diagnostics.py`, `cli/parsers/rendering.py`, `cli/dispatch/rendering.py`, `plan_preview.py`, `autoplot/run.py`, `autoplot/summary.py`, `workflow/__init__.py`, `workflow/one_step_entry.py` | `SemanticRule` owns the static additive `invocation` shape: existing plan/autoplot operations, required input and template, fixed rule identity, and source-controlled template choices. The CLI governance composition layer loads the validated-envelope registry once and injects the same current-certification projector into both `rules list/show`; the catalog remains readiness-free so contract hashing has no reverse dependency or data recursion. Explicit `plan` and `autoplot` call that projector before source parsing or project creation: current continues, while missing/stale returns the same repair reasons. Expected plan rule/template/source errors use the existing blocked v1 payload. A current Autoplot invocation checks source existence once before the runner. Public rule/template identifiers still enter the existing top-level request and explicit-template marker, so preview and render cannot select different task sets. Human omission permits existing automatic classification. This surface adds no second catalog, request envelope, readiness schema, receipt, cache, classifier pass, or source hash. |
| Source-bound scientific transform | `semantic_sources/scientific_transform.py`, `semantic_sources/stress_relaxation_transform.py`, `semantic_sources/dma_temperature_transform.py`, `semantic_sources/registered_paired_curve_transform.py`, `semantic_sources/registered_paired_curve_contract.py`, `semantic_sources/paired_curve_table_metadata.py`, `semantic_sources/gpc_sources.py`, `semantic_sources/gpc_transform_contract.py`, `semantic_sources/tga_transform.py` | Returns one typed resolved object containing exact transformed series, a declarative column/unit/anchor/coordinate/axis/output contract, and selected source paths. The registered paired-curve owner derives aliases, canonical labels/units, metric IDs, table metadata, scale-driven domain projection, and closed row evidence from the existing `SemanticRule`; DSC, DTG, UV-Vis, XRD, and SAXS consume that rule-driven owner directly while TGA retains only a compatibility wrapper. GPC contributes only an Agilent/canonical RT-RI reader and contract leaf: source sample text, `min`/`mV` detector evidence, row order, retained/excluded counts, and selected workbooks remain source-derived, with no normalization or molecular-weight inference. Preview and preparation must consume that same domain resolver; the payload belongs inside the existing semantic-preparation lineage and must not create another ledger, digest, or cache. |
| Scientific source transaction snapshot | `materials_rules/models.py`, domain `materials_rules/*_rules.py`, `semantic_sources/scientific_source.py`, `semantic_sources/scientific_source_models.py`, `semantic_sources/scientific_source_single_curve.py`, `semantic_sources/rheology_sweep_domain.py`, `semantic_sources/rheology_temperature_domain.py`, `workflow/scientific_source_resolution.py` | Each ready canonical rule may select one internal scientific-source adapter; stress relaxation, DMA temperature, registered DSC/TGA/DTG/UV-Vis/XRD/SAXS paired curves, GPC/SEC, rheology temperature, and directory rheology frequency are the first thin adapters and all other rules default to none. The shared resolver combines one rule/source identity, one typed domain, and the applicable already-resolved FigurePlan without raw rule-ID classification. `scientific_source_single_curve.py` is the only adapter-to-generic-plan binder for both paired tables and GPC; preparation calls the same rule-owned transform dispatcher when no envelope was supplied. A domain may be a single-y `ResolvedScientificTransform` or the shared, non-serialized multi-metric `ResolvedRheologySweepDomain`; it must never be a dummy transform or generic object bag. Expected adapter failures use one internal `ScientificSourceResolutionError` while preserving the existing public reason/message; FigurePlan, preview, Studio, and Workflow do not rediscover the family. Broad `ValueError` fallbacks must not disguise snapshot invariants or programming errors as source failures. One Studio or Workflow transaction passes the typed envelope through planning, semantic materialization, named/direct/auto routing, and terminal adaptation. Pending/unadapted rules do not read the source through this seam. A family handler may parse only while creating the envelope; downstream orchestration may not reconstruct it from wire JSON or assign a plan hash to a transform after the fact. Domain variants and adapter IDs remain absent from public requests, previews, ledgers, rule payloads, and certification hashes. |
| Preparation source attestation | `preparation_source_attestation.py` | Owns the typed source/prepared-artifact snapshot and the one exact set of canonical rules that require it. Semantic preparation, Studio queue preparation, and private prepared-source admission consume `requires_preparation_source_attestation`; they may not copy that membership, add another capability registry, or introduce another hash/receipt layer. |
| Persisted scientific review | `scientific_review.py`, `scientific_review_ledger.py` | Purely projects the existing semantic-preparation contract into family-neutral human/AI items. Browser result review binds only to its run-local manifest; a prepared project and Studio bind only to canonical request evidence. Missing or failed ledger fields remain unknown/blocked, document-context changes clear the review, and no projector reads sources, invents anchors, or creates another receipt. |
| Read-only FigurePlan and transform preview | `plan_preview.py` | Builds one additive v1 planned/not-applicable/blocked payload from the existing semantic, Study Model, FigurePlan, and scientific-transform owners. `not_applicable` refers only to FigurePlan; a source-bound `scientific_transform` may still be present. DMA, registered DSC/TGA/DTG/UV-Vis/XRD/SAXS paired curves, and GPC each pass one typed source snapshot to both transform projection and FigurePlan resolution rather than reparsing or caching it. Rheology temperature and directory frequency pass one internal multi-metric sweep domain to FigurePlan and later preparation while correctly leaving `scientific_transform` null. The preview never renders, writes transformed data, creates a project, or runs completed-plan gates. |
| Scientific recognition, units, metrics | `materials_rules/`, `semantic.py`, `semantic_sources/` | Deterministic, fixture-backed, no GUI state. |
| Numeric separator evidence | `semantic_sources/numeric_separators.py`, `semantic_sources/rheology_sweep_sources.py` | Resolve decimal punctuation only from parser-selected scientific coordinate/response columns. Any amount of explicit evidence is sufficient; point-count voting, unrelated-table scanning, and silent mixed/ambiguous locale guesses are forbidden. This leaf performs no unit conversion, source selection, caching, or schema projection. |
| Semantic preparation dispatch | `materials_rules/models.py`, domain `materials_rules/*_rules.py`, `semantic.py`, `semantic_sources/prepare_*.py` | Each canonical rule selects at most one internal `preparation_adapter`: rheology, curve-family, mechanical, or identity. The dispatcher invokes exactly one existing handler; a `None` result means identity and never probes another family, while handler exceptions propagate unchanged. Legacy family-only calls resolve one unique catalog rule by linear lookup, including `rheology_frequency`; no family map, callable registry, cache, or request field exists. The adapter remains outside public rule payloads and certification hashes. Source snapshot validation, the single attestation hash boundary, `SemanticPreparationContext`, transform-step construction, processed filenames, and post-handler attestation validation remain in the shared preparation owner. Registered paired-curve rules, including DSC, materialize the already-resolved transform through the same curve-family branch; no family-specific provenance or workbook gate runs downstream. Specialized source readers may enforce explicit scientific evidence but may not invent it: swelling accepts only explicit s/min/h time units from the header or adjacent unit row, uncurated torque preserves the full absolute-time curve, and Impact requires an explicit compatible unit. |
| Terminal-source binding lifecycle | `terminal_source_binding.py`, `terminal_source_binding_wire.py`, `render/panel_render.py`, `veusz_worker/operations.py` | One materialized binding owns raw, prepared, and terminal artifacts plus task, metric, order, point-count, and request context. The parent `seal()` performs the sole pre-worker inventory/request validation and captures the request hash; worker environment consumption performs the one cross-process current-state verification. Later Studio and series consumers verify structural order/count/artifact agreement without rehashing the same inventory. Archive, reopen, installation, and publication remain independent authority boundaries and are not elided by this same-transaction rule. |
| PDF raster artifact visibility | `qa/artifacts.py` | Invalid pixmaps and a zero-ink raster fail as blank. Any nonzero raster content remains valid evidence regardless of page-area-dependent ink fraction; continuous ink fraction and content bounds are reported for review, not used as an empirical scientific-output threshold. |
| Raw source parsing | `source_tables/` | Typed curve, replicate, and heatmap tables without rendering. |
| Table-source filesystem selection | `semantic_sources/table_source_files.py` | Owns supported table suffixes, deterministic recursive enumeration, workbook identity, and strict file-or-single-member-directory resolution. It never reads or ranks table contents; scanners and registered transforms consume it instead of copying directory-shape logic. |
| Tensile-export filesystem identity | `semantic_sources/tensile_export_identity.py` | Sole owner of the `.is_tens_exports` suffix, parent membership, source-derived sample name, and case-insensitive CSV membership. Classification, Intake, batch discovery, and the semantic compatibility facade reuse this leaf; it contains no scientific parsing or rendering policy. |
| Generic source inspection | `source_inspection/` | Recommend only production-supported templates. |
| Mapping | `mapping_contract/`, `data_mapping/` | Closed contracts, explicit confirmation, immutable source evidence. |
| Changed-owner verification | `verification/changed.py`, `verification/owners.py` | `changed.py` collects the current `HEAD` staged, unstaged, and untracked paths once, resolves their stable owner union, and runs at most one changed-file Ruff command, one explicit-target focused pytest command, the existing scoped mypy command when selected, and one tracked diff whitespace check. `owners.py` is the source-controlled path-to-test and gate authority. Unknown production/configuration paths fail closed without a broad-test fallback; Doctor is a handoff gate, smoke is a final cross-boundary milestone gate, and acceptance/full remain release gates. This owner never renders, opens, edits, hashes, or exports a Veusz document. |
| Scoped static typing | `[tool.mypy]` in `pyproject.toml` | Strict Python 3.11 baseline for `foundation/`, `json_contract.py`, `figure_plan/`, the delivery plan-object validator `delivery/plan_binding.py`, the typed delivery manifest-gate consumers `delivery/package_builder.py` and `delivery/package_validation.py`, the persisted output-package owner `study_model/package_contract.py`, the pure publication-state projection `publish_state.py`, and the read-only Autoplot owners `autoplot/publish_integrity.py`, `autoplot/evidence.py`, and `autoplot/summary.py` only. Imports outside that list provide type information but are not part of the current diagnostic claim. |
| Intake project manifest | `project_manifest.py` | `intake_manifest.json` is canonical; compatibility `*.sciplot.json` mirrors, read-modify-write updates, and ZIP snapshots share one rollback-capable cross-process project lock. |
| Raw-source Studio composition | `studio_core/studio_prepare.py` | Pass final source options into Intake, inject and capture exactly one generated preparation, then terminate source dispatch. `intake/project/` separately owns raw copies, the canonical request and in-memory manifest draft, blocked failure projection, and initial ZIP. |
| Workflow route intent | `workflow/route_intent.py`, `workflow/request_rendering.py`, `workflow/legacy_route_rendering.py` | Resolve strict optional recipe/template fields once after confirmed mapping/cleanup and before semantic or presentation enrichment. Scientific auto, named-recipe, and direct requests all enter shared semantic materialization with the transaction snapshot. Only requests without a scientific snapshot or selected source-bound plan may enter the injected legacy recipe/direct leaf. Readiness keeps only a lazy compatibility projection. |
| Workflow effective semantic presentation | `request_contract.py`, `workflow/scientific_source_resolution.py`, `workflow/request_run.py` | Project only rule-owned, request-editable render defaults into the canonical request after scientific-source/FigurePlan resolution. Semantic defaults override generic Autoplot defaults; keys named by the existing explicit-render-option marker may override them again. Registered single-curve axis labels come from the same rule axis plan. Renderer-only style metadata never leaks into the public request, and no second template, option schema, or family dispatch is introduced. |
| Workflow render-family dispatch | `materials_rules/models.py`, domain `materials_rules/*_rules.py`, `workflow/auto_split.py` | Each canonical `SemanticRule` owns one internal `render_adapter`, defaulting to generic; specialized rules opt into performance, impact, mechanical, DMA temperature, or rheology without a parallel rule map. DSC uses the default generic adapter. Workflow validates the canonical rule once, reads that field, and calls exactly one adapter. Without a selected plan, one specialized adapter may decline only to the generic renderer; with a selected plan, adapter decline fails closed. Render-adapter choice does not select FigurePlan capability, and Workflow never probes another family. |
| Figure-task metric identity | `figure_plan/metric_binding.py`, `figure_plan/task.py` | Preserve the closed v1 Cartesian wire contract and add explicit v2 `cartesian_xy` or `ordered_metrics` bindings without fake axes. Child-task version is independent from the enclosing v1 plan. |
| Selected figure execution | `materials_rules/models.py`, domain `materials_rules/*_rules.py`, `figure_plan/` | Each applicable canonical rule selects one internal `figure_plan_adapter`; `resolve_figure_plan` reads it lazily and invokes exactly one leaf instead of classifying raw rule IDs. The internal adapter is excluded from public rule payloads and certification hashes. `REQUIRED_FIGURE_PLAN_RULE_IDS` owns the exact current membership that must persist a source-bound plan and use task-aware figure-set publication; the compatibility `SUPPORTED_...` name aliases that same object. A focused contract keeps adapter membership equal to the required set without turning either into a second resolver registry. Unadapted and unknown rules return before source-tree hashing. FigurePlan owns stable ordered tasks, plan identity, per-task outcomes, stale-state rejection, and publish/delivery gates; heavy family resolution remains lazy so startup cannot create a materials-rule initialization cycle. Render adapters execute tasks but do not select them. |
| Registered generic single-curve plan | `semantic_sources/registered_paired_curve_transform.py`, `semantic_sources/registered_paired_curve_contract.py`, `semantic_sources/paired_curve_table_metadata.py`, `semantic_sources/table_source_files.py`, `semantic_sources/gpc_sources.py`, `semantic_sources/gpc_transform_contract.py`, `semantic_sources/ftir_sources.py`, `semantic_sources/ftir_transform_contract.py`, `semantic_sources/scientific_source_single_curve.py`, `semantic_sources/tga_transform.py`, `figure_plan/single_curve_resolution.py`, `semantic_sources/prepare_curve_families.py`, `workflow/auto_split.py`, `workflow/single_task_bundle.py`, `studio_core/figure_task_evidence.py` | Rule-owned source adapters return the existing scientific-transform object; the generic plan adapter projects output metric IDs, dynamic source-bound axis labels, and source-derived series order into exactly one v2 Cartesian task. DSC, TGA, DTG, UV-Vis, XRD, and SAXS exercise the paired-table owner across signed responses, independent and descending coordinates, independent x grids, header-embedded units, preceding sample rows, and a positive log-y presentation domain. DSC's adjacent digitization provenance records only the registered fixture's evidence; ordinary CSV/XLSX inputs do not require a DOI, publication record, or adjacent provenance. A workbook with more than one matching worksheet fails closed as ambiguous. GPC proves the same downstream owner with multiple Agilent workbooks whose analysed Slice Table and RI detector metadata supply exact sample, coordinate, response, and unit evidence. FTIR uses one read per actual file: structured headers alone distinguish Transmittance from Absorbance, while headerless response remains neutral and keeps every finite point, zero, coordinate, and source row order. Units must be explicit and identity-equivalent except that FTIR's selected rule owns the wavenumber axis when a headerless source does not declare it; this authority is recorded without numeric conversion. No empirical `%T` cleanup, fixed FTIR input domain, anchor, normalization, silent conversion, sorting, interpolation, source-specific sample/value/point/peak/onset constant, DTG derivation, XRD phase assignment, SAXS structural assignment, GPC molecular-weight inference, or undeclared log transform is permitted. Preparation materializes the same snapshot once, then Workflow and Studio reuse the generic single-task Veusz, QA, figure-set, exact-current, and delivery owners. |
| DMA temperature single-task plan | `dma_temperature_contract.py`, `figure_plan/dma_temperature_resolution.py`, `semantic_sources/dma_sources.py`, `semantic_sources/dma_temperature_transform.py`, `studio_core/source_bound_prepare.py`, `workflow/dma_temperature_plan.py`, `workflow/dma_temperature_bundle.py` | Own one independent temperature/storage-modulus task, explicit source-to-Pa-to-MPa conversion, complete source-derived sample/point evidence, typed semantic-preparation attestation, and a sealed terminal table. Plan preview and FigurePlan resolution share one typed source snapshot; execution accepts the full scientific-source envelope and verifies its source/plan identity without backfilling a hash. Tan-delta evidence cannot select it. Studio and Workflow consume the same one-task plan without entering the rheology-temperature two-task resolver. |
| Mechanical curve and descriptive-summary plans | `mechanical_figure_contract.py`, `semantic_sources/mechanical_facts.py`, `figure_plan/mechanical_resolution.py`, `mechanical_task_sources.py`, `workflow/mechanical_bundle.py`, `workflow/mechanical_terminal_validation.py`, `studio_core/source_bound_prepare.py`, `studio_core/mechanical_task_source_lifecycle.py` | Own the complete ordered tensile, compression, and flexural plans. One immutable source-facts projection binds raw specimen values, explicit repeat grouping, representative or individual curve selection, source hashes, units, sample order, and replicate counts. Curve tasks retain measured curves; every summary task uses the shared `box_strip` median/IQR/raw-point contract. Studio renders the primary and all children from task-owned terminal tables inside one rollback boundary; exact-current reopen validates and preserves the registered set without rematerializing it. Workflow independently installs the same exact task set transactionally. Terminal evidence closes request, source, values, statistics, palette, and actual encoding. Child templates do not become new public rule presentations. |
| DMA named-recipe plan seam | `workflow/dma_named_recipe.py`, `workflow/request_rendering.py`, `workflow/dma_execution_evidence.py` | Admit only `rheology_dma` paired with the exact selected `dma_temperature_sweep` plan. Preflight rejects recipe, rule, task, source, sample, metric, unit, encoding-claim, or clipping-bound conflicts before semantic preparation. Auto and recipe then share preparation and task execution while preserving distinct route identity; a route-neutral evidence digest covers terminal data, units, encodings, and axis visibility. Other named recipes remain fail-closed with selected plans. |
| Workflow task-artifact installation | `workflow/task_artifacts.py`, `workflow/single_task_bundle.py` | Install task-owned editable worker trees and remap QA evidence for selected-task bundles. Performance and mechanical plans have transactional multi-task loops; DMA and generic planned single-curve rules, including DSC, share the single-task lifecycle. A private prepared-source marker prevents the terminal worker from repeating semantic preparation without inventing a new source-attestation contract. These owners never select figures, templates, metrics, or scientific identities. |
| Terminal FigureTask evidence | `terminal_request.py`, `figure_plan/terminal_binding.py`, `workflow/request_rendering.py` | Preserve the exact unversioned legacy request when no task is selected. Task-aware terminal requests use a closed v2 envelope containing the exact v1/v2 task and only its metric binding. Workflow parses the selected plan before rendering, then binds ordered unique terminal tasks before reports or publication; the binding leaf is not a FigurePlan-facade export. |
| Studio FigureTask evidence | `studio_figure_set_contract.py`, `studio_core/figure_task_evidence.py`, `studio_core/figure_set_registry.py`, `studio_core/figure_set_storage.py` | Project exact tasks into queue, registry, and spec evidence once. Cartesian tasks alone expose compatibility x/y; ordered tasks expose only ordered metrics. Legacy registry v1 stays readable without task authority, while task-aware registry v2 binds the exact ordered plan, canonical task-owned paths, specs, and editable outcomes before the first replacement. |
| Native series revision and presentation persistence | `studio_core/veusz_series_revision.py`, `studio_core/series_presentation.py`, `studio_core/series_revision_persistence.py`, `sciplot_gui/studio_project/series_revision.py` | Revise source-authorized membership and order inside the live Veusz `Document` as one native Undo step. Persist only the presentation selection while retaining the complete source-bound spec, values, and encodings; derive the visible view only for exact-current document audit. Managed saves commit every ready VSZ, spec, the canonical request, and registry in one existing figure-set transaction. |
| Selected presentation identity | `presentation_identity.py`, `studio_core/presentation_evidence.py` | Resolve one closed versioned `rule_id`/template value from the canonical request plus the already-resolved current rule. It binds only the plan's declared primary task and primary spec; each secondary spec verifies its own task template without minting another identity. Exact-current VSZ stays hash-bound visual authority; recognition never selects presentation. |
| Global visual contract | `policy/plot_contract.json`, `policy/`, `style_contract/` | Single hard-style and option authority. |
| Request validation | `request_contract.py` | Reject unsupported templates/options before rendering and expose the single projection of rule-owned editable defaults onto the existing request surface. Internal renderer policy remains outside the request contract. |
| Ordinary XY series encoding | `studio_render/series_option_context.py`, `studio_render/series_options.py`, `studio_core/series_encoding_contract.py`, `studio_core/veusz_primitives.py`, `veusz_worker/spec_audit/series_encoding.py` | Resolve request provenance, palette, final-series order, per-series overrides, line style, marker, fill, and provenance once. Persist a closed versioned encoding per series; the writer consumes it without re-resolution, and exact-current audit enforces only fields owned by explicit/direct request intent. Performance scatter/radar and scalar fields retain separate semantic contracts. |
| Ordinary XY axis-data visibility | `studio_core/axis_data_visibility.py`, `veusz_worker/spec_audit/series.py` | Recompute finite data extents against both configured render-option bounds and final effective axes. Persist potential below/above-bound counts separately from coordinates actually clipped by the final spec; reject stale or forged visibility evidence during exact-current audit. |
| Pure plot construction | `studio_render/` | Convert confirmed data and policy into render specs. |
| Veusz lifecycle | `studio_core/`, `studio.py` | Core owns implementation; `studio.py` exposes the stable GUI/CLI integration API. |
| Rule contract certification | `readiness/rule_contract.py`, `readiness/rule_certification.py` | Build the canonical rule payload once, derive full/semantic hashes, and compare one already-resolved rule with exactly one validated-envelope registry entry. No Studio policy or I/O belongs here. |
| Validated-envelope registry and scoped acceptance lineage | `readiness/constants.py`, `readiness/registry_model.py`, `readiness/registry_build.py`, `readiness/registry_merge.py`, `readiness/registry_io.py`, `readiness/status.py`, `cli/parsers/diagnostics.py`, `cli/dispatch/diagnostics.py` | Legacy registry v1 remains readable; complete certification and scoped merges write registry v2. `certify` builds from one complete ready-rule acceptance summary. `merge` replaces only selected entries after the same strict row, manifest, contract, evidence, artifact, and manual-visual validation, while every unselected base entry must still match its current full and semantic rule contracts. Versioned lineage records form a non-overlapping complete partition of registry entries and retain each real summary identity and selected rule set; status projects that same lineage. A candidate uses the existing registry schema and never reruns unselected lifecycles, invents hashes, or creates another authority. |
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
    while mechanical, DMA temperature, rheology, and generic rendering,
    including DSC, retain the prepared source boundary. Generic semantic Workflow requests mark
    that boundary only through the private worker environment, so terminal Studio
    reads the prepared table without repeating semantic preparation; the marker
    never enters public request JSON and adds no file-hash gate. If no FigurePlan
    is selected and the specialized adapter
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
30. The shared preparation-attestation owner supplies temperature-rheology
    semantic preparation with one typed source attestation: the source-tree
    hashes before and after preparation must match,
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
31. `semantic_sources/rheology_sweep_domain.py` owns one frozen,
    process-local multi-metric source snapshot shared by rheology temperature and
    raw-export-directory frequency. It fingerprints around one parser-selected raw
    load, applies the request's replicate and order policy once, retains both raw
    and prepared samples, and rejects drift. `rheology_temperature_domain.py` is a
    compatibility adapter, not a second schema. Frequency ignores adjacent derived
    workbooks whenever raw text exports are selected; a metric is task-available
    only when every prepared sample contains at least one paired point, and the
    prepared workbook writes exactly that same metric set. Plot-ready frequency
    workbook files retain their existing direct path.
    `figure_plan/temperature_resolution.py` projects that same domain into exactly two v2
    Cartesian tasks in order: `storage_modulus_vs_temperature` followed by
    stable figure identity `tan_delta_vs_temperature` with canonical metric
    `loss_factor`. Both tasks bind the same source-derived sample order and
    replicate counts. Semantic preparation consumes the domain's prepared samples
    without rereading, recoalescing, or reordering the source; the domain has no
    wire payload and is not misrepresented as a single-y scientific transform.
    Studio performs semantic preparation once, reuses its
    typed attestation for the primary and secondary documents, and installs one
    v2 registry transaction. Workflow requires the plan before task-source
    materialization and binds each terminal request to its exact task. Publish
    and delivery accept only the completed two-task plan and exact membership
    of two editable VSZ documents, two PDFs, and two 300-dpi TIFFs; source,
    task, render, or second-artifact failure rolls back the whole set.
32. `dsc_curve` is a thin consumer of the registered generic single-curve
    spine. Its `SemanticRule` selects `registered_paired_curve` scientific-source
    resolution, `registered_single_curve` FigurePlan resolution, curve-family
    materialization, and the default generic render adapter. A supported CSV or
    XLSX with one matching Temperature/Heat Flow table and explicit
    identity-equivalent units yields exactly one v2 Cartesian `curve` task,
    `dsc_heat_flow_vs_temperature`; samples, order, coordinates, values, and
    source-tree identity all come from that input. More than one matching
    worksheet is ambiguous and fails closed instead of choosing or inventing a
    cooling/heating phase. The registered fixture's adjacent
    `digitization_provenance.json` remains fixture evidence only: ordinary DSC
    inputs require neither it nor DOI/publication metadata. Studio and Workflow
    then reuse the generic single-task registry/spec, Veusz, QA, exact-current,
    rollback, and delivery owners for one VSZ, PDF, and 300-dpi TIFF. This rule
    makes no cycle phase, raw-instrument, transition identity, enthalpy, or
    crystallinity claim.
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
34. `semantic_sources/scientific_source_single_curve.py` is the only binder
    from a rule-owned single-curve source adapter into the generic FigurePlan.
    `registered_paired_curve_transform.py` is shared by DSC, TGA, DTG, UV-Vis,
    XRD, and SAXS; `tga_transform.py` is only its compatibility wrapper. It accepts a
    file or a directory containing exactly one supported table, requires
    explicit units identity-equivalent to the selected rule, and derives
    adjacent/header unit evidence plus preceding/adjacent/fallback sample
    identity from that same table snapshot. Log-domain exclusion follows only
    the registered axis scales: a linear SAXS q coordinate, including zero,
    is retained while a non-positive response is excluded from its log-y
    presentation with closed row evidence. It never performs log10/ln, sorting,
    interpolation, anchoring, normalization, DTG derivation, phase/structure
    assignment, or substitution of a fixture sample, value, point count, peak,
    or onset coordinate. The same transform feeds
    `figure_plan/single_curve_resolution.py` and semantic preparation. Exactly
    one v2 task then runs through the shared generic single-task Workflow and
    Studio lifecycle. GPC uses the same binder and downstream lifecycle after a
    thin Agilent/canonical RT-RI adapter has bound source sample text, Slice Table
    points, and explicit `min`/`mV` evidence. FTIR also uses the same binder after
    one source read; headerless response stays neutral, explicit headers own
    Transmittance/Absorbance, and coordinate reversal remains presentation-only.
    Neither family adds a FigurePlan, renderer, bundle, or chemistry/molecular-
    weight claim. Generic multi-task plans,
    missing or non-equivalent units, and nonfinite values fail closed.
35. Every ordinary-series Veusz spec contains a closed
    `axis_data_visibility` record. For each axis it separates coordinates below
    or above configured render-option bounds from coordinates outside the final
    effective axis. Automatic relaxation is explicit; a potential default-bound
    count is never treated as proof of actual clipping. The worker recomputes
    the record from final spec series and axes and rejects any mismatch.
36. A named Workflow recipe may consume a selected FigurePlan only through an
    explicitly bounded seam. The current sole seam is `rheology_dma` with
    `dma_temperature_sweep`: route identity remains `recipe`, while plan and
    source validation happen before semantic preparation and the execution then
    reuses auto's preparation, sealed terminal source, and single-task bundle.
    The recipe contributes no template, metric, sample, unit, encoding, or axis
    authority. Its route-neutral DMA execution evidence must equal the auto
    route for the same source and request options. All other named recipe/plan
    combinations fail before recipe execution.

Verification requirements are defined once in `skill/SKILL.md`.
