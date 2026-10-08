# Managed plots: document authority and disposable backend artifacts

Design established before implementation, 2026-10-08. The supported managed
vertical slice is now implemented; actual runtime evidence is listed below.
This document distinguishes those tested guarantees from unsupported capabilities.

## Authority

`LegacyPlot` is compatibility mode: imported current VSZ remains the complete
visual authority; semantic edits/reimport preserve unknown native state.
`ManagedPlot` is created from an explicit Template, Binding and Theme: the sealed
SciPlotDocument, source records, transform identities/results and resources are
the complete authority. VSZ, previews and exports are disposable build products.
Unsupported managed capability fails before publication; it never falls back to
opaque native state or silently changes authority mode.

## Compilation boundary

```text
Template + Binding + Theme + raw sources + typed transforms
  -> sealed ManagedPlot document + immutable scientific resources
  -> SemanticCompiler (backend neutral, resolves all defaults and bindings)
  -> resolved PlotIR + content hash
  -> VeuszBackendCompiler (no template, theme or scientific inference)
  -> VSZ + actual native audit + render + export
```

The initial managed slice is a single Cartesian line figure with explicitly
represented axes, dimensions, styles, legend and ordinary annotations. Other
forms remain declared unsupported until they have a full-state reconstruction
test. Backend paths are private implementation details, never semantic selectors.
Renderer timestamps/volatile metadata are excluded from scientific and PlotIR
identity. Actual output-byte hashes remain separate from input build keys.

## State and execution

Reuse the current revision store, idempotency journal, transaction stages,
scientific/presentation hashes, compact protocol and export-pending recovery.
Route backend calls by recorded authority. Managed preview compiles a complete
candidate from the new document, and apply adopts that immutable compiled result.
Deleting generated artifacts triggers a fresh document-to-IR-to-native build; an
existing artifact with unknown external changes is rejected, not overwritten or
adopted silently. Source/executor refresh requires explicit scientific intent and
new revision. Ordinary theme/style edits reuse verified scientific results.

The semantic `plot.create` template route defaults to ManagedPlot for its supported
contract. Existing native projects and explicit compatibility creation remain
LegacyPlot. No automatic promotion of imported VSZ is attempted.

## Transform and graph contract

Each TransformNode has stable ID, type, executor ID/version/content hash, input
and output dataset IDs, parameters, determinism declaration, provenance, output
content identity and status. Built-ins cover select/rename, unit-preserving numeric
scaling and normalization. External execution invokes a fixed file with recorded
interpreter/script hashes and a closed input/output exchange; arbitrary source
snippets or unrecorded processes are not accepted as transforms.

Nodes are source -> transform -> dataset -> plot -> render/export, with content
identity per node. A plot's transaction depends only on its source/executor/data
closure and its own artifact. Another plot's backend files are not dependencies.
The existing pure DAG owns cycle checks and downstream invalidation.

## ExternalMutation

Capture old/new native identity, exact represented semantic diff, evidence and
classification. Full-state equivalence is required to claim a known-only change;
a represented width difference alone does not exclude simultaneous opaque edits.
Legacy reimport preserves opaque changes after its existing review. Managed plots
classify known deltas through full-state equivalence and reject external mutation
without adopting it. Known-delta adoption and explicit Managed-to-Legacy conversion
remain future capabilities. There is no mixed authority state.

## Required real acceptance

A. Create from Template/Binding/Theme; delete every VSZ/render/export; rebuild from
raw sources and SciPlot state. IDs, XY data, scientific hash, resolved PlotIR hash,
styles/layout and successful actual native export must match.

B. Change paper theme to presentation theme; only presentation identity changes.
C. Change source A; only its dependency descendants become dirty, plot B stays current.
D. Change normalization parameter; output and scientific hashes change, unrelated
plot B stays current. E. Change the bytes of a fixed scientific script without
renaming it; executor identity and downstream invalidation must change.
F. Known legacy style mutation yields an ExternalMutation semantic diff; opaque
legacy state remains explicit; unknown managed native state cannot be adopted.

Also retain stale-revision rejection, idempotent replay, source race guards,
native scientific audit, immutable provenance, crash recovery and thin CLI/MCP.

## Implemented acceptance and limits

Actual A–F native acceptance passed for the represented Cartesian XY contract.
`tests/test_managed_engine_native.py` deletes all generated artifacts and the IR
cache, then checks unchanged scientific identity, IR, full native state and pixels.
`tests/test_managed_protocol_native.py` repeats this through actual CLI creation
and official MCP export on the persistent service. Source/normalization/executor
changes and unrelated-plot transactions have independent native regression cases.
Compile-receipt and apply/commit crash windows have explicit fault-injection tests.
Backend/runtime identity includes shared helpers and vendored Veusz, separately
from scientific/IR identity. A pending compile can only be adopted after complete
native equivalence, and interrupted managed apply still guards its old baseline.

The initial transforms are one-input/one-output, row-preserving column operations;
non-deterministic execution is explicitly unsupported. Source-only task creation
remains legacy compatibility. Managed exports provide exact native fidelity and
sealed PDF/TIFF evidence, not full publication layout/overflow QA or cross-machine
font-pixel determinism. Unknown native features never become backend-only managed
state. Full report, exported schemas, observations and gate results are retained
under `.tmp_verify/managed_architecture_20261008/`; raw user research data is untouched.
