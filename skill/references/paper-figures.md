# Selected figures across projects

`task paper start --group` packages saved figures in group item order and
registered figure order. It selects the originals, not exported copies.

```bash
skill/scripts/sciplot task paper start --group GROUP_DIRECTORY --out NEW_OUTPUT --paper-dir NEW_PAPER_TASK --json
```

Use repeated `--item-id ID` to select items in that explicit order and
`--title TITLE` to override the group title. A single figure uses its group
label, normalized to a safe filename; a multi-figure item adds its figure
title or a stable ID.

- A Managed selection binds each figure's canonical `plot`, `plot_id` and
  current `revision`, including each registered frequency figure in order. It
  uses the [Managed delivery](managed-delivery.md) publisher. To deliver only
  a non-primary member alongside other selected Managed plots, use that route
  with an ordered explicit `plot deliver` request.
- A Legacy selection retains the saved native version and existing paper
  publisher. Its creation, presentation and export child tasks must finish.
- Mixed Managed and Legacy figures require separate packages. Neither route
  advances group tasks, accepts a pending review, or redraws a missing export.
  Follow the failed figure's recovery advice and retry when its exact saved
  export is current.

The paper checkpoint freezes the selection once. Repeat the same start command
or use `task paper inspect` for a read-only status check; `task paper resume`
retries that frozen request. A different selection, order or revision needs
both a new checkpoint and a new output. A completed package is a frozen
snapshot; its original figures may subsequently advance. Inspection checks
current originals and the published byte inventory without a fresh native audit.
The Legacy `--request` format and its original start/inspect boundary are
unchanged.

For an explicit **Legacy** cross-project selection, use the existing v1 wire:

1. Query existing projects with `project inspect` for their registered figure IDs.
   Read the selected version with
   `sciplot task paper capabilities --project PROJECT --figure FIGURE_ID --json`.
   Copy `project`, `figure_id` and `expected_version` into each request item; add
   a safe unique `label`. The full request schema is returned by
   `sciplot task paper capabilities --json`.
2. Write the explicit list following [paper-figures.json](paper-figures.json).
   `items` array order is the paper order. Stems are `001_LABEL`, `002_LABEL`,
   and so on. Labels accept ASCII letters, digits, `_` and `-` and must be unique
   including case. `out` is a new caller-selected external directory outside all
   original sources, native imported data, projects and deliveries.
3. Run `sciplot task paper start --request REQUEST_JSON --paper-dir PAPER_TASK
   --json`. Keep the task receipt outside source/project/output directories.
   Development requests, checkpoints and outputs belong under ignored
   `.tmp_verify/`; ordinary deliveries use the explicitly selected destination.
4. Inspect or retry with `sciplot task paper inspect PAPER_TASK --json` and
   `sciplot task paper resume PAPER_TASK --json`. Resume retains the same list,
   labels, ordering and exact source/document versions. Source, spec, figure ID,
   saved VSZ or sealed stage changes require inspection and a new selection.

Completed start replay, inspection and resume preserve the historical task
receipt and frozen selected versions.
It offers delivery only while both the complete package inventory and those
source versions remain current. Changed package bytes or members return a blocked
preserve-and-new-selection repair, with no overwrite. Changed original sources or
semantic/native revisions leave an intact package labelled historical and require
reviewing the changes before starting a new selection in a new output.

The package uses existing `figures/`, `project/` and `data/` delivery directories.
It contains one PDF, one `_300dpi.tiff` and one editable VSZ per selection,
selected plotted-data CSVs, `data/figure_sources.json`, a CSV source/version
index, and `Open_in_Veusz.command`. The manifest records exact original project,
figure, request/spec/VSZ/source versions, actual scientific and native state
seals, and portable document hashes. It is immutable delivery evidence, not
another scientific or editable document authority.

The original saved project is read only. Packaging copies the existing current,
QA-bound PDF/TIFF bytes from its sealed publication run. It never renders or
exports a figure merely to package it, regenerates data, reapplies edits or
changes an existing delivery. Missing/stale publication, export, request, native
or spec evidence returns `paper_publication_unsealed`/`paper_publication_changed`;
finish the original export explicitly before making a new selection. A sealed
publication must also have completed its original rule, QA and delivery gates;
a passing artifact QA inside an unfinished or blocked publication is insufficient.
A missing completion record blocks capture rather than being assumed successful.
Its complete file inventory is guarded during capture, retries and
publication. Native Save, source inspection and scientific audits still execute;
this route does not claim zero native calls.
Current saved native presentation, including legitimate manual styles, passes
through secure native Save and actual scientific audits. Registered canonical
project figures are supported; standalone VSZs, moved snapshots and ManagedPlot
artifact caches cannot acquire original-project authority. Unsupported or missing
ManagedPlot canonical bindings are not guessed or relabelled as legacy projects.

Actual native linked data join the exact source closure. Only inputs consumed by
selected documents are copied into `data/imports/`, and Veusz serializes relative
imports. Copies securely reopen with matching complete native state and scientific
audits while the sealed original PDF/TIFF bytes are copied unchanged. A moved package opens as an independent
portable Veusz copy without editing an original project.

Successful single figures are byte sealed in the task's private staging for exact
retry. Failed or uncertain attempts are preserved and new attempts allocated;
unknown files in sealed attempts block reuse. A complete package is privately
built and validated, then the existing exclusive atomic directory installer
publishes it without replacing even an empty destination. Lost-publication-reply
recovery recognizes only the frozen candidate with matching sources and complete
file inventory. Task completion, current sources, artifact QA, human review and
journal acceptance remain separate claims.

## CLI and MCP composition

`sciplot_core.cli.task_paper` provides `register_paper_commands(actions)` for
the shared task parser and `dispatch_paper(args)` for a `task_action == "paper"`
dispatch branch. MCP uses the same `task_papers` functions: `paper_capabilities`,
`start_paper`, `inspect_paper`, `resume_paper`. The closed JSON request schema is
owned by `task_paper_contract.paper_request_schema`.

The group CLI delegates through `task_paper_selection.start_group_paper`, then
the same strict `start_paper` owner. It reads hashed group/child receipts and
registered projects without the gallery/preview path. The frozen group origin
and four per-figure version guards remain in the paper receipt. This is an
ordered delivery, never an atomic edit across plots. MCP's existing explicit
paper request contract remains strict; no generic JSON execution surface exists.

CLI and MCP use these owners directly. Ordinary user instructions use the
shared `sciplot task paper` entry above.

## Development verification

The registered local-task owner includes the paper modules and public adapter,
`tests/test_task_papers.py` and `tests/test_task_papers_native.py`. Generic
`delivery/install.py` retains delivery-integrity coverage, and the old
`workflow/rheology_tts_creation.py` seam retains prepared-creation recovery
controls. Synthetic native cases use the supported shared CLI. Real private-source
acceptance remains separate ignored evidence; no private inputs are committed.
