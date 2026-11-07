"""Cold-load observations replace GUI launch checks without certifying science."""

import pytest

from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.smoke import contracts, runtime_environment


@pytest.mark.parametrize("problem", [None, "empty-data", "empty-page", "external-link", "missing-link"])
def test_relocated_native_probe_checks_every_exact_copy_and_actual_link_closure(
    tmp_path, monkeypatch, problem,
):
    package = tmp_path / "original"
    for name in ("first", "second"):
        document = package / "project" / f"{name}.vsz"
        document.parent.mkdir(parents=True, exist_ok=True)
        document.write_text(f"exact native {name}")
    source = package / "source.csv"
    source.write_text("x,y\n1,2\n")
    before = {path.relative_to(package): path.read_bytes() for path in package.rglob("*") if path.is_file()}
    observed = []

    def inspect(path):
        observed.append(path)
        payload = {
            "document": {"path": str(path.resolve()), "sha256": file_sha256(path)},
            "datasets": ["x", "y"], "pages": ["page1"],
            "linked_files": [str(path.parent.parent / "source.csv")],
        }
        if problem == "empty-data":
            payload["datasets"] = []
        elif problem == "empty-page":
            payload["pages"] = []
        elif problem == "external-link":
            payload["linked_files"] = [str(source)]
        elif problem == "missing-link":
            payload["linked_files"] = [str(path.parent.parent / "missing.csv")]
        return payload

    monkeypatch.setattr(contracts, "_inspect_veusz_document_state", inspect)
    result = runtime_environment._relocated_delivery_native_probe(
        tmp_path / "run", {"path": str(package)},
    )
    assert result["passed"] is (problem is None)
    assert len(observed) == 2 and all(path.is_relative_to(tmp_path / "run") for path in observed)
    assert result["native_copy_sha256"] == {
        f"project/{name}.vsz": file_sha256(package / "project" / f"{name}.vsz")
        for name in ("first", "second")
    }
    assert {path.relative_to(package): path.read_bytes() for path in package.rglob("*") if path.is_file()} == before


def test_native_probe_refuses_absent_link_observation_and_changed_document(tmp_path, monkeypatch):
    document = tmp_path / "saved.vsz"
    document.write_bytes(b"original")
    state = {"document": {"path": str(document), "sha256": file_sha256(document)},
             "datasets": ["x"], "pages": ["p"]}
    monkeypatch.setattr(contracts, "_inspect_veusz_document_state", lambda _path: state)
    with pytest.raises(ValueError, match="linked-source metadata"):
        runtime_environment._native_document_probe([document])
    state["linked_files"] = []

    def mutate(_path):
        document.write_bytes(b"changed during native load")
        return state

    monkeypatch.setattr(contracts, "_inspect_veusz_document_state", mutate)
    assert runtime_environment._native_document_probe([document])["passed"] is False


def test_project_native_probe_uses_all_registered_ready_documents(tmp_path, monkeypatch):
    from sciplot_core.studio_core import project_query_paths

    documents = [tmp_path / "first.vsz", tmp_path / "second.vsz"]
    for path in documents:
        path.write_bytes(b"saved native")
    monkeypatch.setattr(project_query_paths, "project_snapshot", lambda _root: (
        {}, "first", [{"document": str(path), "status": "ready"} for path in documents]
        + [{"document": str(tmp_path / "unready.vsz"), "status": "pending"}],
    ))
    observed = []

    def inspect(paths):
        observed.extend(paths)
        return {"passed": True}

    monkeypatch.setattr(runtime_environment, "_native_document_probe", inspect)
    assert runtime_environment._project_native_probe(tmp_path)["passed"]
    assert observed == documents
