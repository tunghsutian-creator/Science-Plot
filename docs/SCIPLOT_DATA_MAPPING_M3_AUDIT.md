# SciPlot M3 Deterministic Data-Mapping Audit

Status: deterministic executor implemented and verified, 2026-07-17. This
audit covers the typed proposal, external confirmation, deterministic
execution, lineage, Studio integration, and delivery gates. It does not claim
that a real model/provider or the Canvas confirmation UI is complete.

## First-principles boundary

AI is allowed to interpret ambiguity and propose structure. It is not allowed
to mutate raw experimental files, run arbitrary code, authorize its own
proposal, choose hidden rows, rewrite VSZ text, or declare a figure ready.

The lifecycle is:

1. a provider or deterministic rule emits `DataMappingProposal` version 2;
2. SciPlot validates the closed schema, request hash, source paths, source
   hashes, headers, columns, units, and transformations;
3. preview executes in memory, writes nothing, and reveals no raw values;
4. a separate `DataMappingConfirmation` binds the exact proposal SHA,
   base-request SHA, source hashes, operator, and timestamp;
5. the deterministic executor writes an isolated candidate project
   atomically;
6. Studio or the normal run path verifies `execution.json` before consuming
   mapped data, deterministically reproduces the mapped CSV hashes, and rejects
   routing or lineage changes;
7. deterministic semantic preparation, VSZ generation, exact-current export,
   QA, and delivery proceed through the normal SciPlot lifecycle.

The proposal always serializes `requires_confirmation=true` and
`executable=false`. `created_at` and `confirmed_at` are required,
timezone-aware fields; omitting either is rejected so repeated loads cannot
change a confirmation hash. Every externally supplied transformation also
requires a stable `transformation_id`; parsing cannot silently mint a new UUID
and thereby change the proposal hash.

## Closed contract

Every source declares:

- a stable source ID;
- a POSIX path relative to one declared source root;
- the exact SHA-256 digest;
- optional workbook sheet;
- explicit header row or headerless state;
- delimiter and decimal convention.

Every mapped column declares:

- source ID and zero-based source-column index;
- expected header when a header exists;
- output column name;
- scientific role such as x, y, z, sample, replicate, error, or metadata;
- whether the column is required.

All textual contract fields are actual JSON strings. Booleans and numbers are
not silently converted into IDs, paths, labels, units, options, or numeric
comparison operands.

The request patch is limited to scientific routing fields: recipe, rule,
template, x/y/z metric, series order, and replicate mode. It cannot carry
arbitrary render styles or executable content.

The only executable transformations are:

- `rename`
- `select`
- `exclude`
- `drop_missing`
- `sort`
- `unit_convert`
- `derive_ratio`
- `normalize_baseline`
- `aggregate_replicates`

Python, shell, command, script, expression, eval, unknown keys, and path
traversal are rejected before any write.

Declared comma-decimal numeric columns are normalized without changing text
roles or delimiter structure. Sorting uses numeric order only when every
non-missing value in the selected column is numeric; otherwise the original
text semantics are preserved.

Before confirmation, every mapped source must still contain rows, retain at
least one explicitly declared x, y, z, or value role after all
transformations, and expose at least one finite value in those numeric roles.
Category-only, empty, nonnumeric, or infinite plotting outputs are rejected at
the mapping boundary rather than delegated to a later renderer.

## Transaction package

Successful execution creates one isolated project directory containing:

```text
PROJECT/
  base_request.json
  proposal.json
  confirmation.json
  preview.json
  execution.json
  request_seed.json
  plot_request.json
  transform_ledger.json
  superseded_base_transform_ledger.json  # when the base branch had lineage
  data/
    ...
```

`request_seed.json` is immutable and hash-verified. `plot_request.json` is the
standard mutable Studio entrypoint, so later Studio metadata enrichment does
not invalidate the original transaction. The source project's request and
exact-current VSZ are never overwritten.

