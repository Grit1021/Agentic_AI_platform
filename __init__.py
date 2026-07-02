__all__ = ['PipelineOrchestrator']


def __getattr__(name):
    if name == 'PipelineOrchestrator':
        from .orchestrator import PipelineOrchestrator

        return PipelineOrchestrator
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
