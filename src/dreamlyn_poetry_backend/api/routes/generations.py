import logging
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime

from botocore.exceptions import BotoCoreError, ClientError, ConnectTimeoutError, ReadTimeoutError
from fastapi import APIRouter, Header, Query, Request, status
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select
from starlette.background import BackgroundTask

from dreamlyn_poetry_backend.api.dependencies import CurrentUser, SessionDep, SettingsDep
from dreamlyn_poetry_backend.api.schemas import GenerationCreateRequest, GenerationPage, GenerationResponse
from dreamlyn_poetry_backend.core.errors import AppError
from dreamlyn_poetry_backend.db.models import Generation, GenerationStatus
from dreamlyn_poetry_backend.services.generation import GenerationService
from dreamlyn_poetry_backend.services.storage import open_storage_stream

router = APIRouter(prefix="/generations", tags=["generations"])
logger = logging.getLogger(__name__)


def serialize_generation(generation: Generation) -> GenerationResponse:
    response = GenerationResponse.model_validate(generation)
    if generation.status == GenerationStatus.completed:
        response.audio_url = f"/api/v1/generations/{generation.id}/audio"
    return response


async def owned_generation(session: SessionDep, user: CurrentUser, generation_id: uuid.UUID) -> Generation:
    generation = await session.scalar(
        select(Generation).where(
            Generation.id == generation_id,
            Generation.user_id == user.id,
            Generation.deleted_at.is_(None),
        )
    )
    if generation is None:
        raise AppError("generation_not_found", "The generation was not found.", status_code=404)
    return generation


@router.post("", response_model=GenerationResponse, status_code=201, operation_id="createGeneration")
async def create_generation(
    payload: GenerationCreateRequest, user: CurrentUser, session: SessionDep, settings: SettingsDep
) -> GenerationResponse:
    generation = await GenerationService(session, settings).generate(user, payload)
    return serialize_generation(generation)


@router.get("", response_model=GenerationPage, operation_id="listGenerations")
async def list_generations(
    user: CurrentUser,
    session: SessionDep,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> GenerationPage:
    filters = (Generation.user_id == user.id, Generation.deleted_at.is_(None))
    total = await session.scalar(select(func.count()).select_from(Generation).where(*filters))
    rows = await session.scalars(
        select(Generation).where(*filters).order_by(Generation.created_at.desc()).limit(limit).offset(offset)
    )
    return GenerationPage(
        items=[serialize_generation(row) for row in rows], total=total or 0, limit=limit, offset=offset
    )


@router.get("/{generation_id}", response_model=GenerationResponse, operation_id="getGeneration")
async def get_generation(
    generation_id: uuid.UUID, user: CurrentUser, session: SessionDep
) -> GenerationResponse:
    return serialize_generation(await owned_generation(session, user, generation_id))


@router.delete("/{generation_id}", status_code=status.HTTP_204_NO_CONTENT, operation_id="deleteGeneration")
async def delete_generation(generation_id: uuid.UUID, user: CurrentUser, session: SessionDep) -> None:
    generation = await owned_generation(session, user, generation_id)
    generation.deleted_at = datetime.now(UTC)
    await session.commit()


@router.get(
    "/{generation_id}/audio",
    operation_id="downloadGenerationAudio",
    response_class=StreamingResponse,
    responses={
        200: {
            "content": {
                "audio/wav": {"schema": {"type": "string", "format": "binary"}},
                "audio/mpeg": {"schema": {"type": "string", "format": "binary"}},
            },
            "description": "Complete audio file.",
        },
        206: {
            "content": {
                "audio/wav": {"schema": {"type": "string", "format": "binary"}},
                "audio/mpeg": {"schema": {"type": "string", "format": "binary"}},
            },
            "description": "Requested byte range.",
        },
    },
)
async def download_audio(
    generation_id: uuid.UUID,
    request: Request,
    user: CurrentUser,
    session: SessionDep,
    settings: SettingsDep,
    range_header: str | None = Header(default=None, alias="Range"),
) -> StreamingResponse:
    generation = await owned_generation(session, user, generation_id)
    if generation.status != GenerationStatus.completed or not generation.storage_key:
        raise AppError("audio_unavailable", "Audio is not available for this generation.", status_code=409)

    try:
        upstream = await open_storage_stream(settings, generation.storage_key, range_header)
    except (ConnectTimeoutError, ReadTimeoutError) as exc:
        raise AppError("audio_timeout", "The audio storage request timed out.", status_code=504) from exc
    except ClientError as exc:
        storage_status = exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
        logger.warning(
            "S3 audio read failed generation_id=%s storage_key=%s status=%s",
            generation.id,
            generation.storage_key,
            storage_status,
        )
        code = 404 if storage_status == 404 else 502
        raise AppError(
            "audio_storage_error", "Audio could not be read from storage.", status_code=code
        ) from exc
    except BotoCoreError as exc:
        raise AppError("audio_storage_unavailable", "Audio storage is unavailable.", status_code=503) from exc
    if upstream.status_code not in {200, 206}:
        await upstream.close()
        code = 404 if upstream.status_code == 404 else 502
        raise AppError("audio_storage_error", "Audio could not be read from storage.", status_code=code)

    async def body() -> AsyncIterator[bytes]:
        try:
            async for chunk in upstream.iter_bytes():
                yield chunk
        finally:
            await upstream.close()

    async def close_stream() -> None:
        await upstream.close()

    response_headers = {
        name: value
        for name in ("content-length", "content-range", "accept-ranges", "etag", "last-modified")
        if (value := upstream.headers.get(name)) is not None
    }
    response_headers["Content-Disposition"] = (
        f'inline; filename="{generation.id}.{generation.audio_format.value}"'
    )
    return StreamingResponse(
        body(),
        status_code=upstream.status_code,
        media_type=upstream.headers.get(
            "content-type", generation.content_type or "application/octet-stream"
        ),
        headers=response_headers,
        background=BackgroundTask(close_stream),
    )
