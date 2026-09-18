# Task capability and local plotting measurements

## 2026-09-17 second pass: repeated table cleanup and schema references

Profiling a complete already-mapped Bath workbook task found 209 mapping-table
reads, 52 workbook openings and 860,992 missing-token cleanup calls. Original
Excel parsing was already reused, but repeated CSV parsing, workbook sheet-name
reading and selected-frame cleanup remained. The operation-local 32 MiB cache now
also reuses those deterministic results. Metadata-cell evidence and scientific
validation still run each time. Cached cleanup is bound to the exact bytes read
for the original cells, preventing stale cells from being stored under a new hash.
Returned frames remain independent, raw `NA` text is preserved in evidence mode,
and different ranges/parsing modes retain separate cache identities.
In the same profiled case, workbook openings decreased from 52 to 6 and cleanup
calls from 860,992 to 19,568. Profiling overhead is excluded from the wall-time
benchmarks below.

Capability schemas now use short local definition names instead of repeating
full SHA digests in every `$ref`. Internal deduplication still uses full hashes;
existing definition names cannot be overwritten. The expanded schema, complete
server validation and capability contract fingerprint are unchanged. Small inputs
are left intact when factoring would increase their serialized size.

| CLI schema response | Before | After |
| --- | ---: | ---: |
| Capability index | 1,282 bytes | 1,282 bytes |
| Create schema | 9,585 bytes | 8,322 bytes |
| Full task schemas | 60,439 bytes | 52,281 bytes |

Timing used three fresh complete tasks per condition, interleaving the saved
previous implementation and new implementation without concurrent test runs.
Both conditions already use the one-call mapping route introduced above. Values
below are medians of local wall time, including CLI startup, native export and QA.

| Case | Previous one-call route | After this pass |
| --- | ---: | ---: |
| Bath workbook, 2 × 4,892 points | 5.252 s | 4.982 s |
| Synthetic ordinary spectra, 5 × 2,000 points | 4.905 s | 4.277 s |

These represent 5.1% and 12.8% lower local elapsed time in this replay. They are
not percentile guarantees or measured external model/token improvements. Existing
native workers and independent scientific/visual audits remain unchanged. Evidence,
the previous source snapshot and replay scripts are retained under
`.tmp_verify/ai_route_phase2_20260917/`. The remaining native startup/export time
and external AI time are separate future work, not a claim of universal one-second
complete publication.
All six mapped CSV outputs in each case matched exactly, and an actual native
before/after pair in each case had identical X/Y values, point counts, sample
identities and colors. Original input hashes stayed unchanged. Every timed run
completed with current source, QA and delivery checks.

## 2026-09-17 caller-reviewed mapping and compact task receipts

The external AI still interprets original data and supplies the scientific intent.
`create.mapping` submits already-reviewed original-file SHA, table selection,
optional attributed metadata and XY pairs together. The existing local mapping
validators, confirmation, plan, Veusz, QA and publication owners remain in charge.
This avoids returning intermediate questions the caller has already answered.
Ambiguous or invalid selections still pause with the current question and error.
CLI/MCP completion responses now omit repeated inventories and healthy-check
detail by default; full responses remain available via `--full`, `full:true`, or
the MCP full-result resource. Questions and review audits remain available.

A sequential public-CLI replay used the same unchanged Bath-01345 workbook and
the same caller-selected XRD region (4,892 points in each of two curves). Both
routes assume the AI already inspected the original data. They exclude that
inspection, capability discovery and external AI latency. The interactive route
uses full responses matching the previous task transport; the batched route uses
the compact default. These are individual local runs, not a latency guarantee.

| Route | Task calls | Total returned UTF-8 bytes | Local elapsed |
| --- | ---: | ---: | ---: |
| Start, table selection, pair selection | 3 | 29,783 | 7.830 s |
| One start with explicit mapping | 1 | 3,801 | 5.133 s |

