# Exact FigureSpec text edits

`plot.intent` is an opt-in convenience for two existing ManagedPlot FigureSpec v2
patch capabilities: `axis.label` and `annotation.text`. It does not interpret a
free-form request, infer a scientific unit, change data or choose between duplicate
display labels. LegacyPlot and managed v1 use their existing routes.

Use `plot describe PLOT --scope summary` to get `plot_id`, `revision`, stable
target IDs and labels. Then send a closed request with the literal replacement
text, the current plot identity and revision, one stable target ID **or** one
exact current label, and a stable idempotency key:

```json
{"mode":"plan","plot_id":"returned-id","base_revision":0,"idempotency_key":"axis-label-1","property":"axis.label","target_id":"axis:xb","value":"Frequency (Hz)"}
```

The CLI is `sciplot plot intent PLOT --request REQUEST.json --json`; JSON-RPC is
`plot.intent` with `{"plot":"PLOT","request":{...}}`, and MCP is
`sciplot_plot_intent` with the same arguments. `mode: "plan"` only reads the
current saved document and input fingerprints. It returns the stable target,
before/after text, advertised presentation risk, relevant axis unit/quantity or
annotation anchor, and the exact `patch_request` it would submit. `no_change`
means the value already matches. No native preview or scientific transform runs
in planning.

After deciding to make the edit, submit the same fields and idempotency key,
changing only `mode` to `"apply"`. Apply compiles to the existing `plot.patch` transaction,
including its revision, currentness, review, native audit, export and recovery
checks. Reuse the same request and idempotency key after an uncertain reply.
Apply may return `needs_review`; inspect that preview and use its bound decision
before treating the edit as complete.

A `target_label` matches exactly and only within the requested object kind.
If it matches zero or multiple objects, the call fails without editing and
returns typed stable-ID candidates with view/scale/side/unit or annotation
anchor context. Choose `target_id` explicitly and retry. A stale
`base_revision`, changed source/native input or pending transaction blocks a new
edit. Plans are informational snapshots; apply always rechecks the current
state. The text itself is literal. For an axis label, verify that any unit you
write agrees with the returned scale unit; SciPlot will not invent or convert it.
