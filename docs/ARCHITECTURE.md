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
- the saved VSZ is the complete legacy visual baseline; an imported semantic
  document owns only its explicitly covered properties, with exact native binding;
- new `ManagedPlot` documents own all represented scientific/presentation state;
  PlotIR, VSZ and render/export products are rebuildable derivatives (the supported
  contract and exclusions are defined below);
- versioned policy and request contracts define constraints;
- QA reports only checks it actually performs.

State authority and renderer choice are separate. The composition facade installs
the Veusz backend router; `ManagedVeuszCompiler` compiles PlotIR into
`document.vsz`, and native inspection, canvas editing and PDF/TIFF export use
Veusz Documents. A Managed VSZ is rebuildable, whereas a Legacy VSZ remains the
complete visual authority. Veusz is the long-term native rendering adapter, not
the semantic application or storage authority. Its replacement would require
rendering, editing, scientific-QA and existing-project migration evidence.

Frequency response completion belongs to `semantic_sources/rheology_frequency_metrics.py`:
instrument, confirmed-column and three-header workbook routes share the original
modulus/positive-frequency derivation and record units/provenance. The frequency
plan defaults to viscosity and admits complex modulus only through an explicit
queue entry. Creep preparation, rule axes and study defaults share original
shear strain versus time, preserving selected interval order and counts.
`rheology_sweep_columns.py` shares exact magnitude identities and explicit unit
evidence across the original sweep reader. Real/imaginary components cannot bind
the magnitude. Literal temperature-labelled frequency Results remain separate
conditions, with their original sample, row bounds, nominal-condition evidence
and point order retained; measured temperatures are never rounded into groups.
`source_inspection/rheology_evidence.py` projects those original intervals for
the semantic task adapter. `task_semantic_frequency.py` binds each interval into
the existing Managed graph and its typed `rheology_complex_viscosity` transform;
the shared metric owner computes `hypot(Gprime, Gdoubleprime) / omega` only with
explicit compatible units. An original source may omit unrelated text columns
from numeric loading only when every direct consumer is a validated deterministic
`select`; selected metadata, complete source hashes and physical rows remain bound.
Exact-current file comparison rehashes the full bytes and rejects identity,
mode, size, modification-time or content changes. A ctime-only metadata update
between two individually stable snapshots does not invalidate identical data.

`data_mapping/original_tables.py` owns the physical table catalog, original-cell
port and byte-bound observation snapshot, above the unchanged raw reader. The
catalog retains every original table ordinal. A qualified source/table/block
selection resolves its table scope before observing measurement cells;
`task_semantic_selection.py` then intersects observed blocks with exact Test and
block predicates before coordinate decisions and builders. Unknown references
and empty intersections fail closed. Original block IDs/order, physical rows,
missing positions and full source SHA stay bound. Unobserved tables retain their
catalog/hash and explicit observation state, without invented blocks or counts.
Omitted or Test-name-only selection retains conservative full discovery.
Selection never creates a filtered file or another scientific executor.

Existing explicit `table_selection` consumers use the same observed-sheet scope
for fresh validation, Managed reload/append, templates and categorical bindings.
Multi-pair/replicate confirmation includes every declared sheet. Explicit
cross-sheet metadata evidence remains readable independently of measurement
scope; it cannot become a measurement candidate. Full historical snapshots keep
their original payload and comparison semantics. Row parsing, accepted numeric
lexemes and acquisition-stage interpretation are unchanged by this boundary.

Ambiguous tables are resolved before coordinate validation. The existing task
question journal then replans only the selected source facts, retaining earlier
answers and complete available/selected/excluded provenance under a new question
identity. Format dispatch reads those same selected candidates.
`task_semantic_temperature.py` owns the intersection of explicit secondary
header/column ID, legacy temperature header and confirmed role. Planning and
Managed binding consume that one selector; disagreements fail before creation.
Unused temperature metadata does not become a prerequisite for source-order
stage concatenation.

`task_semantic_stages.py` owns complete acquisition-stage domains for planning
and lowering. Finite observation runs remain display evidence. Only adjacent
measured decreases in the resolved time column locate a reset; a decrease across
missing time is an unresolved boundary. Every confirmed physical position stays
in its source region. Cumulative assembly passes complete stages to the sealed
executor, or refuses with original-row evidence. Unexecuted drafts with missing
coverage need reconfirmation; saved creation requests do not replan.

Current semantic coordinate planning and expert/append admission use
`plot_transforms/unit_relations.py` for registered unit relations. Finite endpoint
spellings are separate from display formatting. Legacy `C` denotes Celsius only
with observed temperature metadata or an exact selected user quantity fact;
charge `C` retains its literal identity. Planning freezes that context beside the
exact source coordinate, and supported lineage consumes that proof before
falling back to original source-header evidence. A renamed graph or display label
cannot establish temperature. Impact source readers share an exact complete
`kJ/m²` spelling identity; area prefixes cannot relabel unchanged values.

`plot_engine/current_unit_admission.py` admits new expert creation before its
creation journal, and actual scientific edits before reservation or execution.
It consumes original metadata from the existing scoped source load. The shared
`original_coordinate.py` traces finite supported graph edges, including executed
columns absent from visible mappings. Scientific layer semantics with a unique
original-column selector can express a user quantity fact; scale labels alone
cannot. Raw charge evidence cannot be erased by rename or a Celsius spelling
confirmation. The real frozen context is under
`provenance.binding.semantic_task.resolution.bindings`; verified CAS binding
reads use the same content-store byte owner without decoding unrelated arrays.
An affected unexecuted C draft without adequate context needs confirmation.
Saved creation/transaction replay, no-ops and presentation edits do not re-enter
new scientific admission. Historical executors remain sealed; unsupported
compound context and unknown derived/external unit lineage remain explicit
refusals.

New semantic creation records `domain_semantics: current_view_v1`. Each endpoint
has a current auto/fixed rule; numeric domains and ticks are their presentation
projection. Auto uses visible drawable members, while fixed endpoints preserve
comparison windows. Hidden members retain complete scientific validation.
`plot_grammar/current_view.py` is the numeric writer after resolved datasets are
available and before final storage/sealing. Creation, append and saved edits use
it; compilation only validates the projection. Manual tick conflicts refuse the
candidate rather than deleting ticks or expanding the data extent. Current
rules are never reconstructed from original creation intent. Unmarked documents
retain their existing numeric-domain scientific projection and replay.
`mark_geometry.py` supplies data primitives to extent/QA and native lowering;
native adapters alone add physical caps, strokes and relative coordinates.
Semantic measurement channels, including secondary temperature, retain point
marks for isolated finite observations instead of fabricating line segments.

Managed resolution and binding dependency graphs both consume the final
canonical document after content interning. A pre-CAS graph cannot serve as
evidence for a different canonical scientific hash.

The existing `source.sha256` scientific operation reconfirms the complete
physical-file group. `managed_source_groups.py` owns canonical path matching;
equal bytes in two distinct files cannot establish the same group.
`managed_source_revision.py` normalizes full declarations, keeps no-ops in their
original CAS representation and checks current facts through the admission
owner's single selected-table load. Original conditions, coordinates and typed
derived inputs cannot be withdrawn to authorize a new SHA. Historical creation
and transaction requests remain historical; source refresh never rewrites them.
Virtual source targets share the same full/summary/edit descriptor and are not
fictional presentation objects. Input-file accumulation rejects conflicting
expected hashes before flattening a physical group.

New confirmed mappings separate physical source views, original sample/category
facts and display aliases. `mapping_contract/source_identity.py` mints each
logical view ID from the canonical original namespace and exact sheet/row/column
selector; SHA witnesses the source version rather than defining that ID.
`sample_labels` retains original facts and `display_labels` is presentation.
`data_mapping/source_projection.py` derives render correspondence only after
reproducing the existing execution receipt. Snapshot-origin parameters are
runtime arguments built by the captured-byte owner, not request fields or a
self-authenticating path/SHA declaration.

Raw replicate groups and ordinary categorical values use explicit source facts,
never split aliases to recover category or condition. Independent groups sharing
one category occupy deterministic group slots while axis ticks stay at category
centres. Current style/order/include selectors are frozen to IDs at creation;
saved rendering does not reinterpret an alias as a selector.

Current explicit XY pairs still run their scientific adapter, preparation
attestation and registered FigureTask. At the mapping-to-preparation boundary,
the legacy intermediate metadata/model string slot named sample carries the
verified logical view key; it is not a new original-sample assertion. Receipt
sample facts and final source bindings retain the original sample, including
several distinct physical views of the same sample without pooling. The native
encoding uses the same view key and applies aliases only after terminal science
validation. Historical requests without structured identity retain their original
serialization and replay; no alias, file stem or worksheet suffix migrates them.

Native continuation applies one style-transfer plan to the saved VSZ and the
presentation fields already represented by its spec. Axis point-size fields and
series encoding use their existing shared field owners. The named
`style_transfer_storage` port stages, strictly audits and atomically installs
both files through the existing figure-set transaction, retaining both originals
on failure. An opaque native font face stays native; it is not guessed into a
global semantic theme. Exact native/spec style fidelity and source-data replay
are separate checks. `source_coverage/spec_units.py` uses those same represented
axis style fields when hashing source-data replay units, and excludes only
direct-label size from the existing label representation. Scientific axes,
values, category coordinates, source bindings and unknown fields remain exact;
the replay check neither erases saved styles nor relaxes native presentation
audit.

Saved Studio metadata refresh is an explicit mutation. Canonical-project reuse
without overrides or regeneration may admit one registered ready primary VSZ
through `adopt_saved_native`, then select its fresh generation before cloning.
Other outside members, secondary or multiple native saves, and unresolved commands
block save admission until explicitly reconciled. Direct VSZ reads
and saved-project queries do not adopt bytes; Managed artifacts retain their
existing semantic/backend authority.

Information loss is permitted only in a named projection. Full physical rows,
missing positions and original numeric values remain in source/mapping evidence;
finite raw display points do not replace that domain. Recorded conversions and
derived calculations produce separate datasets with bound inputs and units.
Presentation aliases cannot supply their sample, quantity or source selector.
Numeric windows/ticks are projections of current rules, and pixels/exported
glyphs cannot reconstruct their scientific authority. Native geometry and
numeric audit precede publication QA; either one's success cannot stand in for
the other's unperformed checks.

Lifecycle success, provenance, artifact QA, human review, and journal
compliance are separate evidence claims.

The explicit `rheology plot` suite is documented in `RHEOLOGY_TTS.md`.
The external AI owns processing, calculations, scientific purpose and the prepared
numerical plan with source bindings, units, transform ledger and series roles.
The local plotting entry point validates that plan, applies governed templates
and exports its coordinates faithfully; it must not call the TTS analysis or
fitting owners. The older combined `rheology tts` utility remains a compatibility
route. The separated plan distinguishes measured/derived
point-line traces, marker-only TTS/shift estimates, line-only predictions,
reference lines and native bars. Initial native audits verify resolved style
and numerical bindings. Composition reuses shared Veusz primitives and exact
export. `rheology capabilities` exposes the contract; style preview/apply binds
current document SHA, sources and compiled specification before editing declared
native settings without refitting or replacing data. Ordinary re-export records
style deviations rather than restoring defaults. Visible suite VSZs remain
editable authority, with hidden creation evidence; the existing managed browser
editor/audit is not expanded or bypassed for this route.
Prepared creation continuation is owned by its narrow workflow checkpoint and
native per-figure creation receipt. Explicit `plot --resume` binds the original
request, sources, prepared bytes and compiled template contract. Saving/saved/
completed states prevent a missing or uncertain saved VSZ from being regenerated.
Completed native figures are verified and reused; unfinished exact export uses
the saved document. A complete sealed delivery is assembled privately with final
path bindings and installed without replacing an existing destination. Unknown
older partial workspaces and changed saved bytes require inspection. This is
creation continuation only; later native edits use existing exact export.
The first-failure repair projection shares those read-only continuation guards
under the existing workflow lease. It attaches guidance to the original exception;
unknown, changed, uncertain or busy evidence produces inspection guidance. A small
closed private worker failure record carries only native project-busy status while
retaining the original traceback. The projection neither acquires another lease nor
allocates files, renders, exports or installs a package.
Exact suite re-export uses one native worker for the same complete native audits
and individual saved-document exports. The suite lifecycle owns hidden staging,
whole-set source/specification/document fingerprints, inventory verification and
publication through the existing presentation-storage replacement transaction.
Failure before publication preserves the visible set; ordinary publication
exceptions roll back replacements. The workspace lease serializes CLI operations,
while native GUI saves are detected by fingerprints. This does not provide
automatic process-crash recovery or a second document authority.

Bound native suite figures also share `plot.open/describe/patch/decide/resume/export`
through `plot_engine/prepared_routing.py` and `workflow/native_suite_operations.py`.
They retain LegacyPlot/native authority and advertise only actual existing
legend and relative-note fields. `native_suite_objects` binds the selected
spec/native/source bytes to a stable figure ID and opaque content-bound revision;
descriptions read current native values. Recognized invalid bindings fail closed
before ordinary importing. `native_suite_preview/storage/transactions` reuse
suite `style_previews`, exact native state audits, snapshots and guarded
publication. They retain original requests for key replay and export-only
continuation, preserving opaque native settings and scientific evidence.
Selected export validates and executes only the chosen figure; unselected
optional native/spec/export files are not prerequisites. Whole-suite export and
the older separated-layout style guard retain their compatibility boundaries.
Creation handles project in-memory successful metadata without another native
inspection. The native backend owns role painting order while scientific and
legend order remain as declared.

The selected figure's existing native-audit sidecar participates in the same
guarded preview baseline as its document and exports. A decision is persisted
before publication; contradictory decisions are refused, and accepted recovery
reuses the existing publication owner without reapplying native edits. Creation
export receipts may establish currentness only when the canonical visible files
match their byte seals. A no-op still inspects current native display state and
does no native mutation, rendering or export.

Managed previews return the scientific audit already passed by their render
stage, after checking the preview receipt and current native SHA. The backend
consumes that same-stage result once. Independent apply/export and source/native
drift checks retain their own boundaries; this introduces no cross-stage audit
cache or new authority.

## External control and native document boundary

### Semantic document engine

Actual new ordinary `stacked_curve` creation records
`direct_label_layout_version: physical-clearance-v1` before FigureTask requests
are frozen. `studio_render/direct_label_layout.py` owns that selection and the
shared deterministic physical placement used by both native spec generation and
source reconstruction. Explicit side, vertical alignment or offset retains user
ownership. A saved request without the version retains the sealed legacy anchor;
an unknown version is refused. Managed intent and exact-current native export do
not acquire a new creation default. The retained 24-file layout-v1 compiler pin
and historical visual baselines are not rewritten.

The new planner reserves whole text footprints against complete visible curve
segments and marker envelopes inside the existing physical frame. It does not
change data, axis ranges, fonts or figure dimensions to force feasibility.
`veusz_audit/direct_label_ink.py` replays each label's existing native paint record
into a finite read-only glyph measuring device: the actual text-run font,
paint-device DPI, shaped glyphs, fallback faces and transform own its unclipped
ink envelope. The envelope also includes Qt PDF's QFixed 26.6 truncated glyph
origin, whose coordinate conversion error is less than one 1/64 device pixel;
glyph metric edges additionally enclose the at-most-two-scalar QFixed metric
reconstruction error. These output/metric representation envelopes do not relax
the frame or curve-clearance target. Terminal materialization
retains and validates the recorded selector rather than dropping it from its
minimal request. Upstream ascent-only control boxes cannot certify descenders.
Actual glyph metrics/path bounds and native visible XY stroke/marker geometry
are consumed by `studio_core/current_direct_label_review.py` only for the recorded
automatic contract. Missing, stale, unsupported or infeasible geometry blocks
that contract. QA never rearranges current native labels; unversioned historical
and explicitly placed labels do not acquire this new refusal policy.