`base_request.json` preserves the exact request bytes whose SHA-256 digest was
confirmed by the proposal and receipt. It cryptographically anchors raw-input
authority and the superseded transform ledger inside the isolated
transaction, rather than trusting hashes stored only in `execution.json`.

Before consumption, SciPlot also verifies canonical transaction paths,
replays the confirmed transforms from the unchanged sources, and rejects
changes to output bytes or metadata, `request_patch`, `effective_input`,
confirmation metadata, or active/superseded transform ledgers. A modified
execution manifest therefore cannot redirect plotting to unconfirmed data.
The verifier also rejects coordinated edits in which an attacker changes the
request seed or either ledger and then updates all adjacent manifest hashes:
those artifacts must still reproduce the confirmed base request and proposal.

Execution writes to a temporary sibling and uses one atomic rename only after
all outputs, hashes, receipts, ledger, and requests are complete. A repeated
identical execution reuses the verified result. Injected failure during a
multi-output write leaves neither a final package nor a temporary residue.

## Lineage model

A mapping proposal starts a new derivation from its own explicit source
hashes. Therefore an old branch's active transform steps cannot be placed
before the new mapping step merely because the base request already had a
ledger.

SciPlot now:

- hash-preserves the old ledger as
  `superseded_base_transform_ledger.json`;
- starts the new active ledger with
  `execute_confirmed_data_mapping_proposal`;
- appends newly executed semantic preparation after mapping;
- removes false identity steps when a real transformation exists;
- verifies mapped outputs, immutable request seed, superseded ledger, and raw
  source hashes before every consumption.

The resulting order is causal, for example:

```text
confirmed FTIR mapping
  -> reformat and order FTIR spectra
  -> native VSZ
  -> exact-current PDF/TIFF
```

## No-silent-omission gate

Artifact completeness alone is insufficient. Studio also records
`sciplot_data_mapping_series_coverage` and blocks VSZ generation unless every
confirmed mapped sample label appears in the prepared series and the minimum
series count is met.

This gate found a real defect during acceptance: Agilent samples named `8` and
`9` were initially parsed as numeric curve points after a unit row. The shared
reader now:

- preserves numeric-looking sample IDs as legend labels;
- preserves labels such as `PA` even when their spelling resembles the
  following `Pa` unit;
- recognizes the structured unit/sample metadata prefix;
- excludes both metadata rows from numeric curve values;
- rejects any later loss of a confirmed mapped series.

## Public entrypoints

```bash
skill/scripts/sciplot mapping preview PROPOSAL \
  --source-root RAW_DIR --request REQUEST --json

skill/scripts/sciplot mapping confirm PROPOSAL \
  --source-root RAW_DIR --request REQUEST \
  --by OPERATOR --out CONFIRMATION --json

skill/scripts/sciplot mapping execute PROPOSAL \
  --confirmation CONFIRMATION \
  --source-root RAW_DIR --request REQUEST \
  --out OUTPUT_ROOT --json

skill/scripts/sciplot mapping show EXECUTION_OR_PROJECT --json
```

The resulting project uses the ordinary command:

```bash
skill/scripts/sciplot studio MAPPED_PROJECT \
  --export pdf,tiff_300 --json
```

## Verification evidence

Synthetic adversarial probe:

- `.tmp_verify/m3_data_mapping_probe_v18/`
- 50/50 checks passed;
- covers schema round-trip, stable timestamps, no self-authorization, path
  confinement, stable transformation identity, closed transformation fields,
  zero-write preview, no raw preview values, exact receipt binding,
  forged/stale/tampered rejection, explicit exclusion, unit conversion, ratio,
  normalization, raw immutability, atomic completeness, standard project
  entrypoint, active and superseded lineage, idempotency, mutable candidate
  versus immutable seed, output/seed/active/superseded-ledger tamper
  rejection, manifest request and input redirection rejection, deterministic
  output replay, strict text and numeric-comparator types, confirmed
  base-request snapshots, coordinated seed/manifest tamper rejection,
  coordinated active/archived-lineage tamper rejection, replicate
  aggregation, comma-decimal normalization with numeric sorting, injected
  partial failure, category-only/empty/nonnumeric-output rejection, semantic
  recovery, numeric and unit-like sample labels, metadata stripping without
  dropping ordinary leading ones, case- and Unicode-normalization-safe
  output-name collision prevention, immutable raw authority/proposal
  identity, and mapped-series coverage.

