# Find and continue saved work

Use this when the original source or saved project may have moved, been renamed,
or been copied. Keep the existing exact-path `task find SOURCE --json` behavior
for known historical creation receipts.

The additive public adapters use:

```bash
sciplot task find SOURCE --search-root PROJECT_OR_DATA_FOLDER --json
sciplot task continue SOURCE --search-root PROJECT_OR_DATA_FOLDER --json
sciplot task continue SOURCE --search-root FOLDER --target EXACT_RESULT_TARGET --json
```

Repeat `--search-root` for a small set of known folders. No global filesystem
scan or persistent index is created. Each search visits at most four descendant
levels and 2,000 entries, and stops descending inside a recognized saved
authority. Incomplete searches and invalid records remain explicit. `--limit`
changes only the displayed result count; it does not remove ambiguity.

The source hash only filters candidates. A candidate identifies its saved
request, figures, native/specification hashes, scientific-source state and any
historical task. A known stale source, visible-edit recovery or foreign delivery
owner can retain a blocked candidate before semantic evaluation. In that case
`semantic_documents_evaluated=false` does not certify a semantic revision or its
currentness, and does not authorize editing. A potentially usable candidate must
still pass the complete current-authority checks. A filename or similar title
cannot bind a project. Multiple projects, including identical copies, require an
exact target selection.

Ordinary projects may retain original raw snapshots in their existing
`study_model`, with a prepared directory as `input`. A copied or renamed external
file can match that exact raw-file seal. Continuing uses the preserved recorded
raw and prepared sources; it does not replace them with the file used to search.
When an exact historical source path has different bytes, the search reports a
source revision rather than treating the older saved plot as that new data.
For a confirmed column mapping, the original source seal remains distinct from
the effective table seal in the FigurePlan; both retain their own currentness
checks.

`task continue` reads the selected current authority again and rechecks the
search source after the final authority read. If that input changes, disappears
or becomes a symlink, `source_changed_during_continuation` requires a fresh find;
it returns no obsolete editing arguments. For a LegacyPlot it
uses the saved VSZ, actual native inspection and the existing native scientific
audit. It returns a current `task.start` edit request template and `task.style`
target arguments. Fill the template's operations with the authorized edit; the
existing preview, acceptance, revision and export owners perform the change.
An older Legacy semantic revision can remain stale after legitimate native saves. Discovery
may establish saved-VSZ continuation from a complete applied edit chain, checking
each reviewed identity, native/spec archive and unchanged source baseline. It
reports that evidence separately and leaves that revision unchanged. Attached
semantic evidence comes from the current project generation; an obsolete physical
shadow cannot replace a missing or invalid attachment.
Missing, pending, tampered or discontinuous history cannot establish that bridge.
For a ManagedPlot it checks the sealed head, canonical model, complete recorded
input closure and pending transaction, then returns `plot.open` arguments for
the existing document editor. Missing disposable native artifacts retain
semantic authority and are rebuilt by the existing export owner.
If only the selected original source file has changed bytes at its recorded path,
continuation returns `plot.open --scope summary` for the same saved figure. Its
summary points to the existing `source.sha256` review. Inspect and authorize the
change there before editing or exporting.

An exported delivery is separately identified as a snapshot unless the existing
launcher owner proves its canonical project binding. Modified visible copies or
extra native documents require visible-edit recovery. A copied project still
pointing to another project's bound delivery is blocked, so its later export
cannot silently overwrite the original handoff.

Missing/stale scientific files, external native saves, copied ManagedPlot roots
with original absolute bindings, malformed paths, symlinks, incomplete receipts
and uncertain tasks fail closed. Studio source-revision guidance uses the existing
`update_source` request. That owner may require restoration of missing raw or
prepared evidence before it can create a valid review. Discovery never rewrites
old task/project paths, imports an unbound snapshot, replays a historical apply,
or recreates an absent project.

`status=current` on continuation identifies a current editing authority. It does
not certify delivery readiness: `ready_to_use` remains null and
`readiness_evaluated` remains false.

## Copy a diagnostic summary

Use `sciplot task continue SOURCE --search-root FOLDER --shareable-diagnostic`
to print only the copyable diagnostic JSON instead of the detailed result.
It reports the continuation status, a known reason code, and a next step
without paths, figure or sample names, values, or local diagnostic contents.
The command does not create a report file or send anything. Copy the JSON if
you choose to share it; keep the ordinary result and terminal log local.

## Adapter integration

`sciplot_core.task_saved_work.find_saved_work(source, search_roots=..., tasks_root=..., limit=...)`
implements the bounded additive find entry. With no `--search-root`, retain
`task_discovery.find_tasks` for backward compatible exact-path find. The default
continuation scopes are the source-adjacent named workspace, delivery, task
history and `.sciplot_documents`, not their entire parent directory.