The implemented authority boundary is specified in [Managed plot design](DESIGN_MANAGED_PLOTS.md).
`LegacyPlot` retains native authority; `ManagedPlot` owns its complete supported
state and compiles through backend-neutral resolved PlotIR. Public CLI creation
and MCP export have passed deletion of the entire artifact directory and IR cache,
followed by recreation with identical semantic IDs, data, scientific/IR hashes
and full native state. A shadow import never acquires managed authority by relabeling.

`plot_document/` is renderer-independent: closed versioned scientific and
presentation domains, stable object IDs, independent content hashes, atomic
semantic patches and engine-computed risk. Pure Template / Binding / Theme
composition and dependency planning are separately validated. These model hashes
prove represented content only; they never replace compiled/native numerical
audits. Scientific transformations cannot be smuggled into presentation patches.
Figure scientific projection is inline control state under provenance.figure_spec;
presentation projection lives under layout.figure_spec. Lossless rejoining is
validated, bindings must match every layer, and no second mutable figure store is
introduced. Scale-domain changes invalidate compile/render/export without rerunning
data transforms. plot.describe publishes typed grammar edit schemas by semantic ID.
The existing scientific executors remain the owners of calculation and preparation.

The implemented additive grammar contract is recorded in [Figure Grammar v2](DESIGN_FIGURE_GRAMMAR.md).
`plot_grammar/` owns Figure/View/Layer/Mark semantics, independent Scale/Axis,
explicit resolution groups and theme precedence. `plot_layout/` owns physical
constraints and hard/soft layout QA. Resolved PlotIR v2 is separate from v1; the
existing document/transaction/data owners remain authoritative. Grammar backend
lowering dispatches on generic marks, never scientific-family names. A-F native
acceptance covers actual rheology, NIST impact data and UV-Vis source data, complete
artifact/IR-cache deletion, theme identity and data-anchored annotations. Native
text bounds are measured before clipping; hard failures block export and soft
heuristics remain warnings. This is bounded layout QA, not journal certification.

New FigureTemplate creation pins `sciplot-house-style-v1` in canonical presentation.
`rendering_contract/` owns extracted immutable resources, their source evidence and
content bindings; grammar resolves them below explicit themes and overrides.
Single-panel defaults use the old fixed 60 x 55 mm frame and absolute margins.
`sciplot-figure-composition-v1` separately owns new inter-panel placement. The
solver rejects impossible constraints; native text fitting never resizes the
prescribed frame. Historical unbound revisions retain their previous compiler
interpretation and are not automatically restyled.

New semantic tasks explicitly select `axis_layout_policy=decorated_secondary_sides_v1`.
It allocates conservative additional right/top decoration space before sealing
PlotIR and records base versus resolved margins. Omitted policy retains the
saved historical layout interpretation, including existing multi-axis figures.
The task adapter tries declared house size presets against the same pure layout
checks; it records the first fitting width rather than reducing fonts or dropping
content. Native text QA remains a separate final check.

`panel_assembly/` composes existing figures and images through that physical
solver, with explicit sparse cells and row/column spans. The pure `document`
leaf, public `model`, `operations`,
`history` and `storage` own a closed versioned placement document, local undo/redo
and atomic writer-lease saves. Session-bound original bytes refuse stale saves,
including independent readers of the same revision; a noncooperative external
writer after the final check is not a kernel compare-and-swap guarantee.
`sources` captures exact Legacy VSZ or canonical Managed authority and rejects
source drift. `native` reflows supported native pages at target mm and compares
opaque payload/science before and after portable Save. `export` places those PDF
pages at physical 1:1 with image-only nondestructive crops and measured outer
letters. Real native text/legend bounds gate publication before clipping.
`preview` renders current frozen sources in temporary storage without Save;
`desktop_previews` caches bounded PNG bytes off the UI thread and constructs Qt
pixmaps on the UI thread. Painting and local spacing do no source I/O or AI work.
`desktop*` is the native workbench adapter; `service` is the shared compact
CLI/MCP new/inspect/apply/export port. Saved placement references do not replace
scientific authority. See [panel assembly design](DESIGN_PANEL_ASSEMBLY.md).

Metric-flow axes and simple legends carry complete typography, physical padding,
frame and explicit legend membership into PlotIR. Native text metrics are measured
by QA; metric flow does not retain ignored hand-positioned text coordinates.
`plot_backends/house_guides.py` maps only resolved IR to native axis/key primitives.
`qa/rendering_regression.py` independently compares old/new structure and native
pixels, with environment matching and discriminating negative controls. This is
separate from rebuild equality. See [rendering design](DESIGN_RENDERING_CONTRACT.md)
and the root old-contract/drift reports for the exact compatibility scope.

`plot_ir/` owns version dispatch, the existing v1 Cartesian contract and document
projection integration; `plot_grammar/` owns closed FigureSpec and PlotIR v2.
`SemanticCompiler` dispatches explicitly by the canonical grammar version.
It expands bindings and theme overrides into explicit dataset references/values,
axes/scales/ticks, styles, dimensions, legend and annotations. It imports no Veusz
object paths. `plot_backends/managed*.py` and `veusz_worker/managed.py` only lower
this resolved IR into a fresh native document and compare its complete native
state, including data/reference/custom-definition state. Unsupported backend
capabilities fail explicitly. Scientific/IR identity excludes renderer timestamps;
compiler/runtime fingerprints and actual artifact byte seals are separate.

`plot_transforms/` owns typed select/rename/scale/normalize, original-row selection,
explicit multi-input time concatenation and physical unit conversion, plus a fixed-file
external executor protocol. Node intent and execution provenance jointly record
stable IDs, parameters, input/output dataset IDs and hashes, executor identity,
determinism and status. External execution binds interpreter/script bytes and
closed parameters; existing scientific algorithms remain external owners.
Non-deterministic declarations are representable but execution is unsupported.
There is no client-supplied code-string evaluation. Original sample/column/row
lineage is checked through supported transforms, with missing values retained.

Display interpolation belongs to the presentation side of FigureSpec marks.
Its deterministic PCHIP arrays and interval lineage are compiled separately from
the original datasets. Native line geometry binds those arrays; measured points
and marker geometry retain the source-bound scientific arrays. Gaps and duplicate
coordinates cannot silently become a fitted continuation. This reuses PlotIR,
native compilation and exact array audits without a second scientific ledger.

`plot_backends/` owns current-native import and the Veusz translation. Imported
projects are `legacy_shadow`, never falsely fully represented: unmodeled objects,
layout and native state remain in the saved VSZ. Actual native style is imported,
not regenerated from an older spec. Managed title/annotation state retains its
semantic ID when hidden. Linear axis bounds preserve ticks, units and direction
and reject clipping. Legend visibility updates native and specification together;
placement retains its original preset for rollback. Ordinary managed annotations
retain coordinate mode and arrow anchors. All native paths stay in a private binding. Saved-file/source
drift invalidates that binding and prevents writes or cache reuse. Source coverage
is limited to recorded source paths; an old project cannot acquire nonexistent
original-source provenance through inference. A selected-VSZ-only external save
can be imported through a frozen `plot.decide` offer, actual native scientific
audit and one visual review. Stable IDs follow unique existing native bindings;
source/specification or structural identity changes are not guessed. Acceptance
appends a revision and exports without rewriting the manually saved VSZ.

`project_lifecycle/` owns the semantic figure-aggregate application and repository
contracts. ProjectApplication owns lifecycle transitions; ProjectRepository is
the sole writer of immutable revision snapshots, atomic head pointers and durable
idempotency journals. Independent commit/export statuses and compact receipts
project that same store; compatibility modules under `plot_engine/` delegate.
Its sibling `.sciplot_documents/` storage is outside the native project inventory.
Each new patch validates its entire batch and base revision before reserving work.
Safe presentation changes with passed native scientific audit commit automatically;
review-risk changes return one frozen preview. Apply recovery delegates to the
existing native transaction, then commits the semantic head once. Export failures
leave the revision committed; retries never reapply it. Only known transient
preview/export failures get one durable extra attempt. Undo appends a revision.
This is recoverable logical execution, not a claim of atomic multi-file filesystem
replacement across power loss. Full candidate/native evidence stays local.
The lifecycle recovery owner projects that existing frozen receipt into descriptions
and validates a compact plot ID/base revision/idempotency key before replaying
the original saved patch. CLI, RPC and MCP delegate to this owner. Recovery
cannot accept a preview, invent a missing request, rebind changed inputs or
advance a historical transaction as current. Transport failure guidance retains
the original key and distinguishes a request not sent from a lost reply.

A failed Managed export-only transaction with an exact native publication-QA
layout rejection may be superseded by a nonempty typed presentation correction.
The guard binds the current head, unchanged science, sources and known native
bytes. Unknown/transient failures, stale or scientific changes and untracked
native files remain blocked. The original transaction keeps its error and
diagnostics plus a durable supersession reference; its old key cannot reclaim
active work. The new correction uses the existing preview, decision and export
phases rather than a parallel recovery workflow.

Managed descriptions expose `export_current` from the service's existing recipe
and exact byte-inventory validator. Clients consume this read-only evidence in
the owning process environment; they do not reconstruct its renderer identity
from a different process. Missing or uncertain evidence is false/unknown and
does not trigger native work. This is separate from a task's final package
inventory and from the installation readiness reported by Doctor.

Large imported scientific provenance values are interned once into immutable
content-addressed JSON blobs before revision zero. References seal exact bytes;
revision/journal writes retain their hashes rather than copying numerical arrays.
Every use and pre-apply boundary verifies the full referenced bytes. Existing
inline history is not silently rewritten into a different hash representation.

Byte-sealed render/export caches reuse exact current inputs; export reuse checks
the complete publication evidence and file inventory, including added/removed
visible files. Source changes invalidate dependent compile/render/export nodes.
Presentation patches do not invoke scientific preparation. Managed graphs use
source -> transform -> mapping -> compile -> render -> export content identities,
and each binding seals only its own source/executor closure. Unrelated plot
artifacts never enter this fingerprint. Explicit scientific patches can refresh
a source hash, transform parameters or a registered executor identity; only
affected transform cache keys execute. A changed file alone does not execute work.

`plot_protocol/` owns serialized local JSON-RPC over a private UNIX socket. The
daemon serves `project.open` and `plot.describe/create/patch/render/rollback/export/decide`.
CLI and MCP are thin clients of the same service, with no provider/model calls.
The backend owns a persistent native child through `native_process/`, routing
existing worker commands under an explicit scope. Each command reloads a fresh
Veusz document; Qt/imports are reused, not unchecked document state. A timeout or
disconnect terminates the child without blindly repeating a mutation. Full source,
runtime and relevant environment drift fails closed before cache identity can
bless output from an old loaded worker. A source/config/interpreter digest
separates daemon versions; an active mutation is never hot-reloaded. Connection
loss carries the original request identity and never silently resends a mutation.
Files are verified when a request uses them; there is no background source
recomputation or claim of a general live filesystem watcher.

While `serve()` owns the main thread, a temporary SIGTERM handler requests a
normal stop after the current bounded request. The existing service `finally`
closes the native worker through EOF and an actual wait, then removes the owned
socket; the previous signal handler is restored. Thread-hosted servers retain
their caller's signal policy. SIGKILL, abrupt exits and worker timeouts do not
acquire normal termination evidence. CLI auto-start still detaches the daemon;
later clients are not its OS parent, so socket removal or a daemon terminal
frame cannot substitute for that parent's actual wait ledger.

The `task style` compatibility facade routes already-imported figures through the
semantic engine; unimported projects and other retained task operations continue
through their existing owners. Native preparation, audit and publication are shared,
not duplicated. Template creation binds explicit original-table cells, units and
stable series IDs through the current mapping/preparation owners. A private
prepared-only checkpoint saves one guarded native baseline without publication;
one semantic transaction then applies the theme and exports once. Interrupted
preparation resumes its sealed checkpoint; changed inputs/output conflicts block.
Unsupported template transforms, layout or custom guards are rejected explicitly.
`mapping_contract/table_selection.py` owns the shared pure selection schema;
`task_prepared_creation.py` owns the prepared checkpoint and never claims delivery.
That prepared-native creation path is retained only as explicit `mode: legacy`
compatibility. Template-based `plot.create` now defaults to ManagedPlot, requiring
a fully represented Cartesian v1 or FigureTemplate v2; source-only task/CLI creation remains
the existing compatibility workflow. No automatic conversion of legacy VSZ occurs.
Managed creation commits document/revision before compiling disposable artifacts.
`managed_backend.py` reuses the same transaction state machine: a durable compile
intent plus exact full-state inspection recovers a VSZ saved before its build
receipt. A byte-sealed product from an obsolete compiler can be rebuilt; unknown
native changes cannot. Export-pending resumes without scientific re-execution.
An external executor interrupted before durable output storage is marked uncertain
and is not blindly repeated. Complete managed presentation rollback restores
theme/layout/export intent as well as represented object properties.

`external_mutation.py` records before/after identity and semantic diffs. Legacy
known-style classification requires an exact baseline and a closed transcript
comparison; concurrent unrepresented changes remain opaque. Managed inspection
requires complete candidate native equivalence. Both known and unknown manual
managed changes currently block automatic adoption; the latter cannot become
canonical state. Managed external-delta adoption and explicit managed-to-legacy
conversion are not yet implemented.

Managed scope is one Cartesian XY figure, supported deterministic transforms,
explicit layout, ordinary labels and PDF/TIFF exports. Multipanel and arbitrary
Veusz features remain unsupported. Managed export readiness proves exact native
fidelity and sealed nonempty output; it does not imply complete publication QA,
arbitrary-theme text-overflow checks or cross-machine font-pixel determinism.
Existing legacy publication owners retain their original QA boundaries.

`studio_core/veusz_line_joins.py` installs the optional native XY
`PlotLine/joinStyle` setting in SciPlot's Veusz creation, loading and export
runtime. Existing curves keep the upstream bevel default; an explicit round
selection changes the QPen join only, preserving coordinates, interpolation,
caps and width. It is saved in VSZ and uses the shared ordinary-curve style
catalog and scientific edit gate. Round-join documents require the SciPlot
runtime extension when reopened; unmodified standalone Veusz is not a supported
loader for that additional setting.

External AI is the product task interface and the direction for further
development. The public CLI is the reference adapter for source planning,
saved-project queries, native edits, exact-current export and continuation.
It calls existing local domain services without starting an internal provider.
`task_control` orchestrates bounded create/edit/export requests over those owners;
task receipts live outside active projects and do not define scientific readiness.

The semantic task adapter accepts multiple source attachments and a small closed
coordinate intent. Local source evidence supplies current tables, columns, units
and reset-time segments; the source-bound plan exposes real ambiguity before
expanding existing FigureTemplate/Binding contracts. Scientific authority remains
the ManagedDocument. The task checkpoint owns only process state and immutable
attempt references. Revising a draft and retrying a committed attempt are distinct
operations; retry cannot recommit science or execute transforms again.

Without an explicit experiment rule, numeric task coordinates bind the existing
original-value `ordinary_xy` context. Omitted and explicit ordinary context have
the same meaning; source layout and axis quantities do not select an experiment
or authorize a derived quantity. `task_semantic_plan` resolves original columns,
units, views, stages and axes once. Lowering validates those literal bindings and
executes the existing typed transforms without selecting coordinates again.
An old unattempted draft is preserved in history and resolved against its
unchanged sources; a frozen creation attempt retains its original request and
recovery identity. An uncertain attempted outcome cannot become a new draft.
`source_context` records caller statements in semantic provenance. Absent an
explicit stage request, the plan retains the full original block, including
missing coordinates and time reversals; it does not infer stage concatenation.
`task_semantic_axes` projects explicit ordinary linear/log choices through the
existing axis policy. Log validation examines every mapped observation, with no
silent deletion or shift. `task_semantic_curve_bindings` resolves qualified
original X/Y pairs for declared compatible `quantity_members`, retaining each
pair's grid and scientific quantity on their shared scale. Views validate the
qualified original identities; the semantic plan owns quantity and unit choices.
The existing `table_selection` owns each confirmed physical row domain. Numeric
first/last/finite counts are observations within that domain, never replacement
bounds. Shared source observation retains literal Test/Result/Interval identities
and declared record members, including all-missing members and shorter tails.
The pure physical block observer lives in `semantic_sources/instrument_regions`;
`table_scanning` retains its existing consumer names. Original numeric-cell
lexeme parsing belongs to the existing `numeric_separators` owner, with the
old parser semantics retained.
Empty storage extent does not establish a measurement; a disconnected inferred
body needs clarification. Separate Tests retain separate domains unless an
explicit supported time-stage contract assembles them. Display finite masks do
not compact the source grid or change its row references. This raw binding
cannot replace an instrument adapter or combine rules, stages or secondary axes.
`impact_presentation` admits `raw_only` only for the existing box/box-strip raw
point path. Preparation, layout and analysis skip summary calculations, while
the native audit retains all original replicate values and category order.

