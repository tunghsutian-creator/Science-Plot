"""Preview and apply shared-template restoration on exact saved rheology suites."""

from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
from uuid import uuid4

from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.foundation.json_hashing import canonical_json_sha256
from sciplot_core.studio_core.project_session import external_project_session
from sciplot_core.workflow.rheology_tts_style_storage import check_snapshot, publish_files, snapshot
from sciplot_core.workflow.rheology_tts_tables import write_json


def _load(workspace: Path) -> tuple[Path, dict]:
    workspace = workspace.expanduser().resolve()
    manifest = json.loads((workspace / "suite.json").read_text(encoding="utf-8"))
    if manifest.get("kind") != "sciplot_rheology_tts_suite" or Path(manifest["workspace"]).resolve() != workspace:
        raise ValueError("Expected a bound rheology suite workspace.")
    delivery = Path(manifest["delivery"]).resolve()
    if manifest.get("figure_layout") != "separate_polymer_modulus":
        raise ValueError("Template restoration requires the separated layout; legacy suites remain reproducible.")
    if json.loads((delivery / "data/delivery_manifest.json").read_text()) != manifest:
        raise ValueError("Visible and hidden suite manifests disagree.")
    for document in manifest["documents"]:
        if Path(document["path"]).resolve() != delivery / "editable" / f"{document['id']}.vsz":
            raise ValueError("Native document path is outside the bound visible editable directory.")
    return workspace, manifest


def _assert_same_science(old: dict, new: dict) -> None:
    def signature(figure):
        return [{"id": p["id"], "rect_mm": p["rect_mm"], "axes": p["axes"],
                 "title": p["title"], "notes": p["notes"],
                 "references": p["reference_lines"],
                 "standard_frame": p.get("standard_frame"), "x_tick_labels": p.get("x_tick_labels"),
                 "series": [{k: s[k] for k in ("name", "kind", "bar_width", "x_name", "y_name", "x_values", "y_values")}
                            for s in p["series"]]} for p in figure["panels"]]
    if (old["id"], old["width_mm"], old["height_mm"], signature(old)) != (
            new["id"], new["width_mm"], new["height_mm"], signature(new)):
        raise ValueError("Presentation restoration attempted to change data, axes, titles or layout.")


def _encoding_values(figure: dict) -> list[dict]:
    return [{"legend": p["legend"], "series": [
        {"legend_key": s["legend_key"], **({key: s["encoding"][key] for key in ("line", "marker")}
                                         if s["kind"] != "bar" else {})}
        for s in p["series"]]} for p in figure["panels"]]


def _presentation_plan(plan: dict, path: Path | None, *, authoritative_paths: tuple[Path, ...]) -> tuple[dict, dict]:
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

    def invariant(payload):
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


def preview_suite_style(workspace: Path, *, presentation_plan: Path | None = None) -> dict:
    from sciplot_core.rheology_tts_render import audit_tts_document, export_tts_document, restyle_tts_document
    from sciplot_core.rheology_tts_spec import compile_tts_spec
    from sciplot_core.workflow.rheology_tts_contract import rheology_capabilities
    from sciplot_core.workflow.rheology_tts_suite import _check_sources, _compiled_figures

    workspace, manifest = _load(workspace)
    with external_project_session(workspace):
        _check_sources(manifest["sources"])
        old_figures = _compiled_figures(manifest)
        delivery = Path(manifest["delivery"])
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
                    "message": "The saved suite already has this presentation contract; native edits remain authoritative."}
        dependencies = [workspace / "suite.json", delivery / "data/delivery_manifest.json", plan_path,
                        delivery / "data/figure_plan.json"]
        # Prepared plotting does not run analysis or create these optional reports.
        # Existing reports still bind the preview; legacy analysis suites require them.
        dependencies.extend(path for path in (workspace / "analysis.json", delivery / "data/analysis.json")
                            if "prepared_input" not in manifest or path.exists() or path.is_symlink())
        for document in manifest["documents"]:
            dependencies.extend([Path(document["path"]), *(Path(p) for p in document["exports"])])
            from sciplot_core.workflow.rheology_tts_suite import _figure_folder
            audit_path = _figure_folder(delivery, document["id"]) / f"{document['id']}.native-audit.json"
            if audit_path.exists():
                dependencies.append(audit_path)
        receipts = manifest.get("presentation_revision", {}).get("figures") or manifest["native_result"]["figures"]
        dependencies.extend(Path(r["spec_path"]) for r in receipts)
        baseline = snapshot(dependencies)
        if external_plan:
            baseline[external_plan["path"]] = external_plan["sha256"]
            check_snapshot({external_plan["path"]: external_plan["sha256"]}, label="external presentation plan")
        directory = workspace / "style_previews" / uuid4().hex
        directory.mkdir(parents=True)
        write_json(directory / "figure_plan.json", upgraded)
        specs, candidates = [], []
        for identifier, figure in new_figures.items():
            spec_path = directory / "specs" / f"{identifier}.spec.json"
            write_json(spec_path, {"kind": compiled["kind"], "version": 1,
                "source_binding": compiled["source_binding"], "transform_ledger": compiled["transform_ledger"], "figure": figure})
            specs.append({"id": identifier, "spec_path": str(spec_path), "spec_sha256": file_sha256(spec_path)})
        for document in manifest["documents"]:
            identifier = document["id"]
            native = Path(document["path"])
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
        return {"status": "preview_ready", "preview": str(directory / "preview.json"),
            "workspace": str(workspace), "changed_figures": len(candidates),
            "figures": [{"id": c["id"], "changes": len(c["edit"]["changes"]),
                         "preview_png": next(e["path"] for e in c["export"]["exports"] if e["format"] == "png_300")}
                        for c in candidates],
            "next_step": "Inspect the candidate images, then apply this current preview; no numerical refit occurs."}


