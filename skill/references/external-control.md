# External AI control of SciPlot

This is the public CLI operating guide for an external AI. Use SciPlot for local,
deterministic scientific preparation, native Veusz operations, validation and
delivery. The AI owns the user's task and interpretation; SciPlot does not need
an internal model provider, GUI selection, or a running browser.

Run commands from the checkout with `skill/scripts/sciplot`. Use absolute data,
project and evidence paths. The uppercase names below are placeholders to replace
with values read from the current command results, not literal arguments.

## Start or resume

```bash
skill/scripts/sciplot doctor --json
skill/scripts/sciplot project capabilities --json
```

Require Doctor `status=ready`. For an existing managed Studio project, start at
**Read the saved project** below; do not rerun its raw source to make an edit. Before applying an
external edit, close every writable native Veusz window for that project,
including a clean window with no unsaved changes. Save any intended native
changes first. A blocked session is a conflict to resolve, not a lock to delete.

For new raw data, read the source and the registered invocation:

```bash
skill/scripts/sciplot inspect SOURCE --json
skill/scripts/sciplot rules list --json
skill/scripts/sciplot rules show RULE_ID --json
skill/scripts/sciplot plan SOURCE --rule RULE_ID --template TEMPLATE_ID --json > PLAN_JSON
```

Choose `availability=ready` and use its exact rule/template values. Read the
whole plan, selected figures and any scientific transform. Preserve the original
plan JSON. When the user's scientific intent and the plan agree:

```bash
skill/scripts/sciplot project create SOURCE --expected-plan PLAN_JSON --json
```

`--expected-plan` checks the current source bytes and scientific choices before
creating a project. `project create` reads the rule and template from that exact
plan and reuses the ordinary native Studio prepare/export lifecycle. A changed
source or mismatched plan requires a fresh plan;
do not remove this argument to bypass a failure. `planned` or `not_applicable`
is a plan result, not a delivery claim. Require the execution result's
`studio_run.ready_to_use=true`, then retain its `project_dir`, `document` and
run/delivery references. The result has a canonical `studio/document.vsz` and
figure-set registry ready for the query/edit loop below. If the source needs clarification or repair, report
the structured reason; never guess units, sample identities or scientific values.

Create returns a compact `sciplot_project_creation_result` v1 object. On success
`status=created`; `project_dir`, `document` and `request` identify the managed
project. `figures` contains brief identity/document/export references, while
`studio_run` retains readiness/state, the full `manifest` resource path and
`delivery_package.path/complete`. Read that manifest only when detailed QA or
scientific evidence is needed; large scientific arrays and repeated internal
payloads are intentionally absent from stdout. A returned creation failure has
`status=blocked` with `studio_run.failure_stage/failure_reason` and a nonzero exit
code. Exceptions before a creation result use the normal CLI error envelope.

Omit `--out` to keep the visible `SOURCE_SciPlot/` package beside the source.
Creation requires both the visible output and its hidden workspace to be new.
If they already exist, inspect the existing managed project or deliberately
choose a new dedicated `--out`; creation never overwrites an existing project.
User evidence such as PLAN_JSON and CHANGES_JSON belongs outside raw-input
directories, the managed project and the visible package. Development evidence
belongs under `.tmp_verify/`.

`autoplot` remains a compatible one-time delivery route with its own ready
summary. Its historical `project_dir` can contain only run artifacts, without a
canonical Studio document; do not feed such a directory into this editing loop
or claim that it is resumable. Use `project create` for new work intended for
external-AI continuation. No automatic migration of old run-only projects is implied.

## Read the saved project

```bash
skill/scripts/sciplot project inspect PROJECT --json
skill/scripts/sciplot project inspect PROJECT --figure FIGURE_ID --json
```

Use `project` from the first result as the canonical project path. Obtain
FIGURE_ID from `figures[].figure_id`; for the primary figure use the returned
`primary_figure_id`, not the literal word `primary`. The summary is read-only
and does not load native objects or regenerate figures. It accepts a project
directory, `plot_request.json`, registered canonical VSZ, or a still-associated
delivery. A moved/copied portable delivery cannot silently select its old owner.

The explicit figure inspection returns `selected_figure.objects`, indexed by
absolute native object paths, with `settings`, `editable_fields` and `target`.
Read the particular field's `setting_path`, `current_value`, editor and bounds.
The target's `document_sha256` identifies the saved VSZ version. These are native
paths and saved-byte identities; do not invent UUIDs or use a GUI changeset.
To limit output after identifying an object:

