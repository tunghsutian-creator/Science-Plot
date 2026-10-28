"""Preview and apply shared-template restoration on exact saved rheology suites."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
from uuid import uuid4
import tempfile
from typing import Any

from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.foundation.json_hashing import canonical_json_sha256
from sciplot_core.workflow.rheology_tts_style_storage import check_snapshot, snapshot
from sciplot_core.workflow.rheology_tts_tables import write_json
from sciplot_core.workflow.native_suite_runtime import current_store, delivery_path, literal_directory, literal_resource, native_path, native_runtime


def _load(workspace: Path, *, native_display: bool = False, repair: bool = False) -> tuple[Path, dict[str, Any]]:
    workspace = workspace.expanduser().resolve()
    manifest = json.loads((workspace / "suite.json").read_text(encoding="utf-8"))
    active = current_store()
    if manifest.get("kind") != "sciplot_rheology_tts_suite" or (active.root if active is not None else Path(manifest["workspace"]).resolve()) != workspace:
        raise ValueError("Expected a bound rheology suite workspace.")
    delivery = delivery_path(manifest).resolve()
    if (workspace / ".sciplot_store/head.json").exists():
        from sciplot_core.project_store import FileProjectStore
        store = active or FileProjectStore(workspace, locations={"delivery": delivery})
        store.recover() if repair else store.snapshot()
        manifest = json.loads((workspace / "suite.json").read_text(encoding="utf-8"))
    if not native_display and manifest.get("figure_layout") != "separate_polymer_modulus":
        raise ValueError("Template restoration requires the separated layout; legacy suites remain reproducible.")
    if json.loads((delivery / "data/delivery_manifest.json").read_text()) != manifest:
        raise ValueError("Visible and hidden suite manifests disagree.")
    for document in manifest["documents"]:
        if native_path(manifest, document) != delivery / "editable" / f"{document['id']}.vsz":
            raise ValueError("Native document path is outside the bound visible editable directory.")
    return workspace, manifest


def _assert_same_science(old: dict[str, Any], new: dict[str, Any]) -> None:
    def signature(figure: dict[str, Any]) -> list[dict[str, Any]]:
        return [{"id": p["id"], "rect_mm": p["rect_mm"], "axes": p["axes"],
                 "title": p["title"], "notes": p["notes"],
                 "references": p["reference_lines"],
                 "standard_frame": p.get("standard_frame"), "x_tick_labels": p.get("x_tick_labels"),
                 "series": [{k: s[k] for k in ("name", "kind", "bar_width", "x_name", "y_name", "x_values", "y_values")}
                            for s in p["series"]]} for p in figure["panels"]]
    if (old["id"], old["width_mm"], old["height_mm"], signature(old)) != (
            new["id"], new["width_mm"], new["height_mm"], signature(new)):
        raise ValueError("Presentation restoration attempted to change data, axes, titles or layout.")


def _encoding_values(figure: dict[str, Any]) -> list[dict[str, Any]]:
    return [{"legend": p["legend"], "series": [
        {"legend_key": s["legend_key"], **({key: s["encoding"][key] for key in ("line", "marker")}
                                         if s["kind"] != "bar" else {})}
        for s in p["series"]]} for p in figure["panels"]]


def _presentation_plan(plan: dict[str, Any], path: Path | None, *, authoritative_paths: tuple[Path, ...]) -> tuple[dict[str, Any], dict[str, Any]]:
    from sciplot_core.rheology_tts_style import prepare_tts_presentation, upgrade_tts_presentation

    governed = prepare_tts_presentation(plan) if "presentation_policy" in plan else upgrade_tts_presentation(plan)
    if path is None:
        return governed, {}
    path = path.expanduser()
    if path.resolve() in tuple(p.resolve() for p in authoritative_paths):
        raise ValueError("The presentation plan must be separate from the suite's active plans.")
    binding = snapshot([path])
    path = path.resolve()
    candidate = prepare_tts_presentation(json.loads(path.read_text(encoding="utf-8")))
    check_snapshot(binding, label="external presentation plan")

    def invariant(payload: dict[str, Any]) -> dict[str, Any]:
        result = deepcopy(payload)
        for figure in result["figures"]:
            for panel in figure["panels"]:
                panel.pop("legend", None)
                for series in panel["series"]:
                    series.pop("label", None)
        return result

    if invariant(governed) != invariant(candidate):
        raise ValueError("A presentation plan may change only display series labels and panel legend positions; scientific values, identities and all other fields must remain unchanged.")
    for old_figure, new_figure in zip(governed["figures"], candidate["figures"], strict=True):
        for old_panel, new_panel in zip(old_figure["panels"], new_figure["panels"], strict=True):
            before, after = old_panel.get("legend", "upper_left"), new_panel.get("legend", "upper_left")
            if before != after and (not before or not after or after not in {
                    "upper_left", "upper_right", "lower_left", "lower_right",
                    "top_left", "top_right", "bottom_left", "bottom_right"}):
                raise ValueError("Presentation updates may reposition an existing legend to a named corner; they cannot change legend widget visibility.")
            if any(not isinstance(series.get("label"), str) for series in new_panel["series"]):
                raise ValueError("Presentation labels must be explicit strings supplied by the caller.")
    return candidate, {"path": str(path), "sha256": binding[str(path)]}


@native_runtime()
def _prepare_style_preview(workspace: Path, directory: Path, *, presentation_plan: Path | None = None) -> dict[str, Any]:
    from sciplot_core.rheology_tts_render import audit_tts_document, export_tts_document, restyle_tts_document
    from sciplot_core.rheology_tts_spec import compile_tts_spec
    from sciplot_core.workflow.rheology_tts_contract import rheology_capabilities
    from sciplot_core.workflow.rheology_tts_saved_state import _check_sources, _compiled_figures

    workspace, manifest = _load(workspace)
    _check_sources(manifest["sources"])
    old_figures = _compiled_figures(manifest)
    delivery = delivery_path(manifest)
    plan_path = workspace / "figure_plan.json"
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    if plan != json.loads((delivery / "data/figure_plan.json").read_text(encoding="utf-8")):
        raise ValueError("Visible and hidden figure plans disagree.")
    upgraded, external_plan = _presentation_plan(plan, presentation_plan,
        authoritative_paths=(plan_path, delivery / "data/figure_plan.json"))
    compiled = compile_tts_spec(upgraded)
    new_figures = {f["id"]: f for f in compiled["figures"]}
    if set(old_figures) != set(new_figures):
        raise ValueError("Template restoration changed the selected figure set.")
    for identifier in old_figures:
        _assert_same_science(old_figures[identifier], new_figures[identifier])
    selected = [d for d in manifest["documents"] if _encoding_values(old_figures[d["id"]]) != _encoding_values(new_figures[d["id"]])]
    if not selected and plan.get("presentation_policy") == upgraded.get("presentation_policy"):
        return {"status": "no_change", "workspace": str(workspace), "delivery": str(delivery),
                **({"presentation_plan": external_plan} if external_plan else {}),
                "message": "The saved suite already has this presentation contract; native edits remain authoritative."}
    dependencies = [workspace / "suite.json", delivery / "data/delivery_manifest.json", plan_path,
                    delivery / "data/figure_plan.json"]
    # Prepared plotting does not run analysis or create these optional reports.
    # Existing reports still bind the preview; legacy analysis suites require them.
    dependencies.extend(path for path in (workspace / "analysis.json", delivery / "data/analysis.json")
                        if "prepared_input" not in manifest or path.exists() or path.is_symlink())
    for document in manifest["documents"]:
        dependencies.extend([native_path(manifest, document), *(delivery / Path(p).relative_to(Path(manifest["delivery"])) for p in document["exports"])])
        from sciplot_core.workflow.rheology_tts_saved_state import _figure_folder
        audit_path = _figure_folder(delivery, document["id"]) / f"{document['id']}.native-audit.json"
        if audit_path.exists():
            dependencies.append(audit_path)
    from sciplot_core.workflow.rheology_tts_saved_state import _active_receipts
    receipts = _active_receipts(manifest)
    from sciplot_core.project_store.runtime import resolve_runtime_path
    dependencies.extend(resolve_runtime_path(r["spec_path"], expected_sha256=r["spec_sha256"]) for r in receipts)
    baseline = snapshot(dependencies)
    if external_plan:
        baseline[external_plan["path"]] = external_plan["sha256"]
        check_snapshot({external_plan["path"]: external_plan["sha256"]}, label="external presentation plan")
    directory.mkdir(parents=True, exist_ok=True)
    write_json(directory / "figure_plan.json", upgraded)
    specs, candidates = [], []
    for identifier, figure in new_figures.items():
        spec_path = directory / "specs" / f"{identifier}.spec.json"
        write_json(spec_path, {"kind": compiled["kind"], "version": 1,
            "source_binding": compiled["source_binding"], "transform_ledger": compiled["transform_ledger"], "figure": figure})
        specs.append({"id": identifier, "spec_path": str(spec_path), "spec_sha256": file_sha256(spec_path)})
    for document in manifest["documents"]:
        identifier = document["id"]
        native = native_path(manifest, document)
        if document not in selected:
            audit_tts_document(native, old_figures[identifier])
            continue
        candidate = directory / "native" / native.name
        edit = restyle_tts_document(native, candidate, old_figures[identifier], new_figures[identifier],
                                   baseline[str(native.resolve())])
        if not edit.get("changes"):
            continue
        exported = export_tts_document(candidate, directory / "exports" / identifier, new_figures[identifier])
        if exported["document_sha256"] != file_sha256(candidate):
            raise ValueError("Candidate changed during preview export.")
        candidates.append({"id": identifier, "edit": edit, "export": exported})
    _check_sources(manifest["sources"])
    check_snapshot(baseline, label="presentation baseline")
    files = [directory / "figure_plan.json", *(Path(s["spec_path"]) for s in specs)]
    if external_plan:
        files.append(Path(external_plan["path"]))
    for item in candidates:
        files.extend([Path(item["export"]["document"]), *(Path(e["path"]) for e in item["export"]["exports"])])
    preview = {"kind": "sciplot_rheology_style_preview", "version": 1,
        "workspace": str(workspace), "delivery": str(delivery), "sources": manifest["sources"],
        "contract_sha256": rheology_capabilities()["contract_sha256"], "baseline": baseline,
        "candidate_files": snapshot(files), "figures": specs, "candidates": candidates,
        "plan": str(directory / "figure_plan.json"), "presentation_plan": external_plan,
        "status": "preview_ready"}
    write_json(directory / "preview.json", preview)
    (directory / "preview.sha256").write_text(canonical_json_sha256(preview), encoding="ascii")
    return preview



def publication_updates(workspace: Path, manifest: dict[str, Any], preview: dict[str, Any], directory: Path,
                        *, native_display: bool = False, spec_targets: dict[str, Path] | None = None) -> dict[Path, bytes]:
    """Build exact audited byte writes; no mutable source survives this callback."""
    from sciplot_core.workflow.rheology_tts_saved_state import _export_receipts, _figure_folder
    from sciplot_core.workflow.native_suite_generation import candidate_bytes, json_bytes

    updated = deepcopy(manifest)
    by_id = {document["id"]: document for document in updated["documents"]}
    delivery = delivery_path(manifest)
    writes = {}
    current_exports = _export_receipts(updated)
    for item in preview["candidates"]:
        identifier = item["id"]
        document = by_id[identifier]
        receipt = deepcopy(item["export"])
        native = native_path(manifest, document)
        writes[native] = candidate_bytes(Path(receipt["document"]), receipt["document_sha256"])
        document["sha256"] = receipt["document_sha256"]
        receipt["document"] = literal_resource(native)
        receipt["export_dir"] = literal_directory(_figure_folder(delivery, identifier))
        actual_exports = set()
        for exported in receipt["exports"]:
            source = Path(exported["path"])
            target = _figure_folder(delivery, identifier) / source.name
            literal = literal_resource(target)
            if literal not in document["exports"] or target in actual_exports:
                raise ValueError("Candidate export target differs from its exact bound inventory.")
            writes[target] = candidate_bytes(source, exported["sha256"])
            actual_exports.add(target)
            exported["path"] = literal
        # Native success/export pending retains old protected outputs. Complete
        # exports must cover the entire expected set, never a plausible subset.
        if receipt["exports"] and {literal_resource(path) for path in actual_exports} != set(document["exports"]):
            raise ValueError("Candidate export set is incomplete.")
        receipt["native_audit"]["document"] = literal_resource(native)
        audit = _figure_folder(delivery, identifier) / (identifier + ".native-audit.json")
        writes[audit] = json_bytes(receipt["native_audit"])
        receipt["native_audit_path"] = literal_resource(audit)
        current_exports[identifier] = receipt
    updated["last_export"] = [current_exports[item["id"]] for item in updated["documents"]]
    updated["presentation_revision"] = {"version": 1, "preview": "preview.json",
        "contract_sha256": preview["contract_sha256"], "figures": deepcopy(preview["figures"]),
        "presentation_plan": preview.get("presentation_plan", {}),
        "scope": "Changed shared-template fields and caller-supplied display labels/legend positions only; numeric analysis and unrelated native edits preserved."}
    if spec_targets:
        for receipt in updated["presentation_revision"]["figures"]:
            target = spec_targets[receipt["id"]]
            writes[target] = candidate_bytes(Path(receipt["spec_path"]), receipt["spec_sha256"])
            receipt["spec_path"] = literal_resource(target)
    if not native_display:
        plan = Path(preview["plan"])
        data = candidate_bytes(plan, preview["candidate_files"][str(plan)])
        writes[workspace / "figure_plan.json"] = data
        writes[delivery / "data/figure_plan.json"] = data
    data = json_bytes(updated)
    writes[workspace / "suite.json"] = data
    writes[delivery / "data/delivery_manifest.json"] = data
    return writes


@native_runtime(repair=True)
def preview_suite_style(workspace: Path, *, presentation_plan: Path | None = None) -> dict[str, Any]:
    from sciplot_core.project_commands import ProjectCommands, ProjectMutation
    from sciplot_core.workflow.native_suite_generation import canonical_sha, command_for, json_bytes, mutation, open_store, source_versions, suite_paths

    workspace, manifest = _load(workspace, repair=True)
    store = open_store(workspace, delivery_path(manifest))
    from sciplot_core.workflow.native_suite_generation import adopt_saved_native
    adopt_saved_native(store, manifest)
    key = "style:" + uuid4().hex
    request = {"adapter": "suite_style", "presentation_plan": str(presentation_plan) if presentation_plan else None}
    reads, writes = suite_paths(workspace, manifest, native_writes=True)
    plan_paths = [workspace / "figure_plan.json", delivery_path(manifest) / "data/figure_plan.json"]
    reads.extend(plan_paths)
    reads.extend(path for path in (workspace / "analysis.json", delivery_path(manifest) / "data/analysis.json")
                 if path.exists() or path.is_symlink())
    writes.extend(plan_paths)
    specs = {item["id"]: workspace / "presentation_specs" / key.replace(":", "_") / (item["id"] + ".spec.json")
             for item in manifest["documents"]}
    writes.extend(specs.values())
    command = command_for(store, "style", key, request=request, reads=reads, writes=writes, whole=True)
    app = ProjectCommands(store)
    with tempfile.TemporaryDirectory(prefix="sciplot-suite-style-") as temporary:
        directory = Path(temporary).resolve()
        def prepare() -> ProjectMutation:
            preview = _prepare_style_preview(workspace, directory, presentation_plan=presentation_plan)
            updates: dict[Path, bytes | None] = {}
            if preview.get("status") == "no_change":
                artifacts = {"preview.json": json_bytes(preview)}
                result = preview
            else:
                prepared_updates = publication_updates(workspace, manifest, preview, directory, spec_targets=specs)
                updates.update(prepared_updates)
                # V1 describes temporary native candidates. This sealed review
                # retains their actual edit evidence without executable old paths;
                # Core owns the read set, candidate bytes and decision/replay.
                artifacts = {"preview.json": json_bytes({"kind": preview["kind"], "version": 2,
                    "figures": list(specs), "contract_sha256": preview["contract_sha256"],
                    "sources": preview["sources"], "candidates": [{"id": item["id"],
                        "edit": {"changes": item["edit"]["changes"]}} for item in preview["candidates"]],
                    "candidate_files": {store.logical_path(path): canonical_sha(data)
                    for path, data in prepared_updates.items()}})}
                for candidate in preview["candidates"]:
                    image = next(item["path"] for item in candidate["export"]["exports"] if item["format"] == "png_300")
                    artifacts[candidate["id"] + ".png"] = Path(image).read_bytes()
                result = {"status": "ready", "workspace": str(workspace), "delivery": manifest["delivery"],
                    "changed_figures": len(preview["candidates"]), "numerical_refit": False,
                    "exact_candidate_export": True}
            for path in writes:
                if path not in updates:
                    logical = store.logical_path(path)
                    updates[path] = store.read_bytes(logical) if logical in store.snapshot()["files"] else None
            review: dict[str, Any] = {"adapter": "suite_style", "preview": "preview.json"}
            candidate = mutation(store, updates, result, sources=manifest["sources"],
                review=review, artifacts=artifacts)
            binding = preview.get("presentation_plan", {})
            if presentation_plan is not None:
                if (set(binding) != {"path", "sha256"}
                        or binding["path"] != str(presentation_plan.expanduser().resolve())):
                    raise ValueError("The display intent lacks its exact external presentation plan binding.")
                check_snapshot({binding["path"]: binding["sha256"]}, label="external presentation plan")
                # This is an intent dependency, never a suite scientific source.
                review["presentation_plan"] = binding
                candidate = replace(candidate, sources=[*(candidate.sources or ()), *source_versions(store, [binding])])
            return candidate
        record = app.preview(command, prepare)
    if record["result"].get("status") == "no_change":
        result: dict[str, Any] = app.decide(command, decision_id=record["decision_id"], accept=True)["result"]
        return result
    return {"status": "preview_ready", "preview": record["artifact_paths"]["preview.json"],
        "workspace": str(workspace), "changed_figures": record["result"].get("changed_figures", 0),
        "decision_id": record["decision_id"],
        "figures": [{"id": name[:-4], "preview_png": path} for name, path in record["artifact_paths"].items()
                    if name.endswith(".png")], "next_step": "Inspect the frozen candidate images, then apply this preview."}


def apply_suite_style(workspace: Path, preview_path: Path, *, native_display: bool = False,
                      _session_held: bool = False) -> dict[str, Any]:
    from sciplot_core.project_commands import ProjectCommands
    from sciplot_core.workflow.native_suite_runtime import read_bound_store
    from sciplot_core.studio_core.source_update_commit import reject_symlink_path
    store = read_bound_store(workspace)
    reject_symlink_path(preview_path)
    path = preview_path.expanduser().resolve()
    if store is None or len([record for record in ProjectCommands(store).commands()
            if record.get("review", {}).get("adapter") == "suite_style"
            and record.get("artifact_paths", {}).get("preview.json") == str(path)]) != 1:
        raise ValueError("Apply requires the exact sealed generation preview before any project recovery.")
    return _apply_suite_style_admitted(workspace, path, native_display=native_display, _session_held=_session_held)


@native_runtime(repair=True)
def _apply_suite_style_admitted(workspace: Path, preview_path: Path, *, native_display: bool = False,
                               _session_held: bool = False) -> dict[str, Any]:
    from sciplot_core.project_commands import ProjectCommand, ProjectCommands
    from sciplot_core.workflow.native_suite_generation import open_store
    from sciplot_core.workflow.rheology_tts_saved_state import _check_sources

    workspace, manifest = _load(workspace, native_display=native_display, repair=True)
    store = open_store(workspace, delivery_path(manifest))
    app = ProjectCommands(store)
    path = preview_path.expanduser().resolve()
    matches = [record for record in app.commands()
               if record.get("review", {}).get("adapter") == "suite_style"
               and record.get("artifact_paths", {}).get("preview.json") == str(path)]
    if len(matches) != 1:
        raise ValueError("Apply requires the exact sealed generation preview; legacy previews remain read-only evidence.")
    record = matches[0]
    _check_sources(manifest["sources"])
    binding = record.get("review", {}).get("presentation_plan")
    if binding is not None and record["phase"] != "complete":
        prepared = store.prepared_input_path(record["command_id"], record["command_digest"],
            decision_id=record["decision_id"], locator=binding["path"], expected_sha256=binding["sha256"])
        path = prepared if prepared is not None else Path(binding["path"])
        check_snapshot({str(path): binding["sha256"]}, label="external presentation plan")
    command = ProjectCommand.from_payload(record["metadata"])
    applied = app.decide(command, decision_id=record["decision_id"], accept=True)
    return {**applied["result"], "generation": applied["generation"], "already_applied": record["phase"] == "complete"}
