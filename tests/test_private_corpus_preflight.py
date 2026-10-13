"""Bounded structural diagnostics; mock bytes are not real-data acceptance."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

import sciplot_core.verification.private_corpus as corpus_module
from sciplot_core.materials_rules import iter_rules
from sciplot_core.verification.changed import build_changed_verification_plan
from sciplot_core.verification.private_corpus import (
    DIRECTORY_RULE_IDS,
    GATE,
    INVENTORY,
    private_corpus_preflight,
)
from sciplot_core.verification.private_corpus_audit import (
    implementation_sources_sha256,
    nodeids_sha256,
    test_sources_sha256 as source_digest,
)

NODE = "tests/test_registered_single_curve_figure_plan.py::test_registered_paired_curve_directory_requires_exactly_one_supported_file[2]"
PUBLIC_SIBLING = NODE.removesuffix("[2]") + "[0]"
FIXTURE = Path("tests/fixtures/real_world/uvvis_spectrum/pda_uvvis_spectra.csv")


def _inventory(tmp_path: Path, *, complete: bool, dependencies: list[dict[str, str]]) -> Path:
    path = tmp_path / "inventory.json"
    path.write_text(json.dumps({
        "kind": "sciplot_private_corpus_dependencies",
        "version": 1,
        "gate": GATE,
        "inventory_complete": complete,
        "cases": [{"nodeid": NODE, "dependencies": dependencies, "evidence": "test_fixture"}],
    }), encoding="utf-8")
    return path


def _run(tmp_path: Path, inventory: Path, *, selected: list[str] | None = None):
    return private_corpus_preflight(
        repo_root=tmp_path, inventory_path=inventory,
        selected_nodeids=selected, collected_nodeids={NODE, PUBLIC_SIBLING},
    )


def test_missing_rule_fixture_blocks_exact_selected_parameter(tmp_path: Path,
                                                              monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SCIPLOT_REFERENCE_DATA", str(tmp_path / "reference"))
    inventory = _inventory(tmp_path, complete=True, dependencies=[{"rule_id": "uvvis_spectrum"}])

    payload = _run(tmp_path, inventory, selected=[NODE])

    assert payload["status"] == "BLOCKED"
    assert payload["collection_verified"] is True
    assert payload["scientific_acceptance"] is False
    assert payload["issues"] == [{
        "gate": GATE, "code": "missing_or_invalid_fixture", "nodeid": NODE,
        "path": FIXTURE.as_posix(), "why": "required file is missing, wrong type, unreadable, or empty",
    }]


def test_nonempty_mock_only_passes_structural_declared_gate(tmp_path: Path,
                                                              monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SCIPLOT_REFERENCE_DATA", str(tmp_path / "reference"))
    source = tmp_path / "reference" / "real_world" / "uvvis_spectrum" / FIXTURE.name
    source.parent.mkdir(parents=True)
    source.write_text("test fixture, not measured data\n", encoding="utf-8")
    inventory = _inventory(tmp_path, complete=True, dependencies=[{"rule_id": "uvvis_spectrum"}])

    payload = _run(tmp_path, inventory)

    assert payload["status"] == "READY_FOR_SELECTED_TESTS"
    assert payload["declared_inputs_status"] == "present"
    assert payload["scientific_acceptance"] is False
    assert payload["cases"][0]["nodeid"] == NODE
    assert payload["cases"][0]["dependencies"] == [
        {"path": FIXTURE.as_posix(), "kind": "file", "status": "present"}
    ]


def test_preliminary_inventory_stays_blocked_even_when_mock_is_present(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SCIPLOT_REFERENCE_DATA", str(tmp_path / "reference"))
    source = tmp_path / "reference" / "real_world" / "uvvis_spectrum" / FIXTURE.name
    source.parent.mkdir(parents=True)
    source.write_bytes(b"mock")
    inventory = _inventory(tmp_path, complete=False, dependencies=[{"rule_id": "uvvis_spectrum"}])

    payload = _run(tmp_path, inventory)

    assert payload["status"] == "BLOCKED"
    assert payload["inventory_complete"] is False
    assert payload["declared_inputs_status"] == "present"
    assert [issue["code"] for issue in payload["issues"]] == ["inventory_incomplete"]


def test_mixed_param_unknown_sibling_is_not_inferred_from_module(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SCIPLOT_REFERENCE_DATA", str(tmp_path / "reference"))
    inventory = _inventory(tmp_path, complete=True, dependencies=[{"rule_id": "uvvis_spectrum"}])

    payload = _run(tmp_path, inventory, selected=[PUBLIC_SIBLING])

    assert payload["status"] == "BLOCKED"
    assert payload["cases"] == []
    assert payload["issues"][0]["code"] == "unmapped_nodeid"
    assert payload["issues"][0]["nodeid"] == PUBLIC_SIBLING


def test_unverified_or_stale_collection_blocks_even_with_mock_fixture(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SCIPLOT_REFERENCE_DATA", str(tmp_path / "reference"))
    source = tmp_path / "reference" / "real_world" / "uvvis_spectrum" / FIXTURE.name
    source.parent.mkdir(parents=True)
    source.write_bytes(b"mock")
    inventory = _inventory(tmp_path, complete=True, dependencies=[{"rule_id": "uvvis_spectrum"}])

    unverified = private_corpus_preflight(repo_root=tmp_path, inventory_path=inventory)
    stale = private_corpus_preflight(
        repo_root=tmp_path, inventory_path=inventory, collected_nodeids=set(),
    )

    assert unverified["status"] == stale["status"] == "BLOCKED"
    assert unverified["issues"][0]["code"] == "collection_unverified"
    assert stale["issues"][0]["code"] == "stale_inventory_nodeid"
    assert stale["issues"][0]["nodeid"] == NODE


@pytest.mark.parametrize("unsafe", [
    "../outside.csv", "tests/fixtures/real_world/../../outside.csv",
    "/tmp/outside.csv",
])
def test_unsafe_dependency_identifier_blocks_before_file_access(
    tmp_path: Path, unsafe: str,
) -> None:
    inventory = _inventory(tmp_path, complete=True, dependencies=[{"path": unsafe, "kind": "file"}])

    payload = _run(tmp_path, inventory)

    assert payload["status"] == "BLOCKED"
    assert payload["issues"][0]["code"] == "invalid_inventory"


def test_nodeid_module_cannot_escape_test_tree(tmp_path: Path) -> None:
    inventory = _inventory(tmp_path, complete=True, dependencies=[{"rule_id": "uvvis_spectrum"}])
    payload = json.loads(inventory.read_text(encoding="utf-8"))
    payload["cases"][0]["nodeid"] = "tests/../../outside.py::test_from_outside"
    inventory.write_text(json.dumps(payload), encoding="utf-8")

    result = _run(tmp_path, inventory)

    assert result["status"] == "BLOCKED"
    assert result["issues"][0]["code"] == "invalid_inventory"


def test_resolved_symlink_cannot_escape_fixture_roots(tmp_path: Path,
                                                     monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SCIPLOT_REFERENCE_DATA", str(tmp_path / "reference"))
    tracked = tmp_path / FIXTURE
    tracked.parent.mkdir(parents=True)
    outside = tmp_path / "outside.csv"
    outside.write_bytes(b"mock")
    tracked.symlink_to(outside)
    inventory = _inventory(tmp_path, complete=True, dependencies=[{"rule_id": "uvvis_spectrum"}])

    payload = _run(tmp_path, inventory)

    assert payload["status"] == "BLOCKED"
    assert payload["issues"][0]["code"] == "unsafe_fixture"
    assert payload["issues"][0]["path"] == FIXTURE.as_posix()


def test_fixture_resolution_io_error_is_structured_blocker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    inventory = _inventory(tmp_path, complete=True, dependencies=[{"rule_id": "uvvis_spectrum"}])

    def denied(*_args: object, **_kwargs: object) -> Path:
        raise OSError("filesystem denied")

    monkeypatch.setattr(corpus_module, "_resolved_fixture", denied)
    payload = _run(tmp_path, inventory)

    assert payload["status"] == "BLOCKED"
    assert payload["issues"][0]["code"] == "unreadable_fixture"
    assert payload["issues"][0]["path"] == FIXTURE.as_posix()


def test_wrong_type_and_empty_file_are_blocked(tmp_path: Path,
                                                monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SCIPLOT_REFERENCE_DATA", str(tmp_path / "reference"))
    source = tmp_path / "reference" / "real_world" / "uvvis_spectrum" / FIXTURE.name
    source.mkdir(parents=True)
    inventory = _inventory(tmp_path, complete=True, dependencies=[{"rule_id": "uvvis_spectrum"}])
    assert _run(tmp_path, inventory)["issues"][0]["code"] == "missing_or_invalid_fixture"
    source.rmdir()
    source.touch()
    assert _run(tmp_path, inventory)["issues"][0]["code"] == "missing_or_invalid_fixture"


def test_directory_child_symlink_escaping_corpus_is_blocked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SCIPLOT_REFERENCE_DATA", str(tmp_path / "reference"))
    directory = tmp_path / "reference" / "real_world" / "gpc_sec_chromatogram"
    directory.mkdir(parents=True)
    (directory / "safe.csv").write_bytes(b"mock")
    outside = tmp_path / "outside.csv"
    outside.write_bytes(b"mock")
    (directory / "linked.csv").symlink_to(outside)
    inventory = _inventory(
        tmp_path, complete=True,
        dependencies=[{"rule_id": "gpc_sec_chromatogram"}],
    )

    payload = _run(tmp_path, inventory)

    assert payload["status"] == "BLOCKED"
    assert payload["issues"][0]["code"] == "missing_or_invalid_fixture"
    assert payload["issues"][0]["path"] == "tests/fixtures/real_world/gpc_sec_chromatogram"


def test_provenance_member_names_are_checked_without_private_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SCIPLOT_REFERENCE_DATA", str(tmp_path / "reference"))
    path = "tests/fixtures/real_world/gpc_sec_chromatogram/source_provenance.json"
    provenance = tmp_path / "reference" / "real_world" / "gpc_sec_chromatogram" / "source_provenance.json"
    provenance.parent.mkdir(parents=True)
    provenance.write_text(json.dumps({"source_files": [{"fixture_file": "Sample A.xlsx"}]}), encoding="utf-8")
    inventory = _inventory(tmp_path, complete=True, dependencies=[
        {"path": path, "kind": "file", "listed_sources": "source_files"},
    ])

    missing = _run(tmp_path, inventory)
    assert missing["issues"][0]["path"] == "tests/fixtures/real_world/gpc_sec_chromatogram/Sample A.xlsx"
    (provenance.parent / "Sample A.xlsx").write_bytes(b"mock")
    present = _run(tmp_path, inventory)
    assert present["status"] == "READY_FOR_SELECTED_TESTS"
    provenance.write_text(json.dumps({"source_files": [{"fixture_file": "../../outside.xlsx"}]}), encoding="utf-8")
    assert _run(tmp_path, inventory)["issues"][0]["code"] == "unsafe_source_member"


def test_checked_in_inventory_is_explicitly_preliminary() -> None:
    payload = json.loads(INVENTORY.read_text(encoding="utf-8"))
    nodeids = [case["nodeid"] for case in payload["cases"]]
    assert payload["inventory_complete"] is False
    assert len(nodeids) == len(set(nodeids))
    assert NODE in nodeids and PUBLIC_SIBLING not in nodeids
    assert any(case["evidence"] == "test_source_inspection" for case in payload["cases"])


def test_cli_collection_failure_is_json_blocked_and_nonzero(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    def failed_collection(*_args: object, **_kwargs: object) -> set[str]:
        raise ValueError("collection failed")

    monkeypatch.setattr(corpus_module, "_collect_nodeids", failed_collection)
    exit_code = corpus_module.main(["--repo-root", str(tmp_path), "--json"])
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 1
    assert payload["status"] == "BLOCKED"
    assert payload["issues"][0]["code"] == "invalid_input_or_collection"
    assert "collection failed" in payload["issues"][0]["why"]


def test_cli_without_source_checkout_inventory_blocks_clearly(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(corpus_module, "INVENTORY", tmp_path / "not-packaged.json")

    exit_code = corpus_module.main(["--repo-root", str(tmp_path), "--json"])
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 1
    assert payload["status"] == "BLOCKED"
    assert "source checkout" in payload["issues"][0]["why"]


def test_directory_rule_kind_catalog_matches_declared_fixture_shape() -> None:
    ready = [rule for rule in iter_rules() if rule.fixture_status == "ready"]
    for rule in ready:
        path = Path(str(rule.fixture_path))
        assert path.parts[:3] == ("tests", "fixtures", "real_world")
        if rule.rule_id in DIRECTORY_RULE_IDS:
            assert path.suffix == "" or path.name.endswith(".is_tens_Exports")
        else:
            assert path.suffix.lower() in {".csv", ".xlsx"}


def test_preflight_files_have_changed_owner_and_focused_target() -> None:
    root = Path(__file__).resolve().parents[1]
    for path in (
        "src/sciplot_core/verification/private_corpus.py",
        "src/sciplot_core/verification/private_corpus_audit.py",
        "src/sciplot_core/verification/private_corpus_inventory.json",
        "tests/test_private_corpus_preflight.py",
    ):
        plan = build_changed_verification_plan([path], repo_root=root)
        assert plan["unowned_paths"] == []
        assert "changed_verification" in {owner["owner_id"] for owner in plan["owners"]}
        selected = next(check["command"] for check in plan["checks"]
                        if check["check_id"] == "pytest_changed_owners")
        assert "tests/test_private_corpus_preflight.py" in selected


def _review_and_receipt(tmp_path: Path, inventory: Path) -> Path:
    nodes = {NODE, PUBLIC_SIBLING}
    payload = json.loads(inventory.read_text())
    payload["collection_audit"] = {
        "static_review_complete": True, "nodeid_count": len(nodes),
        "nodeids_sha256": nodeids_sha256(nodes), "test_sources_sha256": source_digest(tmp_path),
        "candidate_nodeids": sorted(nodes),
        "synthetic_candidates": [{"nodeid": PUBLIC_SIBLING, "reason": "zero-copy branch"}],
    }
    inventory.write_text(json.dumps(payload))
    path = tmp_path / "access-audit.json"
    path.write_text(json.dumps({
        "kind": "sciplot_private_corpus_access_audit", "version": 1,
        "inventory_sha256": hashlib.sha256(inventory.read_bytes()).hexdigest(),
        "test_sources_sha256": source_digest(tmp_path),
        "implementation_sources_sha256": implementation_sources_sha256(tmp_path),
        "capture_complete": True,
        "capture_scope": ["python.open", "python.os.scandir", "python.os.listdir", "static.fixture_dependencies"],
        "collected_nodeids": sorted(nodes), "executed_nodeids": sorted(nodes),
        "events": [{"nodeid": NODE, "path": FIXTURE.as_posix(), "event": "open"}],
    }))
    return path


@pytest.mark.parametrize("mutation", [
    "none", "subset", "inventory_drift", "unmapped", "escape", "capture_incomplete",
])
def test_complete_inventory_requires_bound_full_access_evidence(
    tmp_path: Path, mutation: str, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SCIPLOT_REFERENCE_DATA", str(tmp_path / "reference"))
    source = tmp_path / "reference" / "real_world" / "uvvis_spectrum" / FIXTURE.name
    source.parent.mkdir(parents=True)
    source.write_bytes(b"mock structural input only")
    inventory = _inventory(tmp_path, complete=False, dependencies=[{"rule_id": "uvvis_spectrum"}])
    receipt_path = _review_and_receipt(tmp_path, inventory)
    receipt = json.loads(receipt_path.read_text())
    if mutation == "subset":
        receipt["executed_nodeids"] = [NODE]
    elif mutation == "inventory_drift":
        receipt["inventory_sha256"] = "0" * 64
    elif mutation == "unmapped":
        receipt["events"][0]["nodeid"] = PUBLIC_SIBLING
    elif mutation == "escape":
        receipt["events"][0]["path"] = "tests/fixtures/real_world/../../outside.csv"
    elif mutation == "capture_incomplete":
        receipt["capture_complete"] = False
    receipt_path.write_text(json.dumps(receipt))
    result = private_corpus_preflight(
        repo_root=tmp_path, inventory_path=inventory, collected_nodeids={NODE, PUBLIC_SIBLING},
        access_audit_path=receipt_path,
    )
    assert (result["status"] == "READY_FOR_SELECTED_TESTS") is (mutation == "none")
    assert result["scientific_acceptance"] is False


def test_profile_manifest_members_are_checked_before_native_execution(tmp_path: Path) -> None:
    relative = "tests/fixtures/rendering_profiles/profile/manifest.json"
    manifest = tmp_path / relative
    manifest.parent.mkdir(parents=True)
    manifest.write_text(json.dumps({"files": {"raw": {"path": "raw/data.csv", "sha256": "a" * 64}}}))
    inventory = _inventory(tmp_path, complete=True, dependencies=[
        {"path": relative, "kind": "file", "listed_sources": "profile_files"},
    ])
    missing = _run(tmp_path, inventory)
    assert missing["issues"][0]["path"] == "tests/fixtures/rendering_profiles/profile/raw/data.csv"
    (manifest.parent / "raw").mkdir()
    (manifest.parent / "raw/data.csv").write_bytes(b"mock")
    assert _run(tmp_path, inventory)["status"] == "READY_FOR_SELECTED_TESTS"
    (manifest.parent / "raw/data.csv").unlink()
    outside = tmp_path / "outside.csv"
    outside.write_bytes(b"mock")
    (manifest.parent / "raw/data.csv").symlink_to(outside)
    assert _run(tmp_path, inventory)["status"] == "BLOCKED"
