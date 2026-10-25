"""Explicit NativeSuite composition over the shared trusted locator runtime."""
from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps
import json
from pathlib import Path
from typing import Any, ParamSpec, TypeVar

from sciplot_core.project_store import FileProjectStore

_STORE: ContextVar[FileProjectStore | None] = ContextVar('native_suite_store', default=None)
P = ParamSpec('P')
T = TypeVar('T')


def current_store() -> FileProjectStore | None:
    return _STORE.get()


def delivery_path(manifest: dict[str, Any]) -> Path:
    store = current_store()
    return store.locations['delivery'] if store is not None else Path(manifest['delivery'])


def _suite_value(path: Path) -> dict[str, Any]:
    from sciplot_core.studio_core.source_update_commit import reject_symlink_path
    reject_symlink_path(path)
    value = json.loads(path.read_bytes())
    if not isinstance(value, dict) or value.get("kind") != "sciplot_rheology_tts_suite":
        raise ValueError("The selected member has no bound NativeSuite manifest.")
    return value


def _bound_selection(target: Path, workspace: Path, delivery: Path,
                     value: dict[str, Any], *, role: str) -> None:
    """Authorize the selected role before a manifest pointer can cause repair."""
    hidden, visible = workspace / "suite.json", delivery / "data/delivery_manifest.json"
    origin_workspace, origin_delivery = Path(value["workspace"]), Path(value["delivery"])
    if not origin_workspace.is_absolute() or not origin_delivery.is_absolute():
        raise ValueError("NativeSuite origins must be exact absolute locations.")
    allowed = {workspace, delivery, hidden, visible}
    if role in {"prepared_request", "analysis_request"}:
        if target != workspace / "request.json":
            raise ValueError("A prepared continuation requires its exact registered request member.")
        request = json.loads(target.read_bytes())
        if not isinstance(request, dict) or request.get("out", str(origin_delivery)) != str(origin_delivery):
            raise ValueError("The selected request is not bound to this suite's delivery.")
        if role == "prepared_request" and request.get("prepared_plan") != value.get("prepared_input", {}).get("path"):
            raise ValueError("The selected prepared request is not bound to this suite.")
        if role == "analysis_request" and request.get("frequency_source") not in {item["path"] for item in value["sources"]}:
            raise ValueError("The selected analysis request is not bound to this suite's original source.")
    elif role == "native":
        if target not in allowed:
            documents = value.get("documents")
            if (not isinstance(documents, list) or target.suffix.lower() != ".vsz"
                    or any(not isinstance(item, dict) for item in documents)):
                raise ValueError("The target is not an exact NativeSuite member.")
            matches = [item for item in documents if isinstance(item.get("id"), str)
                       and Path(item.get("path", "")) == origin_delivery / "editable" / (item["id"] + ".vsz")
                       and target == delivery / "editable" / (item["id"] + ".vsz")]
            if len(matches) != 1:
                raise ValueError("The target is not an exact selected NativeSuite figure.")
    else:
        raise ValueError("Unknown host NativeSuite selection role.")
    # Existing update generations retain root links even while one derived
    # manifest has advanced. Read both links before any store/recovery action;
    # an outside fake manifest cannot grant repair of another project.
    for manifest in (hidden, visible):
        linked = _suite_value(manifest)
        if (linked.get("workspace"), linked.get("delivery")) != (str(origin_workspace), str(origin_delivery)):
            raise ValueError("NativeSuite root links disagree; no project repair is authorized.")


def _pending_request_store(workspace: Path, target: Path, *, role: str) -> FileProjectStore:
    """A pending suite has no manifest; only its registered original request binds it."""
    probe = FileProjectStore(workspace)
    adapter = "prepared_native_suite" if role == "prepared_request" else "analysis_native_suite"
    candidates = []
    for record in probe.commands():
        value = record.get("metadata", {}).get("request", {})
        source = value.get("request_file", {})
        if (record.get("metadata", {}).get("kind") != "native_create"
                or value.get("adapter") != adapter or "continuation_of" in value or not source):
            continue
        if probe.resolve_path(source["path"], expected_sha256=source["sha256"]) == target:
            if json.loads(target.read_bytes()) != value["request"]:
                raise ValueError("The selected pending request differs from its frozen command.")
            candidates.append(value)
    if len(candidates) != 1:
        raise ValueError("Only the exact registered original request can continue this pending suite.")
    if (workspace / ".sciplot_store/local_locations.json").is_file():
        return probe
    delivery = Path(candidates[0]["binding"]["delivery"])
    return FileProjectStore(workspace, locations={"delivery": delivery})


def _store_suite_evidence(workspace: Path) -> str | None:
    """A generic project store is not evidence of pending NativeSuite creation."""
    from sciplot_core.project_commands import ProjectCommand

    probe = FileProjectStore(workspace)
    with probe._locked(allow_pending=True) as (_io, current):
        saved = "suite.json" in current["files"] or "@delivery/data/delivery_manifest.json" in current["files"]
        project_id = current["project_id"]
    admitted = False
    for record in probe.commands():
        metadata = record.get("metadata")
        if (record.get("kind") != "sciplot_project_command" or record.get("version") != 1
                or record.get("project_id") != project_id or not isinstance(metadata, dict)):
            raise ValueError("A damaged project command cannot establish or discard NativeSuite authority.")
        request = metadata.get("request", {})
        if not isinstance(request, dict):
            raise ValueError("A project command has a damaged frozen request.")
        adapter = request.get("adapter")
        if adapter is not None and not isinstance(adapter, str):
            raise ValueError("A project command has a damaged adapter identity.")
        fixed = adapter in {"prepared_native_suite", "analysis_native_suite"}
        if fixed or record.get("native_workspace") is not None:
            # commands() already verifies the fixed native_workspace marker
            # and inode. Bind its owner metadata too; never infer from a path.
            command = ProjectCommand.from_payload(metadata)
            if (metadata["kind"] != "native_create" or command.project_id != project_id
                    or command.key != record["command_id"] or command.command_digest != record["command_digest"]):
                raise ValueError("NativeSuite creation evidence differs from its admitted command.")
            admitted = True
    return "saved" if saved else "pending" if admitted else None


