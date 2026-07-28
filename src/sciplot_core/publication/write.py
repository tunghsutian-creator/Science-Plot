"""Write publication intent, ledger, profile, and QA artifacts."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def write_publication_artifacts(
    output_dir: Path,
    *,
    publication_intent: dict[str, Any],
    transform_ledger: dict[str, Any],
    publication_profile: dict[str, Any],
    publication_qa: dict[str, Any] | None = None,
) -> dict[str, str]:
    output_dir.mkdir(parents=True, exist_ok=True)
    artifacts = {
        "publication_intent": output_dir / "publication_intent.json",
        "transform_ledger": output_dir / "transform_ledger.json",
        "journal_profile": output_dir / "journal_profile.json",
    }
    payloads = {
        "publication_intent": publication_intent,
        "transform_ledger": transform_ledger,
        "journal_profile": publication_profile,
    }
    if publication_qa is not None:
        artifacts["publication_qa"] = output_dir / "publication_qa.json"
        payloads["publication_qa"] = publication_qa
    for key, path in artifacts.items():
        path.write_text(
            json.dumps(payloads[key], indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
    return {key: str(path) for key, path in artifacts.items()}
