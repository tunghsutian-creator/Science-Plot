from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from sciplot_core._bootstrap import ensure_legacy_core
from sciplot_core._paths import REPO_ROOT, local_reference_root, real_world_fixture_root, resolve_fixture_path
from sciplot_core._utils import json_safe, slug
from sciplot_core.curate import curate_torque_project
from sciplot_core.evidence import enrich_rule_evidence, write_evidence_status_dashboard
from sciplot_core.materials_rules import SemanticRule, get_rule, iter_public_rules
from sciplot_core.policy import DEFAULT_FIGURE_SIZE
from sciplot_core.studio import export_studio_document, prepare_studio_document, publish_studio_export_run
from sciplot_core.visual_review import write_final_size_visual_review
from sciplot_core.workflow import run_request

ensure_legacy_core()

from src.data_loader import read_raw_table  # noqa: E402

DEFAULT_3DPA_FTIR_LABELS = ("PA6", "A20", "A40", "A80", "A20-2MIN", "A30-2MIN")
DEFAULT_3DPA_TORQUE_DIRS = ("转矩/260607", "转矩/Z", "torque/260607", "torque/Z")
DEFAULT_DENSE_SERIES_COUNT = 44
DEFAULT_REPRESENTATIVE_COUNT = 6
RULE_ACCEPTANCE_VERSION = 2
RULE_ACCEPTANCE_CHECK_IDS = (
    "semantic_rule_selected",
    "vsz_reopen_export",
    "manual_edit_preserved",
    "canonical_pdf_tiff_pair",
    "qa_passed",
    "delivery_complete",
    "provenance_complete",
)
@dataclass(frozen=True)
class SpectrumSeries:
    label: str
    source: Path
    data: pd.DataFrame


def _public_fixture_index(repo_root: Path) -> dict[Path, dict[str, Any]]:
    corpus_root = repo_root / "tests" / "fixtures" / "polymer_corpus"
    manifest_path = corpus_root / "manifest.json"
    if not manifest_path.exists():
        corpus_root = local_reference_root(repo_root=repo_root) / "polymer_corpus"
        manifest_path = corpus_root / "manifest.json"
    if not manifest_path.exists():
        return {}
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    entries = payload.get("entries") if isinstance(payload.get("entries"), list) else []
    indexed: dict[Path, dict[str, Any]] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        fixture_value = entry.get("fixture_path")
        if not isinstance(fixture_value, str) or not fixture_value.strip():
            continue
        indexed[(corpus_root / fixture_value).resolve()] = entry
    return indexed


def _real_world_fixture_index(repo_root: Path) -> dict[Path, dict[str, Any]]:
    fixture_root = real_world_fixture_root(repo_root=repo_root)
    manifest_path = fixture_root / "evidence_manifest.json"
    if not manifest_path.exists():
        return {}
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    entries = payload.get("entries") if isinstance(payload.get("entries"), list) else []
    indexed: dict[Path, dict[str, Any]] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        fixture_value = entry.get("fixture_path")
        if not isinstance(fixture_value, str) or not fixture_value.strip():
            continue
        indexed[(fixture_root / fixture_value).resolve()] = entry
    return indexed


