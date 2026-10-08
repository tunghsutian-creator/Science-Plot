"""Native drift classification proves the complete candidate, never adopts it."""

from copy import deepcopy
import json
from pathlib import Path

import pytest

from sciplot_core._paths import REPO_ROOT
from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.plot_backends.managed import ManagedVeuszCompiler
from sciplot_core.plot_backends.managed_plan import native_name
from sciplot_core.plot_engine.external_mutation import require_managed_representability
from sciplot_core.plot_engine.errors import EngineError
from sciplot_core.plot_engine.managed_external import inspect_managed_mutation
from sciplot_core.plot_engine.managed_state import make_binding, resolved_ir
from sciplot_core.plot_engine.storage import write
from sciplot_core.plot_ir import create_managed_document
from sciplot_core.plot_transforms import resolve_transforms
from test_plot_ir import managed_example


def _canonical(tmp_path):
    template, binding, datasets = managed_example()
    for source in binding["data_sources"]:
        path = tmp_path / (source["source_id"] + ".csv")
        values = datasets[source["source_id"]]["columns"]["column:1"]["values"]
        path.write_text("Time,Signal\ns,V\n" + "\n".join(f"{i},{'' if value is None else value}" for i, value in enumerate(values)) + "\n")
        source.update(path=str(path), sha256=file_sha256(path))
        datasets[source["source_id"]]["provenance"]["sources"][0]["sha256"] = source["sha256"]
    document = resolve_transforms(create_managed_document(template, binding, plot_id="managed-external"), datasets)["document"]
    root = tmp_path / "plot"
    return root, document, make_binding(root, document, output=root / "generated")


@pytest.mark.comprehensive
@pytest.mark.parametrize("opaque", [False, True])
def test_managed_inspection_requires_full_candidate_equivalence_and_never_adopts(tmp_path, opaque):
    root, document, binding = _canonical(tmp_path)
    original_document = deepcopy(document)
    model = Path(binding["canonical_document"])
    model_before = model.read_bytes()
    compiler = ManagedVeuszCompiler(warm=False)
    native = Path(binding["document"])
    original_ir = resolved_ir(root, document)
    built = compiler.compile_ir(original_ir, native.parent)
    write(native.parent / "build.json", {key: built[key] for key in (
        "ir_hash", "document_sha256", "native_state_hash", "compiler_identity")})
    widget = "/page1/graph1/" + native_name("series", "series:A")
    changes = [{"object_path": widget, "setting_path": widget + "/PlotLine/width", "expected_value": "0.7pt", "value": "1.1pt"}]
    if opaque:
        changes.append({"object_path": widget, "setting_path": widget + "/markerSize", "expected_value": "3.0pt", "value": "5pt"})
    request = tmp_path / "native-change.json"
    request.write_text(json.dumps(changes))
    modified = tmp_path / "manually-saved.vsz"
    compiler._run(["edit-document", str(native), "--changes", str(request), "--output-document", str(modified),
                   "--preview-png", str(tmp_path / "manual-preview.png")])
    native.write_bytes(modified.read_bytes())
    saved = native.read_bytes()
    record = inspect_managed_mutation(root, binding, compiler)
    assert record["authority"] == "ManagedPlot"
    assert record["represented_diff"] == [{"target": "series:A", "property": "style.line.width", "before": "0.7pt", "after": "1.1pt"}]
    assert record["classification"] == ("opaque_native_change" if opaque else "known_semantic_delta")
    assert record["equivalence"]["method"] == "canonical_native_state"
    if opaque:
        with pytest.raises(EngineError, match="not completely represented"):
            require_managed_representability(record)
    else:
        assert require_managed_representability(record) == record
    assert model.read_bytes() == model_before and native.read_bytes() == saved
    assert document == original_document and not (root / "head.json").exists()
    assert not (native.parent / "exports").exists()
    evidence = REPO_ROOT / f".tmp_verify/document_migration_20261007/external_mutation_managed_{'opaque' if opaque else 'known'}.json"
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text(json.dumps({"status": "passed", "external_mutation": record,
        "canonical_unchanged": True, "native_unchanged_by_inspection": True,
        "revision_or_exports_created": False}, indent=2))


def test_untracked_native_cannot_claim_an_invented_before_hash(tmp_path):
    root, document, binding = _canonical(tmp_path)
    native = Path(binding["document"])
    native.parent.mkdir(parents=True)
    native.write_bytes(b"foreign native file")
    class NoInspect:
        def inspect_ir(self, *_):
            pytest.fail("An untracked file must be rejected before native inspection")
    with pytest.raises(EngineError) as error:
        inspect_managed_mutation(root, binding, NoInspect())
    assert error.value.reason_code == "managed_external_mutation_untracked"