Returned text decreased 87.2%. Complete original bytes, mapped CSV text, sample
identities and all native X/Y arrays matched; current source/QA/delivery checks
passed for both. Evidence and replay script are under
`.tmp_verify/ai_route_20260917/` (`route-metrics.json`, `measure_route.py`, and the
two route directories). A separate unchanged user FTIR task response projected
from 7,092 to 3,681 bytes without changing its saved task or native document.

The optional mapping schema makes create discovery larger: the current formatted
index is 1,282 bytes, create schema 9,585 bytes and full task schemas 60,439 bytes
(including the CLI trailing newline). The earlier simple-create schema was 1,183
bytes. Cache discovery per contract revision; do not charge schema setup as zero
or repeatedly fetch it per figure. The replay's returned-byte reduction is not a
measured tokenizer percentage. Actual client tokens, model rounds and external
end-to-end latency remain unknown until matched client telemetry is available.

## Earlier capability measurements

Recorded 2026-09-10. This is local interface evidence; the matched real AI-client
task comparison remains open. Installation/release work is deferred.

## Change

`task capabilities` now returns a version-2 index. `--section` and optional `--name`
read one request action, response field, operation or original-table query schema.
`--expected-contract` binds the read to the index fingerprint. `--full` returns all
task schemas. Task requests retain version 1 and all existing revision guards.

Repeated JSON Schema nodes use root-local `$defs` references. Every returned schema
and MCP tool input schema is standalone. The original domain validators remain
complete; expanding the new full schemas exactly reproduces the saved baseline.
MCP exposes `sciplot_task_capabilities`. Task receipts include state-specific
`next_step` guidance for questions, image review, export retry, preview correction
and uncertain outcomes, using the existing recovery/transaction owners.

## Local measurements

The earlier quoted 181,506 bytes preceded scientific-metadata and independent-range
schema additions. The immediate optimization baseline was **204,457 bytes**.
Each condition below was run three times through the public CLI and saved in
`.tmp_verify/ai_efficiency/`. All nine optimized queries and three baseline queries
exited successfully, with identical byte counts within each condition.

| Query | UTF-8 stdout bytes | Local elapsed median | Range |
| --- | ---: | ---: | ---: |
| Previous full output | 204,457 | 0.311 s | 0.307–0.322 s |
| New `--full` | 51,609 | 0.371 s | 0.368–0.375 s |
| New default index | 1,282 | 0.352 s | 0.349–0.354 s |
| New `--section request --name create` | 1,183 | 0.349 s | 0.344–0.353 s |

Full definitions are 74.8% smaller. Index plus a create schema totals 2,465 bytes,
but requires two reads and contains less information than the full schema. This
does not establish lower total task latency or fewer model/tool calls. The local
timings include interpreter startup and were collected during development, with
other verification activity possible. They do not show a latency improvement.

Fingerprint: `f8466cf8e246a03c8b78be065e8660b4510cad3fd41f455cd2841c4136f3ecd5`.
`semantic-equivalence.json` verifies exact expansion equality for requests,
responses and original-region queries against `before-0.json`. Source-controlled
tests check every named schema, stale fingerprints, closed-field validation,
unsupported operations and unchanged revision/recovery boundaries. Official MCP
SDK tests cover discovery and the real native create/edit/export/cold-resume loop.

## Reproduction and limitations

Use the public commands three times each and preserve stdout, exit code, elapsed
time, source revision and contract fingerprint:

```bash
skill/scripts/sciplot task capabilities --json
skill/scripts/sciplot task capabilities --full --json
skill/scripts/sciplot task capabilities --section request --name create --json
.venv/bin/python -m pytest -q tests/test_task_capabilities.py
```

The pre-optimization stdout and timings are retained as `before-*.json` and
`before-metrics.json`; optimized results use `after-*.json`, `after-metrics.json`.
Reconstructing the old expanded shape from the same source-owned request/response
schemas reproduces its information content, but is not a new real-client baseline.