`plot_engine/managed_source_append.py` builds a bounded scientific update for one
original-value Managed XY view. It validates original table selection and column
metadata through existing source owners, then extends the current binding and
FigureSpec with deterministic select nodes and layers. No caller arrays or
transcribed templates are accepted. Compatible quantities, registered unit
relations and existing complete-data scale validation apply. The unsealed
`plot_transforms/unit_relations` leaf projects the existing registered executor;
it introduces no independent aliases or numerical conversion rules. A real
numeric conversion needs the appended curve's explicit `x_unit` or `y_unit`
equal to the current axis unit. Identity spellings need no numerical permission;
typed conversion still preserves their exact recorded unit labels. Normalization,
fitting and stage assembly remain outside this operation. A path/ID-only request returns original
metadata before transaction allocation. A complete request uses the existing
preview, source revalidation, journal, decision and reply-loss recovery owners.
Before/candidate images and scientific evidence remain attached to that receipt.
The Figure `legend.order` edit projects directly into the existing presentation
guide's `order` field. A nonempty value is a full permutation of that guide's
eligible layer identities, including hidden layers; the compiler filters hidden
entries for rendering. An empty array restores automatic order. Existing
validation, review, rejection and reply-loss recovery own the edit, with no
transform execution or scientific hash change. Managed line-pattern schemas and
writers share `style_values`' projection of the existing seven native patterns,
retaining historical `dash` and `dot` aliases without rewriting saved values.
The existing exact native-state comparison audits curve and legend line styles.
`append_target_lineage` traces the actual select, row-slice, rename and registered
unit-conversion chain back to original columns and physical rows. Eligibility
does not depend on a global whitelist of every transform in the document.
`append_measurement_identity` requires the same original SHA and preserves the
existing metadata-region path. `append_source_regions` permits a different
same-file region only with one exact block from the shared physical observer;
its literal Test identity uses the existing source-cell metadata evidence.
Partial, ambiguous or cross-Test regions gain no such permission. Overlapping
original responses are rejected even when hidden or assigned another alias.

`task_replicate_summary` accepts an explicit missing-value policy or the current
source-bound question response, then uses `semantic_sources/impact_replicate_disclosure`
to count original finite replicates. Mean/sample-SD calculations remain in the
existing bar owner. `source_coverage/replicate_disclosure` freshly checks the
complete typed disclosure against the canonical original input before native
publication or summary CSV export, including when prepared tables are the
renderer's input. Original physical columns and missing cells remain recorded.
The visible summary projects audited numbers with round-trip precision and
binds their original-source tree and saved-spec hashes; it creates no new method.

`mapping_contract/categorical` closes the ordinary original-file/table binding.
`task_categorical_creation` owns its existing task question and missing-value
continuation; `categorical_plan` seals that binding into the current plan-preview
identity without inventing an experiment or FigurePlan.
`studio_render/categorical_bindings` reads the declared original physical cells,
and `categorical_bound_series` reuses given-value point-lines or the existing
mean/sample-SD bar groups. Sample/condition identity, selection, category order
and display aliases remain distinct. `categorical_disclosure` derives original
valid-n/missing-cell evidence; publication compares the complete binding and
typed disclosure against the canonical source request and fresh original input.
Cold query indicators check the binding's actual original-file SHA while still
reporting `scientific_audit_evaluated=false`; they do not fabricate a FigurePlan
or substitute hash currentness for scientific publication audit. Single-primary
receipts reuse their existing canonical figure and delivery records.
The current legend placement retains bounded reserve and final QA; saturated
overlap can continue that existing search, while explicit corners are measured
against the same final axis contract as native export. The requested corner and
explicit axis bounds remain fixed; unspecified bounds can use the existing
bounded reserve. Its recorded limits and QA use the actual final axis extents.
Ordinary grouped summaries reuse `component_legend`'s existing row/swatch contract
and the bounded axis reserve. `segmented_legend_clearance` derives a conservative
top band without moving explicit bounds. Native `segmented_legend_geometry`
measures painted component boxes against the complete bar/SD shapes; the current
layout review binds that evidence to document bytes and exact expected paths.
Missing or stale geometry and a legend outside its fixed frame remain blocking.

`studio_core/categorical_display` keeps late aliases/styles in the closed
`presentation_categorical_display` overlay. Original category labels, group IDs,
observations, statistics, canonical request and scientific hashes retain their
existing authority. Current edit context exposes stable original selectors and
complete expected display values; bars allow color, while given-value point-lines
also allow represented markers/fill and native-key layout. The worker applies
the existing native operations and audits unchanged numerical datasets plus the
effective presentation. `categorical_display_preflight` runs the complete current
source/native audit before export can touch files; the existing inside-export
audit remains. One explicit conflict subtype crosses the existing four-key
worker failure envelope. Cold and persistent workers frame that subtype before
native settings chatter can obscure it; other errors keep their original output
and failure behavior. Retry uses the existing task and export recovery owner.

`performance_comparison/metadata` exposes read-only original Metric IDs and unit
facts. Its closed `selection` contract binds exactly two Metrics, source SHA,
per-Metric user statements and the existing scatter display choice.
`selection_rows` and `selected_scatter` retain exact original numeric cells,
physical selected rows, explicit missing-pair masks/counts and material identity.
`plan_source_options` carries this declaration through the ordinary expected-plan
identity. Native source reread independently derives the same complete evidence;
changed units, masks, statements or source bytes block publication. Selecting
`preserve_original` suppresses display jitter without changing the older default.

Task-to-Managed calls cross the existing local AF_UNIX protocol. Its
`plot_protocol/socket_client` leaf owns the shared validated transport without
importing the concrete service. The compatible direct/socket facade retains the
explicit direct path. This keeps the task orchestrator independent of
`PlotService`, whose source-only compatibility entry can still use ordinary
tasks. A common lower error leaf preserves the public task exception identity.

The `edit` CLI opens the default post-delivery human editing surface for an existing
saved figure. `Open_in_SciPlot.command` opens its bound delivery through this CLI;
the retained `Open_in_Veusz.command` is the advanced and portable native route.
`live_editor` owns session binding, serialized browser commands and the
loopback HTTP adapter. `veusz_worker/live_session.py` keeps one Veusz Document on
its process main thread, applies advertised native operations, uses native undo/
redo and renders through the existing preview function. A PaintHelper built from
the same document and render parameters performs revision-bound pixel hit testing.
Rendered keys expose their native ControlKey bounds; revision-bound pixel drags
use the native alignment/manual-position mapping as one validated undo operation.
There is no Matplotlib renderer or independently persistent browser document.
The private document copy is an unsaved session; the saved VSZ remains authority.

The browser owns input drafts and request coalescing, not scientific decisions.
Commands bind a session revision and expected native setting values. Source,
project and delivery changes reject stale edits. Save derives the final changes
from native values, calls `preview_document_edit`, compares its native pixels with
the displayed frame, then calls `apply_document_edit`; client candidate bytes are
never trusted. Native undo survives Save, and undoing a saved change creates a new
unsaved difference. Export requires a saved document and delegates to the existing
export task. Reload replaces the unsaved session from current saved authority.
The combined publish command saves the active draft before calling that export
owner; an export failure retains the saved revision for export-only retry. Figure
selection follows registered IDs and requires saving or discarding the current
draft. Delivery entry resolution preserves explicit secondary-figure targets and
rejects separately modified visible copies before selecting canonical authority.
The launcher's explicit portable fallback opens an unbound/moved copy in Veusz;
it never creates a replacement managed binding. Opening old packages does not
rewrite them; a subsequent normal export adds the default canvas launcher.
Session reads detect a stopped native worker, retain the last frame and require
reload before further edits. A completed export receipt is accepted only when
fresh QA and delivery evidence both identify the current saved result.
The server binds only 127.0.0.1, validates Host/Origin and session proof, and serves
only packaged UI assets and the current identified native frame.

`task_repair` normalizes only the unambiguous misplaced `task_dir` transport alias,
rejects conflicting locations, and projects bounded field/constraint errors from
the shared schemas and explicit domain issues. Candidate IDs, selected-pair bounds
and profile conflicts retain their semantic correction constraints. Stale preview
replies carry the current image, audit and operation binding; MCP exposes that
image through its existing immutable resources. CLI and MCP response failures include the saved current
question and next step without a native query, state mutation or automatic retry.
An exact matching question binding returns only its reference and correction
constraints; absent/stale bindings return bounded evidence for a fresh decision.
Source bytes and scientific evidence are still rechecked on resume.
`task_error_feedback` bounds error narration while preserving full diagnostics in
the durable task record or a private local file for long pre-task errors. Small
errors require no diagnostic file. A diagnostic-write failure explicitly returns
the full original error instead of replacing it with a new exception.
`task_recovery_policy` classifies known failure codes by phase. Only a terminated,
unaccepted preview may receive one automatic timeout retry; `task_execution`
persists its lifetime budget before starting a new attempt directory. Creation,
apply and export failures do not receive this automatic retry. Unknown failures
request diagnostic inspection; valid operations are never rewritten to repair a
worker timeout. Existing transaction owners retain mutation recovery authority.
`task_output_choice` detects occupied output/workspace paths before planning. An
explicit current-question-bound `out` answer records a separate output selection
while retaining the original request. It reuses task/source/output overlap guards
and cannot change output after native creation starts. Existing uncertain-creation
and export-only recovery remain separate. No existing delivery is moved or adopted.
Task inspection projects current figure identities and sample-style targets from
its single existing project query; it never uses historical receipt revisions as
current edit targets or starts a native settings worker for that projection.
Task edits may defer export and return the saved document revision for successive
edits. Their completion scope is saved editing; a separate export owns readiness.
`task_editing` owns pure pending-batch replacement and no-change decisions.
Replacements retain the original request and a task-local intent history, reuse
the saved baseline and require current preview identity on later responses.
They never recover an uncertain apply by replacing it. A no-change shortcut is
limited to complete, native-normalized, audited pure style operations; export
intent and scientific validation remain with the existing task/native owners.
`annotation_schema.validate_operation_batch` uses the advertised JSON Schema
to reject malformed wire shapes before new task allocation, pending-intent
replacement or project preview I/O. The validator caches only immutable schema
validators, never document state. Historical task parsing stays compatible;
physical widths share the pure `style_values` grammar with native settings;
sample, scientific units and native-setting validation remain in their owners.
Failed, unaccepted previews may be corrected with the current task-local
preview_revision. Ready previews remain operation-ID-bound. These bindings are
exclusive, checked under the existing task lease and retain original baseline,
intent history and failure reasons; neither accepted nor uncertain applied work
can be replaced. Identical latest corrections keep the same receipt semantics.
`task_discovery` reads bounded existing creation receipts by exact original source
path. It uses the shared receipt validation and source fingerprint, reports
partial searches and ambiguity, and returns historical task/project references.
It adds no persistent project index, raw-path resolution to the edit APIs, or
implicit project creation/selection. Queries of selected projects remain separate.
Preview location validation reads request paths only, resolving relative sources
against the project. The document-edit owner retains complete before/after byte
inventories; directory allocation does not repeat that file-hashing pass.
`mcp_server` is an optional stdio adapter with shared schemas and per-connection
immutable result resources. Neither adapter reads chat state or starts a model.
`studio_core/control_results.py` owns the shared compact CLI/MCP projection;
domain services retain full evidence and CLI `--full`/MCP resources expose it.
`sample_style_presets` captures audited current ordinary sample line styles into
a standalone explicitly selected preference file. Application checks its byte
fingerprint and exact unique target labels, then expands it through sample styles
into the existing native transaction. Saved previews contain frozen native values,
not a mutable preset-file dependency. Source metadata is historical context, not
a global identity catalog or target scientific authority. No data, axes, layout
or semantic color encodings are transferred; source-revision style preservation
keeps its separate, stricter scientific-compatibility owner.

`task_group_contract` validates explicit independent experiment lists;
`task_group_storage` owns their hashed progress and cross-item path boundaries.
`task_groups` references existing task receipts, checkpoints follow-up requests
before execution and carries successful items past another item's question or
failure. Shared sample styles expand into ordinary per-figure edit tasks with
deferred export; the existing native transactions retain all scientific checks.
Create items may attach typed initial presentation operations. Native preparation
checkpoints before a normal edit preview and exports only after its bound
acceptance. This composes existing create/edit children; it adds no group-level
mutation authority or cross-plot transaction. Original-source preflight guards
both selected responses and automatic child continuation before native writes.
The overview projects the existing response templates, next steps and ordered
figure descriptors, so an unchanged receipt needs no repeated discovery.
`task_group_review` queries current project evidence and caches native PNGs by
project/figure/document/spec identity, then writes a read-only HTML gallery.
It contains no plotting implementation, browser editor, model provider or
aggregate publication certification. Candidate previews retain their distinct
scope and revision bindings; MCP exposes owner-returned PNG snapshots on demand.

`task_comparison_contract` validates explicit alternative operation batches for
one saved figure. `task_comparison_storage` binds their receipts and native
review identities to one full project/delivery baseline. `task_comparisons`
creates independent ordinary edit tasks with export disabled, freezes exactly
one caller selection before any write, and delegates application and optional
export to the existing task/transaction owners. Retries recover that same
selection; they cannot apply a second candidate. `task_comparison_review`
validates stored native images and presents the original, alternatives and
bounded factual differences without rendering during inspection. These are
historical comparison snapshots after selection, with current evidence reported
separately. There is no internal model, alternate renderer or browser editor.

`task_group_gallery`, `task_comparison_gallery` and `task_review_html` own only
the read-only HTML presentation of those query results. Packaged local CSS/JS
is embedded in each page for an offline thumbnail rail, zoomable/pannable native
preview canvas, collapsible evidence inspector, search, attention filtering,
gallery/side-by-side viewing and explicit text copying. The page never calls a write
endpoint. A copied choice carries the comparison directory, candidate and
revision identities and asks the caller to re-query before selection. Current
source/export/delivery indicators remain separate from task completion and
historical comparison images; missing evidence is displayed as unknown.
A saved-figure intent field is available only with a native project/document,
figure identity and document hash, an available preview and no known stale-source
or blocking state. It copies these bindings and mandatory re-query instructions
to the external AI; it never emits a native edit or acceptance payload. Unsaved
drafts are page-local. Candidates and unidentified figures have no intent field.
Tavotto-derived design tokens, their pinned source and full AGPL notice are
recorded in `third_party/tavotto-ui/`; the complete license is packaged and embedded
in each generated page's About dialog. No Tavotto renderer or document model is used.
Comparison queries project the current saved figure path/revision from their
existing inspection, without another native worker. The gallery adds no global
project index or scientific readiness gate.

`project_creation` shares source-bound preparation and exact-current publication
between CLI, tasks and MCP. Task creation checkpoints the prepared project before
export so an export failure can resume without re-preparing data. Profiles reuse
only verified rule/template selections; actual header/unit evidence and a fresh
source plan are required for each new input.
Managed primary-document export runs its scientific audit in the same native
worker as PDF/TIFF export. The existing private snapshots, current document/spec
hash checks and prepared-source derivation remain required. Publication rechecks
the returned audit against the live authority and its identical run snapshot;
evidence is passed only within that export call, never recovered from a prior
receipt. Secondary documents retain their existing exact-current audit path.

