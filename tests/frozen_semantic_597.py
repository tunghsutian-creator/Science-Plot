"""Execute a finite, byte-pinned 597 writer against the current namespace fence.

Only seven historical owners and the original FakeBackend class slice are loaded from
the fixture. Other project imports remain in this tracked checkout and their
actually executed source hashes must match the original source manifest.
"""
import ast
import hashlib
import importlib.abc
import importlib.machinery
import importlib.util
import json
from pathlib import Path
import sys
from copy import deepcopy
from types import ModuleType


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests/fixtures/frozen_semantic_597"


def read_manifest():
    manifest = json.loads((FIXTURE / "manifest.json").read_bytes())
    for section in ("owners", "slices"):
        for record in manifest[section].values():
            assert hashlib.sha256((FIXTURE / record["fixture"]).read_bytes()).hexdigest() == record["sha256"]
    return manifest


def _function_bytes(path, qualified):
    lines = path.read_text().splitlines(keepends=True)

    def find(nodes, prefix=""):
        for node in nodes:
            if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                name = prefix + node.name
                if name == qualified:
                    start = min([node.lineno] + [value.lineno for value in node.decorator_list])
                    return "".join(lines[start - 1:node.end_lineno]).encode()
                result = find(node.body, name + ("." if isinstance(node, ast.ClassDef) else ".<locals>."))
                if result is not None:
                    return result
        return None

    value = find(ast.parse("".join(lines)).body)
    assert value is not None, (path, qualified)
    return value


def validate_operational_helpers(manifest, calls):
    for filename, qualified, _line in calls:
        path = Path(filename)
        if path.is_relative_to(FIXTURE):
            continue
        relative = path.relative_to(ROOT).as_posix()
        expected = manifest["operational_helpers"][relative]
        if "sha256" in expected:
            assert hashlib.sha256(path.read_bytes()).hexdigest() == expected["sha256"], relative
        else:
            original = expected["functions"][qualified]
            assert hashlib.sha256(_function_bytes(path, qualified)).hexdigest() == original["sha256"], (relative, qualified)


class FrozenOwners(importlib.abc.MetaPathFinder):
    """Explicit names only; no replacement of the tracked top-level package."""
    def __init__(self, manifest):
        self.members = {name: FIXTURE / record["fixture"] for name, record in manifest["owners"].items()}
        assert not set(self.members).intersection(sys.modules)

    def find_spec(self, fullname, path=None, target=None):
        member = self.members.get(fullname)
        if member is None:
            return None
        loader = importlib.machinery.SourceFileLoader(fullname, str(member))
        return importlib.util.spec_from_file_location(fullname, member, loader=loader)


def main():
    manifest = read_manifest()
    finder = FrozenOwners(manifest)
    sys.meta_path.insert(0, finder)
    executed = set()
    functional_calls = set()
    profiling = False

    def profile(frame, event, argument):
        if event != "call":
            return
        filename = Path(frame.f_code.co_filename)
        if filename.is_relative_to(ROOT / "src/sciplot_core") or filename.is_relative_to(FIXTURE):
            executed.add(filename)
            if frame.f_code.co_flags & 2:
                functional_calls.add((str(filename), frame.f_code.co_qualname, frame.f_code.co_firstlineno))

    try:
        import sciplot_core
        from sciplot_core.foundation.file_hashing import file_sha256
        from sciplot_core.plot_document import seal_document
        from sciplot_core.plot_engine.storage import digest, read, write
        from sciplot_core.project_lifecycle.application import ProjectApplication
        from sciplot_core.project_lifecycle.context import repository_scope
        from sciplot_core.project_lifecycle.repository import FileProjectRepository, transaction_path
        from sciplot_core.project_lifecycle.target_adapter import FilesystemProjectTargets
        from sciplot_core.studio_core.project_session import external_project_session

        assert Path(sciplot_core.__file__).resolve().is_relative_to(ROOT / "src/sciplot_core")
        backend_file = FIXTURE / manifest["slices"]["fake_backend"]["fixture"]
        original_backend = ModuleType("frozen597_backend")
        original_backend.__dict__.update(Path=Path, deepcopy=deepcopy, file_sha256=file_sha256,
                                        seal_document=seal_document, digest=digest, read=read, write=write)
        exec(compile(backend_file.read_bytes(), str(backend_file), "exec"), original_backend.__dict__)
        operation, case_name, phase = sys.argv[1:]
        case = Path(case_name).resolve()
        native, root = case / "native", case / "semantic"
        # Imports keep the real current checkout; this records the actual
        # operational dependency closure, not dormant definitions at import.
        assert sys.getprofile() is None, "The historical counter must preserve any existing observer."
        sys.setprofile(profile)
        profiling = True
        backend = original_backend.FakeBackend(native)
        repository = FileProjectRepository(lease=external_project_session)
        application = ProjectApplication(backend, repository, targets=FilesystemProjectTargets(repository))
        request_path = case / "request.json"
        result = {}
        if operation == "prepare":
            document, binding = backend.initial()
            repository.prepare_namespace(root)
            repository.commit(root, document, binding, "import")
            request = {"plot_id": document["plot_id"], "base_revision": 0,
                "idempotency_key": "pending-" + phase, "intent_class": "presentation",
                "changes": [{"op": "set", "target": ["title:main"], "property": "title.text", "value": "Requested title"}]}
            result["result"] = application.patch(root, request)
            assert result["result"]["status"] == "needs_review"
            with repository_scope(repository):
                transaction = repository.read(transaction_path(root, request["idempotency_key"]))
                transaction.update(phase=phase, accepted=True)
                repository.persist(root, transaction)
            request_path.write_text(json.dumps(request))
        else:
            assert operation == "resume"
            try:
                result["result"] = application.patch(root, json.loads(request_path.read_bytes()))
            except Exception as exc:
                result["error"] = {"type": type(exc).__name__, "message": str(exc)}
        result["backend_calls"] = backend.calls
        result["loaded_owners"] = {name: str(Path(sys.modules[name].__file__).resolve())
            for name in manifest["owners"]}
    finally:
        if profiling:
            sys.setprofile(None)
    validate_operational_helpers(manifest, functional_calls)
    result["executed"] = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in sorted(executed)}
    result["functional_calls"] = sorted(functional_calls)
    print(json.dumps(result))


if __name__ == "__main__":
    main()