Full runtime gate:

- `.tmp_verify/m3_mapping_runtime_smoke_v12/runtime_smoke_vc5b6nrh/`
- runtime smoke version 13 passed 30/30 top-level checks;
- includes the 50/50 mapping probe and a complete synthetic mapped-project
  Studio lifecycle. This fixture is a runtime change gate, not real-data
  evidence.

Authorized-real-data lifecycle:

- `.tmp_verify/m3_real_mapping_v9/projects/real-ftir-headerless-v1/`
  - registered headerless FTIR CSV;
  - 480 mapped rows, one expected and one actual series;
  - active lineage is mapping then FTIR semantic preparation;
  - artifact QA passed, publication QA passed, delivery complete,
    `ready_to_use=true`.
- `.tmp_verify/m3_real_mapping_v9/projects/real-gpc-slice-table-v1/`
  - two registered Agilent GPC/SEC workbooks;
  - explicit `Slice Table`, `RT (mins)`, and `RI` selection;
  - 544 and 496 mapped rows;
  - expected labels `[8, 9]` exactly match actual labels `[8, 9]`;
  - active lineage is mapping then chromatogram extraction;
  - artifact QA passed, publication QA passed, delivery complete,
    `ready_to_use=true`.

The sources retain their registered SHA-256 values before and after execution.
The final figures were also inspected visually; the numeric-label artifact was
removed and both GPC curves remain present.

The ordinary `run` route was also exercised on the mapped FTIR project. It
retained mapping then FTIR semantic-preparation lineage, passed artifact and
publication QA, and produced a complete delivery package.

Packaged-code gate:

- `/private/tmp/sciplot-m3-mapping-wheel-final6-20260717/sciplot_core-0.1.0-py3-none-any.whl`
- SHA-256:
  `770f1cca453c87bc78ce2998bc68140c72e0c78e6dee9ea879b7e7f55483dbef`;
- isolated installation passes `pip check`;
- importing `sciplot_core` and `sciplot_core.data_mapping` from the wheel does
  not load PyQt or Veusz;
- the wheel-installed CLI independently passes the same 50/50 mapping probe.

## Honest limitations

- The acceptance receipts identify
  `noninteractive_acceptance_operator`. They validate external-receipt
  mechanics but are not user clicks and do not count toward required human
  sessions.
- No real model/provider is connected. The proposals used typed structured
  payloads and do not prove model interpretation quality.
- The Canvas Assistant does not yet show proposal, confirmation, progress, or
  cancellation UI for data mapping.
- `--by` records an operator assertion; authenticated identity and consent
  belong to the future local provider/UI boundary.
- The executor intentionally supports a narrow transformation language. New
  scientific transformations require a schema addition, deterministic
  implementation, fixture, adversarial probe, and authorized-real-data
  acceptance.
- This work proves lifecycle success and exact-current publication QA for the
  two acceptance cases. It is not a general journal-compliance claim.

## Next M3 work

1. Define the provider-neutral request/response envelope and cancellation
   protocol.
2. Show `DataMappingProposal` preview and confirmation in the existing
   Assistant Inspector tab.
3. Require a real user action to issue a production confirmation receipt.
4. Run the six canonical natural-language Canvas tasks and real mapping tasks.
5. Promote repeated accepted mappings into deterministic material rules.
