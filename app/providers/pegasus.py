import asyncio
import json
import os
from pathlib import Path
from typing import Any, Dict

from twelvelabs import TwelveLabs
from twelvelabs.types import AnalyzePromptV2, SyncResponseFormat, VideoContext_AssetId

from .base import AnalysisProvider, ProviderReadiness
from ..config import settings
from ..contracts import VIDEO_ANALYSIS_JSON_SCHEMA
from ..prompts import VIDEO_ANALYSIS_PROMPT, VIDEO_ANALYSIS_PROMPT_VERSION


class PegasusAnalyzer(AnalysisProvider):
    name = "pegasus"
    minimum_duration_seconds = 4.0

    def cache_identity(self) -> Dict[str, str]:
        return {"model": settings.twelve_labs_model, "prompt_version": VIDEO_ANALYSIS_PROMPT_VERSION}

    def readiness(self) -> ProviderReadiness:
        configured = bool(os.getenv("TWELVE_LABS_API_KEY"))
        return ProviderReadiness(self.name, configured, "Ready" if configured else "Add TWELVE_LABS_API_KEY to .env")

    async def analyze(self, path: Path, file_id: str, purpose: str) -> Dict[str, Any]:
        if not self.readiness().configured:
            raise RuntimeError("TWELVE_LABS_API_KEY is not configured")
        return await asyncio.to_thread(self._analyze_sync, path, file_id, purpose)

    async def delete_asset(self, asset_id: str) -> None:
        if not self.readiness().configured:
            raise RuntimeError("TWELVE_LABS_API_KEY is not configured")
        client = TwelveLabs(api_key=os.environ["TWELVE_LABS_API_KEY"])
        await asyncio.to_thread(client.assets.delete, asset_id)

    def _analyze_sync(self, path: Path, file_id: str, purpose: str) -> Dict[str, Any]:
        client = TwelveLabs(api_key=os.environ["TWELVE_LABS_API_KEY"])
        if path.stat().st_size <= 200 * 1024 * 1024:
            with path.open("rb") as handle:
                asset = client.assets.create(method="direct", file=handle, filename=path.name)
            asset_id = asset.id
        else:
            asset_id = client.multipart_upload.upload_file(path, filename=path.name, file_type="video").asset_id
        if not asset_id:
            raise RuntimeError("Twelve Labs did not return an asset ID")
        try:
            for _ in range(240):
                asset = client.assets.retrieve(asset_id)
                if asset.status == "ready":
                    break
                if asset.status == "failed":
                    raise RuntimeError("Twelve Labs failed to process %s: %s" % (path.name, asset.error))
                import time
                time.sleep(5)
            else:
                raise TimeoutError("Twelve Labs asset processing timed out for %s" % path.name)
            response = client.analyze(
                model_name=settings.twelve_labs_model,
                video=VideoContext_AssetId(asset_id=asset_id),
                prompt_v_2=AnalyzePromptV2(input_text=VIDEO_ANALYSIS_PROMPT.format(purpose=purpose)),
                temperature=0.1,
                response_format=SyncResponseFormat(type="json_schema", json_schema=self.compatible_schema(VIDEO_ANALYSIS_JSON_SCHEMA)),
                max_tokens=12000,
            )
            if not response.data:
                raise RuntimeError("Twelve Labs returned no analysis for %s" % path.name)
            analysis = json.loads(response.data)
            return {
                "schema_version": "1.0", "file_id": file_id,
                "provider": self.name, "model": settings.twelve_labs_model,
                "prompt_version": VIDEO_ANALYSIS_PROMPT_VERSION,
                "remote_asset": {"id": asset_id, "status": "ready", "retained": True},
                "usage": response.usage.model_dump(mode="json") if response.usage and hasattr(response.usage, "model_dump") else {},
                "provider_response": {"data": response.data},
                "analysis": analysis,
            }
        except Exception:
            try:
                client.assets.delete(asset_id)
            except Exception:
                pass
            raise

    @classmethod
    def compatible_schema(cls, value: Any) -> Any:
        """Return Twelve Labs' supported JSON Schema subset without weakening local checks."""
        if isinstance(value, list):
            return [cls.compatible_schema(item) for item in value]
        if not isinstance(value, dict):
            return value
        cleaned = {key: cls.compatible_schema(item) for key, item in value.items()}
        if cleaned.get("type") == "number":
            cleaned.pop("minimum", None)
            cleaned.pop("maximum", None)
        return cleaned
