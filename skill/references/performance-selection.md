# Select original performance Metrics

Use this route when a tidy material/Metric/Value table needs two explicit
scatter coordinates or selected Metrics have missing units. It reuses the
existing `performance_comparison` plan and native scatter renderer.

```bash
skill/scripts/sciplot inspect /absolute/original.csv --performance --json
```

The read-only response supplies the current source SHA, exact original Metric
IDs, unit conflicts, missing counts, a closed `selection_schema` and an
intentionally incomplete `selection_template`. Select two distinct original
Metric IDs in `x_metric` and `y_metric`. Keep only declarations for those two
Metrics. Each missing-unit declaration needs `metric_id`, `unit` and the user's
actual `user_statement`; observed units cannot be overwritten. Never infer a
unit from magnitude or apply one global Value-column unit to different Metrics.

Set `scatter_x_display` to `preserve_original` for exact original X positions.
Distinct materials with equal coordinates remain distinct observations.
`deterministic_jitter` retains the existing explicit display option; omission
of the entire selection retains the older rule's behavior.

```bash
skill/scripts/sciplot plan /absolute/original.csv --rule performance_comparison --template scatter --performance-selection SELECTION.json --json
skill/scripts/sciplot project create /absolute/original.csv --expected-plan PLAN.json --json
```

Save the complete returned plan as `PLAN.json`. Source drift invalidates it.
Original Value cells use the common exact numeric reader; selected physical
rows, missing-pair masks and counts, units and attributed declarations remain
in source evidence and are rederived for native publication and cold export.
The existing valid-pair policy records missing selected coordinates explicitly;
it does not insert zeroes or fill measurements. Duplicate observations for one
material/Metric need a supported replicate identity and otherwise stop for
clarification. This route neither invents ratios nor substitutes another Metric.

Review the returned TIFF, scientific audit and delivery evidence. Retain the
original source for cold continuation. Use the existing saved-project export
and recovery route after an interrupted reply.
