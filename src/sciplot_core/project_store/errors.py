"""Explicit project-store conflict and recovery outcomes."""


class ProjectStoreError(ValueError):
    reason_code = "project_store_invalid"


class ProjectConflict(ProjectStoreError):
    reason_code = "project_generation_conflict"


class ProjectRecoveryRequired(ProjectStoreError):
    reason_code = "project_recovery_required"


class ProjectCommandConflict(ProjectConflict):
    reason_code = "project_command_conflict"
