# AI-prepared HDPE/LDPE UDC rheology/TTS

Start with `skill/scripts/sciplot doctor --json` and
`skill/scripts/sciplot rheology capabilities --json`; reuse current session
readiness/contracts. AI owns data processing, calculations, scientific purposes
and the source-bound prepared numerical plan, including units, transforms and
series roles. The local program validates that plan and draws its supplied values
with governed templates. Its `plot` entry point must not analyze or refit data.

## Create and review

Use `prepared_request_schema` for the closed request and `prepared_plan` for the
plan's enforced provenance schema, complete minimal example and scientific
disclosure guidance. `presentation.processed_plan` and `presentation.roles`
describe the figure/panel/series fields and supported roles. A request contains
`version:1`, absolute `prepared_plan` JSON path, and optional `out` and
`expected_contract_sha256`:

```bash
skill/scripts/sciplot rheology plot --request REQUEST.json --json
```

The plan requires `version:1`, `source_binding`, `transform_ledger` and `figures`.
`source_binding.sources` is a nonempty ordered array; each record contains exactly
an absolute original local `path` and its unchanged file-byte `sha256`. Bind all
inputs used for the prepared result. Put field/row selections, transformations
or an explicit declaration of none, exclusions and scientific limitations in the
nonempty `transform_ledger`. A structured ledger is recommended; existing
nonempty text/list disclosures remain supported. The program adds the plan-file
binding itself; do not invent a different source-binding or series-unit schema.

Declare final units in panel `x_label`/`y_label` and source/output units plus any
conversions in the ledger, per figure/series when needed. A real or imaginary
viscosity component is distinct from complex-viscosity magnitude. The caller
must supply the correctly defined final quantity with its derivation and unit
evidence. This plotting entry preserves those declarations and values; it does
not infer units, convert coordinates or verify the scientific calculation.

Omit `out` by default. The delivery belongs beside the **first bound source**;
an explicit destination may also be a new revision inside an existing
source-bound sibling suite. If that check fails, use the source-adjacent
destination; do not relabel or relocate source bindings to bypass it. If a plan
is structurally rejected, correct the named field using `prepared_plan` in the
live capabilities. Refresh `expected_contract_sha256` after reviewing a changed
contract, without changing already approved coordinates or scientific choices.

Creation replies are compact; complete native evidence remains at
`full_evidence_path`. Read that file for a missing detail instead of creating the
suite again. `rheology plot` and compatibility `rheology tts` accept `--full`.
The older combined `rheology tts` is retained for compatibility, not new-work
routing. Read `docs/RHEOLOGY_TTS.md` only for a specific scientific-plan or recovery
detail absent from the live contract and this route.

Measured/derived traces use points with guide lines, TTS observations use points,
and regression predictions use lines. Preserve user encodings and distinctions
among observations, fits, reference lines and bars. Do not suppress measured-point
markers or hardcode physical sizes to match a generic curve example.
The separated plan creates independent documents and retains fit diagnostics;
legacy combined documents remain supported. Review the returned export images and
current evidence before delivery. Launchers use the native Veusz editor. This
route does not claim the ordinary browser canvas or strict thermorheological
simplicity. Preserve raw inputs and all source-bound scientific limitations.

## Saved style corrections and exports

For an authorized template-style correction:

```bash
skill/scripts/sciplot rheology style-preview WORKSPACE --json
skill/scripts/sciplot rheology style-apply WORKSPACE --preview PREVIEW_JSON --json
```

Between those calls, review the candidate native export images and the returned
current-document/source/spec-bound preview. Existing user intent authorizes apply;
stale bindings require a fresh preview. Apply publishes those exact accepted
candidates as a bounded template-style migration, without arbitrary custom-style
input. Do not regenerate data or reapply an accepted edit for an export retry.

For exact saved re-export, use `rheology export WORKSPACE --json`. It reports style
deviations while preserving saved native edits. Completed or subsequently edited
suites use this route. Review final exports and deliver; do not append another
inspection/export chain to a successful result.

## Interrupted first creation

Follow the first failure's `repair` guidance. For `resume_prepared_creation`, run
the returned command with the same request:

```bash
skill/scripts/sciplot rheology plot --request REQUEST.json --resume --json
```

For `inspect_creation_evidence`, preserve the indicated request, workspace and
checkpoint, and inspect the original error; do not issue a blind resume. Guidance
validates evidence without saving/exporting or recovering by itself. Never delete
the workspace or recreate saved VSZ files. Resume rejects changed bindings,
uncertain native saves and unknown older partial workspaces.
