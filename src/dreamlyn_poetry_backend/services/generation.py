import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from dreamlyn_poetry_backend.api.schemas import GenerationCreateRequest
from dreamlyn_poetry_backend.core.config import Settings
from dreamlyn_poetry_backend.core.errors import AppError
from dreamlyn_poetry_backend.db.models import Generation, GenerationStatus, User


@dataclass(frozen=True)
class UpstreamResult:
    url: str
    storage_key: str
    content_type: str


class GenerationService:
    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self.session = session
        self.settings = settings

    async def generate(self, user: User, request: GenerationCreateRequest) -> Generation:
        if (
            not self.settings.generation_min_duration_seconds
            <= request.duration_seconds
            <= self.settings.generation_max_duration_seconds
        ):
            raise AppError(
                "invalid_duration",
                "duration_seconds is outside the configured range.",
                details={
                    "minimum": self.settings.generation_min_duration_seconds,
                    "maximum": self.settings.generation_max_duration_seconds,
                },
            )
        if len(request.prompt) > self.settings.generation_max_prompt_length:
            raise AppError("prompt_too_long", "The prompt exceeds the configured maximum length.")
        if user.invite is None:
            raise AppError(
                "api_key_unavailable", "No model API key is assigned to this user.", status_code=503
            )

        generation = Generation(
            user_id=user.id,
            prompt=request.prompt,
            duration_seconds=request.duration_seconds,
            audio_format=request.audio_format,
            seed=request.seed,
            status=GenerationStatus.pending,
            upstream_model=self.settings.litellm_model,
        )
        self.session.add(generation)
        await self.session.commit()
        await self.session.refresh(generation)

        try:
            result = await self._call_litellm(request, user.invite.api_key)
        except AppError as exc:
            generation.status = GenerationStatus.failed
            generation.error_code = exc.code
            generation.error_message = exc.message
            generation.completed_at = datetime.now(UTC)
            await self.session.commit()
            raise

        generation.status = GenerationStatus.completed
        generation.storage_url = result.url
        generation.storage_key = result.storage_key
        generation.content_type = result.content_type
        generation.completed_at = datetime.now(UTC)
        await self.session.commit()
        await self.session.refresh(generation)
        return generation

    async def _call_litellm(self, request: GenerationCreateRequest, api_key: str) -> UpstreamResult:
        payload: dict[str, Any] = {
            "model": self.settings.litellm_model,
            "messages": [{"role": "user", "content": request.prompt}],
            "stream": False,
            "extra_body": {
                "output_mode": "device",
                "duration_seconds": request.duration_seconds,
                "audio_format": request.audio_format.value,
            },
        }
        if request.seed is not None:
            payload["extra_body"]["seed"] = request.seed
        try:
            async with httpx.AsyncClient(timeout=self.settings.generation_timeout_seconds) as client:
                response = await client.post(
                    f"{str(self.settings.litellm_base_url).rstrip('/')}/v1/chat/completions",
                    json=payload,
                    headers={"Authorization": f"Bearer {api_key}"},
                )
            response.raise_for_status()
        except httpx.TimeoutException as exc:
            raise AppError(
                "generation_timeout", "The music generation request timed out.", status_code=504
            ) from exc
        except httpx.HTTPStatusError as exc:
            raise AppError(
                "generation_upstream_error",
                "The music generation service rejected the request.",
                status_code=502,
            ) from exc
        except httpx.HTTPError as exc:
            raise AppError(
                "generation_unavailable", "The music generation service is unavailable.", status_code=503
            ) from exc

        try:
            body = response.json()
            content = body["choices"][0]["message"]["content"]
            device = json.loads(content) if isinstance(content, str) else content
            url = str(device["url"])
            storage_key = str(device["storage_key"])
            audio_format = str(device["format"])
        except (ValueError, TypeError, KeyError, IndexError) as exc:
            raise AppError(
                "invalid_upstream_response",
                "The music service returned an invalid response.",
                status_code=502,
            ) from exc
        content_type = "audio/mpeg" if audio_format == "mp3" else "audio/wav"
        return UpstreamResult(url=url, storage_key=storage_key, content_type=content_type)
