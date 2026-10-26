"""Generated raw-group continuation; native preparation/export ports are stubbed."""
from copy import deepcopy
import json
from pathlib import Path

import pytest

from sciplot_core import task_control as control, task_execution as execution, task_source_execution as source_execution
from sciplot_core.data_mapping import load_data_mapping_execution
from sciplot_core.data_mapping.plan_binding import resolve_mapping_plan_request
from sciplot_core.data_mapping.plan_binding import project_replicate_binding, verify_replicate_source_expansion
from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.foundation.json_hashing import canonical_json_sha256
from sciplot_core.plan_preview import build_plan_preview
from sciplot_core.semantic_sources.impact_sources import _read_impact_source
from sciplot_core.studio_core import source_update_commit as transaction, source_update_review as review
from sciplot_core.task_contract import TaskControlError
from sciplot_core.task_storage import load_task
from test_task_raw_replicate_mapping import original, native_boundary


def project_request(source, plan):
    seed, binding = resolve_mapping_plan_request(source, plan["data_mapping"])
    return {**seed, "render_options": {"summary_statistic": "raw_only"},
            "data_mapping_plan_binding": binding, "resolved_figure_plan": plan["resolved_figure_plan"]}


def write_project(project, source, request):
    for name in ("raw", "source", "studio"):
        (project / name).mkdir(parents=True, exist_ok=True)
    for name in ("raw", "source"):
        (project / name / source.name).write_bytes(source.read_bytes())
    (project / "plot_request.json").write_text(json.dumps(request))
    (project / "intake_manifest.json").write_text("{}")
    payload = _read_impact_source(Path(request["data_mapping_plan_binding"]["effective_input"]))
    groups = [{"label": sample, "raw_values": list(values), "replicate_count": len(values)}
              for sample, values in zip(payload.samples, payload.values, strict=True)]
    (project / "studio/spec.json").write_text(json.dumps({"template": "box", "categorical": {"groups": groups},
        "series": [], "styles": {"Amber": "#123456", "Blue": "#abcdef"}}))
    (project / "studio/document.vsz").write_text("generated native boundary placeholder")


@pytest.fixture
def bound(tmp_path, monkeypatch):
    source, request, mapping = original(tmp_path)
    calls = native_boundary(monkeypatch, tmp_path)
    state = control.start_task({**request, "mapping": mapping}, task_dir=tmp_path / "initial")
    assert state["status"] == "complete" and len(calls) == 1
    project = tmp_path / "project"
    previous = project_request(source, calls[0]["expected_plan"])
    write_project(project, source, previous)
    return source, project, mapping, previous


def expanded(mapping):
    result = deepcopy(mapping)
    result["column_mapping"]["replicates"].append({"column_index": 2,
        "table_selection": {**mapping["table_selection"], "data_end_row": 8}})
    return result


def mapped_plan(source, mapping, tmp_path, monkeypatch):
    calls = native_boundary(monkeypatch, tmp_path)
    state = control.start_task({"version": 1, "action": "create", "source": str(source),
        "rule_id": "impact_metric", "template": "box", "summary_statistic": "raw_only", "mapping": mapping},
        task_dir=tmp_path / "mapping_task")
    assert state["status"] == "complete", state
    return calls[0]["expected_plan"]


def test_raw_group_expansion_retains_old_source_domains_masks_and_exact_values(bound, tmp_path, monkeypatch):
    source, _, mapping, previous = bound
    plan = mapped_plan(source, expanded(mapping), tmp_path, monkeypatch)
    verify_replicate_source_expansion(previous, source, plan["data_mapping"], plan)
    old = load_data_mapping_execution(previous["data_mapping_execution"])
    new = load_data_mapping_execution(plan["data_mapping"]["data_mapping_execution"])
    assert [item["rows"] for item in new["outputs"]] == [7, 7, 5]
    assert [item["sha256"] for item in new["outputs"][:2]] == [item["sha256"] for item in old["outputs"]]
    assert plan["resolved_figure_plan"]["primary_figure_id"] == previous["resolved_figure_plan"]["primary_figure_id"] == "impact_strength_by_sample"
    assert plan["data_mapping"]["expected_sample_labels"] == ["Amber", "Blue", "Coral"]