def _rule_fixture_evidence(rule: SemanticRule, *, repo_root: Path) -> dict[str, Any]:
    fixture = resolve_fixture_path(str(rule.fixture_path or ""), repo_root=repo_root)
    public_entry = _public_fixture_index(repo_root).get(fixture)
    if public_entry is not None:
        return {
            "tier": "public_source_excerpt",
            "real_data_evidence": True,
            "source_url": public_entry.get("source_url"),
            "doi": public_entry.get("doi"),
            "license": public_entry.get("license"),
            "description": "Reduced excerpt from a source-annotated public experimental dataset.",
            "manifest_metadata": public_entry,
        }
    real_world_entry = _real_world_fixture_index(repo_root).get(fixture)
    if real_world_entry is not None:
        return {
            "tier": str(real_world_entry.get("tier") or "user_authorized_real_excerpt"),
            "real_data_evidence": bool(real_world_entry.get("real_data_evidence")),
            "source_url": real_world_entry.get("source_url"),
            "doi": real_world_entry.get("doi"),
            "license": real_world_entry.get("license"),
            "description": str(real_world_entry.get("description") or ""),
            "source_data_status": real_world_entry.get("source_data_status"),
            "manifest_metadata": real_world_entry,
        }
    fixture_parts = set(fixture.parts)
    if "real_world" in fixture_parts:
        return {
            "tier": "user_authorized_real_excerpt",
            "real_data_evidence": True,
            "source_url": None,
            "doi": None,
            "license": None,
            "description": "User-authorized real instrument export or reduced excerpt retained as regression evidence.",
        }
    if "archived_output_raw_data" in fixture_parts:
        return {
            "tier": "archived_project_data",
            "real_data_evidence": True,
            "source_url": None,
            "doi": None,
            "license": None,
            "description": "Archived project data retained as regression evidence.",
        }
    return {
        "tier": "instrument_shaped_fixture",
        "real_data_evidence": False,
        "source_url": None,
        "doi": None,
        "license": None,
        "description": "Fixture exercises the instrument-shaped contract but is not claimed as real-data evidence.",
    }


def _rule_matrix_row(rule: SemanticRule, *, repo_root: Path) -> dict[str, Any]:
    fixture = resolve_fixture_path(str(rule.fixture_path or ""), repo_root=repo_root)
    evidence = enrich_rule_evidence(
        rule,
        _rule_fixture_evidence(rule, repo_root=repo_root),
        fixture=fixture,
        repo_root=repo_root,
    )
    return {
        "rule_id": rule.rule_id,
        "semantic_family": rule.semantic_family,
        "recipe": rule.recipe,
        "template": rule.template,
        "rule_readiness": rule.fixture_status,
        "fixture_path": str(fixture),
        "fixture_exists": fixture.exists(),
        "evidence": evidence,
        "lifecycle_status": "not_run",
        "checks": {check_id: None for check_id in RULE_ACCEPTANCE_CHECK_IDS},
        "project_dir": None,
        "manifest": None,
        "artifact_review": {"status": "not_run"},
        "limitations": [],
        "error": None,
    }


def build_rule_acceptance_matrix(*, repo_root: Path = REPO_ROOT) -> list[dict[str, Any]]:
    return [_rule_matrix_row(rule, repo_root=repo_root) for rule in iter_public_rules()]


def _delivery_artifact_passed(delivery: dict[str, Any], artifact_id: str) -> bool:
    artifacts = delivery.get("artifacts") if isinstance(delivery.get("artifacts"), list) else []
    return any(
        isinstance(item, dict) and item.get("id") == artifact_id and item.get("exists") is True
        for item in artifacts
    )


def _manual_edit_probe(document_path: Path, *, rule_id: str) -> str:
    marker = f"# SciPlot acceptance manual-edit preservation probe: {rule_id}"
    with document_path.open("a", encoding="utf-8") as handle:
        handle.write(f"\n{marker}\n")
    return marker