`continue_saved_work(source, search_roots=..., tasks_root=..., target=..., figure_id=...)`
implements the continuation entry. CLI and MCP adapters should convert wire
paths to `Path` and forward the exact returned arguments to their existing
owners. `needs_selection` requires an exact target; `blocked` requires its
reported repair. No task request/response schema change or persistent catalog is
needed. CLI flag registration and MCP tools are composed in the shared adapters.

Focused verification is `tests/test_task_saved_work.py` plus the existing exact
find/project-query coverage. The one native continuation acceptance is
`tests/test_task_saved_work_native.py` (comprehensive): it checks copied-source
discovery, actual editing with returned arguments, scientific audit, original
byte preservation, explicit duplicate selection, copied-project output
protection, a real source-update review and missing-raw rejection.

## Relocate an existing Store

The daily MCP profile has three different paths. Use `sciplot_plot_deliver` to
hand off snapshots for a paper. Use Store relocation to edit the same project
from a new location. Use Save As to make a separate editable copy of one figure.

Use the exact root of an already versioned Store, not a figure handle, raw
VSZ, task directory or paper package. Choose new paths under existing research
directories:

```bash
sciplot project bundle-export STORE_ROOT --out NEW_BUNDLE --json
sciplot project bundle-import BUNDLE_ROOT --out NEW_PROJECT_PATH --json
```

In daily or expert MCP, call `sciplot_project_bundle_export` with
`project` (the exact Store root) and `output_dir` (a new bundle directory).
Then call `sciplot_project_bundle_import` with the returned `bundle` path and
an unused `output_dir` for the project. Both tools use the same Store owner as
the CLI. The export receipt's `next_step` supplies the exact bundle argument;
choose the new project directory yourself. The import receipt supplies exact
`project.open` arguments for one registered figure or asks you to choose from
the returned figure IDs when there are several. A Store with no registered
figures reports that state rather than promising an editable figure.
Compare returned `project_id` and `generation` before continuing at the new
location. Use the returned `project` path to reopen it. Import preserves the
project and admitted history, without granting executor permissions or external
export destinations from another host. New exports stay with the moved Store;
use a new delivery destination for a visible package. An installed paper
snapshot still cannot recover the original Store.

If the original input path is gone, open the imported project directly rather
than using `task continue SOURCE`, which searches from a readable input:

```bash
sciplot plot open NEW_PROJECT_PATH --figure SAVED_PLOT_ID --scope summary --json
```

Use the returned plot handle to edit. The relocated Store supplies the exact
saved source versions. If bundle verification fails, use an intact verified
bundle. If an older project reports a missing unsaved source, restore that
exact source version before bundling. A same-named file or a paper snapshot
is not a substitute.

Keep using one active location for the project. This operation does not give
two independently writable identities and does not remove the previous
location. Export rejects unadmitted project changes. Neither command replaces
an existing destination; inspect any path left by an interrupted operation
before choosing a new destination.

### Save the same project as one `.sciplot` file

```bash
sciplot project bundle-export SAVED_PLOT_OR_STORE --single-file --out NEW_PROJECT.sciplot --json
sciplot plot open NEW_PROJECT.sciplot --figure SAVED_PLOT_ID --json
```

With `--single-file`, you can pass the exact saved Managed v2 plot handle from
`task create` or `plot open`, or the exact Store root. Either input saves the
**whole project**, including its other figures, source versions and history.
The project and plot IDs do not change. Use `--expected-generation` to require
an already observed Store generation; otherwise SciPlot captures the current
admitted generation. The receipt identifies the new `project_file`, generation,
and archive SHA-256. Open that file directly; `bundle-import` is for directory
bundles. In daily or expert MCP, use the existing
`sciplot_project_bundle_export` with `single_file: true`, the `.sciplot`
filename in `output_dir` and optional `expected_generation`, then
`sciplot_project_open` with the receipt's `next_step.arguments`. If you
accidentally use bundle import on the file, the error gives the same direct-open
arguments and leaves the destination untouched. If there are multiple figures, specify the
exact plot ID when opening; saving does not select or discard any figure.

### Save the first ordinary XY figure

```bash
sciplot task create ORIGINAL.csv --x temperature --y heat_flow \
  --project-file NEW.sciplot --json
```

Use a new filename in an existing folder. This saves one editable project
file without exporting a figure or creating another project folder. In daily
or expert MCP, send a version 1 create request to `sciplot_task_start` with
`sources`, `intent` and the new absolute `project_file` path. Reopen with the
returned `next_step.arguments`. Leave source and project selection unchanged
when resuming a confirmed task.

### Append an independent ordinary XY figure

Add a figure from the original data directly. No intermediate plotting project
or request file is needed. First read the current project generation:

