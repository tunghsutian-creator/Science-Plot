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
        reentry = (str(original), expected_sha256, source_id) == (str(self.actual), None, None)
        verified = expected in self.calls
        self.calls.append((str(original), expected_sha256, source_id))
        assert self.calls[-1] == expected or reentry and verified  # Exact same-reader IO; code paths cannot become source mappings.
        return self.actual

    def literal_path(self, actual):
        assert actual == self.actual
        return self.source["path"]


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
    locator = Refused(source, actual)
    if failure == "changed_bytes":
        actual.write_text("Time,Signal\ns,V\n0,99\n1,99\n2,99\n")
    with source_location_scope(locator):
        with pytest.raises(ValueError):
            load_sources(document, "uvvis_spectrum")
        with pytest.raises(ValueError):
            require_inputs(document)
    assert document == original and literal.read_bytes() != b""
