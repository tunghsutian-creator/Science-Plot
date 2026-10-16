"""Changed owners for documentation and vendored native build support."""

from sciplot_core.verification.owner_model import ChangedOwner

WHEEL_DISTRIBUTION_OWNER = ChangedOwner(
    owner_id="wheel_distribution",
    owned_test_paths=frozenset({"tests/test_wheel_surface.py"}),
    pytest_targets=("tests/test_wheel_surface.py",),
    release_gates=("full_pytest",),
)

VEUSZ_NATIVE_BUILD_OWNER = ChangedOwner(
    owner_id="veusz_native_build",
    exact_paths=frozenset({"third_party/veusz/pyqt_setuptools.py"}),
    owned_test_paths=frozenset({"tests/test_veusz_build_recovery.py"}),
    pytest_targets=("tests/test_veusz_build_recovery.py",),
    handoff_gates=("doctor",),
    final_milestone_gates=("smoke",),
    release_gates=("full_pytest",),
)

SCIENTIFIC_TEXT_OWNER = ChangedOwner(
    owner_id="scientific_native_text",
    exact_paths=frozenset({
        "src/sciplot_core/studio_core/qt_compat.py",
        "src/sciplot_core/studio_core/veusz_scientific_text.py",
    }),
    owned_test_paths=frozenset({"tests/test_veusz_scientific_text.py"}),
    pytest_targets=(
        "tests/test_veusz_scientific_text.py",
        "tests/test_scientific_unit_expression_contract.py",
        "tests/test_native_font_evidence.py",
        "tests/test_performance_veusz.py",
        "tests/test_radar_scientific_display.py",
    ),
    mypy_required=True,
    release_gates=("full_pytest",),
)

DOCUMENTATION_OWNER = ChangedOwner(
    owner_id="documentation_contract",
    path_prefixes=("docs/", "third_party/tavotto-ui/"),
    exact_paths=frozenset(
        {
            "AGENTS.md",
            ".github/workflows/minimal-repository.yml",
            ".gitignore",
            "DEVELOPMENT_LOG.md",
            "DEVELOPMENT_ROADMAP.md",
            "OLD_RENDERING_CONTRACT.md",
            "visual_drift_report.md",
            "README.md",
            "skill/references/external-control.md",
            "skill/references/advanced-workflows.md",
            "skill/references/saved-figure-edit.md",
            "skill/references/ordinary-create.md",
            "skill/references/saved-work-continuation.md",
            "skill/references/paper-figures.md",
            "skill/references/managed-delivery.md",
            "skill/references/panel-assembly.md",
            "skill/references/paper-figures.json",
            "skill/references/performance-radar.md",
            "skill/references/rheology-prepared.md",
        }
    ),
    owned_test_paths=frozenset({"tests/test_documentation_contract.py", "tests/test_repository_policy.py"}),
    pytest_targets=("tests/test_documentation_contract.py", "tests/test_repository_policy.py"),
)
