# SciPlot unfinished development priorities

Status: 2026-10-13. External AI is the task interface. Current behavior belongs
in README and live capabilities; this file lists unfinished, closable work.

## 2026-10-13 continuation: implementation, evidence, and next slices

Implemented on the local integration branch, not yet published or released:

- The repository policy now permits only explicitly curated documentation and
  showcase assets. The tracked-ignored-file gate still rejects local-only work,
  and a source-control regression checks both allowed and private paths. A
  development-only NumPy bound keeps the Python 3.11 mypy gate compatible with
  its dependency stubs; ordinary runtime NumPy resolution is unchanged.
- Managed FigureTemplate v2 has additional source-revision and semantic-edit
  regressions: exact changed source values and units, unchanged presentation
  state during scientific refresh, stale-source rejection, no-op without a
  revision and exact changed-source IR values/units. The supported plotting
  model and LegacyPlot authority rules are unchanged.
- `project.open` and `plot.describe` accept opt-in ManagedPlot summary or exact
  target/property edit reads. Omitting the selector returns the prior full
  response; LegacyPlot summary remains full and LegacyPlot edit is rejected.
  Focused tests cover contracts, revision/currentness guards, CLI/RPC/MCP
  adapter routing and selector errors. Local encoded response bytes are smaller
  on the test figure. Actual external-client tokens, billed cost and
  user-visible time are unknown.
- The existing local protocol evidence now distinguishes actual CLI stdout
  UTF-8 bytes from re-encoded MCP/RPC result bytes and retains three warm
  same-operation RPC observations. No cross-transport or before/after speedup
  is inferred from them.
- The saved-figure AI entry now chooses the compact summary first for a
  previously identified ManagedPlot, then the exact selected edit contract or
  literal typed text-intent plan. Unknown authority and LegacyPlot still start
  with the full response. A fixture-scoped MCP serialization comparison is
  recorded separately from the full tool-definition payload, which response
  scoping does not remove; it is not external-client token, cost or end-to-end
  latency evidence.
- The official MCP stdio client discovery/error-recovery regression now checks
  the 33 currently advertised tools, including `sciplot_plot_intent`, and
  passes locally. Its former 32-tool expectation was stale; this check does
  not exercise native preview/export or an independent AI client.
- An opt-in `plot.intent` route now resolves only Managed FigureSpec v2 axis
  labels and annotation text from an exact stable ID or unique current label.
  Its plan shows the literal before/after value and unit or anchor context;
  explicit apply delegates to the same revision-checked, idempotent semantic
  patch transaction. Ambiguous labels fail closed. An axis-label regression
  checks unchanged scientific state; native preview/export is not yet verified
  in this cloud runner.
- In-process, real-journal fault-injection regressions now check typed-intent
  candidate-write and head-commit interruption, replay, source/native drift,
  stale or historical delivery guards, and equivalent stable-ID/label replay.
  No unsafe replay was reproduced, so this adds no journal protocol or native
  behavior change. Additional scoped-read regressions check malformed direct
  Python selectors before import writes, duplicate display labels with exact
  stable-ID/scientific context, and simultaneous source/native drift without
  starting native inspection or mutating the source. These tests do not replace
  native worker or socket acceptance. An aggregate changed-path audit also
  found and fixed the missing fail-closed owner mapping for the saved rebuild
  explanation regression.
- A new plot edit competing with a pending transaction now returns a read-only
  `plot.describe(scope=summary)` repair with the observed pending phase/key,
  rather than suggesting that the caller replay a different request. Stale
  typed revision/identity errors also point to the compact current read.
  Real-journal and CLI/RPC/MCP adapter regressions cover the structured repair;
  the transaction, revision and apply paths are unchanged.
- Managed summary reads now explain observed changed inputs and affected saved
  dependency nodes. They leave future cache reuse, native scientific audit and
  export inventory unverified. A changed-native summary defers native
  inspection while retaining its external-mutation resolution guard; the
  original full description still follows its prior inspection path. This is
  an explanation of current evidence, not a second scheduler or a guaranteed
  future execution plan.
