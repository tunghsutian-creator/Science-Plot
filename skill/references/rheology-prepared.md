# AI-prepared HDPE/LDPE UDC rheology/TTS

Start with `skill/scripts/sciplot doctor --json` and
`skill/scripts/sciplot rheology capabilities --json`; reuse current session
readiness/contracts. AI owns data processing, calculations, scientific purposes
and the source-bound prepared numerical plan, including units, transforms and
series roles. The local program validates that plan and draws its supplied values
with governed templates. Its `plot` entry point must not analyze or refit data.

## Create and review

Use the advertised closed request and plan contracts. A request contains
`version:1`, absolute `prepared_plan` JSON path, and optional `out` and
`expected_contract_sha256`:

```bash
skill/scripts/sciplot rheology plot --request REQUEST.json --json
```

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
