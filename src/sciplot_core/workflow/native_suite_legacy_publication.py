"""Reverify an already installed legacy outcome, then import it without writes."""
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
from typing import Any

from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.foundation.json_hashing import canonical_json_sha256
from sciplot_core.project_commands import PreparedFile, PreparedSource, ProjectCommands, ProjectMutation
from sciplot_core.project_store import FileProjectStore
from sciplot_core.workflow.native_suite_generation import candidate_file, canonical_sha, command_for, command_key, json_bytes, source_versions
from sciplot_core.workflow.native_suite_objects import native_identity, selected_spec
from sciplot_core.workflow.native_suite_preview import LegacyCandidate
from sciplot_core.workflow.rheology_tts_contract import rheology_capabilities
from sciplot_core.workflow.rheology_tts_publication_recovery import read_publication
from sciplot_core.workflow.rheology_tts_saved_state import _check_sources, _figure_folder
from sciplot_core.workflow.rheology_tts_style_storage import check_snapshot


def import_installed(context: dict[str, Any], record: dict[str, Any], path: Path,
                     store: FileProjectStore, app: ProjectCommands, frozen: LegacyCandidate) -> dict[str, Any] | None:
    """Current scientific verification does not authenticate past execution claims."""
    from sciplot_core.studio_core.source_update_commit import reject_symlink_path

    preview_path, seal = path.parent / "preview.json", path.parent / "preview.sha256"
    for item in (preview_path, seal):
        reject_symlink_path(item)
    preview = frozen.preview
    if (record["preview"] != str(preview_path) or canonical_json_sha256(preview) != seal.read_text()
            or preview.get("kind") != "sciplot_native_display_preview"
            or preview.get("workspace") != context["workspace"] or preview.get("delivery") != context["delivery"]
            or preview.get("contract_sha256") != rheology_capabilities()["contract_sha256"]
            or preview.get("baseline") != record["baseline"] or preview.get("sources") != record["sources"]):
        raise ValueError("Legacy publication preview bindings changed; preserve and inspect.")
    native = Path(context["plot"])
    workspace, delivery = Path(context["workspace"]), Path(context["delivery"])
    audit_path = _figure_folder(delivery, context["figure_id"]) / (context["figure_id"] + ".native-audit.json")
    expected = {str(native), *context["document"]["exports"], str(audit_path),
                str(workspace / "suite.json"), str(delivery / "data/delivery_manifest.json")}
    installed = read_publication(path.parent, preview, expected_files=expected)
    if installed is None:
        return None
    if record.get("accepted") is False:
        raise ValueError("Legacy rejected decision contradicts installed publication evidence; preserve and inspect.")
    evidence, evidence_paths = installed
    frozen_evidence = {**frozen.evidence, **{item: candidate_file(item, file_sha256(item)) for item in evidence_paths}}
    if (json.loads(frozen_evidence[path].data) != record or json.loads(frozen_evidence[preview_path].data) != preview
            or frozen_evidence[seal].data.decode() != canonical_json_sha256(preview)):
        raise ValueError("Legacy publication evidence changed while being frozen.")
    for item in evidence_paths:
        if (item.suffix == ".json" and json.loads(frozen_evidence[item].data) != evidence
                or item.suffix == ".sha256" and frozen_evidence[item].data.decode() != canonical_json_sha256(evidence)):
            raise ValueError("Legacy installed evidence changed while being frozen.")
    candidates = preview.get("candidates", [])
    if len(candidates) != 1 or candidates[0]["id"] != context["figure_id"]:
        raise ValueError("Legacy publication must bind exactly the selected native figure.")
    selected = candidates[0]
    edit, exported = selected["edit"], selected["export"]
    candidate = Path(exported["document"])
    digest = exported["document_sha256"]
    if (not candidate.is_absolute() or ".." in candidate.parts or not candidate.is_relative_to(path.parent)
            or Path(edit["document"]) != candidate
            or edit.get("source_document") != context["plot"]
            or edit.get("source_document_sha256") != record["before_native_sha256"]
            or record["baseline"].get(context["plot"]) != record["before_native_sha256"]
            or edit.get("document_sha256") != digest or edit.get("baseline_audit", {}).get("status") != "passed"
            or edit.get("candidate_audit", {}).get("status") != "passed"
            or edit.get("candidate_audit", {}).get("document_sha256") != digest
            or edit.get("candidate_audit", {}).get("changed_presentation", {}).get("unrelated_native_state_unchanged") is not True):
        raise ValueError("Legacy publication lacks its exact before/after native preservation proof.")
    files = preview["candidate_files"]
    if str(candidate) not in files or files[str(candidate)] != digest or any(
            not Path(name).is_absolute() or ".." in Path(name).parts or not Path(name).is_relative_to(path.parent) for name in files):
        raise ValueError("Legacy publication candidate evidence escapes or lacks its exact native bytes.")
    check_snapshot(files, label="legacy publication candidate")
    published = evidence["published_files"]
    if (set(published) != expected or published.get(str(native)) != digest
            or evidence.get("result", {}).get("status") != "ready"
            or evidence["result"].get("workspace") != context["workspace"]
            or evidence["result"].get("delivery") != context["delivery"]):
        raise ValueError("Legacy publication does not prove the exact complete installed resource set.")
    suffixes = {"pdf": ".pdf", "tiff_300": "_300dpi.tiff", "png_300": "_300dpi.png"}
    if len(exported["exports"]) != 3 or {item["format"] for item in exported["exports"]} != set(suffixes):
        raise ValueError("Legacy publication has incomplete frozen exports.")
    frozen_exports = deepcopy(exported["exports"])
    preview_png: PreparedFile | None = None
    for item in frozen_exports:
        source = str(Path(item["path"]))
        target = _figure_folder(delivery, context["figure_id"]) / (context["figure_id"] + suffixes[item["format"]])
        if source not in files or files[source] != item["sha256"] or published.get(str(target)) != item["sha256"]:
            raise ValueError("Legacy installed exports disagree with the frozen audited candidate.")
        if item["format"] == "png_300":
            if record.get("preview_png") != source:
                raise ValueError("Legacy preview PNG is not its exact confined frozen export.")
            preview_png = frozen.png
        item["path"] = str(target)
    expected_audit = deepcopy(exported["native_audit"])
    expected_audit["document"] = str(native)
    if json.loads(audit_path.read_bytes()) != expected_audit:
        raise ValueError("Legacy installed audit differs from its frozen candidate audit.")
    if any(not Path(name).is_absolute() or ".." in Path(name).parts for name in record["baseline"]):
        raise ValueError("Legacy publication baseline paths are not canonical finite members.")
    check_snapshot({name: sha for name, sha in record["baseline"].items() if name not in expected},
                   label="legacy unchanged presentation baseline")
    check_snapshot(published, label="legacy exact installed publication")
    _check_sources(record["sources"])
    spec, figure = selected_spec(context)
    from sciplot_core.rheology_tts_render import audit_tts_document

    # Capture ordinary, unaliased files and independently audit CURRENT science.
    # Historical audit/result JSON is evidence, never permission to skip this.
    captured = frozen.native
    current = candidate_file(native, digest)
    audit = audit_tts_document(native, figure)
    if (audit.get("status") != "passed" or audit.get("document_sha256") != digest
            or Path(audit.get("document", "")) != native or file_sha256(native) != digest
            or current.data != captured.data):
        raise ValueError("Legacy installed native failed current exact scientific verification.")
    check_snapshot(published, label="legacy exact installed publication")
    check_snapshot(files, label="legacy publication candidate")
    for item, expected_file in frozen_evidence.items():
        current_evidence = candidate_file(item, canonical_sha(expected_file.data))
        if current_evidence.mode != expected_file.mode:
            raise ValueError("Legacy publication evidence mode changed during verification.")
    if preview_png is None:
        raise ValueError("Legacy publication lacks its exact preview PNG.")
    reads = [Path(name) for name in published]
    reads.extend(Path(name) for name in record["baseline"] if Path(name).is_relative_to(workspace)
                 or Path(name).is_relative_to(delivery))
    reads.append(spec)
    request = {"adapter": "native_display", "figure_id": context["figure_id"], "request": record["request"]}
    key = command_key("native_patch", {"figure": context["figure_id"], "key": record["request"]["idempotency_key"]})
    command = command_for(store, "attachment_import", key, request=request, reads=reads, writes=[],
                          expected_revision=record["request"]["base_revision"])
    identity = native_identity(context["manifest"]["workspace"], context["figure_id"], record["sources"], file_sha256(spec), digest)
    result = {**record, "phase": "complete", "accepted": True, "presentation_hash": digest,
        "revision": identity["revision"], "exports": frozen_exports,
        "legacy_recovery": {"installed_bytes_reverified": True, "current_scientific_audit": audit,
                            "historical_execution_authenticated": False}}
    artifacts: dict[str, bytes | PreparedFile] = {"native.vsz": captured, "preview.json": json_bytes(preview),
        "preview.png": preview_png, "legacy_operation.json": frozen_evidence[path],
        "current-audit.json": json_bytes(audit)}
    artifacts.update({"evidence/" + item.relative_to(path.parent).as_posix(): value for item, value in frozen_evidence.items()})
    sources = []
    current_sources = store.snapshot()["sources"]
    dependencies = [{"path": str(item), "sha256": canonical_sha(value.data)} for item, value in frozen_evidence.items()]
    for source_binding in source_versions(store, [*record["sources"], *dependencies]):
        proof = frozen_evidence.get(Path(source_binding["path"]))
        if proof is None:
            actual = store.resolve_path(source_binding["path"], expected_sha256=source_binding["version"], source_id=source_binding["source_id"])
            frozen_source = candidate_file(actual, source_binding["version"], unaliased=False)
        else:
            frozen_source = proof
        prior = current_sources.get(source_binding["source_id"], {}).get(source_binding["version"], {})
        sources.append(PreparedSource(source_binding["source_id"], source_binding["path"], source_binding["version"], frozen_source.data,
            aliases=tuple(prior.get("aliases", ())), mode=prior.get("mode", frozen_source.mode)))
    candidate_mutation = ProjectMutation({}, result, artifacts=artifacts, prepared_sources=tuple(sources),
        review={"adapter": "native_display", "figure_id": context["figure_id"],
                "legacy_decision_id": record["decision_id"], "legacy_operation": str(path)})
    # The callback only returns these already captured bytes. The old accepted
    # decision admits the exact sealed import; no renderer or old writer runs.
    imported = app.preview(command, lambda: candidate_mutation)
    return app.decide(command, decision_id=imported["decision_id"], accept=True)