```bash
skill/scripts/sciplot project inspect PROJECT --figure FIGURE_ID --object OBJECT_PATH --json
```

Inspect and visually review the exact saved figure when needed:

```bash
skill/scripts/sciplot project preview PROJECT --figure FIGURE_ID --out NEW_PREVIEW_DIRECTORY --json
```

Read the returned PNG. Each preview `--out` must be a **new**, dedicated directory
outside the source, project and visible delivery; do not reuse an old preview
directory. A preview is not a PDF/TIFF publication or a new ready result.

## Preview an authorized style edit

Write CHANGES_JSON as a JSON list. Use the exact paths and expected values from
the most recent figure inspection. For example, **only if inspection actually
advertises these paths and the current value is `8pt`**, a change to `9pt` is:

```json
[
  {
    "object_path": "/page1/graph1/x",
    "setting_path": "/page1/graph1/x/Label/size",
    "expected_value": "8pt",
    "value": "9pt"
  }
]
```

```bash
skill/scripts/sciplot project edit-preview PROJECT --figure FIGURE_ID \
  --expected-document DOCUMENT_SHA256 --changes CHANGES_JSON \
  --out NEW_EDIT_DIRECTORY --json
```

This stages native edits and a PNG, then audits the candidate's scientific
contents against the current spec. It does not replace the saved document.
Review the returned `actual_changes`, scientific audit and preview image.
Current capability scope covers the advertised axis typography, ordinary curve
color/line width, and legend typography/placement fields. It excludes data,
expressions, scientific labels/units, axis scales/bounds, sample identity and
semantic color encodings. An unadvertised field is unavailable, even if native
Veusz has such a setting. Do not substitute text patches, arbitrary Python or
GUI automation for rejected operations.

Existing user authorization for a concrete style change is sufficient. Ask only
when intent, scientific meaning or scope is unresolved. Keep the complete
`edit-preview.json` unchanged; it binds the request, source, project, delivery
and candidate evidence and is the input to apply.

## Apply, recover a reply, and export

```bash
skill/scripts/sciplot project edit-apply PROJECT --preview NEW_EDIT_DIRECTORY/edit-preview.json --json
skill/scripts/sciplot project operation PROJECT --operation-id OPERATION_ID --json
```

Take OPERATION_ID from the edit preview/apply output. Apply recomputes the
allowed native operations, checks the preview against current state, archives
the previous VSZ, and replaces the selected canonical document with rollback
on ordinary failure. A stale request, source, figure, delivery or expected value
requires a new inspection and preview. Never modify the old preview to make it
pass. An unmerged visible VSZ remains a separate recovery concern.

If the success reply was lost, query `project operation` and inspect
`status`, `result_is_current`, `document_sha256` and `result_sha256`.
Retrying the same unchanged preview may return `already_applied` when its saved
result and recovery evidence still match. If a later edit changed the document,
the old apply is rejected. This is bounded recovery of this edit, not a general
exactly-once task engine. A missing or pending outcome is not a success claim.

Apply does not export. Publish the exact-current complete project:

```bash
skill/scripts/sciplot studio PROJECT --export pdf,tiff_300 --json
skill/scripts/sciplot project inspect PROJECT --json
```

Require `studio_run.ready_to_use=true`, current QA, and the complete source-adjacent
package. Inspect the final PDF/TIFF appearance as part of handoff. All registered
figures are included by the managed export use case, even when only one figure
was styled.

## Resume in a new AI session

Retain PROJECT, the user's task, and any relevant operation ID or preview path.
A new process or conversation repeats `project capabilities`, `project inspect`
and, when editing, the explicit figure inspection. It reads the saved document
and durable outcome; it does not need previous chat state, a GUI selection or
an in-app AI provider. Continue from the current returned SHA, not a remembered one.

Inspection `status=ok` means the query succeeded. Its `ready_to_use=null` and
`readiness_evaluated=false` are deliberate. `last_run.recorded_ready_to_use`
is historical; `source`, `qa` and `delivery` report separate current byte-binding
indicators and may be unknown or stale. They do not perform a new scientific
audit, certify a build, inspect unsaved native changes, or replace final visual
review. Edit and preview success likewise do not claim a deliverable is ready.

Read stdout JSON and the exit code together. Runtime errors use the public
JSON failure envelope; usage errors may still be argparse text. Stop on a
blocked/error result and report its actual cause instead of treating an output
path or an earlier successful run as evidence that the current task succeeded.
