"""One private Studio project image; only its host may publish captured bytes."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import UTC, datetime
import json
import os
from pathlib import Path
import stat
from tempfile import TemporaryDirectory
from typing import Any
from uuid import uuid4

from sciplot_core.project_commands import PreparedFile, SourceTreeRead, InputRead
from sciplot_core.project_commands.resources import resource_key
from sciplot_core.project_store import FileProjectStore, ProjectConflict
from sciplot_core.project_store.io import directory, install, read_file, sha
from sciplot_core.data_mapping.execution_inputs import MappingInputReadSet

_ACTIVE: ContextVar[StudioPreparationCandidate | None] = ContextVar("studio_preparation_candidate", default=None)


def _files(root: Path, *, descriptor: int | None = None) -> dict[str, PreparedFile]:
    """Capture ordinary members through directory descriptors, never aliases."""
    def visit(fd: int, prefix: str) -> dict[str, PreparedFile]:
        result = {}
        for name in sorted(os.listdir(fd)):
            info = os.stat(name, dir_fd=fd, follow_symlinks=False)
            logical = prefix + name
            if stat.S_ISDIR(info.st_mode):
                with directory(fd, (name,)) as child:
                    result.update(visit(child, logical + "/"))
            elif stat.S_ISREG(info.st_mode):
                data, mode = read_file(fd, name, owned=True)
                result[logical] = PreparedFile(data, mode)
            else:
                raise ProjectConflict("A private Studio candidate contains an aliased or special member.")
        return result

    if descriptor is not None:
        return visit(descriptor, "")
    fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        return visit(fd, "")
    finally:
        os.close(fd)


@dataclass
class StudioPreparationCandidate:
    store: FileProjectStore
    snapshot: dict[str, Any]
    project_dir: Path
    resources: Path
    request_members: set[str] = field(default_factory=lambda: {"plot_request.json"})
    mapping_inputs: dict[str, MappingInputReadSet] = field(default_factory=dict)
    _root_identity: tuple[int, int] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        info = self.project_dir.lstat()
        self._root_identity = (info.st_dev, info.st_ino)

    @contextmanager
    def root_descriptor(self) -> Iterator[int]:
        fd = os.open(self.project_dir, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            info = os.fstat(fd)
            if ((info.st_dev, info.st_ino) != self._root_identity
                    or info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) != 0o700):
                raise ProjectConflict("The private Studio project directory changed identity.")
            yield fd
            current = self.project_dir.lstat()
            if (current.st_dev, current.st_ino) != self._root_identity:
                raise ProjectConflict("The private Studio project directory changed identity.")
        finally:
            os.close(fd)

    def write_member(self, relative: str, data: bytes, *, mode: int = 0o644) -> None:
        resource_key(relative)
        if relative.startswith("@"):
            raise ProjectConflict("A private Studio member cannot select an external resource.")
        parts = tuple(relative.split("/"))
        with self.root_descriptor() as root:
            with directory(root, parts[:-1], create=True) as parent:
                install(parent, parts[-1], data, mode=mode)

    def read_member(self, relative: str) -> PreparedFile:
        resource_key(relative)
        if relative.startswith("@"):
            raise ProjectConflict("A private Studio member cannot select an external resource.")
        parts = tuple(relative.split("/"))
        with self.root_descriptor() as root:
            with directory(root, parts[:-1]) as parent:
                data, mode = read_file(parent, parts[-1], owned=True)
        return PreparedFile(data, mode)

    def remove_member(self, relative: str) -> None:
        """Apply one exact frozen deletion only within this private image."""
        resource_key(relative)
        parts = tuple(relative.split("/"))
        if (relative.startswith("@") or parts[0] in {"raw", "source", ".sciplot_store"}
                or relative in self.snapshot.get("input_resources", [])):
            raise ProjectConflict("A private deletion cannot select scientific inputs or another resource root.")
        with self.root_descriptor() as root:
            try:
                with directory(root, parts[:-1]) as parent:
                    read_file(parent, parts[-1], owned=True)
                    os.unlink(parts[-1], dir_fd=parent)
                    os.fsync(parent)
            except FileNotFoundError:
                pass

    def write_request(self, payload: dict[str, Any], *, relative: str = "plot_request.json") -> None:
        if Path(relative).suffix != ".json":
            raise ValueError("Studio requests must be JSON project members.")
        try:
            mode = self.read_member(relative).mode
        except FileNotFoundError:
            mode = 0o644
        self.write_member(relative, json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False).encode(), mode=mode)
        self.request_members.add(relative)

    @property
    def logical_root(self) -> Path:
        return self.store.root

    @property
    def mapping_tree_reads(self) -> tuple[SourceTreeRead, ...]:
        from sciplot_core.data_mapping.execution_directories import mapping_live_trees

        trees: dict[str, SourceTreeRead] = {}
        for readset in self.mapping_inputs.values():
            for tree in mapping_live_trees(readset):
                literal = tree.locator
                if literal in trees and trees[literal] != tree:
                    raise ProjectConflict("A private preparation observed different mapping directory versions.")
                trees[literal] = tree
        return tuple(trees[name] for name in sorted(trees))

    @property
    def mapping_input_reads(self) -> tuple[InputRead, ...]:
        values: dict[str, InputRead] = {}
        for readset in self.mapping_inputs.values():
            for item in readset.input_reads(self.snapshot):
                if item.resource in values and values[item.resource] != item:
                    raise ProjectConflict("A private preparation has conflicting metadata input identities.")
                values[item.resource] = item
        return tuple(values[name] for name in sorted(values))

    def resource_path(self, logical: str) -> Path:
        """Select a private output for one already granted logical resource."""
        resource_key(logical)
        parts = logical.split("/")
        if not parts[0].startswith("@"):
            return self.project_dir.joinpath(*parts)
        key = parts[0][1:]
        if key not in self.store.locations:
            raise ProjectConflict("The host did not grant this candidate resource root.")
        relative = "/".join(parts[1:])
        members = self.store.location_members[key]
        if members is not None and relative not in members:
            raise ProjectConflict("The private output is outside its finite resource capability.")
        root = self.resources / key
        root.mkdir(mode=0o700, exist_ok=True)
        return root.joinpath(*parts[1:])

    def logical_path(self, physical: str) -> str:
        path = Path(physical)
        if path.is_absolute() and path.is_relative_to(self.project_dir):
            return str(self.logical_root / path.relative_to(self.project_dir))
        for key in self.store.locations:
            root = self.resources / key
            if path.is_absolute() and path.is_relative_to(root):
                return str(self.store.locations[key] / path.relative_to(root))
        return physical

    def project_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Project only the closed host artifact fields, never scientific JSON."""
        result = deepcopy(payload)

        def paths(value: dict[str, Any], keys: tuple[str, ...]) -> None:
            for key in keys:
                if isinstance(value.get(key), str):
                    value[key] = self.logical_path(value[key])

        def plan(value: Any) -> None:
            if isinstance(value, dict):
                for outcome in value.get("outcomes", []):
                    if isinstance(outcome, dict) and isinstance(outcome.get("artifacts"), list):
                        outcome["artifacts"] = [self.logical_path(item) if isinstance(item, str) else item
                                                for item in outcome["artifacts"]]

        def figures(value: Any) -> None:
            if not isinstance(value, dict):
                return
            paths(value, ("primary_document", "generated_from", "registry_path"))
            for figure in value.get("figures", []):
                if isinstance(figure, dict):
                    paths(figure, ("document", "spec"))
            plan(value.get("resolved_figure_plan"))

        paths(result, ("project_dir", "request", "document", "launcher", "veusz_launcher", "export_edited_launcher"))
        plan(result.get("resolved_figure_plan"))
        figures(result.get("figure_set"))
        studio = result.get("studio")
        if isinstance(studio, dict):
            paths(studio, ("document", "spec", "launcher", "veusz_launcher", "export_edited_launcher",
                           "generated_from", "figure_set_registry"))
            figures(studio.get("figure_set"))
            plan(studio.get("resolved_figure_plan"))
        contract = result.get("launcher_contract")
        if isinstance(contract, dict):
            primary = contract.get("primary")
            if isinstance(primary, dict):
                paths(primary, ("path",))
            supporting = contract.get("supporting")
            if isinstance(supporting, dict):
                for item in supporting.values():
                    if isinstance(item, dict):
                        paths(item, ("path",))
        return result

    def capture(self) -> dict[str, PreparedFile | None]:
        with self.root_descriptor() as root_fd:
            current = _files(self.project_dir, descriptor=root_fd)
        if any(name.startswith(".sciplot_store/") for name in current):
            raise ProjectConflict("A private producer cannot create another project authority.")
        writes: dict[str, PreparedFile | None] = {}
        original = {name: value for name, value in self.snapshot["files"].items() if not name.startswith("@")}
        for name in original.keys() | current.keys():
            before, after = original.get(name), current.get(name)
            before_identity = (before["sha256"], before["mode"]) if before else None
            after_identity = (sha(after.data), after.mode) if after else None
            if before_identity == after_identity:
                continue
            if name.split("/", 1)[0] in {"raw", "source"} or name in self.snapshot.get("input_resources", []):
                raise ProjectConflict("Studio preparation cannot replace original scientific inputs.")
            writes[name] = after
        for key in self.store.locations:
            root = self.resources / key
            if root.exists():
                current_resource = _files(root)
                original_resource = {name[len(key) + 2:]: value for name, value in self.snapshot["files"].items()
                                     if name.startswith("@" + key + "/")}
                for relative in original_resource.keys() | current_resource.keys():
                    prepared, before = current_resource.get(relative), original_resource.get(relative)
                    logical = "@" + key + "/" + relative
                    self.resource_path(logical)
                    old = (before["sha256"], before["mode"]) if before else None
                    new = (sha(prepared.data), prepared.mode) if prepared else None
                    if old == new:
                        continue
                    if logical in self.snapshot.get("input_resources", []):
                        raise ProjectConflict("A private resource projection cannot replace scientific inputs.")
                    writes[logical] = prepared
        return writes

    def finalize(self) -> None:
        """Serialize only owned host projections into their final logical paths."""
        paths = [*(self.project_dir / name for name in sorted(self.request_members)), self.project_dir / "studio/figure_set.json",
                 self.project_dir / "intake_manifest.json", *self.project_dir.glob("*.sciplot.json")]
        for path in paths:
            relative = path.relative_to(self.project_dir).as_posix()
            try:
                captured = self.read_member(relative)
            except FileNotFoundError:
                continue
            original = json.loads(captured.data)
            if path.name == "figure_set.json":
                projected = self.project_payload({"figure_set": original})["figure_set"]
            else:
                projected = self.project_payload(original)
            if projected != original:
                self.write_member(relative, json.dumps(projected, ensure_ascii=False, indent=2).encode(), mode=captured.mode)


