import io
from typing import Any

import pytest

from dreamlyn_poetry_backend.core.config import Settings
from dreamlyn_poetry_backend.services import storage


class FakeS3Client:
    def __init__(self) -> None:
        self.parameters: dict[str, Any] | None = None
        self.closed = False

    def get_object(self, **parameters: Any) -> dict[str, Any]:
        self.parameters = parameters
        return {
            "ResponseMetadata": {
                "HTTPStatusCode": 206,
                "HTTPHeaders": {
                    "Content-Type": "audio/mpeg",
                    "Content-Range": "bytes 0-2/3",
                },
            },
            "Body": io.BytesIO(b"abc"),
        }

    def close(self) -> None:
        self.closed = True


@pytest.mark.asyncio
async def test_storage_uses_bucket_key_credentials_and_range(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_client = FakeS3Client()
    client_arguments: dict[str, Any] = {}

    def fake_boto_client(service: str, **arguments: Any) -> FakeS3Client:
        client_arguments.update(service=service, **arguments)
        return fake_client

    monkeypatch.setattr(storage.boto3, "client", fake_boto_client)
    result = await storage.open_storage_stream(settings, "music/example.mp3", "bytes=0-2")

    assert fake_client.parameters == {
        "Bucket": "dreamlyn-music",
        "Key": "music/example.mp3",
        "Range": "bytes=0-2",
    }
    assert client_arguments["service"] == "s3"
    assert client_arguments["aws_access_key_id"] == "test-read-access-key"
    assert client_arguments["aws_secret_access_key"] == "test-read-secret-key"
    assert client_arguments["config"].s3["addressing_style"] == "path"
    assert result.headers == {
        "content-type": "audio/mpeg",
        "content-range": "bytes 0-2/3",
    }
    assert b"".join([chunk async for chunk in result.iter_bytes()]) == b"abc"
    await result.close()
    assert fake_client.closed
