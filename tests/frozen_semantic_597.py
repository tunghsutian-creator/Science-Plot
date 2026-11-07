"""Execute a finite, byte-pinned 597 writer against the current namespace fence.

The seven writers, original operational modules and two import-ABI leaves use
the explicit 597 fixture. Finite shared functions keep their original source
and loaded code identity without replacing preloaded guard dependencies.
Unknown operational helpers still refuse. Current verification enforcement is
witnessed separately before and after the operation, never historical code.
"""
import ast
import __future__
import hashlib
import importlib.abc
import importlib.machinery
import importlib.util
import json
from pathlib import Path
import sys
from copy import deepcopy
from types import CodeType, ModuleType


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


def read_operational_closure(manifest):
    """Bind the finite execution shell to unchanged, original 597 evidence."""
    closure = json.loads((FIXTURE / "operational-closure-v2.json").read_bytes())
    assert (closure["kind"], closure["version"], closure["source_commit"]) == (
        "sciplot_frozen_operational_closure", 2, manifest["source_commit"])
    assert closure["original_manifest_sha256"] == hashlib.sha256((FIXTURE / "manifest.json").read_bytes()).hexdigest()
    records = closure["helpers"]
    assert {record["module_source_path"] for record in records.values()} == set(manifest["operational_helpers"])
    for name, record in records.items():
        assert record["module_source_path"] == "src/" + name.replace(".", "/") + ".py"
        original = manifest["operational_helpers"][record["module_source_path"]]
        declared = original.get("functions")
        authorities = list(declared.values()) if declared else [original]
        assert all(record["original_source_path"] == value["source_path"] for value in authorities)
        assert all(record["sha256"] == value.get("source_sha256", value.get("sha256")) for value in authorities)
        path = FIXTURE / record["fixture"]
        assert record["fixture"] == "operational/" + record["original_source_path"] + ".txt"
        assert not path.is_symlink()
        content = path.read_bytes()
        assert hashlib.sha256(content).hexdigest() == record["sha256"]
        assert hashlib.sha1(b"blob " + str(len(content)).encode() + b"\0" + content).hexdigest() == record["git_blob"]
        assert record["mode"] in {"frozen_original_module", "shared_original_file", "shared_original_functions"}
        if declared:
            assert record["mode"] == "shared_original_functions" and record["functions"] == declared
        if record["mode"] == "shared_original_functions":
            assert set(record["functions"]) == (set(declared) if declared else {"json_safe"})
            for function, expected in record["functions"].items():
                assert hashlib.sha256(_function_bytes(path, function)).hexdigest() == expected["sha256"]
    # These original application imports carry class/type ABI before profiling.
    # Their old blobs are separate from the unchanged 26 operational records.
    imports = closure["import_dependencies"]
    assert {name: record["git_blob"] for name, record in imports.items()} == {
        "sciplot_core.project_lifecycle.command_dispatch": "463a4516a16af9e1346d4857eb11c1ed5b191d43",
        "sciplot_core.plot_engine.backend": "a4c88e0e1e7400363e4ae20f5132f496a05e56ca"}
    for name, record in imports.items():
        assert record["mode"] == "frozen_original_import_abi"
        assert record["module_source_path"] == record["original_source_path"] == "src/" + name.replace(".", "/") + ".py"
        assert record["fixture"] == "operational/" + record["original_source_path"] + ".txt"
        content = (FIXTURE / record["fixture"]).read_bytes()
        assert hashlib.sha256(content).hexdigest() == record["sha256"]
        assert hashlib.sha1(b"blob " + str(len(content)).encode() + b"\0" + content).hexdigest() == record["git_blob"]
    return closure


def _code_identity(code):
    """Compare actual function bodies, excluding location and annotation timing."""
    return code.replace(co_filename="", co_firstlineno=1, co_linetable=b"",
        co_flags=code.co_flags & ~__future__.annotations.compiler_flag,
        co_consts=tuple(_code_identity(value) if isinstance(value, CodeType) else value for value in code.co_consts))


