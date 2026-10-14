"""Lifecycle availability follows public call contracts, never private facade shape."""

import builtins
from pathlib import Path

import pytest

from sciplot_core.doctor import runtime_checks
from sciplot_core.studio_core.lifecycle_contract import VSZ_LIFECYCLE_PORTS


@pytest.fixture
def source_contract(tmp_path):
    """Synthetic source interfaces deliberately do not implement native behavior."""
    for port in VSZ_LIFECYCLE_PORTS:
        path = tmp_path / (port.module.replace(".", "/") + ".py")
        path.parent.mkdir(parents=True, exist_ok=True)
        arguments = [*port.positional]
        if port.required_keywords or port.optional_keywords:
            arguments.extend(["*", *port.required_keywords])
            arguments.extend(name + "=None" for name in port.optional_keywords)
        path.write_text(f"def {port.function}({', '.join(arguments)}) -> dict:\n    raise RuntimeError('not a native runtime')\n")
    return tmp_path


@pytest.mark.parametrize("facade", ["", "obsolete_helper = object()\n", "raise RuntimeError('never import this facade')\n"])
def test_lifecycle_static_contract_survives_private_facade_removal(source_contract, facade):
    (source_contract / "studio.py").write_text(facade)
    status = runtime_checks.lifecycle_capability_status(source_root=source_contract)

    assert status["static_available"] is True
    assert status["runtime_verified"] is False
    assert status["runtime_verification"] == "not_run"
    assert status["verification_scope"] == "public_source_interfaces_only"
    assert all(port["source_sha256"] and port["interface_available"] for port in status["ports"])


@pytest.mark.parametrize("mutation", ["missing", "wrong_positional", "required_new_keyword", "missing_audit_port", "syntax"])
def test_lifecycle_contract_rejects_missing_or_incompatible_public_calls(source_contract, mutation):
    path = source_contract / "studio_core/export_execution.py"
    source = path.read_text()
    if mutation == "missing":
        path.unlink()
    elif mutation == "wrong_positional":
        path.write_text(source.replace("document_path", "unrelated_input"))
    elif mutation == "required_new_keyword":
        path.write_text(source.replace("*, formats", "*, new_required, formats"))
    elif mutation == "missing_audit_port":
        path.write_text(source.replace(", audit_spec_path=None", ""))
    else:
        path.write_text("not valid Python syntax!")
    status = runtime_checks.lifecycle_capability_status(source_root=source_contract)

    assert status["static_available"] is False
    assert status["runtime_verified"] is False
    assert status["issues"] == [{"capability": "export_exact_current_document", "reason_code": "lifecycle_interface_unavailable"}]


def test_lifecycle_contract_does_not_import_owners_or_qt(source_contract, monkeypatch):
    original_import = builtins.__import__

    def forbidden_runtime_import(name, *args, **kwargs):
        if name.startswith(("PyQt", "veusz", "sciplot_core.studio", "sciplot_core.delivery")):
            pytest.fail(f"Static lifecycle availability imported runtime owner {name}")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", forbidden_runtime_import)
    assert runtime_checks.lifecycle_capability_status(source_root=source_contract)["static_available"] is True


def test_lifecycle_status_binds_running_package_instead_of_external_repo(source_contract, monkeypatch):
    monkeypatch.setattr(runtime_checks, "PACKAGE_ROOT", source_contract)
    monkeypatch.setattr(runtime_checks, "REPO_ROOT", Path("/absent/external/runtime/repo"))

    assert runtime_checks._vsz_lifecycle_available() is True
