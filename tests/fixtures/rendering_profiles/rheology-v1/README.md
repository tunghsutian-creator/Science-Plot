# Historical PP frequency-sweep golden profiles

These fixtures preserve the actual corrected 2026-09-18 user delivery for PP 3155 and PP-5UDC. They are not generated examples from the current Managed compiler.

| Profile | Historical editable native | Quantity | Data |
| --- | --- | --- | --- |
| `manifest-gp.json` | `FS_SciPlot_修正_20260918/project/studio_004.vsz` | Storage modulus G′ | 16 original points per sample |
| `manifest-gpp.json` | `FS_SciPlot_修正_20260918/project/loss_modulus_vs_frequency.vsz` | Loss modulus G″ | 16 original points per sample |

Original source directory: `/Users/dongxutian/Library/CloudStorage/OneDrive-HKUST(Guangzhou)/1 PhD/4 UDC/pp3155 udc`. Every file needed to run these tests is contained in this fixture directory; the original path documents provenance and is not a runtime dependency.

`historical-evidence/说明.md` and `原始数据核对.json` establish actual delivery and preserved raw data. Each profile retains its historical spec, the six-setting native color edit, and the outcome hash matching the delivered VSZ. The corrected sample colors are PP 3155 black and PP-5UDC blue. The historical companion spec did not synchronize these native color edits. Consequently the fresh legacy replay uses the original saved spec with exactly those six documented color changes, then calls the existing legacy production compiler.

The accepted VSZ, original PDF/TIFF and raw UTF-16 CSV files are byte-preserved. The `golden` PNG/structure/environment were captured once from that accepted native file, not from either freshly compiled route. Both historical delivered 300 dpi TIFFs have exactly the same pixels as the first current render of their immutable VSZ. The golden manifests have no update mode.

The old native axis stores `\omega (rad s⁻¹)` while the Managed axis stores literal `ω (rad s⁻¹)`. The manifest pins the Veusz symbol-table source proving that both paint the same U+03C9 character, and lists exactly the axis-label and painted-text paths involved. Comparison normalizes only those exact strings in memory. Original structures and their encoded differences are retained. This exception requires **zero actual pixel differences**, even below the usual antialias tolerance; other commands, glyphs, units, paths and renderer versions are rejected. The pinned golden files are never rewritten.

The numeric CSV fixtures are literal selections of raw zero-based rows 10–25 and columns 3/4 (G′) or 3/5 (G″), preserving all values and their order. Tests compare every selected point to both the original raw CSV and original historical spec before rendering.

`test_rheology_family_profiles_native.py` first checks the accepted native against the fixed golden and pinned environment. Only then does it build a new legacy native and a ManagedPlot, compare both to the independent golden, and delete/rebuild the Managed backend artifacts. The Managed request uses semantic axis runs for the italic G variable; the canonical schema contains no Veusz markup or native paths. Native paths exist only in the explicit test projection.

These profiles cover fonts, original scientific labels, major and minor logarithmic ticks, sample colors and marker identities, line and marker opacity/strokes, legend membership/geometry, physical layout, exact data arrays, export metrics, and raster differences. They do not assert dual-axis equivalence, TTS/fitting behavior, derived viscosity correctness, or universal rheology-family coverage. The selected historical package has separate G′, G″ and tan δ plots; no dual-axis golden was manufactured for this test.

Full native inventory is retained separately from the currently drawn structure. Each profile reports six latent width differences on hidden grid/border channels (historical inherited 1.2 pt, current 0.5 pt) and the two omega encoding differences. These are not represented as byte-identical native state. The pass guarantee concerns the current scientific drawing, its geometry and exact pixels; it does not promise identical future behavior if arbitrary hidden native settings are manually enabled.

Run the two source audits with `pytest tests/test_rheology_family_profiles_native.py -m 'not comprehensive'`. Run actual native profiles with the same test file and `-m comprehensive` in a supported native rendering environment. Font or renderer changes must fail the fixed environment gate and be reviewed explicitly; the fixture must not be regenerated merely to make a test pass.