No matched AI-client end-to-end runs with model/tool rounds, actual returned bytes,
latency, failure retries and identical visual/scientific review have been recorded.
SDK transport tests and a deterministic CLI acceptance harness are not substitutes
for that measurement. AI-client token telemetry remains **unknown**, not zero.
The existing [independent acceptance protocol](INDEPENDENT_ACCEPTANCE.md) defines
the remaining matched-task measurements. No token or AI-latency benefit is claimed.

## Observed recovery

The public Zhou workbook workflow encountered `blocked/previewing` with
`invalid_coordinate`: a peak label's relative text position conflicted with its
data-coordinate arrow target. The returned `next_step` supplied
`expected_preview_revision=2`. A complete corrected operation batch using axis
coordinates produced a new reviewable preview; the native save happened only after
review acceptance. This exercised the existing correction and transaction owners.
It is one recorded recovery, not a measured reduction in client retries. The task
has no callable SciPlot MCP connection here; the user has been asked for an actual
client or log location before a matched-client result can be claimed.

The subsequent public sulfate-workbook check found a second concrete failure:
`inspect` suggested repeating the same failed inspection and reshaping the raw
table. The recognition error and CLI hint now preserve the original source and
point to the existing task capability/create route with `choose_columns:true`.
The hint requires a scientifically matching rule and states that column selection
does not transpose horizontal data or convert units. Following it on the unchanged
workbook reaches `needs_input/rule_id`, with no native creation. The source remains
unsupported; this is a verified diagnostic handoff, not a successful plot or a
measured reduction in client retries. The original failure and follow-up are in
`.tmp_verify/independent_ranges/candidates/4xg86pthpy-v3/`.

## 2026-09-17 local execution and task route

A profile of one cold inspection of the unchanged Bath-01345 workbook found
27 `pandas.read_excel` calls in that single operation. The profile attributes
6.28 of its 6.96 seconds to those repeated reads. Profiling adds overhead; the
unprofiled before/after measurements below are the timing comparison.
The same cold task query after the change performs three Excel reads, retained
in `parse-profile-comparison.json`; these cover distinct parse contexts/source
paths rather than 27 repeated reads.

Table parses now have one bounded operation-local cache (32 MiB), shared by
nested mapping, planning, creation, export and completion queries. Every reuse
rehashes actual bytes; cache entries return independent frame copies. Same-size,
same-mtime source changes invalidate reuse, and changes during parsing fail.
Scientific decisions, source hashes, saved VSZ and QA are still checked. Curve
scanning uses one object-array view instead of repeated pandas scalar indexing.
Nothing persists between task calls or replaces Veusz rendering.

Task question responses omit a duplicate table snapshot and bound initial table
previews to eight rows. Original metadata, rejection reasons, source identity and
question identity remain; `full_evidence_path` points to the complete hashed task
record, and `task table-region` reads additional original cells. Completed
start/resume calls return a fresh `current_project` query and TIFF paths when
source/QA/delivery are current. No additional preview/export/inspect call is
needed for that unchanged result. An idempotent retry keeps the task record,
timing totals, review IDs and document bytes unchanged.

`local_timing` records active local calls and their phases, including completion
checks. It excludes model/transport time, user waiting and interpreter startup;
the CLI wall times below include startup and all requested native creation,
PDF/TIFF export, QA and publication. `external_model_seconds` stays null. Saved
idempotent calls do not accumulate another timing sample.

The agent guide now routes supported creation directly through `task start`,
reuses session capability discovery, batches edits and avoids intermediate
exports. These changes remove unnecessary opportunities for AI/tool round trips.
Their end-to-end benefit still requires matched actual-client traces; no model
token or latency reduction is inferred from local bytes or local execution.

### Recorded results