def _run_rule_lifecycle_acceptance(
    rule: SemanticRule,
    *,
    projects_root: Path,
    repo_root: Path,
) -> dict[str, Any]:
    row = _rule_matrix_row(rule, repo_root=repo_root)
    fixture = Path(row["fixture_path"])
    try:
        prepared = prepare_studio_document(
            fixture,
            output_root=projects_root,
            project_name=f"{rule.rule_id} acceptance",
            rule_id=rule.rule_id,
        )
        project_dir = Path(str(prepared["project_dir"]))
        request_path = Path(str(prepared["request"]))
        document_path = Path(str(prepared["document"]))
        marker = _manual_edit_probe(document_path, rule_id=rule.rule_id)
        exports = export_studio_document(document_path, formats=["pdf", "tiff_300"])["exports"]
        studio_run = publish_studio_export_run(
            project_dir=project_dir,
            request_path=request_path,
            document_path=document_path,
            exports=exports,
        )
        manifest_path = Path(str(studio_run["manifest"]))
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        semantic = manifest.get("semantic") if isinstance(manifest.get("semantic"), dict) else {}
        transform = manifest.get("transform_ledger") if isinstance(manifest.get("transform_ledger"), dict) else {}
        publication_intent = (
            manifest.get("publication_intent") if isinstance(manifest.get("publication_intent"), dict) else {}
        )
        delivery = manifest.get("delivery_package") if isinstance(manifest.get("delivery_package"), dict) else {}
        editable_vsz = delivery.get("editable_vsz") if isinstance(delivery.get("editable_vsz"), dict) else {}
        editable_path = Path(str(editable_vsz.get("path"))) if editable_vsz.get("path") else None
        manual_edit_preserved = bool(
            manifest.get("manual_edit_detected") is True
            and marker in document_path.read_text(encoding="utf-8")
            and editable_path is not None
            and editable_path.exists()
            and marker in editable_path.read_text(encoding="utf-8")
            and editable_vsz.get("hash_matches_export") is True
        )
        exported_formats = {str(item.get("format")) for item in exports if isinstance(item, dict)}
        checks = {
            "semantic_rule_selected": semantic.get("rule_id") == rule.rule_id,
            "vsz_reopen_export": document_path.exists()
            and prepared.get("series_count", 0) > 0
            and {"pdf", "tiff_300"} <= exported_formats,
            "manual_edit_preserved": manual_edit_preserved,
            "canonical_pdf_tiff_pair": _delivery_artifact_passed(delivery, "canonical_pdf_tiff_pairs"),
            "qa_passed": manifest.get("qa", {}).get("status") == "passed",
            "delivery_complete": delivery.get("complete") is True,
            "provenance_complete": bool(
                semantic.get("rule_id") == rule.rule_id
                and transform.get("status") == "runtime_recorded"
                and publication_intent.get("kind") == "sciplot_publication_intent"
                and manifest.get("raw_archive", {}).get("path")
            ),
        }
        row.update(
            {
                "lifecycle_status": "passed" if all(checks.values()) else "failed",
                "checks": checks,
                "project_dir": str(project_dir),
                "manifest": str(manifest_path),
                "limitations": [
                    "The manual-edit probe appends a harmless VSZ comment and proves exact-document preservation; "
                    "full visual-object inspection is exercised by the separate exact-current publication-QA suite."
                ],
            }
        )
    except Exception as exc:  # keep the matrix complete when one family blocks
        row.update(
            {
                "lifecycle_status": "failed",
                "error": {"type": type(exc).__name__, "message": str(exc)},
            }
        )
    return row


def _write_rule_acceptance_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fieldnames = [
        "rule_id",
        "semantic_family",
        "template",
        "rule_readiness",
        "evidence_tier",
        "real_data_evidence",
        "lifecycle_status",
        "physical_size_status",
        *RULE_ACCEPTANCE_CHECK_IDS,
        "fixture_path",
        "manifest",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    "rule_id": row["rule_id"],
                    "semantic_family": row["semantic_family"],
                    "template": row["template"],
                    "rule_readiness": row["rule_readiness"],
                    "evidence_tier": row["evidence"]["tier"],
                    "real_data_evidence": row["evidence"]["real_data_evidence"],
                    "lifecycle_status": row["lifecycle_status"],
                    "physical_size_status": row.get("artifact_review", {}).get("status", "not_run"),
                    **{check_id: row["checks"].get(check_id) for check_id in RULE_ACCEPTANCE_CHECK_IDS},
                    "fixture_path": row["fixture_path"],
                    "manifest": row["manifest"],
                }
            )