def apply_suite_style(workspace: Path, preview_path: Path) -> dict:
    from sciplot_core.workflow.rheology_tts_contract import rheology_capabilities
    from sciplot_core.workflow.rheology_tts_suite import _check_sources, _figure_folder

    workspace, manifest = _load(workspace)
    preview_path = preview_path.expanduser().resolve()
    if not preview_path.is_relative_to(workspace / "style_previews") or preview_path.name != "preview.json":
        raise ValueError("Preview must be the saved preview.json inside this suite's style_previews directory.")
    directory = preview_path.parent
    with external_project_session(workspace):
        preview = json.loads(preview_path.read_text(encoding="utf-8"))
        if canonical_json_sha256(preview) != (directory / "preview.sha256").read_text(encoding="ascii"):
            raise ValueError("Presentation preview receipt changed after creation.")
        if preview.get("workspace") != str(workspace) or preview.get("delivery") != manifest["delivery"]:
            raise ValueError("Presentation preview belongs to a different suite.")
        _check_sources(preview["sources"])
        external_plan = preview.get("presentation_plan")
        if external_plan:
            check_snapshot({external_plan["path"]: external_plan["sha256"]}, label="external presentation plan")
        if (directory / "applied.json").exists():
            applied = json.loads((directory / "applied.json").read_text())
            check_snapshot(applied["published_files"], label="previously applied presentation")
            return {**applied["result"], "already_applied": True}
        if preview["contract_sha256"] != rheology_capabilities()["contract_sha256"]:
            raise ValueError("Presentation contract changed after preview; inspect a new preview.")
        check_snapshot(preview["baseline"], label="presentation baseline")
        check_snapshot(preview["candidate_files"], label="presentation candidate")
        updated = deepcopy(manifest)
        by_id = {d["id"]: d for d in updated["documents"]}
        delivery = Path(manifest["delivery"])
        updates = []
        current_exports = {Path(v["document"]).stem: v for v in updated.get("last_export", updated["native_result"]["figures"])}
        for candidate in preview["candidates"]:
            identifier = candidate["id"]
            document = by_id[identifier]
            receipt = deepcopy(candidate["export"])
            native = Path(document["path"])
            updates.append((Path(receipt["document"]), native))
            document["sha256"] = receipt["document_sha256"]
            receipt["document"] = str(native)
            receipt["export_dir"] = str(_figure_folder(delivery, identifier))
            for exported in receipt["exports"]:
                source = Path(exported["path"])
                target = _figure_folder(delivery, identifier) / source.name
                if str(target) not in document["exports"]:
                    raise ValueError("Candidate export target differs from the bound suite export inventory.")
                updates.append((source, target))
                exported["path"] = str(target)
            receipt["native_audit"]["document"] = str(native)
            audit_source = directory / "published_audits" / f"{identifier}.native-audit.json"
            audit_target = _figure_folder(delivery, identifier) / audit_source.name
            write_json(audit_source, receipt["native_audit"])
            updates.append((audit_source, audit_target))
            receipt["native_audit_path"] = str(audit_target)
            current_exports[identifier] = receipt
        updated["last_export"] = [current_exports[d["id"]] for d in updated["documents"]]
        updated["presentation_revision"] = {"version": 1, "preview": str(preview_path),
            "contract_sha256": preview["contract_sha256"], "figures": preview["figures"],
            "presentation_plan": preview.get("presentation_plan", {}),
            "scope": "Changed shared-template fields and caller-supplied display labels/legend positions only; numeric analysis and unrelated native edits preserved."}
        staged_manifest = directory / "applied_manifest.json"
        write_json(staged_manifest, updated)
        updates.extend([(Path(preview["plan"]), workspace / "figure_plan.json"),
                        (Path(preview["plan"]), delivery / "data/figure_plan.json"),
                        (staged_manifest, workspace / "suite.json"),
                        (staged_manifest, delivery / "data/delivery_manifest.json")])
        _check_sources(preview["sources"])
        expected = {**preview["baseline"], **{source["path"]: source["sha256"] for source in preview["sources"]}}
        generated = [source for source, _ in updates if str(source.resolve()) not in preview["candidate_files"]]
        candidates = {**preview["candidate_files"], **snapshot(generated)}
        published = publish_files(updates, directory / "backup", expected=expected, candidates=candidates,
                                  allowed_roots=(workspace, delivery))
        result = {"status": "ready", "workspace": str(workspace), "delivery": str(delivery),
            "changed_figures": len(preview["candidates"]), "numerical_refit": False,
            "exact_candidate_export": True, "backup": str(directory / "backup")}
        write_json(directory / "applied.json", {"published_files": published, "result": result})
        return result
