"""Host-created private per-command project locator binding for native workers."""
from collections.abc import Iterator
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import stat
import tempfile
from typing import Any

from sciplot_core.foundation.json_hashing import canonical_json_sha256
from sciplot_core.project_commands import SourceTreeRead
from sciplot_core.foundation.source_locations import selected_source_resolver, source_location_scope
from .errors import ProjectConflict, ProjectStoreError
from .io import digest
from .incoming_sources import expectation_payload, expectation_trees, source_expectation_scope, without_source_expectations
from .candidate_resources import validate_resources_binding
from .native_artifacts import artifact_payload, bound_native_artifacts, native_artifact_binding
from .repository import FileProjectStore
from .resources import ResourceRoot
from .runtime import ProjectSourceResolver
from sciplot_core.data_mapping.execution_inputs import (
    _READ_SET, _read, mapping_input_reads,
)


@contextmanager
def native_runtime_binding(argv: list[str]) -> Iterator[dict[str, str] | None]:
    """Only selected trusted host state creates a locator; no wire/root discovery."""
    selected = selected_source_resolver()
    if selected is None:
        native_artifact_binding(argv, None)
        yield None
        return
    if not isinstance(selected, ProjectSourceResolver):
        raise ProjectStoreError("This scientific locator has no trusted native-worker binding.")
    project = selected.binding()
    mapping = native_mapping_binding()
    if mapping is not None:
        project["mapping_inputs"] = mapping
    artifacts = native_artifact_binding(argv, selected)
    if artifacts is not None:
        project["native_artifacts"] = artifacts
    value = {"project": project, "argv_sha256": digest(argv), "parent_pid": os.getpid()}
    data = json.dumps(value, sort_keys=True, allow_nan=False).encode()
    with tempfile.TemporaryDirectory(prefix="sciplot-project-runtime-") as temporary:
        root = Path(temporary).resolve(strict=True)
        root.chmod(0o700)
        path = root / "binding.json"
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o400)
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
        yield {"path": str(path), "sha256": hashlib.sha256(data).hexdigest()}


def validate_binding_reference(value: Any) -> None:
    if (not isinstance(value, dict) or set(value) != {"path", "sha256"}
            or not isinstance(value["path"], str) or not Path(value["path"]).is_absolute()
            or len(value["path"]) > 8192 or not isinstance(value["sha256"], str)
            or len(value["sha256"]) != 64 or any(c not in "0123456789abcdef" for c in value["sha256"])):
        raise ProjectStoreError("Invalid closed native project locator reference.")


def _read_binding(reference: dict[str, str], argv: list[str]) -> dict[str, Any]:
    validate_binding_reference(reference)
    path = Path(reference["path"])
    parent = path.parent.stat()
    if (path.parent.resolve() != path.parent or parent.st_uid != os.geteuid()
            or not stat.S_ISDIR(parent.st_mode) or parent.st_mode & 0o077):
        raise ProjectStoreError("A native locator requires a private host-owned directory.")
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, "rb") as stream:
        info = os.fstat(stream.fileno())
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid() or info.st_mode & 0o077
                or info.st_size > 65536):
            raise ProjectStoreError("A native locator requires a bounded private host-owned file.")
        data = stream.read(65537)
    if hashlib.sha256(data).hexdigest() != reference["sha256"]:
        raise ProjectConflict("Native project locator bytes changed after host binding.")
    value = json.loads(data)
    if (not isinstance(value, dict) or set(value) != {"project", "argv_sha256", "parent_pid"}
            or value["argv_sha256"] != digest(argv) or value["parent_pid"] != os.getppid()):
        raise ProjectConflict("The native project locator belongs to a different command or host process.")
    project = value["project"]
    if not isinstance(project, dict):
        raise ProjectStoreError("Unsupported closed native project locator.")
    fields = {"kind", "version", "root", "project_id", "generation", "generation_sha256", "locations"}
    if "source_expectations" in project:
        fields.add("source_expectations")
        expectation_payload(project["source_expectations"])
    if "native_artifacts" in project:
        fields.add("native_artifacts")
        artifact_payload(project["native_artifacts"])
    if "mapping_inputs" in project:
        fields.add("mapping_inputs")
        mapping_binding_payload(project["mapping_inputs"])
    if project.get("kind") == "sciplot_project_candidate_runtime":
        fields.add("candidate")
        candidate = project.get("candidate")
        candidate_fields = {"root", "device", "inode"}
        if isinstance(candidate, dict) and "resources" in candidate:
            candidate_fields.add("resources")
            validate_resources_binding(candidate["resources"])
        if (not isinstance(candidate, dict) or set(candidate) != candidate_fields
                or not isinstance(candidate["root"], str) or not Path(candidate["root"]).is_absolute()
                or any(type(candidate[key]) is not int or candidate[key] < 0 for key in ("device", "inode"))):
            raise ProjectStoreError("Invalid closed private candidate locator.")
    elif project.get("kind") != "sciplot_project_runtime":
        raise ProjectStoreError("Unsupported closed native project locator.")
    if set(project) != fields or project["version"] != 1 or not isinstance(project["locations"], dict):
        raise ProjectStoreError("Unsupported closed native project locator.")
    return project


@contextmanager
def worker_project_runtime(reference: dict[str, str] | None, argv: list[str]) -> Iterator[None]:
    with without_mapping_inputs(), without_source_expectations(), bound_native_artifacts(None, argv, None):
        with _worker_project_runtime(reference, argv):
            yield


