import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any, cast

import boto3
from botocore.config import Config

from dreamlyn_poetry_backend.core.config import Settings

CHUNK_SIZE = 64 * 1024


@dataclass(slots=True)
class StorageStream:
    status_code: int
    headers: dict[str, str]
    body: Any
    client: Any
    _closed: bool = field(default=False, init=False)

    async def iter_bytes(self) -> AsyncIterator[bytes]:
        while chunk := await asyncio.to_thread(self.body.read, CHUNK_SIZE):
            yield cast(bytes, chunk)

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        await asyncio.to_thread(self.body.close)
        await asyncio.to_thread(self.client.close)


def _open_storage_stream(
    settings: Settings, storage_key: str, range_header: str | None
) -> StorageStream:
    timeout = settings.s3_download_timeout_seconds
    client: Any = boto3.client(
        "s3",
        endpoint_url=str(settings.s3_endpoint_url),
        aws_access_key_id=settings.s3_access_key.get_secret_value(),
        aws_secret_access_key=settings.s3_secret_key.get_secret_value(),
        region_name=settings.s3_region_name,
        config=Config(
            signature_version="s3v4",
            connect_timeout=timeout,
            read_timeout=timeout,
            retries={"max_attempts": 2, "mode": "standard"},
            s3={"addressing_style": "path"},
        ),
    )
    parameters: dict[str, Any] = {"Bucket": settings.s3_bucket, "Key": storage_key}
    if range_header:
        parameters["Range"] = range_header
    try:
        response: dict[str, Any] = client.get_object(**parameters)
    except Exception:
        client.close()
        raise

    metadata = cast(dict[str, Any], response["ResponseMetadata"])
    response_headers = cast(dict[str, Any], metadata["HTTPHeaders"])
    return StorageStream(
        status_code=cast(int, metadata["HTTPStatusCode"]),
        headers={str(name).lower(): str(value) for name, value in response_headers.items()},
        body=response["Body"],
        client=client,
    )


async def open_storage_stream(
    settings: Settings, storage_key: str, range_header: str | None
) -> StorageStream:
    return await asyncio.to_thread(_open_storage_stream, settings, storage_key, range_header)
