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


@contextmanager
def suite_runtime(target: Path, *, repair: bool = False) -> Iterator[None]:
    from sciplot_core.project_store.runtime import project_runtime
    from sciplot_core.studio_core.source_update_commit import reject_symlink_path

    reject_symlink_path(target)
    target = target.expanduser().resolve()
    roots = [path for path in (target, *target.parents) if (path / '.sciplot_store/head.json').is_file()]
    workspace = roots[0] if roots else None
    if workspace is None:
        candidates = [target / 'suite.json', target / 'data/delivery_manifest.json'] if target.is_dir() else [target]
        if target.suffix.lower() == '.vsz':
            candidates = [target.parent.parent / 'data/delivery_manifest.json']
        for path in candidates:
            if path.is_file() and path.suffix == '.json':
                value = json.loads(path.read_bytes())
                if isinstance(value, dict) and value.get('kind') == 'sciplot_rheology_tts_suite':
                    root = Path(value['workspace'])
                    if (root / '.sciplot_store/head.json').is_file():
                        workspace = root
                    break
    if workspace is None:
        yield  # Explicit legacy host context, before its first store import.
        return
    if (workspace / '.sciplot_store/local_locations.json').is_file():
        store = FileProjectStore(workspace)
    else:
        value = json.loads((workspace / 'suite.json').read_bytes())
        store = FileProjectStore(workspace, locations={'delivery': Path(value['delivery'])})
    store.recover() if repair else store.snapshot()
    token = _STORE.set(store)
    try:
        with project_runtime(store):
            yield
    finally:
        _STORE.reset(token)


def native_runtime(*, repair: bool = False) -> Callable[[Callable[P, T]], Callable[P, T]]:
    def decorate(function: Callable[P, T]) -> Callable[P, T]:
        @wraps(function)
        def wrapped(*args: P.args, **kwargs: P.kwargs) -> T:
            first = args[0]
            if not isinstance(first, (str, Path)):
                raise TypeError('NativeSuite composition requires an explicit host path.')
            target = Path(first)
            with suite_runtime(target, repair=repair):
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
