# Independent XY ranges: implementation and evidence

Recorded 2026-09-10. Installation/release acceptance is deferred at the user's
request. This record covers data mapping, native creation and source updates.

## Implemented contract

Every pair can supply a complete original `table_selection` and optional complete
`metadata_confirmations` list. Pair regions can differ in length, starting row,
metadata rows and worksheet within the same original file. Another worksheet
inherits no declarations. Disjoint vertical blocks can share column indices;
overlapping response rows cannot be assigned to different samples.

The existing DataMapping proposal freezes all choices and source hashes. Execution
and loading reconstruct each source view independently. The rectangular effective
CSV leaves both cells empty after a curve ends; individual CSVs contain only their
own measured points. Plan binding independently checks sample order and per-sample
point counts. Native creation and source update share this mapping and its checks.

Angle spellings `degree`, `degrees`, `deg` and `°` are equivalent without changing
numbers. Older explicit degree confirmations retain their original mapped headers.
Confirmation cannot relabel measurements requiring conversion or equate different
scientific quantities. Arbitrary conversion and new quantity support are not added.

Real specimen `FeⅠ-2` exposed a header matcher bug: ASCII tokenization reduced
`2θ` to `2`, so a sample number was mistaken for an angle. Axis matching now keeps
Unicode scientific letters. Original sample cells remain unchanged.

The same real case exposed two native precision losses: imports used 12 significant
digits and upstream Save used seven. New one-dimensional imports and the native
Save adapter now round-trip binary64 values. New ordinary/performance specs bind
`native_1d_numeric_encoding=float64_round_trip_v1`; their audits compare reopened
values exactly, without quantizing expected values. Historical specs keep their
old serialization contract; no existing document is silently regenerated. The
adapter changes only the native numeric format, without rewriting VSZ text or
modifying upstream files. This new guarantee covers one-dimensional datasets;
two-dimensional persistence retains its existing contract.

## Untouched independent workbook