def _verify_shared_original_functions(closure):
    for name, record in {**closure["helpers"], **closure.get("import_dependencies", {})}.items():
        module = sys.modules.get(name)
        if module is None:
            continue  # An unimported definition is not an executed dependency.
        if record["mode"] in {"frozen_original_module", "frozen_original_import_abi"}:
            assert Path(module.__file__) == FIXTURE / record["fixture"], ("wrong frozen owner", name)
            continue
        path = ROOT / record["module_source_path"]
        assert Path(module.__file__) == path, ("foreign shared owner", name)
        if record["mode"] == "shared_original_file":
            assert hashlib.sha256(path.read_bytes()).hexdigest() == record["sha256"], name
            continue
        original = compile((FIXTURE / record["fixture"]).read_bytes(), str(path), "exec", dont_inherit=True)
        def codes(code):
            for value in code.co_consts:
                if isinstance(value, CodeType):
                    yield value
                    yield from codes(value)
        originals = {value.co_qualname: value for value in codes(original)}
        for qualified, expected in record["functions"].items():
            function = module
            for part in qualified.split("."):
                function = getattr(function, part)
            assert function.__module__ == name and function.__code__.co_filename == str(path), ("foreign shared function", name, qualified)
            assert hashlib.sha256(_function_bytes(path, qualified)).hexdigest() == expected["sha256"], (name, qualified)
            assert _code_identity(function.__code__) == _code_identity(originals[qualified]), ("changed loaded function", name, qualified)
        if name == "sciplot_core.foundation.json_values":
            from collections.abc import Mapping
            from dataclasses import asdict, is_dataclass

            for binding, expected in {"Mapping": Mapping, "asdict": asdict, "is_dataclass": is_dataclass, "Path": Path}.items():
                assert module.json_safe.__globals__[binding] is expected, ("changed shared dependency", binding)


def current_enforcement_sources():
    from sciplot_core.verification import private_process_boundaries, public_input_guard

    source = ROOT / "src/sciplot_core"
    verification = source / "verification"
    assert Path(private_process_boundaries.__file__).resolve() == verification / "private_process_boundaries.py"
    assert Path(public_input_guard.__file__).resolve() == verification / "public_input_guard.py"
    result = {}
    for name, digest in private_process_boundaries.source_hashes().items():
        if name == "repository:skill/scripts/sciplot":
            continue  # Shell startup is outside this Python-call counter.
        path = (verification / name).resolve()
        assert path.is_relative_to(source), ("foreign enforcement owner", name)
        result[str(path)] = digest
    # The shared observation source map does not include public enforcement.
    # Bind its actual loaded owner explicitly, rather than changing that registry.
    guard = Path(public_input_guard.__file__).resolve()
    result[str(guard)] = hashlib.sha256(guard.read_bytes()).hexdigest()
    return result


def validate_operational_helpers(manifest, calls, enforcement_sources=None, *, closure=None):
    helpers = {record["module_source_path"]: record for record in closure["helpers"].values()} if closure else {}
    fixture_paths = {str(FIXTURE / record["fixture"]) for record in [
        *manifest.get("owners", {}).values(), *manifest.get("slices", {}).values(),
        *(closure["helpers"].values() if closure else []),
        *(closure.get("import_dependencies", {}).values() if closure else [])]}
    import_only = {str(FIXTURE / record["fixture"]) for record in (closure or {}).get("import_dependencies", {}).values()}
    if closure:
        _verify_shared_original_functions(closure)
    for filename, qualified, _line in calls:
        path = Path(filename)
        if path.is_relative_to(FIXTURE):
            if closure:
                assert str(path) in fixture_paths, ("unknown frozen helper", filename, qualified)
                assert str(path) not in import_only, ("import-only ABI executed", filename, qualified)
            continue
        relative = path.relative_to(ROOT).as_posix()
        helper = helpers.get(relative)
        if helper is not None and helper["mode"] == "shared_original_functions":
            assert qualified.split(".<locals>.", 1)[0] in helper["functions"], ("unknown historical function", relative, qualified)
            continue
        expected = manifest["operational_helpers"].get(relative)
        if expected is None:
            assert enforcement_sources is not None and str(path) in enforcement_sources, ("unknown helper", relative, qualified)
            assert hashlib.sha256(path.read_bytes()).hexdigest() == enforcement_sources[str(path)], ("current enforcement changed", relative)
            continue
        if "sha256" in expected:
            assert hashlib.sha256(path.read_bytes()).hexdigest() == expected["sha256"], relative
        else:
            original = expected["functions"][qualified]
            assert hashlib.sha256(_function_bytes(path, qualified)).hexdigest() == original["sha256"], (relative, qualified)
    if enforcement_sources is not None:
        assert current_enforcement_sources() == enforcement_sources, "Current enforcement source identity changed during the historical operation."


