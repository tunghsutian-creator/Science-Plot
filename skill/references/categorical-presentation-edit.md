# Late ordinary categorical display edits

Use the same saved project after an ordinary `categorical_binding` creation.
This route covers `rule_id=null`, `given_values` point-lines and
`mean_sample_sd` / `mean_sample_sd_n` bar summaries. It changes displayed
category names and represented styles while retaining original category IDs,
observations, groups, sample counts, statistics, source hashes and the canonical
scientific request.

Read the current source-bound selectors and selected schemas together:

```bash
skill/scripts/sciplot task edit-context PROJECT \
  --operation set_category_display_labels \
  --operation set_categorical_display_style --json
```

Use `categorical_display.categories` for original `category_id` and current
displayed `label`. Use `style_targets` for each stable `series_id`, original
`source_selector`, complete `current_style`, and `editable_fields`. A condition
can cover several summary series; select all returned targets for that condition
when the user requests the same color throughout. Select a metric by its returned
original `value_column_index` and source label. Do not guess native widget paths
or transcribe values from the image.

Fill the returned `request_template.operations` with an authorized batch. For
example, using the exact IDs and expected values from that context:

```json
[
  {"op":"set_category_display_labels","changes":[
    {"category_id":"original-id","expected_label":"current label","label":"Control"}
  ]},
  {"op":"set_categorical_display_style","changes":[
    {"series_id":"returned-series-id","expected_style":{"color":"#215977","marker":"circle","marker_fill_mode":"filled"},
     "style":{"color":"#B65B43","marker":"square","marker_fill_mode":"open"}}
  ]}
]
```

Bar summaries advertise only `color`; marker or marker-fill requests fail before
save. Given-value point-lines support `color`, `marker` and `marker_fill_mode`.
Markers are circle, square, diamond, triangle or none; fill is open or filled.
All numerical observations and line vertices remain intact.

When `categorical_display.legend` is present, the given-value figure has an
existing native key. The style operation can additionally include:

```json
{"legend":{"position":"upper_right","columns":2,
           "expected":{"columns":1,"horzPosn":"left","vertPosn":"top"}}}
```

Copy the complete `legend.current` into `expected`. Positions are upper/lower
left/right and columns are integers 1–12. A grouped-bar custom segmented legend
has no corner/column operation here. An explicit corner remains the user's
choice; a layout collision must be resolved through a new authorized edit.

Save the complete edit request and start the existing task transaction:

```bash
skill/scripts/sciplot task start --request REQUEST.json --task-dir STABLE_TASK --json
```

View its candidate image and scientific audit, then resume using the returned
`next_step.response_template`. Repeat the identical task/request after an
uncertain reply; use a fresh context for later edits. A saved-only edit requires
the existing `action=export` task to refresh delivery. View the final TIFF and
deliver the returned PDF/TIFF only after publication checks pass.

Display aliases are stored separately from the original `category_axis_labels`
dataset. The existing display-label dataset and label provider render the alias;
cold audits verify both original and displayed labels. Duplicate aliases, stale
expectations, unknown IDs, unrepresented styles and source/native tampering are
rejected through the existing audit and transaction owners.