def active_preparation_candidate(project: Path) -> StudioPreparationCandidate | None:
    selected = _ACTIVE.get()
    return selected if selected is not None and project.expanduser().resolve() == selected.project_dir else None


def require_preparation_candidate(project: Path) -> StudioPreparationCandidate:
    selected = active_preparation_candidate(project)
    if selected is None:
        raise ProjectConflict("A Studio producer requires its host-owned private project candidate.")
    return selected


@contextmanager
def private_preparation_scope(candidate: StudioPreparationCandidate) -> Iterator[None]:
    """Bind an already host-validated disposable image, without another store."""
    with candidate.root_descriptor():
        token = _ACTIVE.set(candidate)
        try:
            yield
        finally:
            _ACTIVE.reset(token)


def install_prepared_figure_set(*, project_dir: Path, replacements: list[dict[str, Any]],
                               manual_archive_requests: list[dict[str, Any]], registry: dict[str, Any] | None,
                               path_replacer: Any = None) -> None:
    """Install into a disposable image; failure never restores active files."""
    candidate = require_preparation_candidate(project_dir)
    from sciplot_core.studio_core.figure_set_storage import _validate_staged_figure_set_task_evidence
    from sciplot_core.studio_core.registry_state import _studio_figure_set_path

    if registry is not None:
        _validate_staged_figure_set_task_evidence(project_dir=project_dir, replacements=replacements, registry=registry)
    pending = {}
    for item in replacements:
        source, target = Path(item["staged"]), Path(item["target"])
        if (not source.is_relative_to(project_dir) or not target.is_relative_to(project_dir)
                or target == source or target.is_symlink()):
            raise ProjectConflict("A private figure-set install cannot address active or foreign members.")
        with candidate.root_descriptor() as root:
            with directory(root, tuple(source.relative_to(project_dir).parts[:-1])) as parent:
                data, mode = read_file(parent, source.name, owned=True)
        if sha(data) != item["expected_hash"] or target in pending:
            raise ProjectConflict("A prepared figure is duplicate or differs from its exact candidate.")
        pending[target] = (source, PreparedFile(data, mode))
    for request in manual_archive_requests:
        document, spec = Path(request["document"]), Path(request["spec"])
        if document not in pending or not document.is_file():
            continue
        previous = candidate.read_member(document.relative_to(project_dir).as_posix())
        data = previous.data
        if sha(data) == request.get("generated_hash"):
            continue
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ") + "_" + uuid4().hex[:8]
        history = document.parent.relative_to(project_dir) / "history"
        candidate.write_member((history / f"{document.stem}_{stamp}{document.suffix}").as_posix(), data, mode=previous.mode)
        if spec in pending and spec.is_file():
            previous_spec = candidate.read_member(spec.relative_to(project_dir).as_posix())
            candidate.write_member((history / f"{document.stem}_{stamp}.spec.json").as_posix(),
                previous_spec.data, mode=previous_spec.mode)
    for target, (source, captured) in pending.items():
        relative = target.relative_to(project_dir).as_posix()
        if path_replacer is None:
            candidate.write_member(relative, captured.data, mode=captured.mode)
            source.unlink()
        else:
            # A trusted fault-injection seam runs only against disposable files.
            with candidate.root_descriptor() as root:
                with directory(root, tuple(target.relative_to(project_dir).parts[:-1]), create=True):
                    path_replacer(source, target)
        with candidate.root_descriptor() as root:
            with directory(root, tuple(target.relative_to(project_dir).parts[:-1])) as parent:
                installed, installed_mode = read_file(parent, target.name, owned=True)
        if installed != captured.data or installed_mode != captured.mode:
            raise ProjectConflict("The private figure-set installer changed candidate bytes.")
    if registry is not None:
        candidate.write_member(_studio_figure_set_path(candidate.project_dir).relative_to(project_dir).as_posix(),
            json.dumps(registry, ensure_ascii=False, indent=2).encode())


