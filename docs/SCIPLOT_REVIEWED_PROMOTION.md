# SciPlot Reviewed Promotion Contract

Status: M5 learning-loop gate G1 implemented and adversarially hardened,
2026-07-18. This contract turns repeated, accepted AI-assisted work into
review material without allowing an AI output, candidate file, or approval
record to change deterministic plotting behavior. It does not claim that any
real decision has repeated three times.

## First-principles boundary

Experience can propose a hypothesis. It cannot grant software capability.

SciPlot therefore separates five authorities:

1. a completed session ledger proves what actually happened;
2. a canonical observation removes instance identity and raw values;
3. a candidate reports repetition but has no runtime effect;
4. a receipt signed by a preregistered owner key authorizes only a normal
   implementation attempt;
5. reviewed source, a changed candidate-specific promotion probe, and a
   provider-disabled real lifecycle prove the implementation on one frozen
   commit.

Plotting, rule matching, policy, readiness, validated envelopes, and delivery
never read promotion artifacts. A verified promotion record remains powerless;
the reviewed source commit is the only behavior authority.

## Eligible observations

`sciplot learning collect` replays the hash-chained session evidence ledger,
its companion head, the witnessed journal boundary, and the referenced
execution or Canvas authority.

It can collect only:

- a passed, handoff-ready `DataMappingProposal` execution whose confirmation,
  transform ledger, mapped outputs, and unchanged raw inputs reproduce; or
- an applied `CanvasOperationBatch` named by a structurally passing committed
  Assistant transaction, provided that the batch was not undone, rolled back,
  or superseded, and every accepted operation still has its exact effect in the
  final reopened VSZ.

Preview, provider response, proposed batch, rejected batch, interrupted
mapping, failed execution, and rolled-back work are not observations. A
replay failure fails collection; it is not silently converted into zero
evidence.

An observation counts toward review only when its enclosing session:

- uses `owner_authorized_real` or `public_authorized_real` data;
- has scope `m3_live_model_scored`, `m6_discovery`, or `m6_qualification`;
- has one consistent owner across preregistration, reopen witness, and
  completion;
- has the explicit reopen attestation;
- completes with `outcome=pass` and no recorded failure; and
- binds the applicable `data_mapping` or `ai_operation` evidence check.

Synthetic observations may be diagnostic, but contribute zero threshold
votes.

A session carrying `promotion_binding` exists only to verify an already
approved implementation. Collection excludes it before mapping or Canvas
observation replay with
`reason_code=promotion_verification_session_non_voting`. Therefore the real
sessions used to verify one candidate cannot recursively vote that candidate,
recreate its three-session threshold, or seed another promotion.

## Canonical decision

Comparisons omit:

- source and project paths;
- provider and model identifiers;
- timestamps, proposal IDs, transaction IDs, batch IDs, and operation IDs;
- source hashes and instance-only object IDs;
- sample labels and raw condition values;
- free annotation or axis text; and
- literal data ranges and dataset references.

Mapping observations retain semantic schema roles, source-column positions,
unit policy, transformation types, redacted condition shapes, and the bounded
request patch. Canvas observations retain object type, relative setting path,
operation type, and safe visual policy. Dataset-setting mutations are rejected
from promotion rather than generalized.

The candidate ID is the SHA-256 of this canonical decision. A candidate reaches
`ready_for_review` only when one attested owner has both three distinct real
session identities and three distinct natural-task fingerprints. Sessions from
different owners cannot combine approval authority, and re-running one task
under new session IDs cannot stuff the vote.

## Artifact and state chain

Every generated artifact contains a canonical content hash and
`runtime_effect=false`.

```text
collection
  -> candidate set: observed | ready_for_review
  -> signed owner decision: approved_for_implementation | rejected | deferred
  -> implementation plan: awaiting_reviewed_source_change
  -> verification: reviewed_implementation_verified
```

Each downstream command validates upstream file hashes, content hashes, signed
receipt state, and immutable byte snapshots used by the semantic loader.
Implementation verification consumes the decision through a fresh private
byte snapshot and requires both its file SHA-256 and internal decision SHA-256
to equal the values frozen in the plan before using it downstream.
Collection and candidate build additionally replay the original session
ledgers and evidence artifacts. Data-mapping replay also binds the initially
captured manifest and proposal, rejects symlinks, and requires the complete
execution tree to retain the same file content, inode, mode, timestamps, and
directory metadata throughout validation.

`ready_for_review` is not approval. Approval is not implementation.
Verification does not toggle a rule or envelope.

## Commands

Collect and build candidates:

```bash
skill/scripts/sciplot learning collect \
  SESSION_EVIDENCE.jsonl [MORE.jsonl ...] \
  --out promotion_collection.json \
  --json

skill/scripts/sciplot learning build \
  promotion_collection.json \
  --out promotion_candidates.json \
  --json
```

Inspect any generated artifact or the closed contract:

```bash
skill/scripts/sciplot learning status promotion_candidates.json --json
skill/scripts/sciplot learning schema --json
```

Before authoring a verification receipt, compute each exact real-session
binding from the replay-verified ledger:

