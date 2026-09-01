# SciPlot Automation Control Contract

Status: R0 frozen design draft; not current runtime behavior.

This document freezes the proposed Automation Brief, local decision policy,
permissions, provider boundary, and future owner map. It does not add a
conductor, an AI intent route, a new request schema, or a new readiness state.
`README.md` remains the authority for current product behavior and
`docs/ARCHITECTURE.md` remains the authority for current module ownership.

## R0 baseline authority

The development-only hidden command is:

```text
skill/scripts/sciplot automation-baseline \
  --out .tmp_verify/r0_automation_baseline \
  --repetitions 3
```

It accepts only the fixed `.tmp_verify/r0_automation_baseline/` development
evidence root. It is not a public plotting entrypoint and does not create a
source-adjacent user delivery. The report is a closed v1 measurement contract
with these scenarios:

| Scenario | Current owner path measured | Expected automation state |
| --- | --- | --- |
| `ready_zero_ai` | certified explicit rule, cold `plan`, Autoplot, QA, exact-current delivery | `ready` |
| `scientific_confirmation` | controlled 75-confidence validated-envelope replay | `needs_human_confirmation` |
| `rule_repair` | in-memory stale-certification invocation preflight | `needs_rule_repair` |
| `selected_object_visual_edit` | one offline submit, proposal, manual accept, apply, and native Undo | `ready` |

The ready scenario compares only immutable FigurePlan facts: rule, selection
policy, source identity, plan identity, selected figure IDs, and ordered tasks.
Lifecycle outcomes are intentionally excluded from plan identity. The probe
reads the existing current and delivered VSZ files only to compare their hashes;
it does not mint artifact authority or replace the existing delivery gate. The
full tasks are compared only in memory; persisted evidence keeps `tasks_sha256`
and never the task values or source-derived sample order.

Measurement definitions are fixed as follows:

- `wall_time_ms` is one in-process scenario duration measured with a monotonic
  clock. Ready samples clear the inspection cache before the combined
  `plan -> autoplot` measurement; reuse inside that one operation remains real.
- `peak_python_memory_bytes` is the `tracemalloc` Python peak. Qt native memory,
  worker RSS, and operating-system cache effects are excluded.
- `raw_source_read_opens` counts read-mode `builtins.open` and `io.open` calls
  for the exact fixture path inside the measured operation. The initial hash,
  one post-ready-sample integrity hash per repetition, and final hash are
  excluded and reported as exactly `repetitions + 2` integrity reads; native-
  library I/O and child processes remain outside this instrumentation.
- During every measured operation, instrumented process-local Python path
  mutations outside its sample root and unapproved child-process launches are
  rejected before delegation. Ready also fingerprints the persistent source-
  parent tree before and after the timed `plan -> autoplot` operation; that
  safety scan is outside the latency/memory interval. Only the existing Veusz
  export/audit worker commands and the read-only `uname -p` platform query are
  allowed; the worker argv is bound to the current Python executable and
  repository cwd. Its base environment is exact; the two private terminal-
  source values are accepted only after validation by their existing owner.
  Output/error are fixed to pipes or `/dev/null`, extra inherited descriptors
  are closed, and caller-supplied streams are rejected. Existing local owner
  calls retain their read-only inherited stdin. This is a portable development
  guard, not an operating-system sandbox for native code.
- The repair replay wraps the actual stale-invocation owner call with the same
  exact-fixture read counter and a process-local `builtins.open`/`io.open`
  write-mode guard. Both counts must be zero; an attempted Python write raises
  before delegating to the real opener, so the probe fails without creating or
  modifying that file. The owner seam receives no source, output, or project
  argument; native-library and child-process writes remain outside this
  portable guard and are stated as a limitation rather than inferred from the
  source-read metric.
- `payload_components` records `{bytes, sha256}` for every independently
  canonicalized current-owner payload projection used for that scenario
  decision. Known machine-local filesystem roots and `.tmp_verify` locators are
  replaced with fixed placeholders before measurement, so a longer checkout or
  output locator cannot inflate the denominator. Veusz object and setting paths
  such as `/page/.../label` remain exact decision facts. The full decision byte
  count is the arithmetic sum of component bytes; there is no wrapper overhead
  or cross-component de-duplication.
