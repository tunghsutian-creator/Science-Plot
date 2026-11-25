"""Read exact saved project figure identities without opening or altering them."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

from sciplot_core.delivery_identity import DELIVERY_IDENTITY, delivery_identity_path, read_delivery_binding
from sciplot_core.foundation.canonical_paths import canonical_path
from sciplot_core.project_store.io import observe_existing_store
from sciplot_core.figure_plan import resolved_figure_plan_from_payload
from sciplot_core.foundation.file_hashing import existing_file_sha256
from sciplot_core.foundation.source_locations import resolve_source_path
from sciplot_core.policy import DELIVERY_LAUNCHER
from sciplot_core.studio_core.delivery_target import _managed_project
from sciplot_core.studio_core.figure_set_state import _read_studio_figure_set


if TYPE_CHECKING:
    from sciplot_core.project_store import FileProjectStore
    from .attachment_index import Attachment
    from .ports import ProjectRepository


FREQUENCY_AUTHORITY = ".sciplot-frequency"
FREQUENCY_RECORD = "frequency-creation.json"


def read_object(path: Path) -> dict[str, Any]:
    canonical_path(path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Expected a JSON object: {path}")
    return payload


def bound_delivery_project(root: Path) -> Path:
    """Identify ownership even when a visible VSZ has outstanding edits."""
    root = canonical_path(root)
    canonical_path(delivery_identity_path(root))
    binding = read_delivery_binding(root)
    if binding is None or binding.request is None:
        raise ValueError("Portable delivery has no associated managed project.")
    project = _managed_project(root, binding)
    if project is None:
        raise ValueError(
            "Portable or relocated delivery has no current project binding."
        )
    canonical_path(resolve_source_path(binding.request))
    if binding.source is not None:
        from sciplot_core.studio_core.project_query_sources import current_source_files

        files, identities = current_source_files(project, Path(binding.source), project_snapshot(project)[2])
        from sciplot_core.project_store.runtime import inspect_runtime_source_file, inspect_runtime_source_tree

        if files:
            for path, digest in files.items():
                inspect_runtime_source_file(path, expected_sha256=digest, source_id=identities.get(path))
        else:
            inspect_runtime_source_tree(binding.source)
    return canonical_path(project)


def resolve_project_path(value: Path) -> Path:
    """Resolve explicit project entries; never discover a project from raw data."""
    path = canonical_path(value)
    if path.is_dir() and (path / "plot_request.json").is_file():
        project = path
    elif path.is_file() and path.name == "plot_request.json":
        project = path.parent
    elif path.is_file() and path.suffix.lower() == ".vsz":
        studio = path.parent.parent if path.parent.name == "figures" else path.parent
        if studio.name == "studio" and (studio.parent / "plot_request.json").is_file():
            project = studio.parent
            _, _, figures = project_snapshot(project)
            if not any(item["document"] == str(path) for item in figures):
                raise ValueError(
                    "The VSZ is not a registered canonical project figure."
                )
        elif path.parent.name == "project":
            project = bound_delivery_project(path.parent.parent)
            binding = read_delivery_binding(path.parent.parent)
            if binding is None or path.name not in dict(binding.documents):
                raise ValueError("The visible VSZ is not registered in this delivery.")
        else:
            raise ValueError("Standalone VSZ has no managed project binding.")
    elif path.is_dir() or path.name in {DELIVERY_LAUNCHER, DELIVERY_IDENTITY}:
        root = path if path.is_dir() else path.parent
        if (root / "plot_request.json").is_file():
            project = root
        else:
            project = bound_delivery_project(root)
    else:
        raise ValueError(
            "Expected a project, plot_request.json, registered VSZ, or bound delivery."
        )
    read_object(project / "plot_request.json")
    canonical_path(project / "studio" / "document.vsz")
    if not (project / "studio" / "document.vsz").is_file():
        raise ValueError("The managed project has no saved canonical document.")
    return project


def project_snapshot(project: Path) -> tuple[dict[str, Any], str, list[dict[str, Any]]]:
    request = read_object(project / "plot_request.json")
    studio = project / "studio"
    # Legacy path normalization resolves paths. Check the original member paths
    # first so an in-tree symlink cannot disappear during normalization.
    for member in (
        studio / "document.vsz",
        studio / "spec.json",
        studio / "figures",
        *(studio / "figures").glob("*.vsz"),
        *(studio / "figures").glob("*.spec.json"),
    ):
        canonical_path(member)
    plan = resolved_figure_plan_from_payload(request.get("resolved_figure_plan"))
    registry_path = project / "studio" / "figure_set.json"
    canonical_path(registry_path)
    registry = _read_studio_figure_set(
        project, expected_plan=plan, require_ready_artifacts=True
    )
    if registry is None and plan is None and registry_path.is_file():
        # Legacy registries have no task contract. Preserve their read-only
        # identities without upgrading their evidence or permitting escape paths.
        if read_object(registry_path).get("version") == 1:
            registry = _read_studio_figure_set(project)
    if registry is None:
        if registry_path.exists() or plan is not None:
            raise ValueError(
                "The figure-set registry is missing, corrupt, or inconsistent."
            )
        primary_id = "primary"
        entries = [
            {
                "figure_id": primary_id,
                "status": "ready",
                "document": str(project / "studio" / "document.vsz"),
                "spec": str(project / "studio" / "spec.json"),
            }
        ]
    else:
        primary_id = str(registry["primary_figure_id"])
        entries = registry["figures"]
    figures: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in entries:
        identity = str(item["figure_id"])
        if identity in seen:
            raise ValueError("Figure identities must be unique within a project.")
        seen.add(identity)
        document, spec = (
            canonical_path(Path(item["document"])),
            canonical_path(Path(item["spec"])),
        )
        if not all(
            path.is_relative_to(project / "studio") for path in (document, spec)
        ):
            raise ValueError("A registered figure path escapes its project.")
        if item.get("status") == "ready" and not all(
            path.is_file() for path in (document, spec)
        ):
            raise ValueError(
                "A ready figure is missing its saved document or specification."
            )
        figures.append(
            {
                "figure_id": identity,
                "title": item.get("title") or identity,
                "primary": identity == primary_id,
                "status": item.get("status"),
                "document": str(document),
                "spec": str(spec),
                "document_sha256": existing_file_sha256(document),
                "spec_sha256": existing_file_sha256(spec),
            }
        )
    if primary_id not in seen or not figures:
        raise ValueError("The project has no registered primary figure.")
    return request, primary_id, figures


def select_figure(
    value: Path, primary_id: str, figures: list[dict[str, Any]], figure_id: str | None
) -> dict[str, Any]:
    identity = figure_id
    if value.suffix.lower() == ".vsz":
        path = canonical_path(value)
        matches = [item for item in figures if item["document"] == str(path)]
        if matches:
            registered = matches[0]["figure_id"]
            if identity is not None and identity != registered:
                raise ValueError("The figure ID does not match this saved VSZ.")
            identity = registered
        elif identity is None and path.parent.name == "project":
            binding = read_delivery_binding(path.parent.parent)
            if binding is None or path.name != binding.primary:
                raise ValueError("Select the figure_id explicitly for a secondary visible VSZ.")
    identity = primary_id if identity is None else identity
    matches = [item for item in figures if item["figure_id"] == identity]
    if not matches:
        raise ValueError(f"Unknown figure_id: {identity}")
    selected = matches[0]
    if selected["status"] != "ready" or not selected["document_sha256"]:
        raise ValueError(f"The selected figure has no saved document: {identity}")
    return selected


@dataclass(frozen=True)
class LegacyFigureObservation:
    """One saved native registry and its byte witnesses, not publication readiness."""

    target: Path
    project: Path
    request: dict[str, Any]
    request_sha256: str | None
    registry_sha256: str | None
    primary_figure_id: str
    figures: list[dict[str, Any]]

    def select(self, figure_id: str | None = None) -> dict[str, Any]:
        return select_figure(self.target, self.primary_figure_id, self.figures, figure_id)

    def require_current(self, *, selected: dict[str, Any] | None = None) -> None:
        figures = self.figures if selected is None else (selected,)
        if (existing_file_sha256(self.project / "plot_request.json") != self.request_sha256
                or existing_file_sha256(self.project / "studio/figure_set.json") != self.registry_sha256
                or any(existing_file_sha256(Path(figure[field])) != figure[field + "_sha256"]
                       for figure in figures for field in ("document", "spec"))):
            raise ValueError("The saved project changed during inspection; query again.")


@observe_existing_store()
def observe_legacy_project(target: Path) -> LegacyFigureObservation:
    """Read the existing native registry, without attaching a semantic writer."""
    project = resolve_project_path(target)
    request_sha = existing_file_sha256(project / "plot_request.json")
    registry_sha = existing_file_sha256(project / "studio/figure_set.json")
    request, primary, figures = project_snapshot(project)
    return LegacyFigureObservation(target, project, request, request_sha, registry_sha, primary, figures)


def resolve_project_figure(project: Path, figure_id: str | None = None) -> dict[str, Any]:
    """Select one exact saved native member without starting a Qt runtime."""
    observation = observe_legacy_project(project)
    selected = observation.select(figure_id)
    observation.require_current(selected=selected)
    return {"project": str(observation.project), **selected}


@observe_existing_store()
def observe_plot_head(plot: Path, *, owner: ProjectRepository | None = None,
                      optional: bool = False) -> dict[str, Any] | None:
    """Read one sealed semantic head using the existing repository's query scope."""
    from .context import repository_scope
    from .repository_router import ComposedProjectRepository

    plot = canonical_path(plot)
    selected = owner if owner is not None else ComposedProjectRepository()
    with repository_scope(selected), selected.query_scope(plot):
        if not selected.has_head(plot):
            if optional:
                return None
            # Retain the repository's own missing/invalid head error.
            return selected.load_head(plot)
        pointer = plot / "head.json"
        before = selected.content_snapshot(pointer)["sha256"]
        head = selected.load_head(plot)
        if selected.content_snapshot(pointer)["sha256"] != before:
            raise ValueError("The selected plot revision changed during observation.")
        return head