def read_bound_store(target: Path, *, role: str = "native") -> FileProjectStore | None:
    """Resolve exact target membership without repairing or entering source IO."""
    from sciplot_core.studio_core.source_update_commit import reject_symlink_path

    reject_symlink_path(target)
    target = target.expanduser().resolve()
    roots = [path for path in (target, *target.parents) if (path / '.sciplot_store/head.json').is_file()]
    workspace = roots[0] if roots else None
    if workspace is not None and not (workspace / "suite.json").is_file():
        evidence = _store_suite_evidence(workspace)
        if evidence is None:
            return None
        if evidence == "saved":
            raise ValueError("A registered NativeSuite manifest is missing; preserve its saved authority for explicit recovery.")
        if role not in {"prepared_request", "analysis_request"}:
            raise ValueError("Pending native creation has no selected saved figure authority.")
        return _pending_request_store(workspace, target, role=role)
    value = _suite_value(workspace / "suite.json") if workspace is not None else None
    if workspace is None:
        candidates = [target / 'suite.json', target / 'data/delivery_manifest.json'] if target.is_dir() else [target]
        if target.suffix.lower() == '.vsz':
            candidates = [target.parent.parent / 'data/delivery_manifest.json']
        for path in candidates:
            if path.is_file() and path.suffix == '.json':
                candidate = json.loads(path.read_bytes())
                if isinstance(candidate, dict) and candidate.get('kind') == 'sciplot_rheology_tts_suite':
                    root = Path(candidate['workspace'])
                    # Exact role membership is checked before dereferencing an
                    # untrusted workspace pointer into a recoverable store.
                    delivery = Path(candidate['delivery'])
                    _bound_selection(target, root, delivery, candidate, role=role)
                    if (root / '.sciplot_store/head.json').is_file():
                        workspace, value = root, candidate
                    break
    if workspace is None:
        return None  # Explicit legacy host context, before first store import.
    assert value is not None
    cold = (workspace / '.sciplot_store/local_locations.json').is_file()
    delivery = workspace / '.sciplot_resources/delivery' if cold else Path(value['delivery'])
    _bound_selection(target, workspace, delivery, value, role=role)
    reject_symlink_path(workspace)
    reject_symlink_path(delivery)
    return FileProjectStore(workspace) if cold else FileProjectStore(workspace, locations={'delivery': delivery})


@contextmanager
def suite_runtime(target: Path, *, repair: bool = False, role: str = "native") -> Iterator[None]:
    from sciplot_core.project_store.runtime import project_runtime
    store = read_bound_store(target, role=role)
    if store is None:
        yield
        return
    store.recover() if repair else store.snapshot()
    token = _STORE.set(store)
    try:
        with project_runtime(store):
            yield
    finally:
        _STORE.reset(token)


def native_runtime(*, repair: bool = False, role: str = "native") -> Callable[[Callable[P, T]], Callable[P, T]]:
    def decorate(function: Callable[P, T]) -> Callable[P, T]:
        @wraps(function)
        def wrapped(*args: P.args, **kwargs: P.kwargs) -> T:
            first = args[0]
            if not isinstance(first, (str, Path)):
                raise TypeError('NativeSuite composition requires an explicit host path.')
            target = Path(first)
            with suite_runtime(target, repair=repair, role=role):
                return function(*args, **kwargs)
        return wrapped
    return decorate


def literal_resource(path: Path) -> str:
    """Serialize one explicitly admitted resource under its preserved host root.

    This also handles new declared spec writes. It is a locator projection, not
    permission to read/write: ProjectMutation still must match its typed command.
    """
    store = current_store()
    if store is None:
        return str(path)
    logical = store.logical_path(path)
    current = store.snapshot()
    if logical.startswith('@'):
        prefix, relative = logical.split('/', 1)
        return str(Path(current['locators'][prefix[1:]]) / relative)
    return str(Path(current['locators']['']) / logical)


def native_path(manifest: dict[str, Any], document: dict[str, Any]) -> Path:
    """Resolve only the closed saved-native authority, including audited drift."""
    expected = Path(manifest['delivery']) / 'editable' / (document['id'] + '.vsz')
    if Path(document['path']) != expected:
        raise ValueError('Native figure is outside its exact bound editable member.')
    identifier = str(document['id'])
    actual = delivery_path(manifest) / 'editable' / (identifier + '.vsz')
    store = current_store()
    if store is not None and store.logical_path(actual) not in store.snapshot()['files']:
        raise ValueError('Native authority is absent from the registered generation.')
    return actual


def literal_directory(path: Path) -> str:
    store = current_store()
    if store is None:
        return str(path)
    roots = {'': store.root, **store.locations}
    original = store.snapshot()['locators']
    for key, root in roots.items():
        if path == root:
            return str(original[key])
    return literal_resource(path)
