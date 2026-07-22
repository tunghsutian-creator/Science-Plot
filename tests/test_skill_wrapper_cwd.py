from __future__ import annotations

import json
import subprocess
from pathlib import Path


def test_skill_wrapper_preserves_callers_working_directory(tmp_path: Path) -> None:
    source = tmp_path / "relative_input.csv"
    source.write_text("x,y\n0,1\n", encoding="utf-8")
    repo_root = Path(__file__).resolve().parents[1]
    wrapper = repo_root / "skill" / "scripts" / "sciplot"

    completed = subprocess.run(
        [str(wrapper), "inspect", source.name, "--json"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )
    payload = json.loads(completed.stdout)

    # The relative source exists only in ``tmp_path``. A successful inspection
    # therefore proves that the wrapper did not change into the repository.
    assert payload["model"]
    assert isinstance(payload["recommendations"], list)
