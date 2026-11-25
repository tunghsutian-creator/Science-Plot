"""Copy only the requested files from one ready, current Managed publication."""

from collections.abc import Callable
from pathlib import Path
from stat import S_ISDIR, S_ISREG
from tempfile import TemporaryDirectory
from typing import Any, TypedDict

from sciplot_core.delivery.filesystem_metadata import is_delivery_finder_metadata
from sciplot_core.delivery.install import install_new_delivery
from sciplot_core.delivery.native_snapshot import SnapshotSealChanged, copy_sealed_file
from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.foundation.research_destination import require_data_destination
from sciplot_core.foundation.source_locations import selected_source_resolver
from sciplot_core.plot_document.schema import figure_handoff_schema
from sciplot_core.plot_document.validation import validate_wire
from sciplot_core.plot_engine.backend import PlotBackend
from sciplot_core.plot_engine.current import require_current
from sciplot_core.plot_engine.export_status import sealed_publication
from sciplot_core.plot_ir.figure_document import is_figure
from sciplot_core.project_store.source_resolver import ProjectSourceResolver
from sciplot_core.studio_core.source_update_files import reject_symlink_path

from .context import active, has_head, load_head, project_query
from .contracts import RevisionToken
from .errors import EngineError
from .paths import canonical_path


class FigureInstall(TypedDict):
    """Private task witness; identifying the directory also excludes byte-identical foreign output."""
    directory_identity: list[int]
    revision_token: dict[str, Any]
    result: dict[str, Any]


def _directory_identity(path: Path) -> list[int]:
    status = path.lstat()
    if not S_ISDIR(status.st_mode):
        raise ValueError("The selected output is no longer a real directory.")
    return [status.st_dev, status.st_ino]


def _installed_matches(out: Path, token: RevisionToken, result: dict[str, Any], receipt: FigureInstall) -> bool:
    if receipt["revision_token"] != token.to_payload() or receipt["result"] != result:
        return False
    try:
        reject_symlink_path(out)
        if _directory_identity(out) != receipt["directory_identity"]:
            return False
        expected = {Path(item["path"]).name: item["sha256"] for item in result["exports"]}
        actual = {path.name: path for path in out.iterdir() if not is_delivery_finder_metadata(path)}
        return (actual.keys() == expected.keys()
                and all(S_ISREG(path.lstat().st_mode) and file_sha256(path) == expected[name]
                        for name, path in actual.items()))
    except (OSError, ValueError):
        return False


def _publication(root: Path, out: Path, request: dict[str, Any], backend: PlotBackend) -> tuple[RevisionToken, list[dict[str, str]]]:
    with project_query(root):
        if not has_head(root):
            raise EngineError("figure_handoff_managed_required", "Select an exact current Managed v2 plot.")
        head = load_head(root)
        document, binding = head["document"], head["binding"]
        if document.get("plot_type") != "ManagedPlot" or not is_figure(document):
            raise EngineError("figure_handoff_managed_required", "Selected-file handoff requires a Managed v2 figure.")
        token = RevisionToken.of(document)
        if (token.plot_id, token.revision) != (request["plot_id"], request["revision"]):
            raise EngineError("figure_handoff_revision_conflict", "This figure ID or revision is no longer current.",
                              action="plot.describe", plot=str(root))
        pending = active(root)
        if pending and pending["phase"] not in {"complete", "rejected"}:
            raise EngineError("document_transaction_pending", "Finish or reject the current plot operation before handing off its figure.")
        resolver = selected_source_resolver()
        protected = [root, Path(binding["output"]), *(Path(source["path"]) for source in document["scientific"]["data_sources"])]
        if isinstance(resolver, ProjectSourceResolver):
            protected.append(resolver.store.root)
        if any(out.is_relative_to(canonical_path(path)) for path in protected):
            raise EngineError("figure_handoff_output_overlap", "Choose a new directory outside the original project, sources and artifacts.")
        require_current(backend, binding)
        publication = sealed_publication(root, head) or {}
        if publication.get("ready_to_use") is True:
            records = [entry for entry in publication["exports"] if entry["format"] in request["formats"]]
            if len(records) == len(request["formats"]) and {entry["format"] for entry in records} == set(request["formats"]):
                return token, records
        raise EngineError("figure_handoff_publication_unready", "Finish the existing plot export first; this handoff does not rebuild a publication.",
                          action="plot.export", plot=str(root))


def handoff_figure(root: Path, request: dict[str, Any], backend: PlotBackend, *,
                   before_install: Callable[[FigureInstall], None] | None = None,
                   installed: FigureInstall | None = None) -> dict[str, Any]:
    """Install a new visible delivery, or only verify one task's frozen installation."""
    validate_wire(request, figure_handoff_schema(), code="figure_handoff_invalid_request")
    if type(request["revision"]) is not int:
        raise EngineError("figure_handoff_invalid_request", "Use the integer revision from plot describe.")
    try:
        out = require_data_destination(canonical_path(Path(request["output_dir"])))
    except (OSError, ValueError) as exc:
        raise EngineError("figure_handoff_invalid_destination", str(exc)) from exc
    if installed is None and out.exists():
        raise EngineError("figure_handoff_destination_exists", "Choose a new output directory; nothing was replaced.")
    if not out.parent.is_dir():
        raise EngineError("figure_handoff_invalid_destination", "The parent directory must already exist.")
    token, records = _publication(root, out, request, backend)
    files = [{**record, "path": str(out / Path(record["path"]).name)} for record in records]
    result = {"kind": "sciplot_figure_handoff", "version": 1, "status": "exported", "ready_to_use": True,
              "plot": str(root), "plot_id": token.plot_id, "revision": token.revision, "output_dir": str(out),
              "exports": files}
    if installed is not None:
        if _installed_matches(Path(request["output_dir"]), token, result, installed):
            return result
        raise EngineError("figure_handoff_install_changed", "The task's selected-file delivery is missing, changed or not its own; nothing was replaced.")
    try:
        with TemporaryDirectory(prefix=".sciplot-figure-", dir=out.parent) as temporary:
            staged = Path(temporary) / "figure"
            staged.mkdir()
            for record in records:
                source = Path(record["path"])
                copy_sealed_file(source, staged / source.name, record["sha256"])
            if before_install is not None:
                before_install({"directory_identity": _directory_identity(staged),
                                "revision_token": token.to_payload(), "result": result})
            if _publication(root, out, request, backend) != (token, records):
                raise EngineError("figure_handoff_publication_changed", "The selected publication changed during handoff.")
            install_new_delivery(staged, out)
    except FileExistsError as exc:
        raise EngineError("figure_handoff_destination_exists", "Choose a new output directory; nothing was replaced.") from exc
    except SnapshotSealChanged as exc:
        raise EngineError("figure_handoff_publication_changed", str(exc)) from exc
    return result