All figures use the public local task CLI and the existing native Veusz route.
The final timing runs were sequential, without concurrent verification commands.
Ordinary spectra use three fresh synthetic five-sample, 2,000-point tasks per
condition; workbook and archived user rows below are individual representative
runs, not percentile latency guarantees. Before/after user runs use identical
source bytes and the pre-change Git source versus the current worktree.

| Case | Before | After | Scope |
| --- | ---: | ---: | --- |
| Ordinary spectrum | 6.352 s | 4.475 s | Median of three complete create/export tasks |
| Bath XRD workbook | 27.799 s | 5.234 s | Creation/export after confirmed mapping |
| Bath cold task inspection | 3.522 s | 0.931 s | Fresh source/QA/delivery query |
| User FTIR | 7.701 s | 7.003 s | Four samples × 7,469 points, one stacked figure |
| User temperature sweep | 5.058 s | 5.003 s | Four samples × 121 points, two figures |
| User stress relaxation | 3.520 s | 3.540 s | Three curves, 260/239/192 retained points |

Ordinary medians improved 29.5%; the workbook creation step improved 81.2%.
The user temperature and relaxation examples show effectively unchanged local
elapsed time. The earlier exploratory runs occurred under varying development
load and are retained separately; they are not the final comparison above.
These data support seconds for local execution, not a universal one-second result
or a measured explanation of the user's minutes-long external AI experience.

For the same Bath questions, table-selection stdout decreased from 54,442 to
9,638 bytes and metadata stdout from 55,763 to 10,958 bytes (82.3%/80.3%). This is
local UTF-8 output size, not client token telemetry. The original complete question
remains in the hashed task record. No scientific information needed for the
selected columns is discarded from that record.

User inputs were copied byte-for-byte from the supplied `新料 1.14/plot` archive
into ignored development evidence. Original hashes, sample order, point counts,
before/after plotted values, reopened native datasets and delivered CSV values
were verified. Visual review exposed an existing temperature-secondary label bug:
tan δ inherited G′ and Pa from the primary figure. The task's metric now sets its
default label; explicit label overrides remain authoritative. Final native axes
and CSV metadata use dimensionless tan δ, while values and sample identities
are unchanged. Originals and existing user deliveries were not rewritten.

Reproduction/evidence root: `.tmp_verify/speed_20260917/`:

- `benchmark.py`, `before/metrics.json`, `final-stable/metrics.json`.
- `user_benchmark.py`, `user-source-provenance.json`, `user-before-final/`,
  `user-final/`, `verify_user_integrity.py`, `user-integrity.json`.
- `bath-inspect.prof`, `bath-inspect-after.prof`, `parse-profile-comparison.json`,
  `merged-real/integrity.json`, `visual-review.json`.

The remaining external requirements are matched real AI-client wall time, model
rounds and token counts, plus independent naturally changed measurement revisions.
Neither local phase timers nor synthetic fault-injection tests close those items.
## 2026-09-18: one-answer task recovery

The same pending task now accepts `expected_question_id` plus a complete
`mapping` answer. It validates original rows, metadata, XY pairs and optional
display labels locally before continuing creation/export. Recognition failures
include bounded structural diagnostics; automatic layout repair is limited to
one explicit, unambiguous axis/unit/sample-row table. No scientific inference or
raw-array rewriting is introduced.

Six sequential public-CLI runs alternated the pre-change source snapshot and
current source, three runs each. Both used identical two-series 2,000-point data,
metadata evidence, native creation and export. Median complete CLI time fell
from 5.433 s to 4.467 s; task calls fell from four to two. Median returned UTF-8
text fell from 28,274 to 8,959 bytes. All six complete exported CSVs had the same
SHA-256 and current source/QA/delivery checks. Local active work was 3.468 s versus
3.525 s: this gain comes from removing process/answer round trips, not a faster
native renderer. Predetermined answers exclude actual model inference and token
accounting; no end-to-end model speedup percentage is inferred.

