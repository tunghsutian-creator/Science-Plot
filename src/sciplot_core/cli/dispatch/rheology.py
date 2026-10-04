"""Dispatch explicit rheology analysis without an internal model."""

import json
from pathlib import Path
from typing import Any

from sciplot_core.cli.value_io import _print_json


def _requires_full_evidence(value: Any) -> bool:
    """Keep uncertain or failed native evidence intact, including nested checks."""
    if isinstance(value, list):
        return any(_requires_full_evidence(item) for item in value)
    if not isinstance(value, dict):
        return False
    for key, item in value.items():
        if key == "status" and item not in ("ready", "completed", "passed", "matched"):
            return True
        if key in {"matches", "template_match", "exists"} and item is not True:
            return True
        if any(word in key for word in ("error", "warning", "failure", "failed", "differences")) and item:
            return True
        if _requires_full_evidence(item):
            return True
    return False


def _compact_creation_result(result: dict[str, Any]) -> dict[str, Any]:
    """Project only fresh creation receipts; full evidence stays with its owner."""
    native = result.get("native_result")
    if (result.get("status") != "ready" or not isinstance(native, dict)
            or native.get("status") != "completed" or _requires_full_evidence(native)):
        return result
    try:
        evidence_path = Path(result["workspace"]) / "suite.json"
        manifest = json.loads(evidence_path.read_text(encoding="utf-8"))
        if (manifest["native_result"] != native or manifest["delivery"] != result["delivery"]
                or manifest["workspace"] != result["workspace"]):
            raise ValueError("Saved manifest no longer matches this creation result.")
        receipts = {item["id"]: item for item in native["figures"]}
        documents = manifest["documents"]
        if (len(receipts) != len(native["figures"]) or len(documents) != result["figures"]
                or [item["id"] for item in documents] != [item["id"] for item in native["figures"]]):
            raise ValueError("Saved figure identities no longer match this creation result.")
        figures = []
        audit_scopes = []
        for document in documents:
            receipt = receipts[document["id"]]
            if document["sha256"] != receipt["document_sha256"]:
                raise ValueError("Saved document revisions no longer match this creation result.")
            audit = receipt["native_audit"]
            if audit["status"] != "passed":
                return result
            if audit["scope"] not in audit_scopes:
                audit_scopes.append(audit["scope"])
            images = {Path(path).suffix: path for path in document["exports"]}
            figures.append({"id": document["id"], "document": document["path"],
                "document_sha256": document["sha256"], "preview": images[".png"],
                "tiff": images[".tiff"], "native_audit_status": audit["status"]})
        index = Path(result["delivery"]) / "index.html"
        index_exists = index.is_file()
    except (OSError, ValueError, KeyError, TypeError) as exc:
        # Creation already succeeded. A presentation fallback must not invite a
        # second creation or hide its original evidence behind a CLI failure.
        return {**result, "compact_unavailable": str(exc)}
    review = {"scope": "Creation snapshot; review exports before delivery. Use a fresh style-preview for later style edits; saved VSZ remains authority.",
              "figures": figures}
    if index_exists:
        review["index"] = str(index)
    return {key: value for key, value in result.items() if key != "native_result"} | {
        "native_status": native["status"], "full_evidence_path": str(evidence_path),
        "native_audit": {"status": "passed", "scopes": audit_scopes},
        "review": review,
    }


def dispatch_rheology(args: Any) -> int | None:
    if args.command != "rheology":
        return None
    from sciplot_core.workflow.rheology_tts_suite import create_suite, export_suite

    if args.rheology_command == "plot":
        from sciplot_core.workflow.rheology_tts_prepared import plot_prepared_suite
        result = (plot_prepared_suite(args.request, resume=True) if getattr(args, "resume", False)
                  else plot_prepared_suite(args.request))
    elif args.rheology_command == "tts":
        result = create_suite(args.request)
    elif args.rheology_command == "export":
        result = export_suite(args.workspace)
    elif args.rheology_command == "capabilities":
        from sciplot_core.workflow.rheology_tts_contract import rheology_capabilities
        result = rheology_capabilities()
    elif args.rheology_command == "style-preview":
        from sciplot_core.workflow.rheology_tts_style_update import preview_suite_style
        result = preview_suite_style(args.workspace, presentation_plan=args.presentation_plan)
    elif args.rheology_command == "style-apply":
        from sciplot_core.workflow.rheology_tts_style_update import apply_suite_style
        result = apply_suite_style(args.workspace, args.preview)
    else:
        raise ValueError("Unknown rheology command; read rheology capabilities.")
    if args.rheology_command in {"plot", "tts"} and not getattr(args, "full", False):
        result = _compact_creation_result(result)
    _print_json(result)
    return 0 if result["status"] in {"ready", "preview_ready", "no_change"} else 1