- Scoped Managed reads now assemble only advertised property names or the one
  selected Figure descriptor, and skip dependency build keys discarded by the
  compact response. They retain changed-input, pending, authority and saved
  graph invalidation guards; fixture JSON-RPC responses match the prior bytes.
  A reproducible 50-call local in-process probe in the task measurement note
  observed shorter summary/edit wall times. This is not a model-token,
  external-client latency or cache-reuse claim.
- The local Doctor now distinguishes missing or unloadable vendored Qt helpers,
  optional source-build tools, unavailable AF_UNIX transport and the separate
  optional private acceptance corpus. It diagnoses this cloud runner's blockers;
  it does not provision dependencies, create substitute data or skip failed
  tests. The ordinary runtime does not require the private corpus.
- A source-checkout-only, stand-alone private-corpus preflight now checks 116
  explicitly inventoried collected test/parameter IDs against their declared
  local fixture structure. Unknown IDs, absent/wrong-type/empty paths, unsafe
  links, stale collection and incomplete inventory return `BLOCKED` and a
  nonzero exit. This preliminary inventory starts from the saved 111 first
  blockers plus five source-inspected comprehensive cases; it is explicitly
  nonexhaustive and does not establish scientific identity or acceptance. No
  pytest markers, CI selection, test skips, ordinary runtime or release gate
  were changed.
- An opt-in native-document font preflight records saved requested settings
  and a specifically qualified Qt screen-font match. The painter-used face,
  glyph fallback and resolved font-file bytes remain unobserved, so cross-host
  rendering portability is unestablished. Default inspection, cache/build
  identities and scientific state remain unchanged. On one actual Linux Figure
  VSZ, 34 saved Utopia requests matched Qt's screen preflight exactly and 10
  Arial requests resolved to Liberation Sans instead; the default inspection
  JSON and VSZ bytes were unchanged. This is not the native-painted font or
  font-file identity, nor cross-host visual portability evidence.

The matched Linux PyQt6/Qt6 6.8.x validation worktree built the vendored Veusz
helpers locally without committing binaries. It exposed a real FigureSpec v2
publication-QA renderer lifetime bug: a per-instance render wrapper held a
renderer/painter cycle until later garbage collection, and the first weakref
repair then expired renderers used inline by Veusz. QA now keeps those instances
alive only through synchronous painting and releases them in `finally`; a
no-GC inline/repeated-render regression covers both failure modes. On the exact
integrated commit, the direct Figure backend suite (4), Figure service source
refresh (1), managed backend native cases (3), and managed-engine source/
transform rebuild and external-script invalidation (2) pass. One direct export
produced a one-page PDF and 1062×659 TIFF, with its TIFF hash unchanged by the
QA lifetime fix. These 10 tests are targeted Linux native evidence, not a
complete native, Mac or private-data acceptance.

At code commit `79a9b9f`, a bounded matched-Qt follow-up retried all 50 exact
test/parameter IDs whose first traceback in the saved pre-build focused log
stopped at missing `qtloops`: all 50 passed. The selection spans synthetic TTS
export/style/error handling, tracked-fixture studio plans, and a child native
worker guarded by a local `fcntl.flock` lease. This is a count of test IDs,
not of native render calls; the four selected TTS files also contain pure
validation tests. Separately, nine selected direct native live-edit,
annotation, document-edit and managed-recovery tests passed, as did both
LegacyPlot human-save reimport parameters. The reimport test initially reached
its final optional evidence write on a fresh checkout and failed because its
ignored output directory was absent. A reviewed test-only fix now creates
that parent; both parameters pass in a fresh worktree without precreation.
The original 10 direct-native cases above were also rerun at this code commit
and passed. These targeted runs do not constitute a current-HEAD full suite.

Verification still open: compiled Veusz helpers are present only in the
isolated validation worktree, and the cloud sandbox denies AF_UNIX sockets, so
socket-backed protocol tests and their new measurements are unverified here.
The direct-native and historical-blocker selections do not cover every
workflow. This minimal source checkout also lacks the separate local
original-data corpus referenced by some broad tests;
resolve the public test-tier boundary or provision the authorized corpus before
claiming a full source-only CI pass. No clean Mac, independent human or external
AI-client token/cost acceptance is implied by the local regression evidence.

