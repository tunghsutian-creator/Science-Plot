"""Selected host locators change physical IO, never scientific source identity."""
from contextlib import nullcontext
from copy import deepcopy
from pathlib import Path

import pytest

from managed_plot_helpers import request_for_source
from sciplot_core.foundation.source_locations import source_location_scope
from sciplot_core.plot_engine.current import changed_inputs
from sciplot_core.plot_engine.managed_backend import ManagedBackend
from sciplot_core.plot_engine.managed_resolution import resolve_science, resolved_metadata
from sciplot_core.plot_engine.managed_sources import load_sources
from sciplot_core.plot_engine.managed_state import input_files, make_binding, require_inputs
from sciplot_core.plot_ir import create_managed_document
from sciplot_core.project_lifecycle.capabilities import COMPATIBILITY_CAPABILITIES
from sciplot_core.project_lifecycle.context import repository_scope
from sciplot_core.project_lifecycle.repository import FileProjectRepository


def relocated_document(tmp_path):
    wire = request_for_source(tmp_path)
    source = wire["data_binding"]["data_sources"][0]
    actual = Path(source["path"])
    source["path"] = str(tmp_path / "unavailable-original" / "A.csv")
    document = create_managed_document(wire["template_definition"], wire["data_binding"], plot_id="located-history")
    return resolved_metadata(document, rule_id=wire["rule_id"], executors={}), actual


class SelectedSource:
    def __init__(self, source, actual):
        self.source, self.actual = source, actual
        self.calls = []

    def resolve_path(self, original, *, expected_sha256=None, source_id=None):
        expected = (self.source["path"], self.source["sha256"], self.source["source_id"])
        reentry = (str(original) == str(self.actual) and expected_sha256 in {None, self.source["sha256"]}
                   and source_id is None)
        verified = expected in self.calls
        self.calls.append((str(original), expected_sha256, source_id))
        assert self.calls[-1] == expected or reentry and verified  # Exact same-reader IO; code paths cannot become source mappings.
        return self.actual

    def literal_path(self, actual):
        assert actual == self.actual
        return self.source["path"]

    def file_paths(self, actual, *, expected_sha256=None, source_id=None):
        literal = self.literal_path(actual)
        return literal, self.resolve_path(actual, expected_sha256=expected_sha256, source_id=source_id)


@pytest.mark.parametrize("projection", ["same-physical", "equal-bytes-distinct-physical"])
def test_source_group_checks_each_identity_then_compares_physical_io_without_rewriting_locator(tmp_path, projection):
    from sciplot_core.foundation.file_hashing import file_sha256
    from sciplot_core.foundation.source_locations import literal_source_path
    from sciplot_core.plot_engine.errors import EngineError
    from sciplot_core.plot_engine.managed_state import source_input_path

    document, actual = relocated_document(tmp_path)
    sources = document["scientific"]["data_sources"]
    original = deepcopy(sources[0])
    for index in range(2):
        alias = tmp_path / f"scientific-alias-{index}.csv"
        alias.symlink_to(actual)
        source = {**deepcopy(original), "source_id": f"scientific:{index}", "path": str(alias)}
        if index == 0:
            sources[0] = source
        else:
            sources.append(source)
    separate = tmp_path / "different-original.csv"
    separate.write_bytes(actual.read_bytes())
    assert file_sha256(separate) == file_sha256(actual) and separate.resolve() != actual.resolve()
    views = [tmp_path / f"approved-view-{index}.csv" for index in range(2)]
    views[0].symlink_to(actual)
    views[1].symlink_to(actual if projection == "same-physical" else separate)
    expected = [(source["path"], source["sha256"], source["source_id"]) for source in sources]
    calls = []

    class StrictAliases:
        def resolve_path(self, literal, *, expected_sha256=None, source_id=None):
            key = str(literal), expected_sha256, source_id
            assert key in expected  # No physical/host path substitutes for scientific admission.
            calls.append(key)
            return views[expected.index(key)]

        def literal_path(self, path):
            assert path in views  # This port recognizes its approved spelling, not its symlink target.
            return sources[views.index(path)]["path"]

        def file_paths(self, actual, *, expected_sha256=None, source_id=None):
            literal = self.literal_path(actual)
            return literal, self.resolve_path(actual, expected_sha256=expected_sha256, source_id=source_id)

    before = deepcopy(document)
    with source_location_scope(StrictAliases()):
        if projection == "same-physical":
            selected = source_input_path(document, str(actual), original["sha256"])
            assert selected == views[0] and selected.is_symlink()
            assert literal_source_path(selected) == sources[0]["path"]
            assert file_sha256(selected) == original["sha256"]
        else:
            with pytest.raises(EngineError) as error:
                source_input_path(document, str(actual), original["sha256"])
            assert error.value.reason_code == "managed_source_locator_conflict"
    assert calls == expected
    assert document == before and len({source["source_id"] for source in sources}) == 2


