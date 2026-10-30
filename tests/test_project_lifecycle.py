"""Single-owner lifecycle, injected repositories and old-format counterexamples."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import nullcontext
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
import hashlib
from fnmatch import fnmatch
from threading import Barrier

import pytest

from managed_plot_helpers import patch, request_for_source
from test_plot_engine import FakeBackend, request

from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.plot_document import seal_document
from sciplot_core.plot_engine.managed_state import make_binding
from sciplot_core.plot_engine.managed_backend import fingerprint_input_roles
from sciplot_core.project_lifecycle.application import ProjectApplication
from sciplot_core.project_lifecycle.capabilities import COMPATIBILITY_CAPABILITIES
from sciplot_core.project_lifecycle.context import repository, repository_scope
from sciplot_core.project_lifecycle.contracts import AuthorityMode, NormalizedCommand, Receipt, RevisionToken
from sciplot_core.project_lifecycle.repository import FileProjectRepository, transaction_path
from sciplot_core.project_lifecycle.target_adapter import FilesystemProjectTargets


class MemoryRepository(FileProjectRepository):
    """A fake storage adapter; head, revisions and journals never reach disk."""
    def __init__(self):
        super().__init__(lease=lambda _: nullcontext())
        self.values = {}
        self.content = {}
        self.writes = []

    def exists(self, path):
        return str(path) in self.values or str(path) in self.content or path.exists()

    def read(self, path):
        return deepcopy(self.values[str(path)])

    def write(self, path, payload):
        self.writes.append(str(path))
        self.values[str(path)] = deepcopy(payload)

    def content_snapshot(self, path):
        payload = self.content.get(str(path))
        if payload is None:
            raise FileNotFoundError(path)
        return {"bytes": payload, "sha256": hashlib.sha256(payload).hexdigest(), "identity": {"size": len(payload)}}

    def publish_content(self, path, payload, verify_existing):
        if str(path) in self.content:
            verify_existing()
        else:
            self.content[str(path)] = bytes(payload)

    def json_members(self, directory, pattern):
        return sorted(Path(path) for path in self.values if Path(path).parent == directory and fnmatch(Path(path).name, pattern))


class ManagedBackend:
    """Resolved IR and science are real; the native/render adapter is synthetic."""
    def __init__(self):
        self.calls = {"preview": 0, "apply": 0, "export": 0}
        self.fail_export = False

    def fingerprint(self, binding, *, input_document=None):
        if input_document is not None:
            fingerprint_input_roles(binding, input_document=input_document)
        return {"files": {path: file_sha256(Path(path)) for path in binding["fingerprint"]["files"]},
                "artifacts": binding["fingerprint"]["artifacts"]}

    def preview(self, before, binding, document, diff, output):
        self.calls["preview"] += 1
        candidate = make_binding(Path(binding["root"]), document, output=Path(binding["output"]))
        return {"scientific_audit": {"status": "passed"}, "_binding": candidate}

    def apply(self, binding, review):
        self.calls["apply"] += 1
        candidate = review["_binding"]
        native = Path(candidate["document"])
        native.parent.mkdir(parents=True, exist_ok=True)
        native.write_bytes(candidate["ir_hash"].encode())
        return {"_binding": candidate}

    def refresh_binding(self, binding, result):
        return result["_binding"]

    def export(self, binding):
        self.calls["export"] += 1
        if self.fail_export:
            raise RuntimeError("synthetic export interruption")
        native = Path(binding["document"])
        native.parent.mkdir(parents=True, exist_ok=True)
        native.write_bytes(binding["ir_hash"].encode())
        artifact = native.parent / "figure.pdf"
        artifact.write_bytes(b"synthetic export " + native.read_bytes())
        return {"ready_to_use": True, "exports": [{"path": str(artifact)}]}


def application(backend, repo):
    return ProjectApplication(backend, repo, targets=FilesystemProjectTargets(repo, resolve_figure=lambda target, _: {
        "project": str(target), "figure_id": "primary"}), capabilities=COMPATIBILITY_CAPABILITIES)


def test_managed_entire_lifecycle_uses_only_injected_repository(tmp_path, monkeypatch):
    repo, backend = MemoryRepository(), ManagedBackend()
    app = application(backend, repo)
    wire = request_for_source(tmp_path)
    source = Path(wire["data_binding"]["data_sources"][0]["path"])
    original = source.read_bytes()
    monkeypatch.setattr(FileProjectRepository, "write", lambda *_: pytest.fail("a second repository wrote state"))
    created = app.create(wire)
    root = Path(created["plot"])
    head = repo.load_head(root)
    science = head["document"]["scientific_hash"]
    assert created["ready_to_use"] and created["revision"] == 0
    assert app.open(root)["revision_token"]["authority"] == "managed"
    edited = app.patch(root, patch(created, "style", "style.line.width", "1.2pt", "series:A"))
    assert edited["revision"] == 1 and edited["scientific_hash"] == science
    reviewed = app.rollback(root, {"base_revision": 1, "target_revision": 0, "idempotency_key": "undo"})
    assert reviewed["status"] == "needs_review"
    assert repo.load_head(root)["document"]["revision"] == 1
    app = application(backend, repo)
    undone = app.decide(root, reviewed["next_step"]["request"])
    assert undone["revision"] == 2 and undone["ready_to_use"]
    after = repo.load_head(root)["document"]
    assert after["presentation"] == head["document"]["presentation"]
    assert after["scientific_hash"] == science and source.read_bytes() == original
    receipt = Receipt.of(repo.read(transaction_path(root, "undo")))
    assert receipt.revision.authority == AuthorityMode.MANAGED and receipt.recovery.committed
    app = application(backend, repo)
    assert app.export(root)["revision"] == 2
    assert any(path.endswith("/head.json") for path in repo.writes)
    assert any(path.endswith("/managed-creation.json") for path in repo.writes)
    assert any("/revisions/" in path for path in repo.writes)
    assert any(path.endswith("/transaction.json") for path in repo.writes)
    assert not list(root.rglob("head.json")) and not list(root.rglob("transaction.json"))


def test_export_only_resume_does_not_repeat_adopted_semantic_change(tmp_path):
    repo, backend = MemoryRepository(), ManagedBackend()
    app = application(backend, repo)
    created = app.create(request_for_source(tmp_path))
    root = Path(created["plot"])
    backend.fail_export = True
    wire = patch(created, "style", "style.line.width", "1.2pt", "series:A")
    result = app.patch(root, wire)
    assert result["commit_status"] == "committed" and result["export_status"] == "pending"
    assert repo.load_head(root)["document"]["revision"] == 1
    backend.fail_export = False
    restarted = application(backend, repo)
    assert restarted.resume(root, {key: wire[key] for key in ("plot_id", "base_revision", "idempotency_key")})["ready_to_use"]
    assert backend.calls["apply"] == backend.calls["preview"] == 1


def test_tagged_command_rejects_wrong_authority_and_cross_usecase_key(tmp_path):
    backend, repo = FakeBackend(tmp_path / "native"), MemoryRepository()
    root = tmp_path / "plot"
    doc, binding = backend.initial()
    repo.commit(root, doc, binding, "import")
    app = application(backend, repo)
    token = RevisionToken.of(doc)
    wrong = replace(token, authority=AuthorityMode.MANAGED)
    with pytest.raises(ValueError, match="token"):
        app.execute(root, NormalizedCommand.create("patch", request(), expected_revision=wrong))
    assert backend.calls["preview"] == 0
    assert app.execute(root, NormalizedCommand.create("patch", request(), expected_revision=token))["ready_to_use"]
    with pytest.raises(ValueError):
        app.rollback(root, {"base_revision": 0, "target_revision": 0, "idempotency_key": "edit-1"})
    assert backend.native_writes == 1


def test_two_concurrent_applications_and_exception_reset_keep_repositories_separate(tmp_path):
    barrier = Barrier(2)
    repos = [MemoryRepository(), MemoryRepository()]
    apps = []
    for index, repo in enumerate(repos):
        backend = FakeBackend(tmp_path / str(index))
        doc, binding = backend.initial()
        root = tmp_path / ("plot" + str(index))
        repo.commit(root, doc, binding, "import")
        original = backend.preview
        def preview(*args, operation=original, selected=repo):
            barrier.wait(timeout=5)
            assert repository() is selected
            return operation(*args)
        backend.preview = preview
        apps.append((application(backend, repo), root))
    with ThreadPoolExecutor(2) as executor:
        futures = [executor.submit(app.patch, root, request()) for app, root in apps]
        assert [future.result()["revision"] for future in futures] == [1, 1]
    assert not set(repos[0].writes) & set(repos[1].writes)
    with repository_scope(repos[0]):
        with pytest.raises(ValueError):
            apps[1][0].patch(apps[1][1], request(key="bad", revision=100))
        assert repository() is repos[0]
    assert repository() not in repos


def test_old_completed_record_replays_without_rewriting_original_journal(tmp_path):
    backend = FakeBackend(tmp_path / "native")
    repo = FileProjectRepository(lease=lambda _: nullcontext())
    doc, binding = backend.initial()
    root = tmp_path / "plot"
    repo.commit(root, doc, binding, "import")
    app = application(backend, repo)
    result = app.patch(root, request())
    journal = transaction_path(root, "edit-1")
    old = repo.read(journal)
    old.pop("normalized_command")
    repo.write(journal, old)  # Materialize the pre-migration journal format.
    snapshot = journal.read_bytes()
    head_bytes = (root / "head.json").read_bytes()
    restarted = application(backend, repo)
    assert restarted.patch(root, request())["replayed"]
    assert journal.read_bytes() == snapshot and (root / "head.json").read_bytes() == head_bytes
    assert restarted.describe(root)["revision"] == result["revision"]
    assert journal.read_bytes() == snapshot and backend.native_writes == 1


@pytest.mark.parametrize("corruption", ["membership", "column", "unit"])
def test_repository_rejects_resealed_inconsistent_managed_aggregate_before_commit(tmp_path, corruption):
    repo, backend = MemoryRepository(), ManagedBackend()
    app = application(backend, repo)
    created = app.create(request_for_source(tmp_path))
    root = Path(created["plot"])
    prior = repo.load_head(root)
    document = deepcopy(prior["document"])
    document["revision"] += 1
    science = document["scientific"]
    if corruption == "membership":
        science["provenance"]["datasets"].pop("A")
    elif corruption == "column":
        science["mappings"]["series:A"]["x"]["column"] = "unbound"
    else:
        science["mappings"]["series:A"]["x_unit"] = "kg"
    before = deepcopy(repo.values)
    with pytest.raises(ValueError):
        repo.commit(root, seal_document(document), prior["binding"], "invalid")
    assert repo.values == before and repo.load_head(root) == prior


def test_legacy_import_and_readers_use_injected_repository(tmp_path, monkeypatch):
    backend, repo = FakeBackend(tmp_path / "legacy"), MemoryRepository()
    app = application(backend, repo)
    monkeypatch.setattr(FileProjectRepository, "write", lambda *_: pytest.fail("default writer used"))
    description = app.open(backend.directory)
    root = Path(description["plot"])
    assert description["revision_token"]["authority"] == "legacy_native"
    assert description["coverage"]["mode"] == "legacy_shadow"
    assert repo.load_head(root)["transaction"] == "import"
    assert app.patch(root, request())["revision"] == 1
    assert not (root / "head.json").exists()


def test_compatibility_modules_contain_no_retained_state_machine_or_writer():
    import ast
    import subprocess
    import sys

    source = Path(__file__).resolve().parents[1] / "src/sciplot_core"
    retired = ("creation", "creation_results", "execution", "exports", "managed_creation",
               "managed_rollback", "publication_repair", "receipts", "recovery", "reimport", "template_creation", "storage")
    for module in retired:
        tree = ast.parse((source / "plot_engine" / (module + ".py")).read_text())
        assert not any(isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) for node in ast.walk(tree))
    completed = subprocess.run([sys.executable, "-c", "import sys; from sciplot_core.project_lifecycle.application import ProjectApplication; "
        "assert not any(m.startswith(('PySide', 'veusz', 'sciplot_core.plot_backends')) for m in sys.modules)"],
        capture_output=True, text=True, check=False)
    assert completed.returncode == 0, completed.stderr


def test_large_scientific_content_lifecycle_never_escapes_injected_repository(tmp_path, monkeypatch):
    from sciplot_core.project_lifecycle import file_content

    monkeypatch.setattr(file_content, "read_snapshot", lambda *_: pytest.fail("default filesystem blob read"))
    monkeypatch.setattr(file_content, "publish", lambda *_: pytest.fail("default filesystem blob write"))
    repo, backend = MemoryRepository(), ManagedBackend()
    app = application(backend, repo)
    wire = request_for_source(tmp_path)
    source = Path(wire["data_binding"]["data_sources"][0]["path"])
    source.write_text("Time,Signal\ns,V\n" + "".join(f"{i / 6000},{2 + i % 7}\n" for i in range(12000)))
    wire["data_binding"]["data_sources"][0].update(sha256=file_sha256(source))
    wire["data_binding"]["data_sources"][0]["table_selection"]["data_end_row"] = 12002
    created = app.create(wire)
    root = Path(created["plot"])
    assert not (root / "content").exists(), "scientific CAS escaped the injected repository"
    assert repo.load_head(root)["document"]["scientific"]["provenance"]["datasets"]["kind"] == "sciplot_content_reference"
    edited = app.patch(root, patch(created, "large-style", "style.line.width", "1.2pt", "series:A"))
    reopened = application(backend, repo).open(root)
    assert edited["ready_to_use"] and reopened["revision"] == 1
    assert reopened["scientific_hash"] == created["scientific_hash"]
    assert not (root / "content").exists()


def test_legacy_inverse_rollback_decision_and_same_key_retry(tmp_path):
    backend, repo = FakeBackend(tmp_path / "legacy"), MemoryRepository()
    root = tmp_path / "plot"
    original, binding = backend.initial()
    repo.commit(root, original, binding, "import")
    app = application(backend, repo)
    changed = app.patch(root, request(changes=[{"op": "set", "target": ["title:main"],
        "property": "title.text", "value": "Edited title"}]))
    assert app.decide(root, changed["next_step"]["request"])["revision"] == 1
    wire = {"base_revision": 1, "target_revision": 0, "idempotency_key": "legacy-undo"}
    review = app.rollback(root, wire)
    assert review["status"] == "needs_review" and backend.native_writes == 1
    saved = repo.read(transaction_path(root, "legacy-undo"))
    assert saved["request"] != wire and saved["rollback_request"] == wire
    finished = application(backend, repo).decide(root, review["next_step"]["request"])
    assert finished["revision"] == 2 and finished["scientific_hash"] == original["scientific_hash"]
    assert repo.load_head(root)["document"]["presentation"] == original["presentation"]
    assert app.rollback(root, wire)["replayed"]
    assert app.decide(root, review["next_step"]["request"])["replayed"]
    assert backend.native_writes == 2


def test_task_edit_keeps_semantic_reads_on_injected_service_repository(tmp_path, monkeypatch):
    from sciplot_core import task_common_edits

    repo, backend = MemoryRepository(), ManagedBackend()
    app = application(backend, repo)
    created = app.create(request_for_source(tmp_path))
    root = Path(created["plot"])
    monkeypatch.setattr(task_common_edits, "doctor_payload", lambda: {"kind": "sciplot_doctor", "status": "ready", "checks": []})
    edited = task_common_edits.edit_task(root, task_dir=tmp_path / "task-entry", font_size="9pt", service=app)
    assert edited["ready_to_use"] and edited["revision"] == 1
    assert repo.load_head(root)["document"]["revision"] == 1 and not (root / "head.json").exists()


def test_task_style_checkpoint_is_filesystem_but_semantic_state_uses_injected_owner(tmp_path, monkeypatch):
    from sciplot_core.plot_engine import compat

    backend, repo = FakeBackend(tmp_path / "legacy"), MemoryRepository()
    root = tmp_path / "plot"
    document, binding = backend.initial()
    repo.commit(root, document, binding, "import")
    app = application(backend, repo)
    monkeypatch.setattr(compat, "PlotService", lambda: app)
    entry = tmp_path / "style-checkpoint"
    arguments = {"samples": None, "all_samples": True, "style": {"width": "0.7pt"}, "figure_id": None, "task_dir": entry}
    first = compat.migrated_style(root, **arguments)
    assert first["ready_to_use"] and (entry / "semantic-style.json").is_file()
    assert compat.migrated_style(root, **arguments)["replayed"]
    assert repo.load_head(root)["document"]["revision"] == 1 and not (root / "head.json").exists()
    assert backend.native_writes == 1


def test_delivery_checkpoint_cache_and_lease_use_injected_repository(tmp_path):
    repo, backend = MemoryRepository(), ManagedBackend()
    app = application(backend, repo)
    created = app.create(request_for_source(tmp_path))
    plot = Path(created["plot"])
    assert not (plot / "export-cache.json").exists()
    wire = {"idempotency_key": "delivery", "out": str(tmp_path / "delivery"), "title": "Synthetic",
            "mode": "native_snapshot", "items": [{"plot": str(plot), "plot_id": created["plot_id"], "revision": 0, "label": "A"}]}
    for _ in range(2):
        result = app.deliver(wire)
        # The fake render adapter deliberately supplies no audited native seal;
        # its semantic cache was nevertheless found in the injected repository.
        assert result["status"] == "partial"
        assert result["items"][0]["error"]["reason_code"] == "managed_delivery_native_unsealed"
    checkpoint = Path(result["checkpoint"])
    assert str(checkpoint / "delivery.json") in repo.values and not (checkpoint / "delivery.json").exists()
    assert not (checkpoint.parent / ".sciplot_session_locks").exists()
