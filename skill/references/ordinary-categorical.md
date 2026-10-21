# Original categorical tables

Use the ordinary `task start` request for categorical data without assigning an
experimental rule. It uses the existing Studio native project, audit, edit and
export lifecycle. The program reads original cells; do not transcribe arrays,
prepare another table or construct a FigureTemplate.

Start with known intent and the original file:

```json
{"version":1,"action":"create","source":"/absolute/original.xlsx","categorical":{"mode":"given_values"}}
```

```sh
sciplot task start --request REQUEST.json --task-dir TASK --json
```

The returned source-bound question supplies original worksheet/row evidence and
the current response schema. Reply with `expected_question_id` and complete
`categorical` choices in the same task. Indices are zero based; `data_end_row`
is exclusive. Select `table_selection`, `sample_column`, optional
`condition_column`, and `value_columns` containing original `column_index`
and optional series display `label`. The program binds `source_sha256`.

Use existing `metadata_confirmations` to declare missing quantity or units with
the source file hash, target sheet and column, and exact source-cell or user
statement evidence. Existing conflicting facts remain errors; confirmations
never convert measurements. Multiple value columns on one axis require the same
stated unit. Select one original file/table per figure.

`given_values` uses the existing point-line template and requires one provided
value per included sample, condition and value column. It adds no error bars or
replicate aggregation. For repeated long-form measurements select
`mean_sample_sd` or `mean_sample_sd_n`: the existing bar template calculates
arithmetic mean and sample SD (ddof=1), requiring at least two valid values in
each group. The `_n` mode also delivers the source-bound audited summary CSV.
No count or statistic is inferred from a display label.

Missing replicate values require an explicit `missing_values:"exclude"`
instruction on the first request, or the returned source-bound missing-values
answer. Blank cells are never filled with zero. Nonnumeric text, nonfinite
values, incomplete identities and ambiguous given-value duplicates require
correction or clarification.

`include_categories` explicitly selects original sample IDs. `category_order`
orders every included ID and never implicitly excludes a sample.
`condition_order` orders all observed conditions. `category_aliases` changes
display tick labels while keeping original IDs in source and statistical
evidence; aliases must remain unique. Long-form summaries currently reuse the
existing layout for one to three conditions.

`series_styles` accepts an existing series label, or a long-form summary's
condition label. Given-value point-lines support hex `color`, `marker` and
`marker_fill_mode` (`filled` or `open`). Repeated-measurement bars support
explicit `color` only; marker and fill-mode requests are rejected because
summary bars have no visible raw-point markers.
Given-value point-lines accept `yscale:"linear"` or `"log"`; every original value
on a log axis must be strictly positive. Summary bars retain their existing
linear axis and visible zero baseline. A summary log request is rejected before
plotting, without changing its requested scale or statistical method.
For `given_values` point-lines with a native key, `legend_position`
accepts the existing inside corners or `auto`, and `legend_columns` is an
explicit integer from 1 to 12. Existing native QA still blocks clipping or
collisions; explicit placement is preserved, and default axis bounds may use
the existing bounded legend reserve. Explicit axis bounds remain fixed.
Repeated-measurement bars retain
their existing fixed categorical legend and reject explicit key columns or
non-`auto` corner placement before plotting.

Read the returned final TIFF, then deliver the package. Cold export uses the
same public task request with `action:"export"` and the saved `project`, or the
existing saved-work continuation. Retry a lost reply with the same task and
request; do not create a replacement project.
For a later alias or style request, keep this saved project and use the
[categorical display edit route](categorical-presentation-edit.md); do not fold
the later intent into a replacement creation.
