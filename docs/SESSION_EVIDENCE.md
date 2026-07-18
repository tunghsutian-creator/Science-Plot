# SciPlot Session Evidence Contract

> Legacy compatibility contract. Version 1 preserves the former Canvas-based
> M3/M6 counting and reviewed-promotion replay format, but its Canvas cutover,
> fifteen-session quota, and required Composition round are cancelled. It is
> not the M6.1 Veusz-first daily-use acceptance gate. Existing ledgers remain
> readable and verifiable; new daily-use work must not be forced into this
> historical quota.

Version 1 was the counting authority for the former M3 production-model round
and M6 Canvas cutover. No run performed before preregistration can be promoted
into either legacy gate.

The contract has three events:

1. `preregistered` binds the natural task, explicit source hashes, project
   baseline, owner, lane, scope, entry route, clean Git commit, frozen
   wheel/package hash, validated-envelope registry, Veusz runtime identity,
   provider/model when applicable, expected evidence, and the operation-journal
   prefix;
2. `reopen_witnessed` is recorded only after the owner really closes and
   reopens the final Canvas or Composition Board. SciPlot replays the current
   session/model, final revision, exact-current VSZ hash, journal suffix,
   PDF/TIFF pair, QA state, and any review or mapping authority;
3. `completed` re-verifies unchanged sources, build identity, witnessed
   authority, passing final manifest, QA, PDF/TIFF hashes, editable VSZ parity,
   delivery, fallbacks, elapsed active time, and the owner outcome.

The JSONL ledger is hash-chained and has a companion `.head.json` checkpoint.
This detects accidental payload edits, reordering, middle deletion, ordinary
tail truncation, and replacement. It is not a signature, remote timestamp, or
identity provider. A person with write access can rewrite the ledger and its
checkpoint together. The owner identity and the fact that a GUI was physically
reopened are explicit attestations; the program binds the files observed at
that moment. Every append first writes and fsyncs a `.pending.json` transaction.
While that file exists, status and further appends fail closed. `sessions
recover` completes only one of the three provable interrupted states
(pending-only, appended-tail, or completed-head) and refuses every mismatch.

Use one explicit central ledger for every session in a formal M3 evaluation
round or M6 qualification round. Per-project defaults are convenient for
isolated diagnostics but cannot produce one aggregate dossier.

## Closed vocabulary

Acceptance lanes:

- `rheology_dma_torque`
- `spectroscopy_scattering_chromatography`
- `thermal_analysis`
- `mechanical_categorical_swelling`
- `scalar_review_composition`

Scopes:

- `m3_live_model_scored`
- `m6_discovery`
- `m6_qualification`
- `formal_contract_probe`
- `synthetic_probe`

`formal_contract_probe` exists only to prove the complete clean-checkout,
frozen-wheel, installed-CLI, runtime-identity, preregistration, reopen, and
completion path with a synthetic fixture. It requires the same clean commit,
explicit `round_id`, verified wheel, repository, and Veusz runtime as a formal
round, but it is deliberately ineligible for M3 or M6 and cannot be promoted
into either count. Ordinary `synthetic_probe` does not require a frozen build.

Source classes:

- `owner_authorized_real`
- `public_authorized_real`
- `synthetic_contract_fixture`

Entry routes:

- `studio`
- `canvas`
- `compose`
- `autoplot`
- `one_step`
- `mapped_candidate_canvas`
- `advanced_editor`
- `cli_run`

Expected evidence IDs:

- `canvas_lifecycle`
- `provider_disabled`
- `ai_operation`
- `cancellation_rollback`
- `data_mapping`
- `review_sidecar`
- `review_promotion`
- `composition_lifecycle`

M3 canonical tasks:

- `axis_format`
- `multi_series`
- `spatial_legend`
- `review_promotion`
- `qa_layout_repair`
- `cancellation_rollback`

Fallback classes:

- `p0_integrity`
- `p1_ordinary`
- `p2_low_frequency`
- `p3_distribution`

P0 and P1 cannot complete as `pass`. P2 can remain as an honest low-frequency
outcome, but any fallback or Advanced Editor use prevents that session from
qualifying for the final M6 fifteen.

## Owner workflow

Use explicit raw/source paths. Do not pass the mutable SciPlot project root as
the source directory, and do not place the evidence ledger inside a directory
whose tree hash is being treated as raw-source authority.

