"""Compatibility imports for repo analysis workflows."""

from importlib import import_module

_EXPORT_MODULES = {
    "RepoAnalysisSubmitWorkflow": "backend.application.repo_analysis.submit_workflow",
    "RepoAnalysisWorkerWorkflow": "backend.application.repo_analysis.worker_workflow",
}

__all__ = sorted(_EXPORT_MODULES)


def __getattr__(name: str):
    if name in _EXPORT_MODULES:
        return getattr(import_module(_EXPORT_MODULES[name]), name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
