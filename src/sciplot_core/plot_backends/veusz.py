"""Veusz preserves opaque legacy state while applying audited semantic deltas."""

from copy import deepcopy
from pathlib import Path
from typing import Any

from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.native_process import PersistentWorker, warm_native_method
from sciplot_core.plot_backends.veusz_compile import compile_diff
from sciplot_core.plot_backends.veusz_evidence import export_evidence
from sciplot_core.plot_backends.veusz_identity import changed_error, fingerprint, require_current
from sciplot_core.plot_backends.veusz_import import import_project
from sciplot_core.plot_backends.veusz_semantic_compile import preflight_hidden_positions
from sciplot_core.studio_core.document_edit import (
    apply_document_edit, preview_document_edit, preview_project_document,
)
from sciplot_core.studio_core.project_export import export_project_document
from sciplot_core.studio_core.project_session import external_project_session


class VeuszBackend:
    def __init__(self, *, warm: bool = True) -> None:
        self._worker = PersistentWorker() if warm else None

    def close(self) -> None:
        worker = getattr(self, "_worker", None)
        if worker is not None:
            worker.close()

    @warm_native_method
    def import_project(self, project: Path, figure_id: str | None = None,
                       plot_id: str | None = None) -> tuple[dict[str, Any], dict[str, Any]]:
        return import_project(project, figure_id, plot_id)

    def fingerprint(self, binding: dict[str, Any]) -> dict[str, Any]:
        return fingerprint(binding)

    @warm_native_method
    def preview(self, document: dict[str, Any], binding: dict[str, Any],
                new_document: dict[str, Any], diff: list[dict[str, Any]],
                output: Path) -> dict[str, Any]:
        require_current(binding)
        changes, operations, updates = compile_diff(document, binding, new_document, diff)
        preflight_hidden_positions(binding, new_document, diff, updates, operations)
        if not changes and operations is None:
            rendered = self.render(binding, output)
            return {**rendered, "status": "ready", "document_only": True,
                    "scientific_audit": binding["native_audit_at_import"],
                    "_backend_updates": updates}
        review = preview_document_edit(
            Path(binding["project"]), changes, output_dir=output,
            figure_id=binding["figure_id"],
            expected_document_sha256=binding["fingerprint"]["files"][binding["document"]],
            expected_spec_sha256=binding["fingerprint"]["files"][binding["spec"]],
            operations=operations,
        )
        return {**review, "_backend_updates": updates}

    @warm_native_method
    def apply(self, binding: dict[str, Any], review: dict[str, Any]) -> dict[str, Any]:
        if review.get("document_only"):
            require_current(binding)
            return {"status": "unchanged", "document_sha256": file_sha256(Path(binding["document"])),
                    "_backend_updates": review["_backend_updates"]}
        native_review = {key: value for key, value in review.items() if key != "_backend_updates"}
        # The existing owner recognizes its durable operation identity after a
        # process interruption; checking the old hash here would prevent recovery.
        result = apply_document_edit(Path(binding["project"]), native_review)
        expected_spec = (review.get("candidate_spec") or {}).get(
            "sha256", binding["fingerprint"]["files"][binding["spec"]])
        return {**result, "_backend_updates": review["_backend_updates"],
                "_backend_expected_spec_sha256": expected_spec}

    def refresh_binding(self, binding: dict[str, Any], apply_result: dict[str, Any]) -> dict[str, Any]:
        result = deepcopy(binding)
        result.update(deepcopy(apply_result.get("_backend_updates", {})))
        expected = {
            result["document"]: apply_result.get("document_sha256"),
            result["spec"]: apply_result.get("_backend_expected_spec_sha256",
                                               binding["fingerprint"]["files"][binding["spec"]]),
        }
        for path, digest in expected.items():
            if digest is None or file_sha256(Path(path)) != digest:
                raise changed_error("Native output changed after apply; preserve the transaction evidence.", [path])
            result["files"][path] = digest
        result["fingerprint"] = {"files": deepcopy(result["files"]),
                                 "source_trees": deepcopy(result["source_trees"])}
        require_current(result)
        return result

    @warm_native_method
    def export(self, binding: dict[str, Any]) -> dict[str, Any]:
        require_current(binding)
        project = Path(binding["project"])
        with external_project_session(project):
            require_current(binding)
            exported = export_project_document(project_dir=project, document_path=Path(binding["document"]),
                                               formats=["pdf", "tiff_300"])
        require_current(binding)
        return {"status": "exported" if exported.ready_to_use else "blocked",
                "ready_to_use": exported.ready_to_use, "exports": exported.exports,
                "document_sha256": exported.document_sha256, "studio_run": exported.run_payload,
                **export_evidence(exported.run_payload)}

    @warm_native_method
    def render(self, binding: dict[str, Any], output: Path) -> dict[str, Any]:
        require_current(binding)
        return preview_project_document(Path(binding["project"]), output_dir=output,
                                        figure_id=binding["figure_id"])
