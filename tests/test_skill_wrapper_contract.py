from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_skill_wrapper_delegates_every_command_to_the_public_cli() -> None:
    wrapper = (REPO_ROOT / "skill" / "scripts" / "sciplot").read_text(
        encoding="utf-8"
    )

    assert 'exec "$PYTHON" -m sciplot_core.cli "$@"' in wrapper
    assert "verify --changed" not in wrapper
