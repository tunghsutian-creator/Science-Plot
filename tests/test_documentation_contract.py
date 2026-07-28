from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
ACTIVE_GUIDANCE = (
    REPO_ROOT / "README.md",
    REPO_ROOT / "skill" / "SKILL.md",
    REPO_ROOT / "docs" / "ARCHITECTURE.md",
    REPO_ROOT / "DEVELOPMENT_ROADMAP.md",
)
REMOVED_ARCHITECTURE_SNAPSHOT = (
    REPO_ROOT / "docs" / "ARCHITECTURE_REFACTOR_AUDIT_2026-07-28.md"
)


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _normalized(path: Path) -> str:
    return " ".join(_read(path).split())


def test_user_plotting_guidance_keeps_deliveries_source_adjacent() -> None:
    readme = _normalized(REPO_ROOT / "README.md")

    assert "绘图交付不要写进 SciPlot 软件或代码仓库内部的 `outputs/`。" in readme
    assert "优先省略 `--out`" in readme
    assert "在原数据旁创建 `SOURCE_SciPlot/`" in readme

    for path in ACTIVE_GUIDANCE:
        guidance = _read(path)
        assert "--out outputs/" not in guidance
        assert "--out=outputs/" not in guidance


def test_current_documents_do_not_restore_the_dated_architecture_snapshot() -> None:
    gitignore = _read(REPO_ROOT / ".gitignore")

    assert not REMOVED_ARCHITECTURE_SNAPSHOT.exists()
    assert "!/docs/ARCHITECTURE_REFACTOR_AUDIT_2026-07-28.md" not in gitignore


def test_active_documents_declare_distinct_responsibilities() -> None:
    readme = _read(REPO_ROOT / "README.md")
    skill = _read(REPO_ROOT / "skill" / "SKILL.md")
    architecture = _read(REPO_ROOT / "docs" / "ARCHITECTURE.md")
    roadmap = _read(REPO_ROOT / "DEVELOPMENT_ROADMAP.md")

    assert "本文是用户工作流和产品边界的唯一说明" in readme
    assert "This skill owns agent routing and verification." in skill
    assert "current module-ownership and dependency reference" in architecture
    assert "unfinished product and maintenance priorities only" in roadmap