@pytest.mark.parametrize("refusal", ["source-id", "version", "permission"])
def test_source_group_propagates_each_member_admission_refusal_before_equal_physical_io(tmp_path, refusal):
    from sciplot_core.plot_engine.managed_state import source_input_path
    from sciplot_core.project_store.errors import ProjectConflict, ProjectSourceVersionMismatch

    document, actual = relocated_document(tmp_path)
    sources = document["scientific"]["data_sources"]
    original = deepcopy(sources[0])
    for index in range(2):
        alias = tmp_path / f"scientific-alias-{index}.csv"
        alias.symlink_to(actual)
        source = {**deepcopy(original), "source_id": f"scientific:{index}", "path": str(alias)}
        if index == 0:
            sources[0] = source
        else:
            sources.append(source)
    expected = [(source["path"], source["sha256"], source["source_id"]) for source in sources]
    calls = []

    class StrictAliases:
        def resolve_path(self, literal, *, expected_sha256=None, source_id=None):
            key = str(literal), expected_sha256, source_id
            assert key in expected
            calls.append(key)
            if source_id == sources[1]["source_id"]:
                if refusal == "source-id":
                    raise ProjectConflict("This source ID is not registered for the selected input.")
                if refusal == "version":
                    raise ProjectSourceVersionMismatch(str(literal), "0" * 64, expected_sha256,
                                                       "The selected source version differs.")
                raise PermissionError("The selected source is outside this invocation's read grant.")
            return actual

        def literal_path(self, _actual):
            pytest.fail("A refused source cannot authorize reverse lookup or fallback.")

        def file_paths(self, actual, *, expected_sha256=None, source_id=None):
            literal = self.literal_path(actual)
            return literal, self.resolve_path(actual, expected_sha256=expected_sha256, source_id=source_id)

    error = {"source-id": ProjectConflict, "version": ProjectSourceVersionMismatch, "permission": PermissionError}[refusal]
    before = deepcopy(document)
    with source_location_scope(StrictAliases()), pytest.raises(error):
        source_input_path(document, str(actual), original["sha256"])
    assert calls == expected and document == before


def test_selected_source_double_requires_initial_identity_and_rejects_other_versions(tmp_path):
    document, actual = relocated_document(tmp_path)
    source = document["scientific"]["data_sources"][0]
    locator = SelectedSource(source, actual)
    with pytest.raises(AssertionError):
        locator.resolve_path(actual)
    assert locator.resolve_path(source["path"], expected_sha256=source["sha256"], source_id=source["source_id"]) == actual
    assert locator.resolve_path(actual) == actual
    assert locator.resolve_path(actual, expected_sha256=source["sha256"]) == actual
    for path, sha, identity in ((actual, "f" * 64, None), (actual, source["sha256"], "foreign"),
                                (tmp_path / "executor.py", source["sha256"], None)):
        with pytest.raises(AssertionError):
            locator.resolve_path(path, expected_sha256=sha, source_id=identity)


def test_managed_cold_source_io_and_currentness_keep_original_literal_and_seal(tmp_path):
    document, actual = relocated_document(tmp_path)
    before = deepcopy(document)
    source = document["scientific"]["data_sources"][0]
    locator = SelectedSource(source, actual)
    repo = FileProjectRepository(lease=lambda _: nullcontext())
    with pytest.raises(ValueError):
        load_sources(document, "uvvis_spectrum")
    with source_location_scope(locator), repository_scope(repo, capabilities=COMPATIBILITY_CAPABILITIES):
        raw = load_sources(document, "uvvis_spectrum")
        require_inputs(document)
        assert raw["A"]["columns"]["column:1"]["values"] == [2.0, 4.0, 8.0]
        assert raw["A"]["provenance"]["sources"][0]["sha256"] == source["sha256"]
        resolved, _ = resolve_science(tmp_path / "semantic", document)
        binding = make_binding(tmp_path / "semantic", resolved, output=tmp_path / "output")
        assert source["path"] in binding["fingerprint"]["files"]
        assert str(actual) not in binding["fingerprint"]["files"]
        assert source["path"] in input_files(resolved)
        backend = ManagedBackend.__new__(ManagedBackend)
        assert changed_inputs(backend, binding) == []
        assert resolved["scientific"]["data_sources"] == document["scientific"]["data_sources"]
    assert locator.calls and document == before
    with pytest.raises(ValueError):
        require_inputs(document)


