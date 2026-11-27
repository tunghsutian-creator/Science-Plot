"""The editor’s selection, native view and typed requests for a standalone archive."""

from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, Literal

from sciplot_core.delivery.install import install_new_delivery
from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.foundation.json_io import read_json_object
from sciplot_core.foundation.research_destination import require_data_destination
from sciplot_core.plot_engine.service import PlotService, public_plot_service
from sciplot_core.plot_ir.figure_document import figure_spec
from sciplot_core.project_lifecycle.contracts import RevisionToken
from sciplot_core.project_lifecycle.errors import EngineError
from sciplot_core.project_lifecycle.project_file import ProjectFileSession
from sciplot_core.project_lifecycle.project_file_handoff import project_file_handoff
from sciplot_core.project_lifecycle.project_file_summary import _summarize, saved_project_file_figure
from sciplot_core.project_store.runtime import project_runtime


def is_archive_target(path: Path) -> bool:
    return path.suffix == ".sciplot" and (path.is_symlink() or not path.is_dir())


def editor_target_path(path: Path, figure_id: str | None) -> Path:
    expanded = path.expanduser()
    if is_archive_target(expanded):
        # The archive owner must see and reject aliases rather than resolve them.
        return expanded
    if figure_id is not None:
        raise ValueError("--figure 只用于 .sciplot 项目文件。")
    return expanded.resolve()


def _require_project(expected: str | None, actual: str) -> None:
    if expected is not None and expected != actual:
        raise ValueError("这个路径上的项目已被替换。请关闭窗口，再打开要编辑的项目。")


def archive_plot_view(service: PlotService, session: ProjectFileSession, figure_id: str | None, *,
                      expected_project_id: str | None) -> tuple[dict[str, Any], Path | None, str | None]:
    """Return choices or one private native view owned by the caller's session."""
    _require_project(expected_project_id, session.project_id)
    try:
        owner, document = saved_project_file_figure(session, figure_id)
    except EngineError as exc:
        if figure_id is not None or exc.reason_code != "project_file_figure_ambiguous":
            raise
        return {"project_id": session.project_id, "figures": exc.repair["figures"]}, None, None

    root = owner.attachment.root
    with project_runtime(session.store):
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
    return ({"project_id": session.project_id, "project_file": str(session.path),
            **{key: document[key] for key in ("plot_id", "revision", "scientific_hash", "presentation_hash")},
            "revision_token": RevisionToken.of(document), "edit_targets": _summarize(session, document)["edit_targets"],
            "axis_ticks": ticks, "domain_semantics": spec.get("domain_semantics")}, native, build["document_sha256"])


def export_archive_figure(path: Path, output: Path, *, export_format: Literal["pdf", "tiff_300"],
                          project_id: str, revision: RevisionToken) -> None:
    """Publish a typed handoff to one exact filename, without overwriting."""
    output = require_data_destination(output.parent) / output.name
    if output.exists() or output.is_symlink():
        raise FileExistsError(output)
    with TemporaryDirectory(prefix=".sciplot-export-", dir=output.parent) as temporary:
        with closing(public_plot_service()) as service:
            result = project_file_handoff(
                service, path, {"plot_id": revision.plot_id, "revision": revision.revision,
                                "formats": [export_format], "output_dir": str(Path(temporary) / "handoff")},
                expected_project_id=project_id, expected_revision=revision)
        [exported] = result["exports"]
        install_new_delivery(Path(exported["path"]), output)
