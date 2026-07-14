import io
import json

import httpx
import pytest
import respx
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from dreamlyn_poetry_backend.api.routes import generations as generation_routes
from dreamlyn_poetry_backend.core.config import Settings
from dreamlyn_poetry_backend.services.storage import StorageStream
from tests.helpers import register_user


class FakeS3Client:
    def close(self) -> None:
        pass


@respx.mock
async def test_generation_history_streaming_and_soft_delete(
    client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    auth, _ = await register_user(client, session_factory)
    headers = {"Authorization": f"Bearer {auth['access_token']}"}

    device = {
        "type": "music_generation",
        "url": "http://s3.test/music/example.mp3",
        "storage_key": "music/example.mp3",
        "format": "mp3",
    }
    upstream = respx.post("http://litellm.test/v1/chat/completions").mock(
        return_value=httpx.Response(
            200,
            json={"choices": [{"message": {"content": json.dumps(device)}}]},
        )
    )
    created = await client.post(
        "/api/v1/generations",
        json={
            "prompt": "Ambient piano",
            "duration_seconds": 10,
            "audio_format": "mp3",
            "seed": 7,
        },
        headers=headers,
    )
    assert created.status_code == 201, created.text
    generation = created.json()
    assert generation["status"] == "completed"
    assert generation["audio_url"].endswith("/audio")
    assert upstream.calls.last.request.headers["authorization"] == "Bearer sk-partner-test"
    sent = json.loads(upstream.calls.last.request.content)
    assert sent["model"] == "timur"
    assert sent["extra_body"]["output_mode"] == "device"

    storage_request: dict[str, str | None] = {}

    async def fake_open_storage_stream(
        settings: Settings, storage_key: str, range_header: str | None
    ) -> StorageStream:
        storage_request.update(storage_key=storage_key, range_header=range_header)
        return StorageStream(
            status_code=206,
            body=io.BytesIO(b"audio-bytes"),
            client=FakeS3Client(),
            headers={
                "content-type": "audio/mpeg",
                "content-range": "bytes 0-10/11",
                "accept-ranges": "bytes",
            },
        )

    monkeypatch.setattr(generation_routes, "open_storage_stream", fake_open_storage_stream)
    audio = await client.get(generation["audio_url"], headers={**headers, "Range": "bytes=0-10"})
    assert audio.status_code == 206
    assert audio.content == b"audio-bytes"
    assert audio.headers["content-range"] == "bytes 0-10/11"
    assert storage_request == {
        "storage_key": "music/example.mp3",
        "range_header": "bytes=0-10",
    }

    history = await client.get("/api/v1/generations", headers=headers)
    assert history.json()["total"] == 1

    deleted = await client.delete(f"/api/v1/generations/{generation['id']}", headers=headers)
    assert deleted.status_code == 204
    missing = await client.get(generation["audio_url"], headers=headers)
    assert missing.status_code == 404


@respx.mock
async def test_failed_generation_is_persisted(
    client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    auth, _ = await register_user(client, session_factory)
    headers = {"Authorization": f"Bearer {auth['access_token']}"}
    respx.post("http://litellm.test/v1/chat/completions").mock(return_value=httpx.Response(503))

    failed = await client.post(
        "/api/v1/generations",
        json={"prompt": "Failure case", "duration_seconds": 5, "audio_format": "wav"},
        headers=headers,
    )
    assert failed.status_code == 502
    assert failed.json()["code"] == "generation_upstream_error"
    history = await client.get("/api/v1/generations", headers=headers)
    assert history.json()["items"][0]["status"] == "failed"