def _write_rule_acceptance_markdown(path: Path, payload: dict[str, Any]) -> None:
    lines = [
        "# SciPlot Ready-Rule Acceptance Matrix",
        "",
        f"Generated: {payload['generated_at']}",
        "",
        "Lifecycle status and real-data evidence are deliberately separate. A fixture-backed rule is not described "
        "as real-data accepted unless its evidence metadata supports that claim.",
        "",
        "| Rule | Evidence | Real data | Lifecycle | Final size | Failed checks |",
        "|---|---|---:|---|---|---|",
    ]
    for row in payload["matrix"]:
        failed = [check_id for check_id, passed in row["checks"].items() if passed is False]
        lines.append(
            f"| `{row['rule_id']}` | `{row['evidence']['tier']}` | "
            f"{'yes' if row['evidence']['real_data_evidence'] else 'no'} | "
            f"`{row['lifecycle_status']}` | `{row.get('artifact_review', {}).get('status', 'not_run')}` | "
            f"{', '.join(failed) or '-'} |"
        )
    lines.extend(
        [
            "",
            "## Honest coverage boundary",
            "",
            "- Rows count as real-data evidence only when their explicit `real_data_evidence` field is true; "
            "the tier records whether the source is public, user-authorized, digitized, derived, or limited.",
            "- `instrument_shaped_fixture` proves a parser/render contract only; it remains a real-data gap.",
            "- The manual-edit probe proves exact VSZ preservation. PDF/TIFF physical size is checked here, while "
            "the generated contact sheets still require an explicit visual decision.",
            "- Native 183 mm Veusz composition remains outside this acceptance suite.",
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")


def run_rule_acceptance_suite(
    *,
    output_root: Path,
    project_name: str = "ready_rule_acceptance",
    rule_ids: list[str] | tuple[str, ...] | None = None,
    repo_root: Path = REPO_ROOT,
) -> dict[str, Any]:
    ready_rules = list(iter_public_rules())
    ready_by_id = {rule.rule_id: rule for rule in ready_rules}
    selected_ids = list(dict.fromkeys(rule_ids or [rule.rule_id for rule in ready_rules]))
    unknown = [rule_id for rule_id in selected_ids if rule_id not in ready_by_id]
    if unknown:
        for rule_id in unknown:
            try:
                rule = get_rule(rule_id)
            except ValueError:
                continue
            if rule.fixture_status != "ready":
                raise ValueError(f"Acceptance suite only runs ready rules; `{rule_id}` is {rule.fixture_status}.")
        raise ValueError(f"Unknown or non-ready rule ids: {', '.join(unknown)}")

    project_dir = output_root.expanduser().resolve() / slug(project_name)
    projects_root = project_dir / "projects"
    project_dir.mkdir(parents=True, exist_ok=True)
    rows_by_id = {row["rule_id"]: row for row in build_rule_acceptance_matrix(repo_root=repo_root)}
    for rule_id in selected_ids:
        rows_by_id[rule_id] = _run_rule_lifecycle_acceptance(
            ready_by_id[rule_id],
            projects_root=projects_root,
            repo_root=repo_root,
        )
    rows = [rows_by_id[rule.rule_id] for rule in ready_rules]
    selected_rows = [rows_by_id[rule_id] for rule_id in selected_ids]
    generated_at = datetime.now(UTC).isoformat()
    visual_review = write_final_size_visual_review(
        output_dir=project_dir,
        rows=rows,
        generated_at=generated_at,
    )
    for row in rows:
        row["artifact_review"] = visual_review["records_by_rule"][row["rule_id"]]
    selected_lifecycle_failed = [
        row["rule_id"] for row in selected_rows if row["lifecycle_status"] != "passed"
    ]
    selected_size_failed = [
        row["rule_id"]
        for row in selected_rows
        if row.get("artifact_review", {}).get("status") == "failed"
    ]
    selected_failed = list(dict.fromkeys([*selected_lifecycle_failed, *selected_size_failed]))
    passed_count = sum(row["lifecycle_status"] == "passed" for row in rows)
    physical_size_passed_count = sum(
        row.get("artifact_review", {}).get("status") == "passed" for row in rows
    )
    real_data_passed_count = sum(
        row["lifecycle_status"] == "passed" and row["evidence"]["real_data_evidence"] for row in rows
    )
    coverage_complete = passed_count == len(ready_rules)
    physical_size_complete = physical_size_passed_count == len(ready_rules)
    selected_state = "ready" if not selected_failed else "needs_rule_repair"
    state = (
        "needs_rule_repair"
        if selected_failed
        else ("ready" if coverage_complete and physical_size_complete else "in_progress")
    )
    payload = {
        "kind": "sciplot_ready_rule_acceptance",
        "version": RULE_ACCEPTANCE_VERSION,
        "generated_at": generated_at,
        "state": state,
        "selected_state": selected_state,
        "project_dir": str(project_dir),
        "selected_rule_ids": selected_ids,
        "failed_rule_ids": selected_failed,
        "coverage": {
            "ready_rule_count": len(ready_rules),
            "lifecycle_passed_count": passed_count,
            "lifecycle_complete": coverage_complete,
            "physical_size_passed_count": physical_size_passed_count,
            "physical_size_complete": physical_size_complete,
            "real_data_lifecycle_passed_count": real_data_passed_count,
            "instrument_shaped_gap_count": sum(
                not row["evidence"]["real_data_evidence"] for row in rows
            ),
        },
        "visual_review": visual_review["summary"],
        "matrix": rows,
        "limitations": [
            "A passed instrument-shaped fixture is not promoted to real-data acceptance.",
            "Exact-current publication QA is implemented separately; this matrix measures rule lifecycle and "
            "real-data breadth rather than journal compliance.",
            "Final PDF/TIFF dimensions are machine-checked, but contact-sheet visual review remains an explicit "
            "manual or agent decision.",
            "Native 183 mm Veusz composition remains deferred in favor of exact-size standalone PDF assembly.",
        ],
    }
    summary_path = project_dir / "acceptance_summary.json"
    matrix_path = project_dir / "acceptance_matrix.json"
    csv_path = project_dir / "acceptance_matrix.csv"
    markdown_path = project_dir / "acceptance_matrix.md"
    summary_path.write_text(json.dumps(json_safe(payload), indent=2, ensure_ascii=False), encoding="utf-8")
    matrix_path.write_text(json.dumps(json_safe(rows), indent=2, ensure_ascii=False), encoding="utf-8")
    _write_rule_acceptance_csv(csv_path, rows)
    _write_rule_acceptance_markdown(markdown_path, payload)
    evidence_dashboard = write_evidence_status_dashboard(
        output_dir=project_dir,
        rows=rows,
        repo_root=repo_root,
        generated_at=generated_at,
    )
    payload["evidence_status"] = evidence_dashboard["summary"]
    payload["artifacts"] = {
        "summary": str(summary_path),
        "matrix_json": str(matrix_path),
        "matrix_csv": str(csv_path),
        "matrix_markdown": str(markdown_path),
        **visual_review["artifacts"],
        **evidence_dashboard["artifacts"],
    }
    summary_path.write_text(json.dumps(json_safe(payload), indent=2, ensure_ascii=False), encoding="utf-8")
    return payload


def _normalize_label(value: str) -> str:
    return value.strip().casefold().replace("_", "-").replace(" ", "")


def _candidate_ftir_dirs(root: Path) -> list[Path]:
    candidates = [
        root,
        root / "FTIR",
        root / "FTIR" / "红外",
        root / "FTIR" / "20 min",
        root / "FTIR" / "2 min",
        root / "红外",
    ]
    seen: set[Path] = set()
    existing: list[Path] = []
    for candidate in candidates:
        resolved = candidate.expanduser()
        if resolved in seen or not resolved.exists() or not resolved.is_dir():
            continue
        seen.add(resolved)
        existing.append(resolved)
    return existing


def _find_ftir_files(root: Path, *, representative_count: int) -> list[Path]:
    files: list[Path] = []
    for directory in _candidate_ftir_dirs(root):
        files.extend(sorted(path for path in directory.glob("*.CSV") if path.is_file()))
        files.extend(sorted(path for path in directory.glob("*.csv") if path.is_file()))
        if len(files) >= representative_count:
            break
    if not files:
        files = sorted(path for path in root.rglob("*.CSV") if path.is_file())
        files.extend(sorted(path for path in root.rglob("*.csv") if path.is_file()))

    by_label = {_normalize_label(path.stem): path for path in files}
    selected: list[Path] = []
    selected_set: set[Path] = set()
    for label in DEFAULT_3DPA_FTIR_LABELS:
        path = by_label.get(_normalize_label(label))
        if path is not None and path not in selected_set:
            selected.append(path)
            selected_set.add(path)
    for path in files:
        if len(selected) >= representative_count:
            break
        if path not in selected_set:
            selected.append(path)
            selected_set.add(path)

    if len(selected) < 2:
        raise ValueError(f"3D PA acceptance needs at least two FTIR CSV files under {root}.")
    return selected[:representative_count]


def _candidate_torque_dirs(root: Path) -> list[Path]:
    candidates = [root / item for item in DEFAULT_3DPA_TORQUE_DIRS]
    torque_root = root / "转矩"
    if torque_root.exists():
        candidates.extend(path for path in torque_root.glob("*") if path.is_dir())
    seen: set[Path] = set()
    existing: list[Path] = []
    for candidate in candidates:
        resolved = candidate.expanduser()
        if resolved in seen or not resolved.exists() or not resolved.is_dir():
            continue
        if len(list(resolved.glob("*.txt"))) < 2:
            continue
        seen.add(resolved)
        existing.append(resolved)
    return existing


def _find_torque_dir(root: Path) -> Path | None:
    candidates = _candidate_torque_dirs(root)
    if candidates:
        return candidates[0]
    for directory in sorted(root.rglob("*"), key=lambda path: path.as_posix()):
        if not directory.is_dir():
            continue
        text = directory.as_posix().casefold()
        if ("转矩" not in text and "torque" not in text) or len(list(directory.glob("*.txt"))) < 2:
            continue
        return directory
    return None


def _sample_label(path: Path) -> str:
    return path.stem.strip()


def _read_raw_spectrum(path: Path) -> pd.DataFrame:
    raw = read_raw_table(path)
    if raw.shape[1] < 2:
        raise ValueError(f"FTIR spectrum must have at least two columns: {path}")
    frame = raw.iloc[:, :2].apply(pd.to_numeric, errors="coerce").dropna()
    if frame.empty:
        raise ValueError(f"FTIR spectrum has no numeric x/y rows: {path}")
    frame.columns = ["x", "raw_y"]
    frame = frame.sort_values("x").reset_index(drop=True)
    y = frame["raw_y"].astype(float)
    low = float(y.quantile(0.01))
    high = float(y.quantile(0.99))
    if high <= low:
        normalized = y * 0.0
    else:
        normalized = ((y - low) / (high - low)).clip(lower=0.0, upper=1.25)
    return pd.DataFrame({"x": frame["x"].astype(float), "y": normalized.astype(float)})


def _load_spectra(paths: list[Path]) -> list[SpectrumSeries]:
    return [
        SpectrumSeries(label=_sample_label(path), source=path.expanduser().resolve(), data=_read_raw_spectrum(path))
        for path in paths
    ]


def _write_curve_table(series: list[SpectrumSeries], output: Path) -> Path:
    output.parent.mkdir(parents=True, exist_ok=True)
    rows: list[list[Any]] = [
        sum((["Wavenumber", "Normalized absorbance"] for _ in series), []),
        sum((["cm^-1", "a.u."] for _ in series), []),
        sum(([item.label, item.label] for item in series), []),
    ]
    max_len = max(len(item.data) for item in series)
    for row_index in range(max_len):
        row: list[Any] = []
        for item in series:
            if row_index < len(item.data):
                row.extend(
                    [
                        float(item.data.iat[row_index, 0]),
                        float(item.data.iat[row_index, 1]),
                    ]
                )
            else:
                row.extend(["", ""])
        rows.append(row)
    pd.DataFrame(rows).to_csv(output, header=False, index=False)
    return output


def _build_dense_series(series: list[SpectrumSeries], *, series_count: int) -> list[SpectrumSeries]:
    if series_count < 1:
        raise ValueError("dense series count must be at least 1.")
    dense: list[SpectrumSeries] = []
    for index in range(series_count):
        item = series[index % len(series)]
        repeat = index // len(series) + 1
        dense.append(
            SpectrumSeries(
                label=f"{item.label} r{repeat:02d}",
                source=item.source,
                data=item.data,
            )
        )
    return dense


def _write_request(path: Path, payload: dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(json_safe(payload), indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def _manifest_summary(manifest: dict[str, Any]) -> dict[str, Any]:
    output_dir = Path(str(manifest["output"]))
    layout_quality = manifest.get("layout_quality") if isinstance(manifest.get("layout_quality"), dict) else {}
    delivery = manifest.get("delivery_package") if isinstance(manifest.get("delivery_package"), dict) else {}
    summaries = layout_quality.get("summaries") if isinstance(layout_quality.get("summaries"), list) else []
    first_axis: dict[str, Any] = {}
    if summaries:
        axes = summaries[0].get("axes") if isinstance(summaries[0], dict) else []
        if isinstance(axes, list) and axes:
            first_axis = axes[0] if isinstance(axes[0], dict) else {}
    pdf_count = len(list((output_dir / "figures").glob("*.pdf")))
    tiff_count = len(list((output_dir / "figures").glob("*_300dpi.tiff")))
    delivery_dir = Path(str(delivery.get("path"))) if delivery.get("path") else output_dir / "delivery"
    state = "ready"
    if manifest.get("qa", {}).get("status") != "passed":
        state = "needs_rule_repair"
    if layout_quality.get("issue_ids"):
        state = "needs_rule_repair"
    if delivery.get("complete") is not True:
        state = "needs_rule_repair"
    return {
        "state": state,
        "output": str(output_dir),
        "manifest": str(output_dir / "manifest.json"),
        "delivery": str(delivery_dir),
        "delivery_complete": bool(delivery.get("complete")),
        "qa_status": manifest.get("qa", {}).get("status"),
        "render_engine": manifest.get("render_engine"),
        "qa_target": manifest.get("qa_target"),
        "veusz_document_count": len(manifest.get("veusz_documents", [])),
        "veusz_spec_count": len(manifest.get("veusz_specs", [])),
        "layout_issue_ids": layout_quality.get("issue_ids", []),
        "autofixes_applied": layout_quality.get("autofixes_applied", []),
        "auto_split": layout_quality.get("auto_split"),
        "split_plan": layout_quality.get("split_plan"),
        "x_bounds": first_axis.get("x_bounds"),
        "x_ticks": first_axis.get("x_ticks"),
        "legend": first_axis.get("legend"),
        "pdf_count": pdf_count,
        "tiff_300_count": tiff_count,
    }


def _run_acceptance_request(
    *,
    run_root: Path,
    request_name: str,
    input_path: Path,
    render_options: dict[str, Any],
    review_notes: list[str],
) -> dict[str, Any]:
    request_dir = run_root / request_name
    request = {
        "template": "stacked_curve",
        "input": str(input_path.resolve()),
        "output": str((request_dir / "run_001").resolve()),
        "render_options": render_options,
        "review_notes": review_notes,
    }
    request_path = _write_request(request_dir / "plot_request.json", request)
    manifest = run_request(request_path)
    return {
        "id": request_name,
        "request_path": str(request_path),
        "summary": _manifest_summary(manifest),
    }


def _run_torque_acceptance(*, project_dir: Path, torque_dir: Path) -> dict[str, Any]:
    curation = curate_torque_project(
        torque_dir,
        output_root=project_dir / "_torque_curation_projects",
        project_name="3D PA torque acceptance",
        open_review=False,
    )
    request_path = Path(str(curation["plot_request"]))
    manifest = run_request(request_path)
    return {
        "id": "torque_260607_curve",
        "request_path": str(request_path),
        "summary": _manifest_summary(manifest),
        "curation": {
            "source_dir": str(torque_dir),
            "project_dir": curation.get("project_dir"),
            "selection_path": curation.get("selection_path"),
            "plot_data_path": curation.get("plot_data_path"),
            "review_html": curation.get("review_html"),
        },
    }


def run_3dpa_acceptance(
    input_root: Path,
    *,
    output_root: Path,
    project_name: str = "3dpa_acceptance",
    representative_count: int = DEFAULT_REPRESENTATIVE_COUNT,
    dense_series_count: int = DEFAULT_DENSE_SERIES_COUNT,
) -> dict[str, Any]:
    root = input_root.expanduser().resolve()
    if not root.exists():
        raise FileNotFoundError(f"3D PA input root not found: {input_root}")
    if representative_count < 2:
        raise ValueError("representative_count must be at least 2.")
    output_root = output_root.expanduser().resolve()
    project_dir = output_root / slug(project_name)
    data_dir = project_dir / "data"
    source_files = _find_ftir_files(root, representative_count=representative_count)
    spectra = _load_spectra(source_files)
    representative_table = _write_curve_table(spectra, data_dir / "3dpa_ftir_representative_stack.csv")
    dense_table = _write_curve_table(
        _build_dense_series(spectra, series_count=dense_series_count),
        data_dir / f"3dpa_ftir_dense_stack_{dense_series_count}.csv",
    )

    runs = [
        _run_acceptance_request(
            run_root=project_dir,
            request_name="ftir_representative_stack",
            input_path=representative_table,
            render_options={"size": DEFAULT_FIGURE_SIZE, "series_label_mode": "legend"},
            review_notes=["3D PA FTIR representative stack acceptance from raw two-column spectra."],
        ),
        _run_acceptance_request(
            run_root=project_dir,
            request_name="ftir_dense_auto_split",
            input_path=dense_table,
            render_options={"size": "60x110", "series_label_mode": "legend"},
            review_notes=[
                "3D PA FTIR dense-stack acceptance. Representative raw spectra are duplicated to exercise "
                "automatic split boundaries without synthetic curve shapes."
            ],
        ),
    ]
    torque_dir = _find_torque_dir(root)
    if torque_dir is not None:
        runs.append(_run_torque_acceptance(project_dir=project_dir, torque_dir=torque_dir))
    state = "ready" if all(run["summary"]["state"] == "ready" for run in runs) else "needs_rule_repair"
    payload = {
        "kind": "sciplot_acceptance_run",
        "target": "3dpa",
        "state": state,
        "project_dir": str(project_dir),
        "source_root": str(root),
        "source_files": [str(path) for path in source_files],
        "torque_source_dir": str(torque_dir) if torque_dir is not None else None,
        "data": {
            "representative_table": str(representative_table),
            "dense_table": str(dense_table),
            "dense_series_count": dense_series_count,
        },
        "runs": runs,
    }
    (project_dir / "acceptance_summary.json").write_text(
        json.dumps(json_safe(payload), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return payload


__all__ = [
    "DEFAULT_3DPA_FTIR_LABELS",
    "DEFAULT_3DPA_TORQUE_DIRS",
    "DEFAULT_DENSE_SERIES_COUNT",
    "DEFAULT_REPRESENTATIVE_COUNT",
    "RULE_ACCEPTANCE_CHECK_IDS",
    "RULE_ACCEPTANCE_VERSION",
    "build_rule_acceptance_matrix",
    "run_3dpa_acceptance",
    "run_rule_acceptance_suite",
]
