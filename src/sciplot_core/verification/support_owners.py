"""Changed owners for documentation, packaging and supporting workflow helpers."""

from sciplot_core.verification.owner_model import ChangedOwner
from sciplot_core.verification.type_gate_owners import WORKFLOW_EXPORT_FORMAT_TYPE_OWNER

WORKFLOW_BUNDLE_EXPORT_OWNER = ChangedOwner(
    owner_id="workflow_bundle_exports",
    exact_paths=frozenset({"src/sciplot_core/workflow/bundle_exports.py"}),
    pytest_targets=WORKFLOW_EXPORT_FORMAT_TYPE_OWNER.pytest_targets,
    handoff_gates=WORKFLOW_EXPORT_FORMAT_TYPE_OWNER.handoff_gates,
    final_milestone_gates=WORKFLOW_EXPORT_FORMAT_TYPE_OWNER.final_milestone_gates,
    release_gates=WORKFLOW_EXPORT_FORMAT_TYPE_OWNER.release_gates,
)

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
            "skill/agents/openai.yaml",
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