@pytest.mark.parametrize("change", ["only_new", "reorder", "row_domain", "old_label"])
def test_fresh_mapping_cannot_drop_rebind_or_rename_old_raw_groups(bound, tmp_path, monkeypatch, change):
    source, _, mapping, previous = bound
    candidate = expanded(mapping)
    groups = candidate["column_mapping"]["replicates"]
    if change == "only_new":
        candidate["column_mapping"]["replicates"] = groups[2:]
    elif change == "reorder":
        groups[0], groups[1] = groups[1], groups[0]
    elif change == "row_domain":
        groups[0]["table_selection"] = {**mapping["table_selection"], "data_end_row": 9}
    else:
        groups[0]["label"] = "Renamed Amber"
    plan = mapped_plan(source, candidate, tmp_path, monkeypatch)
    with pytest.raises(ValueError, match="existing raw group"):
        verify_replicate_source_expansion(previous, source, plan["data_mapping"], plan)


@pytest.mark.parametrize("field", ["summary_statistic", "render_options", "data_mapping_plan_binding"])
def test_raw_mode_cannot_be_inferred_from_mutated_project_context(bound, field):
    _, _, _, previous = bound
    previous = deepcopy(previous)
    if field == "data_mapping_plan_binding":
        previous[field]["expected_sample_labels"] = ["Coral"]
    elif field == "render_options":
        previous[field]["summary_statistic"] = "mean_sample_sd_n"
    else:
        previous[field] = "mean_sample_sd_n"
    with pytest.raises(ValueError, match="immutable replicate binding"):
        project_replicate_binding(previous)


