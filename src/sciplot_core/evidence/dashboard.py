"""Coordinate durable evidence status dashboard artifacts."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from sciplot_core.foundation.json_values import json_safe

from sciplot_core.evidence.enrichment import (
    load_candidate_rejections,
)

from sciplot_core.evidence.summary import (
    _status_summary,
)

from sciplot_core.evidence.csv_report import (
    _write_csv,
)

from sciplot_core.evidence.markdown_report import (
    _write_markdown,
)

from sciplot_core.evidence.html_report import (
    _write_html,
)


def write_evidence_status_dashboard(
    *,
    output_dir: Path,
    rows: list[dict[str, Any]],
    repo_root: Path,
    generated_at: str | None = None,
) -> dict[str, Any]:
    timestamp = generated_at or datetime.now(UTC).isoformat()
    payload = {
        "kind": "sciplot_23_rule_evidence_status",
        "version": 1,
        "generated_at": timestamp,
        "summary": _status_summary(rows),
        "matrix": rows,
        "candidate_rejections": load_candidate_rejections(repo_root=repo_root),
        "definitions": {
            "lifecycle": "Studio prepare, exact VSZ reopen/export, manual-edit preservation, PDF/TIFF pair, QA, delivery, and provenance checks.",
            "evidence": "Authorization, source identity, fixture identity, units, and real-data tier are evaluated independently of lifecycle.",
            "visual_review": "Final physical-size visual review is a separate artifact-level gate and is not inferred from lifecycle success.",
        },
    }
    json_path = output_dir / "evidence_status.json"
    csv_path = output_dir / "evidence_status.csv"
    markdown_path = output_dir / "evidence_status.md"
    html_path = output_dir / "evidence_dashboard.html"
    json_path.write_text(
        json.dumps(json_safe(payload), indent=2, ensure_ascii=False), encoding="utf-8"
    )
    _write_csv(csv_path, rows)
    _write_markdown(markdown_path, payload)
    _write_html(html_path, payload)
    return {
        "summary": payload["summary"],
        "artifacts": {
            "evidence_json": str(json_path),
            "evidence_csv": str(csv_path),
            "evidence_markdown": str(markdown_path),
            "evidence_dashboard": str(html_path),
        },
    }