```bash
skill/scripts/sciplot learning session-binding \
  SESSION_EVIDENCE.jsonl SESSION_ID \
  --json
```

The output is powerless unsigned input for the owner receipt. It binds the
canonical ledger path, the byte prefix ending at that session's completion,
the preregistration/witness/completion event hashes, and the current
CanvasSession, VSZ, export, journal-prefix, optional mapping/review, and final
manifest hashes. The program still does not author or sign the receipt.

The program deliberately does not create owner receipts, private keys, or
signatures. `learning schema` reports the fixed external trust-registry path
and exact receipt fields. The registry is outside the repository and contains
active RSA public keys with canonical fingerprints; SciPlot only reads it.
The production path is derived from the operating-system account database,
not `HOME`, XDG, or another environment override. Every path component must
avoid symlinks and group/world write access; the file must be a regular file
owned by the current uid. On macOS the registry must additionally carry the
user-immutable flag (`chflags uchg`). Temporarily clear that flag, replace the
registry through an owner-controlled process, restore owner-only permissions,
and set `uchg` again when rotating a key. Test-only callers may inject an
unprotected temporary registry through a private API; the CLI cannot.
`decide` accepts a pre-existing, detached-signature-verified receipt:

```bash
skill/scripts/sciplot learning decide \
  promotion_candidates.json owner_decision_receipt.json \
  --out promotion_decision.json \
  --json
```

An approval receipt must also declare a closed `implementation_contract`:

- the exact candidate ID;
- exact repository-relative source files allowed to change;
- exact changed `src/**/*_promotion_probe.py` files;
- accepted probe artifact kinds; and
- applicable real-data lifecycle lanes already represented by the candidate;
- exactly one whole-candidate manifest assertion for every lane; and
- for a mapping candidate, exactly one independently replayed mapping
  execution assertion for every lane; and
- for a Canvas candidate, one final-VSZ setting or widget assertion for every
  canonical operation in every lane.

Generic health fields such as `CanvasSession.state=ready`, QA pass, or
`ready_to_use=true` are not candidate effects and are rejected as lifecycle
assertions. A deterministic mapping implementation must emit the complete
redacted canonical decision in its final manifest and independently reproduce
the confirmed proposal, mapped files, transformation ledger, and final plotted
source lineage. A Canvas implementation must emit the same candidate and must
additionally reproduce every canonical setting or widget effect in the
reopened final VSZ.

Only an approved `ready_for_review` candidate can produce a plan:

```bash
skill/scripts/sciplot learning plan \
  promotion_decision.json \
  --repo /path/to/clean/sciplot \
  --out implementation_plan.json \
  --json
```

The implementation uses the ordinary source-review path. The mechanism never
writes a rule, policy, fixture, probe, validated envelope, or candidate state.

After a reviewed commit exists, `verify` accepts a separate signed
owner-authored receipt binding the exact plan, commit, passing probe artifacts,
and the complete `learning session-binding` facts for every real session:

```bash
skill/scripts/sciplot learning verify \
  implementation_plan.json verification_receipt.json \
  --repo /path/to/clean/sciplot \
  --out promotion_verification.json \
  --json
```

Verification requires:

- a clean descendant commit different from the plan baseline;
- a root-owned absolute Git executable, explicit git-dir/work-tree, and a
  closed environment that ignores ambient `PATH` and repository-affecting
  `GIT_*` variables; full 40-character SHA-1 and 64-character SHA-256 commit
  identities are both accepted and checked against the repository object
  format;
- no `assume-unchanged`, `skip-worktree`, or other non-normal index flag, and a
  direct byte/object-mode comparison of every tracked worktree file with the
  expected commit blob before and after verification;
- every behavior-affecting changed file to equal the owner-approved source
  scope, with every approved promotion probe changed and no undeclared code;
- every named JSON probe artifact to retain its recorded hash, use an approved
  kind, report `passed` or `ready`, and bind the candidate ID, canonical
  decision, plan, source scope, producer probe, and exact commit; its signed
  path must already be a canonical absolute path, so lexical aliases cannot
  name or duplicate the same artifact;
- SciPlot to materialize `src/` from the exact reviewed Git commit into a
  private read-only snapshot, then run the approved probe from that snapshot
  through the fixed `--promotion-context PATH --json` interface and reproduce
  the signed JSON artifact exactly; current-worktree bytes are never executed;
- every approved lifecycle lane to have an applicable, owner-attested,
  provider-disabled real session running the exact same clean frozen commit;
- every signed session reference to retain the exact completion ledger prefix,
  all three event hashes, and every signed authority artifact hash; canonical
  ledger paths prevent lexical aliases from duplicating one session;
- each lifecycle to have been preregistered before work with the candidate,
  signed decision, plan hash, and exact assertion IDs; and
- the final manifest to contain the complete canonical candidate and, for a
  mapping candidate, the witnessed execution and final manifest to
  independently reproduce the proposal, mapped outputs, transforms, and
  plotted source lineage; for a Canvas candidate, the reopened final VSZ must
  reproduce every canonical operation. A merely successful unrelated
  lifecycle is insufficient.