- The scenario component sets are closed: ready uses `rule_show`,
  `plan_preview`, and `autoplot_result`; confirmation uses `semantic`,
  `source_package`, `mapping_package`, `render_request`, and `evaluation`;
  repair uses only `rule_show`; the post-apply selected-object `handoff_ready`
  decision uses `intent`, `base_revision`, `context`, visual-preview metadata,
  provider response, apply result, complete transaction history, and Undo
  evidence. Thus the visual denominator and Brief fixture describe the same
  terminal decision rather than mixing a pre-submit request with a completed
  transaction.
- Session bootstrap payloads (`doctor`, ready-rule catalog, and selected-rule
  show) are reported separately and excluded from every scenario denominator;
  they are measured once per run, not charged once per repetition. The ready
  scenario still includes its decision-time `rule_show` component explicitly.
- Visual-preview metadata excludes both `base64` and `data_base64`. Decoded PNG
  bytes are reported separately as `image_bytes` and are not part of the
  control-payload compression denominator.
- `provider_payload_bytes` and `provider_context_bytes` are sorted compact
  UTF-8 JSON byte counts of the actual offline provider request and its context.
- `image_bytes` is decoded PNG bytes, not base64 character count.
- `provider_requests` counts deterministic replay-provider invocations.
  `model_calls` counts production OpenAI adapter or SSE-client attempts; those
  routes are blocked during the benchmark and a passing report requires zero.
- Offline replay has no transport token usage. Input and output token counts are
  therefore `null` with basis `offline_replay_no_token_usage`, never estimated
  or reported as zero.
- A selected-object edit separately records submit-to-proposal and
  proposal-to-applied durations. The full multi-branch Assistant probe is not
  used as a single-edit latency sample.
- Before Veusz opens the isolated selected-object working copy, the source hash
  before and after copying and the copied-document hash must all match. The
  source and copy must still have that identity after the complete apply-plus-
  Undo cycle.

The current scientific-confirmation owner exposes a state and reason codes but
does not expose one minimal question payload. R0 records that as a baseline gap;
it does not claim that the future human-confirmation interaction already exists.
The session gate requires Doctor `status=ready` and at least the frozen 24 ready
rules, so a contracted-rule inventory regression cannot produce passing R0
evidence.
The report also records the tracked fixture hash before and after the complete
four-scenario run, while every ready sample directly checks the same raw source
bytes. An observed or blocked source mutation invalidates the evidence rather
than producing a passing report.
The closed validator checks report shape, internal relations, and the producer-
measured component manifests. It is not a standalone authenticity or tamper-
evidence mechanism: coordinated replacement of values and their hashes cannot
be detected without an external anchor. R1 compression gates must rerun the
producer against live current-owner objects and compare the Brief in that same
process; an archived R0 JSON is only a regression reference.

## Automation Brief v1

The future Brief is a pure projection of an already-created in-memory owner
result. It must not read a source, classify again, load a second catalog, write a
project, or persist a cache or receipt.

The exact top-level fields are:

```text
kind
version
phase
subject
decision
candidates
invocation
identities
provider
completion
```

The nested v1 fields and vocabularies are closed:

- `kind`: `sciplot_automation_brief`; `version`: `1`.
- `phase`: `preflight | planned | executed | selected_object`.
- `subject`: `kind`, `opaque_id`. The ID must not be a path, filename, source
  hash, project-directory name, or reversible encoding of any of those values.
- `decision`: `automation_state`, `next_action`, `decision_code`,
  `owner_reason_refs`, `question`, `maintenance_owner`.
- `candidates`: an ordered list containing only certified-ready `rule_id`,
  `semantic_family`, `default_template`, and `allowed_templates` values.
- `invocation`: `preview_operation`, `execute_operation`, `rule_id`,
  `selected_template`, `required_argument_names`; absent values are explicit
  `null`, not omitted fields.
- `identities`: only `rule_contract_sha256`, `request_sha256`,
  `figure_plan_sha256`, `document_revision`, and `render_sha256`.
- `provider`: `mode`, `outcome`, `call_budget`, `calls_used`.
- `completion`: `ready_to_use`, `qa_status`, `delivery_complete`,
  `artifact_count`.

