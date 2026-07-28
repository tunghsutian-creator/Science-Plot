"""Study-model API and first-party compatibility facade."""

from __future__ import annotations

from sciplot_core.study_model.experiment_plans import (  # noqa: F401
    STUDY_MODEL_KIND,
    STUDY_MODEL_VERSION,
    REPLICATE_MODES,
    _REPLICATE_MODE_ALIASES,
    _DEFAULT_FIGURE_QUEUE,
    _TENSILE_DESCRIPTIVE_STATISTICS,
    _EXPERIMENT_PLANS,
)
from sciplot_core.study_model.recommendations import (  # noqa: F401
    normalize_replicate_mode,
    _token,
    _unique_id,
    _experiment_plan,
    experiment_recommendation_payload,
    _metric_payloads,
    _source_file_payload,
    _statistics_method_contract,
)
from sciplot_core.study_model.normalization import (  # noqa: F401
    normalize_study_model,
    build_study_model,
)
from sciplot_core.study_model.request_sync import (  # noqa: F401
    study_model_from_request,
    sync_study_model_samples,
)
from sciplot_core.study_model.run_artifacts import (  # noqa: F401
    _figure_artifact_key,
    _json_contract_matches,
    attach_run_artifacts_to_study_model,
)
from sciplot_core.study_model.package_contract import (  # noqa: F401
    build_output_package_contract,
    verify_output_package_contract,
)

__all__ = [
    "REPLICATE_MODES",
    "STUDY_MODEL_KIND",
    "STUDY_MODEL_VERSION",
    "attach_run_artifacts_to_study_model",
    "build_output_package_contract",
    "verify_output_package_contract",
    "build_study_model",
    "experiment_recommendation_payload",
    "normalize_replicate_mode",
    "normalize_study_model",
    "study_model_from_request",
    "sync_study_model_samples",
]