@contextmanager
def _worker_project_runtime(reference: dict[str, str] | None, argv: list[str]) -> Iterator[None]:
    if reference is None:
        # Even pooled requests without a project cannot inherit the previous one.
        with source_location_scope(None):
            yield
        return
    value = _read_binding(reference, argv)
    locations = {}
    for key, item in value["locations"].items():
        if (not isinstance(item, dict) or set(item) != {"path", "members"}
                or not isinstance(item["path"], str) or not Path(item["path"]).is_absolute()
                or item["members"] is not None and (not isinstance(item["members"], list)
                    or not all(isinstance(name, str) for name in item["members"]))):
            raise ProjectStoreError("Invalid trusted native resource-root capability.")
        locations[key] = ResourceRoot(Path(item["path"]), tuple(item["members"]) if item["members"] is not None else None)
    if not isinstance(value["root"], str) or not Path(value["root"]).is_absolute():
        raise ProjectStoreError("A native project locator needs its explicit physical root.")
    store = FileProjectStore(Path(value["root"]), locations=locations)
    resolver: ProjectSourceResolver
    if value["kind"] == "sciplot_project_candidate_runtime":
        from .candidate_runtime import ProjectCandidateResolver

        candidate = value["candidate"]
        resources = candidate.get("resources")
        resolver = ProjectCandidateResolver(store, Path(candidate["root"]), value["generation"],
            bound_identity={key: candidate[key] for key in ("device", "inode")},
            resources_root=Path(resources["root"]) if resources is not None else None,
            bound_resources=resources)
    else:
        resolver = ProjectSourceResolver(store, value["generation"])
    if (resolver.snapshot["project_id"] != value["project_id"]
            or digest(resolver.snapshot) != value["generation_sha256"]):
        raise ProjectConflict("The native locator differs from the selected project generation.")
    with bound_native_artifacts(value.get("native_artifacts"), argv, resolver):
        if "source_expectations" in value:
            mode, sources = expectation_payload(value["source_expectations"])
            trees = expectation_trees(value["source_expectations"])
            with source_expectation_scope(resolver.snapshot, mode, sources, trees=trees, store=store), source_location_scope(resolver):
                with bound_mapping_inputs(value.get("mapping_inputs")):
                    yield
        else:
            with source_location_scope(resolver):
                with bound_mapping_inputs(value.get("mapping_inputs")):
                    yield


def mapping_binding_payload(value: Any) -> dict[str, Any]:
    """Validate a closed byte witness, never a new filesystem capability."""
    if (not isinstance(value, dict) or set(value) != {"execution", "files", "trees"}
            or not isinstance(value["execution"], str) or not Path(value["execution"]).is_absolute()
            or not isinstance(value["files"], list) or not value["files"] or not isinstance(value["trees"], list)):
        raise ProjectConflict("Invalid closed mapping input binding.")
    paths = set()
    for item in value["files"]:
        if (not isinstance(item, dict) or set(item) != {"path", "sha256", "mode"}
                or not isinstance(item["path"], str) or not Path(item["path"]).is_absolute()
                or any(part in {".", ".."} for part in Path(item["path"]).parts)
                or item["path"] in paths or not isinstance(item["sha256"], str)
                or len(item["sha256"]) != 64 or any(c not in "0123456789abcdef" for c in item["sha256"])
                or type(item["mode"]) is not int or not 0 <= item["mode"] <= 0o777):
            raise ProjectConflict("Invalid exact mapping input file witness.")
        paths.add(item["path"])
    if value["execution"] not in paths:
        raise ProjectConflict("The mapping binding lacks its exact execution bytes.")
    for tree in value["trees"]:
        if not isinstance(tree, dict) or set(tree) != {"locator", "tree_sha256"}:
            raise ProjectConflict("Invalid mapping directory witness.")
        guard = SourceTreeRead(**tree)
        direct = [item for item in value["files"] if item["path"] == guard.locator]
        if direct:
            content = {"kind": "file", "content_sha256": direct[0]["sha256"]}
        elif Path(guard.locator) == Path(value["execution"]).parent / "data":
            members = [{"path": str(Path(item["path"]).relative_to(guard.locator)), "content_sha256": item["sha256"]}
                       for item in value["files"] if Path(item["path"]).is_relative_to(guard.locator)]
            if not members:
                raise ProjectConflict("A mapping tree must bind its complete captured outputs.")
            content = {"kind": "directory", "files": sorted(members, key=lambda item: item["path"])}
        else:
            raise ProjectConflict("A mapping tree cannot expand the captured execution closure.")
        if canonical_json_sha256(content, allow_nan=False) != guard.tree_sha256:
            raise ProjectConflict("A mapping tree composite differs from its captured file byte versions.")
    return value


def native_mapping_binding() -> dict[str, Any] | None:
    active = _READ_SET.get()
    if active is None:
        return None
    if not active.sealed:
        raise ProjectConflict("Native preparation requires its completely verified mapping read set.")
    active.require_current()
    return mapping_binding_payload({"execution": active.execution, "files": [
        {"path": item.literal, "sha256": item.sha256, "mode": item.actual_mode}
        for _path, item in sorted(active.files.items())],
        "trees": [item.to_payload() for _path, item in sorted(active.trees.items())]})


@contextmanager
def without_mapping_inputs() -> Iterator[None]:
    token = _READ_SET.set(None)
    try:
        yield
    finally:
        _READ_SET.reset(token)


@contextmanager
def bound_mapping_inputs(value: dict[str, Any] | None) -> Iterator[None]:
    if value is None:
        yield
        return
    value = mapping_binding_payload(value)
    with mapping_input_reads(value["execution"]) as active:
        assert active is not None
        for item in value["files"]:
            observed, _path = _read(Path(item["path"]), item["sha256"])
            if observed.actual_mode != item["mode"]:
                raise ProjectConflict("The worker mapping input changed its exact physical permissions.")
        active.trees = {item["locator"]: SourceTreeRead(**item) for item in value["trees"]}
        active.seal()
        yield
