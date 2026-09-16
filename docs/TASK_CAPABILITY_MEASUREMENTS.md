# Task capability payload measurements

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
