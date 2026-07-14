import json

import httpx
import respx
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tests.helpers import register_user


@respx.mock
async def test_generation_history_streaming_and_soft_delete(
    client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
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

    audio_route = respx.get("http://s3.test/music/example.mp3").mock(
        return_value=httpx.Response(
            206,
            content=b"audio-bytes",
            headers={
                "Content-Type": "audio/mpeg",
                "Content-Range": "bytes 0-10/11",
                "Accept-Ranges": "bytes",
            },
        )
    )
    audio = await client.get(generation["audio_url"], headers={**headers, "Range": "bytes=0-10"})
    assert audio.status_code == 206
    assert audio.content == b"audio-bytes"
    assert audio.headers["content-range"] == "bytes 0-10/11"
    assert audio_route.calls.last.request.headers["range"] == "bytes=0-10"

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
