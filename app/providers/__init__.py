from .base import AnalysisProvider, ProviderReadiness
from .pegasus import PegasusAnalyzer

PROVIDERS = {
    "pegasus": PegasusAnalyzer,
}


def provider_for_name(name: object):
    """Resolve only an analyzer that the current application supports."""
    return PROVIDERS.get(name) if isinstance(name, str) else None


def readiness_for_provider(name: object) -> ProviderReadiness:
    """Return a safe readiness result for current and historical provider names."""
    provider = provider_for_name(name)
    if provider is None:
        return ProviderReadiness(
            provider="unsupported",
            configured=False,
            message="This saved item uses a video-understanding provider that is no longer supported.",
        )
    return provider().readiness()


__all__ = [
    "AnalysisProvider", "ProviderReadiness", "PegasusAnalyzer", "PROVIDERS",
    "provider_for_name", "readiness_for_provider",
]
