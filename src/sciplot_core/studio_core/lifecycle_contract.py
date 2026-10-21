"""Public saved-VSZ lifecycle capabilities, independent of facade layout and Qt.

These ports describe supported calls and their declared authority boundaries.
Static interface availability does not certify native execution or artifacts.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class LifecyclePort:
    capability: str
    module: str
    function: str
    positional: tuple[str, ...]
    required_keywords: tuple[str, ...] = ()
    optional_keywords: tuple[str, ...] = ()
    authority: str = "saved_vsz"


VSZ_LIFECYCLE_CONTRACT_ID = "sciplot-saved-vsz-lifecycle-v1"
VSZ_LIFECYCLE_PORTS = (
    LifecyclePort("preserve_saved_document_on_open", "studio_core.studio_prepare",
                  "prepare_studio_document", ("target",),
                  optional_keywords=("regenerate_generated",)),
    LifecyclePort("export_exact_current_document", "studio_core.export_execution",
                  "export_studio_document", ("document_path",), ("formats",),
                  ("output_dir", "audit_spec_path")),
    LifecyclePort("apply_reviewed_edit_with_history", "studio_core.document_edit",
                  "apply_document_edit", ("project", "preview")),
    LifecyclePort("publish_source_bound_export", "studio_core.publish_run",
                  "publish_studio_export_run", (),
                  ("project_dir", "request_path", "document_path", "exports", "export_document_sha256"),
                  ("primary_native_audit",)),
    LifecyclePort("build_hash_bound_delivery", "delivery.package_builder",
                  "build_delivery_package", ("output_dir",), ("manifest",)),
)
