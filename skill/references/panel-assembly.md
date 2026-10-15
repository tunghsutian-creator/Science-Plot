# Arrange existing figures and images

Use `skill/scripts/sciplot compose open` for the native local workbench. Select
saved figures across projects or add a PNG, JPEG, single-frame TIFF or one-page
unencrypted PDF diagram. Drag whole panels; set rows/columns, spans, horizontal
and vertical gaps in mm, and automatic or custom panel letters. Cropping applies
to images without changing source bytes. Undo/redo includes layout operations.
Save a layout JSON and reopen it with `compose open /absolute/layout.json`.
Replacing a source keeps placement. Use the current source version explicitly
when it changed; export refuses stale references rather than silently rebinding.

For AI layout intent, read `compose capabilities --json` once, then use the
closed operation contract with the returned revision:

```bash
skill/scripts/sciplot compose new /absolute/layout.json --rows 2 --columns 2 --width-mm 180 --height-mm 140 --json
skill/scripts/sciplot compose apply /absolute/layout.json --expected-revision 0 --operations @/absolute/operations.json --json
skill/scripts/sciplot compose inspect /absolute/layout.json --json
skill/scripts/sciplot compose export /absolute/layout.json --out /absolute/new-package --dpi 300 --json
```

`operations.json` is an array, for example:

```json
[{"op":"add_panel","panel":{"id":"micrograph","source":{"kind":"image","path":"/absolute/SEM.tiff"},"row":0,"column":0}},{"op":"set_spacing","gap_x_mm":6,"gap_y_mm":8}]
```

Project references identify the saved project and exact figure ID. Managed
references identify the canonical document root and exact plot ID. The native
project chooser resolves the correct authority. An attempted legacy reference
to a canonical ManagedPlot returns its managed reference without converting it.
Source versions are captured locally on add/replace. Ordinary layout operations
read no scientific source and call no model. MCP exposes the same owner through
`sciplot_compose_capabilities` and `sciplot_compose` (new/inspect/apply/export).

Legacy VSZ remains the visual authority. Managed semantic documents, sources and
transforms remain authoritative; absent native caches are rebuilt in temporary
storage. Supported simple native Cartesian panels reflow at the allocated mm
size and retain data, axis ranges and point typography. Unsupported geometry,
impossible margins, clipped scientific text or legends stop export. Resize the
layout or repair that source through its existing editing route. Never stretch
a scientific PDF to make it fit. A source preview is display-only and may show
a figure whose requested export size fails native QA.

The new export directory contains PDF/TIFF, saved layout, manifest, source copies
and editable native files. Keep original source roots for layout re-export;
portable VSZ/import copies support native manual editing, but relocated layout
references are not automatically rebound. Custom outer panel letters use up to
16 printable ASCII characters (empty hides, null means automatic); scientific
labels inside plots retain their existing text contract. Font portability and
journal acceptance require their own evidence. Original files stay unchanged.
