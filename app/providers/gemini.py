import asyncio
import json
import os
from pathlib import Path
from typing import Any, Dict

from google import genai
from google.genai import types

from .base import AnalysisProvider, ProviderReadiness
from ..config import settings
from ..contracts import VIDEO_ANALYSIS_JSON_SCHEMA
from ..prompts import VIDEO_ANALYSIS_PROMPT, VIDEO_ANALYSIS_PROMPT_VERSION


class GeminiAnalyzer(AnalysisProvider):
    name = "gemini"

    def cache_identity(self) -> Dict[str, str]:
        return {"model": settings.gemini_model, "prompt_version": VIDEO_ANALYSIS_PROMPT_VERSION}

    def readiness(self) -> ProviderReadiness:
        configured = bool(os.getenv("GEMINI_API_KEY"))
        return ProviderReadiness(self.name, configured, "Ready" if configured else "Add GEMINI_API_KEY to .env")

    async def analyze(self, path: Path, file_id: str, purpose: str) -> Dict[str, Any]:
        if not self.readiness().configured:
            raise RuntimeError("GEMINI_API_KEY is not configured")
        return await asyncio.to_thread(self._analyze_sync, path, file_id, purpose)

    async def delete_asset(self, asset_id: str) -> None:
        if not self.readiness().configured:
            raise RuntimeError("GEMINI_API_KEY is not configured")
        client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
        await asyncio.to_thread(client.files.delete, name=asset_id)

    def _analyze_sync(self, path: Path, file_id: str, purpose: str) -> Dict[str, Any]:
        client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
        uploaded = client.files.upload(file=str(path))
        try:
            for _ in range(240):
                state = getattr(getattr(uploaded, "state", None), "name", None)
                if state == "ACTIVE":
                    break
                if state == "FAILED":
                    raise RuntimeError("Gemini failed to process %s" % path.name)
                import time
                time.sleep(5)
                uploaded = client.files.get(name=uploaded.name)
            else:
                raise TimeoutError("Gemini file processing timed out for %s" % path.name)
            response = client.models.generate_content(
                model=settings.gemini_model,
                contents=[uploaded, VIDEO_ANALYSIS_PROMPT.format(purpose=purpose)],
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_json_schema=VIDEO_ANALYSIS_JSON_SCHEMA,
                ),
            )
            if not response.text:
                raise RuntimeError("Gemini returned no analysis for %s" % path.name)
            analysis = json.loads(response.text)
            usage = getattr(response, "usage_metadata", None)
            return {
                "schema_version": "1.0", "file_id": file_id,
                "provider": self.name, "model": settings.gemini_model,
                "prompt_version": VIDEO_ANALYSIS_PROMPT_VERSION,
                "remote_asset": {"id": uploaded.name, "uri": uploaded.uri, "status": "ready", "retained": True},
                "usage": usage.model_dump(mode="json") if usage and hasattr(usage, "model_dump") else {},
                "provider_response": {"text": response.text},
                "analysis": analysis,
            }
        except Exception:
            try:
                client.files.delete(name=uploaded.name)
            except Exception:
                pass
            raise