Freeze the exact clean committed runtime before a formal round:

```bash
skill/scripts/sciplot sessions freeze-build \
  --out /absolute/path/to/frozen_builds \
  --repo /absolute/path/to/clean/sciplot-checkout \
  --veusz-root /absolute/path/to/veusz-runtime \
  --json
```

The command builds a wheel without dependency resolution, verifies every
wheel `RECORD` member, and requires the active `sciplot_core`, `sciplot_gui`,
and `sciplot_recipes` bytes to match the wheel exactly. The preregistration
also binds the validated-envelope registry plus the active Veusz, PyQt/linked
Qt, Python, platform, and dependency fingerprints. Use the wheel reported by
`frozen_build.json`; an arbitrary ZIP or stale wheel is rejected. The wrapper
supplies its source and runtime roots automatically. A normally installed
wheel must pass explicit `--repo` and `--veusz-root` paths so no checkout or
renderer location is inferred from `site-packages`.

Before doing the declared work:

```bash
skill/scripts/sciplot sessions preregister PROJECT \
  --ledger /absolute/path/to/m6_discovery_2026_07.jsonl \
  --source RAW_SOURCE \
  --lane spectroscopy_scattering_chromatography \
  --scope m6_discovery \
  --source-class owner_authorized_real \
  --task "Create and refine the cross-sample FTIR comparison" \
  --round-id m6_discovery_2026_07 \
  --owner dongxutian \
  --entry-route canvas \
  --build-artifact /absolute/path/to/frozen-sciplot.whl \
  --repo /absolute/path/to/clean/sciplot-checkout \
  --veusz-root /absolute/path/to/veusz-runtime \
  --expected canvas_lifecycle \
  --expected provider_disabled \
  --journal PROJECT/.sciplot_canvas/operation_journal.jsonl \
  --json
```

For a formal round, also pass one shared absolute `--ledger` path to every
preregistration. The per-project default is
`PROJECT/.sciplot_evidence/session_evidence.jsonl`. Formal scopes reject a
missing `--round-id`, a dirty or uncommitted worktree, and synthetic source
class. The non-counting `formal_contract_probe` accepts only the synthetic
source class while still enforcing the clean frozen-build contract.

When a provider-disabled session is recertifying an approved reviewed-promotion
candidate, preregistration must additionally bind all three identities and one
or more lane-specific behavior assertions before work begins:

```bash
  --promotion-candidate-id CANDIDATE_SHA256 \
  --promotion-decision-sha256 DECISION_SHA256 \
  --promotion-plan-sha256 PLAN_SHA256 \
  --promotion-assertion-id ASSERTION_SHA256
```

The identity fields and assertion list are all-or-none, formal-real-only, and
cannot be attached retroactively. Repeat `--promotion-assertion-id` when a
lane has multiple assertions. Promotion verification requires the sorted,
exact assertion set declared for that lane and rejects an otherwise successful
session from the same lane or commit when the binding is absent or the
final manifest does not contain the complete canonical candidate. Canvas
candidates additionally require one assertion per canonical operation and
must reproduce each setting or widget effect in the reopened VSZ. Mapping
candidates require a separate assertion that replays the witnessed proposal,
mapped outputs, transformation ledger, and final plotted source lineage;
copying the canonical JSON into a manifest is insufficient. Generic health
fields do not qualify as promotion assertions.

Every session with this `promotion_binding` is verification-only and
explicitly non-voting. `learning collect` records
`promotion_verification_session_non_voting` and does not turn its mapping or
Canvas activity into a new observation. Verification evidence therefore
cannot recursively manufacture promotion evidence.

For a mapping-candidate recertification, preregister both
`--expected provider_disabled` and `--expected data_mapping`, but do not pass
`--provider` or `--model`. The mapping execution still records which provider
originally proposed the mapping; that historical identity does not mean the
recertification runtime is connected to a provider. The reopened journal must
prove provider-disabled state and contain no Assistant request, proposal,
handoff, commit, or rollback activity. Completion accepts the mapping only
after the exact execution and final source lineage are independently replayed.

After completion, obtain the exact facts for the externally signed
verification receipt with:

```bash
skill/scripts/sciplot learning session-binding \
  /absolute/path/to/session_evidence.jsonl SESSION_ID --json
```