class FrozenOwners(importlib.abc.MetaPathFinder):
    """Explicit names only; no replacement of the tracked top-level package."""
    def __init__(self, manifest, closure=None):
        self.members = {name: FIXTURE / record["fixture"] for name, record in manifest["owners"].items()}
        self.members.update({name: FIXTURE / record["fixture"] for name, record in (closure or {}).get("helpers", {}).items()
                             if record["mode"] == "frozen_original_module"})
        self.members.update({name: FIXTURE / record["fixture"] for name, record in (closure or {}).get("import_dependencies", {}).items()})
        assert not set(self.members).intersection(sys.modules)

    def find_spec(self, fullname, path=None, target=None):
        member = self.members.get(fullname)
        if member is None:
            return None
        loader = importlib.machinery.SourceFileLoader(fullname, str(member))
        return importlib.util.spec_from_file_location(fullname, member, loader=loader)


def source_call_profile(executed, functional_calls):
    """Classify immutable code filenames once within this one counter invocation.

    Path membership here is purely lexical: it never resolves a file, reads
    source bytes or authorizes execution. Every matching call is still recorded;
    the separate final source-byte validation remains fresh.
    """
    roots = (ROOT / "src/sciplot_core", FIXTURE)
    classified = {}

    def profile(frame, event, argument):
        if event != "call":
            return
        name = frame.f_code.co_filename
        if name not in classified:
            path = Path(name)
            classified[name] = path if any(path.is_relative_to(root) for root in roots) else None
        filename = classified[name]
        if filename is not None:
            executed.add(filename)
            if frame.f_code.co_flags & 2:
                functional_calls.add((str(filename), frame.f_code.co_qualname, frame.f_code.co_firstlineno))

    return profile


def main():
    manifest = read_manifest()
    closure = read_operational_closure(manifest)
    finder = FrozenOwners(manifest, closure)
    sys.meta_path.insert(0, finder)
    executed = set()
    functional_calls = set()
    profiling = False

    profile = source_call_profile(executed, functional_calls)

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
        _verify_shared_original_functions(closure)
        enforcement_sources = current_enforcement_sources()
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
    validate_operational_helpers(manifest, functional_calls, enforcement_sources, closure=closure)
    assert read_manifest() == manifest
    assert read_operational_closure(manifest) == closure
    result["historical_operational_closure"] = {
        "version": closure["version"], "source_commit": closure["source_commit"],
        "original_manifest_sha256": closure["original_manifest_sha256"],
        "loaded": {name: {"path": str(Path(sys.modules[name].__file__)), "mode": record["mode"]}
                   for name, record in {**closure["helpers"], **closure["import_dependencies"]}.items() if name in sys.modules}}
    result["current_enforcement"] = {"claim": "Current source identity only; not frozen597 scientific certification.",
                                     "sources": enforcement_sources}
    result["executed"] = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in sorted(executed)}
    result["functional_calls"] = sorted(functional_calls)
    print(json.dumps(result))


if __name__ == "__main__":
    if sys.argv[1:2] == ["resume"]:
        # This child belongs only to the historical control. Keep its parent's
        # 30-second deadline; retain one stack if resume is still working at25s.
        # Startup before this script (including sitecustomize) is not covered.
        import faulthandler

        faulthandler.dump_traceback_later(25, repeat=False, file=sys.stderr)
        try:
            main()
        finally:
            faulthandler.cancel_dump_traceback_later()
    else:
        main()