A saved pre-final-run `pytest -q -m focused` log (SHA-256
`2d4279448fb7982047794eec198bee91e919901892ad1944ba7645cb3a75d91c`)
records 3332 passed, 152 failed, 19 errors, 2 skipped and 192 deselected.
Its 171 observed non-passes were classified from their tracebacks: 111 stop
at the absent private original-data corpus, 50 at the missing compiled Veusz
`qtloops` helper and 10 at denied AF_UNIX socket creation. No first traceback
was classified as a product failure. This inventory comes from a pre-final
commit, not a current-HEAD full-suite pass. The 50 `qtloops`-blocked IDs were
subsequently rerun and passed in the bounded selection above; the missing
private-data and socket cases may still expose later assertions once their
prerequisites are available.

Proposed P0 validation-tier repair, **not implemented**: `focused` and
`comprehensive` remain runtime-depth tiers. An explicit private-corpus
requirement would be an orthogonal marker at individual test or parameter-case
granularity, not a blanket module exclusion; mixed public/synthetic and
private-source cases already occur in one test module. Start with the 111 saved
first blockers and the preliminary 116-case preflight inventory, then review
the complete fixture dependency inventory before marking anything. A public
source-checkout regression may exclude only reviewed private cases **after**
an authorized private runner is operating; a green
public subset is not scientific acceptance. Public CI must still run its full
public `focused` and `comprehensive` native-backed gates; this is not a Qt
bypass. On the same commit, the authorized Mac/private/native run must execute
the full unfiltered suite, with independent
human acceptance tracked separately. Its missing-corpus preflight must exit
nonzero with a clear BLOCKED result, never silently skip or replace data. The
current Doctor's optional fixture-existence check and the new, explicitly
incomplete stand-alone preflight are not a full private acceptance gate.
When implementing, make `verify --changed` show private evidence as pending
rather than falsely green; coordinate changed-owner selection, smoke and other
acceptance outside pytest, the advanced guide, and the release `full_pytest`
gate so private and public evidence cannot be conflated. The private release
gate remains blocked until real execution exists. Keep existing CI/markers
unchanged until that gate can be validated end to end.

Remaining acceptance and candidate next slices. The first two have a bounded
local implementation above; their broader native/client evidence gates remain
open. Later additions should use existing document, patch and dependency
owners rather than another grammar, cache or renderer:

