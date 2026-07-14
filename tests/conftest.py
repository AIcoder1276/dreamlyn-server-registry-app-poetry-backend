from collections.abc import AsyncIterator
from typing import cast

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool
from starlette.routing import Mount

from dreamlyn_poetry_backend.app import create_app
from dreamlyn_poetry_backend.core.config import Settings, get_settings
from dreamlyn_poetry_backend.db import Base
from dreamlyn_poetry_backend.db.session import get_session


@pytest.fixture
def settings() -> Settings:
    return Settings(
        database_url="sqlite+aiosqlite://",
        jwt_secret="test-secret-that-is-long-enough-for-tests",
        refresh_cookie_secure=False,
        admin_docs_username="admin",
        admin_docs_password="admin-password",
        litellm_base_url="http://litellm.test",
        cors_allowed_origins=["http://frontend.test"],
        s3_endpoint_url="http://s3.test",
        s3_access_key="test-read-access-key",
        s3_secret_key="test-read-secret-key",
    )


@pytest_asyncio.fixture
async def session_factory(settings: Settings) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = create_async_engine(settings.database_url, poolclass=StaticPool)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    yield factory
    await engine.dispose()


@pytest_asyncio.fixture
async def client(
    settings: Settings, session_factory: async_sessionmaker[AsyncSession]
) -> AsyncIterator[httpx.AsyncClient]:
    app = create_app(settings)

    async def test_session() -> AsyncIterator[AsyncSession]:
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_session] = test_session
    app.dependency_overrides[get_settings] = lambda: settings
    admin_mount = next(route for route in app.routes if isinstance(route, Mount) and route.path == "/admin")
    admin_app = cast(FastAPI, admin_mount.app)
    admin_app.dependency_overrides[get_session] = test_session
    admin_app.dependency_overrides[get_settings] = lambda: settings
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://backend.test"
    ) as test_client:
        yield test_client
