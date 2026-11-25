# SciPlot development roadmap

Baseline: main `376d95e2`, 2026-11-25. This is the one active work queue.
[README](README.md) describes shipped behavior; [Architecture](docs/ARCHITECTURE.md)
owns boundaries; [Complexity evidence](docs/COMPLEXITY_REDUCTION_PLAN.md) records
design decisions and measured history. Neither is a second queue.

**Product target:** A researcher uses the default client to turn an original file
into a paper-ready figure, then opens the same plot in another session, edits it
and moves it to another directory without losing its history or original data.
External AI is the task interface; CLI and MCP use the same local owners. The task
record says what to do next, the Store says which revision is current, and the
export receipt says which artifacts are ready. Keep those facts separate.
A paper delivery is a snapshot; a move preserves identity and history; Save As
gives the selected figure an independent identity. Keep Veusz/Qt as the native
adapter. No new application shell, tool family, scheduler, or global cache for
this plan.

## Order and stage exits

| Stage | Work | Exit |
| --- | --- | --- |
| A. Establish the actual user path | 01 tracks the existing CI; 02 owns this queue. Start 03 and 05 in parallel; 06 may inventory old formats. | A real external client has made its first editable figure, friction is observed, and the prior candidate's CI outcome is recorded. |
| B. Close daily use | 04 and 06 follow 03; 07 follows 04; finish 05. | A researcher can reopen the same figure in a new session, review/edit/recover, export, move and Save As through the default profile. Legacy redraw does not write the original. |
| C. Retire duplicated work | 08 before 09; 10 can investigate now and integrates after 01; 11 follows 10. | The first ordinary create family has one implementation. Each other removed path has real callers migrated, and each cost claim has a matched measurement. |
| D. Qualify and ship | 12 follows B; 13 follows 12 and the selected C batch. | The frozen candidate has separate Linux, signed Mac, human and real-science evidence. A missing gate leaves a controlled candidate. |
| E. Expand based on use | 14 follows D. | A known researcher blockage, an owning component and a real acceptance case justify each addition. |

## Work packets

### 01. Close the prior integration and main CI runs