def register_prepared_studio_block(project: Path, block: dict[str, Any]) -> None:
    """Update the candidate's mirrors without publishing a nested head or ZIP."""
    candidate = require_preparation_candidate(project)
    from sciplot_core.figure_plan import sync_figure_plan_projection
    from sciplot_core.launchers import LEGACY_WEB_WORKBENCH_LAUNCHER, inspect_project_launcher_contract
    from sciplot_core.intake.packaging import _apply_launcher_contract_to_manifest

    with candidate.root_descriptor() as root:
        try:
            os.unlink(LEGACY_WEB_WORKBENCH_LAUNCHER, dir_fd=root)
        except FileNotFoundError:
            pass
    paths = [project / "intake_manifest.json", *sorted(project.glob("*.sciplot.json"))]
    payload = None
    for path in paths:
        try:
            payload = json.loads(candidate.read_member(path.name).data)
        except FileNotFoundError:
            continue
        break
    if payload is None:
        return
    payload["studio"] = block
    sync_figure_plan_projection(payload, block)
    _apply_launcher_contract_to_manifest(payload, contract=inspect_project_launcher_contract(project))
    data = json.dumps(payload, ensure_ascii=False, indent=2)
    for path in paths:
        candidate.write_member(path.relative_to(project).as_posix(), data.encode())


