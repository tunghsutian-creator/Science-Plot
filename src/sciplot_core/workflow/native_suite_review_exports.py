"""Export and publish exact frozen reviewed native candidates through explicit child commands."""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import tempfile
from typing import Any
from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.project_commands import ProjectCommands, ProjectMutation
from sciplot_core.project_store import FileProjectStore
from sciplot_core.workflow.native_suite_generation import command_for, command_key, json_bytes, mutation, suite_paths, saved_command
from sciplot_core.workflow.native_suite_objects import selected_spec, require_object
from sciplot_core.workflow.native_suite_command_records import _preview_export

def _resume_preview_export(context: dict[str, Any], parent: dict[str, Any],
                           store: FileProjectStore, app: ProjectCommands) -> None:
    from sciplot_core.rheology_tts_render import export_tts_document
    from sciplot_core.workflow.rheology_tts_saved_state import _check_sources
    if _preview_export(app, parent):
        return
    attempts = [item for item in app.commands()
                if item.get("metadata", {}).get("request", {}).get("adapter") == "native_preview_export"
                and item["metadata"]["request"].get("parent") == parent["command_digest"]]
    request = {"adapter": "native_preview_export", "parent": parent["command_digest"], "attempt": len(attempts)}
    reads, _writes = suite_paths(Path(context["workspace"]), context["manifest"], (context["figure_id"],))
    command = command_for(store, "native_export", command_key("preview_export", request),
                          request=request, reads=reads, writes=[], figure_id=context["figure_id"])
    with tempfile.TemporaryDirectory(prefix="sciplot-native-preview-export-") as temporary:
        directory = Path(temporary).resolve()
        def prepare() -> ProjectMutation:
            candidate = directory / Path(context["plot"]).name
            candidate.write_bytes(Path(parent["artifact_paths"]["native.vsz"]).read_bytes())
            if file_sha256(candidate) != parent["result"]["presentation_hash"]:
                raise ValueError("Frozen native candidate changed.")
            _spec, figure = selected_spec(context)
            exported = export_tts_document(candidate, directory / "exports" / context["figure_id"], figure)
            if exported["document_sha256"] != parent["result"]["presentation_hash"]:
                raise ValueError("Preview export did not use the frozen native candidate.")
            artifacts = {item["format"]: Path(item["path"]).read_bytes() for item in exported["exports"]}
            artifacts["preview.png"] = artifacts["png_300"]
            # Paths are attachment keys. Private temporary paths never become
            # public review references or another persistent operation record.
            for item in exported["exports"]:
                item["path"] = item["format"]
            exported["document"] = "native.vsz"
            exported["native_audit"]["document"] = "native.vsz"
            exported["native_audit_path"] = "native-audit.json"
            _check_sources(context["manifest"]["sources"])
            return mutation(store, {}, {"export": exported}, sources=context["manifest"]["sources"], artifacts=artifacts)
        app.execute(command, prepare)


def _publish_reviewed_exports(context: dict[str, Any], parent: dict[str, Any], child: dict[str, Any],
                             store: FileProjectStore, app: ProjectCommands) -> dict[str, Any]:
    from sciplot_core.workflow.rheology_tts_saved_state import _check_sources, _export_receipts, _figure_folder
    request = {"adapter": "native_reviewed_export_publication", "parent": parent["command_digest"],
               "export": child["command_digest"]}
    key = command_key("reviewed_export", request)
    command = saved_command(app, key, request)
    reads, writes = suite_paths(Path(context["workspace"]), context["manifest"], (context["figure_id"],))
    if command is None:
        command = command_for(store, "native_export", key, request=request, reads=reads, writes=writes,
                              figure_id=context["figure_id"])
    def prepare() -> ProjectMutation:
        current = require_object(Path(context["plot"]))
        if file_sha256(Path(current["plot"])) != parent["result"]["presentation_hash"]:
            raise ValueError("Reviewed native bytes are no longer current.")
        manifest = deepcopy(current["manifest"])
        receipt = deepcopy(child["result"]["export"])
        folder = _figure_folder(Path(context["delivery"]), context["figure_id"])
        updates = {}
        suffixes = {"pdf": ".pdf", "tiff_300": "_300dpi.tiff", "png_300": "_300dpi.png"}
        for item in receipt["exports"]:
            target = folder / (context["figure_id"] + suffixes[item["format"]])
            updates[target] = Path(child["artifact_paths"][item["format"]]).read_bytes()
            item["path"] = str(target)
        receipt["document"] = context["plot"]
        receipt["export_dir"] = str(folder)
        receipt["native_audit"]["document"] = context["plot"]
        audit_path = folder / (context["figure_id"] + ".native-audit.json")
        receipt["native_audit_path"] = str(audit_path)
        updates[audit_path] = json_bytes(receipt["native_audit"])
        existing = _export_receipts(manifest)
        existing[context["figure_id"]] = receipt
        manifest["last_export"] = [existing[item["id"]] for item in manifest["documents"]]
        updates[Path(context["workspace"]) / "suite.json"] = json_bytes(manifest)
        updates[Path(context["delivery"]) / "data/delivery_manifest.json"] = json_bytes(manifest)
        _check_sources(manifest["sources"])
        return mutation(store, updates, {"status": "ready", "exports": receipt["exports"]}, sources=manifest["sources"])
    return app.execute(command, prepare)