The ordinary skill entry decreased from 27,015 to 8,057 characters, with advanced
workflows moved to an on-demand reference. Character counts are not token usage.
The earlier Luna workbook was no longer present at its supplied Downloads path
when the original-workbook replay began; it was not reconstructed or substituted.
Synthetic native coverage verifies independent ranges, original-to-delivery
values, native constant stacking offsets, units and source revision review.

Reproduction, baseline source, requests, receipts and exact CSV hashes:
`.tmp_verify/recovery_20260918/`. Client follow-up measurements must record their
different source/task scope separately from this paired local experiment.


### Independent Luna workbook trial after the recovery changes

An explicitly requested fresh `gpt-5.6-luna` subagent used the original
`最新一批_FTIR_1-17.xlsx`: 17 curves, 7,469 points each. The first 278-second
phase stopped without output after invalid metadata answers and permission
retry. Its diagnosis of unsupported percent transmittance was incorrect; logs
showed declaration/evidence mismatches. Parent changes then added indexed,
batched rejection messages, FTIR metadata guidance, and unit spelling
consistency in the original-cell and downstream FTIR validators.

Continuation reused the same task, took 249 seconds and six resume attempts,
and delivered PDF/TIFF/editable VSZ. Total first-start-to-finish time was 807
seconds including parent investigation and repairs. Final local call: 30.127
seconds; cumulative local active calls: 47.870 seconds across 10 recorded
entries. This is an intervened diagnostic trial, not an unassisted matched
before/after model benchmark. It did not demonstrate second-scale end-to-end
plotting. External model token counts and inference durations remain unknown.

Independent parent verification compared every exported X/Y value with the
original workbook, retained all sample IDs and percent units, checked original
and current native hashes, and reviewed TIFF. The zero-valued final row causing
the terminal drops is present in the original and was retained. Detailed local
evidence: `.tmp_verify/recovery_20260918/luna-original-integrity.json` and
`luna-trial-metrics.json`; original agent summaries are retained separately.

## 2026-09-18: compact reviewed candidates and large-workbook processing

The same original 17-series FTIR workbook now returns an explicit source-backed
shared-X candidate in about 1 s. The caller reviews the cited original note,
rows, columns, quantities, units and samples, then sends the current question ID
and candidate ID. Optional pair indices choose a subset or order. Full mapping
and metadata declarations remain available locally; a missing or ambiguous note,
incomplete range, or unsuitable candidate still needs an explicit mapping answer.
This does not let the program choose scientific conditions without review.

Sequential public-CLI measurements used a saved pre-change source snapshot and
the same untouched original file. No tests or other benchmark tasks ran alongside
these final timings. Both conditions completed native creation, full QA and delivery.

| Local route | Complete times (s) | Median (s) | Answer bytes |
| --- | --- | --- | --- |
| Previous code, full mapping | 36.186, 32.825 | 34.505 | 47,640 |
| Current code, reviewed candidate | 19.047, 21.101 | 20.074 | 184 |

The median local reduction is 41.8% in this two-run comparison. One additional
current-code run using the old full mapping took 21.244 s, separating reduced
local processing from the shorter answer route. Both candidate trials used two
task calls. Predetermined decisions exclude external inference, transport and
human waiting. Bytes are not tokens, and this is not a universal speed guarantee.

Optimizations remove scalar/regex work on ordinary numeric cells, vectorize
numeric range diagnostics, share only byte-bound parser facts across identical
archive copies within one bounded operation, read each cited note sheet once per
validation, and share compact PDF drawing styles across QA checks. Every cache
hit rehashes actual file bytes; source/semantic validation and native audits remain.

All five runs retained all 17 × 7,469 original X/Y points exactly, numeric sample
IDs and percent units. Complete CSV SHA-256 and 1,417 × 1,299 TIFF pixels were
identical across all runs; the raw workbook SHA was unchanged. Current saved VSZ
hashes matched completed receipts, with current source/QA/delivery checks.
Scripts, source baseline, requests, receipts and the parent audit are retained
under `.tmp_verify/speed_20260918/`, especially `final-measurements.json`.