`data_mapping/column_choice` retains the original single-pair CSV/TSV route.
`data_mapping/table_choice` exposes original Excel worksheets and CSV/TSV rows,
binds explicit metadata/data ranges, and proposes shared-X or paired-XY source
views with original cell evidence. Empty interior columns never change indices.
`task_column_mapping` binds a question identity to that proposal and persists the
same path-bound confirmation before execution. The mapping owner composes selected
pairs into its verified effective table; that table and every selected output must
reproduce from the original cells. Each pair may select independent rows, worksheet
and metadata declarations. Disjoint vertical blocks are distinct views; overlapping
response rows cannot become different samples. Completed pairs are serialized as
empty XY cells in the rectangular composite, while individual mapped outputs retain
their exact lengths. Plan binding checks sample order and each selected point count.
It adds no profile reuse or numerical changes.
The mutually exclusive `column_mapping.replicates` branch binds independent
original value columns to the existing raw-only impact adapter. Its sheet,
metadata, explicit row domain and cell evidence use the same confirmation and
mapping transaction. Per-group outputs preserve every confirmed row and null
position; rectangular composite padding is only adapter storage. The replicate
proposal belongs to the existing `data_mapping/table_choice` owner;
`data_mapping/plan_binding` checks the renderer's finite membership, order and duplicates
against these source-verified domains. It does not infer X coordinates, compute
summaries or use finite observation counts to select rows. Existing XY proposal
and serialized-table meanings remain unchanged.
`task_initial_mapping` batches choices supplied in `create.mapping` or one
question-bound `resume.mapping`, bound to the original single-file SHA. It delegates table,
metadata and column validation to `task_column_mapping`; no alternate importer
or automatic scientific decision is introduced. Durable confirmations recover
interrupted batches, while invalid choices retain an ordinary correctable question.
Recovery checkpoints its pending answer and reuses an existing confirmation after
interruption. It never accepts a source-update or native-edit visual preview.
Existing ordinary source revision can expand an immutable raw-replicate binding
through this same question and mapping transaction. Raw mode comes from verified
old mapping and matching scientific render facts. Every old group must retain its
order, original source identity, cell/column references, full row domain, mask and
values; new groups follow them. Candidate preparation checks this before entering
the native owner, then retains the existing figure task, preview/revision ID,
style transfer, archive, atomic installation and export recovery. The bounded
expansion requires the same unchanged original file and an existing raw binding.
`data_mapping/curve_support` gates adapters that consume validated XY mappings.
Semantic attachment planning retains that adapter gate. Its original-table
evidence owner recognizes explicit quantity/sample/unit rows and closed
machine-header unit suffixes; sample metadata partitions adjacent column blocks
without interpreting them as acquisition stages. Exact coordinate selectors may
bind an otherwise unknown header to the caller's declared quantity, but cannot
replace a known quantity or viscosity component. `task_semantic_coordinates.py`
owns the common literal selector, frozen binding lookup and absent-source-unit
rules used by planning and lowering. A coordinate's `source_unit`
fills only an absent original unit and is replayed through the existing
source-bound user-statement metadata confirmation; its `unit` independently
selects an existing registered conversion. Explicit registered frequency policy
resolves measured or authorized derived coordinates into the common plan;
the one lowerer consumes these blocks through the same Managed typed graph and
preserves each original sample, point order and grid. An unresolved coordinate
returns a same-task intent revision, rather than advertising an incompatible
family's ordinary XY importer.
Optional coordinate `direction` projects directly into the existing generic
Scale direction with an ascending default. Its increasing numeric domain and
original row arrays remain unchanged; the Veusz audit verifies descending native
axis bounds independently from exact source datasets.
For a generic multi-sample table, `task_semantic_figure._source_views` projects
each retained literal sample block into the existing select-before-load stage
binding. Independent sample blocks never become cumulative acquisition stages.
Same-sample staged sources retain their existing binding identity and explicit
time-assembly path. A non-time sample table rejects an explicit stage request;
multi-sample secondary-coordinate or temperature-continuity assembly requires
one selected original block. Source selection, exclusions, sample identities,
per-sample grids, row order and raw values stay in the original plan and Managed
source graph; no replacement source table or new scientific transform is added.
`data_mapping/table_diagnostics` reports bounded numeric extents and holes; extents
are not selections. Automatic layout recovery requires one complete table with
explicit axis names, units, paired unique sample identities and finite data, and
passes through the same mapping transaction. Other cases return a short question.
`data_mapping/table_candidates` proposes bounded shared-X tables only with explicit
axis/unit evidence, complete finite rows, unique header sample identities, and one
unambiguous source-note quantity/unit declaration. The caller decides whether the
note applies and which pairs to select; `mapping_candidate_id` plus current question
identity expands the frozen mapping through the existing transaction. It is never
auto-applied. Unknown, stale or malformed candidate answers do not mutate the task.
Optional pair labels name the displayed curves; original sample/cell evidence is
retained. Same-workbook cross-sheet cell citations are byte-checked and replayed.
FTIR declarations retain response mode and units; percent transmittance is never
treated as absorbance or inferred from measurement magnitude.
`data_mapping/merged_metadata` reads original XLSX/XLSM merge declarations.
Explicit `expand_merged_metadata` selections may associate metadata above the
measurement region with its anchor; original blanks and anchor coordinates remain
separate evidence. Numeric labels in new confirmed mappings use optional
`sample_row_encoding=explicit_json_v1`: derived sample cells contain `@sample:`
followed by a JSON string, which the existing paired-table scanner decodes as
explicit identity. Historical mappings reproduce their original serialization;
unmarked numerical rows are never newly inferred as sample metadata.
`data_mapping/plan_binding` verifies the immutable execution and
request seed; the outer plan hashes the original input while the existing
scientific transform and FigurePlan describe the effective mapped input.
Creation, query and export verify both identities. Publication retains the
effective-source archive and a separate byte-verified original-input archive.
Mapping execution v2 fingerprints the explicit file for a single-source step,
so task/output files in its parent are not mistaken for source data; historical
v1 directory-bound executions retain their original verification rules. Reuse of
saved mapped projects resolves the same effective source before FigurePlan checks.

`task_table_region` serves bounded, source/question-bound original rectangles through
CLI and MCP without changing the task. `mapping_contract/table_metadata` owns the
closed declaration schema. `data_mapping/table_metadata` resolves column diagnostics
and separates original facts from cited external excerpts and attributed statements.
Invalid declarations return bounded, indexed errors together. Only equivalent
spellings of an explicitly cited unit can differ from its literal cell text;
quantity/sample evidence and original numeric values remain unchanged.
`task_column_mapping` replaces pending declarations with question-versioned history;
changing the selected region resets them. `DataMappingProposal.table_confirmation`
freezes the selection, pairs and evidence, and the mapping frame owner replays these
bindings against the original before confirmation, execution and export verification.
External citation relevance is judged by the caller; SciPlot verifies record shape,
source/cell identity and deterministic consistency, not the truth of an external claim.

`task_capabilities` projects a compact index and on-demand schemas from the existing
request, response and operation owners. A canonical fingerprint binds query versions.
`task_schema_compaction` factors repeated schema nodes into local definitions at each
standalone schema/tool root; it never weakens the server validators. `task_next_step`
projects existing scientific-question, preview and recovery states into guidance,
without performing recovery, accepting previews or replacing transaction archives.

`task_edit_context` composes runtime readiness, a single saved-project query and
only the requested edit operation schemas into a read-only entry for an external
AI. It supplies a current document-bound request template and existing target
records; it does not allocate a task, prepare data, accept a preview or export.
Managed annotations and sample targets come from the guarded spec snapshot;
generic native settings still require current native inspection. Unfinished
tasks retain their original continuation, and unknown project evidence remains
unknown. An already-read source.current=False rejects the edit context; sample/
preset preview uses the same guard after its existing query, including retries.
Direct generic native edits retain their prepared-source audit boundary and do
not gain an additional raw-source query. Preview receipts supply revision-bound response templates so callers
can continue without a second schema-discovery round.

`task_shortcuts` composes typed CLI intents with those same owners. `task create`
performs Doctor and constructs an ordinary create request; scientific questions
remain explicit. `task style` binds the current figure and exact sample labels,
constructs only existing color/width operations and returns the normal preview.
An explicit all-samples selection rejects empty or ambiguous inventories. CLI
resume flags construct existing acceptance/retry responses; acceptance requires
the caller's reviewed operation ID, never the latest ID inferred from storage.
`next_step.cli_argv` supplies argument arrays without shell interpolation. These
adapters add no renderer, mapping inference or automatic acceptance. For an
explicit style task key, the task owner checkpoints the exact original typed
intent before preview work. Replaying it returns the original task's current
evidence, without rebinding the intent to a new document SHA or expanding a new
all-samples inventory. Changed or unrecorded intent conflicts; it cannot authorize
the old preview. Whitespace in a valid physical size may be normalized, never its
value or unit.

`task_common_edits` parses closed presentation clauses, binds only represented
targets and composes the existing semantic patch or native task transaction.
An explicit first-call entry path freezes its original request for idempotent
replay. Pending work cannot be overwritten with a new intent; unknown or
unrepresented properties reject before mutation. CLI/MCP use this same owner.
`task_series_edits` binds exact display names, original scientific sample names
or stable IDs to the represented series. `studio_core/series_display.py` routes
Legacy display-name/membership changes through the existing native revision and
presentation persistence owners. Managed edits retain every layer, mapping and
dataset while updating presentation visibility, labels and corresponding guide
labels. These operations preserve the scientific hash and partial Legacy shadow
coverage; they do not acquire source or native-state adoption authority.

The same pure series selector now binds the width/color shortcut: exact stable
ID first, otherwise one unique current display, legend alias or scientific sample
label. Duplicate selectors for one target reject. All-series selection retains
document order and hidden members, and the compatibility checkpoint freezes
that resolved patch; old checkpoints replay their literal request unchanged.
The v1 shortcut retains advertised `style.line.*` properties. FigureSpec v2
ordinary measurement line/point layers lower to existing mark `style` patches,
merging only requested fields into each explicit mark override. Color updates
both line and point marks; width changes line marks and never infers a marker
outline or size. Theme/view/layer defaults and guide text/layout stay intact;
guide symbols derive from the resolved layer marks in the existing compiler.
`style_values` owns the existing physical-point conversion and v1 Managed color
resolution; risk validation and compilation reuse these pure values. RGB6/RGB12
v2 colors still use their existing grammar schema. The v1 0.1–10 pt review range
and v2 generic style presentation risk remain distinct existing contracts, not
a new shortcut policy. Scientific-role v1 colors and nonmeasurement/mixed-mark
v2 layers require their explicit edit contract. The shortcut adds no Undo state,
journal, renderer, native adoption or scientific writer; `PlotService` still
owns currentness, preview, commit/export, replay and rollback. This does not
resolve every historical compatibility entry-path/rebinding limitation.

Legend columns use existing schema/catalog bounds, and layout QA may block export.
Installed font validation uses the existing native process. The closed internal
`font-families` command accepts no paths or extra arguments and creates Qt only
on that process's main thread; an MCP background owner never initializes Qt.

`task_saved_work` and its evidence helper perform bounded explicit-folder
discovery using existing project/task/document identities. Source hashes filter
candidates; final native/semantic/source/delivery checks, including a final
search-source rehash, decide whether continuation arguments are current. Copies
remain separate, snapshots remain non-original, and no catalog or path rebinding
is introduced. Current editing authority does not imply ready delivery.

`task_papers` packages an ordered selection of registered project figures using
the existing native Save/audit ports and sealed publication files. Version guards and source closure bind
each selection. Native Save converts consumed linked inputs to portable copies;
it never patches VSZ text. Sealed staging supports exact partial retries and the
generic exclusive directory installer rejects all existing targets. Completed
start replay, inspect and resume share a read-only currentness projection;
historical frozen delivery stays distinct from present source/package validity.
`task_paper_selection` is a read-only group adapter: it freezes complete selected
children and registered figures through the strict paper request owner, without
rendering a gallery. `task_paper_publication` validates the existing publication
receipt and exact file inventory and copies its PDF/TIFF bytes; it cannot render
to repair a missing or changed publication. Native portable Save and scientific
audits remain required. The original publication must be finished and ready with
its canonical rule, QA and delivery gates satisfied; QA alone cannot establish
completion. Missing completion evidence fails closed without repairing the run.
`task_paper_status` projects current source/package
evidence; the new group start calls it after completion before offering delivery.
Explicit-request start retains its original completion/inspection boundary.

Radar interpretation is presentation of existing scientific values and declared
normalization. A reserved panel expands new page width without changing the
physical scientific frame or polar coordinates. Fixed-frame QA identifies the
native radar scaffold structurally (rings, spokes and hidden carrier axes);
Cartesian frames retain their contract. Explicit conflicting dimensions fail
before consumer defaults. A closed worker rejection envelope preserves that
domain reason through the public render adapter; unexpected crashes stay errors.

`source_tables/read_session` owns a bounded 32 MiB, operation-local parse cache.
Every hit rehashes actual source bytes; misses hash before and after parsing, and
callers receive independent frames. Explicitly byte/format/options-only parsers
may share parses across identical archive copies; path-dependent loaders retain
path identity. Numeric range facts (finite counts and invalid original rows) may
also be reused by byte identity, while scientific eligibility and metadata evidence
are recomputed. Nested task, creation, query and mapping
owners share one scope, which is discarded on exit. It reuses original cells,
workbook sheet names and deterministic missing-token cleanup of selected ranges,
not scientific decisions, validation results, source hashes or document state.
Normalized range reuse is bound to the same bytes as the freshly checked original
metadata cells; changed bytes between raw reading and normalization fail closed.
Generic paired scanners use one object-array view to avoid per-cell pandas index
allocation without changing row, locale, exclusion or sample rules.
`task_result_projection` is a pure CLI/MCP response projection. It removes duplicate
success inventories and healthy-check detail, retaining current edit identities,
readiness uncertainty, failed evidence, pending questions and all review audits.
Full responses are opt-in; neither task storage nor native state is compacted.
`task_timing` measures active local calls and phases under the existing task lease;
external model/transport/user time remains unknown. Completed start/resume calls
query fresh current project evidence before returning it, without persisting that
query as future readiness authority. A complete export with unresolved current
source/QA/delivery evidence lists those gaps instead of asking for the same
unchanged inspection; unknown/stale indicators remain unresolved. Question summaries omit redundant workbook
snapshots and bound initial previews; the complete hashed question stays on disk.

`task_source_execution` checkpoints source-update preview, application and export.
`task_source_update` persists all before/candidate PNGs and a review identity;
the existing source-update owner continues to prepare, audit and install the
candidate. Its durable operation records the reviewed baseline, installed target
and archive before replacement. Recovery accepts only a byte-proven completed
installation or an untouched baseline. Version-2 installation intents also bind
replacement part names and their complete old/new inventories. The
`source_update_recovery` owner classifies every part before mutation, restores a
byte-proven baseline, and preserves displaced candidate bytes plus a rollback
receipt. Recovery can itself resume after interruption. Unknown/tampered parts
and legacy mixed installations retain the archive and block. Retrying from the
restored baseline still rebuilds and compares the original reviewed candidate.
An export retry never reapplies the source revision. The task requires fresh
source-bound selection for all persisted mapping forms. The staging owner consumes
the confirmed plan through mapped project preparation and keeps original byte
snapshots through the existing Intake materializer.

`annotation_axes`, `annotation_contracts`, `annotation_geometry`, `annotation_batch`
and `peak_evidence` own pure annotation meaning, geometry and data-bound observed
extrema. `annotation_operations`/`peak_analysis` are saved-project services;
the native worker creates ordinary Veusz widgets. The existing edit transaction
replays and audits both VSZ and `spec.native_annotations`, archives both, and
rolls both back on failure. Annotation metadata is semantic/provenance evidence,
not a second visual document. `annotation_rebinding` classifies fixed annotations
and observed peaks by exact sample identity, coordinates, units and window.
`source_update_annotations` uses the existing audited native candidate editor,
first for provisional review markers and then for explicit decisions. Candidate
IDs bind complete numeric series, independently of temporary file paths. Final
source-update confirmation binds the decisions and all figure previews. Installing
the candidate refreshes only path-dependent peak provenance signatures after
checking unchanged sample values, source hashes and observed points.

