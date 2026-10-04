# Source-bound rheology TTS suites

`sciplot rheology plot --request REQUEST.json --json` draws an already processed,
source-bound numerical figure plan as a native Veusz suite beside the sources.
The external AI owns data processing and scientific decisions. The local plotting
program validates the prepared plan, applies its governed templates, and exports
the supplied coordinates faithfully. This entry point does not run TTS analysis,
shift fitting or Arrhenius regression. Ordinary frequency-sweep tasks retain
their existing `task start` route.

Before preparing a new suite or changing its presentation, read the live contract:

```bash
skill/scripts/sciplot doctor --json
skill/scripts/sciplot rheology capabilities --json
```

The external AI processes the data: it chooses and documents original sample/Test
identities, selected intervals, temperature corrections, fitting methods,
transforms, diagnostics and scientific comparisons. It prepares the final numeric
coordinates, quantities, units and scientific series roles, with source hashes
and a transform ledger. The program owns presentation defaults, dimensions,
native binding checks and export. Do not copy a markerless
generic-curve example into a measured frequency sweep, or restate marker sizes
and line widths independently in each AI-generated figure plan. Explicit user
style requests remain the authority for an intentional exception.

The live capabilities response includes the closed plotting-request schema and
its `contract_sha256`. Copy that hash into the optional
`expected_contract_sha256` request field to reject a changed contract. Plotting
does not accept arbitrary appearance fields; custom native edits remain
authoritative on exact re-export.

```json
{
  "version": 1,
  "prepared_plan": "/absolute/AI_processed_figure_plan.json",
  "out": "/absolute/UDC_Rheology_Figures"
}
```

Use the current advertised prepared-plan contract, including its source binding,
final numerical arrays, units, transform ledger and role/template declarations.
Do not send raw instrument files to this command expecting it to choose a model
or calculate a master curve. The AI inspects the data and calculation evidence,
writes the processed plan, then runs the plotting command and reviews the native
exports. Validation proves fidelity to that plan; it does not establish the
scientific validity of the AI's processing.

Creation commands return a compact receipt by default. Keep its delivery and
workspace paths for continuation, open its index, and review the listed native
export previews. Complete per-document audit/export evidence remains in the
returned manifest file. Use `--full` on `rheology plot` or the compatibility
`rheology tts` creation command only when that detailed response is needed;
do not repeat a successful creation just to obtain it. Read the saved manifest
instead. Compact output does not change numerical validation or artifact QA.

## Continue an interrupted prepared creation

For a failed **new prepared** creation, the first JSON error preserves its original
exception and adds `repair` guidance. When `repair.action` is
`resume_prepared_creation`, use the returned command with the same request:

```bash
skill/scripts/sciplot rheology plot --request REQUEST.json --resume --json
```

Resume binds the same request, output, plan bytes, original sources and compiled
template contract. It verifies completed native figures and continues only
unfinished work. A saved VSZ is exported from its existing bytes; it is never
recreated as a retry. The complete package is assembled privately and installed
only into an absent visible destination. If installation completed before the
last checkpoint update, a matching sealed package can be returned without
rendering again.

The guidance only recommends resume after the shared continuation guards pass.
It reads existing evidence without saving, exporting, installing or probing a new
lock. Changed or missing saved native files, conflicting visible files, uncertain
native-save states, a busy session and older partial workspaces without a trusted
checkpoint use `repair.action=inspect_creation_evidence`. Preserve the returned
request/workspace/checkpoint locations and the original failure for inspection;
do not delete a workspace or choose a new name merely to bypass that protection.
This is not an automatic migration or a recovery guarantee for arbitrary process
termination or power loss. A completed, subsequently edited suite uses
`rheology export WORKSPACE --json`, not creation resume. The combined legacy
`rheology tts` route has no new resume option.

Malformed prepared-plan objects or source-binding arrays stop before workspace
allocation or native rendering, with the invalid field path in the error. Correct
that input structure; the program does not repair, infer or rewrite scientific values.

Processing must preserve original Test identities, row indices, source hashes,
measurement order and status fields. Keep explicit display mappings separate
from source labels and retain excluded-interval reasons. Never invent missing
measurements or treat imaginary viscosity as complex-viscosity magnitude.

The delivered revised plan contains 12 independent core figures, two activation-energy
summaries, and 36 independent SI figures. Every document contains one graph, one polymer, and at most one
direct modulus channel. Diagnostics may compare methods or channel-specific shift
factors, clearly labelled. Core and ordinary SI figures use the program's standard
60 × 55 mm canvas; long method-comparison legends use its 120 × 55 mm preset.
The existing analysis delivery also includes Tables A/B/C, captions, a field
dictionary and an offline file index; those scientific reports belong to the
processing evidence, not an implicit calculation inside the plotting entry point.
An existing source-adjacent suite may contain a new revision child folder; its
hidden evidence uses a distinct path and previous files are preserved.

## Existing calculation and compatibility route

