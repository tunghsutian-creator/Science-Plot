"""The native adapter returns the completed candidate hash expected by backends."""
from test_native_project_commands import edit as edit
from test_project_query import project as project

from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.project_commands import ProjectCommands
from sciplot_core.studio_core import document_edit
from sciplot_core.studio_core.project_command_scope import project_store


def test_completed_native_apply_reports_current_hash_on_first_and_replayed_result(edit):
    project, document, review, calls = edit
    result = document_edit.apply_document_edit(project, review)
    assert result["document_sha256"] == result["result_sha256"] == file_sha256(document)
    assert result["document_sha256"] != review["document_sha256"]
    replayed = document_edit.apply_document_edit(project, review)
    assert replayed["document_sha256"] == result["document_sha256"]
    assert replayed["status"] == "already_applied" and len(calls) == 1
    saved = ProjectCommands(project_store(project)).query(review["operation_id"])
    assert saved["result"]["result_sha256"] == result["document_sha256"]
    assert "document_sha256" not in saved["result"]