@pytest.mark.parametrize("resolver_kind", ["minimal", "project"])
@pytest.mark.parametrize("host_kind", ["builtin", "external"])
def test_currentness_host_pins_never_enter_the_source_locator(tmp_path, monkeypatch, resolver_kind, host_kind):
    import sys
    from sciplot_core.foundation.file_hashing import file_sha256
    from sciplot_core.plot_engine.managed_state import declared_host_files
    from sciplot_core.plot_transforms import ExternalExecutor
    from sciplot_core.project_store.repository import FileProjectStore
    from sciplot_core.project_store.source_resolver import ProjectSourceResolver

    document, actual = relocated_document(tmp_path)
    if host_kind == "external":
        wire = request_for_source(tmp_path)
        script = tmp_path / "fixed-transform.py"
        script.write_text("raise AssertionError('A role projection must not execute the transform')\n")
        executor = ExternalExecutor(Path(sys.executable), script,
            {"type": "object", "properties": {}, "additionalProperties": False})
        node = wire["data_binding"]["transforms"][0]
        node.update(kind="external", parameters={}, executor=executor.descriptor("fixed"))
        document = resolved_metadata(create_managed_document(wire["template_definition"], wire["data_binding"],
            plot_id="host-role"), rule_id=wire["rule_id"], executors={"fixed": executor.to_dict("fixed")})
    source = document["scientific"]["data_sources"][0]
    if resolver_kind == "minimal":
        locator = SelectedSource(source, actual)
    else:
        project = tmp_path / "project"
        project.mkdir()
        store = FileProjectStore(project)
        store.snapshot(import_legacy=True)
        locator = ProjectSourceResolver(store)

    def forbidden(*args, **kwargs):
        pytest.fail("A declared implementation/executor pin entered source relocation")

    monkeypatch.setattr(locator, "resolve_path", forbidden)
    monkeypatch.setattr(locator, "literal_path", forbidden)
    host = declared_host_files(document)
    assert host
    before = deepcopy(document)
    with source_location_scope(locator):
        assert {path: ManagedBackend._source_hash(document, path, sha) for path, sha in host.items()} == host
        if host_kind == "external":
            script.write_text("raise AssertionError('A different implementation must stay different')\n")
            observed = ManagedBackend._source_hash(document, str(script), host[str(script)])
            assert observed == file_sha256(script) and observed != host[str(script)]
    assert document == before


def test_canonical_fingerprint_key_keeps_the_declared_source_literal(tmp_path):
    wire = request_for_source(tmp_path)
    source = wire["data_binding"]["data_sources"][0]
    actual = Path(source["path"])
    source["path"] = str(tmp_path / "unavailable-original" / "unused" / ".." / "A.csv")
    document = resolved_metadata(create_managed_document(wire["template_definition"], wire["data_binding"],
        plot_id="source-literal-spelling"), rule_id=wire["rule_id"], executors={})
    before = deepcopy(document)
    source = document["scientific"]["data_sources"][0]
    locator = SelectedSource(source, actual)
    repo = FileProjectRepository(lease=lambda _: nullcontext())
    with source_location_scope(locator), repository_scope(repo, capabilities=COMPATIBILITY_CAPABILITIES):
        resolved, _ = resolve_science(tmp_path / "semantic", document)
        binding = make_binding(tmp_path / "semantic", resolved, output=tmp_path / "output")
        assert str(Path(source["path"]).resolve()) in binding["fingerprint"]["files"]
        assert changed_inputs(ManagedBackend.__new__(ManagedBackend), binding) == []
        assert resolved["scientific"]["data_sources"] == document["scientific"]["data_sources"]
    assert document == before
    assert (source["path"], source["sha256"], source["source_id"]) in locator.calls