### Reused Luna diagnostic retest

The existing Luna agent retested from 14:35:04 to 14:38:26 +08:00 (202 s including
TIFF review). It reused earlier context and needed parent intervention, so this
is neither a fresh-client run nor an unassisted matched before/after benchmark.
Eight task-operation receipts record invalid start, valid start, blocked resume,
retry, blocked inspection, failed post-move retry, corrected start and completion;
readiness and help checks add separate calls. Do not count only the final task.

The initial JSON incorrectly included CLI-only `task_dir`. A generic error led
the agent to also remove valid `out`, causing a conflict with the existing user
delivery. After parent correction, the new task retained `out`, used CLI
`--task-dir`, and completed with one candidate reply. Its two local calls took
18.692 s of active work (about 20 s of shell wall time). The request validator now
names invalid and missing fields, explains CLI `--task-dir`, and preserves valid
`out` in its correction guidance. A targeted test covers that exact failure.

During the detour the agent moved the old user delivery despite instructions.
The parent restored it to its original Downloads location without overwriting
anything, verified all five pre/post file hashes, and matched the original CSV
and VSZ hashes against the prior integrity record. Source bytes were unchanged.
The retest's separate development CSV and TIFF pixels equal the original delivery.
See `luna-retest/original-delivery-restored.json` and the parent trial audit;
the agent's original summary is retained as historical, incomplete evidence.

## 2026-09-18: local preflight and direct correction feedback

The task boundary now normalizes a misplaced JSON `task_dir` into the transport
option when unambiguous, retaining valid `out`. Conflicting locations still fail.
Occupied output/workspace paths are checked before data planning. An explicit
question-bound new `out` continues the same task; it cannot redirect an uncertain
native creation. Original outputs are never moved to make a retry succeed.

CLI and MCP wire failures return bounded JSON-pointer constraints. Correctable
response failures also return the saved current question and next step, avoiding
an extra inspect/help round trip. Invalid wire answers leave the task unchanged. Existing
source/numeric/metadata validation still precedes native creation; original row
indices and invalid numeric counts remain visible for the caller's mapping decision.
When the caller's question ID still matches, feedback reuses that previously
returned evidence and sends only the question reference plus correction constraints.
Missing or stale bindings include the bounded current evidence for a fresh decision.

A sequential real-workbook CLI replay deliberately combined a misplaced task
location, occupied development output and a duplicate pair-index answer. Timings:

| Call | Local wall time (s) | Result |
| --- | --- | --- |
| Start with transport alias and occupied output | 0.340 | Alias normalized; output choice returned before planning |
| Choose new output in same task | 0.939 | Original FTIR mapping candidate returned |
| Invalid duplicate pair selection | 0.331 | Constraint and same-question reference returned; task bytes unchanged |
| Correct answer using the same reviewed candidate | 18.233 | Complete native creation, QA and delivery |

Total: 19.844 s for four calls, no inspect/help calls. This is a single local
fault-injection replay with predetermined corrections, not an end-to-end AI
comparison. Request/response bytes and all raw receipts are recorded separately.
Before same-question delta projection, an earlier replay took 20.994 s and its
bad-answer response was 7,725 UTF-8 bytes; the final response is 1,802 bytes. Paths
differ slightly between the two development runs. This measures returned text,
not external model tokens, and the timing difference is not a matched speed claim.
All 17 × 7,469 values match the prior independently audited original-data CSV,
TIFF pixels are identical, all five existing user-delivery hashes and original
workbook bytes are unchanged, and source/QA/delivery are current. Reproduction:
`.tmp_verify/communication_20260918/replay.py`; final evidence:
`real-workbook-compact/audit.json`; earlier full-question feedback: `real-workbook/audit.json`.
