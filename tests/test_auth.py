import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from dreamlyn_poetry_backend.db.models import User
from tests.helpers import register_user


async def test_registration_consumes_invite_and_auth_flow(
    client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    auth, invite_code = await register_user(client, session_factory, email="Partner@Example.com")
    assert auth["token_type"] == "bearer"
    assert auth["user"]["email"] == "partner@example.com"
    assert "poetry_refresh_token" in client.cookies

    duplicate = await client.post(
        "/api/v1/auth/register",
        json={
            "email": "other@example.com",
            "display_name": "Other",
            "password": "another-long-password",
            "invite_code": str(invite_code),
        },
    )
    assert duplicate.status_code == 409
    assert duplicate.json()["code"] == "invite_unavailable"

    headers = {"Authorization": f"Bearer {auth['access_token']}"}
    profile = await client.get("/api/v1/users/me", headers=headers)
    assert profile.status_code == 200
    assert profile.json()["display_name"] == "Partner Studio"

    refreshed = await client.post("/api/v1/auth/refresh")
    assert refreshed.status_code == 200
    assert refreshed.json()["access_token"] != auth["access_token"]

    logout = await client.post("/api/v1/auth/logout")
    assert logout.status_code == 204
    assert "poetry_refresh_token" not in client.cookies


async def test_blocked_user_is_rejected_immediately(
    client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    auth, _ = await register_user(client, session_factory)
    async with session_factory() as session:
        user = await session.scalar(select(User).where(User.email == "partner@example.com"))
        assert user is not None
        user.is_blocked = True
        await session.commit()

    response = await client.get(
        "/api/v1/users/me", headers={"Authorization": f"Bearer {auth['access_token']}"}
    )
    assert response.status_code == 403
    assert response.json()["code"] == "user_blocked"


async def test_change_password_invalidates_current_access(
    client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    auth, _ = await register_user(client, session_factory)
    headers = {"Authorization": f"Bearer {auth['access_token']}"}
    changed = await client.post(
        "/api/v1/auth/change-password",
        json={"current_password": "long-enough-password", "new_password": "a-new-long-password"},
        headers=headers,
    )
    assert changed.status_code == 204
    invalidated = await client.get("/api/v1/users/me", headers=headers)
    assert invalidated.status_code == 401

    old_login = await client.post(
        "/api/v1/auth/login",
        json={"email": "partner@example.com", "password": "long-enough-password"},
    )
    assert old_login.status_code == 401
    new_login = await client.post(
        "/api/v1/auth/login",
        json={"email": "partner@example.com", "password": "a-new-long-password"},
    )
    assert new_login.status_code == 200