The delivered revised analysis reduces each modulus using the original point temperature:
`G_reduced = G_raw * (Tref_C + 273.15) / (Tpoint_C + 273.15)`. Density is assumed
constant because no density data are supplied. Original and reduced values remain
distinct fields. One horizontal shift per sweep fits both reduced moduli in log
space, over measured overlaps only, with equal pair/channel weight and no
additional fitted vertical shifts. Each sweep's mean measured temperature enters
the subsequent free-intercept Arrhenius regression. Its prediction at 210 °C is
subtracted from all independently fitted log shifts to set the reference origin;
this leaves slopes, residuals and relative shifts unchanged. A reference outside
the measured sweep-mean range is explicitly labelled an extrapolated normalization.
No 210 °C measurement is synthesized. Original frequencies multiplied by aT define
delivered master coordinates; separate FS210 measurements are never spliced in.

The older `rheology tts --request REQUEST.json --json` command remains a combined
analysis-and-plot compatibility utility. It is not the primary route for new
AI-processed work. Its request uses raw sources, sample/Test mappings and explicit
analysis options. Absent `analysis_options` and `figure_layout`, it retains the
legacy nominal-temperature, unreduced-modulus/interpolated-reference analysis
and combined figure plan for exact reproduction. Selecting the revised combined
calculation requires `temperature_basis=measured_mean`,
`modulus_correction=Tref_over_T`, `reference_normalization=arrhenius_postfit`, and
`figure_layout=separate_polymer_modulus`.
The old nominal/bT=1 calculations are retained as a method sensitivity in Table C,
and cannot silently substitute for the requested measured-temperature primary fit.

## Scientific roles and presentation defaults

The prepared suite resolves style from each series' scientific role. A panel
can contain different roles; choosing a single marker style for an entire panel
would confuse observations and model predictions.

| Plan role | Scientific use | Default presentation |
| --- | --- | --- |
| `measured_curve` | Original sweeps; derived viscosity, tanδ and van Gurp–Palmen traces | Template markers with connecting guide lines |
| `context_curve` | Full supplied traces surrounding an explicitly selected fitting region | Open shared-template markers and guide lines |
| `fitting_region_points` | Caller-selected coordinates used by a fit | Filled shared-template markers without lines |
| `master_points` | Shifted/reduced original TTS sweeps | Circle markers only, retaining each original isotherm as a separate series |
| `observed_shift` | Independently fitted Arrhenius shift estimates | Circle markers only |
| `regression_fit` | Arrhenius regression predictions | Solid lines only |
| `diagnostic_curve` | Shift-factor comparison traces | Method markers with connecting guide lines |
| `diagnostic_points` | Activation-energy sensitivity and TTS diagnostic estimates | Method markers only |
| `summary_bar` | Activation-energy summaries | Native bars |

Declare tanδ = 1 and other reference lines as native panel references, not as
measurement series. The program derives missing template IDs, series IDs and
presentation provenance from accepted role declarations. It rejects conflicting
templates and raw style overrides. It does not recalculate or sort coordinates.
Diagnostic roles require an advertised `semantic_id` for the method marker;
`summary_bar` also requires the native `kind: "bar"` declaration.
Governed plans use one panel per figure and the shared 60 × 55 mm or 120 × 55 mm
canvas presets. Missing dimensions, panel rectangle and standard-frame settings
receive program defaults. Arbitrary canvas sizes, disabled standard frames and
raw font, margin, marker or line overrides are rejected.

Marker size, marker outline and curve width come from the shared SciPlot policy.
The policy currently uses 2 pt markers, 0.8 pt marker outlines and 1.2 pt curves.
Default marker visibility is a role decision, not a consequence of whether a
series has a legend label: later TTS isotherms and fitted lines can both have
empty labels. A style-only repair must preserve the sample/color association,
point order and all source, fit and reduced-coordinate values. It must not join
overlapping isotherms into a fabricated continuous curve.

New separated-suite creation verifies native marker and line settings as well
as numerical arrays and bindings. The saved native document remains the visual
authority after delivery; generation defaults are not a reason to silently
undo subsequent edits.

For region-resolved pseudo-TTS, the AI supplies the complete reduced coordinates
and a separate fitting-window subset selected using the **original** frequency.
Pair `context_curve` and `fitting_region_points` with the same `color_index` to
share their color and shape. Supply all filled fitting-point series before the
context series: native Veusz siblings paint in reverse order, so this keeps the
filled points visible above the open context markers. The program never selects
the window or calculates shift factors.

Optional `series.error_values` supplies symmetric Y errors in the Y-axis units,
one finite nonnegative value per point. Zero is valid. Curves and native bars bind
these values directly to the saved Y dataset; native and CSV audits retain them.
The plotting program neither estimates uncertainty nor interprets it as replicate
variation. The caller supplies error semantics, grouped-bar X offsets and any
display-fit coordinates. For the processed pseudo-TTS package, main Ea values,
SEs, shifts, common slopes and reduced points stay frozen; excluded-temperature
diagnostics belong in a separately attributed AI-derived table.

## Inspecting and applying a style correction

For an existing suite, use its returned hidden workspace, not a new create request:

