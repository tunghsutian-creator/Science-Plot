"""Adapt full managed compilation to the existing durable transaction interface."""

from copy import deepcopy
from pathlib import Path
from typing import Any
from uuid import uuid4

from sciplot_core.foundation.file_hashing import existing_file_sha256, file_sha256
from sciplot_core.plot_backends.managed import ManagedVeuszCompiler, compiler_identity

from .errors import EngineError
from .managed_state import make_binding, read_canonical, require_inputs, resolved_ir
from .storage import read, write


class ManagedBackend:
    def __init__(self) -> None:
        self.compiler = ManagedVeuszCompiler()

    def close(self) -> None:
        self.compiler.close()

    def _owned_intent(self, binding: dict[str, Any]) -> dict[str, Any] | None:
        native = Path(binding["document"])
        path, marker = native.parent / "compile-intent.json", native.parent / "build.json"
        if not path.exists():
            return None
        value = read(path)
        expected = {"ir_hash": binding["ir_hash"], "canonical_sha256": binding["canonical_sha256"],
                    "compiler_identity": compiler_identity()}
        if any(value.get(key) != item for key, item in expected.items()) or not value.get("compile_id"):
            return None
        if marker.exists() and read(marker).get("compile_id") == value["compile_id"]:
            return None
        return value

    def fingerprint(self, binding: dict[str, Any]) -> dict[str, Any]:
        files = {name: existing_file_sha256(Path(name)) for name in binding["fingerprint"]["files"]}
        native = Path(binding["document"])
        expected = binding["ir_hash"]
        if native.exists():
            marker = native.parent / "build.json"
            if not marker.exists():
                expected = binding["ir_hash"] if self._owned_intent(binding) else "untracked_native_artifact"
            else:
                record = read(marker)
                if record.get("ir_hash") != binding["ir_hash"] or record.get("document_sha256") != file_sha256(native):
                    expected = binding["ir_hash"] if self._owned_intent(binding) else "external_native_mutation"
        return {"files": files, "artifacts": {str(native): expected}}

    def _ensure(self, binding: dict[str, Any]) -> tuple[dict[str, Any], Path]:
        canonical = read_canonical(binding)
        require_inputs(canonical)
        root = Path(binding["root"])
        # Re-resolve IR from canonical state even if all generated files vanished.
        ir = resolved_ir(root, canonical)
        if ir["ir_hash"] != binding["ir_hash"]:
            raise EngineError("managed_ir_conflict", "Canonical state does not reproduce the bound PlotIR identity.")
        ir_path = Path(binding["ir_path"])
        if not ir_path.exists():
            write(ir_path, ir)
        native = Path(binding["document"])
        marker = native.parent / "build.json"
        intent = self._owned_intent(binding)
        rebuild = not native.exists()
        if native.exists():
            if self.fingerprint(binding) != binding["fingerprint"]:
                raise EngineError("managed_external_mutation", "An existing managed artifact changed outside its document.",
                                  action="inspect_external_mutation")
            record = read(marker) if marker.exists() else None
            # A known previous compiler product can be discarded on compiler
            # version change, after its own byte seal excludes manual edits.
            rebuild = bool(record and record.get("compiler_identity") != compiler_identity()
                           and record.get("document_sha256") == existing_file_sha256(native))
            if intent or not rebuild:
                inspected = self.compiler.inspect_ir(ir, native)
                exact = inspected["status"] == "unchanged" and inspected["scientific_audit"]["status"] == "passed"
                if not exact and not rebuild:
                    raise EngineError("managed_external_mutation", "Existing native state does not exactly reproduce its canonical PlotIR.")
                if exact:
                    rebuild = False
                if intent and exact:
                    write(marker, {"ir_hash": ir["ir_hash"], "document_sha256": inspected["document_sha256"],
                          "native_state_hash": inspected["native_state_hash"], "compiler_identity": compiler_identity(),
                          "compile_id": intent["compile_id"]})
        if rebuild:
            intent = {"ir_hash": binding["ir_hash"], "canonical_sha256": binding["canonical_sha256"],
                      "compiler_identity": compiler_identity(), "compile_id": uuid4().hex}
            write(native.parent / "compile-intent.json", intent)
            if native.exists():
                previous = read(marker)
                if previous.get("document_sha256") != file_sha256(native):
                    raise EngineError("managed_external_mutation", "The previous compiler product changed before rebuild.")
                # This exact byte-sealed, obsolete compiler product is disposable.
                # The durable intent makes interruption before or after deletion recoverable.
                native.unlink()
            built = self.compiler.compile_ir(ir, native.parent)
            write(marker, {"ir_hash": ir["ir_hash"], "document_sha256": built["document_sha256"],
                  "native_state_hash": built["native_state_hash"], "compiler_identity": built["compiler_identity"],
                  "compile_id": intent["compile_id"]})
        require_inputs(canonical)
        return ir, native

    def preview(self, document: dict[str, Any], binding: dict[str, Any], new_document: dict[str, Any],
                diff: list[dict[str, Any]], output: Path) -> dict[str, Any]:
        candidate = make_binding(Path(binding["root"]), new_document, output=Path(binding["output"]))
        ir, native = self._ensure(candidate)
        output.mkdir(parents=True, exist_ok=True)
        preview = self.compiler.render_ir(ir, native, output / "preview.png")
        return {"scientific_audit": self.compiler.audit_ir(ir, native), "preview": preview.get("preview", preview),
                "_managed_binding": candidate}

    def apply(self, binding: dict[str, Any], review: dict[str, Any]) -> dict[str, Any]:
        candidate = review["_managed_binding"]
        self._ensure(candidate)
        return {"status": "adopted_managed_artifact", "_managed_binding": deepcopy(candidate)}

    def refresh_binding(self, binding: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
        return dict(result["_managed_binding"])

    def export(self, binding: dict[str, Any]) -> dict[str, Any]:
        ir, native = self._ensure(binding)
        result = self.compiler.export_ir(ir, native, native.parent / "exports")
        result["exports"].append({"path": str(native), "format": "vsz", "sha256": file_sha256(native)})
        return result

    def render(self, binding: dict[str, Any], output: Path) -> dict[str, Any]:
        ir, native = self._ensure(binding)
        output.mkdir(parents=True, exist_ok=True)
        return self.compiler.render_ir(ir, native, output / "preview.png")