def test_same_task_corrects_choice_reviews_same_figure_and_installs_once_with_archive(bound, tmp_path, monkeypatch):
    source, project, mapping, previous = bound
    original_bytes = source.read_bytes()
    baseline = transaction.project_inventory(project)
    candidates = []
    events = []
    monkeypatch.setattr(review, "project_figures", lambda root: {"impact_strength_by_sample":
        (root / "studio/document.vsz", root / "studio/spec.json")})

    def preview(selected_project, selected_source, *, review_path, worksheet, mapping_request):
        assert selected_project == project and selected_source == source and worksheet is None
        plan = dict(build_plan_preview(source, request=mapping_request))
        try:
            verify_replicate_source_expansion(previous, source, mapping_request, plan)
        except ValueError as exc:
            return {"status": "blocked", "project": str(project), "revision_id": "0" * 64,
                    "review_path": str(review_path), "previews": [],
                    "source_update": {"reason": f"Fresh source mapping cannot prepare this project: {exc}"}}
        candidate = tmp_path / f"candidate_{len(candidates)}"
        write_project(candidate, source, project_request(source, plan))
        changes = review.compare_figures(project, candidate)
        assert changes["before_figure_count"] == changes["after_figure_count"] == 1
        assert changes["figures"][0]["samples_added"] == ["Coral"]
        assert changes["figures"][0]["samples_removed"] == []
        assert changes["figures"][0]["numerical_differences"] == []
        record = {"kind": "sciplot_project_source_update", "version": 1, "status": "ready",
                  "project": str(project), "source": str(source), "changes": changes}
        revision = canonical_json_sha256(record)
        candidates.append((candidate, record, revision))
        events.append("preview")
        return {"status": "ready", "project": str(project), "revision_id": revision,
                "review_path": str(review_path), "source_update": record,
                "previews": [{"scope": scope, "figure_id": "impact_strength_by_sample", "preview": {"path": str(tmp_path / f"{scope}.png")}}
                             for scope in ("before", "candidate")]}

    monkeypatch.setattr(source_execution, "prepare_source_update_review", preview)
    task = tmp_path / "update"
    state = control.start_task({"version": 1, "action": "update_source", "project": str(project), "source": str(source)}, task_dir=task)
    assert state["status"] == "needs_input" and state["question"]["mapping_shape"] == "replicates"
    assert "Amber" in state["question"]["message"]
    incomplete = expanded(mapping)
    incomplete["column_mapping"]["replicates"] = incomplete["column_mapping"]["replicates"][2:]
    state = control.resume_task(task, {"expected_question_id": state["question"]["question_id"], "mapping": incomplete})
    assert state["status"] == "needs_input" and state["mapping_error"]["reason_code"] == "source_mapping_invalid"
    assert transaction.project_inventory(project) == baseline
    state = control.resume_task(task, {"expected_question_id": state["question"]["question_id"], "mapping": expanded(mapping)})
    assert state["status"] == "needs_review" and len(candidates) == 1, state
    with pytest.raises(TaskControlError, match="旧源更新预览"):
        control.resume_task(task, {"accept_source_update": True, "expected_revision_id": "0" * 64})

    def apply(_project, *, review_path, expected_revision_id):
        candidate, record, revision = candidates[0]
        assert _project == project and expected_revision_id == revision
        events.append("apply")
        archive = transaction.install_source_update(project, candidate,
            expected=transaction.project_inventory(project), review=record, validate=lambda: None)
        assert transaction.project_inventory(archive) == baseline
        assert file_sha256(archive / "source" / source.name) == file_sha256(source)
        return {"status": "updated", "archive": str(archive), "document": str(project / "studio/document.vsz")}

    monkeypatch.setattr(source_execution, "apply_source_update_review", apply)

    def fail_export(*args):
        events.append("export_failed")
        raise OSError("generated export boundary failure")

    monkeypatch.setattr(execution, "export_project", fail_export)
    state = control.resume_task(task, {"accept_source_update": True, "expected_revision_id": state["revision_id"]})
    assert state["status"] == "blocked" and state["phase"] == "exporting"
    monkeypatch.setattr(execution, "export_project", lambda *a: events.append("export") or {
        "project_dir": str(project), "studio_run": {"ready_to_use": True, "failure_reason": None}})
    state = control.resume_task(task, {"retry": True})
    assert state["status"] == "complete"
    assert control.resume_task(task, {"retry": True})["status"] == "complete"
    assert events == ["preview", "apply", "export_failed", "export"]
    current = json.loads((project / "plot_request.json").read_text())
    assert current["data_mapping_plan_binding"]["expected_sample_labels"] == ["Amber", "Blue", "Coral"]
    assert source.read_bytes() == original_bytes
    assert load_task(task)["source_update_outcome"]["status"] == "updated"


def test_existing_staging_rejects_changed_old_domain_before_native_preparation(bound, tmp_path, monkeypatch):
    from sciplot_core.project_host_factory import project_store
    from sciplot_core.project_store.runtime import project_runtime
    from sciplot_core.studio_core import source_update_staging
    source, project, mapping, _ = bound
    candidate = expanded(mapping)
    candidate["column_mapping"]["replicates"][0]["table_selection"] = {**mapping["table_selection"], "data_end_row": 9}
    plan = mapped_plan(source, candidate, tmp_path, monkeypatch)
    store = project_store(project)
    snapshot = store.snapshot(import_legacy=True)
    before = transaction.project_inventory(project)
    monkeypatch.setattr(source_update_staging, "_build_source_candidate", lambda *a, **k: pytest.fail("changed old group must stop before private/native preparation"))
    with project_runtime(store), pytest.raises(ValueError, match="Fresh source mapping cannot prepare.*existing raw group"):
        with source_update_staging.prepare_candidate(project, source, tmp_path / "staging", worksheet=None, mapping_request={
                **plan["data_mapping"], "rule_id": "impact_metric", "template": "box"}):
            pytest.fail("A changed existing raw group reached a private candidate")
    assert transaction.project_inventory(project) == before and not (tmp_path / "staging").exists()
    assert store.snapshot() == snapshot