def attachments_by_figure(store: FileProjectStore, index: dict[str, Any]) -> dict[str, Attachment]:
    """The stable project figure key is not a plot ID or a namespace path."""
    from .attachment_index import Attachment

    attachments: dict[str, Attachment] = {}
    for entry in index["attachments"].values():
        figure_id = entry["figure_id"]
        if figure_id in attachments:
            raise ValueError("One figure has competing current semantic attachments.")
        attachments[figure_id] = Attachment(store, entry)
    return attachments


@observe_existing_store()
def observe_project_figure_heads(project: Path, figure_ids: Sequence[str]) -> dict[str, tuple[Path, dict[str, Any]]]:
    """Read selected project attachments together; never fall back to their old shadows."""
    from sciplot_core.project_store.io import STORE
    from .attached_repository import AttachedProjectRepository
    from .attachment_index import read_index, require_local_owner
    from .repository import document_root
    from .store_composition import existing_store

    project = canonical_path(project)
    store = None
    snapshot = None
    registered: dict[str, Attachment] = {}
    if (project / STORE / "head.json").is_file():
        store = existing_store(project)
        snapshot = store.observe_members(projection=False).selected
        registered = attachments_by_figure(store, read_index(store, snapshot))
    heads = {}
    for figure_id in figure_ids:
        attachment = registered.get(figure_id)
        if attachment is not None:
            head = observe_plot_head(attachment.root, owner=AttachedProjectRepository(attachment))
            assert head is not None
            if head["document"]["plot_id"] != attachment.entry["plot_id"]:
                raise ValueError("The selected semantic attachment has a different plot identity.")
            heads[figure_id] = (attachment.root, head)
        else:
            plot = document_root(project, figure_id)
            require_local_owner(plot)
            head = observe_plot_head(plot, optional=True)
            if head is not None:
                heads[figure_id] = (plot, head)
    if store is not None and snapshot is not None and store.observe_members(projection=False).selected["generation"] != snapshot["generation"]:
        raise ValueError("The semantic attachments changed during figure observation.")
    return heads