`sample_style` exposes exact ordinary series labels and expands supported
color/width batches using current advertised native fields. The separate
`set_axis_range` operation in `annotation_axes` changes only a linear numeric X or Y
display window through the same native preview/apply transaction. It preserves
all series values and the original source-axis contract, records actual clipping
in `axis_data_visibility`, and requires explicit clipping authorization. Native
audits bind the displayed bounds; prepared-source signatures bind the preserved
source axis while rejecting changes to its labels, scales and other semantics.
Out-of-window annotations require an explicit same-batch move or removal.
Studio review retains generated clipping diagnostics and classifies them as
informational only for an ordinary axis with a validated, explicitly authorized
current display window. Other-axis, legend and scientific failures remain blocking;
neither the saved diagnostic evidence nor the native document is rewritten by QA.
The native setting catalog permits a boolean visibility edit for the canonical
Y axis of bound ordinary Cartesian curves. It changes only axis drawing; the
scientific label/unit, range, datasets and X-axis display remain bound. Scalar,
categorical and performance figures do not expose this presentation exception.
`document_edit_policy`
binds visible marker colors and generated direct-label colors to ordinary series;
sample colors expand to all those fields using each field's current value. Free
annotations and semantic legends remain outside sample color edits. Duplicate labels
remain ambiguous. The saved-project service binds both the document revision
and specification hash before passing expanded operations to the existing
transaction; workers do not interpret sample aliases or add another style policy.
Ordinary line transparency shares that catalog and policy, with integer bounds
and whole-batch visible-mark checks. A reviewed white-background color/opacity
edit can retain visual tone while avoiding Qt's dense transparent-stroke PDF
outlines. Export still uses the exact native document; no implicit color baking,
path simplification, raster replacement or separate PDF renderer is installed.

Inspected ordinary Legacy curves expose their existing native line-pattern
enumeration and represented display-name/membership operations. Inspected Legacy
keys expose column count and a positive physical sample length;
the existing native candidate worker measures the complete key before save and
rejects any out-of-page geometry. Unknown/opaque state remains unsupported.
These edits preserve native authority, scientific bindings and immutable house
defaults; a completed selected-artifact package does not imply recovery or
republishing of a copied managed project.

Candidate editing and candidate data audit share one native worker process.
The source-coverage audit owner still creates private document/spec snapshots
for its in-process runner; the host checks the returned audit's scope, current
file identities and closed unit inventory before verifying prepared sources.
Initial-document audit and apply-time native replay retain their own checks.
Returned audit evidence is internal worker output, never an accepted preview
field supplied by an external caller or a persisted cross-operation cache.

`distribution/macos` builds a relocatable runtime from the installed dependency
environment, audits bundled native dependencies and generates client connection
instructions. It is build tooling outside the core wheel, not another plotting UI.
`distribution/macos/identity.py` binds source snapshots and complete app trees,
including executable modes and internal symlink targets. `verification.py` retains
failed/unfinished checks, validates JSON outcome states and rechecks app identity
after local runtime/MCP checks. `release.py` verifies a relocated copy, checks the
extracted ZIP against that same identity, and records archive checksums. Its public
channel additionally requires actual Developer ID, stapled-ticket and Gatekeeper
checks; it does not sign, upload, or weaken host security. These are local technical
gates, separate from independent-user and clean-machine acceptance. The welcome
page emits a field-allowlisted feedback summary without source data, paths, logs
or credentials. It never sends that summary or modifies client configuration.

Veusz `MainWindow` remains a compatible native document tool. It owns its object
tree, property editor, Datasets, canvas, menus, Save and Undo/Redo. External
operations load the saved VSZ in a separate native worker and do not depend on
the live window or its selection.

`src/sciplot_gui/` attaches Project and optional selected-object AI docks to the
same Veusz `Document`; it does not own a second document model or renderer.

The retained browser `app` is a loopback-only confirmation adapter. It may collect
initial data choices and show results read-only, but it must not own
post-render visual editing.
The separate `edit` adapter owns live presentation and delegates all native edits,
save transactions and exports to the owners described above; it does not extend
the Intake state machine or put scientific mapping in the browser.

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
      automation_baseline*.py  closed R0 report, schema, validation, and probe evidence
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
        project_query*.py      saved project/figure identities and byte evidence
        document_edit*.py      reviewed native edit transaction and durable outcomes
        project_session.py     native/external process exclusion
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
  -> Core public facades
  -> GUI presentation installer (compatible interactive commands only)

external project commands
  -> saved-project query / native edit transaction / existing Studio export

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

External project queries resolve the existing request, figure-set registry and
canonical document paths without preparation or project mutation. Explicit
figure/object queries invoke native inspection in a subprocess; summary queries
do not load Qt. Objects are addressed by figure ID, native object path and the
saved document SHA-256. A live GUI changeset is neither a persisted version nor
a cross-session identity.

### Adapter ownership during module convergence

Scientific document validation and seals remain in `plot_document`/`plot_ir`.
`ProjectApplication` owns semantic transactions, currentness, preview/export and
rollback; its injected repository validates semantic revisions and journals. For
an attached figure, `AttachedProjectRepository` persists those facts through
`ProjectCommands` and the selected `FileProjectStore`. The Store owns immutable
complete generations and the sole durable project head; native/spec/manifest/
delivery files are checked materializations. Semantic revision, project generation
and native content identity have separate meanings. A standalone semantic
aggregate retains its existing repository owner and format. The
`PlotService` compatibility facade constructs concrete ports and routes separate
native-project aggregates; it contains no competing semantic state machine.
Prepared template adoption is an invocation-scoped read constraint in
`project_lifecycle/prepared_admission.py`. Every attached storage batch carries
its validated project reads, memberships and original source-tree witnesses into
the same Core publication, including early content/index writes. It does not
hold a project writer lease across native work or create another checkpoint
authority. Read-only native observation keeps the observed document fingerprint
separate from the prior canonical version required for a later audited adoption.
`studio_core/preparation_original_sources.py` owns preparation's selected-input
observation. Registered directories use their exact file namespace, with a
metadata census before content IO and the same finite membership on recheck.
`data_mapping/numeric_readset_proof.py` binds only one successful numerical replay
to its exact inputs; it neither authenticates an old namespace-directory digest
nor grants filesystem access. All preparation callers publish those admitted
source facts through the existing Core mutation.
`data_mapping/execution_candidate.py` checks the mutable mapping destination's
structure separately from immutable seed and numerical inputs. It reuses the
selected resolver's exact namespace admission. Current requests remain guarded
by ordinary publisher preimage/CAS checks; an imported historical execution does
not claim that its obsolete external destination is still physically present.
Provider-neutral capability admission owns AI command scope. GUI
changeset/native selection/Undo remains a separate identity domain. Adapters may
resolve intent into those contracts but cannot mint a competing state authority.

`openai_provider/transport_helpers.py` owns one request's response, connection and
cancellation monitor. SSE parsing stays in `sse_client.py`; I/O interruption does
not race response disposal. Secondary cleanup errors preserve an existing failure;
standalone cleanup errors surface through the redacted provider boundary.

`plot_engine/edit_entry.py` admits and leases style/common edit checkpoint paths.
A checkpoint retains the original literal request, not transaction stages. Replay
uses that binding before fresh target discovery; the lifecycle journal remains
execution authority. `project_lifecycle/checkpoint_storage.py` persists default
project entries as resources of the same Store, while explicit external entries
retain one literal request-file owner. Its entry lease retains the selected host
runtime through replay/cleanup when the original project is offline. Source,
export and revision directories cannot become user edit entries. Necessary old
checkpoint formats remain readable.

`studio_render/template_resolution.py` projects declared option values once.
Domain defaults and series-encoding provenance consume it; recorded effective
values and explicit declarations remain distinct. Axis heuristics consume semantic
axis fields, never paths or hashes. Presentation defaults preserve explicit label
layout and axis-mode choices; scientific metric labels and scale constraints keep
their existing owners. Exact-current native reopen/export does not infer defaults.

The [core migration contract](DESIGN_PROJECT_LIFECYCLE.md) defines the complete
semantic caller scope, authority/revision/command identities, failure isolation
and old-writer retirement. Desktop setting batches compensate failures against
the full live draft and quarantine unverifiable state before native output.
Panel saves use one directory-inode lease and descriptor-bound staging; process
death releases exclusion without deleting an unproven historical lock. These
bounded changes are distinct from the subsequent
[project-core migration](DESIGN_PROJECT_CORE_MIGRATION.md). That migration routes
NativeSuite, Studio/GUI/browser/MCP, publication and attached semantic writers into
one command/generation boundary, preserving their distinct scientific/native
authorities and old-history readers. Fixed refusal shells retire transferred old
semantic writers; preserving an immutable backup does not create another head.

`studio_core/project_command_scope.py` owns finite read witnesses and command
builders. The complete saved-native admission use case belongs to
`studio_core/native_adoption.py`, above those primitives and the observed-native
binding owner. Every native-save, edit, preparation, export and probe caller uses
that one use case; the lower scope does not retain or re-export the old mutation
function. Native audit, source/spec fences, CAS and generation publication still
use the sole ProjectCommands/FileProjectStore writer.

Builtin scientific execution selects an immutable per-operator implementation and
its actual numerical dependency closure. Historical descriptors resolve retained
implementations without rewriting old seals; an unrelated operator upgrade cannot
become a request to refresh old science. External interpreter/script identity is
separate from the host-owned action/source grant checked before every new launch.
Adopted results remain readable after revocation. Grants do not provide an OS
sandbox, hermetic external dependencies or cancellation of in-flight code.

The host source port separates original scientific locators/UUIDs/versions from
physical project locations. Incoming live versions, sealed baseline files and
explicitly imported complete-tree witnesses are finite request scopes; worker
bindings preserve them and reset between pooled calls. Same-name discovery,
partial directory contents and file hashes cannot stand in for a complete tree.
QA/native observations keep their actual inspected paths. Host artifact addresses
alone project back from private preparation to published locations.

Pure private render/export/QA computation is disposable and may finish before a
storage command is reserved; it changes no active/raw/delivery files. This is not
a general native exactly-once guarantee or an exception for external scientific
effects. Sealed candidates resume their exact original decision/result without
executing the effect again. External scientific resolution writes its uncertainty
journal before launch and refuses an unknown prior outcome. Package-level domain
dependency cleanup, global cost/owner optimization, outbound minimization and all
historical scientific-schema closure remain separate work and claims.

## Ownership table

