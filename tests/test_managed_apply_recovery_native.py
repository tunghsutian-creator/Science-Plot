"""Interrupted managed adoption cannot silently replace a manually changed base."""

import json
from pathlib import Path
import re

import pytest

from sciplot_core._paths import REPO_ROOT
from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.plot_backends.managed import ManagedVeuszCompiler
from sciplot_core.plot_engine import execution
from sciplot_core.plot_engine.service import PlotService
from sciplot_core.plot_engine.storage import active, load_head, persist
from managed_plot_helpers import patch, request_for_source
from test_plot_engine import SimulatedCrash


def _manual_marker_save(native: Path) -> str:
    changed, count = re.subn(r"Set\('markerSize', '[^']+'\)", "Set('markerSize', '19pt')", native.read_text())
    assert count == 1
    native.write_text(changed)
    return file_sha256(native)


@pytest.mark.comprehensive
@pytest.mark.parametrize(("interruption", "mutation", "succeeds"), [
    ("applying", "base", False),
    ("native_applied", "base", False),
    ("committed", "base", True),
    ("committed", "candidate", False),
    ("applying", "missing_baseline", False),
])
def test_recovery_checks_the_authoritative_native_at_each_commit_boundary(tmp_path, monkeypatch,
                                                                        interruption, mutation, succeeds):
    request = request_for_source(tmp_path)
    source = Path(request["data_binding"]["data_sources"][0]["path"])
    original_source = file_sha256(source)
    service = PlotService()
    service.backend.managed.compiler.close()
    service.backend.managed.compiler = ManagedVeuszCompiler(warm=False)
    try:
        created = service.create(request)
        assert created["ready_to_use"], created
        root = Path(created["plot"])
        base = Path(load_head(root)["binding"]["document"])
        change = patch(created, "interrupted-width", "style.line.width", "0.9pt", "series:A")
        real_apply, real_commit = service.backend.apply, execution.commit
        calls = []

        def tracked_apply(*args):
            calls.append("apply")
            if interruption == "applying":
                raise SimulatedCrash()
            return real_apply(*args)

        def interrupted_commit(*args):
            if interruption == "committed":
                real_commit(*args)
            raise SimulatedCrash()

        with monkeypatch.context() as checkpoint:
            checkpoint.setattr(service.backend, "apply", tracked_apply)
            if interruption != "applying":
                checkpoint.setattr(execution, "commit", interrupted_commit)
            with pytest.raises(SimulatedCrash):
                service.patch(root, change)
        saved = active(root)
        assert saved["phase"] == ("applying" if interruption == "applying" else "native_applied")
        assert saved["managed_base_binding"]["document"] == str(base)
        candidate = Path(saved["review"]["_managed_binding"]["document"])
        assert candidate != base
        before = load_head(root)
        assert before["document"]["revision"] == (1 if interruption == "committed" else 0)
        changed_path = None
        if mutation == "missing_baseline":
            saved.pop("managed_base_binding")
            persist(root, saved)
        else:
            changed_path = base if mutation == "base" else candidate
            manual_sha = _manual_marker_save(changed_path)

        def must_not_reapply(*_args):
            pytest.fail("Recovery must guard the base or resume commit without applying again")

        with monkeypatch.context() as recovery:
            recovery.setattr(service.backend, "apply", must_not_reapply)
            resumed = service.patch(root, change)
        assert calls == ["apply"]
        assert file_sha256(source) == original_source
        if changed_path is not None:
            assert file_sha256(changed_path) == manual_sha
        if succeeds:
            assert resumed["status"] == "complete" and resumed["ready_to_use"] is True, resumed
            assert resumed["revision"] == 1
            assert load_head(root) == before
            assert service.describe(root)["status"] == "current"
        else:
            assert resumed["status"] == "blocked" and resumed.get("ready_to_use") is not True, resumed
            assert resumed["error"]["reason_code"] == (
                "managed_recovery_baseline_missing" if mutation == "missing_baseline" else "document_inputs_changed")
            assert load_head(root) == before
            assert active(root)["phase"] == saved["phase"]
        evidence = REPO_ROOT / f".tmp_verify/managed_architecture_20261008/apply_recovery_{interruption}_{mutation}.json"
        evidence.parent.mkdir(parents=True, exist_ok=True)
        evidence.write_text(json.dumps({"status": "passed", "interruption": interruption,
            "mutation": mutation, "recovery": resumed, "source_unchanged": True,
            "manual_native_preserved": changed_path is not None,
            "head_unchanged_during_recovery": True, "no_repeat_apply": True}, indent=2))
    finally:
        service.close()
