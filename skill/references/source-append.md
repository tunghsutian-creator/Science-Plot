# Append an original table to a saved Managed XY figure

Open the existing ManagedPlot with `plot open TARGET --scope summary --json`.
Choose a view advertising `source.append`, then read its current contract:

```bash
skill/scripts/sciplot plot describe PLOT --scope edit --target-id VIEW_ID --property source.append --json
```

The contract supplies the plot ID, current revision, exact value schema and
existing scientific quantities, units and domains. This operation keeps that
same plot and its original sources, curve IDs, aliases, styles, axes and legend
settings. It supports original numeric XY observations with linear or logarithmic
scales and existing select/row-slice/rename/registered-unit-conversion bindings.
Derived calculations, normalization, stage assembly, multiple panels and ambiguous scale choices
need their own supported scientific operation. Legacy native authority is retained;
it cannot be silently converted by this operation.

The original file may also supply a previously unused response-column pair.
Give that projection a new source ID and retain the file's complete current SHA,
worksheet and metadata rows. A response column whose physical rows overlap an
existing curve is rejected, including hidden curves and renamed bindings.
Changing sample text or a display alias does not create a new observation.
An independent Test in that same file also needs one exact, complete physical
block returned by source inspection, with its own metadata rows and range.
Keep its literal Test name in `sample`; use `label` for display text. Partial,
shifted, ambiguous or cross-Test regions cannot establish this permission.

First request original metadata through the same public patch, supplying only
the new source ID and absolute path:

```json
{"plot_id":"RETURNED_PLOT_ID","base_revision":0,"idempotency_key":"append-file-B","intent_class":"scientific","changes":[{"op":"set","target":["RETURNED_VIEW_ID"],"property":"source.append","value":{"source":{"source_id":"raw:B","path":"/absolute/file-B.csv"}}}]}
```

Submit it with `plot patch PLOT --request REQUEST.json --json`. The
`managed_append_source_confirmation_required` clarification returns
`repair.source_sha256`, original worksheet dimensions, candidate table regions
and literal column indices/headers/units/samples/conflicts. It returns no numeric
arrays and confirms no experiment identity. `repair.next_step` supplies required
fields and a value template. This read allocates no semantic transaction, changes
no revision/native/delivery, and leaves the same idempotency key available.

Choose the exact original region and coordinate indices from those facts. Complete
the same request using `value.source.sha256`, `value.source.table_selection` and
`value.curves`, for example:

```json
{"source":{"source_id":"raw:B","path":"/absolute/file-B.csv","sha256":"CURRENT_SHA256_FROM_CLARIFICATION","table_selection":{"sheet":null,"header_rows":[0],"unit_row":1,"sample_row":2,"data_start_row":3,"data_end_row":100}},"curves":[{"sample":"ORIGINAL_OR_EXPLICIT_SCIENTIFIC_SAMPLE","x_column_index":0,"y_column_index":1,"label":"Cooling B","color":"#cc3300","line_width_pt":1.3}],"source_context":"The user states this is the cooling acquisition; retain original XY values."}
```

Every row bound is zero-based and the end is exclusive; the example bounds must
be replaced with the returned original region. The program constructs bindings
and layer IDs from those original columns. Do not transcribe a FigureTemplate
or numeric arrays. An absent original sample needs an explicit scientific sample
identity; `label` is optional display text. Source context is retained as a user
statement attached to the appended source, without replacing the creation intent.

Quantities must match the existing scales. Spelling-equivalent units retain
the same numeric values. A registered numeric conversion requires an explicit
curve `x_unit` or `y_unit` exactly equal to the current axis unit; source units
remain bound to original metadata and the conversion is recorded in preview
evidence. An absent target-unit field does not authorize numerical conversion.
Missing metadata requires
the source-bound `metadata_confirmations` contract; declarations cannot overwrite
conflicting raw facts. Original row order, gaps, duplicates and each source's
independent length remain intact. Figures with endpoint rules retain each
endpoint's explicit auto/fixed choice: auto endpoints follow the visible plotted geometry,
and fixed endpoints remain fixed. Existing manual ticks stay exact; a conflict
rejects the candidate instead of silently dropping ticks or clipping observations.
Historical figures without explicit auto rules retain their saved numeric windows.
A requested domain change uses the existing `scale.domain` contract.
Logarithmic axes use the existing complete-data validation, which rejects
nonpositive observations without deleting or shifting them.

A complete request returns `needs_review`, `before_preview`, the candidate
`preview`, scientific audit and added-layer evidence. View both images and submit
the returned `plot.decide` request under the existing user authorization. Rejection
keeps the original head. A changed source blocks acceptance; resolve it before
continuing. Retransmit the identical complete request/key after a lost reply, or
follow its resume/export continuation. A new append uses a new key and current
revision. General rollback across scientific revisions remains unsupported.

After acceptance, cold open/edit/export continues from that same Managed plot.
View the final TIFF and deliver the returned PDF, TIFF and editable native file.
