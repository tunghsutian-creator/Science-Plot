"""Ownership of the native live editor transport and its browser projection."""

from sciplot_core.verification.owner_model import ChangedOwner
from sciplot_core.verification.type_gate_owners import ARCHITECTURE_CORE_TARGETS


LIVE_EDITOR_OWNER = ChangedOwner(
    owner_id="live_native_editor",
    path_prefixes=("src/sciplot_core/live_editor/", "src/sciplot_core/live_editor_assets/", "web/editor/"),
    exact_paths=frozenset({"MANIFEST.in", "src/sciplot_core/veusz_worker/live_session.py",
                           "src/sciplot_core/cli/parsers/interfaces.py",
                           "src/sciplot_core/cli/dispatch/interfaces.py"}),
    owned_test_paths=frozenset({"tests/test_live_editor.py", "tests/test_live_native_session.py", "tests/test_live_editor_entry.py"}),
    pytest_targets=("tests/test_live_editor.py", "tests/test_live_native_session.py", "tests/test_live_editor_entry.py",
                    "tests/test_document_edit.py", "tests/test_document_edit_policy.py",
                    "tests/test_project_export_use_case.py", "tests/test_frontend_topology.py",
                    *ARCHITECTURE_CORE_TARGETS),
    mypy_required=True, handoff_gates=("doctor",), final_milestone_gates=("smoke",),
    release_gates=("full_pytest",),
)
