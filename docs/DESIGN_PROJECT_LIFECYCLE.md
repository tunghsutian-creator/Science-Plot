# Project lifecycle core migration

Status: core migration contract. Exact-commit validation records own acceptance
claims. This document defines the complete target, not a project-wide health certificate.

## Reason for replacement

The 2026-10-25 independent project-level review inspected 82 source files and
validated 101 source references. It found multiple use-case and transaction
owners, global scientific executor source coupling, path-bound project storage,
unsafe native setting-batch failure behavior and a persistent panel lock without
process-death recovery. Static source evidence did not prove that user data had
been damaged. The source review alone contained no fault injection or performance
measurement. Subsequent implementation evidence must be identified separately.

Scientific validation, source hashes, sealed historical execution and the native
renderer provide useful behavior to preserve. Existing classes and module names
are not compatibility requirements. Moving a state machine to another file, or
adding an unused interface beside it, does not resolve divided ownership.

## Complete scope and dependency direction

This batch replaces three owners, with one shared lifecycle interface owner:

1. Semantic figure aggregate: every current create, open/import, describe, typed
   intent, patch, decide, reimport, rollback, recovery, render, export and delivery
   entry for Managed documents and Legacy semantic shadows. CLI, RPC, MCP,
   checkpoint/edit adapters and Python compatibility entries reach the same
   application owner. NativeSuite project workflows remain a distinct aggregate;
   they must not be silently described as migrated semantic documents.
2. Desktop Assistant setting batches: manual and automatic application, native
   Undo/Redo and their save/export safety boundaries. Arbitrary Veusz operations
   are outside the supported setting-set command family.
3. Panel-layout persistence: model, CLI, MCP and desktop saves reach the same
   storage owner, including concurrent save, process death and directory exchange.

The semantic dependency direction is:

```text
CLI / RPC / MCP / compatibility facade
  -> composition: target resolution + concrete backend + repository + capabilities
  -> ProjectApplication: admitted commands and lifecycle state transitions
  -> ProjectRepository port + scientific/native capability ports
  -> filesystem repository / Veusz rendering adapters
```

Composition owns existing native, stored-document and local delivery format/path
discovery. Application logic consumes closed target variants and never discovers
a store by reading arbitrary index/head paths. Repository owns namespace
preparation, semantic cache/checkpoint state, immutable scientific content bytes,
and all actual head, immutable revision and journal JSON writes.
Scientific grammar and source validation remain their existing pure owners.
Default backend construction does not leak into the application state machine.

## Authority, commands and recovery

Managed semantic documents own represented science and presentation. A Legacy
saved VSZ owns complete native appearance; its semantic shadow owns only explicitly
represented properties and must retain its exact native binding. GUI changesets,
semantic revisions and saved native byte identities are different identity
domains; none can stand in for another.

Revision tokens bind plot identity, authority mode, monotonic revision and both
scientific and presentation seals. Commands bind kind, idempotency key, expected
revision, original wire request and canonical business request. Original request
bytes/body are historical evidence and are not overwritten by a retry. Equivalent
typed labels and stable object IDs may compile against the same saved pre-command
snapshot into the same business command and replay it. Different kind, target,
value, authority or base revision cannot reuse that key. A canonical request hash
is an integrity witness; it is not proof of historical external authenticity.

Public transaction receipts use the same typed projection for revision, commit,
export and recovery state while retaining compatible response fields. An absent historical
command digest remains unknown. Export failure can leave a committed revision;
retry resumes export without reapplying science. Undo appends a revision. Source,
immutable revision and completed historical journal bytes survive restart.
Repository injection applies throughout the invocation, resets on error and
isolates concurrent applications. In-memory repository controls include large
content-addressed provenance and compatibility edit/delivery callers, and fail if
semantic state escapes into a default filesystem implementation. The user-facing
edit-entry checkpoint remains its own leased filesystem record of a literal
request; it contains no execution phases or semantic head state. Native artifacts
and original source bytes retain their rendering and scientific I/O owners
rather than becoming a generic repository filesystem.

No second journal or revision tree is introduced. The existing store remains
readable. The old storage and orchestration modules are compatibility delegates
to the new owner, not alternative implementations. Commit validates authority,
identity, exact monotonic revision and the existing scientific aggregate rules
before writing. This does not assert atomic replacement of all project files
across a power loss; whole-project generation publication is a separate scope.

## Native transaction safety

Veusz remains the long-term editable native renderer and export adapter. Its
OperationMultiple executes members sequentially and does not compensate a failed
member. The desktop setting adapter therefore captures the full live draft,
including raw references, opaque native content, metadata, Undo/Redo and operation
state. Failure in apply, Undo or Redo restores and independently compares that
snapshot. Successful application produces one native Undo item.

If restoration cannot be verified, preserve the live draft and quarantine it.
Guard Document save methods, actual exporter admission, already-open export
dialogs and project save/export boundaries. Reject before an existing output is
unlinked. A successful explicit native reload may clear quarantine. Qt action
callbacks report execution failure without allowing an uncaught slot exception
to terminate the process. These are ephemeral safety facts, not a second durable
scientific ledger. Native failure controls must include the unguarded upstream
counterexample and the actual public Studio bridge.

## Panel writer lifecycle

One nonblocking kernel lock is held on the parent directory descriptor. Every
current layout writer cooperates with it; aliases to that inode share exclusion.
Separate layouts in one directory intentionally serialize. Close and process
death release the lock without a lock-file reclamation heuristic.

A persistent versioned fence excludes historical O_EXCL writers. It is not the
lease owner and is never reclaimed by PID or age. An unknown historical marker
is retained and refused because inactivity cannot be proved; explicit Save As
remains available. Staging writes, publication and cleanup use held directory
descriptors. A replaced parent pathname fails identity validation without writing
private staged bytes into the replacement directory. Existing revision conflicts,
exact JSON bytes and preservation of the previous valid file remain required.

## Migration exit and acceptance

The batch is ready only when a caller/writer inventory proves all target paths
reach the single owner, replaced state machines/writers are removed, old projects
remain readable and no second authority is introduced. Fault controls cover
native partial failure and unverifiable compensation, process death, live writer
contention, directory replacement, equivalent retries, divergent retries,
source-binding rejection and injected repository isolation. Real native lifecycle
evidence covers create/edit/undo/restart/cold export through public clients.

Development uses relevant tests and strict static checks. Freeze the composed
batch once its bounded contracts pass; execute the required complete regression,
capture, strict access export, readiness/native smoke and exact-commit CI before
merge. Do not repeat a complete run for every small worker change. A subset,
static review or capture-only success cannot certify complete acceptance.

The subsequent [project-core migration](DESIGN_PROJECT_CORE_MIGRATION.md) implements
operator-specific immutable versions, host execution grants and the shared project
command/generation boundary. Attached semantic repositories, NativeSuite, Studio,
GUI/browser and publication callers use that boundary; standalone semantic
aggregates retain their one documented repository owner. These are concrete caller
migrations, not unused interfaces. Their combined release evidence remains a
separate gate from this earlier semantic/desktop/panel batch.

Discardable private native rendering, export and QA may precede storage admission
when they affect no active project, original source or delivery. They do not have
a durable exactly-once computation promise. Already sealed effects and external
scientific execution retain their own decision/journal and unknown-outcome rules.
Host grants authorize exact application actions/sources, not OS or network
isolation. Domain package cleanup, measured costs, outbound minimization and the
remaining open scientific schemas stay explicit later work. Neither batch proves
all-family scientific compatibility or global architecture health.