The binding covers the ledger byte prefix through completion, the three event
hashes, and current authority artifact hashes. Use the returned canonical path
and fields unchanged; path aliases are rejected and cannot duplicate one
session. SciPlot computes these powerless facts but never creates the receipt,
private key, or signature.

Perform the task through SciPlot, save the exact-current VSZ, export the
canonical PDF and 300 dpi TIFF, and let the normal QA/delivery path finish.
Then close the Canvas, reopen that project yourself, inspect the reopened
figure, and record the witness:

```bash
skill/scripts/sciplot sessions witness \
  /absolute/path/to/m6_discovery_2026_07.jsonl SESSION_ID \
  --owner dongxutian \
  --journal PROJECT/.sciplot_canvas/operation_journal.jsonl \
  --canvas-session PROJECT/.sciplot_canvas/canvas_session.json \
  --document PROJECT/studio/document.vsz \
  --json
```

Add `--review PROJECT/.sciplot_canvas/review_annotations.json` when review
evidence was preregistered. Add `--mapping-execution .../execution.json` for a
confirmed mapping handoff. For a `data_mapping` session, preregister the exact
mapping `source_root` directory as `--source`, not only one member file: the
directory inventory is the first transform input and every proposal source
hash must equal that inventory. The final transform ledger must begin with the
exact confirmed mapping step and end at the plotted data snapshot. Auto and
explicit-recipe routes record their processed source; a direct multi-table
mapping records every concrete mapped table. If the final transform has
multiple outputs, the plotted snapshot inventory must equal that complete
terminal set, so a directory alias or one selected member cannot hide silent
omission. Independently, every rendered Veusz curve, categorical group, or
scalar field records the source file's canonical path and SHA-256. Completion
captures both the exact specifications and exact-current VSZ files into
private read-only snapshots, then reopens only those bytes. It quantizes the
specification expectation once to Veusz's persisted `.6e` token and compares
the reopened value exactly; extra precision in a hand-edited VSZ is not
rounded away. Every expected unit must retain a real visible line, marker,
fill, native boxplot, or scalar-image channel, the categorical boxplot
inventory must be exact, and unapproved visible data plotters are rejected.
Independently, the verifier replays the exact terminal tables through the
renderer's data-selection and transform semantics and requires those derived
units, the specification, and the reopened VSZ to agree. Terminal tables are
captured through regular-file descriptors with `O_NOFOLLOW`; replay consumes
only private read-only copies, maps their provenance back to the original
canonical path/SHA-256, and rechecks the original identity before returning.
The comparison binds stable series name, visible label, x/y dataset identity,
and order. The reopened document must also expose the exact x/y axis labels,
directions, numeric or categorical mode, linear or logarithmic scale, bounds,
tick formats, major and minor ticks, tick visibility, text sizes, line and
tick dimensions, legend keys, direct-label text/position/alignment/size/color/
background/border/order, complete visible-label inventory,
categorical text dataset, category-axis labels, and XY/boxplot order. Scalar
fields additionally bind the independently derived z range, color scale and
ticks, a custom colormap with at least two distinct fully opaque colors,
inversion, field mapping/draw mode, colorbar text,
line and tick dimensions, and contour inventories to the reopened image,
custom colormap definition, colorbar, and contour widgets. Source-evidenced
automatic renders use a closed shape inventory: only the exact page
background, bounded source-bound reference bands, exact native reference lines,
and an optional highly transparent local colorbar background are allowed.
Reference bands use logarithmic geometry on logarithmic axes; reference lines
bind point-to-point geometry, width, style, color, transparency, and visibility.
Unmanaged rect, ellipse, line, polygon, image-file, or SVG overlays fail closed.
External
requests cannot self-declare that their source is already preprocessed, and a
manifest cannot self-attest its own terminal request. The verifier rebuilds a
closed request from the confirmed authoritative request and private terminal
table snapshots, then treats any manifest projection only as a declaration
that must match. An explicit split policy is reproduced into the exact panel
plan and per-panel series selection. Unconfirmed automatic splitting and
multi-metric bundles without an independently persisted panel plan cannot
produce formal source evidence. Two unit-like metadata rows are ambiguous and
stop rather than guessing sample labels. Duplicate display labels stop before
label-based selection or split routing; unknown or fully hidden selections
stop instead of silently restoring all curves. The verifier then recomputes
coverage: every
terminal plotted snapshot must contribute to at least one rendered unit, no
rendered unit may cite a source outside that terminal inventory, and each
output of a multi-source mapping must contribute.
A display label or total series count cannot satisfy this test, so
case-insensitive aliases, an injected table, one non-plottable table, and a
data-edited stale VSZ all fail closed; coordinated request/spec/VSZ forgery,
axis or series relabeling, reordered series, arbitrary visible text, hidden
marks, missing boxes, changed scalar color semantics, extra plotters,
split-plan tampering, and file-swap races also fail.
Style-only VSZ edits remain valid. A
deterministic transform of one mapped output may use the explicit
`transitive_single_output` result, while its transform ledger and terminal
snapshot remain mandatory. Every ledger replay reopens the bound run manifest
and rederives this source lineage instead of trusting the stored completion
object. For native composition, use `--composition .../composition.json`
instead of `--canvas-session` and `--document`.