Main already contains the baseline. At 06:47 UTC the [integration run](https://github.com/tunghsutian-creator/Science-Plot/actions/runs/45545787330)
and the [main run](https://github.com/tunghsutian-creator/Science-Plot/actions/runs/45563010803)
were pending. Main ran fresh checks rather than reusing the prior run.
Read the terminal results for that SHA, distinguish failed nodes from missing
runner evidence, and repair actual failures separately. Do not dispatch a third
run or claim that a push is a pass. The existing scoped cleanup is separate.

### 02. Keep one editable plan

Keep this roadmap, the historical complexity reference, and the
[independent acceptance procedure](docs/INDEPENDENT_ACCEPTANCE.md) in their own
roles. Use route or work-packet names and links, not old ordinal references.
Exit: a reader can find the next action and its evidence here, while historical
measurements and the independent acceptance protocol remain readable.
Check the documentation contracts and changed links only.

### 03. Make a first figure from a real external client

Use the existing Welcome/MCP probe and a public generated two-sample example.
Separate Doctor, local STDIO discovery, and an actual call from a configured
external client. Through that client ask about one real column/unit ambiguity,
plot the original observations, and return an editable project entry and saved
export. Record elapsed time, decisions, calls, and where help is needed. An
SDK-only probe is transport evidence, not an external-client pass. No automatic
client configuration or private data transmission. Targeted Welcome and STDIO
tests accompany the actual-client evidence.

### 04. Reopen and recover the same figure

Depends on 03. Reuse the existing task/plot continuation and saved-operation
receipts in CLI/MCP. Use only the current receipt for approval; reproject an
ephemeral preview when needed rather than persisting its resource URI.
Remove the adapter's redundant decision logic where the owner covers it.
Exit: close the client or lose its first reply, reopen a selected non-first plot
with the same project/plot IDs, reject stale approval, and resume a saved but
unexported change without resaving. Verify that another plot and the sources
are unchanged. Use an actual native continuation plus the existing recovery
tests.

### 05. Expose move and Save As in the default profile

Use existing bundle export/import and Save As operations and document them apart
from paper delivery. No new Store format or moving code in MCP. Exit: move to
an offline directory and reopen the same ID/history even with the old location
inaccessible; export there; Save As creates an independently editable ID
without changing the original. Do not overwrite a destination, carry host grants,
or imply two-way sync. Verify discovery and the existing real portable/native
cases.

### 06. Retire unused legacy write paths

Depends on 03. Inventory archived VSZ, current NativeSuite consumers, and
persisted review receipts before removing a writer. Old figures open and
redraw into a new directory without changing original bytes. Convert only an
equivalent supported XY subset through an explicit operation to a new Managed
project; verify values, units, samples and presentation. Preserve an already
committed action's recovery and current NativeSuite behavior. Do not silently
complete an old unapproved edit. Remove only compatibility branches whose
actual consumers are migrated, not original files or native evidence.

### 07. Report failures with an action the user can take

Depends on 04. Reuse owner-provided reason, stage and continuation status for
missing data, relocation/permissions, stale revisions, and saved-but-unexported
work. Remove overlapping heuristic messages. Exit: targeted refusals and
recoveries give a clear next step and whether a commit happened. The user can
explicitly export a support summary with build, action, phase and reason,
without original values, sample labels, paths, credentials or model logs. No
automatic uploads or product analytics.

### 08. Give ordinary XY one create implementation

Depends on 03 and 04. Move only ordinary XY through one source observation,
scientific binding, Managed creation and recovery implementation. Existing
public wire shapes may forward; delete the replaced native/Studio detour for
this family only. Exit: both inputs match for raw values, units, sample identity,
coordinates and retry; test duplicate X, missing values, invalid log domains and
old saved tasks. Do not remove specialized paths without same-result evidence.

### 09. Migrate one proven second family and remove one measured duplicate

Depends on 08. Choose either an ordinary categorical flow or an actual
scientific suite slice based on 03 and field evidence. Trace raw reads, hashes,
native invocations and latency at matched input/runtime/mode before removing
anything. Exit: original bytes, scientific result, rendering, preview/approval,
reopen/export and refusal/recovery still agree. Report actual counts or times.
Stop if equivalence or a concrete benefit is missing. Do not reopen completed
Store streaming or same-review reuse.

### 10. Make fast change feedback the normal developer entry

Integrate after 01. Use the existing [development workflow](skill/references/development.md);
evaluate documentation, a narrow code change and a shared scientific change.
Remove duplicate selection/documentation where the current owner covers it.
Exit: `verify --changed` reports why author checks were selected and explicitly
names anything deferred; additions, deletions, cross-owner inputs and a genuine
failure select correctly. Unknown scope never mints acceptance. No new runner.

### 11. Prove and remove a repeated candidate check

Depends on 01 and 10. Keep both pytest processes, their disjoint profiles and
their existing shared private-absent staged source. Compare the early module
surface with the actual verification wheel and remove a repeated proof only if
they cover the same release responsibility with the same failure behavior.
For private capture, profile the actual operator before changing its recipe;
production preflight already reviews once. Exit: known bad wheels, selection,
source/runtime drift and fail-closed outcomes remain checked. Rely on one
exact candidate run only when the main admission proves the same successful SHA;
fresh fallback is not a reused pass.
[Historical measurement limits](docs/COMPLEXITY_REDUCTION_PLAN.md#measured-history)
are not current performance evidence.

### 12. Independent beginner and installation acceptance

Follows Stage B. Follow the [existing procedure](docs/INDEPENDENT_ACCEPTANCE.md)
with an exact supported Mac build, a genuinely clean Apple-silicon Mac and
3–5 non-developers in an actual external client. Verify their own data, a real
ambiguity, review, export and next-day recovery. Inspect original values, units,
sample/physical row identities, and the same figure ID. Record first attempts,
interventions, friction, and positive/negative outcomes; keep unknown usage unknown.
Local relocation, synthetic fixtures and SDK discovery are not this human usability evidence.

Complete independent original-source coverage for advertised table choices,
including untouched workbook/FTIR metadata, selected pair/worksheet/region,
changed-value cross-sheet revisions, explicit units, original Test/block
selection, missing values, binary64 round trips, source append (including an unused pair or independent Test in the same file),
categorical and replicate statistics, and frequency/viscosity metadata. Retain
raw-only point behavior, valid-n and missing-policy disclosure, compatible
true grids, and complete original row/missing domains through native export.
A rule-selection answer must not encode arbitrary scientific facts; extend
reusable profiles only when current headers, units and mappings can be validated.
Generated tests or shift/fitting assumptions do not substitute for original-source
evidence.
Use the existing [metadata](docs/SCIENTIFIC_METADATA_ACCEPTANCE.md),
[table range](docs/TABLE_RANGE_ACCEPTANCE.md) and
[source update](docs/TABLE_SOURCE_UPDATE_ACCEPTANCE.md) protocols and preserve
known visual gaps: e.g. independent legend collision, mechanical individual
points, previously delivered dual-Y and multipanel checks, and cross-host font
evidence are not inferred from native or geometry success. Do not silently move
a fixed legend or claim unavailable font-face evidence.

For **Reviewed annotation rebinding**, independently test untouched source
revisions with moved, missing and multiple observed peaks. Check exact
metadata/values/samples, preview/approval, native/spec/CSV export and actual
interrupted-update recovery. A generated edit or fault injection cannot
replace a real revision, and an unchanged XRD pair does not cover these cases.

### 13. Freeze and qualify one candidate for release

Depends on 12. Bind exact Linux whole public CI, native Mac build/relocation
and independent real-science results to the same candidate. Keep separately
required local private full and complete access capture: exact collected
nodes/parameters, authorized original raw/golden inputs and bytes, child
startup/exits and socket/access epoch evidence, original waits, declared and
undeclared file/metadata controls. Keep private inputs and streams local.
Incomplete observation, capture or runtime authority remains blocked; do not
promote the preliminary inventory from static review or a passing subset.
Retain cold replay for original sealed DataMapping executions and strict
version-3 preparation; old-reader unit controls do not certify native recreation.

Use the [existing beta/release process](docs/PUBLIC_BETA.md). Public delivery
requires Developer ID signing, stapled notarization, Gatekeeper and exact ZIP
identity/checksum as well as the independent Mac/client outcomes. Do not claim
other platforms/font configurations or physical print/journal acceptance.
Keep the same proven artifact, check actual branch rules before a normal
fast-forward, and separate already-pushed source from default upgrades or
publication. No backup or cleanup of private inputs/evidence is implied.

### 14. Add only a capability that removes a real blocker

Follow Stage D's observations. A specific PDF review, layout, reused style,
or new scientific plotting problem may warrant one bounded addition through
its existing owner. Compare actual user effort with equivalent quality and
confirm a true native round trip. Keep unsupported representations explicit.
No sweeping chart catalog, rendering rewrite, cloud sync, or complete old-format
bidirectional support. Explicit repair of incorrectly bound existing sources,
general scientific rollback, stronger outbound minimization, additional visual
families and unrepresented native state remain separate contracts. A new
correct figure does not repair an old revision; a read-only legacy adapter does
not grant write support.

## How to execute

Each packet is a scoped change or evidence delivery. Use targeted checks during
iteration and an integration gate once for the frozen scope. Run the relevant
native/scientific refusal controls when ownership crosses those boundaries.
Record all end-to-end scopes separately rather than running full repeatedly or
substituting numbers from earlier commits. For credible performance comparisons
match input, runtime, native path and evidence mode, and distinguish user time,
model time and local processing. Treat unavailable token/billing counters as
unknown. Never turn a new abstraction or general cache into a substitute for
deleting a demonstrated duplicate.

**Start now:** 02 keeps the queue current; 03 tests the first figure in a real
client; 05 uses existing move/Save As. These slices can proceed while 01 tracks
the earlier runs without duplicating them.
