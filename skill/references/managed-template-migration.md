# Reusing a legacy template as a Managed template

First identify the input:

- A saved legacy VSZ is not a template. Open or redraw it without editing it. For a supported saved Cartesian XY figure, `sciplot project legacy-convert FIGURE --out NEW_DIRECTORY` creates a separate Managed copy. It refuses figures with settings it cannot preserve.
- An old `plot create` request with `mode: legacy` is a template recipe. The same frozen request and key may finish an existing operation; they cannot start a new one. Named workflow recipes under `sciplot recipe` and legacy workflow JSON are different interfaces, not reusable PlotTemplates.

For a Cartesian template that uses known scientific and visual settings, reauthor
the **request**, not the saved old project:

1. Retain its exact original paths and source hashes, original table bounds,
   literal headers and columns, units, samples, and stable series IDs. Use a new
   creation key and a separate output.
2. Make layout explicit: canvas size/margins, both axes (units, limits and ticks),
   legend, annotations, background and one line/marker style per slot. Include
   matching semantic object IDs for both axes, the legend and any annotations.
   The native compatibility recipe's empty layout represented renderer defaults,
   not actual Managed settings.
3. Use `presentation.export_configuration: {"formats":["pdf","tiff_300"]}`
   and omit `mode` or set it to `managed`. Run
   `sciplot plot create --request MANAGED_REQUEST.json --json`.

The paired UV–vis migration test exercises this path with two named series, their
exact measured values, axis units, slot IDs, theme line widths and per-series
colors. Reauthoring a template is **not** reproduction of an old physical drawing:
if its old layout or appearance matters, specify the observed settings rather
than infer them, or redraw the original saved VSZ.

Do not invent replacements for unknown native widgets, dynamic native scripts,
specially authored fills or layout outside the Cartesian schema, or unregistered
scientific transforms/guards. Only use FigureTemplate v2 when its explicit
marks, scales, composition, and executors represent the intended behavior.
