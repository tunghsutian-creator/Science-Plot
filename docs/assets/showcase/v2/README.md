# Gallery data

These eight examples use **synthetic data**, rendered with SciPlot / Veusz and
exported as complete PDF pages before conversion to 300 dpi PNG. They illustrate
plot types, not measured material properties.

Standard figures are **60 × 55 mm** (709 × 650 px); performance figures are
**120 × 55 mm** (1417 × 650 px).

| Figure | Data | Source and settings |
| --- | --- | --- |
| [Spectra](spectra/spectra-rich.png) | Five curves, 601 points each | [CSV](spectra/spectra-rich.csv) · [Settings](spectra/options.json) · [Manifest](spectra/manifest.json) |
| [Stacked spectra](curves/stacked-spectra.png) | Five curves, 600 points each | [CSV](curves/stacked-spectra.csv) · [Settings](curves/stacked-spectra.options.json) · [Manifest](curves/manifest.json) |
| [Rheology](curves/rheology-point-lines.png) | Five curves, 16 points each | [CSV](curves/rheology-point-lines.csv) · [Settings](curves/rheology-point-lines.options.json) · [Manifest](curves/manifest.json) |
| [Distributions](distributions/replicate-distributions.png) | Five samples, 10 replicates each | [CSV](distributions/data/synthetic-replicate-distributions.csv) · [Settings](distributions/requests/replicate-distributions.json) · [Manifest](distributions/manifest.json) |
| [Composition](distributions/composition-bars.png) | Five formulations, two components | [CSV](distributions/data/synthetic-composition-bars.csv) · [Settings](distributions/requests/composition-bars.json) · [Manifest](distributions/manifest.json) |
| [Response map](distributions/response-heatmap.png) | One continuous field, 61 × 41 grid | [CSV](distributions/data/synthetic-response-heatmap.csv) · [Settings](distributions/requests/response-heatmap.json) · [Manifest](distributions/manifest.json) |
| [Performance scatter](performance/performance-scatter-rich.png) | Sixteen materials in four groups | [CSV](performance/performance-scatter-rich.csv) · [Request](performance/scatter.request.json) · [Manifest](performance/manifest.json) |
| [Radar comparison](performance/performance-radar-rich.png) | Three complete samples and three incomplete references | [CSV](performance/performance-radar-rich.csv) · [Request](performance/radar.request.json) · [Manifest](performance/manifest.json) |

## Reading the figures

Spectra are smooth synthetic curves. Stacked spectra use a vertical display offset;
the source CSV retains the unshifted values. Rheology uses 16 supplied points per
sample with logarithmic axes and no fitted values.

Box plots show the median, interquartile range, whiskers and all 10 observations
per sample. Composition has two components, Polymer and Modifier, totaling 100%
for every formulation. The continuous response field is a mathematical illustration.
See the [data notes](distributions/README.md) for formulas and component definitions.

Scatter envelopes show group ranges, not confidence intervals. The radar contains
three complete five-metric profiles and three reference datasets with 3, 3 and 2
available metrics. References use unconnected hollow markers; missing values are
neither filled nor interpolated. Each radar axis has its own declared range and
direction. Polygon area is not an overall performance score.

## Reproduce

Run `skill/scripts/sciplot doctor --json` from the repository root, then follow the
commands in the corresponding manifest using fresh output directories. Convert
the resulting complete PDF page with:

```bash
pdftoppm -png -r 300 -singlefile INPUT_PDF OUTPUT_PREFIX
```

[SHA256SUMS](SHA256SUMS) identifies the published data, settings and images.
Run `shasum -a 256 -c SHA256SUMS` in this directory to check them. Exported bytes can
vary across platforms and dependency versions.

The [cover](../../sciplot-banner.png) combines full native figure pages in an
[editable SVG](../../sciplot-banner.svg). Rebuild it with:

```bash
QT_QPA_PLATFORM=offscreen .venv/bin/python docs/assets/build_banner.py
```

The [earlier gallery](../README.md) is retained as an archive.