Do not edit the witnessed authority. Complete it against the ready Studio
manifest or composition delivery manifest:

```bash
skill/scripts/sciplot sessions complete \
  /absolute/path/to/m6_discovery_2026_07.jsonl SESSION_ID \
  --owner dongxutian \
  --outcome pass \
  --active-seconds 420 \
  --manifest PROJECT/runs/studio_001/manifest.json \
  --json
```

Use `--outcome needs_fix` or `--outcome abandoned` with at least one
`--failure "..."` when the task does not finish. Record every fallback as, for
example, `--fallback
p2_low_frequency:used an unsupported low-frequency Veusz property`. M3
planning attempts use `--model-score correct|incorrect`; the two cancellation
attempts use `not_applicable`.

Inspect aggregate truth with:

```bash
skill/scripts/sciplot sessions status \
  /absolute/path/to/m6_discovery_2026_07.jsonl \
  --require integrity \
  --json
```

Top-level `status=passed` means the ledger and checkpoint are internally
consistent. It does not mean M3 or M6 passed. Those claims exist only at
`m3.gate_passed` and `m6.gate_passed`. Automation must use `--require m3` or
`--require m6`; the command then exits nonzero until that exact gate passes.
Print the machine-readable closed enums and aggregate contract with
`skill/scripts/sciplot sessions schema --json`.

If status reports an interrupted append, do not delete or edit any companion
file. Run:

```bash
skill/scripts/sciplot sessions recover \
  /absolute/path/to/m6_discovery_2026_07.jsonl \
  --json
```

Recovery succeeds only when the pending candidate, JSONL tail, and head prove
one unambiguous append state.

## Counting rules

- One preregistered session counts at most once.
- A duplicate natural task on the same source evidence is rejected. Reusing a
  source can count only for a genuinely different natural task.
- M3 accepts exactly attempts 1 and 2 for each provider/model/canonical task.
  The five planning tasks need 9 of 10 correct first proposals, at least one
  success per task, and all ten safe lifecycles. Both cancellation attempts
  must restore the exact baseline, giving 12 of 12 authority-safe attempts.
- Attempts from different `round_id`, provider/model identities, or frozen
  build identities are reported separately and can never be combined into a
  passing M3 round.
- `m6_discovery` is diagnostic and never counts toward the final fifteen.
- `m6_qualification` requires owner/public authorized real source evidence,
  positive active time, unchanged sources and frozen build, an actual reopen
  witness, final ready manifest, no fallback, and no Advanced Editor use.
- All fifteen must bind one candidate identity: Git commit, frozen artifact
  hash, registry hash, and Veusz runtime commit. Sessions from different
  `round_id` values are never combined.
- M6 is one fixed cohort of exactly fifteen: exactly three sessions in every
  lane, one provider-disabled pass in every lane, three AI-operation passes
  across three lanes, one confirmed mapping, review-sidecar plus promotion
  evidence, and one native composition. Overfilled, mixed-candidate, and
  cross-round collections do not pass.
- Synthetic probes, copied artifacts, failed/abandoned attempts, agent-only
  review, discovery sessions, undone/rolled-back AI edits, and unrecorded
  external-editor use never qualify.

The source-controlled adversarial gate is:

```bash
skill/scripts/sciplot session-evidence-probe \
  --out .tmp_verify/session_evidence \
  --json
```

It uses explicitly synthetic source data and never counts as a real session.
Its positive paths nevertheless create real Veusz VSZ/PDF/300 dpi TIFF
artifacts and run production QA and delivery; fake artifact bytes appear only
in rejection tests.