| Concern | Owner | Boundary |
| --- | --- | --- |
| Low-level text, timestamp, hash, JSON and path primitives | `foundation/` | Leaf package; never imports ingestion, workflow, GUI, or rendering. |
| Automation state vocabulary | `automation_states.py` | One closed owner for ready, confirmation, and repair states. Project editing/export states remain separate. |
| External project command adapter | `cli/parsers/project.py`, `cli/dispatch/project.py`, `cli/dispatch/project_create.py` | Public create, capabilities, inspect, preview, edit-preview, edit-apply and operation commands call core services. Create validates a complete expected plan before allocating output, requires new visible/workspace paths and rechecks them under a workspace session lease, then invokes the ordinary Studio preparation/export lifecycle. Other commands address saved figures without preparation. No GUI selection, provider setup, alternative request model or renderer belongs here. |
| Saved project queries | `studio_core/project_query.py`, `project_query_paths.py`, `project_query_evidence.py` | Resolve the current managed request, registered figures and still-bound delivery without preparing or mutating the project. Existing explicit figure/object queries load native settings; edit contexts may request only guarded spec metadata when native fields are unnecessary. Saved document hashes bind targets; historical run records and current source/QA/delivery byte indicators remain separate, with readiness explicitly unevaluated. |
| Shared native editing capabilities | `native_settings.py`, `studio_core/document_edit_policy.py`, `veusz_worker/document_edit.py`, `veusz_worker/operations.py` | Read the existing setting catalog and native values, restrict external operations to the advertised scientific-safe subset, and check the entire batch before a native operation. Spec-aware policy excludes semantic curve-color encodings. The worker loads saved documents with unsafe commands/import recovery disabled, renders previews and saves candidates; it cannot install a managed project edit. |
| Reviewed document edits | `studio_core/document_edit.py`, `document_edit_state.py`, `document_edit_commit.py` | Stage the native candidate and science audit outside the project, then re-execute and compare the reviewed operations under existing project/session locks. Preserve before/after VSZ and bounded operation outcomes, install one selected document with rollback, and query an interrupted or already-applied result. Source/request/spec and visible-package state participate in stale detection. Export remains a separate shared Studio use case. |
| Native/external session exclusion | `studio_core/project_session.py`, native window integration | A writable native project window retains a shared process lease even when clean; an external commit requires an exclusive lease as well as the existing project lock. Open/Save As track the active project, close releases it, and process termination releases the OS lock. Read-only project queries do not acquire a nested project lock. |
| Expected scientific plan | `plan_preview.py`, `cli/dispatch/project_create.py`, `autoplot/run.py` | `project create` requires a complete successful expected plan and rechecks current source bytes plus the same rule/template before creating a canonical resumable Studio project. Compatible one-time Autoplot also accepts the preflight but retains its run-only layout; its project directory does not imply a canonical editable Studio state. The existing FigurePlan and scientific transform remain the authorities; this is not a new planning schema or durable task store. |
| R0 automation baseline evidence | `automation_baseline*.py`, hidden diagnostics CLI composition | Development-only schema, validation, metrics, and one linear black-box probe measure four existing owner paths under an explicit output root. The probe may count and compare existing payloads, hashes, calls, source opens, filesystem write opens, timings, and states; it cannot classify scientific facts, mint readiness, become a plotting route, persist a cache/receipt, or implement the proposed Brief/conductor/provider policy. |
| Autoplot persisted evidence | `autoplot/evidence.py` | Typed aggregate over reported result, persisted one-step state, and manifest; public JSON remains unchanged. |
| Autoplot user summary | `autoplot/summary.py` | One v2 result builder serves both the read-only projection of persisted evidence and a rule-repair preflight result. The normal projection reads publish integrity, delivery state, and the completed FigurePlan without reparsing or rehashing the plan; the preflight variant contains no invented run evidence and is never persisted. |
| AI-callable rule invocation | `materials_rules/models.py`, `materials_rules/catalog.py`, `readiness/rule_certification.py`, `readiness/registry_io.py`, `cli/dispatch/governance.py`, `cli/dispatch/diagnostics.py`, `cli/parsers/rendering.py`, `cli/dispatch/rendering.py`, `plan_preview.py`, `autoplot/run.py`, `autoplot/summary.py`, `workflow/__init__.py`, `workflow/one_step_entry.py` | `SemanticRule` owns the static additive `invocation` shape: existing plan/autoplot operations, required input and template, fixed rule identity, and source-controlled template choices. The CLI governance composition layer loads the validated-envelope registry once and injects the same current-certification projector into both `rules list/show`; the catalog remains readiness-free so contract hashing has no reverse dependency or data recursion. Explicit `plan` and `autoplot` call that projector before source parsing or project creation: current continues, while missing/stale returns the same repair reasons. Expected plan rule/template/source errors use the existing blocked v1 payload. A current Autoplot invocation checks source existence once before the runner. Public rule/template identifiers still enter the existing top-level request and explicit-template marker, so preview and render cannot select different task sets. Human omission permits existing automatic classification. This surface adds no second catalog, request envelope, readiness schema, receipt, cache, classifier pass, or source hash. |
| CLI machine failure envelope | `cli/parser_errors.py`, `cli/value_io.py`, `cli/entrypoint.py`, `task_error_feedback.py` | Exact argument names reject implicit abbreviations. An explicit `--json` parse failure returns one structured correction on stdout and exits 2; runtime failures use the same bounded presentation and exit 1. Human help and usage remain human-readable. Domain issues retain exact fields and constraints; long diagnostics stay local with a reference. This boundary does not infer scientific intent, retry work, or write projects. |
| Source-bound scientific transform | `source_tables/raw_readers.py`, `semantic_sources/table_scanning.py`, `semantic_sources/panalytical_scan_metadata.py`, `semantic_sources/scientific_transform.py`, `semantic_sources/rheology_interval.py`, `semantic_sources/stress_relaxation_sources.py`, `semantic_sources/stress_relaxation_transform.py`, `semantic_sources/dma_temperature_transform.py`, `semantic_sources/registered_paired_curve_transform.py`, `semantic_sources/registered_paired_curve_contract.py`, `semantic_sources/paired_curve_table_metadata.py`, `semantic_sources/gpc_sources.py`, `semantic_sources/gpc_transform_contract.py`, `semantic_sources/swelling_identity.py`, `semantic_sources/swelling_pair_run.py`, `semantic_sources/swelling_sources.py`, `semantic_sources/swelling_table_selection.py`, `semantic_sources/swelling_transform.py`, `semantic_sources/tga_transform.py` | Returns one typed resolved object containing exact transformed series, a declarative column/unit/anchor/coordinate/axis/output contract, and selected source paths. Stress-relaxation interval units are selected-column evidence between the interval header and first numeric row, never a fixed row offset or default; missing, conflicting, or conversion-requiring units fail before transformation, while truly non-interval wide sources retain their separate explicit compatibility path. The registered paired-curve owner derives aliases, canonical labels/units, metric IDs, table metadata, scale-driven domain projection, and closed row evidence from the existing `SemanticRule`; DSC, DTG, UV-Vis, XRD, and SAXS consume that rule-driven owner directly while TGA retains only a compatibility wrapper. Quote-aware ragged CSV reading and the table scanner recognize PANalytical Data Collector metadata plus its exact `[Scan points]` schema, bind the declared point count and raw detector-count evidence, and fail closed on count mismatch. For XRD only, those raw count values may be presented unchanged on the registered `Intensity (a.u.)` axis; this is an explicit display policy with no numeric scaling or normalization. GPC contributes only an Agilent/canonical RT-RI reader and contract leaf: source sample text, `min`/`mV` detector evidence, row order, retained/excluded counts, and selected workbooks remain source-derived, with no normalization or molecular-weight inference. Swelling contributes one structurally labeled table reader: each Time/ratio pair owns its first numeric run, one structurally empty formatting row may bridge that run, and later disconnected values remain excluded with closed evidence; explicit s/min/h units alone authorize conversion to hours. Preview and preparation must consume that same domain resolver; the payload belongs inside the existing semantic-preparation lineage and must not create another ledger, digest, or cache. |
| Scientific source transaction snapshot | `materials_rules/models.py`, domain `materials_rules/*_rules.py`, `semantic_sources/scientific_source.py`, `semantic_sources/scientific_source_models.py`, `semantic_sources/scientific_source_single_curve.py`, `semantic_sources/rheology_sweep_domain.py`, `semantic_sources/rheology_temperature_domain.py`, `workflow/scientific_source_resolution.py` | Each ready canonical rule may select one internal scientific-source adapter; stress relaxation, DMA temperature, registered DSC/TGA/DTG/UV-Vis/XRD/SAXS paired curves, GPC/SEC, swelling, rheology temperature, and directory rheology frequency are the first thin adapters and all other rules default to none. The shared resolver combines one rule/source identity, one typed domain, and the applicable already-resolved FigurePlan without raw rule-ID classification. `scientific_source_single_curve.py` is the only adapter-to-generic-plan binder for stress relaxation, paired tables, GPC, and swelling; preparation calls the same rule-owned transform dispatcher when no envelope was supplied. A domain may be a single-y `ResolvedScientificTransform` or the shared, non-serialized multi-metric `ResolvedRheologySweepDomain`; it must never be a dummy transform or generic object bag. Expected adapter failures use one internal `ScientificSourceResolutionError` while preserving the existing public reason/message; FigurePlan, preview, Studio, and Workflow do not rediscover the family. Broad `ValueError` fallbacks must not disguise snapshot invariants or programming errors as source failures. One Studio or Workflow transaction passes the typed envelope through planning, semantic materialization, named/direct/auto routing, and terminal adaptation. Pending/unadapted rules do not read the source through this seam. A family handler may parse only while creating the envelope; downstream orchestration may not reconstruct it from wire JSON or assign a plan hash to a transform after the fact. Domain variants and adapter IDs remain absent from public requests, previews, ledgers, rule payloads, and certification hashes. |
| Swelling source grammar | `semantic_sources/swelling_identity.py`, `semantic_sources/swelling_pair_run.py`, `semantic_sources/swelling_sources.py`, `semantic_sources/swelling_table_selection.py`, `semantic_sources/swelling_transform.py` | One selected file and one labeled table own exact condition/sample cells, strict Time/ratio units, a closed first-run row selection, and the existing scientific-transform projection. Only a structurally empty isolated row may bridge; disconnected content cannot influence numeric-locale evidence or re-enter the curve. No sample alias, table ranking, point/value threshold, source-specific row, or second schema is permitted. |
| Single-curve source snapshot binding | `semantic_sources/scientific_source_single_curve.py` | Fingerprint the source immediately before and after the one transform parse, reject drift before FigurePlan binding, and pass the same transform object plus matching hash into the generic task. This is the shared boundary for stress relaxation, paired tables, GPC, FTIR, and swelling; it is not a cache, receipt, or additional ledger. |
| Preparation source attestation | `preparation_source_attestation.py` | Owns the typed source/prepared-artifact snapshot and the one exact set of canonical rules that require it. Semantic preparation, Studio queue preparation, and private prepared-source admission consume `requires_preparation_source_attestation`; they may not copy that membership, add another capability registry, or introduce another hash/receipt layer. |
| Persisted scientific review | `scientific_review.py`, `scientific_review_ledger.py` | Purely projects the existing semantic-preparation contract into family-neutral human/AI items. Browser result review binds only to its run-local manifest; a prepared project and Studio bind only to canonical request evidence. Missing or failed ledger fields remain unknown/blocked, document-context changes clear the review, and no projector reads sources, invents anchors, or creates another receipt. |
| Read-only FigurePlan and transform preview | `plan_preview.py` | Builds one additive v1 planned/not-applicable/blocked payload from the existing semantic, Study Model, FigurePlan, and scientific-transform owners. `not_applicable` refers only to FigurePlan; a source-bound `scientific_transform` may still be present. Stress relaxation, DMA, registered DSC/TGA/DTG/UV-Vis/XRD/SAXS paired curves, GPC, and swelling each pass one typed source snapshot to both transform projection and FigurePlan resolution rather than reparsing or caching it. Rheology temperature and directory frequency pass one internal multi-metric sweep domain to FigurePlan and later preparation while correctly leaving `scientific_transform` null. The preview never renders, writes transformed data, creates a project, or runs completed-plan gates. |
| Scientific recognition, units, metrics | `materials_rules/`, `semantic.py`, `semantic_sources/` | Deterministic, fixture-backed, no GUI state. |
| Numeric separator evidence | `semantic_sources/numeric_separators.py`, `semantic_sources/rheology_sweep_sources.py`, `semantic_sources/swelling_sources.py` | Resolve decimal punctuation only from parser-selected scientific coordinate/response rows and columns. Any amount of explicit evidence is sufficient; disconnected blocks, point-count voting, unrelated-table scanning, and silent mixed/ambiguous locale guesses are forbidden. This leaf performs no unit conversion, source selection, caching, or schema projection. |
| Semantic preparation dispatch | `materials_rules/models.py`, domain `materials_rules/*_rules.py`, `semantic.py`, `semantic_sources/prepare_*.py` | Each canonical rule selects at most one internal `preparation_adapter`: rheology, curve-family, mechanical, or identity. The dispatcher invokes exactly one existing handler; a `None` result means identity and never probes another family, while handler exceptions propagate unchanged. Legacy family-only calls resolve one unique catalog rule by linear lookup, including `rheology_frequency`; no family map, callable registry, cache, or request field exists. The adapter remains outside public rule payloads and certification hashes. Source snapshot validation, the single attestation hash boundary, `SemanticPreparationContext`, transform-step construction, processed filenames, and post-handler attestation validation remain in the shared preparation owner. Registered paired-curve rules, including DSC, materialize the already-resolved transform through the same curve-family branch; no family-specific provenance or workbook gate runs downstream. Specialized source readers may enforce explicit scientific evidence but may not invent it: swelling accepts only explicit s/min/h time units from the header or adjacent unit row; uncurated torque preserves the full absolute-time curve and converts a vendor Index only when adjacent metadata declares a positive s/min/h sampling cadence; Impact requires an explicit compatible unit. |
| Terminal-source binding lifecycle | `terminal_source_binding.py`, `terminal_source_binding_wire.py`, `render/panel_render.py`, `render/target_paths.py`, `veusz_worker/operations.py` | One materialized binding owns raw, prepared, and terminal artifacts plus task, metric, order, point-count, and request context. The parent `seal()` performs the sole pre-worker inventory/request validation and captures the request hash; the render target owner validates and strips only its two private environment values for development instrumentation, while worker environment consumption performs the one cross-process current-state verification. Later Studio and series consumers verify structural order/count/artifact agreement without rehashing the same inventory. Archive, reopen, installation, and publication remain independent authority boundaries and are not elided by this same-transaction rule. |
| PDF raster artifact visibility | `qa/artifacts.py` | Invalid pixmaps and a zero-ink raster fail as blank. Any nonzero raster content remains valid evidence regardless of page-area-dependent ink fraction; continuous ink fraction and content bounds are reported for review, not used as an empirical scientific-output threshold. |
| Raw source parsing | `source_tables/` | Typed curve, replicate, and heatmap tables without rendering. |
| Table-source filesystem selection | `semantic_sources/table_source_files.py` | Owns supported table suffixes, deterministic recursive enumeration, workbook identity, and strict file-or-single-member-directory resolution. It never reads or ranks table contents; scanners and registered transforms consume it instead of copying directory-shape logic. |
| Tensile-export filesystem identity | `semantic_sources/tensile_export_identity.py` | Sole owner of the `.is_tens_exports` suffix, parent membership, source-derived sample name, and case-insensitive CSV membership. Classification, Intake, batch discovery, and the semantic compatibility facade reuse this leaf; it contains no scientific parsing or rendering policy. |
| Curated tensile workbook identity | `semantic_sources/tensile_workbooks.py` | A non-empty `DataStudio_Metadata.label` is the exact sample identity for the representative curve and specimen summaries; without it, the exact workbook stem is retained. Filenames never normalize, abbreviate, or outrank declared metadata. The resulting single identity flows through mechanical facts, ordering, FigurePlan, and task sources. |
| Generic source inspection | `source_inspection/` | Recommend only production-supported templates. |
| Mapping | `mapping_contract/`, `data_mapping/` | Closed contracts, explicit confirmation, immutable source evidence. |
| Changed-owner verification | `verification/changed.py`, `verification/owners.py` | Default selection unions staged, unstaged and untracked paths against a resolved HEAD; an explicit base also includes committed paths from that resolved commit. Rename/delete endpoints stay selected, including index/worktree cancellation. The current worktree executes at most one changed-file Ruff, one explicit-target focused pytest, the configured strict mypy when selected, and one tracked whitespace command. Whole-module/ancestor selectors subsume narrower selectors without losing their node union. Unknown paths fail closed with no broad fallback; an empty selection is NO_TESTS, not PASS. Dedicated typed-intent ownership does not remove the broad native owner for mixed/backend or future paths. Doctor is handoff, full smoke is final milestone, and rules/full pytest remain release gates. Verification does not edit or render user plots; optional evidence capture hashes local input bytes without acquiring document authority. |
| Local verification evidence | `verification/evidence.py`, `evidence_identity.py`, `durable_runner.py`, `pytest_finish.py` | Unsigned developer receipts bind exact command/scope/node IDs, actual content/environment/input closure and original completion artifacts. Capture checks before/after bytes, membership and aliases; unknown or changed closure, absent finish, skipped bodies and incomplete execution cannot mint reusable PASS. Reuse reads known local files and never executes receipt-supplied paths/commands. Detached supervision executes one command once and reports original execution after transport disconnect; it never retries or upgrades a declared fixture closure to private scientific acceptance. Requests and logs remain ignored/local, environment values are hashed, and no receipt is a scientific document, source ledger or publication authority. |
| Test input scope | `verification/input_scope.py`, `input_scope_manifest.json`, `public_input_guard.py`, `public_stage.py`, `public_control_boundary.py` | Exact reviewed public/private nodes partition the unchanged lifecycle tiers. Unknown, stale, duplicate or omitted nodes fail before bodies. Public comprehensive CI derives a source-only checkout with independent Git identity, excludes private namespaces in the copy only, and binds original/copied source, config and native runtime before/after. Only a source-bound generated-control caller can exercise the genuine missing-startup negative. Authorized local unfiltered full retains original private scientific assertions. The CPython/owned-process guard fails closed for unsupported bootstrap routes and does not claim a kernel sandbox. |
| Supported private access capture | `verification/private_observer.py`, `private_observer_pytest.py`, `private_process_boundaries.py`, `private_capture.py` | Opt-in source-bound bootstrap records synchronous chained process streams, actual spawn ownership, same-PID exec handoff, startup, observed roots, terminal and loss state. The strict consumer verifies raw topology and an external durable wait bound to the actual root PID, command, executable and source. Inner supervisor success cannot substitute for root exit; absent witness or root failure remains BLOCKED. Normal native EOF/recycle retains genuine terminal evidence; interruption, stream loss, root/source drift, unknown process ports or missing terminal remain BLOCKED. Finite source-compiled uname and owned Bash/Python handoffs have exact command/runtime/environment boundaries. Historical or self-asserted completion cannot certify closure; capture never rewrites raw inputs or scientific acceptance. |
| Private process exclusion | `verification/process_private_exclusion.py`, `process_private_launch.py`, `private_exclusion_boundary.py` | The existing observer may fence one source-owned launch only after binding the real primary collection and setup/call/teardown context. File namespaces and evidence writes are denied by the actual OS boundary; caller invocation and final post-loader invocation are separate facts. Same-launch composition unions protected paths and intersects finite socket permissions. A matching test name or a nested observer is insufficient. Descriptor-only controls do not establish native capability, and an already-fenced descendant cannot assume a second sandbox can be installed. |
| Audit-local engine lifetime | `verification/private_audit_runtime.py`, `private_native_exit_port.py`, `native_exit_boundary.py` | Reuse the existing engine socket, actual Popen object and one primary kqueue sensor. Retain original bind identity and source-owned successful listen after chmod; compare the complete settled endpoint identity on connect. A fenced nested actor needs the actual live held parent generation, kernel peer PID, matching compiled caller and successfully written current request frame before kernel registration. That internal call does not replay its primary stream; queued declarations retain historical admission. Final acceptance still requires the complete source exclusion, chain, registration and genuine kernel exit; an UNKNOWN registration event cannot replace these facts. Owner JSON alone proves none of these. Explicit fixture actors remain observed without acquiring default lifecycle management; their unique actual exit, including an intentional signal, stays distinct from a normal default-actor close. Teardown may stop only its registered managed actor; the existing observed-epoch orphan path additionally needs original producer finish and ancestor wait. Missing registration, lineage, socket identity or exit blocks closure. This opt-in audit mechanism grants no scientific authority. |
| Socket observation facts | `verification/private_socket_ports.py`, `private_audit_runtime.py` | A successful connect remains successful when later peer inspection fails; missing endpoint or peer facts are recorded and reviewed, never invented. Only explicit ENOTCONN may attribute a closed endpoint within the existing sealed actor contract: unchanged complete endpoint/owner, one real item and launch generation, independent kernel-peer readiness and validated actual exit. The peer for that call remains unknown. Raw registrations also reject unclosed or UNKNOWN competing generations; known wrong peers cannot fall back to owner JSON. Other missing facts remain BLOCKED. Observation timestamps do not claim an exact kernel exit instant, and this is no authorization for arbitrary socket or descriptor handoffs. |
| Scoped static typing | `[tool.mypy]` in `pyproject.toml` | The exact strict Python diagnostic scope, its file and directory entries, and all strictness options belong only to `[tool.mypy]`. Changed owners project that executable scope into local verification without maintaining another scope list or file count. Imported modules outside the configured entries provide type information but are not part of the diagnostic claim. |
| Intake project manifest | `project_manifest.py` | `intake_manifest.json` is canonical; compatibility `*.sciplot.json` mirrors, read-modify-write updates, and ZIP snapshots share one rollback-capable cross-process project lock. |
| Intake rule projection | `intake/catalog.py`, `intake/session.py`, `intake/project/project_builder.py`, `intake/intake_static/index.html` | The source-controlled Intake catalog owns navigation metadata only: grouping, labels, icons, one unique canonical rule id, and unknown entries. Public template choices, render defaults, and replicate recommendations project from the existing `SemanticRule`; internal project construction obtains rule render options through its existing semantic-recognition path exactly once rather than treating them as browser edits. The browser sends no invisible replicate default. Omission uses the rule recommendation, explicit valid API values survive, and invalid values fail before persistence. Intake does not own a second capability catalog, template alias, renderer, request field, or family default. |
| Raw-source Studio composition | `studio_core/studio_prepare.py` | Pass final source options into Intake, inject and capture exactly one generated preparation, then terminate source dispatch. `intake/project/` separately owns raw copies, the canonical request and in-memory manifest draft, blocked failure projection, and initial ZIP. |
| Workflow route intent | `workflow/route_intent.py`, `workflow/request_rendering.py`, `workflow/legacy_route_rendering.py` | Resolve strict optional recipe/template fields once after confirmed mapping/cleanup and before semantic or presentation enrichment. Scientific auto, named-recipe, and direct requests all enter shared semantic materialization with the transaction snapshot. Only requests without a scientific snapshot or selected source-bound plan may enter the injected legacy recipe/direct leaf. Readiness keeps only a lazy compatibility projection. |
| Workflow effective semantic presentation | `request_contract.py`, `workflow/scientific_source_resolution.py`, `workflow/request_run.py` | Project only rule-owned, request-editable render defaults into the canonical request after scientific-source/FigurePlan resolution. Semantic defaults override generic Autoplot defaults; keys named by the existing explicit-render-option marker may override them again. Registered single-curve axis labels come from the same rule axis plan. Renderer-only style metadata never leaks into the public request, and no second template, option schema, or family dispatch is introduced. |
| Workflow render-family dispatch | `materials_rules/models.py`, domain `materials_rules/*_rules.py`, `workflow/auto_split.py` | Each canonical `SemanticRule` owns one internal `render_adapter`, defaulting to generic; specialized rules opt into performance, impact, mechanical, DMA temperature, or rheology without a parallel rule map. DSC uses the default generic adapter. Workflow validates the canonical rule once, reads that field, and calls exactly one adapter. Without a selected plan, one specialized adapter may decline only to the generic renderer; with a selected plan, adapter decline fails closed. Render-adapter choice does not select FigurePlan capability, and Workflow never probes another family. |
| Workflow typed FigurePlan spine | `workflow/request_run.py`, `workflow/request_rendering.py`, `workflow/auto_split.py`, selected `workflow/*_bundle.py` and task-source leaves | `request_run` resolves one immutable FigurePlan, persists its wire projection, and passes the same typed object through request rendering, family dispatch, the selected bundle, and task-source materialization. Downstream owners never reparse that persisted payload when the typed object is present; a compatibility caller without it may parse once at the highest missing-object boundary. Rule, source, attestation, ordered-task, terminal seal/consume, installation, reopen, publication, and delivery checks remain independent lifecycle boundaries rather than in-process reparsing. |
| Figure-task metric identity | `figure_plan/metric_binding.py`, `figure_plan/task.py` | Preserve the closed v1 Cartesian wire contract and add explicit v2 `cartesian_xy` or `ordered_metrics` bindings without fake axes. Child-task version is independent from the enclosing v1 plan. |
| Selected figure execution | `materials_rules/models.py`, domain `materials_rules/*_rules.py`, `figure_plan/` | Each applicable canonical rule selects one internal `figure_plan_adapter`; `resolve_figure_plan` reads it lazily and invokes exactly one leaf instead of classifying raw rule IDs. The internal adapter is excluded from public rule payloads and certification hashes. `REQUIRED_FIGURE_PLAN_RULE_IDS` owns the exact current membership that must persist a source-bound plan and use task-aware figure-set publication; the compatibility `SUPPORTED_...` name aliases that same object. A focused contract keeps adapter membership equal to the required set without turning either into a second resolver registry. Unadapted and unknown rules return before source-tree hashing. FigurePlan owns stable ordered tasks, plan identity, per-task outcomes, stale-state rejection, and publish/delivery gates; heavy family resolution remains lazy so startup cannot create a materials-rule initialization cycle. Render adapters execute tasks but do not select them. |
| Registered generic single-curve plan | `source_tables/raw_readers.py`, `semantic_sources/table_scanning.py`, `semantic_sources/panalytical_scan_metadata.py`, `semantic_sources/registered_paired_curve_transform.py`, `semantic_sources/registered_paired_curve_contract.py`, `semantic_sources/paired_curve_table_metadata.py`, `semantic_sources/table_source_files.py`, `semantic_sources/gpc_sources.py`, `semantic_sources/gpc_transform_contract.py`, `semantic_sources/ftir_sources.py`, `semantic_sources/ftir_transform_contract.py`, `semantic_sources/swelling_identity.py`, `semantic_sources/swelling_pair_run.py`, `semantic_sources/swelling_sources.py`, `semantic_sources/swelling_table_selection.py`, `semantic_sources/swelling_transform.py`, `semantic_sources/scientific_source_single_curve.py`, `semantic_sources/tga_transform.py`, `figure_plan/single_curve_resolution.py`, `semantic_sources/prepare_curve_families.py`, `workflow/auto_split.py`, `workflow/single_task_bundle.py`, `studio_core/figure_task_evidence.py` | Rule-owned source adapters return the existing scientific-transform object; the generic plan adapter projects output metric IDs, dynamic source-bound axis labels, and source-derived series order into exactly one v2 Cartesian task. DSC, TGA, DTG, UV-Vis, XRD, and SAXS exercise the paired-table owner across signed responses, independent and descending coordinates, independent x grids, header-embedded units, preceding sample rows, a PANalytical metadata-plus-scan block, and a positive log-y presentation domain. DSC's adjacent digitization provenance records only the registered fixture's evidence; ordinary CSV/XLSX inputs do not require a DOI, publication record, or adjacent provenance. A workbook with more than one matching worksheet fails closed as ambiguous. GPC proves the same downstream owner with multiple Agilent workbooks whose analysed Slice Table supplies source-derived sample identity and the explicit instrument-calibrated `Mw (g/mol)`, `LogM`, and `dW/dLogM` columns; values and source order are preserved while the registered x axis is displayed logarithmically. FTIR uses one read per actual file: structured headers alone distinguish Transmittance from Absorbance, while headerless response remains neutral and keeps every finite point, zero, coordinate, and source row order. Swelling requires one matching labeled table, explicit time-unit evidence, source-derived condition/replicate identity, and one closed first-run selection per pair before joining this same plan. Units must be explicit and identity-equivalent except for declared conversions such as swelling s/min to h, FTIR's selected rule owning the wavenumber axis when a headerless source does not declare it, and XRD raw counts presented unchanged as `Intensity (a.u.)`; every authority is recorded without an undeclared numeric transformation. No empirical `%T` cleanup, fixed input domain, anchor, normalization, silent numeric conversion, sorting, interpolation, source-specific sample/value/point/peak/onset constant, DTG derivation, XRD phase assignment, SAXS structural assignment, GPC calibration inference from RT/RI, or undeclared numeric log transform is permitted. Preparation materializes the same snapshot once, then Workflow and Studio reuse the generic single-task Veusz, QA, figure-set, exact-current, and delivery owners. |
| DMA temperature single-task plan | `dma_temperature_contract.py`, `figure_plan/dma_temperature_resolution.py`, `semantic_sources/dma_sources.py`, `semantic_sources/dma_temperature_transform.py`, `studio_core/source_bound_prepare.py`, `workflow/dma_temperature_plan.py`, `workflow/dma_temperature_bundle.py` | Own one independent temperature/storage-modulus task, explicit source-to-Pa-to-MPa conversion, complete source-derived sample/point evidence, typed semantic-preparation attestation, and a sealed terminal table. Plan preview and FigurePlan resolution share one typed source snapshot; execution accepts the full scientific-source envelope and verifies its source/plan identity without backfilling a hash. Tan-delta evidence cannot select it. Studio and Workflow consume the same one-task plan without entering the rheology-temperature two-task resolver. |
| Mechanical curve and descriptive-summary plans | `mechanical_figure_contract.py`, `semantic_sources/mechanical_facts.py`, `figure_plan/mechanical_resolution.py`, `mechanical_task_sources.py`, `workflow/mechanical_bundle.py`, `workflow/mechanical_terminal_validation.py`, `studio_core/source_bound_prepare.py`, `studio_core/mechanical_task_source_lifecycle.py` | Own the complete ordered tensile, compression, and flexural plans. One immutable source-facts projection binds raw specimen values, explicit repeat grouping, representative or individual curve selection, source hashes, units, sample order, and replicate counts. Curve tasks retain measured curves; every summary task uses the shared `box_strip` median/IQR/raw-point contract. Studio renders the primary and all children from task-owned terminal tables inside one rollback boundary; exact-current reopen validates and preserves the registered set without rematerializing it. Workflow independently installs the same exact task set transactionally. Terminal evidence closes request, source, values, statistics, palette, and actual encoding. Child templates do not become new public rule presentations. |
| DMA named-recipe plan seam | `workflow/dma_named_recipe.py`, `workflow/request_rendering.py`, `workflow/dma_execution_evidence.py` | Admit only `rheology_dma` paired with the exact selected `dma_temperature_sweep` plan. Preflight rejects recipe, rule, task, source, sample, metric, unit, encoding-claim, or clipping-bound conflicts before semantic preparation. Auto and recipe then share preparation and task execution while preserving distinct route identity; a route-neutral evidence digest covers terminal data, units, encodings, and axis visibility. Other named recipes remain fail-closed with selected plans. |
| Workflow task-artifact installation | `workflow/task_artifacts.py`, `workflow/single_task_bundle.py` | Install task-owned editable worker trees and remap QA evidence for selected-task bundles. Performance and mechanical plans have transactional multi-task loops; DMA and generic planned single-curve rules, including DSC and swelling, share the single-task lifecycle. A private prepared-source marker prevents the terminal worker from repeating semantic preparation without inventing a new source-attestation contract. These owners never select figures, templates, metrics, or scientific identities. |
| Terminal FigureTask evidence | `terminal_request.py`, `figure_plan/terminal_binding.py`, `workflow/request_rendering.py` | Preserve the exact unversioned legacy request when no task is selected. Task-aware terminal requests use a closed v2 envelope containing the exact v1/v2 task and only its metric binding. Workflow parses the selected plan before rendering, then binds ordered unique terminal tasks before reports or publication; the binding leaf is not a FigurePlan-facade export. |
| Studio FigureTask evidence | `studio_figure_set_contract.py`, `studio_core/figure_task_evidence.py`, `studio_core/figure_set_registry.py`, `studio_core/figure_set_snapshot.py`, `studio_core/figure_set_storage.py` | Project exact tasks into queue, registry, and spec evidence once. Cartesian tasks alone expose compatibility x/y; ordered tasks expose only ordered metrics. Legacy registry v1 stays readable without task authority, while task-aware registry v2 binds the exact ordered plan, canonical task-owned paths, specs, and editable outcomes before the first replacement. Exact-current reuse validates and relocates one registry snapshot, then reuses that same snapshot for presentation evidence, artifact completeness, and generated-document identity. |
| Studio FigureTask execution support | `studio_core/figure_requests.py`, `studio_core/impact_task_sources.py`, `studio_core/figure_source_request.py`, `studio_core/figure_registry_geometry.py`, `studio_core/mechanical_task_source_lifecycle.py` | Bind each already-selected task to its exact rheology, Impact, or private mechanical render request; read actual registry geometry; and keep materialized Impact and mechanical task sources inside the existing Studio rollback boundary. Impact execution reads one source snapshot, rebuilds the complete current plan from that same payload, then writes only into a versioned transaction-owned directory beneath ordinary non-symlink project ancestors; point-line rendering uses a verified private workbook copy rather than rereading mutable raw input. Dynamic request and queue values are narrowed once before typed owners consume them, and responsibility modules are imported directly. These helpers do not independently select a FigurePlan, invent a task or source, create a second request schema, or acquire publication authority. Malformed task, queue, source, or geometry evidence remains fail closed or follows the explicit bounded legacy geometry fallback. |
| Studio FigureTask publication | `studio_core/request_paths.py`, `studio_core/figure_set_publication_scope.py`, `studio_core/publish_inventory.py`, `studio_core/publish_run.py`, `studio_core/publish_finalize.py` | Bind publication to the canonical project request and primary VSZ, then required-plan publication strictly loads and normalizes one figure-set registry snapshot before any secondary export or run allocation. Canonical registry members must remain ordinary in-project paths rather than symlinks, and the dedicated scope leaf validates the complete expected figure set. The same in-memory snapshot drives presentation evidence, secondary-document collection, and primary generated-document identity; primary and spec hashes are checked again after secondary collection and before run allocation. Inventory carries that normalized registry plus verified spec hashes through the run coordinator; finalization writes the exact registry into the run-local Studio receipt and rejects spec drift before accepting the snapshot. Missing or tampered ready documents, specs, or hash projections fail closed. Planless and legacy publication retain compatibility behavior without acquiring task authority. |
| Native series revision and presentation persistence | `studio_core/veusz_series_revision.py`, `studio_core/series_presentation.py`, `studio_core/series_revision_persistence.py`, `sciplot_gui/studio_project/series_revision.py` | Revise source-authorized membership and order inside the live Veusz `Document` as one native Undo step. Persist only the presentation selection while retaining the complete source-bound spec, values, and encodings; derive the visible view only for exact-current document audit. Managed saves commit every ready VSZ, spec, the canonical request, and registry in one existing figure-set transaction. |
| Visible document recovery | `studio_core/delivery_recovery.py`, `delivery_recovery_state.py` | Preview one still-bound primary delivery using last-good baseline, canonical and candidate identities plus current scientific source evidence. Apply recomputes the preview under the project lock, privately archives the previous canonical bytes and installs the candidate with rollback. It does not auto-export or merge a two-sided divergence. |
| Source revision | `studio_core/source_update.py`, `source_update_staging.py`, `source_update_review.py`, `source_update_commit.py` | Use ordinary Intake and Studio preparation in an isolated sibling candidate. Review figure, sample, replicate and numerical changes; apply rebuilds and compares the exact logical preview. Recheck source/delivery/project identity before transactionally installing active source, VSZ/spec and metadata, preserving runs and archiving old active files. Metadata relocation never rewrites raw/source data bytes. Corrupt or incomplete registered figure sets cannot fall back to a single primary. |
| Native compatible style transfer | `veusz_worker/style_transfer.py` | Pair unique sample and task identities through the native API. Allowlist fonts, strokes, ordinary series colors and compatible manual legend layout, excluding data bindings, hiding, scientific labels, bounds and semantic color encodings. Audit the candidate against its new specification before native atomic save. Report skipped styles explicitly. |
| Revision presentation | `cli/dispatch/project_revision.py`, `sciplot_gui/studio_project/project_changes.py`, `change_dialogs.py`, `change_worker.py` | CLI and native Project dock call the same preview/apply services. GUI performs core work off the UI thread and reloads native Documents on the UI thread; it blocks unresolved local edits and concurrent project windows. These adapters do not derive science or edit VSZ text. |
| Selected presentation identity | `presentation_identity.py`, `studio_core/presentation_evidence.py` | Resolve one closed versioned `rule_id`/template value from the canonical request plus the already-resolved current rule. It binds only the plan's declared primary task and primary spec; each secondary spec verifies its own task template without minting another identity. Exact-current VSZ stays hash-bound visual authority; recognition never selects presentation. |
| Global visual contract | `policy/plot_contract.json`, `policy/`, `style_contract/` | Single hard-style and option authority. |
| Request validation | `request_contract.py` | Reject unsupported templates/options before rendering and expose the single projection of rule-owned editable defaults onto the existing request surface. Internal renderer policy remains outside the request contract. |
| Ordinary XY series encoding | `studio_render/series_option_context.py`, `studio_render/series_options.py`, `studio_core/series_encoding_contract.py`, `studio_core/veusz_primitives.py`, `veusz_worker/spec_audit/series_encoding.py` | Resolve request provenance, palette, final-series order, per-series overrides, line style, marker, fill, and provenance once. Persist a closed versioned encoding per series; the writer consumes it without re-resolution, and exact-current audit enforces only fields owned by explicit/direct request intent. Performance scatter/radar and scalar fields retain separate semantic contracts. |
| Ordinary XY axis-data visibility | `studio_core/axis_data_visibility.py`, `veusz_worker/spec_audit/series.py` | Recompute finite data extents against both configured render-option bounds and final effective axes. Persist potential below/above-bound counts separately from coordinates actually clipped by the final spec; reject stale or forged visibility evidence during exact-current audit. |
| Pure plot construction | `studio_render/` | Convert confirmed data and policy into render specs. |
| Veusz lifecycle | `studio_core/`, `studio.py`, `studio_core/lifecycle_contract.py` | Core owns implementation; `studio.py` exposes the stable GUI/CLI integration API. Doctor validates the named public owner call contracts and source evidence without relying on private facade aliases or loading native owners; static availability explicitly leaves runtime_verified=false. Native execution and artifacts have separate smoke/scientific evidence. |
| Native numeric persistence | `studio_core/veusz_numeric_persistence.py`, `veusz_data_import.py`, `veusz_save.py`, `performance_veusz/apply.py`, `veusz_worker/numeric_evidence.py` | New ordinary/performance specs declare `native_1d_numeric_encoding=float64_round_trip_v1`. Import and native Save retain binary64 curve values with 17 significant digits; strict reopened-data audit rejects precision loss. The runtime adapter changes the native writer's numeric format only, without modifying upstream source or patching VSZ text. Historical specs retain their earlier quantized comparison; two-dimensional persistence keeps its existing contract. |

