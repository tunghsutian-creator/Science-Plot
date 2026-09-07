# Distributions, composition and response fields

These synthetic examples are rendered by SciPlot's public CLI as native, editable Veusz figures. Full PDF pages are converted to 300 dpi PNG with Poppler, without cropping or retouching. Every figure is 60 × 55 mm (709 × 650 px).

| Figure | Data | Meaning |
| --- | --- | --- |
| [Distribution](replicate-distributions.png) | 5 samples × 10 observations | Tensile strength (MPa): median, IQR and all 50 observations |
| [Composition](composition-bars.png) | 5 formulations × 2 components | Polymer (Pol.) and Modifier (Mod.) mass fractions, totaling 100% per formulation |
| [Response field](response-heatmap.png) | 61 × 41 coordinates | One continuous synthetic conversion field; retained unchanged |

All data are illustrative, with no experimental or literature performance claims. The two-component compositions are a redesigned synthetic example: Modifier combines all non-polymer fractions. Polymer/Modifier percentages are A: 82/18, B: 69/31, C: 62/38, D: 56/44 and E: 42/58. Components are additive fractions, not statistical replicates.

[generate_data.py](generate_data.py) deterministically writes LF-terminated CSVs and public render options; it does not draw figures. Distribution values use `random.Random(1729)`, with `(mean, standard deviation)` pairs `(32, 4)`, `(47, 6)`, `(64, 7)`, `(79, 8)` and `(96, 7.5)`, ten observations each, rounded to three decimals.

The unchanged response field uses `100 × (1 − exp(−t × 0.015 × exp((T − 150) / 23)))`, sampled every minute over 0–60 min and every 2 °C over 120–200 °C. This is an illustrative formula, not a fitted kinetic model.

[manifest.json](manifest.json) records sources, hashes, commands, native documents and QA evidence. Use a new output directory when reproducing. Current distribution and composition evidence is in `.tmp_verify/github_showcase_v3/distributions/`; unchanged heatmap evidence remains in the manifest's v2 location. All source values and hashes match the native specifications, render QA has no issues, and final-size labels and legend spacing have been reviewed.