- Dataset: [Bath 00402](https://researchdata.bath.ac.uk/402/), Bordeneuve et al.,
  DOI 10.15125/BATH-00402, CC BY 4.0.
- Download: `Open_Access_Dataset.zip`; exact member
  `Open Access Dataset/Open access XRD data.xlsx`.
- Workbook SHA-256: `4c2e92fbed7bb82fe5e79f457e0749e52769bd42e6540d45a69b9b83776b64ca`.
- Sheet1, zero-based X/Y columns 0/1 and 3/4. Original sample names are
  `CsCHA before TGA 700 oC` and `CsCHA after TGA 700 oC`.
- Data ranges `[2,3479)` and `[2,2747)` retain **3,477 and 2,745 points**.

Row 0 supplies exact sample names; row 1 retains the original `2THETA` and `PSD`
channel text. The caller inspected the original cells and the
[published Figure 2](https://ars.els-cdn.com/content/image/1-s2.0-S138718111730687X-gr2.jpg).
Its axes support diffraction angle in degrees and intensity in arbitrary units.
Applying that interpretation to the identically labelled before/after PSD channels
is a recorded external declaration, not a unit found in an original cell. No
instrument code was silently replaced, and original values, including negative
background values, remain unchanged.

Public CLI trace:
`task capabilities → on-demand create schema → task start → table-region →
table_selection → metadata_confirmations → independent pairs → native create/export
→ cold task inspect → native preview`.

Evidence under ignored `.tmp_verify/independent_ranges/`:

- `run_real_case.py`, `commands.json`, numbered CLI requests/responses and `real-case.json`.
- `verify_real_integrity.py`, `integrity.json`: every original X/Y value and its
  order equals the spec, native Veusz datasets and delivered CSV. The original
  archive is byte-identical, and delivered VSZ equals canonical VSZ.
- Canonical/delivered VSZ SHA-256:
  `d6ab3add9de5b52ba7c98ac76ac564b9c4e984f3cfea4aabd59421cd6e8e6d14`.
- `native-preview/current.png`, `export-review.png`, `visual-review.json`: both
  curves, sample labels and axes are visible without clipping. This was an
  uncalibrated screen review, not final-size human readability acceptance.

## Public natural workbook revision

[Mendeley c9jtdd9ff5 version 1](https://data.mendeley.com/datasets/c9jtdd9ff5/1)
and [version 2](https://data.mendeley.com/datasets/c9jtdd9ff5/2) are the author's
published workbooks, downloaded without cell edits:

- `All Research data_ZQ20250618.xlsx`, SHA-256
  `50a8c842b1a548dff9b0221277bc4345d1bd77aab4eb7b48e10e71bec339aaa6`.
- `All Research data_ZQ20251229.xlsx`, SHA-256
  `e0016dd1883db22265293b79a3112418e59486276e45bb19247a3fe87f4ae694`.

Both hashes match publisher file metadata. The workbook revision changes tables
and P XANES records; the selected `XRD` sheet is identical. Original columns 0/1
and 0/2 preserve `FeⅠ-1` and `FeⅠ-2`, each with 4,779 points in rows `[1,4780)`.
The X header supplies degrees. The Y quantity and arbitrary-intensity unit are
external declarations from Figure 5, printed page 60 of the
[accepted manuscript](https://eprints.whiterose.ac.uk/id/eprint/236418/3/Accepted%20manuscript.pdf).
Original specimen cells provide identity. The full raw angular domain is retained;
the manuscript's displayed subset does not crop the input or assign phases.

The public task route requires fresh mapping for version 2 and a new observed-peak
choice despite unchanged XRD values. Review selects the strongest discrete maximum
within 32–35 degrees for `FeⅠ-1` (33.2087 degrees, intensity 123); the fixed 40-degree
reference stays in place. This tests a **natural whole-workbook revision with
unchanged selected measurements**, not a real peak shift or changed point count.
The real unequal Bath case and synthetic changed-value revision remain separate.

Evidence is under `.tmp_verify/independent_ranges/candidates/`. The first
`natural-revision/` run retains its coordinate-error recovery, corrected previews
and `integrity-failure.json`: 315 X values per curve differed in the native VSZ,
although raw cells, spec and delivered CSV matched. The precision repair is rerun
in `natural-precision/`; its final acceptance status is recorded in `integrity.json`.
The repaired run **passed**: both 4,779-point series match original cells, spec,
native GetData arrays and delivered CSV exactly; new and old raw archives match,
and current source/QA/delivery agree. Canonical and delivered VSZ SHA-256:
`68b9ea6e456ae35b533cde1f5b6157050b54766b018833adddcb2280b9fc1df4`.
Before/candidate previews and the final exported PDF were reviewed; annotations,
legend and axes are visible without clipping. This is uncalibrated visual evidence.

## Automated update and remaining acceptance

`tests/test_table_ranges.py` covers same-sheet and cross-sheet ranges, disjoint
vertical blocks, stale/tampered ranges, invalid bounds, worksheet-bound declarations,
conflicts, angle spelling, historical confirmation replay and adapter point loss.
Its native lifecycle creates unequal A/B curves (4/3 points, including long decimals), adds an observed peak
and reference line, changes to a separately generated cross-sheet revision (5/2
points), requires fresh mapping and peak rebinding, then exports. Native datasets
are read back and compared with the revised measurements; raw files remain intact.

This fixture is explicitly synthetic. The Bath before/after measurement columns
are distinct conditions in one workbook, **not a naturally revised file pair**.
Independent revisions that actually change unequal measurements or worksheet
arrangement remain useful additional acceptance; the published Zhou pair does not
cover these changes. Cross-sheet changed-value acceptance currently has native
automated evidence. Other inspected public candidates were not forced through:
`j3nf5ksgm6` has an orphan Y row and conflicting radiation metadata;
`3c5ym3gwn2` has a real cross-sheet layout revision but its instrument report says
`cps`, which cannot be relabelled as `a.u.`; `4fzjbrjvfg` changes XRD angle values
to an implausible scale. Those sources are not recorded as successful cases.

An additional bounded check compared [7s6zjz62v2 versions 1 and 3](https://data.mendeley.com/datasets/7s6zjz62v2/3)
and [4xg86pthpy versions 2 and 3](https://data.mendeley.com/datasets/4xg86pthpy/3).
The first workbook was renamed with identical publisher SHA-256; the second
dataset's XRD and TGA workbooks also retain identical hashes. Its changed
`Sulfate test data.xlsx` contains horizontal summary/repeated measurements, not
the supported XY-column layout. Downloaded sulfate hashes match both publisher
versions; no transpose, unit relabelling or substitute experiment rule was used.
Public `inspect` fails, and a diagnostic create task with `choose_columns:true`
pauses at the scientific-rule question without creating a figure. Original bytes
remain unchanged. Metadata, hashes, worksheet structure and before/after CLI
results are recorded in `candidates/additional-candidate-audit.json` under the
same ignored evidence root. These candidates do not close changed-measurement
revision acceptance.

## 2026-09-17 merged metadata and interrupted installation

The untouched Bath-01345 `Sintered titania XRD_MIP_Compression.xlsx` now completes
the public task route with `expand_merged_metadata:true`. Its SHA-256 is
`ece4b70a827b3b1e36716b449caf0c89d50716cba9992488556de08e94cf00cd`.
Selection uses original `XRD` header row 6, sample row 5, data rows `[7,4899)`,
and XY columns 0/1 and 2/3. Original merged sample headings supply the association;
the blank non-anchor cells remain blank in raw metadata and cell evidence.
No separate sample declaration is needed for this explicit merged selection.

Both Ti acrylate samples retain all 4,892 points. Every original X/Y value and
its order equals the spec, reopened native Veusz datasets and delivered CSV.
Archived raw bytes match the workbook, and canonical/delivered VSZ hashes are
identical (`2b282a9e458a0ac8603c4a7062783bf04c8f19833c3e89a46f92ab2f9dc8fac1`).
Cold inspection reports current source, QA and delivery. The exported TIFF was
visually reviewed for curves, sample labels, axes and clipping; this is an
uncalibrated agent review. Evidence: `.tmp_verify/speed_20260917/merged-real/`,
including requests/results, `integrity.json` and its verification script.

Native automated coverage adds merged numeric sample `8` and textual `009`,
preserving exact identity and three points per curve through mapping, creation
and cold export. Numeric metadata receives a versioned derived sample encoding;
unmarked numerical rows are not inferred to be sample rows. Merges crossing into
measurements are rejected. This numeric case is synthetic, not independent data.

Version-2 source-update intents record the complete old/new file inventories and
replacement names before installation. Tests interrupt every top-level rename
boundary, and interrupt rollback itself; retry restores the exact baseline and
preserves displaced candidate bytes and a rollback receipt. A native subprocess
test exits abruptly after archiving the active source, then retries through the
public task CLI and verifies revised native values plus current source/QA/delivery.
Unknown bytes, changed recovery records and legacy mixed states remain blocked.
Tests: `test_task_source_update.py`, `test_task_source_control_native.py` and
`test_table_metadata.py`; results are under the same speed verification root.

Independent changed-measurement unequal/cross-sheet revision acceptance remains
open. Existing user archives supplied for speed tests are original plotting
inputs, not an independently established natural before/after revision pair.
Synthetic interruption and numeric-label tests do not close that external item.
