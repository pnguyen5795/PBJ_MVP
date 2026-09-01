from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict


@dataclass(frozen=True)
class ProviderReadiness:
    provider: str
    configured: bool
    message: str


class AnalysisProvider(ABC):
    name: str

    @abstractmethod
    def cache_identity(self) -> Dict[str, str]:
        """Return the model and prompt versions that make an analysis reusable."""
        raise NotImplementedError

    @abstractmethod
    def readiness(self) -> ProviderReadiness:
        raise NotImplementedError

    @abstractmethod
    async def analyze(self, path: Path, file_id: str, purpose: str) -> Dict[str, Any]:
        """Return provider-neutral analysis JSON for one original video."""
        raise NotImplementedError

    @abstractmethod
    async def delete_asset(self, asset_id: str) -> None:
        """Delete one explicitly selected remote asset."""
        raise NotImplementedError