This bounded style migration supports `figure_layout=separate_polymer_modulus`.
A separated suite created with `rheology plot` needs no local `analysis.json`:
its AI-prepared coordinates, source bindings and transform ledger supply the
existing scientific evidence. If analysis files were supplied, the preview binds
and protects them too. Compatibility analysis suites still require their analysis
files. Missing legacy evidence is an error, not a reason to regenerate analysis.

```bash
skill/scripts/sciplot rheology style-preview /absolute/SOURCE/.sciplot/PACKAGE --json
skill/scripts/sciplot rheology style-apply /absolute/SOURCE/.sciplot/PACKAGE --preview /absolute/returned-preview.json --json
```

To include AI-prepared display-label or legend-position changes in the same
preview, supply a separate presentation-plan file:

```bash
skill/scripts/sciplot rheology style-preview /absolute/SOURCE/.sciplot/PACKAGE --presentation-plan /absolute/PLAN.json --json
```

The presentation plan follows the live governed-plan contract and may change
only series display `label` fields and supported panel `legend` positions relative
to the resolved current plan. Sources, scientific identities, numeric coordinates,
units, axes, transforms and series/point order must stay identical. The supplied
file must be separate from the suite's active plans. Its SHA is bound into the
preview and rechecked before apply; editing that file requires a new preview.

Temperature-label changes belong to the AI's explicit mapping. For example, an
original interval recorded as nominal 220 °C may display `220 °C` in place of its
measured mean `221.1 °C`; nominal 210 °C may replace `208.8 °C`. The AI verifies
each mapping against original interval metadata. The plotting program neither
rounds temperatures nor refits using the display values. Measured temperatures
and temperature-dependent calculations remain unchanged. Published plotting CSVs
retain their original scientific provenance labels; the current figure plan and
saved native document govern the updated display labels.

Inspect the concrete preview before applying it. The preview binds the current
saved document SHA, original-source hashes and the corresponding compiled
specification, plus the optional presentation-plan SHA, and returns its JSON path,
setting changes, candidate native files
and PDF/TIFF/PNG previews in a hidden preview directory. Inspect those rendered
candidates. Apply rechecks the suite manifest, all current native hashes, sources,
compiled specification, candidate hashes and export hashes; changed bindings
require a fresh preview. This prevents an old repair request from overwriting
a newer edit. A current native setting that conflicts with a targeted change
also stops the migration; unrelated native settings remain intact. Review belongs to the agent's normal verification
loop when the user has already authorized the style correction; it does not
require an additional human approval step.

This is a bounded migration to the governed template contract with optional
caller-supplied display labels and legend positions; the command does not accept
arbitrary custom styles or provide another general editing UI.
It edits the declared native presentation settings through Veusz. It does not rerun
the TTS or Arrhenius analysis, replace datasets, regenerate axes, or patch VSZ
text. Apply publishes the accepted candidate native files and their exact exports,
updates the active compiled specification, plan and delivery manifests, and keeps
backups for rollback if publication fails. Unchanged documents remain untouched.
A ready apply result already includes delivery; it does not need another creation
or fit. Reapplying the same preview is idempotent only after checking that its
applied result is still current. Later export-only recovery uses `rheology export`
and must not repeat an accepted native edit.

Full-window, individual-channel, measured-temperature and restricted-window
sensitivities remain separate evidence. Numerical RMS is not replicate
uncertainty; no strict TTS or bond-exchange mechanism is certified. A pooled
relaxation spectrum is not inferred when the joint superposition is inadequate.

The compatibility calculation remains in `semantic_sources/rheology_tts.py` and
reuses the ordinary instrument parser. It is not invoked by `rheology plot`.
The prepared-plan workflow validates the supplied scientific coordinates and
owns the suite lifecycle. `rheology_tts_spec/native/render` compiles shared
SciPlot style contracts and uses native Veusz creation, binary64 save/reload
audits and the existing exact-document export owner. There is no new renderer.

The suite has vector PDF, 300 dpi TIFF/PNG, numerical CSV/JSON and editable VSZ.
Visible `editable/*.vsz` files become the sole visual edit authority after
initial delivery; hidden creation documents are historical evidence. The
launcher opens SciPlot's native Veusz editor. The ordinary browser canvas's
single-graph audit is not advertised as supporting this specialized analysis suite.
Save and close native edits, then run `Update_exports.command`, or
`sciplot rheology export SOURCE/.sciplot/PACKAGE --json` to audit the original
arrays and re-export exact saved documents without refitting or regeneration.
Ordinary re-export records style deviations from the generated baseline and
preserves the saved style; it does not silently restore program defaults.
Suite export audits all saved documents in one native worker and stages every
new export under its hidden workspace. It publishes the complete candidate set
and both manifests through the existing rollback-capable file replacement owner
only after source, compiled-specification, saved-document and candidate hashes
agree. A later render failure leaves the current visible exports intact; an
ordinary publication exception restores the replaced files. Missing exports can
be recreated without replacing the saved VSZ. The workspace lease serializes CLI
suite operations; saved edits from an open native window are guarded by hashes.
This is not a process/power-loss atomic transaction or automatic crash recovery.
New source bytes require a new explicit analysis. Existing packages are never
silently replaced by a creation request.