@contextmanager
def studio_preparation_candidate(store: FileProjectStore, *, snapshot: dict[str, Any] | None = None) -> Iterator[StudioPreparationCandidate]:
    from sciplot_core.project_store.runtime import project_candidate_runtime
    from sciplot_core.project_manifest import private_project_manifest_scope

    before = snapshot or store.snapshot(import_legacy=True)
    if before["project_id"] != store.snapshot()["project_id"] or before.get("outside_changes"):
        raise ProjectConflict("A private preparation requires one exact reconciled project generation.")
    with TemporaryDirectory(prefix="sciplot-studio-candidate-") as temporary:
        parent = Path(temporary).resolve(strict=True)
        parent.chmod(0o700)
        root, resources = parent / "project", parent / "resources"
        root.mkdir(mode=0o700)
        resources.mkdir(mode=0o700)
        for name, entry in before["files"].items():
            if name.startswith("@"):
                continue
            target = root / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(store.read_bytes(name, generation=before["generation"]))
            target.chmod(entry["mode"])
        candidate = StudioPreparationCandidate(store, before, root, resources)
        token = _ACTIVE.set(candidate)
        try:
            with project_candidate_runtime(store, root, generation=before["generation"], resources_root=resources), private_project_manifest_scope(root):
                yield candidate
        finally:
            _ACTIVE.reset(token)
