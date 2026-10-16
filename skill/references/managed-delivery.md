# Deliver selected ManagedPlots without hand-built packaging scripts

This entry packages exact **current ManagedPlot revisions with passed native
publication QA**. Ordinary `task create` still uses its existing authority; do
not promote a legacy figure just to use this route. Legacy deliveries retain
their existing task/paper routes. A Managed v1 export lacking native publication
QA is explicitly unsupported here; absence is never treated as a pass.

Reuse each plot's current `plot`, `plot_id` and `revision`. Labels below are
display names for the delivery index and safe file naming; they never rename a
scientific sample, source column or original CSV. Request array order is the
publication order. Supply a stable key and a **new** destination directory:

```json
{"idempotency_key":"selected-figures-1","title":"Selected final figures","mode":"native_snapshot","out":"/absolute/new-delivery","items":[{"plot":"/absolute/original-plot","plot_id":"returned-plot-id","revision":1,"label":"P0.3/0.7"}]}
```

Submit through one public surface:

```bash
skill/scripts/sciplot plot deliver --request DELIVERY_REQUEST.json --json
```

JSON-RPC is `plot.deliver` with `{"request":{...}}`; MCP is
`sciplot_plot_deliver` with the same arguments. No separate source-copy,
launcher-writing, index-building or ZIP script is needed. This is an ordered
delivery checkpoint, **not** an atomic edit across multiple plots. Each plot
retains its own export transaction and scientific/QA owner.

For an existing byte-sealed export, the entry reuses that exact publication and
runs the compiler's existing read-only native scientific/publication audit. It
does not refresh an old compiler environment merely to package its files. A
missing cache or incomplete export set blocks and directs you to finish the
original export explicitly. Delivery never invokes export/recompile on an
original plot. Changed sources,
native state, audited files or ambiguous existing exports block rather than
overwrite them.

The product writes:

- `pdf/`, `tiff/` and `project/`: named final publications and independent VSZ
  snapshots created by native Save, never VSZ text edits.
- `data/originals/`: exact original file bytes, addressed by SHA256; the index
  retains source IDs and original names. No data are silently normalized or
  reconstructed for packaging.
- `data/plotted/`: the exact sealed PlotIR bytes plus one CSV per dataset.
  Each table retains its column order and own row count, without padding,
  truncation, recomputation or `.15g` rounding. Numeric CSV values round-trip
  to the stored values; empty cells represent null. Column IDs, labels, units
  and original row/transform/role evidence remain in the index and exact IR.
  References such as `1/e` are serialized from their sealed dataset, never
  recalculated or described as measurements.
- `index.json`: ordered display labels, physical files, source hashes and
  explicit local ManagedPlot continuation identities.
- Canonical `Open_in_Veusz.command`, `README.txt` and `Figures.zip`. The ZIP is
  inside the same exclusively installed directory and freezes the initial
  package; later manual edits do not silently rewrite it.

`status=partial` lists sealed and failed/conflicted items and does not publish a
partly ready directory. Retry the **identical request**, including key, item
order, revisions and output path. Sealed item bytes are checked and reused;
only unsealed audits/capture resume. Original native bytes must still match
the item’s fresh audit seal on retry, completed replay and final publication. CLI partial/blocked results exit nonzero. A lost
reply after final exclusive installation can be recognized from the complete
byte inventory. Existing destinations, edited completed deliveries and edited
sealed staging are preserved and return conflicts. Choose a new destination
for a new selection or an intentional new edition.

## Continue the original local ManagedPlot

Use the exact item ID returned by an ambiguous package open:

```bash
skill/scripts/sciplot plot open /absolute/new-delivery --figure 001_P0_3_0_7 --scope summary --json
```

This verifies the exact snapshot file inventory (with only standalone regular
Finder `.DS_Store` metadata excluded), index, original native byte seal, plot identity and revision,
scientific/presentation hashes and current source/native bindings, then opens
the **original local ManagedPlot**. Use its advertised semantic edits and normal
patch/intent/export continuation. The delivery result also returns the exact
`plot.describe` continuation for each original. Changed or unavailable originals
are never restored, reimported or rebound automatically. An edited independent
snapshot blocks implicit reconnection so its changes cannot be discarded by
quietly opening an older original.

## Move and independently edit the native snapshot

The package is explicitly `mode=native_snapshot` and reports
`portable_managed_project=false`. It contains **no relocated Managed registry**;
absolute local continuation paths are provenance, not portable bindings. This
entry provides no human ManagedPlot editor and does not claim that opening a
copied VSZ edits its original ManagedPlot.

Copy the complete directory or unpack its ZIP at a new location, then use
`Open_in_Veusz.command` with a working SciPlot/Veusz installation. Its native
Save snapshots contain their consumed data and can be reopened, edited, saved
and exported independently. Edits stay in that copy and do not update the
original project or frozen archive. Product publication reopens the native
snapshot after a real staging relocation and rejects remaining outside imports.
Generated native acceptance also performs a separate directory move, real
reopen, style edit, atomic Save and PDF/TIFF export with exact dataset equality.
That bounded acceptance does not certify every private figure, GUI workflow,
font installation, journal or a transferable full Managed project.

For a complete Managed project migration, retain its original sources and
registry and use an explicitly supported migration owner when available;
this native snapshot route does not invent one.
