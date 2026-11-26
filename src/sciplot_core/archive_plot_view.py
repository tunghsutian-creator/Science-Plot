"""The native view of a committed figure, privately backed by its archive session."""

from collections.abc import Iterator
from contextlib import closing, contextmanager
from pathlib import Path
from typing import Any

from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.foundation.json_io import read_json_object
from sciplot_core.plot_engine.service import public_plot_service
from sciplot_core.plot_ir.figure_document import figure_spec
from sciplot_core.project_lifecycle.contracts import RevisionToken
from sciplot_core.project_lifecycle.errors import EngineError
from sciplot_core.project_lifecycle.project_file_summary import project_file_figure
from sciplot_core.project_store.runtime import project_runtime


@contextmanager
def archive_plot_view(path: Path, figure_id: str | None) -> Iterator[tuple[dict[str, Any], Path, str]]:
    """Render only the selected committed revision; never save this private session."""
    with project_file_figure(path, figure_id) as (session, owner, document):
        root = owner.attachment.root
        with closing(public_plot_service()) as service, project_runtime(session.store):
            summary = service.describe(root, description={"scope": "summary"})
            if summary.get("pending") or summary.get("changed_inputs"):
                raise EngineError("project_file_view_unavailable", "The saved figure has pending or changed inputs.")
            native = Path(summary["artifact"])
            if not native.is_relative_to(session.store.root):
                raise EngineError("project_file_view_unavailable", "The figure has no private native artifact.")
            if (summary["artifact_status"] == "missing"
                    and summary.get("next_step", {}).get("reason") == "rebuild_disposable_artifacts"):
                # The attached renderer can reproduce the committed native artifact
                # in this disposable workspace without exporting or updating the archive.
                service.render(root)
            build = read_json_object(native.with_name("build.json"))
            if (build is None or build.get("ir_hash") != summary["ir_hash"]
                    or file_sha256(native) != build.get("document_sha256")):
                raise EngineError("project_file_view_unavailable", "The native view does not match the saved figure.")
        spec = figure_spec(document)
        ticks = {axis["id"]: {"mode": "automatic"} if axis.get("ticks_mode") == "automatic" else axis["ticks"]
                 for view in spec["views"] for axis in view["axes"]}
        yield ({"project_id": session.project_id, "project_file": str(session.path),
                **{key: document[key] for key in ("plot_id", "revision", "scientific_hash", "presentation_hash")},
                "revision_token": RevisionToken.of(document), "edit_targets": summary["edit_targets"],
                "axis_ticks": ticks, "domain_semantics": spec.get("domain_semantics")}, native, build["document_sha256"])