| Rule contract certification | `readiness/rule_contract.py`, `readiness/rule_certification.py` | Build the canonical rule payload once, derive full/semantic hashes, and compare one already-resolved rule with exactly one validated-envelope registry entry. No Studio policy or I/O belongs here. |
| Validated-envelope registry and scoped acceptance lineage | `readiness/constants.py`, `readiness/registry_model.py`, `readiness/registry_build.py`, `readiness/registry_merge.py`, `readiness/registry_io.py`, `readiness/status.py`, `cli/parsers/diagnostics.py`, `cli/dispatch/diagnostics.py` | Legacy registry v1 remains readable; complete certification and scoped merges write registry v2. `certify` builds from one complete ready-rule acceptance summary. `merge` replaces only selected entries after the same strict row, manifest, contract, evidence, artifact, and manual-visual validation, while every unselected base entry must still match its current full and semantic rule contracts. Versioned lineage records form a non-overlapping complete partition of registry entries and retain each real summary identity and selected rule set; status projects that same lineage. A candidate uses the existing registry schema and never reruns unselected lifecycles, invents hashes, or creates another authority. |
| Studio prepare-time rule binding | `studio_core/rule_contract_binding.py` | Own the closed versioned binding persisted in canonical `plot_request.json`. Only successful generated preparation mints or refreshes it; exact-current reuse preserves it. |
| Studio publication rule readiness | `studio_core/rule_readiness.py` | Leaf owner combines canonical request identity, strict persisted review evidence, exactly one current catalog lookup, current certification, and prepare-time binding into one immutable publication snapshot. Inventory, semantics, finalization, registry, and native status project that snapshot; they do not resolve competing rule identities. |
| Managed rule-readiness display evidence | `sciplot_gui/studio_project_status/rule_readiness_evidence.py` | Strictly parses untrusted v1/v2 managed receipts before native status may display a specific rule or contract repair reason. Standalone and secondary receipts remain isolated. |
| Material performance data | `performance_comparison/` | Validate tidy values and declared bounds; never infer missing science. |
| Material performance objects | `performance_veusz/` | Native editable scatter/radar objects and index geometry. |
| Native compatibility status | `sciplot_gui/studio_project_status/` | Pure evidence-to-state logic for the retained live native window; external saved-project queries do not import this GUI package or claim knowledge of unsaved state. |
| Retained selected-object AI | setting catalogue, `assistant_provider/capabilities.py`, assistant operations, GUI bridge | The request owns its advertised selected-object catalog. `bind_setting_targets` admits the whole draft before provider no-op filtering; `bind_setting_batch` binds typed commands to that catalog, revision and expected values. Response validation and GUI preparation share this pure owner. Providers own transport/JSON coercion; the GUI rechecks live selection, revision and native normalization before one Undo operation. Its live-selection restriction remains local to that adapter, not the explicit saved-object external API. |
| QA and delivery | `qa/`, `readiness/`, `delivery/`, evidence packages | Inspect and package artifacts without changing content. |
| Current managed export | `studio_core/project_export.py` | CLI, Intake, and Qt share one export-and-publish use case. It consumes the saved canonical document once and returns an immutable JSON snapshot with independent projections; Intake does not rerun Workflow after Studio preparation. |
| Managed scientific audit | `source_coverage/managed_documents.py`, `veusz_worker/spec_audit/` | Every managed publication compares all current documents against source-derived scientific expectations before QA and delivery. Strict generated audits additionally enforce generated styling; current-document audits permit ordinary styling changes while retaining data, bindings, units, identities, and visible scientific geometry. |
| Delivery replacement and continuation | `delivery/package_transaction.py`, `launchers/delivery_binding.py`, `studio_core/delivery_target.py`, CLI interface composition | Stage and validate candidates before replacing visible managed artifacts, retain backups through verification, and roll back ordinary failures. Launcher comments bind the original delivery location, canonical project, and VSZ baselines. Relocated copies resolve as portable documents; unmerged visible changes stop replacement. This is not a crash-atomic filesystem transaction. |
| Explicit worksheet confirmation | `intake/table_preview.py`, `semantic_sources/table_selection.py`, paired-curve source readers | The preview retains original row/column indices. Explicit sheet selection is bound to current workbook bytes and consumed only by the registered paired-curve adapter. Preview-only metadata never silently narrows source coverage. Browser-local import settings contain configuration and must be checked against each current source. |
| Runtime gates | `smoke/`, `acceptance/`, probes | Evidence only; never production rendering routes. |
| Upstream Veusz | `third_party/veusz/` | Preserve upstream identity; SciPlot integration stays outside. |

