# SciPlot Deterministic Readiness M5 Audit

Status: implemented M5 readiness baseline, 2026-07-17. This document records
the authority boundary for deterministic `ready_to_use=true`. It does not
declare M5's learning/promotion loop complete and does not count as M6 human
daily-use evidence.

## Decision

`ready_to_use` is a host-side conclusion, not a field that an AI provider,
request, old manifest, or renderer can assert.

A new run is ready only when all of these conditions hold:

1. the selected rule has a source-controlled validated envelope;
2. the current full rule contract equals the accepted contract;
3. the presented semantic/render payload equals the accepted semantic
   contract;
4. the actual runtime render request matches the versioned policy bound into
   that rule certificate;
5. source, mapping, experiment type, semantic family, confidence, and package
   versions agree;
6. high-confidence automatic recognition or an explicit host-side
   confirmation admits the input;
7. structured QA is `passed`, not `unknown`;
8. delivery is complete; and
9. one-step and autoplot state agree.

Any failed contract or QA gate returns `needs_rule_repair`. A supported
medium-confidence match without explicit confirmation returns
`needs_human_confirmation`.

## Contract authority

`src/sciplot_core/validated_envelopes.json` is the portable, source-controlled
certificate registry. It stores hashes and bounded evidence metadata, not
local fixture or manifest paths.

Each full rule contract binds:

- the semantic family, recipe, template, axes, units, analyses, metrics,
  render options, recommendation, readiness, and priority;
- keywords, path keywords, column aliases, vendor models, and experiment
  families used for automatic recognition; and
- the versioned ready-rule matcher policy; and
- a versioned runtime-request policy that requires the automatic route, the
  exact certified template, canonical PDF/TIFF, an empty split policy, and a
  closed presentation-only override set.

Each envelope separately records the accepted semantic-contract hash. This
prevents a payload with the right `rule_id` but modified axis, template, unit,
analysis, or render settings from borrowing the rule's certificate.

The request policy separately binds what this run actually asked the renderer
to do. Figure size, palette, stroke, marker, legend, and other closed
presentation fields may vary. Axis domains/scales/labels, data selection or
transforms, fits, scientific annotations, changed templates, direct recipes,
and split policies cannot borrow automatic ready authority; they stop for
confirmation or repair.

The registry parser is closed and rejects unknown fields, duplicate rule IDs,
false real-data claims, unsupported authorization, missing fixture-tree
hashes, incomplete acceptance checks, inconsistent coverage counts, Boolean
version impostors, and unknown future acceptance versions. Choosing a visual
template cannot serve as scientific-semantic confirmation.

## Evidence baseline

The current registry certifies all 23 ready rules against the 2026-07-17
version-3 acceptance run:

- 23/23 complete Studio lifecycles;
- 23/23 authorized real-data evidence rows;
- 23/23 current full rule-contract hashes;
- 23/23 current semantic-contract hashes;
- 23/23 exact VSZ reopen/export, manual-edit preservation, canonical PDF/TIFF,
  QA, delivery, provenance, and physical-size checks;
- 3/3 generated contact sheets explicitly inspected and passed; and
- 0 instrument-shaped evidence gaps.

Evidence strength remains visible:

- 13 rules have registered fixture, upstream source, and source/output units;
- 2 rules have registered fixture and source hashes but canonical units only;
- 8 rules use computed, unregistered fixture hashes and retain that limitation.

These tiers do not change lifecycle success, but they must not be flattened
into equivalent provenance strength.

## Runtime gates

`one_step_status.json`, the manifest's `one_step` block, and
`autoplot_summary.json` persist the validated-envelope evaluation. Autoplot
requires the complete evaluation kind/version, `inside_validated_envelope`,
`contract_current=true`, passed QA, complete delivery, and matching reported
and persisted states.

Legacy projects remain readable, but a legacy one-step or autoplot artifact
without a current envelope cannot be promoted to ready. It must be rerun under
the current deterministic pipeline.

AI-provided `ready_to_use`, stale registry entries, same-rule semantic
tampering, source/mapping identity mismatches, invalid or Boolean package
versions, incomplete evaluations, non-Boolean delivery completion, low
confidence, unknown QA, and reported/persisted state conflicts are adversarial
probe cases. A copied valid evaluation relabeled as another rule is also
rejected by rebinding it to the current rule and source registry. A copied
evaluation paired with a different render request is rejected by the persisted
request-contract hash.

## Operator commands

Inspect the installed certificate:

```bash
skill/scripts/sciplot readiness status --json
```

After changing a ready rule or its recognition contract, run the complete
authorized real-data acceptance, inspect every contact sheet, record the
explicit visual decision, then build a candidate registry:

```bash
skill/scripts/sciplot acceptance rules \
  --out outputs/acceptance \
  --name CURRENT_RULE_CONTRACTS \
  --json

skill/scripts/sciplot readiness certify \
  outputs/acceptance/CURRENT_RULE_CONTRACTS/acceptance_summary.json \
  --out candidate_validated_envelopes.json \
  --json
```

The candidate must pass `readiness status --registry`, the readiness probe,
doctor, runtime smoke, and an isolated wheel install before replacing the
source registry.

## Verification

The implemented baseline passes:

- readiness adversarial probe: 29/29 at
  `.tmp_verify/readiness_m5/request_policy_binding_final/readiness_probe_ty8ees6a/readiness_probe.json`;
- current authorized real-data acceptance: 23/23 at
  `.tmp_verify/acceptance_m5/readiness_contract_v3_request_policy/acceptance_summary.json`,
  with all three contact sheets explicitly inspected;
- representative real FTIR autoplot: `ready_to_use=true`, no AI handoff;
- doctor: `status=ready`, 23/23 current envelopes; and
- runtime smoke version 18: 34/34 at
  `.tmp_verify/runtime_smoke_m5/request_policy_binding_final/runtime_smoke_o5g9wbh7/runtime_smoke.json`.

The source registry SHA-256 is
`1e406fc4f5463c2b6f6f835f695f4a07ad6e87094550e474e15f081707cca4fc`.
Two independently generated candidates were byte-equivalent after removing
only their top-level `generated_at` timestamps, and neither contains a local
`/Users/` or `/private/` path.

The isolated wheel
`/private/tmp/sciplot-m5-request-policy-wheel-20260717-0640/sciplot_core-0.1.0-py3-none-any.whl`
has SHA-256
`a1ad6f989e302fc50e48f9618945afc8cd3059414e092618ce960b19bd873a0a`.
Its archive contains the readiness evaluator, adversarial probe, and source
registry. A clean `--no-deps --target` installation imported all three from
the installed target outside the repository, reported `status=ready` with
`23/23` current envelopes, passed the packaged probe `29/29`, and `pip check`
reported no broken requirements.

The smoke fixture remains explicitly synthetic. The 23-rule acceptance is the
real-data lifecycle evidence; neither automated suite counts as a human M6
session.

## Remaining M5 and M6 work

M5 still needs the promotion workflow that converts repeated accepted AI
mappings or operations into reviewed rules, policies, fixtures, and regression
probes without silently broadening an envelope.

M6 still requires at least fifteen real plotting, editing, or composition
sessions across five families, zero accepted-edit loss, recorded fallback
reasons, default `studio` migration to SciPlot Canvas, and explicit owner
approval before Veusz `MainWindow` retires from the normal product surface.

This audit establishes deterministic readiness. It does not establish blanket
journal compliance, live-model quality, or frontend cutover.