@dataclass(frozen=True)
class FrequencyFigureObservation:
    """Registered Managed members of one saved generation, published or not."""

    generation: str
    projection_status: str | None
    primary_figure_id: str
    figures: list[dict[str, Any]]


@observe_existing_store()
def observe_frequency_figures(project: Path, *, projection: bool = False) -> FrequencyFigureObservation:
    """Select canonical members in the saved order, independent of sibling export status."""
    from sciplot_core.project_lifecycle.attachment_index import INDEX, validate_index
    from sciplot_core.project_store import FileProjectStore

    project = canonical_path(project)
    if not (project / ".sciplot_store/head.json").is_file():
        raise ValueError("The Managed frequency project has no registered figure plan.")
    store = FileProjectStore(project)
    observation = store.observe_members((INDEX, "figure-plan.json"), projection=projection)
    plan_bytes = observation.members["figure-plan.json"].data
    index_bytes = observation.members[INDEX].data
    if plan_bytes is None or index_bytes is None:
        raise ValueError("The Managed frequency project has no registered figure plan.")
    plan = resolved_figure_plan_from_payload(json.loads(plan_bytes))
    entries = attachments_by_figure(store, validate_index(json.loads(index_bytes), observation.selected["project_id"]))
    if (plan is None or not plan.selected_figure_ids
            or not set(plan.selected_figure_ids).issubset(entries)):
        raise ValueError("The saved frequency figure plan and attachment index do not agree.")
    figures = [{"figure_id": task.figure_id, "title": task.title, "plot_id": entries[task.figure_id].entry["plot_id"],
                "plot": str(entries[task.figure_id].root)} for task in plan.tasks]
    status = observation.projection["projection_status"] if observation.projection is not None else None
    return FrequencyFigureObservation(observation.selected["generation"], status, plan.primary_figure_id, figures)