@pytest.mark.parametrize("resolver_kind", ["minimal", "project"])
def test_equal_bytes_do_not_authorize_an_undeclared_fingerprint_path(tmp_path, monkeypatch, resolver_kind):
    from sciplot_core.plot_engine import managed_backend
    from sciplot_core.project_store.repository import FileProjectStore
    from sciplot_core.project_store.source_resolver import ProjectSourceResolver

    document, actual = relocated_document(tmp_path)
    source = document["scientific"]["data_sources"][0]
    other = tmp_path / "same-bytes-other-file.csv"
    other.write_bytes(actual.read_bytes())
    if resolver_kind == "minimal":
        locator = SelectedSource(source, actual)
    else:
        project = tmp_path / "project"
        project.mkdir()
        store = FileProjectStore(project)
        store.snapshot(import_legacy=True)
        locator = ProjectSourceResolver(store)

    def forbidden(_path):
        pytest.fail("An undeclared fingerprint path must not be opened as a host pin")

    monkeypatch.setattr(managed_backend, "existing_file_sha256", forbidden)
    before = deepcopy(document)
    with source_location_scope(locator):
        assert ManagedBackend._source_hash(document, str(other), source["sha256"]) is None
    assert document == before


@pytest.mark.parametrize("failure", ["missing", "changed_bytes"])
def test_currentness_does_not_replace_refused_source_io_with_the_original(tmp_path, failure):
    document, actual = relocated_document(tmp_path)
    before = deepcopy(document)
    source = document["scientific"]["data_sources"][0]
    original = Path(source["path"])
    original.parent.mkdir()
    original_bytes = actual.read_bytes()
    original.write_bytes(original_bytes)
    repo = FileProjectRepository(lease=lambda _: nullcontext())
    with source_location_scope(SelectedSource(source, actual)), repository_scope(repo, capabilities=COMPATIBILITY_CAPABILITIES):
        resolved, _ = resolve_science(tmp_path / "semantic", document)
        binding = make_binding(tmp_path / "semantic", resolved, output=tmp_path / "output")

    class Refused(SelectedSource):
        def resolve_path(self, original, *, expected_sha256=None, source_id=None):
            if failure == "missing":
                raise ValueError("The selected source is unavailable")
            return super().resolve_path(original, expected_sha256=expected_sha256, source_id=source_id)

        def file_paths(self, actual, *, expected_sha256=None, source_id=None):
            literal = self.literal_path(actual)
            return literal, self.resolve_path(actual, expected_sha256=expected_sha256, source_id=source_id)

    if failure == "changed_bytes":
        actual.write_text("Time,Signal\ns,V\n0,99\n1,99\n2,99\n")
    with source_location_scope(Refused(source, actual)):
        backend = ManagedBackend.__new__(ManagedBackend)
        if failure == "missing":
            with pytest.raises(ValueError, match="selected source"):
                changed_inputs(backend, binding)
        else:
            assert changed_inputs(backend, binding) == [source["path"]]
    assert document == before
    assert original.read_bytes() == original_bytes


@pytest.mark.parametrize("failure", ["missing", "changed_bytes"])
def test_locator_failure_never_falls_back_to_same_name_original_or_blesses_changed_bytes(tmp_path, failure):
    document, actual = relocated_document(tmp_path)
    source = document["scientific"]["data_sources"][0]
    literal = Path(source["path"])
    literal.parent.mkdir()
    literal.write_bytes(actual.read_bytes())  # A tempting live same-name/original candidate.
    original = deepcopy(document)
    class Refused(SelectedSource):
        def resolve_path(self, original, *, expected_sha256=None, source_id=None):
            if failure != "changed_bytes":
                raise ValueError("The explicitly selected source version is unavailable")
            return super().resolve_path(original, expected_sha256=expected_sha256, source_id=source_id)

        def file_paths(self, actual, *, expected_sha256=None, source_id=None):
            literal = self.literal_path(actual)
            return literal, self.resolve_path(actual, expected_sha256=expected_sha256, source_id=source_id)
    locator = Refused(source, actual)
    if failure == "changed_bytes":
        actual.write_text("Time,Signal\ns,V\n0,99\n1,99\n2,99\n")
    with source_location_scope(locator):
        with pytest.raises(ValueError):
            load_sources(document, "uvvis_spectrum")
        with pytest.raises(ValueError):
            require_inputs(document)
    assert document == original and literal.read_bytes() != b""