A mapping-candidate lifecycle deliberately separates historical proposal
identity from runtime authority. It preregisters `provider_disabled` and
`data_mapping` together without provider/model fields, witnesses the existing
confirmed execution, and permits no Assistant journal activity. Auto, explicit
recipe, and direct-render manifests identify the actual processed or mapped
tables passed to rendering. Multi-output lineage must bind the complete
terminal transform set; one member or a directory-level placeholder is not
enough. Every curve, categorical group, or scalar field written into the Veusz
specification also records the exact current source path and SHA-256 consumed
by that rendered unit. Completion independently reopens those specifications
and the exact-current VSZ from private read-only byte snapshots. Expected
numbers are quantized once to Veusz's persisted `.6e` token; reopened values
must equal that token exactly, so an untouched save passes but extra-precision
hand edits do not. The verifier requires a real visible line, marker, fill,
boxplot, or scalar-image channel for every expected unit, requires the exact
native boxplot inventory, and rejects unapproved visible data plotters. It
also independently replays the exact terminal tables through the renderer's
data-selection and transform semantics: terminal-derived units, specification
units, and reopened VSZ units must agree. Terminal tables are captured through
regular-file descriptors with `O_NOFOLLOW`; derivation consumes only private
read-only copies, maps provenance back to the original canonical path/hash,
and rechecks the original identity before returning. Unit signatures bind the
stable series name, visible label, x/y dataset identity, and order; the
reopened document must expose the exact axis label/direction/mode/scale/range,
tick format/count/manual values/visibility, text sizes, line and tick
dimensions, legend, direct-label text/position/alignment/size/color/background/
border/order, complete visible-label, categorical
text-dataset, category-axis label, and XY/boxplot order inventories. Scalar
signatures also bind the independently derived z range, color scale and ticks,
custom colormap with at least two distinct fully opaque colors, inversion,
field mapping/draw mode, colorbar text/line/tick
dimensions, and contour contract; reopened image, custom-colormap, colorbar,
and contour inventories must agree. The source-evidenced automatic path also
closes the visible shape inventory to the exact page background, bounded
source-bound reference bands, exact native reference lines, and an optional
highly transparent local colorbar background. Log-axis bands use logarithmic
geometry; native lines bind point-to-point geometry, width, style, color,
transparency, and visibility. Unmanaged overlay shapes fail closed. External
requests cannot self-assert that source preprocessing is complete, and
manifest terminal-request projections are declarations rather than
authority. Verification rebuilds the closed terminal request from the
confirmed request and private terminal snapshots, reproduces any explicitly
confirmed split plan and per-panel selection, and compares the declaration
against that result. Automatic splits and multi-metric bundles without an
independent confirmed panel plan fail closed for formal source evidence.
Ambiguous unit-like metadata rows, duplicate labels before label-based
selection or split routing, and unknown or fully hidden series selections
all fail closed rather than guessing or falling back to all curves.
Every terminal plotted source must contribute, every rendered source must
belong to that terminal inventory, and every confirmed multi-output mapping
member must contribute.
Case-fold matches, aggregate series counts, injected directory members, and a
stale generation spec are never coverage evidence; display labels are checked
as semantic identity, never accepted as source provenance. A single-output
mapping may use
`transitive_single_output` after a deterministic recipe or semantic transform
because no sibling source can be omitted; the transform ledger and terminal
snapshot still prove that derivation. Session-ledger replay reopens the bound
run manifest and rederives this complete lineage before any observation may
vote. Snapshot capture verifies the original inode, mode, size, mtime, ctime,
and hash before and after each isolated audit, so swapping a clean
specification, document, or terminal table into the audit fails closed.

## Adversarial probe and limitations

`sciplot promotion-probe` checks canonical redaction, powerless artifacts,
same-owner three-session threshold behavior, mixed-owner and duplicate-task
vote stuffing, synthetic zero votes, signed owner authority, receipt-derived
state, signed ledger/event/authority binding, exact-commit probe re-execution,
rejection of hidden index flags and ambient Git redirection, same-snapshot
`learning status` dispatch, rejection of health-only assertions,
whole-candidate manifest binding, independently replayed mapping lineage,
provider-disabled mapping recertification, complete multi-table terminal
snapshots, renderer-consumed path/hash coverage under colliding display labels
and a non-plottable source, non-voting promotion verification sessions,
plan-bound stable decision snapshots, SHA-256 Git repositories, canonical
probe-artifact paths, final-VSZ operation matching, replayed synthetic-ledger
behavior, and stale-hash rejection.
Its positive threshold records are explicitly simulated contract fixtures;
they are never written into a real candidate collection.

The local session hash chain detects ordinary tampering but is not a remote
timestamp. Promotion authority additionally depends on custody of the private
key corresponding to the external trusted-owner registry; SciPlot never stores
or uses that private key. The adversarial probe creates an ephemeral RSA key
through the system OpenSSL executable and retains it only in an anonymous file
descriptor, so no private key is shipped in source or named on disk.
`reviewed_by` remains an owner-signed local review
attestation rather than a mandatory third-party identity. G3 and G4 supply
natural real observations. If no decision repeats, the correct G1 output is
zero `ready_for_review` candidates.
