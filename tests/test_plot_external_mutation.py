"""Complete native equality distinguishes represented edits from mixed opaque state."""

from copy import deepcopy
import hashlib
from pathlib import Path

import pytest

from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.plot_backends.veusz_external_mutation import compare_setting_transcript
from sciplot_core.plot_engine.errors import EngineError
from sciplot_core.plot_engine.external_mutation import (
    authority_status, capture_baseline, exact_native_equivalence, record_external_mutation,
    record_legacy_mutation, require_managed_representability, validate_external_mutation,
)

SCRIPT = b"""# Veusz saved document
SetCompatLevel(0)
ImportString('x(numeric)', '1\\n2\\n')
Add('page', name='page1', autoadd=False)
To('page1')
Add('graph', name='graph1', autoadd=False)
To('graph1')
Set('rightMargin', '0.45cm')
Add('xy', name='series_1', autoadd=False)
To('series_1')
Set('xData', 'x')
Set('PlotLine/width', '1pt')
To('..')
To('..')
To('..')
"""
DIFF = [{"target": "series:E2", "property": "style.line.width", "before": "1pt", "after": "0.7pt"}]
SETTING = "/page1/graph1/series_1/PlotLine/width"


def _legacy(tmp_path):
    native = tmp_path / "document.vsz"
    native.write_bytes(SCRIPT)
    binding = {"document": str(native), "fingerprint": {"files": {str(native): file_sha256(native)}},
               "targets": {"series:E2": {"properties": {"style.line.width": {
                   "kind": "setting", "setting_path": SETTING}}}}}
    root = tmp_path / "history"
    frozen = capture_baseline(root, binding)
    return root, native, {"document": {"plot_id": "test", "revision": 0}, "binding": frozen}


def _record(tmp_path, content):
    root, native, head = _legacy(tmp_path)
    native.write_bytes(content)
    binding = deepcopy(head["binding"])
    binding["fingerprint"]["files"][str(native)] = file_sha256(native)
    return record_legacy_mutation(root, head, binding, DIFF)


def test_legacy_width_is_known_only_with_complete_prior_native_baseline(tmp_path):
    record = _record(tmp_path, SCRIPT.replace(b"'1pt'", b"'0.7pt'"))
    assert record["classification"] == "known_semantic_delta" and record["represented_diff"] == DIFF
    assert record["authority"] == "LegacyPlot"
    assert record["equivalence"]["method"] == "closed_saved_transcript"
    assert validate_external_mutation(record) == record


@pytest.mark.parametrize("extra", [
    lambda raw: raw.replace(b"'0.45cm'", b"'0.95cm'"),
    lambda raw: raw.replace(b"'1\\n2\\n'", b"'1\\n9\\n'"),
    lambda raw: raw + b"Set('width', '999mm')\n",
    lambda raw: raw + b"UnknownNativeFeature('anything')\n",
])
def test_legacy_width_plus_unrepresented_native_change_stays_opaque(tmp_path, extra):
    record = _record(tmp_path, extra(SCRIPT.replace(b"'1pt'", b"'0.7pt'")))
    assert record["classification"] == "opaque_native_change"
    assert record["represented_diff"] == DIFF


def test_unrecorded_legacy_baseline_never_infers_complete_native_coverage(tmp_path):
    root, native, head = _legacy(tmp_path)
    head["binding"].pop("native_baseline")
    native.write_bytes(SCRIPT.replace(b"'1pt'", b"'0.7pt'"))
    binding = deepcopy(head["binding"])
    binding["fingerprint"]["files"][str(native)] = file_sha256(native)
    record = record_legacy_mutation(root, head, binding, DIFF)
    assert record["classification"] == "opaque_native_change" and record["equivalence"] is None


def test_corrupt_frozen_baseline_is_not_accepted_as_opaque_fallback(tmp_path):
    root, native, head = _legacy(tmp_path)
    Path(head["binding"]["native_baseline"]["path"]).write_bytes(b"changed history")
    native.write_bytes(SCRIPT.replace(b"'1pt'", b"'0.7pt'"))
    binding = deepcopy(head["binding"])
    binding["fingerprint"]["files"][str(native)] = file_sha256(native)
    with pytest.raises(EngineError) as error:
        record_legacy_mutation(root, head, binding, DIFF)
    assert error.value.reason_code == "external_mutation_baseline_corrupt"


def test_capture_checks_current_sha_and_never_replaces_a_baseline(tmp_path):
    root, native, head = _legacy(tmp_path)
    baseline = Path(head["binding"]["native_baseline"]["path"])
    assert baseline.read_bytes() == SCRIPT and not baseline.is_relative_to(native.parent / "project")
    native.write_bytes(b"new bytes")
    with pytest.raises(EngineError) as error:
        capture_baseline(root, head["binding"])
    assert error.value.reason_code == "external_mutation_baseline_changed"
    assert baseline.read_bytes() == SCRIPT


@pytest.mark.parametrize("suffix", [b"To('page1')\nTo('graph1')\nTo('series_1')\nSet('PlotLine/width', '0.7pt')\n",
                                    b"__import__('os').getcwd()\n", b"value = 1\n"])
def test_closed_transcript_does_not_execute_or_guess_unknown_syntax(suffix):
    assert compare_setting_transcript(SCRIPT + suffix, SCRIPT + suffix, []) is None


def test_transcript_ignores_only_comments_and_python_literal_formatting():
    observed = SCRIPT.replace(b"'1pt'", b'"0.7pt"') + b"# Saved at a later time\n"
    result = compare_setting_transcript(SCRIPT, observed, [{"setting_path": SETTING, "before": "1pt", "after": "0.7pt"}])
    assert result["observed_state_sha256"] == result["expected_state_sha256"]


def _managed(*, opaque=False):
    before, after = hashlib.sha256(SCRIPT).hexdigest(), hashlib.sha256(b"observed").hexdigest()
    proof = exact_native_equivalence(backend_identity="b" * 64, before_native_sha256=before,
        observed_native_sha256=after, expected_native_sha256="e" * 64 if opaque else after,
        base_revision=0, represented_diff=DIFF)
    return record_external_mutation(plot_id="test", base_revision=0, authority="ManagedPlot", backend="veusz",
        before_native_sha256=before, after_native_sha256=after, represented_diff=DIFF, equivalence=proof)


def test_managed_unknown_native_state_is_rejected_despite_known_width_diff():
    record = _managed(opaque=True)
    with pytest.raises(EngineError) as error:
        require_managed_representability(record)
    assert error.value.reason_code == "managed_external_mutation_opaque"
    assert error.value.repair["action"] == "reject_or_explicit_downgrade"


def test_exact_equivalence_record_cannot_be_reused_for_another_delta_or_authority():
    record = _managed()
    assert require_managed_representability(record) == record
    for field, value in (("base_revision", 1), ("after_native_sha256", "f" * 64), ("authority", "LegacyPlot")):
        changed = {**record, field: value}
        with pytest.raises(EngineError):
            validate_external_mutation(changed)


def test_authority_modes_state_their_actual_rebuild_boundary():
    assert authority_status("ManagedPlot")["source_of_truth"] == "sciplot_document"
    assert authority_status("ManagedPlot")["rebuild_from_document"] is True
    assert authority_status("LegacyPlot")["source_of_truth"] == "saved_native_document"
    assert authority_status("LegacyPlot")["rebuild_from_document"] is False