`next_action` is one of:

```text
plan
execute
request_intent_selection
ask_human
handoff_rule_repair
request_selected_object_proposal
continue_manual_edit
handoff_ready
stop
```

`decision_code` expresses only the conductor classification:

```text
deterministic_route
intent_selection_required
human_confirmation_required
rule_repair_required
selected_object_edit_requested
input_stopped
provider_stopped
execution_stopped
integrity_stopped
ready_handoff
```

The provider outcome is orthogonal to the three scientific automation states:

```text
not_used
available
completed
unavailable
cancelled
timeout
transport_failed
output_rejected
```

A provider failure must not be relabeled `needs_rule_repair` or
`needs_human_confirmation`. Owner reasons remain exact references of the form
`{owner, code, detail_id}`. The conductor owns no copy of domain reason catalogs
and must not infer meaning from prefixes or parameterized reason strings.

## Canonical and size policy

- Canonical bytes use sorted keys, compact separators, UTF-8,
  `ensure_ascii=False`, and `allow_nan=False`.
- Every level rejects unknown fields, missing fields, unknown versions,
  booleans in numeric fields, NaN/Inf, and duplicate list members.
- The same in-memory facts produce byte-identical output. Timestamps, random
  IDs, cache identities, receipts, and provider prose are forbidden.
- The compact Brief is at most 8 KiB. Ready, scientific-confirmation, and visual
  scenarios must each be at least 70% smaller than the complete current payload
  set needed for the same decision:
  `brief_bytes / full_decision_payload_bytes <= 0.30`. The smaller repair
  payload has an evidence-based gate of at least 55% reduction plus an absolute
  1,280-byte cap: ratio `<= 0.45` and `brief_bytes <= 1280`. Raising the global
  cap cannot replace either reduction gate.
- R0 freezes a same-decision, complete-field feasibility fixture for the four
  scenarios at 985, 1,070, 1,122, and 1,032 canonical bytes against the path-
  normalized standard denominators 15,700, 4,877, 2,677, and 15,951 bytes. The
  ready and visual fixtures both represent terminal `handoff_ready`; the
  fixtures retain the two exact repair reasons and demonstrate that every
  frozen gate is mathematically reachable. They are design evidence, not an
  implemented R1 projector.
- Candidate count is at most 32, templates per candidate at most 8, owner reason
  references at most 8, and the one human question at most 320 UTF-8 bytes.
- A new field or vocabulary value requires a version bump; v1 has no extension
  bag.

## Local conductor decision table

The first matching row wins:

| Priority | Local fact | Decision and budget |
| ---: | --- | --- |
| 1 | Invalid payload/identity or contradictory evidence | `stop` or owner repair; 0 AI, 0 writes |
| 2 | Owner state is `needs_rule_repair` | `handoff_rule_repair`; preserve exact owner reason references |
| 3 | Owner state is `needs_human_confirmation` | `ask_human`; exactly one question, 0 AI |
| 4 | Explicit rule/template or one deterministic local match | `plan -> execute`; 0 AI |
| 5 | Scientific facts are unique and only ready-catalog intent selection is missing | At most one text call; accept only an allowed rule/template, then run local `plan` |
| 6 | User explicitly requests a current-object visual change | At most one visual call under current revision/capability/confirmation/Undo gates |
| 7 | Provider is absent, fails, times out, or is cancelled | Preserve the automation state, do not retry, continue manual/local path |
| 8 | Execution completed | `handoff_ready` only after exact-current, QA, manifest, and delivery hashes pass |

Plan lifecycle values such as `blocked`, input-not-found failures, and transport
failures are not additional automation states. A future conductor may project a
three-state value only when the current owning domain has produced one.

## Permission matrix

| Fact or action | Authority | AI permission |
| --- | --- | --- |
| Raw source, sample/column/unit/anchor identity | source and semantic owners, plus explicit human confirmation | no read or inference permission |
| Ready rules and templates | source-controlled catalog plus certification | select only from the supplied allowlist |
| Request and FigurePlan creation | current local owners | no direct creation or mutation authority |
| Execution, rendering, QA, export, and delivery | current local workflow/Studio owners | no direct invocation outside the conductor decision |
| Selected-object setting | setting catalog, current revision, and user acceptance | propose one typed `set_setting` batch only |
| Raw data, datasets, rule contract, request authority, VSZ code, QA/delivery evidence | their existing local owners | never modify |
| Final `ready` | exact-current VSZ, QA, manifest, plan, and delivery gates | no authority |
| Retry or fallback | local policy | no automatic retry, model switch, rule switch, or threshold relaxation |

