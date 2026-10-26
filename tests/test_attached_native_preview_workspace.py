"""Native previews never write into the attached project's semantic namespace."""
from contextlib import nullcontext
from copy import deepcopy
from pathlib import Path
from sciplot_core.foundation.file_hashing import file_sha256

import pytest

from sciplot_core.project_lifecycle.backend_paths import RepositoryBackendPaths
from sciplot_core.project_lifecycle.errors import EngineError


@pytest.mark.parametrize("mode", ["sealed", "document_only", "unsealed"])
def test_attached_native_preview_uses_private_external_workspace_and_keeps_its_owner(tmp_path, mode):
    project = tmp_path / "project"
    project.mkdir()
    destination = project / ".sciplot_store/derived/preview"
    artifacts = tmp_path / "sealed-native-artifacts"
    artifacts.mkdir()
    candidate = artifacts / "after.vsz"
    candidate.write_bytes(b"sealed native candidate")

    class Repository:
        def binding_scope(self, _binding):
            return nullcontext()

        def runtime_path(self, _output):
            return destination

    class Backend:
        def preview(self, _before, _binding, _after, _diff, output):
            assert not output.exists() and not output.is_relative_to(project)
            self.workspace = output
            output.mkdir()
            image = output / "current.png"
            image.write_bytes(b"preview pixels")
            self.audit = {"status": "passed", "original_observation": str(output / "audit.json")}
            if mode == "document_only":
                return {"document_only": True, "preview": {"path": str(image), "sha256": file_sha256(image)}, "scientific_audit": deepcopy(self.audit)}
            return {"kind": "sciplot_document_edit_preview", "version": 3 if mode == "sealed" else 2,
                    "candidate": {"path": str(candidate)}, "preview": {"path": str(candidate)},
                    "review_path": str(output / "review.json"), "scientific_audit": deepcopy(self.audit)}

    backend = Backend()
    adapter = RepositoryBackendPaths(backend, Repository())
    binding = {"kind": "sciplot_veusz_binding", "_semantic_attachment_id": "a" * 32}
    if mode == "unsealed":
        with pytest.raises(EngineError) as error:
            adapter.preview({}, binding, {}, [], project / "semantic-preview")
        assert error.value.reason_code == "native_preview_owner_invalid"
    else:
        result = adapter.preview({}, binding, {}, [], project / "semantic-preview")
        assert result["scientific_audit"] == backend.audit and "review_path" not in result
        assert Path(result["preview"]["path"]).is_file()
        assert candidate.read_bytes() == b"sealed native candidate"
    assert not backend.workspace.exists()
