"""Backend compiler: complete neutral PlotIR to disposable Veusz artifacts."""

from contextlib import nullcontext
import json
from pathlib import Path
import subprocess
import sys
from typing import Any

from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.native_process import PersistentWorker, run_worker
from sciplot_core.native_process.identity import current_identity
from sciplot_core.plot_document import DocumentError
from sciplot_core.plot_backends.managed_plan import validate_capabilities
from sciplot_core.studio_core.export_execution import export_studio_document
from sciplot_core.veusz_runtime import veusz_worker_environment


def compiler_identity() -> dict[str, str]:
    # Reuse the native runtime's byte identity, including shared helpers,
    # vendored Veusz, interpreter/packages and relevant renderer environment.
    # It is build metadata, never part of scientific or PlotIR identity.
    return {"name": "sciplot.veusz.plot_ir", "version": "2", "content_hash": current_identity()}


class ManagedVeuszCompiler:
    """Own native process lifetime; data/semantic compilation is outside this boundary."""

    def __init__(self, *, warm: bool = True) -> None:
        self._worker = PersistentWorker() if warm else None

    def close(self) -> None:
        if self._worker is not None:
            self._worker.close()

    def _scope(self) -> Any:
        return self._worker.activate() if self._worker else nullcontext()

    def _run(self, arguments: list[str]) -> dict[str, Any]:
        with self._scope():
            result = run_worker([sys.executable, "-m", "sciplot_core.veusz_worker", *arguments],
                                text=True, capture_output=True, check=True, timeout=120,
                                env=veusz_worker_environment(), cold_runner=subprocess.run)
        payload: dict[str, Any] = json.loads(result.stdout)
        return payload

    def _write_ir(self, ir: dict[str, Any], output: Path) -> Path:
        from sciplot_core.plot_ir import validate_ir

        validate_ir(ir)
        validate_capabilities(ir)
        output.mkdir(parents=True, exist_ok=True)
        path = output / f"plot-ir-{ir['ir_hash']}.json"
        encoded = json.dumps(ir, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
        if path.exists() and path.read_bytes() != encoded:
            raise ValueError("Managed IR evidence file has changed.")
        if not path.exists():
            path.write_bytes(encoded)
        return path

    def compile_ir(self, ir: dict[str, Any], output: Path) -> dict[str, Any]:
        output = output.expanduser().resolve()
        ir_path = self._write_ir(ir, output)
        result = self._run(["compile-plot-ir", str(ir_path), str(output / "document.vsz"),
                            "--preview", str(output / "preview.png")])
        if result["ir_hash"] != ir["ir_hash"] or result["scientific_hash"] != ir["scientific_hash"]:
            raise ValueError("Managed compiler response does not match its requested IR identity.")
        result["compiler_identity"] = compiler_identity()
        result["evidence_files"] = {str(ir_path): file_sha256(ir_path),
                                     result["document"]: result["document_sha256"],
                                     result["preview"]["path"]: result["preview"]["sha256"]}
        return result

    def inspect_ir(self, ir: dict[str, Any], document: Path) -> dict[str, Any]:
        document = document.expanduser().resolve()
        ir_path = self._write_ir(ir, document.parent)
        result = self._run(["inspect-plot-ir", str(ir_path), str(document)])
        if result["ir_hash"] != ir["ir_hash"]:
            raise ValueError("Managed inspection response does not match its requested IR identity.")
        return result

    def _require_exact(self, ir: dict[str, Any], document: Path) -> dict[str, Any]:
        result = self.inspect_ir(ir, document)
        if result["status"] != "unchanged" or result["scientific_audit"]["status"] != "passed":
            error = DocumentError("external_mutation", "Managed native artifact differs from its canonical PlotIR.")
            error.repair = {"action": "inspect_external_mutation", "opaque_native_change": result["opaque_native_change"]}
            raise error
        if result.get("publication_qa", {}).get("status", "passed") != "passed":
            raise DocumentError("publication_qa_failed", "Managed Figure fails deterministic native publication QA.",
                                issues=result["publication_qa"].get("hard", []))
        return result

    def audit_ir(self, ir: dict[str, Any], document: Path) -> dict[str, Any]:
        return dict(self._require_exact(ir, document)["scientific_audit"])

    def export_ir(self, ir: dict[str, Any], document: Path, output: Path) -> dict[str, Any]:
        before = self._require_exact(ir, document)
        with self._scope():
            result = export_studio_document(document, formats=["pdf", "tiff_300"], output_dir=output)
        if file_sha256(document) != before["document_sha256"]:
            raise ValueError("Managed native artifact changed during export.")
        evidence = {str(document): before["document_sha256"]}
        evidence.update({record["path"]: record["sha256"] for record in result["exports"]})
        return {**result, "status": "exported", "ready_to_use": True, "evidence_files": evidence,
                "scientific_audit": before["scientific_audit"], "ir_hash": ir["ir_hash"],
                **({"publication_qa": before["publication_qa"]} if "publication_qa" in before else {})}

    def render_ir(self, ir: dict[str, Any], document: Path, output: Path) -> dict[str, Any]:
        before = self._require_exact(ir, document)
        result = self._run(["preview-document", str(document), "--out", str(output)])
        if (result["document"]["sha256"] != before["document_sha256"]
                or file_sha256(document) != before["document_sha256"]):
            raise ValueError("Managed native artifact changed between audit and preview.")
        return {**result, **({"publication_qa": before["publication_qa"]} if "publication_qa" in before else {})}