def test_fresh_mapping_reaches_real_private_native_boundary_with_old_raw_groups_intact(bound, tmp_path, monkeypatch):
    from sciplot_core.project_host_factory import project_store
    from sciplot_core.project_store.runtime import project_runtime
    from sciplot_core.studio_core import preparation_commands, source_update_staging
    from sciplot_core.studio_core.source_update_sources import incoming_scope
    import subprocess

    source, project, mapping, previous = bound
    plan = mapped_plan(source, expanded(mapping), tmp_path, monkeypatch)
    old = load_data_mapping_execution(previous["data_mapping_execution"])
    store = project_store(project, with_snapshot=True)
    snapshot = store.snapshot(import_legacy=True)
    before = transaction.project_inventory(project)
    original = source.read_bytes()
    reached = []

    class NativeBoundaryReached(Exception):
        pass

    def native_boundary(candidate, **kwargs):
        request = json.loads(candidate.read_member("plot_request.json").data)
        assert candidate.store.root == project and candidate.snapshot["generation"] == snapshot["generation"]
        assert candidate.project_dir != project and kwargs["regenerate_generated"] is True
        assert request["data_mapping_execution"] == plan["data_mapping"]["data_mapping_execution"]
        assert request["data_mapping_plan_binding"]["expected_sample_labels"] == ["Amber", "Blue", "Coral"]
        current = load_data_mapping_execution(request["data_mapping_execution"])
        assert [item["rows"] for item in current["outputs"]] == [7, 7, 5]
        assert [item["sha256"] for item in current["outputs"][:2]] == [item["sha256"] for item in old["outputs"]]
        assert (candidate.project_dir / "raw" / source.name).read_bytes() == original
        reached.append(candidate.project_dir)
        raise NativeBoundaryReached

    monkeypatch.setattr(preparation_commands, "prepare_studio_candidate", native_boundary)
    monkeypatch.setattr(subprocess, "Popen", lambda *_a, **_k: pytest.fail("pure admission spawned native"))
    # Mirror the public owner's existing exact incoming-file capability, rather
    # than asking a selected old generation to discover an unbound new source.
    with project_runtime(store), incoming_scope(store, snapshot, source, transaction.file_inventory(source)), pytest.raises(NativeBoundaryReached):
        with source_update_staging.prepare_candidate(project, source, tmp_path / "unused-staging", worksheet=None,
                snapshot=snapshot, mapping_request={**plan["data_mapping"], "rule_id": "impact_metric", "template": "box"}):
            pytest.fail("controlled native boundary unexpectedly returned a completed figure")
    assert len(reached) == 1 and not reached[0].exists()
    assert transaction.project_inventory(project) == before and store.snapshot() == snapshot
    assert source.read_bytes() == original and not (tmp_path / "unused-staging").exists()


def test_shared_metric_predicate_does_not_expand_legacy_duplicate_header_parsing(tmp_path):
    from sciplot_core.semantic_sources.impact_sources import _is_impact_metric
    from sciplot_core.semantic_sources import impact_sources, table_scanning
    from sciplot_core.foundation.text_values import token
    for metric in ("re", "impactstrength", "冲击强度", "re1", "other", ""):
        assert _is_impact_metric(metric) == (metric == "re" or "impact" in metric or "冲击" in metric)
    source = tmp_path / "legacy.csv"
    source.write_text("Re,Re.1\nkJ/m²,kJ/m²\nAmber,Blue\n1,8\n2,9\n")
    assert token("Re.1") == "re1"
    assert impact_sources._read_candidate_tables is table_scanning._read_candidate_tables
    assert _read_impact_source(source).samples == ("Amber",)


def test_unbound_legacy_project_cannot_inherit_new_raw_group_revision_authority(bound, tmp_path, monkeypatch):
    source, _, mapping, previous = bound
    plan = mapped_plan(source, expanded(mapping), tmp_path, monkeypatch)
    previous = {key: value for key, value in previous.items() if key != "data_mapping_plan_binding"}
    with pytest.raises(ValueError, match="existing immutable raw group binding"):
        verify_replicate_source_expansion(previous, source, plan["data_mapping"], plan)