def locate_frequency_project(value: Path) -> tuple[Path, Path, dict[str, Any], Path | None] | None:
    """Identify the written frequency authority without consulting its publication."""
    from sciplot_core.foundation.json_hashing import canonical_json_sha256
    from sciplot_core.foundation.json_io import read_json_object
    from sciplot_core.output_contract import REQUEST_DELIVERY_ROOT_KEY
    from sciplot_core.policy.render_options import DELIVERY_PROJECT_DIR

    project = canonical_path(value)
    workspace = project.parent.parent if project.parent.name == FREQUENCY_AUTHORITY else None
    visible = binding = None
    document = project if project.suffix.casefold() == ".vsz" and project.parent.name == DELIVERY_PROJECT_DIR else None
    if workspace is None:
        if project.name == "plot_request.json":
            workspace = project.parent
        elif project.is_dir() and (project / FREQUENCY_RECORD).is_file():
            workspace = project
        else:
            visible = (project.parent.parent if document is not None
                       else project.parent if project.name == DELIVERY_IDENTITY else project)
            if not visible.is_dir() or not (visible / DELIVERY_IDENTITY).is_file():
                return None
            binding = read_delivery_binding(visible)
            if binding is None or not binding.request:
                return None
            workspace = Path(binding.request).parent
    creation = read_json_object(workspace / FREQUENCY_RECORD)
    if creation is None:
        return None
    request = creation["request"]
    canonical_request = workspace / "plot_request.json"
    if read_json_object(canonical_request) != request:
        raise ValueError("The saved Managed frequency plotting request changed.")
    authority = workspace / FREQUENCY_AUTHORITY / canonical_json_sha256(request)
    if ((visible is not None and (visible != Path(request[REQUEST_DELIVERY_ROOT_KEY])
                                  or binding.root != str(visible) or binding.request != str(canonical_request)))
            or (project.parent.name == FREQUENCY_AUTHORITY and project != authority)):
        raise ValueError("The selected frequency location does not match its exact saved project.")
    if document is not None:
        if not document.is_file():
            raise ValueError(f"The selected delivery document does not exist: {document}")
        if binding is None or document.name not in dict(binding.documents):
            raise ValueError(f"The selected VSZ is not registered in this delivery: {document}")
    return authority, canonical_request, creation, document