1. The bounded axis-label/annotation-text route is implemented locally; a
   theme intent remains a proposal. Before broadening, check exact targets,
   stale revisions, native review and unchanged science. [Vega-Lite parameters](https://vega.github.io/vega-lite/docs/parameter.html)
   are an interaction/declarative reference, not a SciPlot schema migration.
2. The read-only dependency explanation is implemented for observed saved
   state; it deliberately does not declare nodes reusable or due to run with
   certainty. Compare its statements with actual local execution and recovery
   before claiming predictive accuracy. [DVC status](https://doc.dvc.org/command-reference/status)
   and [repro](https://doc.dvc.org/command-reference/repro) are UX references,
   not a second SciPlot scheduler.
3. The opt-in screen-font preflight above is partial identity evidence. Record
   the font face/file actually used by native painting only where the runtime
   can prove it, leaving unresolved identity explicitly unknown. [Matplotlib's font
   manager](https://matplotlib.org/stable/api/font_manager_api.html) illustrates
   why a family name alone is not portability evidence. Exit only after
   cross-environment visual and resource-identity checks.
4. MCP discovery optimization is a deferred measurement question. A local
   official-stdio client re-encoding of `tools/list` with this SDK/code yielded
   33 tools and 138,628 UTF-8 bytes including result metadata; the eight
   largest separately encoded tool definitions totalled 119,083 bytes.
   Neither figure measures imported client context, tokens, cache, billed cost
   or latency. First gather independent client traces and, where a host actually
   supports them, evaluate [client-side filtering or deferred tool loading](https://developers.openai.com/api/docs/guides/tools-connectors-mcp).
   Consider an opt-in scoped server profile only if those traces justify it;
   keep the current full schema/validation path available. No discovery
   profile is implemented in this round.

## Semantic document migration after the verified presentation slice

The 2026-10-07 slice introduces a versioned scientific/presentation model, stable
semantic patches, durable revisions/recovery, audited Veusz shadow import and a
persistent CLI/MCP service. Its A–G acceptance covers safe title/width edits,
scientific/stale-revision rejection, source invalidation, idempotency and separate
export recovery. This changes the ordinary supported-edit entry; it does not mean
every scientific plot or native setting has been migrated.

The supported ManagedPlot contracts now have document authority,
resolved PlotIR, disposable backend artifacts, typed deterministic transforms,
fixed-file external executors, per-source/transform dependency invalidation and
ExternalMutation classification. Real rebuild acceptance includes the public CLI
and MCP path. Legacy imports and source-only task creation remain compatibility;
no automatic promotion is intended.

FigureSpec/PlotIR v2 now covers generic multiple scales/views, seven typed marks,
weighted physical layout, scoped themes, guides and actual native-text bounds QA.
Real dual-Y rheology, 2x2 mixed research data, impact uncertainty/points and spectrum
annotation slices pass full rebuild. This closes the bounded grammar slice, not
arbitrary native feature parity or journal acceptance.

The visual compatibility gate now compares retained production legacy rendering
against new contract-bound FigureTemplate v2, independently of self-rebuild.
Five real single-panel line/point/spectrum cases match effective structure and
native pixels; immutable extracted house style and a separate composition policy
replace unrecorded visual defaults. See the root rendering-contract/drift reports.
Real historical mechanical bars/errorbar caps and separate PP frequency-sweep
G′/G″ now have fixed three-way golden profiles; existing FTIR/NMR remain green.
See [research compatibility profiles](docs/RESEARCH_COMPATIBILITY_PROFILES.md).
Remaining visual acceptance includes mechanical visible individual points/legends,
a historically delivered dual-Y golden, other legacy families, multi-panel quality,
additional font/runtime environments and hidden channels before exposing them.
Historical unbound revisions and explicit v1 templates are not silently restyled.

Remaining expansion requires equivalent full-rebuild evidence: symlog/other scale
transforms, facets/repeat, spanning/sparse grids, multiple figure legends, colorbars,
image/area marks, broader named scientific templates, explicitly pinned additional
resources and resolved font-file identities, richer continuous geometry collision
checks, known managed external-delta adoption and explicit authority conversion.
Non-deterministic executor adoption and uncertain external-execution reconciliation
need their own durable contracts. Background file observation remains separate;
current exact byte checks run when requests use files.

Exit: each added capability has a real native round-trip and failure-recovery
case; template instantiation preserves supplied data/units and requested style;
new scientific nodes carry an explicit versioned execution/decision contract.
Keep local timings separate from external-model tokens and end-to-end user time.

## 1. Independent beginner and installation acceptance

Reactivated for the macOS public beta on 2026-09-26. The distribution tools now
retain failed verification, bind the relocated app and its ZIP to exact file
identities, exercise task capabilities over MCP, and reject public packaging
without Developer ID, a stapled notarization ticket and Gatekeeper acceptance.
The [beta guide](docs/PUBLIC_BETA.md) covers installation, current canvas editing,
feedback and recovery. These automated gates do not close the independent checks.

Recruit 3–5 people who did not develop SciPlot. On the first supported macOS
configuration, have them install/connect, create a figure from their own data,
answer a real ambiguity, request an annotation, export and resume the next day.
Record completions, time, maintainer interventions and mistaken project choices.
Current programmatic/agent evidence is not this human usability evidence.

Validate a clean machine separately from relocation on the development machine.
Finish a signed/notarized distribution path if distributing to other Macs.
Additional platforms and AI clients need their own installation acceptance.

## 2. Independent original-data acceptance for table choices

Worksheet/region selection, multirow headers, shared X and multiple XY use
the same source-bound task/DataMapping route. Bounded original-region queries,
per-column diagnostics and evidence-bound metadata confirmations now complete
one untouched independent XRD workbook through creation/export. A real external
figure confirms another source's quantity while its missing unit still blocks it.
See [the metadata acceptance record](docs/SCIENTIFIC_METADATA_ACCEPTANCE.md).
The five earlier failures remain historical evidence. A published natural workbook
revision now completes fresh mapping, annotation review and export; its selected
XRD measurements are unchanged across versions.

Independent per-pair rows and cross-sheet mappings are implemented, including
native source updates. One untouched Bath XRD workbook retains 3,477/2,745 points
through exact-current export; see [range acceptance](docs/TABLE_RANGE_ACCEPTANCE.md).
The public Zhou natural workbook revision preserves all 4,779 points per selected
curve through native/CSV export. Real changed-value and cross-sheet revisions
remain additional acceptance work; current changed-value cross-sheet evidence is
automated. New one-dimensional native persistence now retains full binary64 values
and audits them exactly; older specs retain their original precision contract.
Explicit XLSX/XLSM merged metadata and numeric-only sample labels are implemented.
The untouched Bath-01345 workbook now selects its declared merged sample row
without separate sample declarations. The user-supplied original 17-series FTIR
workbook now preserves numeric sample IDs 1–17 through native creation and export,
with every delivered value checked against its 7,469 original points per curve.
Extend real-case
coverage for externally documented units and scientific statements. Unit conversions
or new quantities need their own scientific rule contract; never infer them just
to make an acceptance source pass. The task rule-selection answer must not encode
arbitrary scientific facts. Extend reusable profiles only when current headers,
units and mappings can be validated.

Exit: every advertised new choice has an untouched independent source completing
selection, correction, native creation and exact-current export through task/MCP.

## 3. Reviewed annotation rebinding: independent source-revision acceptance

Fresh mapped-source selection, compatible fixed annotations and reviewed observed
peak rebinding now have automated native coverage, including moved/missing/multiple
candidates and export-only recovery. An author's published original/revision pair
with unchanged selected XRD values completes the same lifecycle with known sample
identity and exact raw/VSZ/CSV agreement. Independent revisions with moved, missing
or multiple changed peaks remain needed. Do not count edited synthetic copies or
development fixtures as that evidence.

Validate original metadata, measurements, sample identity and final VSZ/spec/CSV
together. New version-2 interrupted installations can restore a completely
byte-proven baseline, preserve displaced candidate bytes and resume the reviewed
update. Tests cover every replacement boundary, interruption during recovery and
a killed native process resumed through public task CLI. Unknown/tampered parts
and legacy mixed installations still block. Independent real interrupted-update
evidence remains separate from these fault-injection tests.

Exit: untouched real revisions cover every peak outcome and confirmed mapping,
with reviewed previews, correct exports and recorded interruption recovery.

## 4. Measured usability and AI-efficiency improvements

Compact capability discovery, named schema reads, lossless definition factoring
and state-specific next-step guidance are implemented. In the earlier measurement,
local full output decreased
from 204,457 to 51,609 bytes with the same expanded definitions; this is not a
measured AI token or latency improvement. See [measurement boundaries](docs/TASK_CAPABILITY_MEASUREMENTS.md).

Operation-local byte-checked table reuse, array-based scanning, compact table
questions, local phase timing and fresh completion queries are implemented.
Local complete-task benchmarks now cover synthetic spectra, an untouched Bath
workbook and three archived user experiments. The fast agent route avoids separate
planning/export calls and redundant completion queries. These measurements still
do not establish external model latency or token savings.
Caller-reviewed `create.mapping` now batches original table/metadata/column choices
in one source-bound call. CLI/MCP task receipts are compact by default, with full
responses on demand. Their local replay measurements are recorded separately from
actual external-model token counts and user-perceived end-to-end time.
Repeated original-table cleanup/workbook structure reads now share the same
byte-checked operation scope; short schema references further reduce discovery
text without changing validation. Three-run before/after medians are recorded for
the already-batched route; native startup/export and external AI time remain.

Recovery now accepts one question-bound mapping answer with rows, columns,
evidence and display labels in the same task. Structural diagnostics and a strict
single-table metadata repair handle deterministic layout issues locally. This
shared recovery includes FTIR; scientific ambiguity still belongs to the caller.
The ordinary agent entry is shorter and advanced workflows are loaded on demand.
Three-run local correction replay reduced four calls to two while preserving
the complete exported CSV. Independent client behavior and token telemetry remain
separate measurements; the prior Luna run exposed repeated recovery detours.

Explicit source-note evidence now supports bounded shared-X mapping candidates:
the AI reviews the proposed rows, columns, units and samples, then submits the
question and candidate IDs (optionally a sample subset). Ambiguous notes and
incomplete numeric ranges still require a full mapping decision. For the original
17-series FTIR workbook, two sequential local runs per condition reduced median
complete CLI time from 34.505 to 20.074 s, with identical CSVs and TIFF pixels;
the answer shrank from 47,640 to 184 UTF-8 bytes. These are not model token counts.
The reused Luna retest still took 202 s with parent intervention after request
field mistakes; precise invalid-field diagnostics now address that observed detour.
The task boundary now automatically relocates unambiguous task-location aliases,
returns structured constraint violations with current question/next-step context,
and pauses on occupied outputs before planning. Explicit output correction resumes
the same task without moving old deliveries; uncertain native creation cannot be
redirected. Exact current-question bindings reuse the earlier evidence and return
only correction details; stale bindings return current evidence. A real-workbook
local fault replay completed in 19.844 s with zero extra inspect/help calls,
including 0.340 s conflict detection and 0.331 s bad-answer feedback (1,802 bytes).
This used predetermined corrections, not measured AI inference.
An unassisted matched client run and further native creation/export optimization
remain needed before claiming second-scale end-to-end performance.
A fresh-context prepared-rheology recovery client has now completed one saved
64-coordinate figure with one resume and unchanged native identity. Its partial
trace and four recorded CLI calls are documented in the measurement record.
A separate fresh-context ordinary-task client has now completed the archived
17-series FTIR workbook in six recorded CLI calls without parent correction or
prefilled requests/mapping. All 126,973 original XY pairs and 34 native datasets
passed, with the final TIFF viewed by client and parent. This closes one bounded
raw-workbook client case; its tool trace remains partial. The old Downloads
source/delivery remain absent and the new trial used a same-byte archive copy.
Neither case establishes matched before/after token or time improvement; actual
model telemetry and independent human/clean-machine acceptance remain open.

The 2026-10-04 saved-edit review found minutes of user-visible time around tens
of seconds of recorded local commands. Saved-edit routing now avoids redundant
discovery/audit/export steps. Combining the primary export and scientific audit
worker reduced a controlled dense-NMR re-export from 5.530 to 5.014 s (two-run
medians), preserving exact data and raster pixels. Finder metadata no longer
invalidates an otherwise current delivery. These bounded corrections do not
close the matched external-client latency/telemetry work above; see the current
measurement record for scope and unchanged creation timing.

A follow-up edit-context entry now combines readiness, current figure identity,
targets and selected schemas. An independent ordinary demo edit completed in
three public CLI calls with both visual reviews and current source/QA/delivery.
The skill entry routes to one task-specific guide. The client still used 16
underlying tools including evidence capture and memory lookup; three CLI calls
do not mean three tools or establish a matched end-to-end speedup.

The 2026-10-07 typed entries move request construction into the program:
recognized ordinary creation completed in one CLI call, and a fresh sample-style
client completed preview/accept/export in two calls without caller-authored JSON.
That client reported ten underlying tools, including two early-yield waits; the
skill now recommends a normal initial wait. Final demo TIFF pixels match the
earlier three-command result. End-to-end timing/token telemetry remains open.

Use the same real tasks to compare model rounds, tool calls, returned bytes,
latency, failures and user questions. Report actual client token telemetry when
available; unknown is not zero. Improve compact results and orchestration from
observed friction, while retaining visual review and genuine scientific choices.

Exit: publish a reproducible before/after record with matching task scope and
quality checks. Do not equate fewer CLI calls with a measured token percentage.


The 2026-10-07 protocol/recovery milestone adds exact JSON argument failures,
shared width preflight, semantic correction fields, stable typed-style replay,
one durable preview-timeout retry, phase-specific continuation and local full
error references. The real-client normal-path record and injected native-failure
record remain distinct. General no-op export reuse, broad automatic recovery and
population-level error/token/latency evidence are not claimed complete. See the
current task capability measurements for verification and observed boundaries.