Accepted decimal text for paired curves and numeric mapping operations shares
`source_tables/parsing.py:coerce_numeric_series`. It owns numeric text recognition,
missing-value validation and integer dtypes while correctly rounding
accepted floating text to binary64 before the native persistence boundary.
Raw cell strings, curve order, independent lengths and scientific transforms
remain separate authorities; this parser performs no normalization or conversion.
The terminal Studio table reader retains original object cells until that same
numeric coercion, so its independent source reread cannot truncate the values
before the existing native round-trip writer and audit.

New ordinary specifications declare the source parser separately as
`source_numeric_encoding=decimal_float64_round_trip_v2`. This encoding coerces
embedded NUL text to missing rather than discarding its suffix, and rounds all
accepted ASCII decimal spellings exactly. Delimited raw reads preserve object
cells through the Python parser so a tokenizer cannot discard a NUL suffix first;
Excel retains numeric text and native numeric cells separately. Sealed v1 keeps
its original source-kind pipeline and correctly rounded ordinary valid decimals.
Only its historically ambient stacked-component coercion and nonstandard-text
fallback may reconstruct the known fused, unfused or later round-trip behavior,
selected by the complete exact saved signature, including unpaired performance
observations. This same-version reconstruction cannot apply lossy parsing to an
ordinary valid v1 decimal or downgrade its encoding. No saved encoding,
source hash, scientific signature or VSZ is upgraded by this declaration.
A versioned specification must reproduce through its own parser. An unversioned
historical specification can instead reproduce through the original table
inference and frozen pandas 3.0.6 17-digit accumulation/scaling,
only after the current parser's exact signature does not match. That compatibility
reader is local to the audited private frame. Its fused and unfused binary64
evaluation candidates are selected only by the complete exact saved signature;
neither OS detection nor an ambient dependency selects scientific values. A
match proves values, not a historical compiler identity. Complete values, axes, identities
and source-artifact signatures must still match exactly. Unknown encodings fail
closed. This audit does not rewrite a historical specification or native document,
and introduces no numeric tolerance or reinterpretation of old measurements.

DataMapping proposals remain version-2 declarations of source, columns, units
and operations. A proposal alone does not authorize historical numeric parsing.
New execution manifests use version 3: the envelope fixes
`decimal_float64_round_trip_v2` for validation, numeric transformations, sort
keys and table eligibility; the transform step records that derived encoding.
The current-parser alias cannot choose a different meaning for this version.
Fresh preview and execution use this contract even for an old proposal.

Completed execution versions 1 and 2 retain their original files and ledger
parameters. After validating the existing source, output, request and lineage
seals, the loader reconstructs the complete execution using one coherent,
bounded historical pipeline. Actual synthetic old-producer records distinguish
the pandas 3.0.6 fused sort from its round-trip numeric transformations and the
later 3.1 parsing behavior. A candidate must reproduce every source's exact
output bytes and all row, column, unit, sample, selection and transform facts;
different sources or operations cannot select independent candidates.
Unknown versions and mismatches fail closed. Matching content does not attest
a historical compiler or certify a new planning/native workflow. Existing
execution reuse passes the same complete loader before fresh strict preview;
neither reuse nor cold load rewrites the old record or weakens source checks.

Impact display statistics are declared by `materials_rules/impact_presentation.py`
and consumed by public rule descriptions and explicit task-presentation guards.
The existing executors still own the calculation: box/box-strip use median/IQR;
bar and compatible workbook condition point-line use arithmetic mean/sample SD.
Internal analysis n tables do not establish delivered valid-n disclosure. The
explicit wide/bar `mean_sample_sd_n` route adds the source-checked visible summary
described above; it does not reinterpret box statistics or old specifications. The
guard preserves an unsupported scientific request rather than changing its
template, statistical meaning, source observations or scientific owner.

`delivery/filesystem_metadata.py` recognizes only a standalone regular `.DS_Store`
as incidental Finder metadata within a visible delivery. Package validation,
replacement snapshots and the delivery side of edit-state comparison share this
exception; source and managed-project inventories do not. Replacement preserves
metadata bytes and rechecks the backup's artifact inventory before installation.
Same-named directories/links and other unknown files retain existing rejection
and rollback guards. Metadata is never scientific or current-document evidence.

Compatibility facades may preserve a public import or documented monkeypatch
seam. They must not acquire business logic or become forwarding layers without
a real compatibility caller.

Shared consumers use named owner ports for original table reads, exact numeric
evidence, race-safe source snapshots and source inventory. Existing local/private
aliases remain where supported patch seams need them; byte, precision, shape,
identity and before/after source guards retain the same implementations.
`rendering_contract/legacy_algorithms.py` exposes named compatibility bindings to
the same sealed tick/legend functions and series values. Grammar consumes that
contract without changing the 24 sealed source entries, v1 manifest or historical
compiler interpretation. This does not complete general policy injection.

Unused private facade reexports can retire only after checking literal/dynamic
callers, public promises and persisted references. The transform implementation
reference in historical ledgers is retained. TGA's documented compatibility
adapter, public modes, Qt shims, mapping v1 inspection and worker `-m` entrypoints
remain supported. Cell text reuses its source-table owner; provider free text
uses a named typed-provider port, retaining boundary aliases and identical error
behavior. The template validator shares its catalog; the environment factory
shares its provider owner while public imports and absent-provider behavior stay
the same.

The unused `studio_core.document_archive` module and private
`semantic_sources.series_labels._constant_sample_label` helper are retired.
Manual-edit preservation remains in the live figure-set transaction in
`figure_set_storage`, including backup hashes, history and rollback; the other
sample-label helpers retain their existing reader callers. The retired source
paths remain classified by their existing verification owners so a deletion
cannot bypass the changed-file guard. Worker entrypoints, registered CLI modes,
public compatibility ports and persisted implementation references are retained.

The archive module's orphaned generated-hash lookup and unused workflow metric
and figure-style aliases are also retired; live transaction and rendering owners
retain their implementations. The unused `statsmodels` base requirement is
removed from distribution dependency discovery without uninstalling local
packages. Tests retain their complete node/parameter set and scientific/security
assertions; only an uncalled readiness-test helper is removed, with the changed
test-source bytes rebound in the preliminary corpus inventory.
The untyped workflow export helper has an exact changed owner that reuses the
workflow export regressions; the strict type-path sets remain unchanged.

Readiness registry freshness covers rule declarations and render-request policy,
not current implementation bytes or environment identity. Historical owner
validation has no build binding. The status projection states these limits;
current implementation acceptance remains separate evidence. File-length and AST
guards are regression aids, not proof that module responsibilities are cohesive.

An external query's `status=ok` means that reading succeeded. It reports
`ready_to_use=null` and `readiness_evaluated=false`; source hashes, artifact QA
hashes and visible-package hashes do not substitute for a new scientific audit,
build certification or visual review. Preview/apply likewise do not publish.
The existing exact-current managed export remains the complete-figure-set
scientific audit, export, QA and delivery boundary.

Document edit history is a bounded transaction recovery record beneath the
project's private runtime, not a second document model or a general exactly-once
execution engine. Reapplying the same preview can return `already_applied` when
the installed result and archived evidence still match; later edits invalidate
that reuse. External commits preserve ordinary failure rollback, while a process
interruption requires inspection of its durable outcome before claiming success.

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
valid visual authority for standalone exact-current export. A managed,
source-faithful delivery requires its scientific spec and source bindings;
missing evidence blocks publication rather than inventing a spec from the
current appearance or inferring a template in reverse.

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
VSZ projects, the default SciPlot canvas launcher and the retained Veusz launcher.
It is not a runtime workspace. The legacy Veusz launcher keeps the delivery's
identity and editable-file baselines; both entrypoints resolve the same owner.

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
4. `foundation/` is the lowest shared dependency leaf. `policy/` and
   `source_tables/` may depend on `foundation/`, but these low-level packages
   never depend on higher core layers or on each other.
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
    retain their one-template behavior. At publication, a registered
    single-curve plan replaces any pre-source generic Study Model queue with
    its exact task before outcomes and artifacts are attached; `primary_curve`
    cannot survive as an unbound parallel identity.
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
    XRD, and SAXS; `tga_transform.py` is only its compatibility wrapper.
    `transform_contract_values.py` owns the common exclusion-count and
    axis-compatibility projections used by transform-contract leaves. The
    registered reader accepts a file or a directory containing exactly one
    supported table, requires
    explicit units identity-equivalent to the selected rule except for XRD raw
    counts presented unchanged as registered arbitrary intensity, and derives
    adjacent/header/schema unit evidence plus preceding/adjacent/instrument/
    fallback sample identity from that same table snapshot. PANalytical
    mixed-width CSV input is parsed quote-aware; its exact scan-point schema and
    declared row count must agree before output. Log-domain exclusion follows only
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
    Swelling joins through a third thin reader: a unique labeled worksheet and
    source-derived condition/replicate identities own one first numeric run per
    Time/ratio pair; a single source row without structural text may be bridged, while a
    longer structural break closes the run and records later numeric values as
    disconnected exclusions. Its declared s/min/h coordinate may be converted
    to h without sorting or interpolation. None of these adapters adds another
    FigurePlan, renderer, bundle, or chemistry/molecular-weight claim. Generic multi-task plans,
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

Verification requirements are defined once in `skill/references/development.md`,
reached through the task router in `skill/SKILL.md`.