## Provider and data-egress threat model

Provider input and output are untrusted for both loopback and remote modes.
`store=false` is a wire control for a supporting adapter, not proof that an
arbitrary provider retains no data.

Never outbound:

- raw bytes or arrays, workbook contents, absolute paths, filenames, hidden
  `.sciplot` contents, environment variables, secrets, API keys;
- complete manifests, requests, plans, diagnostic payloads, logs, VSZ source,
  rule source, QA evidence, or delivery evidence.

The text route receives only the exact Automation Brief whitelist. The visual
route is allowed only after an explicit user request and may receive the
exact-current PNG, selected-object identity, allowed settings, and necessary QA
delta. A PNG is itself sensitive because it can expose sample names, labels,
curve shapes, and annotations; the visual route must say so before remote use.

The current full plan includes an absolute source path, and the current
selected-object context derives `project_id` from a directory name. Neither may
be copied into the Brief or a provider payload. Source- or provider-sensitive
persisted material is limited to byte counts, call counts, timings, provider
ID/outcome, hashes, and closed reason references. The report also keeps fixed
non-sensitive state/action IDs, platform metadata, checks, and the artifact
locators defined below; prompts, images, model text, task/sample values, and
source or project paths are not retained. R0 report artifact self-locators are
the sole path exception: they match the fixed repository-relative
`.tmp_verify/r0_automation_baseline/automation_r0_<16-hex>/` pattern, contain no
username or source-derived name, and are never provider input. The development-
only R0 probe creates source-derived VSZ, PNG,
and history artifacts in one unique ephemeral work directory, hashes them for
the closed evidence record, and deletes that directory before writing the final
JSON and Markdown. A completed R0 evidence root therefore retains only those
two reports.

## Future owner and minimum-test map

These are planned owners, not current architecture modules:

| Stage | Proposed unique owner | Minimum focused evidence |
| --- | --- | --- |
| R1 Brief contract/projection | `automation_brief/contracts.py`, `model.py`, `projector.py` | closed fields/version/byte cap; canonical round-trip; all path/raw-array/secret canaries absent; injected owner object with source/classifier/network/write patched to fail |
| R2 pure decision | `conductor/decision.py` | table-driven priority coverage; zero-call ready; one question; repair stop; provider outcome never changes automation state |
| R2 execution seam | `conductor/run.py` | direct/conductor request, plan, task, artifact, and terminal evidence identity; cancellation and partial-failure recovery |
| R3 intent proposal | provider-neutral `intent_selection` contract | allowlisted rule/template/stop only; one-call hard budget; invalid/unavailable/cancelled output causes zero writes and no retry |
| R3/R4 outbound policy | `assistant_provider/outbound_policy.py` | text has no PNG/path/raw arrays; visual requires explicit user intent; loopback and remote outputs use identical validation |
| R4 host-side operation validation | current capability/operation owner | wrong type/range, no-op, duplicate, stale, and out-of-scope values all reject before `OperationMultiple` |

The existing CLI parser/dispatch family remains the only CLI composition path.
The existing Autoplot, Studio, Veusz, request, catalog, renderer, document,
cache, and evidence owners remain unique.

## Preconditions recorded by R0

1. Current `plan` serializes and discards its typed scientific snapshot;
   Autoplot classifies/resolves again. R2 needs an in-process typed snapshot
   seam. Reconstructing one from plan JSON or adding a cross-command cache is
   forbidden.
2. Current confirmation evidence has no minimal-question payload. R1/R2 must add
   and test exactly one bounded question before claiming that interaction.
3. Current selected-object adapter validation is stricter than the
   provider-neutral host apply path for range and no-op checks. R4 must move the
   shared validation into the host authority before expanding operations.
4. R1, R2, R3, and R4 are not authorized or implemented by this R0 contract.