```bash
sciplot plot open FILE.sciplot --scope summary --json
sciplot task create ORIGINAL.csv --x temperature --y heat_flow \
  --append-to FILE.sciplot --expected-generation GENERATION --json
sciplot plot open FILE.sciplot --figure NEW_PLOT_ID --scope summary --json
```

Use `generation` from the open summary, or `repair.generation` when open asks which
saved figure to select. Use `result.plot_id` from the append receipt. Resolve any
ambiguity with the same task's returned response template; selection follows
ordinary XY, including explicit original headers or source blocks.

In daily or expert MCP, call `sciplot_project_open`, then `sciplot_task_start` with
a version 1 create request containing your `sources` and `intent`, and the fields
`append_to` (absolute .sciplot filename) and `expected_generation`. Pass the
receipt's `next_step.arguments` to `sciplot_project_open`.

Append modifies only the selected project file, preserves prior figures and
revisions, and creates no export. For a lost reply, repeat the same command or
resume the saved task with `--retry`. A new operation needs the current
generation. The older `plot append --request` and `sciplot_project_file_append`
interfaces still accept a previously frozen ordinary XY request.

### Add one original curve to an existing figure

For a saved ordinary XY figure in one `.sciplot`, open the exact figure first
and retain its plot ID, revision and project generation. Use the physical column
indices (zero-based; Excel column C is 2), not a repeated heading. Specify the
exact worksheet when the workbook has more than one matching table.

```bash
sciplot plot add-series FILE.sciplot MEASURED.xlsx --plot-id PLOT_ID \
  --revision REVISION --expected-generation GENERATION --sheet Measured \
  --x-column 0 --y-column 2 --sample 'Run B' --json
```

Read the planned selection. To confirm it, repeat the command with `--apply`,
`--plan-id` and `--source-sha256` from `apply_request`. MCP users call
`sciplot_project_file_add_series` with the same `target` and `request`, first
in `plan` mode and then passing the returned `apply_request`. The incoming
curve uses its own observed X grid. This saves one revision of the selected
figure without altering other figures or exporting. If the data or archive
changed, reopen and plan again. The exact applied request can be retried after
reply loss, even once the source is no longer at its original location.

### Replace the original for one saved curve

Use `plot replace-series-source FILE.sciplot REVISED.xlsx` with the same
`--plot-id`, `--revision`, `--expected-generation`, `--sheet`, `--x-column`,
and `--y-column` selectors as above, plus `--layer-id` from `plot open`'s
`edit_targets` instead of `--sample`. MCP uses
`sciplot_project_file_replace_series_source` with `replace_layer`. Plan first,
then apply the exact returned proposal. The new original must retain the same
worksheet, physical columns, row region and scientific metadata; a shared
original or changed layout needs a different operation. Only the selected
curve's version changes. Other curves and figures, and the old revision's
sealed source, stay intact.

## Make a new, independently editable copy

Use Save As for **one current Managed plot**, not for moving a whole project or
packaging figures for a paper. Read that plot's exact handle, ID and revision
first. If it is a member of a multi-figure project, identify the specific member
rather than just its parent project.

```bash
skill/scripts/sciplot plot describe PLOT --scope summary --json
skill/scripts/sciplot project save-as PLOT --plot-id ID --revision REVISION --out NEW_PROJECT_DIRECTORY --json
```

The destination must be unused and outside the original project, its data and
outputs. Save As creates a new project ID and plot ID, starting at revision zero.
It carries the selected plot's measured bytes, units, sample bindings and saved
presentation, not the old project's revision history or its paper exports.
The copied data stay bound even if the original files later move or change.
Open the returned new plot handle; use the ordinary edit and export commands
there. Retrying the exact same Save As after a lost reply returns the existing
copy, not a second one. Choose another new path to make another copy.

This command does not transfer executor permissions. Plots that declare
external executors are refused; restore or operate on them in their original
project. For a standalone old VSZ, use the explicit legacy conversion if the
old figure is supported. Moving an entire project with its history and same
identity is a different operation. In daily or expert MCP,
`sciplot_project_save_as` takes `plot`, `plot_id`, `revision` and `output_dir`.

### Save a separate standalone project

Use `project save-as-file` to give all current figures in a supported standalone
Managed project a new, independent home. Use the project ID and generation
from `plot open` (MCP `sciplot_project_open`):

```bash
skill/scripts/sciplot project save-as-file ORIGINAL.sciplot --project-id ID --expected-generation GENERATION --out COPY.sciplot --json
```

The new file contains the current figure state and all sealed source versions,
with fresh IDs and revision zero. Open any figure using its returned
`open_arguments`. Old revisions, permissions and regenerable render caches
stay behind. A project with unsupported assets or pending edits is refused as
a whole, and an existing destination is never overwritten. If a reply was lost, inspect the
destination before trying a different name. In daily or expert MCP use
`sciplot_project_file_save_as` with `target`, `output_file`,
`expected_project_id` and `expected_generation`.
