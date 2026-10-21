"""Native measured XY/append, then cold-service current-export cache reuse."""
import json
import os
from pathlib import Path

import pytest
from test_frequency_interval_binding import instrument_source
from test_task_semantic_resolution import bits, raw_intent, source_coordinates, state


@pytest.mark.comprehensive
def test_native_ordinary_measured_log_conversion_append_and_cold_service_reuse(tmp_path):
    from sciplot_core.foundation.file_hashing import file_sha256
    from sciplot_core.plot_backends.managed_audit import scientific_audit
    from sciplot_core.plot_backends.native_primitives import dataset_name
    from sciplot_core.plot_engine.service import PlotService
    from sciplot_core.plot_engine.storage import load_head, read
    from sciplot_core.plot_ir.figure_document import figure_spec
    from sciplot_core.task_semantic_creation import build_managed_request
    from sciplot_core.veusz_worker.document_edit import loaded_native_document

    first = instrument_source(tmp_path / "E2.csv", temperatures=(190,), magnitude=True)
    second = instrument_source(tmp_path / "E4.csv", temperatures=(170,), magnitude=True)
    first.write_text(first.read_text(encoding="utf-16").replace("Anonymous material", "E2"), encoding="utf-16")
    # Construct a deliberately different reported measurement before freezing
    # the generated original. Recomputing it from G'/G'' would be incorrect.
    rows = second.read_text(encoding="utf-16").splitlines()
    rows[2] = rows[2].replace("Anonymous material", "E4")
    for index in range(10, 26):
        cells = rows[index].split("\t")
        cells[11] = str(float(cells[11]) * 2)
        rows[index] = "\t".join(cells)
    second.write_text("\n".join(rows), encoding="utf-16")
    sources = {str(path): file_sha256(path) for path in (first, second)}
    intent = raw_intent()
    intent["selection"] = {"test_names": ["E2"]}
    current = state(first, intent, tmp_path)
    wire = build_managed_request(current)
    expected = [source_coordinates(path) for path in (first, second)]
    service = PlotService()
    sessions = []
    try:
        created = service.create(wire)
        assert created["ready_to_use"], created
        plot = Path(created["plot"])
        before = load_head(plot)
        old_ir = read(Path(before["binding"]["ir_path"]))
        assert "source.append" in service.describe(plot)["figure_edit_contract"]["view:main"]
        # Explicit presentation recovery retains the long appended label and
        # the original data. The first, narrower proof's failure is retained.
        from jsonschema import Draft202012Validator

        layout_contract = service.describe(plot, description={"scope": "edit", "target": "figure:main", "property": "layout"})
        layout = {**layout_contract["current_value"], "width_mm": 120}
        descriptor = layout_contract["figure_edit_contract"]["figure:main"]["layout"]
        assert Draft202012Validator(descriptor["value_schema"]).is_valid(layout)
        layout_request = {"plot_id": created["plot_id"], "base_revision": 0, "idempotency_key": "explicit-space-for-long-legend",
            "intent_class": "presentation", "changes": [{"op": "set", "target": ["figure:main"], "property": "layout", "value": layout}]}
        resized = service.patch(plot, layout_request)
        if resized["status"] == "needs_review":
            resized = service.decide(plot, resized["next_step"]["request"])
        assert resized["ready_to_use"] and resized["revision"] == 1, resized
        assert load_head(plot)["document"]["scientific_hash"] == before["document"]["scientific_hash"]
        other_intent = raw_intent()
        other_intent["selection"] = {"test_names": ["E4"]}
        other = state(second, other_intent, tmp_path / "other")["semantic_plan"]
        coordinate = other["resolved_bindings"][0]
        request = {"plot_id": created["plot_id"], "base_revision": resized["revision"], "idempotency_key": "append-second-measured-original",
            "intent_class": "scientific", "changes": [{"op": "set", "target": ["view:main"], "property": "source.append",
                "value": {"source": {"source_id": "raw:E4", "path": str(second), "sha256": sources[str(second)],
                                     "table_selection": coordinate["table_selection"]},
                          "curves": [{"sample": "E4", "x_column_index": 3, "y_column_index": 11,
                                      "x_unit": "rad/s", "y_unit": "Pa s", "label": "Second measured curve"}]}}]}
        preview = service.patch(plot, request)
        assert preview["status"] == "needs_review", preview
        accepted = service.decide(plot, preview["next_step"]["request"])
        assert accepted["ready_to_use"] and accepted["revision"] == 2, accepted
        assert service.patch(plot, request)["replayed"] is True
        head = load_head(plot)
        ir = read(Path(head["binding"]["ir_path"]))
        assert all(ir["datasets"][name] == dataset for name, dataset in old_ir["datasets"].items())
        layers = figure_spec(head["document"])["views"][0]["layers"]
        assert len(layers) == 2
        with loaded_native_document(Path(head["binding"]["document"])) as loaded:
            assert scientific_audit(ir, loaded)["status"] == "passed"
            for index, layer in enumerate(layers):
                assert bits(loaded.data[dataset_name(layer["dataset_id"], layer["mappings"]["x"])].data.tolist()) == bits(expected[index][0])
                assert bits(loaded.data[dataset_name(layer["dataset_id"], layer["mappings"]["y"])].data.tolist()) == bits(expected[index][1])
        scientific_hash = head["document"]["scientific_hash"]
    finally:
        worker = service.backend.managed.compiler._worker
        process = worker._process
        service.close()
        if process is not None:
            sessions.append({"pid": process.pid, "starts": worker.starts, "normal_close_exit": process.returncode})
            assert process.returncode == 0
    # Reconstruct the semantic service after the native worker has closed.
    # Exact-current exports are reusable; this path does not reopen Veusz.
    cold_service = PlotService()
    try:
        cold = cold_service.describe(plot)
        exported = cold_service.export(plot)
        assert cold["status"] == "current" and cold["revision"] == 2
        assert exported["ready_to_use"] and exported["revision"] == 2
        assert load_head(plot)["document"]["scientific_hash"] == scientific_hash
        assert {str(path): file_sha256(path) for path in (first, second)} == sources
    finally:
        worker = cold_service.backend.managed.compiler._worker
        process = worker._process
        cold_service.close()
        assert process is None and worker.starts == 0
    assert len(sessions) == 1 and sessions[0]["normal_close_exit"] == 0
    evidence = tmp_path / "native-continuation.json"
    evidence.write_text(json.dumps({"scope": "generated proof with explicit schema-bound 120mm layout; real native arrays and one normally closed worker; cold-service reconstruction reuses current exports without a new native process; no default RPC socket; no native or human GUI restart claim",
        "proof_pid": os.getpid(), "native_sessions": sessions, "source_sha256": sources, "created": created,
        "cold_service_native_starts": 0,
        "layout_contract": layout_contract, "resized": resized, "layout_scientific_hash_before": before["document"]["scientific_hash"],
        "preview": preview, "accepted": accepted, "cold": cold, "exported": exported, "scientific_hash": scientific_hash,
        "source_to_native": {"x": "original float.hex exact", "y": "original reported cell float * .001 hex exact", "rows_per_source": 16}}, indent=2))
