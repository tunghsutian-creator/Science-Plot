# Reading a performance radar

The `performance_comparison` rule's `polar_curve` figure keeps the source's
`RadarOrder`, `Unit`, `Direction`, `ScaleMin`, and `ScaleMax`. It does not choose
new bounds from the observed minimum and maximum.

Each axis shows its metric name, original unit, declared raw range, and direction:
`↑` means a higher raw value is better; `↓` means a lower raw value is better.
The outer endpoint number is the original-unit value at radius 1, not a second
normalized measurement. For a lower-is-better metric it is `ScaleMin`.

The radius is dimensionless and uses the existing declared-bound formulas:

- Higher is better: `r = (value - ScaleMin) / (ScaleMax - ScaleMin)`.
- Lower is better: `r = (ScaleMax - value) / (ScaleMax - ScaleMin)`.

Radius 0 and 1 are the declared endpoints, rather than the worst and best
observed samples. Intermediate radii are linear fractions within those bounds.
The filled polygon links the separate axes. Its area is not an overall score;
changing axis order can change area without changing a single measurement.

Negative values are retained when they lie within the declared bounds. Equal
observations retain their original radii; zero-width declared bounds and values
outside the bounds fail validation. A sample needs every radar metric for its
polygon. A reference may have incomplete metrics and remains marker-only at its
available axes; missing reference values are never filled or interpolated.
Every original metric needs a nonempty declared `Unit`.

New radar figures reserve the existing 60 mm presentation panel for material
identities and interpretation notes. The plot panel stays 60 × 55 mm with the
original 41.5 × 38.5 mm science frame. A one-column page is 120 × 55 mm, including
the two-sample case that previously used a 60 × 55 mm page. Existing figures with
a reserved panel keep their page dimensions. An explicit conflicting page size
fails before generation; it is not silently overwritten.

Axis text stays at the governed 6 pt size. Four- and five-axis figures wrap long
Latin and Chinese labels in physical text slots. A label that cannot fit fails
with `performance_radar_label_space_insufficient`; supply a shorter
`DisplayLabel` and retain the original `Unit`, bounds and order. An overcrowded
material panel fails with `performance_radar_legend_space_insufficient`; use
the existing source-declared legend columns or identities.

The VSZ remains a native editable Veusz document. Existing saved figures retain
their exact-current native appearance when re-exported; the new display contract
does not regenerate or restyle them.

For a source-bound new radar through the existing public CLI:

```bash
skill/scripts/sciplot render performance.csv --template polar_curve --auto --out SOURCE_SciPlot
```
